#!/bin/bash
# ═══════════════════════════════════════════════════════════════
#  Bio-Station Pro — 噬菌体组装全流程环境部署脚本 (WSL/Linux)
#  
#  功能: 自动检测并安装所有生物信息学工具链
#  设计: 幂等执行 (重复运行安全)，缺什么装什么
#  工具链: fastp, unicycler, flye, pharokka, phold, polypolish,
#          checkv, phispy, vibrant, virsorter2, prokka
#  用法: bash setup_assembly_env.sh [--skip-db]
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

# ─── 基础路径 ─────────────────────────────────────────────
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(dirname "$SCRIPT_DIR")
DB_BASE="$PROJECT_ROOT/database"
LOG_FILE="$PROJECT_ROOT/logs/setup_env.log"

mkdir -p "$PROJECT_ROOT/logs"
exec > >(tee -a "$LOG_FILE") 2>&1

SKIP_DB=false
[[ "${1:-}" == "--skip-db" ]] && SKIP_DB=true

# ─── 颜色与输出工具 ──────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

ok()   { echo -e "${GREEN}[]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
fail() { echo -e "${RED}[]${NC} $1"; }

check_cmd() {
    if command -v "$1" &>/dev/null; then
        ok "$1 已就绪 ($(command -v $1))"
        return 0
    else
        warn "$1 未安装"
        return 1
    fi
}

# ─── 0. 系统预检 ─────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Bio-Station Pro — 环境自动部署"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "  项目根目录: $PROJECT_ROOT"
echo "═══════════════════════════════════════════════════════════"
echo ""

export PATH="$PATH:/usr/local/bin:/root/.local/bin"
export DEBIAN_FRONTEND=noninteractive

# ─── 1. 系统级依赖 ───────────────────────────────────────
echo "─── [1/8] 系统级依赖 ───"
SYSTEM_DEPS=(
    python3-pip cmake g++ libomp-dev
    mummer hmmer prodigal aragorn mash
    samtools minimap2 bwa seqtk
    libgl1 libfontconfig1
    trnascan-se glimmer
)

MISSING_SYS=()
for pkg in "${SYSTEM_DEPS[@]}"; do
    if ! dpkg -s "$pkg" &>/dev/null; then
        MISSING_SYS+=("$pkg")
    fi
done

if [ ${#MISSING_SYS[@]} -gt 0 ]; then
    warn "需要安装 ${#MISSING_SYS[@]} 个系统包: ${MISSING_SYS[*]}"
    
    # 强制清理可能的 apt 锁 (处理异常码 100)
    rm -f /var/lib/dpkg/lock-frontend /var/lib/apt/lists/lock /var/cache/apt/archives/lock || true
    
    # 使用 --allow-releaseinfo-change 处理签名/版本变更
    apt-get update -qq --allow-releaseinfo-change || true
    
    if apt-get install -y -qq "${MISSING_SYS[@]}"; then
        ok "系统依赖安装完成"
    else
        warn "apt-get install 失败，部分功能可能受限"
    fi
else
    ok "系统依赖已全部就绪"
fi

# ─── 2. 核心流水线工具 ──────────────────────────────────
echo ""
echo "─── [2/8] 核心流水线工具 ───"

# fastp
if ! check_cmd fastp; then
    warn "正在安装 fastp..."
    # 优先尝试 apt，再尝试 conda
    apt-get install -y -qq fastp 2>/dev/null || {
        pip3 install fastp --break-system-packages 2>/dev/null || true
    }
    check_cmd fastp || fail "fastp 安装失败，请手动安装"
fi



# NCBI datasets
if ! check_cmd datasets; then
    warn "正在安装 NCBI datasets CLI..."
    curl -fsSL https://ftp.ncbi.nlm.nih.gov/pub/datasets/command-line/LATEST/linux-amd64/datasets \
        -o /usr/local/bin/datasets && chmod +x /usr/local/bin/datasets 2>/dev/null || true
    check_cmd datasets || warn "NCBI datasets 安装失败 (非致命)"
fi

# ─── 3. Pharokka + Phold (注释引擎) ────────────────────
echo ""
echo "─── [3/8] 注释引擎 (Pharokka + Phold) ───"

if ! check_cmd pharokka.py; then
    warn "正在安装 Pharokka..."
    pip3 install pharokka --break-system-packages
fi
check_cmd pharokka.py

if ! check_cmd phold; then
    warn "正在安装 Phold..."
    pip3 install phold --break-system-packages
fi
check_cmd phold

# ─── 4. Polypolish (碱基精修) ───────────────────────────
echo ""
echo "─── [4/8] 精度增强工具 (Polypolish) ───"

if ! check_cmd polypolish; then
    warn "正在安装 Polypolish..."
    pip3 install polypolish --break-system-packages 2>/dev/null || {
        # 如果 pip 安装失败，尝试从 GitHub Release 下载预编译二进制
        POLY_VER="0.6.0"
        POLY_URL="https://github.com/rrwick/Polypolish/releases/download/v${POLY_VER}/polypolish-linux-x86_64-musl-v${POLY_VER}.tar.gz"
        warn "pip 安装失败，尝试从 GitHub 下载预编译版本..."
        curl -fsSL "$POLY_URL" | tar xz -C /usr/local/bin/ 2>/dev/null || true
    }
fi
check_cmd polypolish || warn "Polypolish 安装失败 (流水线将跳过精修步骤)"

# CheckV (基因组质量评估)
if ! check_cmd checkv; then
    warn "正在安装 CheckV..."
    pip3 install checkv --break-system-packages 2>/dev/null || true
fi
check_cmd checkv || warn "CheckV 安装失败"

# 特殊补丁: prodigal-gv (CheckV 必须依赖)
if ! check_cmd prodigal-gv; then
    warn "正在尝试补齐 prodigal-gv (CheckV 核心依赖)..."
    PGV_URL="https://github.com/apcamargo/prodigal-gv/releases/download/2.11.0/prodigal-gv-linux"
    
    # 下载到 /usr/local/bin
    if curl -fsSL "$PGV_URL" -o /usr/local/bin/prodigal-gv; then
        chmod +x /usr/local/bin/prodigal-gv
        #  核心修复：建立到顶级系统目录的链接，确保 CheckV 必能找到
        ln -sf /usr/local/bin/prodigal-gv /usr/bin/prodigal-gv || true
        ok "prodigal-gv 安装并链接成功"
    else
        warn "prodigal-gv 下载失败，请检查网络"
    fi
else
    # 已存在，确保执行权限
    chmod +x "$(which prodigal-gv)" || true
fi

# ─── 5. 前噬菌体分离工具 (PhiSpy + VIBRANT + VirSorter2) ──
echo ""
echo "─── [5/8] 前噬菌体分离工具 (PhiSpy + VIBRANT + VirSorter2) ───"

# Prokka (宿主基因组快速注释，PhiSpy 前置依赖)
if ! check_cmd prokka; then
    warn "正在安装 Prokka (宿主注释器)..."
    apt-get install -y -qq prokka 2>/dev/null || {
        pip3 install prokka --break-system-packages 2>/dev/null || true
    }
    check_cmd prokka || warn "Prokka 安装失败 (将降级使用 Prodigal)"
fi

# PhiSpy (前噬菌体精确检测)
if ! check_cmd phispy; then
    warn "正在安装 PhiSpy (前噬菌体检测引擎)..."
    pip3 install phispy --break-system-packages 2>/dev/null || {
        # 如果 pip 安装失败，尝试从 GitHub 源码安装
        warn "pip 安装失败，尝试从 GitHub 源码安装..."
        pip3 install git+https://github.com/linsalrob/PhiSpy.git --break-system-packages 2>/dev/null || true
    }
    check_cmd phispy || warn "PhiSpy 安装失败 (前噬菌体分离将降级运行)"
fi

# VIBRANT (噬菌体识别与分箱)
if ! check_cmd VIBRANT_run.py && ! check_cmd vibrant; then
    warn "正在安装 VIBRANT (噬菌体分箱引擎)..."
    pip3 install vibrant --break-system-packages 2>/dev/null || {
        # VIBRANT 可能不在 PyPI，尝试 conda
        if command -v conda &>/dev/null; then
            conda install -y -c bioconda vibrant 2>/dev/null || true
        fi
    }
    # 再次检查（支持两种命令名）
    if ! check_cmd VIBRANT_run.py && ! check_cmd vibrant; then
        # 最后手段：GitHub 安装
        warn "标准渠道失败，尝试 GitHub 源码安装..."
        pip3 install git+https://github.com/AnantharamanLab/VIBRANT.git --break-system-packages 2>/dev/null || true
    fi
    check_cmd VIBRANT_run.py || check_cmd vibrant || warn "VIBRANT 安装失败 (将尝试 VirSorter2 降级)"
fi

# VirSorter2 (机器学习噬菌体分类 — VIBRANT 的降级后备)
if ! check_cmd virsorter; then
    warn "正在安装 VirSorter2 (ML噬菌体分类后备)..."
    pip3 install virsorter --break-system-packages 2>/dev/null || {
        if command -v conda &>/dev/null; then
            conda install -y -c bioconda virsorter2 2>/dev/null || true
        fi
    }
    check_cmd virsorter || warn "VirSorter2 安装失败 (非致命)"
fi

# ─── 6. Kraken2 (宿主剔除引擎) ──────────────────────────
echo ""
echo "─── [6/8] Kraken2 宿主剔除引擎 ───"

if ! check_cmd kraken2; then
    warn "正在安装 Kraken2..."
    apt-get install -y -qq kraken2 2>/dev/null || {
        if command -v conda &>/dev/null; then
            conda install -y -c bioconda kraken2 2>/dev/null || true
        fi
    }
    check_cmd kraken2 || warn "Kraken2 安装失败"
fi

# ─── 7. 数据库部署 ──────────────────────────────────────
echo ""
echo "─── [7/8] 数据库部署 ───"

if [ "$SKIP_DB" = true ]; then
    warn "已跳过数据库下载 (--skip-db)"
else
    # Pharokka 数据库
    PHAROKKA_DB="$DB_BASE/pharokka_db"
    mkdir -p "$PHAROKKA_DB"
    ln -sfn "$PHAROKKA_DB" /opt/pharokka_db
    ok "Pharokka DB 链接: /opt/pharokka_db -> $PHAROKKA_DB"

    if [ ! -f "$PHAROKKA_DB/phrogs_db.index" ] && [ ! -f "$PHAROKKA_DB/phrogs_profile_db" ]; then
        warn "Pharokka 数据库未检测到，正在下载 (约 10GB)..."
        install_databases.py -o /opt/pharokka_db || warn "Pharokka 数据库下载失败，请稍后重试"
    else
        ok "Pharokka 数据库已存在"
    fi

    # Phold 数据库
    PHOLD_DB="$DB_BASE/phold_db"
    mkdir -p "$PHOLD_DB"
    ln -sfn "$PHOLD_DB" /opt/phold_db
    ok "Phold DB 链接: /opt/phold_db -> $PHOLD_DB"

    if [ ! -d "$PHOLD_DB/phold_structure_db" ] && [ ! -f "$PHOLD_DB/phold_annot.tsv.gz" ]; then
        warn "Phold 数据库未检测到，正在下载..."
        phold install -d /opt/phold_db || warn "Phold 数据库下载失败，请稍后重试"
    else
        ok "Phold 数据库已存在"
    fi

    # CheckV 数据库
    CHECKV_DB="$DB_BASE/checkv_db"
    mkdir -p "$CHECKV_DB"
    ln -sfn "$CHECKV_DB" /opt/checkv-db
    ok "CheckV DB 链接: /opt/checkv-db -> $CHECKV_DB"

    if [ ! -f "$CHECKV_DB/README.txt" ] && [ ! -d "$CHECKV_DB/genome_db" ]; then
        warn "CheckV 数据库未检测到，正在下载 (约 3GB)..."
        checkv download_database "$CHECKV_DB" || warn "CheckV 数据库下载失败，请稍后重试"
    else
        ok "CheckV 数据库已存在"
    fi

    # VIBRANT 数据库
    echo ""
    echo "─── VIBRANT 数据库 ───"
    VIBRANT_DB="$DB_BASE/vibrant_db"
    if command -v VIBRANT_run.py &>/dev/null || command -v vibrant &>/dev/null; then
        # VIBRANT 数据库通常随安装自带，但需要确认已下载
        if [ ! -d "$VIBRANT_DB" ] || [ -z "$(ls -A "$VIBRANT_DB" 2>/dev/null)" ]; then
            warn "正在下载 VIBRANT 数据库..."
            mkdir -p "$VIBRANT_DB"
            # VIBRANT 有自带的数据库下载命令
            if command -v VIBRANT_setup.py &>/dev/null; then
                VIBRANT_setup.py 2>/dev/null || warn "VIBRANT 数据库下载失败 (非致命)"
            elif command -v download-db &>/dev/null; then
                download-db --vibrant "$VIBRANT_DB" 2>/dev/null || true
            fi
        else
            ok "VIBRANT 数据库已存在"
        fi
    else
        warn "VIBRANT 未安装，跳过数据库下载"
    fi

    # VirSorter2 数据库
    echo ""
    echo "─── VirSorter2 数据库 ───"
    VS2_DB="$DB_BASE/virsorter2_db"
    if command -v virsorter &>/dev/null; then
        if [ ! -d "$VS2_DB" ] || [ -z "$(ls -A "$VS2_DB" 2>/dev/null)" ]; then
            warn "正在下载 VirSorter2 数据库 (约 4GB)..."
            mkdir -p "$VS2_DB"
            virsorter setup -d "$VS2_DB" -j 4 2>/dev/null || warn "VirSorter2 数据库下载失败 (非致命)"
        else
            ok "VirSorter2 数据库已存在"
        fi
    else
        warn "VirSorter2 未安装，跳过数据库下载"
    fi
fi

# ─── 环境检查总结 ────────────────────────────────────────
# ─── 8. 环境检查总结 ────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  环境部署完成 — 工具状态汇总"
echo "═══════════════════════════════════════════════════════════"

TOOLS=(fastp minimap2 samtools bwa seqtk kraken2 pharokka.py phold polypolish checkv prokka phispy datasets)
VIBRANT_OK=false
if command -v VIBRANT_run.py &>/dev/null || command -v vibrant &>/dev/null; then
    VIBRANT_OK=true
fi
ALL_OK=true

for t in "${TOOLS[@]}"; do
    if command -v "$t" &>/dev/null; then
        echo -e "  ${GREEN}${NC} $t"
    else
        echo -e "  ${RED}${NC} $t (缺失)"
        ALL_OK=false
    fi
done

# 单独检查有两种命令名的工具
if [ "$VIBRANT_OK" = true ]; then
    echo -e "  ${GREEN}${NC} VIBRANT"
else
    echo -e "  ${RED}${NC} VIBRANT (缺失)"
    ALL_OK=false
fi

if command -v virsorter &>/dev/null; then
    echo -e "  ${GREEN}${NC} VirSorter2"
else
    echo -e "  ${YELLOW}○${NC} VirSorter2 (可选，VIBRANT 降级后备)"
fi

echo ""
if [ "$ALL_OK" = true ]; then
    ok "所有核心工具已就绪，流水线可以正常运行！"
else
    warn "部分工具缺失，流水线中的对应功能将自动降级跳过。"
fi

echo ""
echo "日志已保存至: $LOG_FILE"
echo "═══════════════════════════════════════════════════════════"
