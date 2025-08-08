"""
NCBI BLAST 搜索工具主程序
支持批量查询和多线程处理
支持命令行和GUI两种模式
"""

import argparse
import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

# 添加src目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from .blast.batch_processor import BatchProcessor


def select_files():
    """
    打开文件选择对话框，让用户选择序列文件
    
    Returns:
        list: 选择的文件路径列表
    """
    root = tk.Tk()
    root.withdraw()  # 隐藏主窗口
    
    # 打开文件选择对话框
    file_paths = filedialog.askopenfilenames(
        title="选择序列文件",
        filetypes=[("Sequence files", "*.seq"), ("FASTA files", "*.fasta *.fa"), ("All files", "*.*")]
    )
    
    root.destroy()
    return list(file_paths)


def run_command_line_mode():
    """
    运行命令行模式
    """
    print("NCBI BLAST 搜索工具")
    print("==================")
    
    # 询问用户如何选择文件
    print("请选择操作:")
    print("1. 选择文件进行批量搜索")
    print("2. 使用sequences目录下的所有序列文件")
    
    choice = input("请输入选项 (1 或 2): ").strip()
    
    sequence_files = []
    
    if choice == "1":
        # 用户选择文件
        print("请在弹出的文件选择对话框中选择序列文件...")
        sequence_files = select_files()
        if not sequence_files:
            print("未选择任何文件，程序退出。")
            return
    elif choice == "2":
        # 使用sequences目录下的所有序列文件
        sequences_dir = Path("sequences")
        if sequences_dir.exists():
            sequence_files = list(sequences_dir.glob("*.seq")) + list(sequences_dir.glob("*.fasta")) + list(sequences_dir.glob("*.fa"))
            if not sequence_files:
                print("sequences目录中没有找到序列文件")
                return
            sequence_files = [str(f) for f in sequence_files]
            print(f"找到 {len(sequence_files)} 个序列文件")
        else:
            print("sequences目录不存在")
            return
    else:
        print("无效选项，程序退出。")
        return
    
    # 询问线程数
    try:
        max_workers = int(input("请输入线程数 (默认为3): ").strip() or "3")
        if max_workers < 1 or max_workers > 10:
            print("线程数必须在1-10之间，使用默认值3")
            max_workers = 3
    except ValueError:
        print("无效输入，使用默认线程数3")
        max_workers = 3
    
    # 创建批处理处理器
    processor = BatchProcessor(max_workers=max_workers)
    
    # 处理序列文件
    results = processor.process_sequences(sequence_files)
    
    # 显示处理总结
    processor.print_summary(results)





def main():
    """
    主程序入口
    """
    # 创建命令行参数解析器
    parser = argparse.ArgumentParser(description="NCBI BLAST 搜索工具")
    parser.add_argument(
        "--gui", 
        action="store_true", 
        help="使用图形界面模式"
    )


if __name__ == "__main__":
    main()