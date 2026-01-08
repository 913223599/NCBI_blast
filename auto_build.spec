# -*- mode: python ; coding: utf-8 -*-
"""
自动生成的 PyInstaller spec 文件
用于打包 NCBI_BLAST_GUI 应用
项目根目录: D:/PycharmProjects/NCBI blast
"""

block_cipher = None

# 数据文件
datas = [
    (r'config.json', r'.'),
    (r'predefined_terms.csv', r'.'),
    (r'translation_data.csv', r'.'),
    (r'requirements.txt', r'.'),
    (r'src/utils/translation/biology_translator.py', r'src/utils/translation'),
    (r'src/utils/translation/blast_result_translator.py', r'src/utils/translation'),
    (r'src/utils/translation/qwen_translator.py', r'src/utils/translation'),
    (r'src/utils/translation/term_extractor.py', r'src/utils/translation'),
    (r'src/utils/translation/translation_data_manager.py', r'src/utils/translation'),
    (r'src/utils/translation/__init__.py', r'src/utils/translation'),
    (r'predefined_terms.csv', r'.'),
    (r'translation_data.csv', r'.'),
    (r'hit_sequences.fasta', r'.'),
    
]

# 隐藏导入
hiddenimports = [
    r'Bio',
    r'Bio.Blast',
    r'Bio.SeqIO',
    r'full_auto_package_fixed',
    r'lxml',
    r'pandas',
    r'requests',
    r'src',
    r'src.__main__',
    r'src.analysis',
    r'src.analysis.msa_engine',
    r'src.analysis.tree_visualizer',
    r'src.blast',
    r'src.blast.batch_processor',
    r'src.blast.executor',
    r'src.blast.local_blast',
    r'src.blast.parser',
    r'src.blast.result_cache',
    r'src.blast.result_converter',
    r'src.gui',
    r'src.gui.application_pyqt',
    r'src.gui.main_window_pyqt',
    r'src.gui.threads.processing_thread',
    r'src.gui.widgets',
    r'src.gui.widgets.api_key_dialog',
    r'src.gui.widgets.control_panel',
    r'src.gui.widgets.file_selector',
    r'src.gui.widgets.help_dialog',
    r'src.gui.widgets.parameter_settings',
    r'src.gui.widgets.result_viewer',
    r'src.gui.widgets.translation_debugger',
    r'src.gui_main_packaged',
    r'src.utils',
    r'src.utils.config_manager',
    r'src.utils.environment_checker',
    r'src.utils.file_handler',
    r'src.utils.hash_checker',
    r'src.utils.translation',
    r'src.utils.translation.biology_translator',
    r'src.utils.translation.blast_result_translator',
    r'src.utils.translation.qwen_translator',
    r'src.utils.translation.term_extractor',
    r'src.utils.translation.translation_data_manager',
    r'test_config_update',
    r'xml.etree.ElementTree',
    
]

a = Analysis(
    [r'src/gui_main_packaged.py'],  # 主入口文件
    pathex=[r'D:/PycharmProjects/NCBI blast/'],  # 当前目录作为路径扩展
    binaries=[],  # 二进制文件，通常为空
    datas=datas,  # 数据文件
    hiddenimports=hiddenimports,  # 隐藏导入
    hookspath=[],  # 额外的hook路径
    hooksconfig={},  # hook配置
    runtime_hooks=[],  # 运行时hook
    excludes=[  # 排除的模块
        'tkinter',
        'matplotlib',
        'PyQt5',
        'PySide2',
        'tensorflow',
        'torch',
        'keras',
        'scipy.spatial.cKDTree',
        'sklearn',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,  # 不使用归档
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,  # 脚本
    a.binaries,  # 二进制文件
    a.zipfiles,  # zip文件
    a.datas,  # 数据文件
    [],  # 选项
    name='NCBI_BLAST_GUI',  # 可执行文件名
    debug=False,  # 调试模式
    bootloader_ignore_signals=False,  # 忽略引导程序信号
    strip=False,  # 是否strip
    upx=True,  # UPX压缩
    upx_exclude=[],  # UPX排除
    runtime_tmpdir=None,  # 运行时临时目录
    console=False,  # 控制台模式，False表示窗口模式
    disable_windowed_traceback=False,  # 禁用窗口模式回溯
    argv_emulation=False,  # 参数模拟
    target_arch=None,  # 目标架构
    codesign_identity=None,  # 代码签名标识
    entitlements_file=None,  # 权限文件
    icon=None,  # 图标文件
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='NCBI_BLAST_GUI',  # 收集目录名
)
