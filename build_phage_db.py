import gzip
import os
import subprocess
from pathlib import Path

def extract_headers(fasta_gz_path: Path, tsv_out_path: Path):
    """提取 FASTA.gz 中的所有 header 为 TSV 映射文件"""
    print(f"正在从 {fasta_gz_path.name} 提取 Headers...")
    count = 0
    with gzip.open(fasta_gz_path, 'rt', encoding='utf-8', errors='ignore') as f_in, \
         open(tsv_out_path, 'w', encoding='utf-8') as f_out:
        
        f_out.write("Accession\tDescription\n")
        for line in f_in:
            if line.startswith('>'):
                header = line[1:].strip()
                parts = header.split(maxsplit=1)
                accession = parts[0]
                desc = parts[1] if len(parts) > 1 else "Unknown"
                f_out.write(f"{accession}\t{desc}\n")
                count += 1
                if count % 500000 == 0:
                    print(f"  已提取 {count} 条...")
                    
    print(f"DONE! 从 {fasta_gz_path.name} 提取了 {count} 条序列信息到 {tsv_out_path.name}\n")

def to_wsl(p: Path) -> str:
    s = str(p.resolve()).replace("\\", "/")
    if len(s) >= 2 and s[1] == ":":
        return f"/mnt/{s[0].lower()}/{s[2:].lstrip('/')}"
    return s

def build_mash_sketch(fasta_gz_path: Path):
    """使用 WSL 通过 mash 构建索引"""
    msh_out = fasta_gz_path.with_suffix(".msh") # Removes .gz, leaves .fasta.msh 
    # If the file ends with .fasta.gz, with_suffix turns it into .fasta.msh, which is fine, 
    # but mash automatically appends .msh. Let's just pass the original path and mash will make .fasta.gz.msh
    
    # Actually, if we run `mash sketch -i -s 1000 -p 8 IN.fasta.gz`, output is `IN.fasta.gz.msh`
    print(f"正在为 {fasta_gz_path.name} 构建 Mash Sketch 索引...")
    
    wsl_in = to_wsl(fasta_gz_path)
    
    cmd = [
        "wsl", "-d", "Ubuntu", "--",
        "mash", "sketch",
        "-i",              # 每条序列单独建立 sketch
        "-s", "1000",      # sketch size 取 1000 (默认值，平衡速度和精度)
        "-k", "21",        # k-mer size 默认 21
        "-p", "8",         # 使用 8 个线程加速
        wsl_in
    ]
    
    try:
        # 这个执行时间会比较长，尤其是 17GB 那个库
        subprocess.run(cmd, check=True)
        print(f"DONE! {fasta_gz_path.name} Mash 索引构建完成！")
    except subprocess.CalledProcessError as e:
        print(f"ERROR 构建 Mash 索引失败: {e}")

if __name__ == "__main__":
    db_dir = Path(r"F:\NCBI blast\database")
    
    phage_db = db_dir / "Phage.17770sequence.fasta.gz"
    prophage_db = db_dir / "Prophage.3281395sequence.fasta.gz"
    
    # 1. 处理 Phage.17770
    if phage_db.exists():
        extract_headers(phage_db, db_dir / "Phage.17770sequence.metadata.tsv")
        build_mash_sketch(phage_db)
    else:
        print(f"找不到 {phage_db}")
        
    # 2. 处理 Prophage.3281395
    if prophage_db.exists():
        extract_headers(prophage_db, db_dir / "Prophage.3281395sequence.metadata.tsv")
        build_mash_sketch(prophage_db)
    else:
        print(f"找不到 {prophage_db}")
