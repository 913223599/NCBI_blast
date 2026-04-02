"""
NCBI BLAST 组件打包脚本

自动将源代码复制到独立组件目录
"""

import os
import shutil
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent
COMPONENT_ROOT = PROJECT_ROOT / "ncbi_blast_component"

# 需要复制的文件映射
# 格式：源目录 -> (目标目录，文件列表)
COPY_MAPPING = {
    # BLAST 核心模块
    "src/blast": ("ncbi_blast_component/blast", [
        "__init__.py",
        "engine.py",
        "executor.py",
        "local_blast.py",
        "manager.py",
        "parser.py",
        "result_converter.py",
        "database_manager.py",
        "batch_processor.py",
    ]),
    
    # GUI 组件
    "src/gui/widgets": ("ncbi_blast_component/gui/widgets", [
        "__init__.py",
        "blast_widget.py",
        "file_selector.py",
        "parameter_settings.py",
        "control_panel.py",
        "result_viewer.py",
        "task_name_dialog.py",
        "translation_debugger.py",
        "alignment_visualizer.py",
    ]),
    
    # GUI 线程
    "src/gui/threads": ("ncbi_blast_component/gui/threads", [
        "__init__.py",
        "processing_thread.py",
    ]),
    
    # 工具模块
    "src/utils": ("ncbi_blast_component/utils", [
        "__init__.py",
        "config_manager.py",
        "file_handler.py",
        "translation.py",
        "ui_translation_manager.py",
        "help_manager.py",
    ]),
    
    # 资源文件
    "src/resources/locales": ("ncbi_blast_component/resources/locales", [
        "zh_CN.json",
    ]),
}

def copy_file(src, dst):
    """复制单个文件"""
    try:
        shutil.copy2(src, dst)
        print(f"  ✓ {src.name}")
        return True
    except Exception as e:
        print(f"  ✗ {src.name}: {e}")
        return False

def copy_module(src_root, dst_root, files):
    """复制整个模块"""
    print(f"\n复制模块：{dst_root}")
    
    # 确保目标目录存在
    dst_root.mkdir(parents=True, exist_ok=True)
    
    # 复制文件
    copied = 0
    for file_name in files:
        src_file = src_root / file_name
        dst_file = dst_root / file_name
        
        if src_file.exists():
            if copy_file(src_file, dst_file):
                copied += 1
        else:
            print(f"  ⚠ 文件不存在：{src_file}")
    
    print(f"完成：{copied}/{len(files)} 个文件")
    return copied

def main():
    """主函数"""
    print("=" * 60)
    print("NCBI BLAST 组件打包工具")
    print("=" * 60)
    
    total_copied = 0
    total_files = 0
    
    for src_rel, (dst_rel, files) in COPY_MAPPING.items():
        src_root = PROJECT_ROOT / src_rel
        dst_root = PROJECT_ROOT / dst_rel
        
        if not src_root.exists():
            print(f"\n⚠ 源目录不存在：{src_root}")
            continue
        
        total_files += len(files)
        copied = copy_module(src_root, dst_root, files)
        total_copied += copied
    
    print("\n" + "=" * 60)
    print(f"打包完成！")
    print(f"总计：{total_copied}/{total_files} 个文件")
    print(f"组件目录：{COMPONENT_ROOT}")
    print("=" * 60)
    
    # 显示使用说明
    print("\n下一步操作:")
    print("1. 检查组件目录中的文件是否完整")
    print("2. 安装依赖：cd ncbi_blast_component && pip install -r requirements.txt")
    print("3. 测试组件：python example_integration.py")
    print("4. 复制到目标项目：Copy-Item ncbi_blast_component <目标路径> -Recurse")

if __name__ == "__main__":
    main()
