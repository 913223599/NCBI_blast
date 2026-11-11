#!/bin/bash
set -e
echo "--- 正在补全 Java 环境、MinCED 和 Dnaapler... ---"
apt-get update && apt-get install -y default-jre wget
pip3 install dnaapler --break-system-packages
wget https://github.com/ctSkennerton/minced/releases/download/0.4.2/minced.jar -O /usr/local/bin/minced.jar
printf '#!/bin/bash\njava -jar /usr/local/bin/minced.jar "$@"\n' > /usr/local/bin/minced
chmod +x /usr/local/bin/minced

echo "--- 依赖已全部就绪！启动 Pharokka 终极注释任务... ---"
python3 /usr/local/bin/pharokka.py -i "/mnt/f/NCBI blast/results/assembly/AS_1776452382749/assemblerstep/unicycler_run/assembly.fasta" -o "/mnt/f/NCBI blast/results/assembly/AS_1776452382749/phageannotationstep/pharokka_res" -d /opt/pharokka_db -t 8 -f
