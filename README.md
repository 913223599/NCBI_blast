# NCBI BLAST 工具

这是一个用于执行 NCBI BLAST 搜索的工具，支持本地和远程 BLAST 搜索，可以对 DNA 序列进行比对分析。

## 功能特性

- 执行本地 BLAST 搜索
- 执行远程 BLAST 搜索
- 批量处理多个序列文件
- 多线程处理避免程序卡死
- 结果缓存避免重复查询
- 图形界面展示处理结果
- 支持取消正在进行的任务
- 提供性能优化方案

## 安装依赖

```bash
pip install biopython
pip install PyQt6
pip install openai
pip install httpx
```

或者使用:

```bash
pip install -r requirements.txt
```

## 运行程序

### 命令行模式

```bash
python -m src.main
```

### GUI模式

```bash
python -m src.gui_main_pyqt
```

或者

```bash
python -m src.main --gui
```

## 打包程序

本项目支持使用 PyInstaller 进行打包，提供两种打包方式：

### 方法1：使用打包脚本（推荐）

```bash
python build.py
```

该命令将使用命令行参数进行打包，生成 onedir 模式的可执行文件。

### 方法2：使用spec文件

```bash
python build.py --spec
```

该命令将使用 NCBI_BLAST_Tool.spec 配置文件进行打包。

### 方法3：直接使用PyInstaller命令

```bash
pyinstaller --onedir --windowed --name=NCBI_BLAST_Tool src/gui_main_pyqt.py
```

打包后的程序将位于 dist/ 目录中。

## 目录结构说明

- `sequences/` - 存放待分析的DNA序列文件
- `results/` - 存放BLAST搜索结果
- `database/` - 存放本地BLAST数据库
- `src/` - 源代码目录
- `dist/` - 打包后的可执行文件目录（打包后生成）

## 配置文件

- `config.json` - API密钥等配置信息
- `translation_data.csv` - 翻译数据文件
- `predefined_terms.csv` - 预定义术语文件