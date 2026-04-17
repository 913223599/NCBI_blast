import os
from pathlib import Path

# 项目根目录：如果环境变量未设置，则自动定位到项目根目录（假设此文件位于 src/backend）
PROJECT_ROOT = Path(os.getenv('PROJECT_ROOT', Path(__file__).resolve().parents[2]))

# 常用子目录
TOOLS_ROOT = PROJECT_ROOT / 'tools'
SRA_TOOLS_BIN = TOOLS_ROOT / 'ncbi_dist' / 'bin' / 'sra-tools'
TREE_TOOLS_BIN = TOOLS_ROOT / 'ncbi_dist' / 'bin' / 'tree-tools'
DOCS_ROOT = TOOLS_ROOT / 'docs' / 'detailed'

# 其他可能使用的路径
CONFIG_JSON = PROJECT_ROOT / 'config.json'
