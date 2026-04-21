#!/bin/bash
# 高性能版：使用全部 CPU 推演核酸库

DB_DIR="/mnt/f/NCBI blast/database"
PHAGE_FASTA="$DB_DIR/Phage.17770sequence.fasta.gz"
PROPHAGE_FASTA="$DB_DIR/Prophage.3281395sequence.fasta.gz"
THREADS=$(nproc)

echo "=== 🚀 检测到 $THREADS 个逻辑处理器。启动全系统资源加速！ ==="

function process_db() {
    local fasta=$1
    local name=$(basename "$fasta")
    local tsv="$DB_DIR/${name%%.fasta.gz}.metadata.tsv"
    
    if [ ! -f "$fasta" ]; then
        echo "❌ 找不到 $fasta"
        return
    fi
    
    echo "[$name] 1. 极速抽取元数据表 (zcat + awk 引擎) ..."
    echo -e "Accession\tDescription" > "$tsv"
    
    zcat "$fasta" | awk '/^>/ {
        id = $1
        sub(/^>/, "", id)
        desc = $0
        sub(/^>[^ \t]+[ \t]*/, "", desc)
        if(desc=="") desc="Unknown";
        print id "\t" desc
    }' >> "$tsv"
    
    echo "[$name] 2. 构建核心 Mash Sketch (启用 $THREADS 核心全力运算) ..."
    mash sketch -i -s 1000 -k 21 -p "$THREADS" "$fasta"
    echo "[$name] ✅ 这一项处理完毕！"
    echo "---------------------------------------------------"
}

# 刚才旧版可能没执行完大的，我们重新用全速版过一遍
process_db "$PHAGE_FASTA"
process_db "$PROPHAGE_FASTA"

echo "🎉 全部数据库转换加速完成！"
