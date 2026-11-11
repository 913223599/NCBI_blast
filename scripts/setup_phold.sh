#!/bin/bash
# Phold AI 运行环境部署（WSL / Ubuntu，复用已下载的 phold_db，不重复下载结构库与 ProstT5 权重）
# 用法: wsl -d Ubuntu -u root bash "/mnt/d/NCBI blast/scripts/setup_phold.sh"
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

DB_BASE="$(resolve_db phold_db)"
PHOLD_LINK="/opt/phold_db"

echo "=============================================================="
echo " Phold 部署"
echo " 项目根目录 : $PROJECT_ROOT"
echo " 数据库目录 : $DB_BASE"
export PATH="$PATH:/usr/local/bin:/root/.local/bin"
export DEBIAN_FRONTEND=noninteractive
export HF_HOME="$DB_BASE"

echo "--- [1/5] 安装系统依赖 ---"
apt-get update -qq || echo "  ! apt-get update 失败，继续尝试安装"
apt-get install -y -qq python3 python3-pip python3-venv cmake g++ libomp-dev \
                     wget curl unzip git zlib1g-dev 2>/dev/null \
  || apt-get install -y python3 python3-pip cmake g++ libomp-dev wget curl unzip git

echo "--- [2/5] 安装 Foldseek 10 (3Di 结构检索内核) ---"
if command -v foldseek >/dev/null 2>&1; then
  echo "  foldseek 已安装: $(command -v foldseek)"
else
  tmp_dir="$(mktemp -d)"
  if wget -q -O "$tmp_dir/foldseek.tar.gz" \
      "https://github.com/steineggerlab/foldseek/releases/download/10-941cd33/foldseek-linux-avx2.tar.gz"; then
    tar -xzf "$tmp_dir/foldseek.tar.gz" -C "$tmp_dir"
    install -m 0755 "$tmp_dir"/foldseek/bin/foldseek /usr/local/bin/foldseek 2>/dev/null \
      || find "$tmp_dir" -name foldseek -type f -exec install -m 0755 {} /usr/local/bin/foldseek \;
    echo "  foldseek -> $(command -v foldseek || echo '未安装')"
  else
    echo "  ! 无法下载 Foldseek，请手动安装后重跑本脚本"
  fi
  rm -rf "$tmp_dir"
fi

echo "--- [3/5] 安装 Phold (pip, 含 ProstT5 依赖) ---"
python3 -m pip install --upgrade pip >/dev/null 2>&1 || true
# CPU 版 torch 体积更小、无需 CUDA 版本对齐；如需 GPU 推理，改为 torch==<对应 cu 版本>
if ! python3 -c "import torch" >/dev/null 2>&1; then
  python3 -m pip install --break-system-packages torch --index-url https://download.pytorch.org/whl/cpu 2>/dev/null \
    || python3 -m pip install torch --index-url https://download.pytorch.org/whl/cpu
fi
python3 -m pip install --break-system-packages phold 2>/dev/null || python3 -m pip install phold
hash -r
echo "  phold -> $(command -v phold || echo '未找到')"

echo "--- [4/5] 链接数据库 (跳过重复下载) ---"
if [ ! -d "$DB_BASE" ] || [ -z "$(ls -A "$DB_BASE" 2>/dev/null)" ]; then
  echo "  数据库为空，开始官方下载 (约 15GB)..."
  mkdir -p "$DB_BASE"
  phold install -d "$DB_BASE" || echo "  ! phold install 失败"
else
  echo "  已检测到现有数据库，跳过下载:"
  ls -1 "$DB_BASE" | head -n 8 | sed 's/^/    /'
fi
ln -sfn "$DB_BASE" "$PHOLD_LINK"
echo "  $PHOLD_LINK -> $(readlink -f "$PHOLD_LINK")"

echo "--- [5/5] 自检 ---"
missing=0
for tool in phold foldseek; do
  if command -v "$tool" >/dev/null 2>&1; then
    printf "  [OK]   %-10s %s\n" "$tool" "$(command -v "$tool")"
  else
    printf "  [MISS] %-10s\n" "$tool"; missing=$((missing + 1))
  fi
done
for f in all_phold_structures.index all_phold_structures_ca.index phold_annots.tsv; do
  if [ -e "$DB_BASE/$f" ]; then
    printf "  [OK]   db:%-32s\n" "$f"
  else
    printf "  [MISS] db:%-32s\n" "$f"; missing=$((missing + 1))
  fi
done
if [ -n "$(find "$DB_BASE" -maxdepth 1 -name 'models--Rostlab--ProstT5*' -print -quit 2>/dev/null)" ]; then
  echo "  [OK]   ProstT5 权重已就位 (HF_HOME=$DB_BASE)"
else
  echo "  [MISS] ProstT5 权重"; missing=$((missing + 1))
fi

if [ "$missing" -eq 0 ]; then
  echo "✅ Phold 运行环境就绪"
  exit 0
fi
echo "⚠️  仍有 $missing 项缺失，请根据上面的 [MISS] 行补齐后重跑"
exit 1
