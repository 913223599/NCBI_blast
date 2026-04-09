"""
批量修复组件中的导入路径
将错误的相对导入改为正确的相对导入
"""

import re
from pathlib import Path

COMPONENT_ROOT = Path(__file__).resolve().parent.parent / "ncbi_blast_component"

print("=" * 60)
print("批量修复导入路径")
print("=" * 60)

# 需要扫描的文件目录
dirs_to_scan = [
    COMPONENT_ROOT / "gui" / "widgets",
    COMPONENT_ROOT / "gui" / "threads",
]

# 修复映射
fixes = {
    # gui/widgets/ 下的文件需要从 gui.utils 改为 ...utils 或 ncbi_blast_component.utils
    r'from \.\.utils\.config_manager import': 'from ncbi_blast_component.utils.config_manager import',
    r'from \.\.utils\.ui_translation_manager import': 'from ncbi_blast_component.utils.ui_translation_manager import',
    r'from \.\.utils\.file_handler import': 'from ncbi_blast_component.utils.file_handler import',
    r'from \.\.utils\.translation import': 'from ncbi_blast_component.utils.translation import',
    r'from \.\.threads\.processing_thread import': 'from ncbi_blast_component.gui.threads.processing_thread import',
    r'from \.\.blast\.local_blast import': 'from ncbi_blast_component.blast.local_blast import',
}

fixed_count = 0

for scan_dir in dirs_to_scan:
    if not scan_dir.exists():
        print(f"⚠ 目录不存在：{scan_dir}")
        continue
    
    for py_file in scan_dir.glob("*.py"):
        try:
            with open(py_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            original_content = content
            
            # 应用所有修复规则
            for pattern, replacement in fixes.items():
                if re.search(pattern, content):
                    content = re.sub(pattern, replacement, content)
                    print(f"✓ 修复 {py_file.name}: {pattern[:30]}... -> {replacement[:30]}...")
                    fixed_count += 1
            
            # 保存修改
            if content != original_content:
                with open(py_file, 'w', encoding='utf-8') as f:
                    f.write(content)
                    
        except Exception as e:
            print(f"✗ 处理 {py_file.name} 失败：{e}")

print("\n" + "=" * 60)
print(f"共修复 {fixed_count} 处导入")
print("=" * 60)
