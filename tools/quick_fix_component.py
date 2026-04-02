"""
一键修复 NCBI BLAST 组件
采用最小化修复方案，让组件可以独立运行
"""

from pathlib import Path

COMPONENT_ROOT = Path(__file__).resolve().parent.parent / "ncbi_blast_component"

print("=" * 60)
print("一键修复 NCBI BLAST 组件")
print("=" * 60)

# 修复 1: 简化 widgets/__init__.py
print("\n[修复 1] 简化 widgets/__init__.py...")
widgets_init = COMPONENT_ROOT / "gui" / "widgets" / "__init__.py"

if widgets_init.exists():
    content = """\"\"\"
GUI 组件模块初始化文件
仅导出实际存在的组件
\"\"\"

# 注意：以下组件在当前版本中暂不可用
# - ApiKeyDialog (需要 API 密钥管理功能)
# - HelpViewerDialog (需要帮助系统)
# - DatabaseManagerDialog (需要数据库管理)
# - SetupWizard (需要安装向导)
# - WebContainer (需要 Web 组件)

# 当前可用的组件已在 blast_widget.py 中直接使用
# 此文件暂时保持简洁，避免导入不存在的模块

__all__ = []

# 如需使用具体组件，请直接导入:
# from .blast_widget import BlastWidget
# from .file_selector import FileSelectorWidget
# from .parameter_settings import ParameterSettingsWidget
# from .control_panel import ControlPanelWidget
# from .result_viewer import ResultViewerWidget
# from .translation_debugger import TranslationDebuggerDialog
# from .task_name_dialog import TaskNameDialog
# from .alignment_visualizer import AlignmentVisualizer
"""
    
    with open(widgets_init, 'w', encoding='utf-8') as f:
        f.write(content)
    print("✓ 已简化 widgets/__init__.py")
else:
    print(f"✗ 文件不存在：{widgets_init}")

# 修复 2: 在 local_blast.py 中添加别名
print("\n[修复 2] 添加 LocalBlast 别名...")
local_blast_file = COMPONENT_ROOT / "blast" / "local_blast.py"

if local_blast_file.exists():
    with open(local_blast_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 检查是否已有别名
    if "LocalBlast =" not in content:
        # 在文件末尾添加别名
        content += "\n\n# 为了兼容性的别名\nLocalBlast = LocalBlastExecutor\n"
        
        with open(local_blast_file, 'w', encoding='utf-8') as f:
            f.write(content)
        print("✓ 已添加 LocalBlast 别名")
    else:
        print("⊘ LocalBlast 别名已存在")
else:
    print(f"✗ 文件不存在：{local_blast_file}")

# 修复 3: 更新主 __init__.py
print("\n[修复 3] 更新主 __init__.py...")
main_init = COMPONENT_ROOT / "__init__.py"

if main_init.exists():
    content = """\"\"\"
一个可独立使用的 NCBI BLAST 图形化分析组件，基于 PyQt6 开发。
旨在提供完整的本地 BLAST 分析功能，并能轻松集成到其他 Python 应用程序中。

__version__ = "1.0.0"
__author__ = "NCBI BLAST Team"
\"\"\"

# 导出核心组件
from .gui.widgets.blast_widget import BlastWidget
from .gui.widgets.file_selector import FileSelectorWidget
from .gui.widgets.parameter_settings import ParameterSettingsWidget
from .gui.widgets.control_panel import ControlPanelWidget
from .gui.widgets.result_viewer import ResultViewerWidget

# 导出工具模块
from .utils.config_manager import ConfigManager, get_config_manager
from .utils.file_handler import FileHandler

# 导出 BLAST 核心模块
from .blast.local_blast import LocalBlast, LocalBlastExecutor, LocalBatchProcessor
from .blast.manager import get_blast_manager

__all__ = [
    # 核心组件
    'BlastWidget',
    'FileSelectorWidget',
    'ParameterSettingsWidget',
    'ControlPanelWidget',
    'ResultViewerWidget',
    
    # 工具模块
    'ConfigManager',
    'get_config_manager',
    'FileHandler',
    
    # BLAST 引擎
    'LocalBlast',
    'LocalBlastExecutor',
    'LocalBatchProcessor',
    'get_blast_manager',
]
"""
    
    with open(main_init, 'w', encoding='utf-8') as f:
        f.write(content)
    print("✓ 已更新主 __init__.py")
else:
    print(f"✗ 文件不存在：{main_init}")

# 修复 4: 创建简单的测试文件
print("\n[修复 4] 创建验证测试文件...")
test_file = COMPONENT_ROOT / "verify_fix.py"

test_content = '''\"\"\"
验证修复是否成功
\"\"\"
import sys
from pathlib import Path

# 添加当前目录到路径
current_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(current_dir))

print("=" * 60)
print("验证 NCBI BLAST 组件修复")
print("=" * 60)

success_count = 0
total_tests = 0

# 测试 1: 导入主包
print("\\n[测试 1] 导入 ncbi_blast_component 包...")
try:
    import ncbi_blast_component
    print(f"✓ 包导入成功")
    print(f"  版本：{getattr(ncbi_blast_component, '__version__', '未知')}")
    success_count += 1
except Exception as e:
    print(f"✗ 包导入失败：{e}")
total_tests += 1

# 测试 2: 导入 BlastWidget
print("\\n[测试 2] 导入 BlastWidget...")
try:
    from ncbi_blast_component import BlastWidget
    print("✓ BlastWidget 导入成功")
    success_count += 1
except Exception as e:
    print(f"✗ BlastWidget 导入失败：{e}")
total_tests += 1

# 测试 3: 导入 ConfigManager
print("\\n[测试 3] 导入 ConfigManager...")
try:
    from ncbi_blast_component import ConfigManager, get_config_manager
    print("✓ ConfigManager 导入成功")
    success_count += 1
except Exception as e:
    print(f"✗ ConfigManager 导入失败：{e}")
total_tests += 1

# 测试 4: 导入 LocalBlast
print("\\n[测试 4] 导入 LocalBlast...")
try:
    from ncbi_blast_component import LocalBlast, LocalBlastExecutor, LocalBatchProcessor
    print("✓ LocalBlast 导入成功")
    success_count += 1
except Exception as e:
    print(f"✗ LocalBlast 导入失败：{e}")
total_tests += 1

# 测试 5: 实例化 BlastWidget (需要 PyQt6)
print("\\n[测试 5] 实例化 BlastWidget...")
try:
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    
    widget = BlastWidget()
    print("✓ BlastWidget 实例化成功")
    success_count += 1
except Exception as e:
    print(f"✗ BlastWidget 实例化失败：{e}")
total_tests += 1

# 总结
print("\\n" + "=" * 60)
print(f"测试结果：{success_count}/{total_tests} 通过")
if success_count == total_tests:
    print("🎉 所有测试通过！组件可以独立运行！")
else:
    print("⚠️ 部分测试失败，请检查错误信息")
print("=" * 60)
'''

with open(test_file, 'w', encoding='utf-8') as f:
    f.write(test_content)
print("✓ 已创建验证测试文件 verify_fix.py")

print("\n" + "=" * 60)
print("修复完成！")
print("=" * 60)
print("\n下一步操作:")
print(f'1. 运行验证测试:')
print(f'   cd "{COMPONENT_ROOT}"')
print(f'   python verify_fix.py')
print(f'\n2. 如果所有测试通过，组件已可独立运行！')
print(f'\n3. 使用示例:')
print(f'''
   from ncbi_blast_component import BlastWidget
   from PyQt6.QtWidgets import QApplication, QMainWindow
   import sys
   
   app = QApplication(sys.argv)
   window = QMainWindow()
   window.setCentralWidget(BlastWidget())
   window.show()
   sys.exit(app.exec())
''')
print("=" * 60)
