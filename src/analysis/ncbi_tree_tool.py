"""
NCBI Tree Tool Wrapper

Wraps the compiled C++ binaries from the NCBI tree-tool project.
Handles conversion between Python data structures and .dm (Data Master) format.
"""

import io
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# 工具搜索的根目录相对偏移层数（从本文件到项目根）
_PROJECT_ROOT_PARENT_LEVELS = 2  # src/analysis -> 项目根

class NcbiTreeToolWrapper:
    """
    NCBI tree-tool 工具集的 Python 封装
    """
    
    def __init__(self, tools_dir=None):
        """
        初始化封装器
        :param tools_dir: 包含编译好的 mds 等工具的目录。如果为 None，自动搜索。
        """
        self.tools_dir = tools_dir
        self.mds_exe = self._find_executable("mds")
        
    def _find_executable(self, name):
        """查找可执行文件"""
        # 1. 如果指定了目录，先在目录里找
        if self.tools_dir:
            path = Path(self.tools_dir) / name
            if path.exists() or path.with_suffix('.exe').exists():
                return str(path)
                
        # 2. 在项目源代码目录中查找 (按相对层级定位)
        project_root = Path(__file__).resolve().parents[_PROJECT_ROOT_PARENT_LEVELS]
        source_bin_path = project_root / "src" / "analysis" / "tree-tool-master" / "dm" / name
        if source_bin_path.exists() or source_bin_path.with_suffix('.exe').exists():
            return str(source_bin_path)
            
        # 3. 检查系统 PATH
        path = shutil.which(name)
        if path: return path
        
        return None

    def is_available(self):
        """检查核心工具是否可用"""
        return self.mds_exe is not None

    def run_mds(self, distance_matrix, names):
        """
        运行 MDS (Multi-Dimensional Scaling)
        :param distance_matrix: numpy array or list of lists, 距离矩阵
        :param names: list of str, 序列名称列表
        :return: pandas.DataFrame, 包含坐标的 DataFrame (PC_1, PC_2, ...)
        """
        if not self.mds_exe:
            raise FileNotFoundError("未找到 'mds' 可执行文件。请先编译 tree-tool。")

        # 1. 创建临时 .dm 文件
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.dm', encoding='utf-8') as tmp_dm:
            dm_path = tmp_dm.name
            self._write_dm_file(tmp_dm, distance_matrix, names)

        try:
            # 2. 调用 mds
            # mds -attrType 2 -attr dist <file>
            # attrType 2 = squared dissimilarity (通常距离矩阵是线性的，但 mds.cpp 注释 imply 2 for dist)
            # 实际上 mds.cpp: 0-sim, 1-dissim, 2-sqr dissim. 
            # Bio.Phylo 计算的是线性距离，所以应该用 1 (dissimilarity)
            cmd = [
                self.mds_exe,
                "-attrType", "1", 
                "-attr", "dist",
                "-maxAttr", "10", # 限制输出维度，提高速度
                str(Path(dm_path).with_suffix('')) # mds 自动添加 .dm 后缀，所以这里去掉
            ]
            
            # 注意：mds 工具可能输出到 stdout
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            
            # 3. 解析输出
            # mds 输出 CSV 格式到 stdout: ObjName, Mult, PC_1, PC_2 ...
            output_csv = result.stdout
            
            # 过滤掉非 CSV 的日志行 (以 # 开头或空行)
            csv_lines = [line for line in output_csv.splitlines() if line.strip() and not line.startswith('#') and "ObjName" in line or "," in line]
            csv_content = "\n".join(csv_lines)
            
            if not csv_content:
                raise RuntimeError(f"MDS output is empty or invalid. Stderr: {result.stderr}")

            df = pd.read_csv(io.StringIO(csv_content))
            return df

        except subprocess.CalledProcessError as e:
            logger.error(f"MDS execution failed: {e.stderr}")
            raise RuntimeError(f"MDS execution failed: {e.stderr}")
        finally:
            # 清理临时文件
            if os.path.exists(dm_path):
                os.remove(dm_path)

    def _write_dm_file(self, file_obj, matrix, names):
        """
        将距离矩阵写入 .dm 格式
        格式参考 dataset.cpp Dataset::load
        """
        n = len(names)
        
        # Header
        file_obj.write(f"OBJNUM {n}\n")
        file_obj.write("NAME\n")
        file_obj.write("NOMULT\n") # 假设没有重数
        
        # Attributes definition
        file_obj.write("ATTRIBUTES\n")
        file_obj.write("  dist REAL2 4\n") # 定义一个名为 dist 的二维实数属性
        
        # Data section
        file_obj.write("DATA\n")
        
        # Objects list
        for name in names:
            # 确保名字没有空格，如果有空格替换为下划线
            safe_name = name.replace(" ", "_")
            file_obj.write(f"{safe_name}\n")
            
        # Matrix data
        file_obj.write("dist FULL\n")
        for i in range(n):
            row_vals = []
            for j in range(n):
                val = matrix[i][j]
                row_vals.append(f"{val:.4f}")
            file_obj.write("\t".join(row_vals) + "\n")
