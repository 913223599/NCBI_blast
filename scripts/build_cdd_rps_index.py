# -*- coding: utf-8 -*-
"""
自动化构建 NCBI CDD / Pfam-A 保守结构域 RPS-BLAST 索引
"""
import os
import sys
import shutil
import ctypes
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

def get_short_path(long_path_str: str) -> str:
    """获取 Windows 8.3 短路径，规避空格与特殊字符引起的 BLAST+ 引擎报错"""
    if os.name != 'nt':
        return long_path_str
    try:
        buffer = ctypes.create_unicode_buffer(1024)
        result = ctypes.windll.kernel32.GetShortPathNameW(long_path_str, buffer, 1024)
        if result > 0:
            return buffer.value
    except Exception:
        pass
    return long_path_str

def build_cdd_rps_index():
    cdd_dir = PROJECT_ROOT / "database" / "cdd_pfam"
    if not cdd_dir.exists():
        print(f"CDD 目录不存在: {cdd_dir}")
        return False
        
    smp_files = list(cdd_dir.glob("*.smp"))
    if not smp_files:
        print(f"未在 {cdd_dir} 找到 .smp 文件")
        return False
        
    print(f"=== 找到 {len(smp_files)} 个 .smp 结构域模型，准备构建 RPS 数据库 ===")
    
    # 1. 写入 smp 文件列表 (使用纯文件名，在 cdd_dir 下执行)
    smp_list_file = cdd_dir / "smp_file_list.pn"
    with open(smp_list_file, "w", encoding="utf-8") as f:
        for p in smp_files:
            f.write(f"{p.name}\n")
            
    print(f"模型列表已写入: {smp_list_file} ({len(smp_files)} 条)")
    
    # 2. 调用 makeprofiledb
    makeprofiledb_bin = shutil.which("makeprofiledb") or "makeprofiledb"
    short_cdd_dir = get_short_path(str(cdd_dir.resolve()))
    
    cmd = [
        makeprofiledb_bin,
        "-in", "smp_file_list.pn",
        "-out", "cdd_pfam",
        "-title", "NCBI_CDD_Pfam_Conserved_Domains",
        "-dbtype", "rps",
        "-index", "true",
        "-max_smp_vol", "10000"
    ]
    
    print(f"执行命令: {' '.join(cmd)}")
    print(f"工作目录 (短路径): {short_cdd_dir}")
    
    res = subprocess.run(
        cmd,
        cwd=short_cdd_dir,
        capture_output=True,
        encoding="utf-8",
        errors="ignore"
    )
    
    print("返回码:", res.returncode)
    if res.stdout:
        print("标准输出:", res.stdout[:500])
    if res.stderr:
        print("标准错误:", res.stderr[:500])
        
    # 检查输出文件
    rps_files = list(cdd_dir.glob("cdd_pfam.*"))
    print("\n生成的数据库索引文件:")
    for f in rps_files:
        print(f"  - {f.name} ({f.stat().st_size:,} bytes)")
        
    if res.returncode == 0 and any(cdd_dir.glob("cdd_pfam.rps*")):
        print("\n=== NCBI CDD / Pfam RPS-BLAST 索引构建 100% 成功！===")
        return True
    else:
        print("\n=== 构建可能存在异常，请检查 ===")
        return False

if __name__ == "__main__":
    build_cdd_rps_index()
