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
    (r'src/cache/03fc2f67c3e6f65ac8d621ff52de4c06.json', r'.'),
    (r'src/cache/1633898fa7b1591cf6c18aaff823cabb.json', r'.'),
    (r'src/cache/1679760242d812d9b6dcddcd6a262b31.json', r'.'),
    (r'src/cache/1ebe0c9fbd8f775ac163b509e3024ecc.json', r'.'),
    (r'src/cache/20152b11770d97c111249365a2ea0108.json', r'.'),
    (r'src/cache/254830f46faa9cf87fbbad4808bacdb9.json', r'.'),
    (r'src/cache/25aba0d23d9866ae890da3fa97a4ce2f.json', r'.'),
    (r'src/cache/2d1eaeb57990854990dd1eb103673e48.json', r'.'),
    (r'src/cache/2d3aa18e6310de0514ea75023abb597d.json', r'.'),
    (r'src/cache/2f7a1a4dd050c800584b3acffd232750.json', r'.'),
    (r'src/cache/300847f914bbebf68347c84f021a8d86.json', r'.'),
    (r'src/cache/334045d45752e074a8daff19fce5bfeb.json', r'.'),
    (r'src/cache/372877cb64a8bf611b8b29f9d6d5a520.json', r'.'),
    (r'src/cache/3ea29158dd52a325e40faafea98b0a58.json', r'.'),
    (r'src/cache/416ba219dd310985dd20d76404225e5c.json', r'.'),
    (r'src/cache/41c49ebbbc75b287165c7c8b9b63d21a.json', r'.'),
    (r'src/cache/4209bc199e62049ce82a1b062d30f339.json', r'.'),
    (r'src/cache/45ba3f6f356f9e71bf266ff30f93787a.json', r'.'),
    (r'src/cache/49b52190d1993bc52d732aa3ac20cb7d.json', r'.'),
    (r'src/cache/538b500c442e53acaad14ecc27a83f63.json', r'.'),
    (r'src/cache/571f80951249208d1dd7818099dfc3fb.json', r'.'),
    (r'src/cache/5cf590579fe9a117d5afb688e4dddc61.json', r'.'),
    (r'src/cache/5e5c51328692802d1676bb44b35d781c.json', r'.'),
    (r'src/cache/6135389ed1cea1d5037dec978b469b0f.json', r'.'),
    (r'src/cache/6491fd56b115600d83d71043d67dc266.json', r'.'),
    (r'src/cache/64d11e9c07c2667f8ca8fd2c0075830b.json', r'.'),
    (r'src/cache/6f043995c8592f4830196493fd0c2a85.json', r'.'),
    (r'src/cache/6ff7986dfac0c54dd6609bd0023831f2.json', r'.'),
    (r'src/cache/71308e6bf686eb31b0353d681144107a.json', r'.'),
    (r'src/cache/72e5c556a2a8b32d0725619443df1994.json', r'.'),
    (r'src/cache/798238a5efc04203f34b51930532141c.json', r'.'),
    (r'src/cache/7a4ed848793fc81e450f8aa8bfba27e4.json', r'.'),
    (r'src/cache/7bdc33e99eced1c2f1b854da2811fa4d.json', r'.'),
    (r'src/cache/7f45dcda7849748dc050a84d4c46d108.json', r'.'),
    (r'src/cache/8253284dae7ea67803d516eda6bfdbc5.json', r'.'),
    (r'src/cache/84a70d600b36eac89b8850769ded3a39.json', r'.'),
    (r'src/cache/8a537493d70f06b4efddc82d55a98bb4.json', r'.'),
    (r'src/cache/8e55457af36f495f2908677a6bec3a4f.json', r'.'),
    (r'src/cache/950fc7412072ff51a72b83c96cf542d0.json', r'.'),
    (r'src/cache/a16d79adc0d4cab39c481cb13c8d7e47.json', r'.'),
    (r'src/cache/a1819964fc3ca35abc2824bf7f6b4671.json', r'.'),
    (r'src/cache/a60e3c83b04cd8bae09700583a474d32.json', r'.'),
    (r'src/cache/b47df58250612b44a8757aed9a4f3a40.json', r'.'),
    (r'src/cache/b68fd094ec86cb1471e15cd48298f1da.json', r'.'),
    (r'src/cache/b763a58c4abc75467685334ecf3c83bf.json', r'.'),
    (r'src/cache/b7ce25ead02042ed388767a1c8ce9ab7.json', r'.'),
    (r'src/cache/b85fc4334aa321b51e5e48fdba45896d.json', r'.'),
    (r'src/cache/b8ed7df3bbd48e3924783846a887b608.json', r'.'),
    (r'src/cache/b95e33cda2639b4d85bed3c209275e40.json', r'.'),
    (r'src/cache/bbaeaa421fb9d20192072e9945dd1809.json', r'.'),
    (r'src/cache/c6139f58ebced760e5e91f27b269ae2b.json', r'.'),
    (r'src/cache/c96803711e48d0424f0e4a9ac41435bd.json', r'.'),
    (r'src/cache/c98fb8d7f925a72e82284206ffe41125.json', r'.'),
    (r'src/cache/ca3c377272d7162f5f62b1ab2366e31b.json', r'.'),
    (r'src/cache/ca523dcd088a7025ade1b6efffad0111.json', r'.'),
    (r'src/cache/cad4321ce860c066ae8c35cfdc8aa28b.json', r'.'),
    (r'src/cache/cbe2e839c46867e764bcf343cd050188.json', r'.'),
    (r'src/cache/cf52237bbbfccf00775f3392e6a6f62b.json', r'.'),
    (r'src/cache/cfa20d9e17a98335daab4ccbc32c6463.json', r'.'),
    (r'src/cache/d66fb081f3431a7b33d06a0a04b1d1a9.json', r'.'),
    (r'src/cache/d7a65c66196c30d1cae7071a46101e76.json', r'.'),
    (r'src/cache/e1fe03e7df24462e9b2dc732b0437c00.json', r'.'),
    (r'src/cache/e32424257c07415adb7df75595f138f2.json', r'.'),
    (r'src/cache/e4ac323edd675acd515945afd0944f06.json', r'.'),
    (r'src/cache/ef262a00ecb49c8519e9586797a70754.json', r'.'),
    (r'src/cache/f0c15244f0ec923d082e4badc2a3982d.json', r'.'),
    (r'src/cache/f2a1aa78c0a33019216683f09a6ef267.json', r'.'),
    (r'src/cache/f4f345e0d45b0945c64bb14c48b5b704.json', r'.'),
    (r'src/cache/f5973cab7888e5212618411a0830cc90.json', r'.'),
    (r'src/cache/f73dbb644e78e79ecb55125f3ec91366.json', r'.'),
    (r'src/cache/f8f133fa6f162df22beb5d388bb79295.json', r'.'),
    (r'src/cache/fa9ac098dc164fac5a8089eb52d08e9d.json', r'.'),
    (r'src/cache/fd95d4f661e65886fcb6953c2aeaa645.json', r'.'),
    (r'src/cache/ff67762812e94896b43d493c8cd3200e.json', r'.'),
    (r'src/results/20260108_154359/hit_sequences_phage_10109074_blast_result.csv', r'.'),
    (r'src/results/20260108_154359/hit_sequences_phage_10115553_blast_result.csv', r'.'),
    (r'src/results/20260108_154359/hit_sequences_phage_10133736_blast_result.csv', r'.'),
    (r'src/results/20260108_154359/hit_sequences_phage_10133761_blast_result.csv', r'.'),
    (r'src/results/20260108_154359/hit_sequences_phage_10146935_blast_result.csv', r'.'),
    (r'src/results/20260108_154359/hit_sequences_phage_10271438_blast_result.csv', r'.'),
    (r'src/results/20260108_154359/hit_sequences_phage_1029515_blast_result.csv', r'.'),
    (r'src/results/20260108_154359/hit_sequences_phage_10429037_blast_result.csv', r'.'),
    (r'src/results/20260108_154359/hit_sequences_phage_10592026_blast_result.csv', r'.'),
    (r'src/results/20260108_154359/hit_sequences_phage_10965508_blast_result.csv', r'.'),
    (r'src/results/20260108_154359/hit_sequences_phage_11131646_blast_result.csv', r'.'),
    (r'src/results/20260108_154359/hit_sequences_phage_11298483_blast_result.csv', r'.'),
    (r'src/results/20260108_154359/hit_sequences_phage_12128796_blast_result.csv', r'.'),
    (r'src/results/20260108_154359/hit_sequences_phage_12141095_blast_result.csv', r'.'),
    (r'src/results/20260108_154359/hit_sequences_phage_12218757_blast_result.csv', r'.'),
    (r'src/results/20260108_154359/hit_sequences_phage_12241748_blast_result.csv', r'.'),
    (r'src/results/20260108_154359/hit_sequences_phage_12392620_blast_result.csv', r'.'),
    (r'src/results/20260108_154359/hit_sequences_phage_12392667_blast_result.csv', r'.'),
    (r'src/results/20260108_154359/hit_sequences_phage_12392716_blast_result.csv', r'.'),
    (r'src/results/20260108_154359/hit_sequences_phage_12421640_blast_result.csv', r'.'),
    (r'src/results/20260108_154359/hit_sequences_phage_12463887_blast_result.csv', r'.'),
    (r'src/results/20260108_154359/hit_sequences_phage_12920168_blast_result.csv', r'.'),
    (r'src/results/20260108_154359/hit_sequences_phage_13112795_blast_result.csv', r'.'),
    (r'src/results/20260108_154359/ZR-1.1492R.SP508270590001_ZR-1.1492R.SP508270590001_blast_result.csv', r'.'),
    (r'src/results/20260108_163950/ZR-1.1492R.SP508270590001_blast_result.csv', r'.'),
    (r'src/results/20260108_164503/70.1492R.SP506300620070_blast_result.csv', r'.'),
    (r'src/results/20260108_164503/71.1492R.SP506300620071_blast_result.csv', r'.'),
    (r'src/results/20260108_164503/72.1492R.SP506300620072_blast_result.csv', r'.'),
    (r'src/results/20260108_171330/hit_sequences_phage_13168448_blast_result.csv', r'.'),
    (r'src/results/20260108_184444/hit_sequences_phage_13911074_blast_result.csv', r'.'),
    (r'src/results/20260108_184652/96.1492R.SP506300620096_96.1492R.SP506300620096_blast_result.csv', r'.'),
    (r'src/results/20260108_184652/97.1492R.SP506300620097_97.1492R.SP506300620097_blast_result.csv', r'.'),
    (r'src/results/20260108_184652/98.1492R.SP506300620098_98.1492R.SP506300620098_blast_result.csv', r'.'),
    (r'src/results/20260108_184652/hit_sequences_phage_13750375_blast_result.csv', r'.'),
    (r'src/results/20260108_184652/hit_sequences_phage_15541525_blast_result.csv', r'.'),
    (r'src/results/20260108_184652/hit_sequences_phage_15543458_blast_result.csv', r'.'),
    (r'src/results/20260108_184652/hit_sequences_phage_15546918_blast_result.csv', r'.'),
    (r'src/results/20260108_184652/hit_sequences_phage_15548467_blast_result.csv', r'.'),
    (r'src/results/20260108_184652/hit_sequences_phage_1630508_blast_result.csv', r'.'),
    (r'src/results/20260108_184652/hit_sequences_phage_388832_blast_result.csv', r'.'),
    (r'src/results/20260108_184652/hit_sequences_phage_390778_blast_result.csv', r'.'),
    (r'src/results/20260108_184652/hit_sequences_phage_6074510_blast_result.csv', r'.'),
    (r'src/results/20260108_184652/hit_sequences_phage_6296379_blast_result.csv', r'.'),
    (r'src/results/20260108_184652/hit_sequences_phage_7291514_blast_result.csv', r'.'),
    (r'src/results/20260108_184652/hit_sequences_phage_739573_blast_result.csv', r'.'),
    (r'src/results/20260108_184652/hit_sequences_phage_7414921_blast_result.csv', r'.'),
    (r'src/results/20260108_184652/hit_sequences_phage_7693405_blast_result.csv', r'.'),
    (r'src/results/20260108_184652/hit_sequences_phage_7781077_blast_result.csv', r'.'),
    (r'src/results/20260108_184652/hit_sequences_phage_8018235_blast_result.csv', r'.'),
    (r'src/results/20260108_184652/hit_sequences_phage_8998904_blast_result.csv', r'.'),
    (r'src/results/20260108_184652/hit_sequences_phage_9074532_blast_result.csv', r'.'),
    (r'src/results/20260108_184652/hit_sequences_phage_9170729_blast_result.csv', r'.'),
    (r'src/results/20260108_184652/hit_sequences_phage_9247675_blast_result.csv', r'.'),
    (r'src/results/20260108_184652/hit_sequences_phage_9305197_blast_result.csv', r'.'),
    (r'src/results/20260108_184652/hit_sequences_phage_9565915_blast_result.csv', r'.'),
    (r'src/results/20260108_184652/hit_sequences_phage_9701888_blast_result.csv', r'.'),
    (r'src/results/20260108_184652/hit_sequences_phage_985351_blast_result.csv', r'.'),
    (r'src/results/20260108_184652/hit_sequences_phage_9969585_blast_result.csv', r'.'),
    (r'src/results/20260108_200506/68.1492R.SP506300620068_blast_result.csv', r'.'),
    (r'src/results/20260108_200506/69.1492R.SP506300620069_blast_result.csv', r'.'),
    (r'src/results/20260108_201812/46.1492R.SP506300620046_blast_result.csv', r'.'),
    (r'src/results/20260108_201938/100.1492R.SP506300620100_blast_result.csv', r'.'),
    (r'src/results/20260108_201938/99.1492R.SP506300620099_blast_result.csv', r'.'),
    (r'src/results/20260108_202049/101.1492R.SP506300620101_blast_result.csv', r'.'),
    (r'src/results/20260108_202049/94.1492R.SP506300620094_blast_result.csv', r'.'),
    (r'src/results/20260108_202049/95.1492R.SP506300620095_blast_result.csv', r'.'),
    (r'src/results/20260108_202049/96.1492R.SP506300620096_blast_result.csv', r'.'),
    (r'src/results/20260108_202049/97.1492R.SP506300620097_blast_result.csv', r'.'),
    (r'src/results/20260108_202049/98.1492R.SP506300620098_blast_result.csv', r'.'),
    (r'src/results/20260108_202213/2.1492R.SP506300620002_blast_result.csv', r'.'),
    (r'src/results/20260108_202213/3.1492R.SP506300620003_blast_result.csv', r'.'),
    (r'src/results/20260108_202213/4.1492R.SP506300620004_blast_result.csv', r'.'),
    (r'src/results/20260108_202213/5.1492R.SP506300620005_blast_result.csv', r'.'),
    (r'src/results/20260108_202213/6.1492R.SP506300620006_blast_result.csv', r'.'),
    
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
