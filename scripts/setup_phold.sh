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

echo "--- [3/5] 安装 Phold (pip, 自动匹配 GPU/CPU PyTorch 与 ProstT5 依赖) ---"
python3 -m pip install --upgrade pip >/dev/null 2>&1 || true

HAS_WSL_GPU=0
if [ -e /dev/dxg ] || command -v nvidia-smi >/dev/null 2>&1; then
  HAS_WSL_GPU=1
fi

TORCH_CUDA_READY=0
if python3 -c "import torch; assert torch.cuda.is_available(); _ = torch.zeros(1, device='cuda') + 1; print(torch.__version__, torch.cuda.get_device_name(0))" >/dev/null 2>&1; then
  TORCH_CUDA_READY=1
fi

if [ "$HAS_WSL_GPU" -eq 1 ]; then
  if [ "$TORCH_CUDA_READY" -eq 1 ]; then
    echo "  已检测到兼容 CUDA 的 PyTorch，跳过重装:"
    python3 -c "import torch; print('    torch=' + torch.__version__ + ', gpu=' + torch.cuda.get_device_name(0))"
  else
    echo "  检测到 WSL GPU，正在部署 PyTorch CUDA 版 (优先 cu128 以适配 RTX 50xx/40xx/30xx)..."
    python3 -m pip install --break-system-packages --upgrade --force-reinstall torch --index-url https://download.pytorch.org/whl/cu128 2>/dev/null \
      || python3 -m pip install --upgrade --force-reinstall torch --index-url https://download.pytorch.org/whl/cu128 \
      || python3 -m pip install --break-system-packages --upgrade --force-reinstall torch --index-url https://download.pytorch.org/whl/cu124 2>/dev/null \
      || python3 -m pip install --upgrade --force-reinstall torch --index-url https://download.pytorch.org/whl/cu124 \
      || python3 -m pip install --break-system-packages torch --index-url https://download.pytorch.org/whl/cpu 2>/dev/null \
      || python3 -m pip install torch --index-url https://download.pytorch.org/whl/cpu
  fi
else
  if ! python3 -c "import torch" >/dev/null 2>&1; then
    python3 -m pip install --break-system-packages torch --index-url https://download.pytorch.org/whl/cpu 2>/dev/null \
      || python3 -m pip install torch --index-url https://download.pytorch.org/whl/cpu
  fi
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

python3 - << 'PY' 2>/dev/null || true
import torch
cuda_ok = bool(torch.cuda.is_available())
gpu_name = torch.cuda.get_device_name(0) if cuda_ok else "CPU"
kernel_ok = False
if cuda_ok:
    try:
        _ = (torch.zeros(1, device="cuda") + 1).item()
        kernel_ok = True
    except Exception:
        kernel_ok = False
print(f"  [INFO] torch={torch.__version__} cuda_available={cuda_ok} kernel_ok={kernel_ok} device={gpu_name}")
PY

if [ "$missing" -eq 0 ]; then
  echo "[OK] Phold 运行环境就绪"
  exit 0
fi
echo "[WARN] 仍有 $missing 项缺失，请根据上面的 [MISS] 行补齐后重跑"
exit 1
