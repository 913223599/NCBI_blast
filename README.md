# NCBI BLAST 图形界面工具

一个功能强大的NCBI BLAST（Basic Local Alignment Search Tool）图形化客户端，提供直观的用户界面来执行生物序列比对和分析。

## 📋 项目概述

NCBI BLAST 图形界面工具是一个基于Python开发的桌面应用程序，旨在简化BLAST序列搜索过程。该工具提供了友好的GUI界面，让用户无需命令行操作即可轻松执行序列比对、获取结果并进行翻译分析。

## ✨ 主要特性

- **直观的图形界面**：基于PyQt6开发，提供现代化的用户体验
- **多线程处理**：支持后台任务执行，避免UI冻结
- **智能参数设置**：预设常用参数，同时支持高级自定义
- **结果可视化**：以表格和图表形式展示比对结果
- **AI辅助翻译**：集成大模型API，自动翻译和解释BLAST结果
- **批量处理**：支持多个序列文件的批量处理
- **结果缓存**：智能缓存机制，避免重复计算
- **离线/在线模式**：支持本地BLAST和在线NCBI服务

## 🛠 技术栈

### 核心技术
- **Python 3.7+**：主要编程语言
- **PyQt6**：图形用户界面框架
- **Biopython**：生物信息学工具包
- **OpenAI SDK**：AI翻译和解释功能
- **Pandas**：数据分析和处理

### 完整项目结构
```
NCBI BLAST/
├── config.json              # 配置文件（API密钥等）
├── requirements.txt         # Python依赖包列表
├── full_auto_package_fixed.py  # 自动打包脚本
├── README.md               # 项目说明文档
├── src/                    # 源代码目录
│   ├── __init__.py         # 包初始化文件
│   ├── __main__.py         # 主程序入口
│   ├── gui_main_packaged.py # GUI打包版本入口
│   ├── analysis/           # 高级分析功能模块
│   │   ├── __init__.py     # 分析模块初始化
│   │   ├── msa_engine.py   # 多序列比对引擎 - ClustalW/Muscle封装
│   │   ├── tree_builder.py # 建树逻辑 - 距离计算和邻接法/UPGMA建树
│   │   └── tree_visualizer.py # 绘图逻辑 - Matplotlib嵌入PyQt绘图
│   ├── blast/              # BLAST核心功能模块
│   │   ├── __init__.py     # 模块初始化
│   │   ├── batch_processor.py    # 批量处理器 - 处理多个序列文件
│   │   ├── executor.py           # 执行器 - 管理BLAST任务执行
│   │   ├── local_blast.py        # 本地BLAST实现 - 本地BLAST执行逻辑
│   │   ├── parser.py             # 结果解析器 - 解析BLAST输出格式
│   │   ├── result_cache.py       # 结果缓存 - 缓存BLAST结果避免重复计算
│   │   └── result_converter.py   # 结果转换器 - 转换结果为不同格式
│   ├── gui/                # 图形用户界面模块
│   │   ├── __init__.py     # GUI模块初始化
│   │   ├── application_pyqt.py   # PyQt应用入口 - 主应用类
│   │   ├── main_window_pyqt.py   # 主窗口 - GUI主界面实现
│   │   ├── threads/        # 多线程处理模块
│   │   │   ├── __init__.py # 线程模块初始化
│   │   │   └── processing_thread.py # 处理线程 - 后台任务执行
│   │   └── widgets/        # GUI组件模块
│   │       ├── __init__.py # 组件模块初始化
│   │       ├── api_key_dialog.py       # API密钥对话框 - 管理API密钥
│   │       ├── control_panel.py        # 控制面板 - 主要控制按钮
│   │       ├── file_selector.py        # 文件选择器 - 选择输入文件
│   │       ├── help_dialog.py          # 帮助对话框 - 用户帮助信息
│   │       ├── parameter_settings.py   # 参数设置 - BLAST参数配置
│   │       ├── result_viewer.py        # 结果查看器 - 展示和分析结果
│   │       ├── settings_dialog.py      # 设置对话框 - 应用程序设置
│   │       ├── summary_panel.py        # 摘要面板 - 显示结果摘要
│   │       └── translation_debugger.py # 翻译调试器 - AI翻译功能调试
│   └── utils/              # 实用工具模块
│       ├── __init__.py     # 工具模块初始化
│       ├── config_manager.py        # 配置管理 - 管理应用程序配置
│       ├── environment_checker.py   # 环境检查 - 检查运行环境
│       ├── file_handler.py          # 文件处理 - 处理各种文件操作
│       ├── hash_checker.py          # 哈希校验 - 验证文件完整性
│       ├── taxonomy_parser.py       # 分类学解析 - 解析生物分类学数据
│       └── translation/      # AI翻译功能模块
│           ├── __init__.py   # 翻译模块初始化
│           ├── biology_translator.py      # 生物学翻译器 - 专业生物学术语翻译
│           ├── blast_result_translator.py # BLAST结果翻译器 - 翻译比对结果
│           ├── qwen_translator.py         # 通义千问翻译器 - AI翻译接口
│           ├── term_extractor.py          # 术语提取器 - 提取关键生物学术语
│           └── translation_data_manager.py # 翻译数据管理 - 管理翻译缓存和数据
```

## 🔧 安装与配置

### 系统要求
- Windows 7 或更高版本
- Python 3.7 或更高版本
- 至少 2GB 可用磁盘空间
- 稳定的网络连接（用于在线BLAST）

### 依赖安装

1. **克隆或下载项目**
   ```bash
   git clone <repository-url>
   cd NCBI_BLAST
   ```

2. **安装Python依赖**
   ```bash
   pip install -r requirements.txt
   ```

3. **安装NCBI BLAST+（可选，用于本地BLAST）**
   - 访问 [NCBI BLAST+](https://blast.ncbi.nlm.nih.gov/Blast.cgi?PAGE_TYPE=BlastDocs&DOC_TYPE=Download) 下载
   - 按照官方指南安装到系统PATH中

### 配置API密钥

编辑 `config.json` 文件，添加您的AI服务API密钥：

```json
{
  "api_keys": {
    "dashscope": "your_api_key_here"
  }
}
```

## 🚀 使用指南

### 启动应用程序

1. **开发模式启动**
   ```bash
   python -m src.gui_main_packaged
   ```

2. **打包为独立应用**
   ```bash
   python full_auto_package_fixed.py
   ```

### 基本操作流程

1. **选择输入文件**
   - 点击"选择文件"按钮
   - 选择FASTA格式的序列文件
   - 支持单个或多个序列文件

2. **设置BLAST参数**
   - 选择数据库（nr, refseq_protein等）
   - 设置E值阈值
   - 选择比对算法（blastp, blastn等）
   - 调整其他高级参数

3. **执行搜索**
   - 点击"开始BLAST"按钮
   - 查看进度指示器
   - 等待结果生成

4. **查看和分析结果**
   - 在结果面板中查看比对详情
   - 导出结果为CSV或JSON格式
   - 使用AI翻译功能理解结果

### 高级功能

#### 批量处理
- 支持同时处理多个序列文件
- 可设置批处理队列
- 自动合并结果

#### AI辅助翻译
- 自动翻译BLAST结果为易懂的生物学解释
- 提供序列功能注释
- 支持专业术语解释

#### 结果缓存
- 智能缓存机制避免重复计算
- 可配置缓存大小和清理策略
- 支持缓存导出和共享

## 📊 功能模块详解

### BLAST模块 ([src/blast/](./src/blast/))
- **Batch Processor**：批量处理多个序列
- **Executor**：执行BLAST查询
- **Local BLAST**：本地BLAST实现
- **Parser**：解析BLAST输出
- **Result Cache**：结果缓存管理
- **Result Converter**：结果格式转换

### GUI模块 ([src/gui/](./src/gui/))
- **Application PyQt**：PyQt应用入口
- **Main Window**：主窗口界面
- **Processing Thread**：后台处理线程
- **Widgets**：
  - File Selector：文件选择器
  - Parameter Settings：参数设置面板
  - Result Viewer：结果查看器
  - Control Panel：控制面板
  - Summary Panel：摘要面板

### 实用工具 ([src/utils/](./src/utils/))
- **Translation**：AI辅助翻译功能
  - Biology Translator：生物学翻译器
  - Qwen Translator：通义千问翻译器
  - Term Extractor：术语提取器
- **Config Manager**：配置管理
- **Environment Checker**：环境检查
- **File Handler**：文件处理
- **Taxonomy Parser**：分类学解析

## 🔧 开发指南

### 代码规范
- 使用Python 3.7+ 语法
- 遵循PEP 8编码规范
- 使用类型提示增强代码可读性
- 编写单元测试覆盖核心功能

### 测试
```bash
# 运行单元测试
python -m pytest tests/

# 运行特定模块测试
python -m pytest tests/test_blast.py
```

### 打包发布
使用提供的自动打包脚本：
```bash
python full_auto_package_fixed.py
```

此脚本会自动：
- 分析项目结构
- 提取依赖关系
- 生成配置文件
- 创建独立的可执行文件

## 🔒 安全和隐私

- 所有API密钥存储在本地配置文件中
- 不收集用户数据
- 支持离线处理敏感数据
- 遵循生物信息学数据安全最佳实践

## 🤝 贡献

欢迎提交Issue和Pull Request来改进项目！

### 贡献步骤
1. Fork项目
2. 创建功能分支
3. 提交更改
4. 发起Pull Request

## 📄 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](./LICENSE) 文件。

## 🆘 支持

如遇到问题，请：
1. 检查[Issues](https://github.com/your-repo/issues)是否有类似问题
2. 提交新Issue，包含详细的错误信息和重现步骤
3. 联系项目维护者

## 🙏 致谢

- NCBI：提供BLAST算法和数据库
- Biopython社区：提供生物信息学Python工具包
- PyQt团队：提供跨平台GUI框架
- Alibaba Cloud DashScope：提供AI翻译能力
- DeepSeek：提供高质量AI模型支持
- 开源社区：提供各类基础库和技术支持