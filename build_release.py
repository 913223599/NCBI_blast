#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NCBI BLAST GUI 工业级构建脚本 (Industrial Build Script)
"""

import shutil
import subprocess
import sys
import time
from pathlib import Path

import argparse

PROJECT_ROOT = Path(__file__).parent.absolute()
DIST_DIR = PROJECT_ROOT / "dist" / "NCBI_BLAST_GUI"
INTERNAL_DIR = DIST_DIR / "_internal"
SPEC_FILE = PROJECT_ROOT / "NCBI_BLAST_GUI.spec"

def run_cmd(cmd, check=True):
    print(f"  > {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=PROJECT_ROOT, check=check)

def sync_assets():
    """使用 Robocopy 极速同步静态资源 (增量同步)"""
    print("[Phase] Syncing assets via Robocopy...")
    
    # 确保目标目录存在
    INTERNAL_DIR.mkdir(parents=True, exist_ok=True)
    
    sync_jobs = [
        # (Src, Dest_Relative_to_Internal)
        (PROJECT_ROOT / "src" / "web", "src/web"),
        (PROJECT_ROOT / "src" / "resources", "src/resources"),
        (PROJECT_ROOT / "resources", "resources"),  # 顶级资源目录 (帮助文档)
    ]
    
    # 检测 BLAST 路径
    local_bin = PROJECT_ROOT / "tools" / "ncbi_dist" / "bin"
    global_bin = Path(r"D:\Program Files\NCBI\blast-2.16.0+\bin")
    
    if (local_bin / "blastn.exe").exists():
        sync_jobs.append((local_bin, "bin"))
    elif global_bin.exists():
        print(f"  - Using global BLAST from: {global_bin}")
        sync_jobs.append((global_bin, "bin"))
    
    # 单个文件手动拷贝
    shutil.copy2(PROJECT_ROOT / "config.json", INTERNAL_DIR / "config.json")
    shutil.copy2(PROJECT_ROOT / "README.md", INTERNAL_DIR / "README.md")
    
    # 拷贝核心翻译数据/规则 (确保路径存在)
    trans_rule_src = PROJECT_ROOT / "src" / "utils" / "translation" / "classification_rules.json"
    if trans_rule_src.exists():
        trans_rule_dst = INTERNAL_DIR / "src" / "utils" / "translation"
        trans_rule_dst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(trans_rule_src, trans_rule_dst / "classification_rules.json")
        print("  - Copied classification rules.")

    for src, rel_dst in sync_jobs:
        if not src.exists():
            print(f"  [Warning] Source missing: {src}")
            continue
        dst = INTERNAL_DIR / rel_dst
        dst.mkdir(parents=True, exist_ok=True)
        # /E: 递归, /MT:32: 32线程并发, /R:0: 不重试, /XO: 仅同步较新文件(增量)
        cmd = ["robocopy", str(src), str(dst), "/E", "/MT:32", "/R:0", "/W:0", "/XO", "/NP"]
        # Robocopy 退出码 0-7 都是成功/部分成功
        subprocess.run(cmd, check=False)
        print(f"  - Synced: {rel_dst}")

def full_build():
    """执行 PyInstaller 核心构建 (不含资源扫描)"""
    print("[Phase] Running PyInstaller Core Build...")
    start_time = time.time()
    
    # 清理旧的编译缓存以确保干净
    build_dir = PROJECT_ROOT / "build"
    if build_dir.exists():
        shutil.rmtree(build_dir)

    cmd = ["pyinstaller", "--noconfirm", str(SPEC_FILE)]
    run_cmd(cmd)
    
    print(f"  - Core build finished in {time.time() - start_time:.2f}s")

def verify():
    """自检产物完整性 (资源审计)"""
    print("[Phase] Verifying build health & Resource Audit...")
    checks = [
        ("EXE 入口", DIST_DIR / "NCBI_BLAST_GUI.exe"),
        ("QtWebEngine", INTERNAL_DIR / "PyQt6/Qt6/bin/Qt6WebEngineCore.dll"),
        ("前端 index", INTERNAL_DIR / "src/web/index.html"),
        ("BLAST 引擎", INTERNAL_DIR / "bin/blastn.exe"),
        ("建树工具 (fasta2dissim)", INTERNAL_DIR / "bin/tree-tools/fasta2dissim.exe"),
        ("翻译分类规则", INTERNAL_DIR / "src/utils/translation/classification_rules.json"),
        ("帮助文档资源", INTERNAL_DIR / "resources/docs/help_zh.md"),
    ]
    
    failed = False
    for name, path in checks:
        if path.exists():
            print(f"  [OK] {name}")
        else:
            print(f"  [!!] {name} 缺失: {path}")
            failed = True
    
    if not failed:
        print("\n>>> 构建与资源审计成功！输出目录: " + str(DIST_DIR))
    else:
        print("\n>>> 构建或资源审计存在问题，请检查缺失项。")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Industrial Build Orchestrator")
    parser.add_argument("--fast", action="store_true", help="仅增量同步静态资源")
    parser.add_argument("--full", action="store_true", help="执行完整重新构建")
    args = parser.parse_args()

    if not args.fast and not args.full:
        print("Usage: python build_release.py --fast (Sync only) or --full (Full build)")
        sys.exit(0)

    if args.full:
        full_build()
    
    sync_assets()
    verify()
