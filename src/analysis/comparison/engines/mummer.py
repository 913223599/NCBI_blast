
import logging
import subprocess
import json
from pathlib import Path
from typing import Dict, Any, List

class MummerEngine:
    """
    MUMmer 对比引擎
    职责：执行 nucmer 比对，并解析 delta 文件为结构化的对齐坐标。
    """
    def __init__(self, wsl_distro: str = "Ubuntu"):
        self.logger = logging.getLogger("Analysis.Comparison.Mummer")
        self.wsl_distro = wsl_distro

    async def run_alignment(self, ref_path: Path, query_path: Path, out_dir: Path) -> Dict[str, Any]:
        """
        高兼容性比对方案：将任务平移至 WSL 内部 /tmp 目录执行。
        """
        import uuid
        task_uuid = str(uuid.uuid4())[:8]
        tmp_dir = f"/tmp/mummer_{task_uuid}"
        
        linux_ref = self._to_wsl(ref_path)
        linux_query = self._to_wsl(query_path)
        
        # 结果收纳路径
        final_coords = out_dir / "reports" / "mummer_run.coords"
        final_delta = out_dir / "xml_raw" / "mummer_run.delta"
        linux_final_coords = self._to_wsl(final_coords)
        linux_final_delta = self._to_wsl(final_delta)

        # 1. 在 WSL 内部构建环境 (使用单引号封装 linux 路径)
        init_cmd = ["wsl", "-d", self.wsl_distro, "-u", "root", "bash", "-c", 
                    f"mkdir -p {tmp_dir} && cp '{linux_ref}' {tmp_dir}/ref.fa && cp '{linux_query}' {tmp_dir}/query.fa"]
        
        # 2. 执行 nucmer
        run_cmd = ["wsl", "-d", self.wsl_distro, "-u", "root", "bash", "-c", 
                   f"cd {tmp_dir} && nucmer --maxmatch -p run ref.fa query.fa && show-coords -r -T -H run.delta > run.coords"]
        
        # 3. 将结果搬运回宿主机
        sync_cmd = ["wsl", "-d", self.wsl_distro, "-u", "root", "bash", "-c", 
                    f"cp {tmp_dir}/run.coords '{linux_final_coords}' && cp {tmp_dir}/run.delta '{linux_final_delta}' && rm -rf {tmp_dir}"]

        try:
            self.logger.info(f"🚀 [WSL-Sandbox] 启动隔离计算: {tmp_dir}")
            subprocess.run(init_cmd, check=True)
            subprocess.run(run_cmd, check=True)
            subprocess.run(sync_cmd, check=True)
            
            # 4. 解析结果
            alignments = self._parse_coords(final_coords)
            return {
                "engine": "mummer",
                "alignments": alignments,
                "summary": self._generate_summary(alignments)
            }
        except Exception as e:
            self.logger.error(f"MUMmer 隔离运行失败: {e}")
            raise RuntimeError(f"Alignment sandbox error: {e}")

    def _parse_coords(self, coords_file: Path) -> List[Dict[str, Any]]:
        results = []
        if not coords_file.exists(): return results
        with open(coords_file, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                parts = line.strip().split('\t')
                if len(parts) >= 9:
                    try:
                        results.append({
                            "ref_start": int(parts[0]), "ref_end": int(parts[1]),
                            "query_start": int(parts[2]), "query_end": int(parts[3]),
                            "len": int(parts[4]), "identity": float(parts[6]),
                            "ref_id": parts[7], "query_id": parts[8]
                        })
                    except: continue
        return results

    def _generate_summary(self, alignments: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not alignments: return {"total_matches": 0, "average_identity": 0}
        total_len = sum(a['len'] for a in alignments)
        avg_id = sum(a['identity'] for a in alignments) / len(alignments) if alignments else 0
        return {
            "total_matches": len(alignments), "matched_length": total_len, "average_identity": round(avg_id, 2)
        }

    def _to_wsl(self, path: Path) -> str:
        """
        标准化路径转换：采用项目内置的 WSLManager 进行映射
        """
        try:
            from src.assembly.env.wsl_manager import WSLManager
            linux_path = WSLManager.window_to_linux_path(str(path.absolute()))
            if linux_path: return linux_path
        except: pass

        # 备选方案：标准 /mnt 驱动器解析
        p_str = str(path.absolute()).replace('\\', '/')
        if ':' in p_str:
            drive, rest = p_str.split(':', 1)
            return f"/mnt/{drive.lower()}{rest}"
        return p_str
