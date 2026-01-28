# NCBI BLAST Pro | 生物序列分析工作站

一个功能强大的NCBI BLAST（Basic Local Alignment Search Tool）图形化客户端，提供直观的用户界面来执行生物序列比对和分析。本项目整合了本地计算、云端加速和高级数据管理功能，旨在为科研人员提供一站式的序列分析解决方案。

## ✨ 主要特性

- **现代化的图形界面**：基于PyQt6开发，采用侧边栏布局，提供流畅直观的用户体验。
- **混合式计算模式**：
  - **本地BLAST**：利用本地多核CPU进行快速、安全的序列比对。
  - **Elastic BLAST**：集成AWS/GCP云服务，将大规模计算任务无缝提交到云端，极大提高分析效率。
- **全面的数据库管理**：
  - **本地构建**：支持从FASTA文件创建自定义BLAST数据库。
  - **在线下载**：一键下载NCBI官方常用数据库（如 `nt`, `nr`, `swissprot`）。
- **高级结果管理**：
  - **任务历史**：自动记录每次分析的参数和结果，方便回溯和重新加载。
  - **结果可视化**：以树状结构清晰展示批量任务结果，并提供详细的比对视图。
  - **数据导出**：支持将比对结果导出为CSV等多种格式。
- **AI辅助功能**：
  - **智能翻译**：集成DeepSeek、DashScope等大语言模型，自动将英文生物学描述翻译为中文。
  - **翻译调试器**：提供工具以测试和优化翻译效果。
- **SRA数据支持**：集成`fasterq-dump`等SRA-Toolkit工具，具备处理SRA测序数据的潜力。
- **可扩展的帮助系统**：内置分类清晰、内容丰富的Markdown帮助文档。

## 🛠 技术栈

- **核心语言**: Python 3.7+
- **GUI框架**: PyQt6
- **生物信息学**: Biopython
- **云端集成**: `google-api-python-client`, `boto3`
- **数据处理**: Pandas
- **AI集成**: `dashscope`, `openai`

## 📂 项目结构

```
NCBI BLAST/
├── resources/
│   └── help/               # Markdown帮助文档
├── src/
│   ├── __main__.py         # 主程序入口
│   ├── analysis/           # 高级分析（多序列比对、进化树）
│   │   ├── msa_engine.py
│   │   └── tree_builder.py
│   ├── blast/              # BLAST核心功能
│   │   ├── batch_processor.py    # 批量处理器（支持多文件、多序列）
│   │   ├── local_blast.py        # 本地BLAST执行逻辑
│   │   ├── elastic_blast_processor.py # Elastic BLAST云端处理器
│   │   ├── database_manager.py   # 数据库管理逻辑
│   │   └── parser.py             # 结果解析器
│   ├── gui/                # 图形用户界面
│   │   ├── main_window_pyqt.py   # 主窗口实现
│   │   ├── threads/              # 后台处理线程
│   │   └── widgets/              # 自定义UI组件
│   │       ├── file_selector.py
│   │       ├── parameter_settings.py
│   │       ├── result_viewer.py
│   │       ├── control_panel.py
│   │       ├── history_dialog.py
│   │       ├── database_manager_dialog.py
│   │       ├── cloud_manager_dialog.py
│   │       ├── help_viewer.py
│   │       └── api_key_dialog.py
│   └── utils/              # 实用工具
│       ├── config_manager.py     # 配置管理
│       ├── history_manager.py    # 历史记录管理
│       ├── help_manager.py       # 帮助文档管理
│       └── translation/          # AI翻译模块
├── tool-master/            # 第三方工具集
│   └── sra-tools-master/   # SRA Toolkit源码
├── config.json             # 配置文件
└── requirements.txt        # Python依赖
```

## 🚀 使用指南

### 1. 安装与配置
1.  **安装依赖**:
    ```bash
    pip install -r requirements.txt
    ```
2.  **配置本地BLAST+**:
    - 从 [NCBI官网](https://blast.ncbi.nlm.nih.gov/Blast.cgi?PAGE_TYPE=BlastDocs&DOC_TYPE=Download) 下载并安装BLAST+。
    - 确保`blastn`, `makeblastdb`等命令在系统PATH中可用。
3.  **配置API密钥** (可选):
    - 在菜单栏“帮助” -> “API密钥”中，输入您的AI翻译服务密钥。

### 2. 启动应用程序
```bash
python -m src
```

### 3. 基本操作流程
1.  **选择文件**: 在左侧文件选择区点击“浏览”或拖入FASTA文件。
2.  **设置参数**: 在左侧参数区选择BLAST程序、数据库和E-value等。
3.  **开始处理**: 点击主界面顶部的“开始处理”按钮，并为任务命名。
4.  **查看结果**: 在右侧结果区查看任务进度和比对详情。

### 4. 高级功能
- **管理本地数据库**: 在菜单栏“设置” -> “本地数据库管理”中下载或构建数据库。
- **使用云端BLAST**: 在“参数设置” -> “高级”中启用Elastic BLAST，并配置云参数。
- **查看历史任务**: 在菜单栏“文件” -> “任务历史记录”中查看、加载或删除旧任务。
- **获取帮助**: 在菜单栏“帮助” -> “帮助”中打开帮助文档。

## 🤝 贡献

欢迎通过提交Issue和Pull Request来改进项目。

1.  Fork本项目。
2.  创建您的功能分支 (`git checkout -b feature/AmazingFeature`)。
3.  提交您的更改 (`git commit -m 'Add some AmazingFeature'`)。
4.  推送到分支 (`git push origin feature/AmazingFeature`)。
5.  发起Pull Request。

## 📄 许可证

本项目采用 MIT 许可证。

## 🙏 致谢

- NCBI (BLAST, SRA Toolkit)
- Biopython, PyQt, Pandas等开源社区
- 阿里云DashScope, DeepSeek等AI服务提供商
