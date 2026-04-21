#!/bin/bash
set -euo pipefail

# ============================================================
# Prophage Database Chunker
# 将 328 万条序列拆为 10 个块，逐块生成 mash 索引
# 源文件只读，绝不修改
# ============================================================

SRC="/mnt/f/NCBI blast/database/Prophage.3281395sequence.fasta.gz"
CHUNK_DIR="/mnt/f/NCBI blast/database/prophage_chunks"
TOTAL_SEQ=3281395
NUM_CHUNKS=10
SEQ_PER_CHUNK=$(( (TOTAL_SEQ / NUM_CHUNKS) + 1 ))

echo "=== Prophage DB Splitter ==="
echo "Source:     $SRC"
echo "Chunks:     $NUM_CHUNKS"
echo "Seq/chunk:  ~$SEQ_PER_CHUNK"
echo ""

mkdir -p "$CHUNK_DIR"

# Step 1: 拆分 FASTA（只读源文件）
echo "[Step 1/$((NUM_CHUNKS+1))] Splitting FASTA into $NUM_CHUNKS chunks..."

chunk_idx=1
seq_count=0

# 初始化第一个输出文件
out_file="$CHUNK_DIR/prophage_chunk_${chunk_idx}.fasta.gz"
exec 3> >(gzip -1 > "$out_file")

zcat "$SRC" | while IFS= read -r line; do
    if [[ "$line" == ">"* ]]; then
        seq_count=$((seq_count + 1))

        # 每达到阈值，切换到新的输出文件
        if (( seq_count > SEQ_PER_CHUNK && chunk_idx < NUM_CHUNKS )); then
            exec 3>&-  # 关闭当前输出
            echo "  Chunk $chunk_idx done (at seq #$((seq_count-1)))"

            chunk_idx=$((chunk_idx + 1))
            seq_count=1
            out_file="$CHUNK_DIR/prophage_chunk_${chunk_idx}.fasta.gz"
            exec 3> >(gzip -1 > "$out_file")
        fi
    fi
    echo "$line" >&3
done

exec 3>&-
echo "  Chunk $chunk_idx done (final)"
echo ""
echo "[Step 1 COMPLETE] $chunk_idx chunks created."
echo ""

# Step 2: 为每个块生成 mash sketch (索引)
for i in $(seq 1 $chunk_idx); do
    chunk_fasta="$CHUNK_DIR/prophage_chunk_${i}.fasta.gz"
    chunk_msh="$CHUNK_DIR/prophage_chunk_${i}.fasta.gz.msh"

    if [[ -f "$chunk_msh" ]]; then
        echo "[Step $((i+1))/$((chunk_idx+1))] Chunk $i index exists, skipping."
        continue
    fi

    echo "[Step $((i+1))/$((chunk_idx+1))] Indexing chunk $i..."
    mash sketch -p 16 -o "$chunk_msh" "$chunk_fasta" 2>/dev/null
    size=$(du -h "$chunk_msh" | cut -f1)
    echo "  -> $chunk_msh ($size)"
done

echo ""
echo "=== ALL DONE ==="
echo "Chunks directory:"
ls -lh "$CHUNK_DIR"
