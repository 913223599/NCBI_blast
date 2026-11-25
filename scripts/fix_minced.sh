#!/bin/bash
set -e
echo "--- 正在补全 Java 环境、MinCED 和 Dnaapler... ---"
apt-get update && apt-get install -y default-jre wget
pip3 install dnaapler --break-system-packages
wget https://github.com/ctSkennerton/minced/releases/download/0.4.2/minced.jar -O /usr/local/bin/minced.jar
printf '#!/bin/bash\njava -jar /usr/local/bin/minced.jar "$@"\n' > /usr/local/bin/minced
chmod +x /usr/local/bin/minced

echo "--- 依赖已全部就绪！ ---"
if [ -n "$1" ] && [ -n "$2" ]; then
  echo "--- 启动 Pharokka 注释任务: input=$1 output=$2 ---"
  python3 /usr/local/bin/pharokka.py -i "$1" -o "$2" -d "${PHAROKKA_DB:-/opt/pharokka_db}" -t "${PHAROKKA_THREADS:-8}" -f
else
  echo "用法（可选触发测试）: bash scripts/fix_minced.sh <input_fasta> <output_dir>"
fi
