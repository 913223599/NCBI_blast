"""
MUMmer 比对引擎
职责：执行 nucmer 比对，解析 delta/coords 文件为结构化对齐坐标，
     并可选调用 show-snps 提取变异位点。
继承 BaseAlignmentEngine 以复用 WSL 路径转换和命令执行工具。
"""

import uuid
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

from src.analysis.engines.engine_base import BaseAlignmentEngine, AlignmentResult


class MummerEngine(BaseAlignmentEngine):
    """
    MUMmer 3.x/4.x 比对引擎
    职责：执行 nucmer 比对，解析 coords 与 snps 输出。
    """

    def __init__(self, wsl_distro: str = "Ubuntu"):
        super().__init__(wsl_distro)
        self.logger = logging.getLogger("Analysis.Comparison.Mummer")

    async def run_alignment(
        self, ref_path: Path, query_path: Path, out_dir: Path, options: Optional[Dict[str, Any]] = None
    ) -> AlignmentResult:
        """
        高兼容性比对方案：将任务平移至 WSL 内部 /tmp 目录执行，避免跨文件系统问题。
        """
        options = options or {}
        task_uuid = str(uuid.uuid4())[:8]
        tmp_dir = f"/tmp/mummer_{task_uuid}"

        # 预处理：确保文件符合 FASTA 规范，并处理 GBK 转换
        try:
            ref_path = self.ensure_fasta(ref_path)
            query_path = self.ensure_fasta(query_path)
        except Exception as e:
            self.logger.warning(f"FASTA 预修复或转换失败 (非严重错误): {e}")

        linux_ref = self.to_wsl_path(ref_path)
        linux_query = self.to_wsl_path(query_path)

        # 结果收纳路径
        out_dir.mkdir(parents=True, exist_ok=True)
        reports_dir = out_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)

        final_coords = reports_dir / "mummer_run.coords"
        final_delta = reports_dir / "mummer_run.delta"
        final_snps = reports_dir / "mummer_run.snps"

        linux_final_coords = self.to_wsl_path(final_coords)
        linux_final_delta = self.to_wsl_path(final_delta)
        linux_final_snps = self.to_wsl_path(final_snps)

        # 核心：组合所有步骤为单一原子操作（使用 set -e 确保任何错误都会中断脚本）
        combined_bash = (
            "set -e; "
            f"mkdir -p '{tmp_dir}'; "
            f"cp '{linux_ref}' '{tmp_dir}/ref.fa'; "
            f"cp '{linux_query}' '{tmp_dir}/query.fa'; "
            f"cd '{tmp_dir}'; "
            f"nucmer --maxmatch -p run ref.fa query.fa; "
            f"show-coords -r -T -H run.delta > run.coords; "
            f"show-snps -T -H run.delta > run.snps 2>/dev/null || true; "
            f"cp run.coords '{linux_final_coords}'; "
            f"cp run.delta '{linux_final_delta}'; "
            f"cp run.snps '{linux_final_snps}' 2>/dev/null || true; "
            f"rm -rf '{tmp_dir}';"
        )

        try:
            self.logger.info(f"[WSL-Atomic] 启动 MUMmer 原子计算任务: {tmp_dir}")
            result = self.run_wsl_command(combined_bash)

            if result.returncode != 0:
                self.logger.error(f"WSL 原子任务失败 (Code {result.returncode})")
                self.logger.error(f"STDOUT: {result.stdout}")
                self.logger.error(f"STDERR: {result.stderr}")
                raise RuntimeError(f"Alignment sandbox error: {result.stderr}")

            # 解析结果
            alignments = self._parse_coords(final_coords)
            variants = self._parse_snps(final_snps)

            return AlignmentResult(
                engine="mummer",
                alignments=alignments,
                summary=self.generate_summary(alignments),
                variants=variants,
                metadata={}
            )

        except Exception as e:
            self.logger.error(f"MUMmer 运行异常: {e}")
            raise

    def _parse_coords(self, coords_file: Path) -> List[Dict[str, Any]]:
        """解析 show-coords -r -T -H 输出"""
        results = []
        if not coords_file.exists():
            return results

        with open(coords_file, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                parts = line.strip().split('\t')
                if len(parts) >= 9:
                    try:
                        ref_start = int(parts[0])
                        ref_end = int(parts[1])
                        query_start = int(parts[2])
                        query_end = int(parts[3])
                        align_len = int(parts[4])
                        identity = float(parts[6])

                        # 判断链方向：如果 query_start > query_end 则为反向
                        strand = "+" if query_start <= query_end else "-"

                        results.append({
                            "ref_start": ref_start,
                            "ref_end": ref_end,
                            "query_start": query_start,
                            "query_end": query_end,
                            "length": align_len,
                            "identity": identity,
                            "strand": strand,
                            "ref_id": parts[7] if len(parts) > 7 else "",
                            "query_id": parts[8] if len(parts) > 8 else ""
                        })
                    except (ValueError, IndexError):
                        continue
        return results

    def _parse_snps(self, snps_file: Path) -> List[Dict[str, Any]]:
        """
        解析 show-snps -T -H 输出，提取变异位点。
        show-snps 输出格式 (tab-separated, 无 header):
        [P1] [SUB] [SUB] [P2] [BUFF] [DIST] [LEN R] [LEN Q] [CTX R] [CTX Q] [FRM] [TAGS]
        """
        variants = []
        if not snps_file.exists():
            return variants

        try:
            with open(snps_file, 'r', encoding='utf-8', errors='replace') as f:
                for line in f:
                    parts = line.strip().split('\t')
                    if len(parts) < 12:
                        continue
                    try:
                        pos = int(parts[0])
                        ref_base = parts[1].upper()
                        alt_base = parts[2].upper()

                        # 判断变异类型
                        if ref_base == '.' and alt_base != '.':
                            var_type = "INS"
                            assessment = f"Insertion ({len(alt_base)}bp)"
                        elif ref_base != '.' and alt_base == '.':
                            var_type = "DEL"
                            assessment = f"Deletion ({len(ref_base)}bp)"
                        else:
                            var_type = "SNP"
                            transitions = {('A', 'G'), ('G', 'A'), ('C', 'T'), ('T', 'C')}
                            assessment = "Transition" if (ref_base, alt_base) in transitions else "Transversion"

                        variants.append({
                            "pos": pos,
                            "type": var_type,
                            "ref": ref_base if ref_base != '.' else '-',
                            "alt": alt_base if alt_base != '.' else '-',
                            "assessment": assessment,
                            "len": 1
                        })
                    except (ValueError, IndexError):
                        continue
        except Exception as e:
            self.logger.warning(f"SNP 解析异常（非致命）: {e}")

        return variants
