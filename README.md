# NCBI BLAST 工具

这是一个用于执行 NCBI BLAST 搜索的工具，可以对 DNA 序列进行比对分析。

## 项目结构

```
ncbi_blast/
├── setup.py                 # 项目安装配置
├── README.md                # 项目说明文档
├── OPTIMIZATION_GUIDE.md    # 性能优化指南
├── sequences/               # 序列文件目录
│   └── *.seq                # 待分析的序列文件
├── src/                     # 源代码目录
│   ├── __init__.py          # Python 包初始化文件
│   ├── __main__.py          # 使包可直接运行
│   ├── main.py              # 程序入口
│   ├── gui_main.py          # GUI程序入口
│   ├── blast/               # BLAST 功能模块
│   │   ├── __init__.py      # Python 包初始化文件
│   │   ├── executor.py      # BLAST 执行器
│   │   ├── parser.py        # BLAST 结果解析器
│   │   ├── batch_processor.py  # 批量处理模块
│   │   ├── local_blast.py   # 本地BLAST处理模块
│   │   ├── optimized_remote_blast.py  # 优化的远程BLAST模块
│   │   ├── hybrid_blast.py  # 混合BLAST处理模块
│   │   ├── optimized_config.py  # 优化配置模块
│   │   ├── result_cache.py  # 结果缓存模块
│   │   ├── smart_scheduler.py  # 智能调度模块
│   │   └── ultimate_blast.py  # 终极BLAST处理器
│   ├── utils/               # 工具模块
│   │   ├── __init__.py      # Python 包初始化文件
│   │   └── file_handler.py  # 文件处理工具
│   └── gui/                 # 图形界面模块
│       ├── __init__.py      # Python 包初始化文件
│       ├── main_window.py   # 主窗口界面
│       └── application.py   # GUI应用程序
└── results/                 # 结果保存目录
    └── *_blast_result.xml   # BLAST 结果文件（以序列文件名命名）
```

## 模块说明

### BLAST 模块
- **executor.py**: 负责执行 BLAST 搜索请求
- **parser.py**: 负责解析 BLAST 搜索结果
- **batch_processor.py**: 负责批量处理多个序列文件
- **local_blast.py**: 本地BLAST处理模块
- **optimized_remote_blast.py**: 优化的远程BLAST模块
- **hybrid_blast.py**: 混合BLAST处理模块
- **optimized_config.py**: 优化配置模块
- **result_cache.py**: 结果缓存模块
- **smart_scheduler.py**: 智能调度模块
- **ultimate_blast.py**: 终极BLAST处理器

### 工具模块
- **file_handler.py**: 负责文件读取和保存操作

### GUI模块
- **main_window.py**: 主窗口界面实现
- **application.py**: GUI应用程序管理

## 功能特点

1. **批量查询功能**: 支持同时处理多个序列文件
2. **文件选择功能**: 提供图形化界面选择待查询的文件
3. **多线程处理**: 使用多线程技术避免程序卡死
4. **结果命名优化**: 结果文件使用对应序列文件名进行命名，便于查阅
5. **双模式支持**: 支持命令行模式和图形界面模式
6. **直观结果展示**: GUI模式下以表格形式展示处理结果
7. **处理进度监控**: 实时显示处理进度和状态
8. **处理取消功能**: 支持取消正在进行的处理任务
9. **性能优化**: 提供多种性能优化方案
10. **模块化设计**: 功能分解为独立模块，便于维护和扩展

## 安装依赖

```bash
pip install biopython
pip install PyQt6
pip install openai
pip install "httpx>=0.23.0,<0.28.0"
```

或者使用项目配置文件:

```bash
pip install -e .
```

## 使用方法

### 命令行模式

```bash
python -m src.main
```

程序运行后会提示选择操作模式：
1. 选择文件进行批量搜索 - 通过文件选择对话框选择要处理的序列文件
2. 使用sequences目录下的所有序列文件 - 自动处理sequences目录中的所有序列文件

然后会提示输入线程数（默认为3），程序将开始批量处理。

### 图形界面模式

```bash
python -m src.main --gui
```

或者

```bash
python -m src.gui_main_pyqt
```

GUI界面包含以下功能：
- 文件选择按钮：通过文件对话框选择要处理的序列文件
- 线程数设置：可设置并发线程数（1-10）
- 开始/停止按钮：控制处理过程
- 结果表格：以表格形式显示处理结果，包括文件名、状态、耗时等
- 进度条：显示处理进度
- 状态栏：显示当前处理状态
- 统计信息：显示处理结果的汇总信息

### 安装后运行

```bash
pip install -e .
ncbi_blast [--gui]
```

## 性能优化

查看 [OPTIMIZATION_GUIDE.md](file:///D:/NCBI%20blast/OPTIMIZATION_GUIDE.md) 了解性能优化方案：

1. **本地BLAST**：安装本地数据库，查询速度提升10-100倍
2. **结果缓存**：避免重复查询，重复查询速度提升50-200倍
3. **智能调度**：优化处理顺序和资源利用
4. **参数优化**：调整BLAST参数平衡速度和准确性
5. **综合优化**：整合所有优化技术的终极解决方案

## 支持的文件格式

- `.seq` - 序列文件
- `.fasta` / `.fa` - FASTA格式文件

## 结果文件

每个序列文件的BLAST结果都会保存在 [results/](file:///D:/NCBI%20blast/results/) 目录中，文件名格式为：
```
[原始文件名]_blast_result.xml
```

## 开发指南

### 添加新功能

1. 在相应模块目录下创建新文件
2. 实现功能并确保接口清晰
3. 在主程序中调用新功能

### 扩展现有功能

1. 修改相应模块文件
2. 保持向后兼容性
3. 更新文档说明

## 配置API密钥

有两种方式配置API密钥:

### 方法1: 使用配置文件（推荐）
在项目根目录下创建`config.json`文件，内容如下:
```json
{
  "api_keys": {
    "dashscope": "your_dashscope_api_key_here"
  }
}
```

### 方法2: 使用环境变量
```bash
# Windows命令行
set DASHSCOPE_API_KEY=your_api_key_here

# Windows PowerShell
$env:DASHSCOPE_API_KEY="your_api_key_here"

# Linux/Mac
export DASHSCOPE_API_KEY=your_api_key_here
```

### 方法3: 在代码中直接传递
```python
translator = get_qwen_translator('your_api_key_here')
```

