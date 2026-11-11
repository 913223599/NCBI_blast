# -*- coding: utf-8 -*-
"""
手动下载数据库的一键自动解压与索引构建工具
使用方法: 将下载好的数据库文件放入对应 database/ 目录后直接运行此脚本:
python scripts/build_downloaded_dbs.py
"""
import os
import sys
import gzip
import tarfile
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_ROOT = PROJECT_ROOT / "database"

def get_makeblastdb_cmd():
    # 优先寻找本地 tools
    for candidate in [
        PROJECT_ROOT / "vendor" / "blast" / "bin" / "makeblastdb.exe",
        PROJECT_ROOT / "tools" / "blast" / "bin" / "makeblastdb.exe",
        PROJECT_ROOT / "vendor" / "ncbi-blast" / "bin" / "makeblastdb.exe"
    ]:
        if candidate.exists():
            return str(candidate)
    return "makeblastdb"

def build_swissprot():
    sp_dir = DB_ROOT / "swissprot"
    sp_dir.mkdir(parents=True, exist_ok=True)
    gz_files = list(sp_dir.glob("*.fasta.gz")) + list(sp_dir.glob("*.fa.gz")) + list(sp_dir.glob("*.gz"))
    fasta_files = list(sp_dir.glob("*.fasta")) + list(sp_dir.glob("*.fa"))
    
    source_fasta = sp_dir / "source.fasta"
    
    if not source_fasta.exists():
        if fasta_files:
            for f in fasta_files:
                if f.name != "source.fasta":
                    print(f"[Swiss-Prot] 发现 FASTA 文件: {f.name} -> 重命名为 source.fasta")
                    f.rename(source_fasta)
                    break
        elif gz_files:
            target_gz = gz_files[0]
            print(f"[Swiss-Prot] 正在解压 {target_gz.name}...")
            with gzip.open(target_gz, 'rb') as f_in:
                with open(source_fasta, 'wb') as f_out:
                    while chunk := f_in.read(1024 * 1024):
                        f_out.write(chunk)
            print("[Swiss-Prot] 解压完成。")
            
    if source_fasta.exists():
        print("[Swiss-Prot] 正在构建 BLAST 蛋白质索引 (swissprot)...")
        cmd = [get_makeblastdb_cmd(), "-in", "source.fasta", "-dbtype", "prot", "-title", "UniProtKB/Swiss-Prot", "-out", "swissprot"]
        res = subprocess.run(cmd, cwd=str(sp_dir), capture_output=True, text=True)
        if res.returncode == 0:
            print("[Swiss-Prot] 索引构建成功，数据库已就绪！")
        else:
            print(f"[Swiss-Prot] 索引构建失败: {res.stderr}")
    else:
        print("[Swiss-Prot] 未在 database/swissprot/ 找到 fasta/gz 文件，跳过。")

def build_vfdb():
    vf_dir = DB_ROOT / "vfdb"
    vf_dir.mkdir(parents=True, exist_ok=True)
    gz_files = list(vf_dir.glob("*.fas.gz")) + list(vf_dir.glob("*.fasta.gz")) + list(vf_dir.glob("*.gz"))
    fasta_files = list(vf_dir.glob("*.fas")) + list(vf_dir.glob("*.fasta"))
    
    source_fasta = vf_dir / "source.fasta"
    if not source_fasta.exists():
        if fasta_files:
            for f in fasta_files:
                if f.name != "source.fasta":
                    print(f"[VFDB] 发现 FASTA 文件: {f.name} -> 重命名为 source.fasta")
                    f.rename(source_fasta)
                    break
        elif gz_files:
            target_gz = gz_files[0]
            print(f"[VFDB] 正在解压 {target_gz.name}...")
            with gzip.open(target_gz, 'rb') as f_in:
                with open(source_fasta, 'wb') as f_out:
                    while chunk := f_in.read(1024 * 1024):
                        f_out.write(chunk)
            print("[VFDB] 解压完成。")
            
    if source_fasta.exists():
        print("[VFDB] 正在构建 BLAST 毒力因子索引 (vfdb)...")
        cmd = [get_makeblastdb_cmd(), "-in", "source.fasta", "-dbtype", "prot", "-title", "VFDB Virulence Factors", "-out", "vfdb"]
        res = subprocess.run(cmd, cwd=str(vf_dir), capture_output=True, text=True)
        if res.returncode == 0:
            print("[VFDB] 索引构建成功，数据库已就绪！")
        else:
            print(f"[VFDB] 索引构建失败: {res.stderr}")
    else:
        print("[VFDB] 未在 database/vfdb/ 找到 fasta/gz 文件，跳过。")

def build_card():
    card_dir = DB_ROOT / "card"
    card_dir.mkdir(parents=True, exist_ok=True)
    tar_files = list(card_dir.glob("*.tar.bz2")) + list(card_dir.glob("*.tar.gz")) + list(card_dir.glob("*.bz2"))
    
    # 解压
    if tar_files:
        for t in tar_files:
            try:
                print(f"[CARD] 正在解压 {t.name}...")
                with tarfile.open(t) as tar:
                    tar.extractall(path=card_dir)
                print("[CARD] 解压完成。")
            except Exception as e:
                print(f"[CARD] 解压异常: {e}")
                
    f_faa = card_dir / "protein_fasta.fasta"
    if not f_faa.exists():
        cands = list(card_dir.glob("*protein*.fasta")) + list(card_dir.glob("*.fasta"))
        if cands:
            f_faa = cands[0]
            
    if f_faa.exists():
        print(f"[CARD] 正在为 {f_faa.name} 构建耐药基因索引 (card_protein)...")
        cmd = [get_makeblastdb_cmd(), "-in", f_faa.name, "-dbtype", "prot", "-title", "CARD Resistome", "-out", "card_protein"]
        res = subprocess.run(cmd, cwd=str(card_dir), capture_output=True, text=True)
        if res.returncode == 0:
            print("[CARD] 索引构建成功，数据库已就绪！")
        else:
            print(f"[CARD] 索引构建失败: {res.stderr}")
    else:
        print("[CARD] 未在 database/card/ 找到蛋白序列文件，跳过。")

def build_defense_finder():
    df_dir = DB_ROOT / "defense_finder"
    df_dir.mkdir(parents=True, exist_ok=True)
    tar_files = list(df_dir.glob("*.tar.gz")) + list(df_dir.glob("*.tgz")) + list(df_dir.glob("*.tar"))
    if tar_files:
        for t in tar_files:
            try:
                print(f"[DefenseFinder] 正在解压 {t.name}...")
                with tarfile.open(t) as tar:
                    tar.extractall(path=df_dir)
                print("[DefenseFinder] 解压完成，模型库已就绪！")
            except Exception as e:
                print(f"[DefenseFinder] 解压异常: {e}")
    elif any(df_dir.glob("*.hmm*")):
        print("[DefenseFinder] 模型文件已就绪。")
    else:
        print("[DefenseFinder] 未在 database/defense_finder/ 找到模型压缩包，跳过。")

def build_cdd():
    cdd_dir = DB_ROOT / "cdd_pfam"
    cdd_dir.mkdir(parents=True, exist_ok=True)
    tar_files = list(cdd_dir.glob("*.tar.gz")) + list(cdd_dir.glob("*.tar"))
    if tar_files:
        for t in tar_files:
            try:
                print(f"[CDD/Pfam] 正在解压 {t.name}...")
                with tarfile.open(t) as tar:
                    tar.extractall(path=cdd_dir)
                print("[CDD/Pfam] 解压完成，结构域库已就绪！")
            except Exception as e:
                print(f"[CDD/Pfam] 解压异常: {e}")
    elif any(cdd_dir.glob("*.rps*")):
        print("[CDD/Pfam] 结构域模型已就绪。")
    else:
        print("[CDD/Pfam] 未在 database/cdd_pfam/ 找到压缩包，跳过。")

def main():
    print("=" * 60)
    print("      本地数据库自动解压与索引构建工具 (NCBI BLAST Pro)")
    print("=" * 60)
    build_swissprot()
    print("-" * 60)
    build_vfdb()
    print("-" * 60)
    build_card()
    print("-" * 60)
    build_defense_finder()
    print("-" * 60)
    build_cdd()
    print("=" * 60)
    print("处理完毕！请在应用【设置 / 本地数据库】中刷新查看状态。")

if __name__ == "__main__":
    main()
