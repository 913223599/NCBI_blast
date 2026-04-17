
import logging
import subprocess
from pathlib import Path
from typing import Tuple, Optional

class SequenceOrientator:
    """
    序列极性校正器
    职责：通过快速草图比对，判断 Query 序列是否相对于 Reference 需要进行反向互补（RC）。
    """
    def __init__(self, wsl_distro: str = "Ubuntu"):
        self.logger = logging.getLogger("Analysis.Comparison.Orientator")
        self.wsl_distro = wsl_distro

    async def detect_and_fix(self, ref_path: Path, query_path: Path, out_dir: Path) -> Tuple[Path, bool]:
        """
        检测方向并生成校正后的序列文件
        :return: (校正后的文件路径, 是否发生了翻转)
        """
        self.logger.info(f"正在检测序列极性: {query_path.name} vs {ref_path.name}")
        
        # 1. 使用 minimap2 进行极速启发式比对
        # 转换为 wsl 路径
        w_ref = self._to_wsl(ref_path)
        w_query = self._to_wsl(query_path)
        
        cmd = ["wsl", "-d", self.wsl_distro, "-u", "root", "bash", "-c", 
               f"minimap2 -c --cm '{w_ref}' '{w_query}' | awk '{{print $5}}' | head -n 10"]
        
        try:
            # 强制指定 utf-8 编码并增加冗余错误处理，防止 GBK 解码失败
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', check=True)
            strands = result.stdout.strip().split('\n')
            
            # 统计正负链比对数量
            plus_count = strands.count('+')
            minus_count = strands.count('-')
            
            should_flip = minus_count > plus_count
            
            if not should_flip:
                self.logger.info("序列极性一致，无需翻转。")
                return query_path, False
            
            # 2. 执行 RC 翻转逻辑
            self.logger.info("检测到反向共线性，正在生成反向互补序列...")
            flipped_path = out_dir / f"flipped_{query_path.name}"
            w_flipped = self._to_wsl(flipped_path)
            
            flip_cmd = ["wsl", "-d", self.wsl_distro, "-u", "root", "bash", "-c", 
                        f"seqtk seq -r '{w_query}' > '{w_flipped}'"]
            
            subprocess.run(flip_cmd, check=True)
            return flipped_path, True
            
        except Exception as e:
            self.logger.error(f"极性校正失败: {e}，将保持原始方向。")
            return query_path, False

    def _to_wsl(self, path: Path) -> str:
        """
        标准化路径转换：采用项目内置的 WSLManager 进行映射
        """
        try:
            from src.assembly.env.wsl_manager import WSLManager
            linux_path = WSLManager.window_to_linux_path(str(path.absolute()))
            if linux_path: return linux_path
        except: pass

        # 备选方案
        p_str = str(path.absolute()).replace('\\', '/')
        if ':' in p_str:
            drive, rest = p_str.split(':', 1)
            return f"/mnt/{drive.lower()}{rest}"
        return p_str
