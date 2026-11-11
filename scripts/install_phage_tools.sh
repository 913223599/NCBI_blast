#!/bin/bash
# PhageScope 噬菌体工具链一键安装脚本 (WSL/Ubuntu 环境)
# 执行该脚本将自动安装 Miniconda3 (若无), 以及 VIBRANT 和 VirSorter2，并建立全局软链。

set -e

echo "========================================"
echo "    PhageScope 噬菌体高级分箱系统安装   "
echo "========================================"

# 1. 检查并安装 Miniconda3
if ! command -v conda &> /dev/null; then
    echo "[1/5] 正在下载并安装 Miniconda3..."
    wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O miniconda.sh
    bash miniconda.sh -b -p /opt/miniconda3
    rm miniconda.sh
    export PATH="/opt/miniconda3/bin:$PATH"
    conda init bash
    echo "Miniconda3 安装完成。"
else
    echo "[1/4] 检测到 Conda 已安装: $(conda --version)"
fi

# 安装 mamba 倍速
echo "[2/5] 正在配置 mamba 加速器..."
conda install -y -n base -c conda-forge mamba

# 2. 安装 VIBRANT
echo "[3/5] 正在安装 VIBRANT..."
if ! conda env list | grep -q "vibrant"; then
    mamba create -n vibrant -y -c bioconda -c conda-forge vibrant
    echo "提示: VIBRANT 需要下载数十 GB 的数据库。请在后续手动执行: conda activate vibrant && download-db.sh"
else
    echo "VIBRANT 环境已存在。"
fi

# 创建全局软链或执行脚本，以便 Python 侧直接 `which vibrant` 能找到
if [ ! -f /usr/local/bin/vibrant ]; then
    cat << 'EOF' > /usr/local/bin/vibrant
#!/bin/bash
source /opt/miniconda3/etc/profile.d/conda.sh
conda activate vibrant
exec VIBRANT_run.py "$@"
EOF
    chmod +x /usr/local/bin/vibrant
fi

# 3. 安装 VirSorter2
echo "[4/5] 正在安装 VirSorter2..."
if ! conda env list | grep -q "virsorter2"; then
    mamba create -n virsorter2 -y -c bioconda -c conda-forge virsorter=2
    echo "提示: VirSorter2 需要下载数据库。请在后续手动执行: conda activate virsorter2 && virsorter setup -d db -j 4"
else
    echo "VirSorter2 环境已存在。"
fi

# 创建全局软链
if [ ! -f /usr/local/bin/virsorter ]; then
    cat << 'EOF' > /usr/local/bin/virsorter
#!/bin/bash
source /opt/miniconda3/etc/profile.d/conda.sh
conda activate virsorter2
exec virsorter "$@"
EOF
    chmod +x /usr/local/bin/virsorter
fi

# 4. 安装 BacpHLiP
echo "[5/5] 正在安装 BacpHLiP..."
if ! conda env list | grep -q "bacphlip"; then
    mamba create -n bacphlip -y -c bioconda -c conda-forge bacphlip
else
    echo "BacpHLiP 环境已存在。"
fi

# 创建全局软链
if [ ! -f /usr/local/bin/bacphlip ]; then
    cat << 'EOF' > /usr/local/bin/bacphlip
#!/bin/bash
source /opt/miniconda3/etc/profile.d/conda.sh
conda activate bacphlip
exec bacphlip "$@"
EOF
    chmod +x /usr/local/bin/bacphlip
fi

echo "========================================"
echo " 基础环境安装完成！"
echo " 请注意：你还需要分别下载两个工具的数据库才能正常工作！"
echo "VIBRANT DB 下载： conda activate vibrant && download-db.sh (约15GB)"
echo "VirSorter2 DB 下载： conda activate virsorter2 && virsorter setup -d db -j 4 (约3GB)"
echo "========================================"
