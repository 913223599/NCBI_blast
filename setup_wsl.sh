#!/bin/bash
set -e

# Switch to Tsinghua Mirror
echo "Updating sources to Tsinghua mirror..."
if [ -f /etc/apt/sources.list.d/ubuntu.sources ]; then
    sed -i 's|http://archive.ubuntu.com|https://mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/ubuntu.sources
    sed -i 's|http://security.ubuntu.com|https://mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/ubuntu.sources
else
    sed -i 's|http://archive.ubuntu.com|https://mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list
    sed -i 's|http://security.ubuntu.com|https://mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list
fi

# Update and install
apt-get update
apt-get install -y iqtree

echo "SUCCESS: IQ-TREE installed in WSL."
iqtree --version
