
import gzip
import os
from pathlib import Path

source_file = Path("f:/NCBI blast/database/Prophage.3281395sequence.fasta.gz")
output_dir = Path("f:/NCBI blast/database/prophage_chunks")
total_sequences = 3281395
chunks = 10
seq_per_chunk = (total_sequences // chunks) + 1

print(f"开始拆分: {source_file}")
print(f"目标份数: {chunks}, 每份约 {seq_per_chunk} 条序列")

def split_fasta():
    output_dir.mkdir(exist_ok=True)
    
    current_chunk = 1
    current_seq_count = 0
    
    f_out = gzip.open(output_dir / f"prophage_chunk_{current_chunk}.fasta.gz", "wt", compresslevel=1)
    
    # 使用 Windows 的 gzip 模块读取，效率尚可
    try:
        with gzip.open(source_file, "wt" if os.name == 'nt' else "rt") as f_in:
            # 修正打开模式，如果是读取应该是 "rt"
            pass
        
        with gzip.open(source_file, "rt", encoding="utf-8", errors="ignore") as f_in:
            for line in f_in:
                if line.startswith(">"):
                    if current_seq_count >= seq_per_chunk and current_chunk < chunks:
                        f_out.close()
                        current_chunk += 1
                        current_seq_count = 0
                        print(f"  -> 已完成 Chunk {current_chunk-1}, 正在开启 Chunk {current_chunk}...")
                        f_out = gzip.open(output_dir / f"prophage_chunk_{current_chunk}.fasta.gz", "wt", compresslevel=1)
                    
                    current_seq_count += 1
                
                f_out.write(line)
                
    finally:
        f_out.close()
    
    print(f"✅ 成功拆分为 {current_chunk} 个文件。")

if __name__ == "__main__":
    split_fasta()
