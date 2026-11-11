#!/bin/bash
set -e

# 自动探测项目根路径 (WSL 路径)
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(dirname "$SCRIPT_DIR")
DB_BASE="$PROJECT_ROOT/database/phold_db"

echo "--- 准备部署 Phold 数据库管线 (分发友好版) ---"
echo "项目根目录: $PROJECT_ROOT"

# 1. 建立目录并在 WSL 内部创建符号链接
mkdir -p "$DB_BASE"
ln -sf "$DB_BASE" /opt/phold_db
echo "已建立动态链接: /opt/phold_db -> $DB_BASE"

echo "--- [2/3] 正在通过 Pip 安装 Phold 软件... ---"
# Phold 依赖于一些编译工具，确保它们存在
apt-get install -y cmake g++ libomp-dev
pip3 install phold --break-system-packages

echo "--- [3/3] 正在启动 Phold 结构数据库下载... ---"
echo "提示：Phold 数据库包含大量结构模型数据，体积较大，请耐心等待。"
export PATH=$PATH:/usr/local/bin:/root/.local/bin
# 使用刚才建立的 /opt/phold_db 路径
phold install -d /opt/phold_db
