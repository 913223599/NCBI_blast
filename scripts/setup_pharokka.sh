#!/bin/bash
set -e

# 自动探测项目根路径 (WSL 路径)
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(dirname "$SCRIPT_DIR")
DB_BASE="$PROJECT_ROOT/database/pharokka_db"

echo "--- [1/4] 正在更新系统包索引... ---"
apt-get update

echo "--- [2/4] 正在安装生物信息依赖工具 (MUMmer, HMMER, etc.)... ---"
apt-get install -y python3-pip mummer hmmer prodigal aragorn mash

echo "--- [3/4] 正在建立 F 盘外挂传送门... ---"
echo "--- 准备部署 Pharokka 数据库管线 (分发友好版) ---"
echo "项目根目录: $PROJECT_ROOT"

# 1. 映射 F 盘数据库目录到 WSL 内部路径
mkdir -p "$DB_BASE"
ln -sf "$DB_BASE" /opt/pharokka_db
echo "已建立动态链接: /opt/pharokka_db -> $DB_BASE"

echo "--- [4/4] 正在安装 Pharokka 软件... ---"
pip3 install pharokka --break-system-packages

echo "--- 准备就绪！即将开始下载大型数据库 (约 10GB)... ---"
echo "注意：如果中途断开，可以重新运行此脚本，它会自动续传。"
export PATH=$PATH:/usr/local/bin:/root/.local/bin
install_databases.py -o /opt/pharokka_db
