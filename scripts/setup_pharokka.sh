#!/bin/bash
# Pharokka 运行环境部署（WSL / Ubuntu，复用已下载的 database 库，不重新下载 10GB 数据）
# 用法: wsl -d Ubuntu -u root bash "/mnt/d/NCBI blast/scripts/setup_pharokka.sh"
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

resolve_db() {
  local name="$1"
  local primary="$PROJECT_ROOT/database/$name"
  local legacy="$PROJECT_ROOT/database/database/$name"
  if [ -d "$primary" ] && [ -n "$(ls -A "$primary" 2>/dev/null)" ]; then
    echo "$primary"; return
  fi
  if [ -d "$legacy" ] && [ -n "$(ls -A "$legacy" 2>/dev/null)" ]; then
    echo "$legacy"; return
  fi
  echo "$primary"
}

DB_BASE="$(resolve_db pharokka_db)"
PHOLD_LINK="/opt/pharokka_db"

echo "=============================================================="
echo " Pharokka 部署"
echo " 项目根目录 : $PROJECT_ROOT"
echo " 数据库目录 : $DB_BASE"
export PATH="$PATH:/usr/local/bin:/root/.local/bin"
export DEBIAN_FRONTEND=noninteractive

echo "--- [1/5] 安装系统依赖 (mash/hmmer/prodigal/aragorn/mummer/tRNAscan-SE) ---"
apt-get update -qq || echo "  ! apt-get update 失败，继续尝试安装"
apt-get install -y -qq python3 python3-pip python3-venv mummer hmmer prodigal aragorn mash \
                     trnascan-se ncbi-blast+ wget curl unzip git 2>/dev/null \
  || apt-get install -y python3 python3-pip mummer hmmer prodigal aragorn mash wget curl unzip git

echo "--- [2/5] 安装 MMseqs2 (Pharokka 的 PHROGs 检索内核) ---"
if command -v mmseqs >/dev/null 2>&1; then
  echo "  mmseqs 已安装: $(command -v mmseqs)"
else
  tmp_dir="$(mktemp -d)"
  if wget -q -O "$tmp_dir/mmseqs.tar.gz" \
      "https://github.com/soedinglab/MMseqs2/releases/latest/download/mmseqs-linux-avx2.tar.gz"; then
    tar -xzf "$tmp_dir/mmseqs.tar.gz" -C "$tmp_dir"
    install -m 0755 "$tmp_dir"/mmseqs/bin/* /usr/local/bin/ 2>/dev/null || true
    echo "  mmseqs -> $(command -v mmseqs || echo '未安装')"
  else
    echo "  ! 无法下载 MMseqs2，请手动安装后重跑本脚本"
  fi
  rm -rf "$tmp_dir"
fi

echo "--- [3/5] 安装 Pharokka (pip) ---"
python3 -m pip install --upgrade pip >/dev/null 2>&1 || true
python3 -m pip install --break-system-packages pharokka 2>/dev/null \
  || python3 -m pip install pharokka
hash -r
echo "  pharokka.py -> $(command -v pharokka.py || echo '未找到')"

echo "--- [4/5] 链接数据库 (跳过重复下载) ---"
if [ ! -d "$DB_BASE" ] || [ -z "$(ls -A "$DB_BASE" 2>/dev/null)" ]; then
  echo "  数据库为空，开始官方下载 (约 10GB)..."
  mkdir -p "$DB_BASE"
  if command -v install_databases.py >/dev/null 2>&1; then
    install_databases.py -o "$DB_BASE"
  else
    echo "  ! 未找到 install_databases.py，请检查 pharokka 是否安装成功"
  fi
else
  echo "  已检测到现有数据库，跳过下载:"
  ls -1 "$DB_BASE" | head -n 8 | sed 's/^/    /'
fi
mkdir -p "$DB_BASE"
ln -sfn "$DB_BASE" "$PHOLD_LINK"
echo "  $PHOLD_LINK -> $(readlink -f "$PHOLD_LINK")"

echo "--- [5/5] 自检 ---"
missing=0
for tool in pharokka.py mmseqs mash hmmer prodigal aragorn; do
  if command -v "$tool" >/dev/null 2>&1; then
    printf "  [OK]   %-12s %s\n" "$tool" "$(command -v "$tool")"
  else
    printf "  [MISS] %-12s\n" "$tool"; missing=$((missing + 1))
  fi
done
for f in all_phrogs.h3m phrog_annot_v4.tsv CARD.dbtype vfdb.dbtype; do
  if [ -e "$DB_BASE/$f" ]; then
    printf "  [OK]   db:%-18s\n" "$f"
  else
    printf "  [MISS] db:%-18s\n" "$f"; missing=$((missing + 1))
  fi
done

if [ "$missing" -eq 0 ]; then
  echo "✅ Pharokka 运行环境就绪"
  exit 0
fi
echo "⚠️  仍有 $missing 项缺失，请根据上面的 [MISS] 行补齐后重跑"
exit 1
