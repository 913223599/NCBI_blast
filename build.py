#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
PyInstaller打包脚本
使用--onedir模式打包NCBI BLAST工具
"""

import os
import sys
import subprocess
import argparse
from pathlib import Path

def build_with_command():
    """使用命令行参数执行PyInstaller打包"""
    # 获取项目根目录
    project_root = Path(__file__).parent.absolute()
    print(f"Project root: {project_root}")
    
    # 设置工作目录为项目根目录
    os.chdir(project_root)
    
    # 构建PyInstaller命令
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=NCBI_BLAST_Tool",
        "--onedir",  # 使用onedir模式
        "--windowed",  # GUI应用不显示控制台窗口
        "--noconfirm",  # 不确认覆盖
        "--hidden-import=PyQt6.sip",
        "--hidden-import=PyQt6.QtCore",
        "--hidden-import=PyQt6.QtGui", 
        "--hidden-import=PyQt6.QtWidgets",
        "--hidden-import=PyQt6.QtNetwork",
        "--collect-all=PyQt6",
        "--add-data=config.json;.",
        "--add-data=translation_data.csv;.",
        "--add-data=predefined_terms.csv;.",
        "--distpath=dist",
        "src/gui_main_pyqt.py"
    ]
    
    print("执行打包命令:")
    print(" ".join(cmd))
    
    # 执行打包命令
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print("打包成功完成!")
        print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print("打包失败:")
        print(e.stderr)
        return False

def build_with_spec():
    """使用spec文件执行PyInstaller打包"""
    # 获取项目根目录
    project_root = Path(__file__).parent.absolute()
    print(f"Project root: {project_root}")
    
    # 设置工作目录为项目根目录
    os.chdir(project_root)
    
    # 构建PyInstaller命令
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",  # 不确认覆盖
        "NCBI_BLAST_Tool.spec"
    ]
    
    print("执行打包命令:")
    print(" ".join(cmd))
    
    # 执行打包命令
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print("打包成功完成!")
        print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print("打包失败:")
        print(e.stderr)
        return False

def main():
    parser = argparse.ArgumentParser(description='NCBI BLAST Tool 打包脚本')
    parser.add_argument('--spec', action='store_true', help='使用spec文件打包')
    
    args = parser.parse_args()
    
    if args.spec:
        print("使用spec文件进行打包...")
        build_with_spec()
    else:
        print("使用命令行参数进行打包...")
        build_with_command()

if __name__ == "__main__":
    main()