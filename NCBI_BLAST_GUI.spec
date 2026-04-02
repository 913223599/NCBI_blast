# -*- mode: python ; coding: utf-8 -*-
"""
NCBI BLAST GUI 标准打包配置文件 (Industrial Standard Spec)
"""

import sys
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# =============================================================================
# 1. 资源配置 (Resource Configuration)
# =============================================================================

# BLAST 工具集 (Binaries)
# 将 tools/ncbi_dist/bin 下的所有内容打包到 _internal/bin
# 配合 src/gui_main_packaged.py 中的 runtime PATH 配置使用
bin_datas = []
if os.path.exists('tools/ncbi_dist/bin'):
    bin_datas.append(('tools/ncbi_dist/bin', 'bin'))

# Web 前端资源 & 翻译数据
web_datas = [
    ('src/web', 'src/web'),          # 前端核心
    ('src/resources', 'src/resources'), # 语言包等
    ('config.json', '.'),            # 默认配置
    ('README.md', '.'),
]

# 汇总所有 datas (Tree 形式在 Analysis 中处理)
all_datas = []
# 注意: 在 spec 中不能直接用 Tree 放入 datas 列表，需在 Analysis 参数中使用 (或转换为 tuples)
# 这里我们采用 Analysis.datas 手动扩展的方式更稳健，或者使用 Tree 对象

# =============================================================================
# 2. 极限排除列表 (Aggressive Exclusion List)
# =============================================================================

# 这些库体积巨大且本项目未使用，屏蔽它们可提速 300%
excludes = [
    'torch', 'tensorflow', 'transformers', 'torchvision', 'torchaudio',
    'cv2', 'matplotlib.tests', 'numpy.f2py', 'IPython', 
    'jupyter', 'notebook', 'nbconvert', 'nbformat', 'jedi',
    'pytest', 'unittest', 
    'tkinter', 'tcl', 'tk', 'idlelib',
    'win32com', 'pythoncom', 'adodbapi',
    'scipy.spatial.tests', 'scipy.sparse.tests',
    'cryptography', 'pycryptodome', 
    'PyQt5', 'PySide2', 'PySide6'
]

hidden_imports = [
    'PyQt6.QtCore', 'PyQt6.QtGui', 'PyQt6.QtWidgets', 
    'PyQt6.QtWebEngineCore', 'PyQt6.QtWebEngineWidgets',
    'pandas', 'numpy', 'requests', 'Bio', 'Bio.Blast'
]

a = Analysis(
    ['src/gui_main_packaged.py'],
    pathex=[],
    binaries=[],
    datas=[], # 静态资源将通过 build_release.py 手动同步
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
    optimize=0, # 必须设置为 0，否则 numpy 等库会因丢失 docstring 报错
)

# =============================================================================
# 3. 资源配置 (通过 build_release.py 同步，此处仅保留元数据)
# =============================================================================

# 我们不再在 Spec 中使用 Tree()，因为 PyInstaller 的 Tree 扫描非常慢且不可控。
# 所有的 src/web, bin 等目录由 build_release.py 在构建后使用 robocopy 增量更新。

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='NCBI_BLAST_GUI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False, # 彻底关闭 UPX，提速 60%
    console=False,
    version='version_info.txt',
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False, # 彻底关闭 UPX
    name='NCBI_BLAST_GUI',
)

