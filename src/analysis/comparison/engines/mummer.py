
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
        
        # 预处理：确保文件在 Windows 侧已经是合规的 FASTA 格式 (符合 Linux 换行规范)
        def _ensure_fasta(p: Path):
            raw_content = p.read_text(encoding='utf-8', errors='ignore').strip()
            # 统一转换为 LF 换行，清理所有 \r
            clean_seq = raw_content.replace('\r\n', '\n').replace('\r', '\n')
            
            if not clean_seq.startswith(">"):
                self.logger.info(f"正在为非标准序列文件补全 FASTA 头部: {p.name}")
                # 构造标准头，并确保 sequence 部分和文件末尾都有换行
                clean_seq = f">{p.stem}\n{clean_seq}\n"
            else:
                # 即使有头部，也确保末尾有换行符，防止 MUMmer 报错
                if not clean_seq.endswith('\n'):
                    clean_seq += '\n'
                    
            p.write_text(clean_seq, encoding='utf-8', newline='\n')
        
        try:
            _ensure_fasta(ref_path)
            _ensure_fasta(query_path)
        except Exception as e:
            self.logger.warning(f"FASTA 预修复失败 (非严重错误): {e}")

        linux_ref = self._to_wsl(ref_path)
        linux_query = self._to_wsl(query_path)
        
        # 结果收纳路径
        final_coords = out_dir / "reports" / "mummer_run.coords"
        final_delta = out_dir / "xml_raw" / "mummer_run.delta"
        linux_final_coords = self._to_wsl(final_coords)
        linux_final_delta = self._to_wsl(final_delta)

        # 核心增强：组合所有步骤为单一原子操作，防止 WSL 跨进程状态丢失或竞争
        # 同时增加调试诊断信息 (ls -l)
        combined_bash = (
            f"mkdir -p '{tmp_dir}' && "
            f"cp '{linux_ref}' '{tmp_dir}/ref.fa' && "
            f"cp '{linux_query}' '{tmp_dir}/query.fa' && "
            f"ls -l '{tmp_dir}' && "
            f"cd '{tmp_dir}' && "
            f"nucmer --maxmatch -p run ref.fa query.fa && "
            f"show-coords -r -T -H run.delta > run.coords && "
            f"cp run.coords '{linux_final_coords}' && "
            f"cp run.delta '{linux_final_delta}' && "
            f"rm -rf '{tmp_dir}'"
        )
        
        full_cmd = ["wsl", "-d", self.wsl_distro, "-u", "root", "bash", "-c", combined_bash]
        
        try:
            self.logger.info(f"🚀 [WSL-Atomic] 启动原子计算任务: {tmp_dir}")
            # 使用 capture_output 获取详细错误
            result = subprocess.run(full_cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
            
            if result.returncode != 0:
                self.logger.error(f"WSL 原子任务失败 (Code {result.returncode})")
                self.logger.error(f"STDOUT: {result.stdout}")
                self.logger.error(f"STDERR: {result.stderr}")
                raise RuntimeError(f"Alignment sandbox error: {result.stderr}")
            
            # 4. 解析结果
            alignments = self._parse_coords(final_coords)
            return {
                "engine": "mummer",
                "alignments": alignments,
                "summary": self._generate_summary(alignments)
            }
        except Exception as e:
            self.logger.error(f"MUMmer 运行异常: {e}")
            raise

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
            linux_path = WSLManager.to_wsl_path(str(path.absolute()))
            if linux_path: return linux_path
        except: pass

        # 备选方案：标准 /mnt 驱动器解析
        p_str = str(path.absolute()).replace('\\', '/')
        if ':' in p_str:
            drive, rest = p_str.split(':', 1)
            return f"/mnt/{drive.lower()}{rest}"
        return p_str
