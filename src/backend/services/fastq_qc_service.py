# -*- coding: utf-8 -*-
"""
FASTQ 测序数据前置质控过滤服务 (Fastq QC Filter Pipeline)
支持：
1. 读长范围过滤 (Length QC: 滤除截断读段与超长嵌合体)
2. 自适应扩增子长度识别 (智能兼容 16S 全长 ~1500bp 与局部可变区 V3-V4 ~400bp)
3. Phred Q 平均质量值过滤 (Q-Score QC: 滤除三代测序重度噪声读段)
4. N 碱基比率过滤 (N-Ratio QC: 滤除未定碱基过多序列)
5. 质控统计报表产出 (QC Summary Metrics: 供前端看板与 Excel 导出)
"""
import gzip
import logging
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional, Sequence

logger = logging.getLogger("api_server")


@dataclass
class FastqQCReport:
    """单样本 FASTQ 质控统计报表"""
    sample_name: str = ""
    total_raw_reads: int = 0
    passed_clean_reads: int = 0
    dropped_len_short: int = 0
    dropped_len_long: int = 0
    dropped_low_quality: int = 0
    dropped_excessive_n: int = 0
    pass_rate_pct: float = 0.0
    mean_len_raw: float = 0.0
    mean_len_clean: float = 0.0
    mean_qscore_raw: float = 0.0
    mean_qscore_clean: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class FastqQCFilter:
    """扩增子测序质量控制过滤器"""

    def __init__(
        self,
        min_len: Optional[int] = 1200,
        max_len: Optional[int] = 1800,
        min_avg_qscore: float = 9.0,
        max_n_ratio: float = 0.05,
        auto_adapt_length: bool = True
    ):
        """
        :param min_len: 最小读长阈值 (全长 16S 默认 1200 bp)
        :param max_len: 最大读长阈值 (全长 16S 默认 1800 bp)
        :param min_avg_qscore: 最小平均 Phred 质量得分 (默认 9.0，滤除严重劣质序列)
        :param max_n_ratio: 允许的最大 N 碱基比例 (默认 5%)
        :param auto_adapt_length: 是否自适应识别扩增子类型 (如自动识别 V3-V4 局部可变区)
        """
        self.min_len = min_len
        self.max_len = max_len
        self.min_avg_qscore = float(min_avg_qscore)
        self.max_n_ratio = float(max_n_ratio)
        self.auto_adapt_length = auto_adapt_length

    @staticmethod
    def calc_mean_qscore(qual_str: str) -> float:
        """计算 Phred 质量字符串的算术平均 Q 值 (Q = ord(c) - 33)"""
        if not qual_str:
            return 0.0
        # 批量统计 ASCII 码总和
        total_q = sum(ord(c) - 33 for c in qual_str)
        return total_q / len(qual_str)

    def resolve_length_window(self, sample_lengths: List[int]) -> Tuple[int, int]:
        """依据抽样序列中位数智能决策质控读长窗口"""
        if not self.auto_adapt_length or not sample_lengths:
            return (self.min_len or 1200, self.max_len or 1800)

        sorted_lens = sorted(sample_lengths)
        median_len = sorted_lens[len(sorted_lens) // 2]

        if median_len >= 1000:
            # 判定为 16S / 18S / ITS 全长扩增子 (理论长度约 1300~1600 bp)
            low = min(self.min_len or 1200, int(median_len * 0.75))
            high = max(self.max_len or 1800, int(median_len * 1.35))
            return (low, high)
        else:
            # 判定为局部扩增子 (如 16S V3-V4、V4 等，长度通常在 250~550 bp)
            low = max(100, int(median_len * 0.65))
            high = int(median_len * 1.45)
            logger.info(f"[FastqQC] 识别为局部短扩增子 (中位数 {median_len} bp)，动态适配质控区间: [{low}, {high}] bp")
            return (low, high)

    def filter_reads(
        self,
        reads_triplets: Sequence[Tuple[str, str, str]],
        sample_name: str = ""
    ) -> Tuple[List[Tuple[str, str]], FastqQCReport]:
        """
        对已读入内存的三元组 (header, seq, qual) 执行综合质控过滤
        返回: (通过质控的 [(header, seq), ...], 质控统计报表)
        """
        total_raw = len(reads_triplets)
        if total_raw == 0:
            return [], FastqQCReport(sample_name=sample_name)

        # 抽样前 100 条长度决定区间
        sample_lens = [len(r[1]) for r in reads_triplets[:100]]
        eff_min_len, eff_max_len = self.resolve_length_window(sample_lens)

        clean_reads: List[Tuple[str, str]] = []
        dropped_len_short = 0
        dropped_len_long = 0
        dropped_low_q = 0
        dropped_excessive_n = 0

        total_len_raw = 0
        total_len_clean = 0
        total_q_raw = 0.0
        total_q_clean = 0.0

        for rid, seq, qual in reads_triplets:
            seq_len = len(seq)
            total_len_raw += seq_len
            q_mean = self.calc_mean_qscore(qual)
            total_q_raw += q_mean

            # 1. 读长下限过滤
            if seq_len < eff_min_len:
                dropped_len_short += 1
                continue

            # 2. 读长上限过滤 (超长嵌合体)
            if seq_len > eff_max_len:
                dropped_len_long += 1
                continue

            # 3. 质量值下限过滤
            if q_mean < self.min_avg_qscore:
                dropped_low_q += 1
                continue

            # 4. N 碱基比例过滤
            n_count = seq.count("N") + seq.count("n")
            if (n_count / max(1, seq_len)) > self.max_n_ratio:
                dropped_excessive_n += 1
                continue

            # 质控通过
            clean_reads.append((rid, seq))
            total_len_clean += seq_len
            total_q_clean += q_mean

        passed_cnt = len(clean_reads)
        report = FastqQCReport(
            sample_name=sample_name,
            total_raw_reads=total_raw,
            passed_clean_reads=passed_cnt,
            dropped_len_short=dropped_len_short,
            dropped_len_long=dropped_len_long,
            dropped_low_quality=dropped_low_q,
            dropped_excessive_n=dropped_excessive_n,
            pass_rate_pct=round((passed_cnt / max(1, total_raw)) * 100.0, 2),
            mean_len_raw=round(total_len_raw / max(1, total_raw), 1),
            mean_len_clean=round(total_len_clean / max(1, passed_cnt), 1) if passed_cnt > 0 else 0.0,
            mean_qscore_raw=round(total_q_raw / max(1, total_raw), 2),
            mean_qscore_clean=round(total_q_clean / max(1, passed_cnt), 2) if passed_cnt > 0 else 0.0
        )

        return clean_reads, report

    def filter_fastq_file(
        self,
        fq_path: Path,
        sample_name: str = ""
    ) -> Tuple[List[Tuple[str, str]], FastqQCReport]:
        """
        流式读取并质控指定 FASTQ 或 FASTQ.GZ 文件
        """
        reads_triplets: List[Tuple[str, str, str]] = []
        is_gz = fq_path.suffix.lower() == ".gz"
        open_fn = gzip.open if is_gz else open

        with open_fn(fq_path, "rt", encoding="utf-8", errors="ignore") as f:
            while True:
                h = f.readline()
                if not h:
                    break
                seq = f.readline().strip()
                f.readline()  # +
                qual = f.readline().strip()
                rid = h.strip().split()[0][1:]
                reads_triplets.append((rid, seq, qual))

        name = sample_name or fq_path.stem.replace(".fastq", "")
        return self.filter_reads(reads_triplets, sample_name=name)
