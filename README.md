# NCBI BLAST 工具

这是一个用于执行 NCBI BLAST 搜索的工具，可以对 DNA 序列进行比对分析。

## 项目结构

```
ncbi_blast/
├── setup.py                 # 项目安装配置
├── README.md                # 项目说明文档
├── config.json              # 配置文件
├── OPTIMIZATION_GUIDE.md    # 性能优化指南
├── translation_data.csv     # 翻译数据文件
├── sequences/               # 序列文件目录
│   └── *.seq                # 待分析的序列文件
├── database/                # 数据库目录
│   ├── taxdmp/              # NCBI Taxonomy 旧版数据库
│   └── new_taxdump/         # NCBI Taxonomy 新版数据库
├── src/                     # 源代码目录
│   ├── __init__.py          # Python 包初始化文件
│   ├── __main__.py          # 使包可直接运行
│   ├── main.py              # 程序入口
│   ├── gui_main_pyqt.py     # GUI程序入口
│   ├── blast/               # BLAST 功能模块
│   │   ├── __init__.py      # Python 包初始化文件
│   │   ├── executor.py      # BLAST 执行器
│   │   ├── parser.py        # BLAST 结果解析器
│   │   ├── batch_processor.py  # 批量处理模块
│   │   ├── local_blast.py   # 本地BLAST处理模块
│   │   ├── optimized_config.py  # 优化配置模块
│   │   ├── result_cache.py  # 结果缓存模块
│   ├── utils/               # 工具模块
│   │   ├── __init__.py             # Python 包初始化文件
│   │   ├── file_handler.py         # 文件处理工具
│   │   ├── taxonomy_parser.py      # Taxonomy数据解析器
│   │   ├── translation/            # 翻译功能模块
│   │   │   ├── __init__.py                # Python  包初始化文件
│   │   │   ├── biology_translator.py      # 生物学文本翻译器
│   │   │   ├── special_pattern_translator.py  # 特殊模式翻译器
│   │   │   ├── species_translator.py      # 物种名称翻译器
│   │   │   ├── qwen_translator.py         # Qwen AI翻译器
│   │   │   ├── translation_data_manager.py  # 翻译数据管理器
│   │   │   ├── translation_quality_checker.py  # 翻译质量检查器
│   │   │   └── term_extractor.py          # 术语提取器
│   │   ├── config_manager.py       # 配置管理器
│   └── gui/                        # 图形界面模块
│       ├── __init__.py             # Python 包初始化文件
│       ├── main_window_pyqt.py     # 主窗口界面
│       ├── application_pyqt.py     # GUI应用程序
│       ├── threads/                # 工作线程模块
│       │   └── processing_thread.py  # BLAST处理线程
│       └── widgets/                # GUI组件模块
│           ├── __init__.py         # Python 包初始化文件
│           ├── file_selector.py    # 文件选择组件
│           ├── control_panel.py    # 控制面板组件
│           ├── parameter_settings.py  # 参数设置组件
│           ├── result_viewer.py    # 结果展示组件
│           └── summary_panel.py    # 摘要面板组件
└── results/                        # 结果保存目录
    └── *_blast_result.xml          # BLAST 结果文件（以序列文件名命名）