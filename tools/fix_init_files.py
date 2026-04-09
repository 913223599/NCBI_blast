"""
修复所有 __init__.py 文件中的导入路径
将 ncbi_blast_component.* 改为相对导入
"""

import re
from pathlib import Path

COMPONENT_ROOT = Path(__file__).resolve().parent.parent

print("=" * 60)
print("修复 __init__.py 文件中的导入路径")
print("=" * 60)

# 需要修复的文件
INIT_FILES = [
    COMPONENT_ROOT / "ncbi_blast_component" / "gui" / "__init__.py",
    COMPONENT_ROOT / "ncbi_blast_component" / "utils" / "__init__.py",
    COMPONENT_ROOT / "ncbi_blast_component" / "blast" / "__init__.py",
]

for file_path in INIT_FILES:
    if not file_path.exists():
        print(f"⚠ 文件不存在：{file_path}")
        continue
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original_content = content
        
        # 替换 ncbi_blast_component.gui 为 .gui
        content = re.sub(
            r'from ncbi_blast_component\.gui\.',
            'from .',
            content
        )
        
        # 替换 ncbi_blast_component.utils 为 .utils
        content = re.sub(
            r'from ncbi_blast_component\.utils\.',
            'from .',
            content
        )
        
        # 替换 ncbi_blast_component.blast 为 .blast
        content = re.sub(
            r'from ncbi_blast_component\.blast\.',
            'from .',
            content
        )
        
        # 如果文件内容有变化，保存修改
        if content != original_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"✓ 修复：{file_path.relative_to(COMPONENT_ROOT)}")
        else:
            print(f"⊘ 无需修改：{file_path.relative_to(COMPONENT_ROOT)}")
            
    except Exception as e:
        print(f"✗ 修复失败 {file_path}: {e}")
        import traceback
        traceback.print_exc()

print("\n" + "=" * 60)
print("修复完成！")
print("=" * 60)
