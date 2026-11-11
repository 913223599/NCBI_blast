# -*- coding: utf-8 -*-
"""
自动将用户下载的数据库文件导入系统、解压、构建索引并进行功能测试 (强制 UTF-8 编码)
"""
import os
import sys
import shutil
import gzip
import tarfile
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_ROOT = PROJECT_ROOT / "database"
DOWNLOAD_DIR = Path("C:/Users/Administrator/Downloads")

def get_makeblastdb_cmd():
    for candidate in [
        PROJECT_ROOT / "vendor" / "blast" / "bin" / "makeblastdb.exe",
        PROJECT_ROOT / "tools" / "blast" / "bin" / "makeblastdb.exe",
        PROJECT_ROOT / "vendor" / "ncbi-blast" / "bin" / "makeblastdb.exe"
    ]:
        if candidate.exists():
            return str(candidate)
    return "makeblastdb"

def process_swissprot():
    print("\n[1/5] 处理 UniProtKB / Swiss-Prot 数据库...")
    dest_dir = DB_ROOT / "swissprot"
    dest_dir.mkdir(parents=True, exist_ok=True)
    
    src_file = DOWNLOAD_DIR / "uniprot_sprot.fasta.gz"
    if src_file.exists():
        dest_gz = dest_dir / "uniprot_sprot.fasta.gz"
        print(f"  - 复制 {src_file.name} 到 {dest_dir}...")
        shutil.copy2(src_file, dest_gz)
        
        dest_fasta = dest_dir / "source.fasta"
        if not dest_fasta.exists() or dest_fasta.stat().st_size < 1000:
            print(f"  - 解压 {dest_gz.name} 到 {dest_fasta.name}...")
            with gzip.open(dest_gz, 'rb') as f_in:
                with open(dest_fasta, 'wb') as f_out:
                    while chunk := f_in.read(2 * 1024 * 1024):
                        f_out.write(chunk)
            print("  - 解压完成，大小: {:.2f} MB".format(dest_fasta.stat().st_size / (1024*1024)))
        else:
            print(f"  - 已存在解压文件: {dest_fasta.name}")
        
        print("  - 构建 BLAST 蛋白质索引 (swissprot)...")
        cmd = [get_makeblastdb_cmd(), "-in", "source.fasta", "-dbtype", "prot", "-title", "UniProtKB/Swiss-Prot", "-out", "swissprot"]
        res = subprocess.run(cmd, cwd=str(dest_dir), capture_output=True, encoding="utf-8", errors="ignore")
        if res.returncode == 0:
            print("  - Swiss-Prot 索引构建成功！")
        else:
            print(f"  - Swiss-Prot 索引构建失败: {res.stderr}")
    else:
        print(f"  - 未找到 {src_file}")

def process_vfdb():
    print("\n[2/5] 处理 VFDB 毒力因子数据库...")
    dest_dir = DB_ROOT / "vfdb"
    dest_dir.mkdir(parents=True, exist_ok=True)
    
    src_file = DOWNLOAD_DIR / "VFDB_setB_pro.fas.gz"
    if src_file.exists():
        dest_gz = dest_dir / "VFDB_setB_pro.fas.gz"
        print(f"  - 复制 {src_file.name} 到 {dest_dir}...")
        shutil.copy2(src_file, dest_gz)
        
        dest_fasta = dest_dir / "source.fasta"
        if not dest_fasta.exists() or dest_fasta.stat().st_size < 1000:
            print(f"  - 解压 {dest_gz.name} 到 {dest_fasta.name}...")
            with gzip.open(dest_gz, 'rb') as f_in:
                with open(dest_fasta, 'wb') as f_out:
                    while chunk := f_in.read(2 * 1024 * 1024):
                        f_out.write(chunk)
            print("  - 解压完成，大小: {:.2f} MB".format(dest_fasta.stat().st_size / (1024*1024)))
        else:
            print(f"  - 已存在解压文件: {dest_fasta.name}")
        
        print("  - 构建 BLAST 毒力因子索引 (vfdb)...")
        cmd = [get_makeblastdb_cmd(), "-in", "source.fasta", "-dbtype", "prot", "-title", "VFDB Virulence Factors", "-out", "vfdb"]
        res = subprocess.run(cmd, cwd=str(dest_dir), capture_output=True, encoding="utf-8", errors="ignore")
        if res.returncode == 0:
            print("  - VFDB 索引构建成功！")
        else:
            print(f"  - VFDB 索引构建失败: {res.stderr}")
    else:
        print(f"  - 未找到 {src_file}")

def process_card():
    print("\n[3/5] 处理 CARD 抗生素耐药数据库...")
    dest_dir = DB_ROOT / "card"
    dest_dir.mkdir(parents=True, exist_ok=True)
    
    for fname in ["card-data.tar.bz2", "card-ontology.tar.bz2"]:
        src_file = DOWNLOAD_DIR / fname
        if src_file.exists():
            dest_file = dest_dir / fname
            print(f"  - 复制 {fname} 到 {dest_dir}...")
            shutil.copy2(src_file, dest_file)
            
            if "card-data" in fname:
                print(f"  - 正在解压 {fname}...")
                with tarfile.open(dest_file, "r:bz2") as tar:
                    tar.extractall(path=dest_dir)
                print("  - 解压完成。")
                
    f_faa = dest_dir / "protein_fasta.fasta"
    if not f_faa.exists():
        cands = list(dest_dir.glob("*protein*.fasta")) + list(dest_dir.glob("*.fasta"))
        if cands: f_faa = cands[0]
        
    if f_faa and f_faa.exists():
        print(f"  - 构建 CARD 耐药蛋白索引 (card_protein) 从 {f_faa.name}...")
        cmd = [get_makeblastdb_cmd(), "-in", f_faa.name, "-dbtype", "prot", "-title", "CARD Resistome", "-out", "card_protein"]
        res = subprocess.run(cmd, cwd=str(dest_dir), capture_output=True, encoding="utf-8", errors="ignore")
        if res.returncode == 0:
            print("  - CARD 耐药索引构建成功！")
        else:
            print(f"  - CARD 索引构建失败: {res.stderr}")

def process_defense_finder():
    print("\n[4/5] 处理 DefenseFinder & AcrDB 抗防御模型库...")
    dest_dir = DB_ROOT / "defense_finder"
    dest_dir.mkdir(parents=True, exist_ok=True)
    
    src_file = DOWNLOAD_DIR / "defense-finder-models-3.1.0.tar.gz"
    if not src_file.exists():
        cands = list(DOWNLOAD_DIR.glob("defense-finder-models*.tar.gz"))
        if cands: src_file = cands[0]
        
    if src_file.exists():
        dest_file = dest_dir / src_file.name
        print(f"  - 复制 {src_file.name} 到 {dest_dir}...")
        shutil.copy2(src_file, dest_file)
        
        print(f"  - 解压 {dest_file.name}...")
        with tarfile.open(dest_file, "r:gz") as tar:
            tar.extractall(path=dest_dir)
        print("  - DefenseFinder 模型解压完成！")

def process_cdd():
    print("\n[5/5] 处理 NCBI CDD / Pfam-A 保守结构域数据库...")
    dest_dir = DB_ROOT / "cdd_pfam"
    dest_dir.mkdir(parents=True, exist_ok=True)
    
    src_file = DOWNLOAD_DIR / "cdd.tar.gz"
    if src_file.exists():
        dest_file = dest_dir / "cdd.tar.gz"
        print(f"  - 复制 {src_file.name} 到 {dest_dir}...")
        shutil.copy2(src_file, dest_file)
        
        print(f"  - 解压 {dest_file.name}...")
        with tarfile.open(dest_file, "r:gz") as tar:
            tar.extractall(path=dest_dir)
        print("  - CDD 保守结构域库解压完成！")

def run_tests():
    print("\n" + "=" * 60)
    print("      正在验证全部数据库注册与就绪状态...")
    print("=" * 60)
    sys.path.insert(0, str(PROJECT_ROOT))
    from src.backend.utils.bio_db_manager import bio_db_manager
    
    statuses = bio_db_manager.list_all_status()
    for s in statuses:
        status_txt = "完整就绪" if s['installed'] else "未就绪"
        print(f"[{s['category']}] {s['name']} (ID: {s['db_id']}) -> 状态: {status_txt} | 大小: {s['size_mb']} MB")

    print("\n" + "=" * 60)
    print("      正在运行多层级联注释 (FunctionalAssigner) 实测...")
    print("=" * 60)
    from src.analysis.annotation.functional_assigner import FunctionalAssigner
    
    assigner = FunctionalAssigner()
    
    # 构建测试蛋白序列 (包含之前提取的假定蛋白)
    test_work_dir = PROJECT_ROOT / "results" / "test_anno_tmp"
    test_work_dir.mkdir(parents=True, exist_ok=True)
    test_faa = test_work_dir / "test_hypothetical.faa"
    
    with open(test_faa, "w", encoding="utf-8") as f:
        f.write(">DAPNSXJR_CDS_0029 hypothetical protein\nMTAPTASELVAAMASRGVTITTADATGILCLVESITECLELNYPEDTCRQDAIMLWSSILIASNTAGRYITSHHAPSGASQSFGYGSKPWMALYNQMKLLDTADCTGDLVEEPDGSSKPWFRVVTGSRC\n")
        f.write(">DAPNSXJR_CDS_0067 hypothetical protein\nMKTIDLLVEELPKRGGWPDGAVEAGFLCSDDTLFFVNEDGDCPSGWRINMNYEAEDNWVGVTREQYEAAVLAATTQATITLPTDGWIDWHGGKCPVEKGALVDVRFRNGREHFEQSALHSNDFASQPFWRHDNEPADIIAYRLHKPQEAEQAESDDEAELNECIGQMPAPAWNGEGLPPVGVECEITFKDDTTPEWYSFVATFIGSNHIVALVGLEELTYKKSELLRPEVKFRPLRSEADKKREEAVQALCDAGGGYCKVNEKTGYGSSWFDVYDAIAAGKIPGVKLEV\n")
        f.write(">DAPNSXJR_CDS_0075 hypothetical protein\nMVMIKKKLQMKMRNAAMEKYTRKINISFIDGVGMYNHACHLNAVNRARSGDSAAVVEVVMINDDSVTAHYINMQADGKFVDHTLGWHWSGADYRLVRYVPFTEWSDITSSLERLKAELCKPVSKWMRAFILTNNEMC\n")

    print(f"已创建测试用假定蛋白序列: {test_faa}")
    results = assigner.run_blastp_annotation(test_faa, test_work_dir, threads=4)
    print(f"\n注释打捞成功赋予功能数量: {len(results)}")
    for qid, res in results.items():
        print(f"\n  * {qid}:")
        print(f"    - 赋予真实功能: {res.get('product')}")
        print(f"    - 来源数据库: {res.get('source_db')}")
        print(f"    - 分类/基因: {res.get('category')} / {res.get('gene_name')}")
        print(f"    - E-value / Identity: {res.get('evalue')} / {res.get('identity')}%")
        if res.get('is_virulence'):
            print(f"    - 毒力标记: {res.get('virulence_desc')}")
        if res.get('is_resistance'):
            print(f"    - 耐药标记: {res.get('resistance_desc')}")

if __name__ == "__main__":
    process_swissprot()
    process_vfdb()
    process_card()
    process_defense_finder()
    process_cdd()
    run_tests()
