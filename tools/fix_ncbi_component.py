"""
修复 ncbi_blast_component 组件的缺失文件

此脚本将：
1. 从 src 目录复制缺失的文件到组件目录
2. 修复导入路径
3. 验证修复结果
"""

import shutil
from pathlib import Path
import os

# 获取项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
COMPONENT_ROOT = PROJECT_ROOT / "ncbi_blast_component"

print("=" * 60)
print("开始修复 NCBI BLAST 组件")
print("=" * 60)

# 需要复制的文件清单
FILES_TO_COPY = [
    # Utils - translation 模块（整个目录）
    ("src/utils/translation", "ncbi_blast_component/utils/translation"),
]

# 需要创建的 __init__.py 文件内容
INIT_FILES = {
    "ncbi_blast_component/utils/translation/__init__.py": """\"\"\"
翻译模块初始化文件
\"\"\"

from .biology_translator import get_biology_translator, get_global_biology_translator
from .blast_result_translator import get_blast_result_translator
from .qwen_translator import get_qwen_translator
from .translation_data_manager import get_translation_data_manager

__all__ = [
    'get_biology_translator',
    'get_global_biology_translator',
    'get_qwen_translator',
    'get_translation_data_manager',
    'get_blast_result_translator'
]
"""
}

# 1. 复制文件
print("\n[步骤 1] 复制缺失的文件...")
for src_rel, dest_rel in FILES_TO_COPY:
    src_path = PROJECT_ROOT / src_rel
    dest_path = PROJECT_ROOT / dest_rel
    
    if not src_path.exists():
        print(f"✗ 源文件不存在：{src_path}")
        continue
    
    try:
        # 如果是目录，使用 copytree
        if src_path.is_dir():
            if dest_path.exists():
                print(f"⚠ 目标目录已存在，跳过：{dest_path}")
            else:
                shutil.copytree(src_path, dest_path)
                print(f"✓ 复制目录：{src_rel} -> {dest_rel}")
        else:
            shutil.copy2(src_path, dest_path)
            print(f"✓ 复制文件：{src_rel} -> {dest_rel}")
    except Exception as e:
        print(f"✗ 复制失败：{e}")

# 2. 创建必要的 __init__.py 文件
print("\n[步骤 2] 创建/更新 __init__.py 文件...")
for file_path_str, content in INIT_FILES.items():
    file_path = PROJECT_ROOT / file_path_str
    try:
        # 确保父目录存在
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 写入文件
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"✓ 创建：{file_path_str}")
    except Exception as e:
        print(f"✗ 创建失败：{e}")

# 3. 修复 blast_widget.py 中的导入路径
print("\n[步骤 3] 修复导入路径...")
blast_widget_path = COMPONENT_ROOT / "gui" / "widgets" / "blast_widget.py"

if blast_widget_path.exists():
    try:
        with open(blast_widget_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 修复 batch_processor 导入
        old_import = "from ..batch_processor import BatchProcessor, MultiSequenceBatchProcessor"
        new_import = """# BatchProcessor 已从 local_blast 模块导入
from ..blast.local_blast import LocalBatchProcessor as MultiSequenceBatchProcessor
# 为了兼容性保留 BatchProcessor 别名
BatchProcessor = MultiSequenceBatchProcessor"""
        
        if old_import in content:
            content = content.replace(old_import, new_import)
            print(f"✓ 修复 batch_processor 导入")
        else:
            print(f"⚠ 未找到需要修复的 batch_processor 导入")
        
        # 修复 elastic_blast_processor 导入
        old_elastic = "from ..elastic_blast_processor import ElasticBlastProcessor"
        new_elastic = "# Elastic BLAST 功能暂不可用\n# from ..elastic_blast_processor import ElasticBlastProcessor\nElasticBlastProcessor = None"
        
        if old_elastic in content:
            content = content.replace(old_elastic, new_elastic)
            print(f"✓ 修复 elastic_blast_processor 导入")
        else:
            print(f"⚠ 未找到需要修复的 elastic_blast_processor 导入")
        
        # 保存修改后的文件
        with open(blast_widget_path, 'w', encoding='utf-8') as f:
            f.write(content)
            
    except Exception as e:
        print(f"✗ 修复导入路径失败：{e}")
else:
    print(f"✗ blast_widget.py 不存在：{blast_widget_path}")

# 4. 更新 blast/__init__.py 导出 LocalBatchProcessor
print("\n[步骤 4] 更新 blast 模块导出...")
blast_init_path = COMPONENT_ROOT / "blast" / "__init__.py"

if blast_init_path.exists():
    try:
        with open(blast_init_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 添加 LocalBatchProcessor 导出
        if 'LocalBatchProcessor' not in content:
            # 在 imports 中添加
            import_line = "from .local_blast import LocalBlastExecutor, LocalBatchProcessor"
            if "from .local_blast import" in content:
                # 替换现有导入
                content = content.replace(
                    "from .local_blast import LocalBlast",
                    "from .local_blast import LocalBlast, LocalBlastExecutor, LocalBatchProcessor"
                )
            else:
                # 添加新导入
                content = content.replace(
                    "from .manager import BlastManager, get_blast_manager",
                    "from .manager import BlastManager, get_blast_manager\nfrom .local_blast import LocalBlast, LocalBlastExecutor, LocalBatchProcessor"
                )
            
            # 在 __all__ 中添加
            if "'LocalBatchProcessor'" not in content:
                content = content.replace(
                    "'get_blast_manager'",
                    "'get_blast_manager',\n    'LocalBlast',\n    'LocalBlastExecutor',\n    'LocalBatchProcessor'"
                )
            
            with open(blast_init_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"✓ 更新 blast/__init__.py")
        else:
            print(f"⚠ LocalBatchProcessor 已经导出")
            
    except Exception as e:
        print(f"✗ 更新 blast/__init__.py 失败：{e}")
else:
    print(f"✗ blast/__init__.py 不存在")

print("\n" + "=" * 60)
print("修复完成！")
print("=" * 60)
print("\n下一步操作:")
print("1. 运行测试脚本验证:")
print(f'   cd "{COMPONENT_ROOT}"')
print("   python test_component.py")
print("\n2. 如果仍有问题，请检查错误信息并手动调整导入路径")
print("=" * 60)
