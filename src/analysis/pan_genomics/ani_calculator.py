# -*- coding: utf-8 -*-
"""
ani_calculator.py - 国际标准全基因组平均核苷酸一致性 (OrthoANI) 与正交平均氨基酸一致性 (OrthoAAI) 计算引擎

严格遵循生物信息学国际标准:
1. ICTV 细菌噬菌体分类规范 (Turner et al., 2021): 种界限 ANI >= 95%, 属界限 ANI >= 70%
2. OrthoANIu 正交双向最佳对齐算法 (Lee et al., 2016; Yoon et al., 2017)
3. 序列一致性 (ANI) 与基因组覆盖度 (Alignment Fraction, AF) 双轨解耦输出，严禁分母混杂稀释
4. 远缘样本无同源区段时规范输出 None (显示为 -/NA)，杜绝 0%/1% 伪低值
5. 支持系统 NCBI BLAST+ (2.16.0+) 多核安全并行流水线与纯 Python 优雅降级
"""

import os
import glob
import shutil
import tempfile
import subprocess
import logging
import concurrent.futures
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any

from .fast_matcher import fast_seq_identity, get_kmers

logger = logging.getLogger("pan_genomics.ani_calculator")


class SliceItem:
    """DNA 切片对象 (默认 1020 bp，密码子对齐窗口)"""
    __slots__ = ("slice_id", "sample_id", "seq", "start", "end", "length")

    def __init__(self, slice_id: str, sample_id: str, seq: str, start: int, end: int):
        self.slice_id = slice_id
        self.sample_id = sample_id
        self.seq = seq
        self.start = start
        self.end = end
        self.length = len(seq)


class OrthoANICalculator:
    """
    国际标准 OrthoANI / OrthoAAI 双轨计算引擎
    """

    def __init__(
        self,
        slice_len: int = 1020,
        min_identity: float = 70.0,
        min_coverage: float = 0.5,
        min_rbh_count: int = 3,
        min_af_threshold: float = 5.0
    ):
        """
        初始化计算参数
        :param slice_len: 切片窗口长度 (bp)，OrthoANI 标准为 1020 bp
        :param min_identity: 切片同源性最小阈值 (%)，ICTV/OrthoANI 标准为 70.0%
        :param min_coverage: 切片比对长度覆盖度阈值 (0.0 ~ 1.0)
        :param min_rbh_count: 判定全基因组显著同源的最低正交切片数 (少于该数归为远缘异属)
        :param min_af_threshold: 判定全基因组显著同源的最低覆盖度 (%)
        """
        self.slice_len = slice_len
        self.min_identity = min_identity
        self.min_coverage = min_coverage
        self.min_rbh_count = min_rbh_count
        self.min_af_threshold = min_af_threshold
        self.blastn_path = self._resolve_blastn_binary()
        if self.blastn_path:
            logger.info(f"OrthoANI 成功定位并加载 NCBI BLASTN 引擎: {self.blastn_path}")
        else:
            logger.warning("未探测到本地 NCBI BLASTN，OrthoANI 将自适应平滑启用纯 Python/C 备用对齐器")

    @staticmethod
    def _resolve_blastn_binary() -> Optional[str]:
        """
        多层级智能定位 NCBI BLASTN 可执行文件:
        1. 系统环境变量 PATH
        2. 项目内置打包发布目录 (dist/NCBI_BLAST_GUI/_internal/bin) 与 vendor 目录
        3. 常见操作系统独立安装目录 (C/D/E 盘 Program Files/NCBI/blast-*)
        """
        # 1. 优先检查系统 PATH
        p_path = shutil.which("blastn")
        if p_path:
            return p_path

        # 2. 检查项目工程内置打包目录与工具箱
        root = Path(__file__).resolve().parent.parent.parent.parent
        internal_candidates = [
            root / "dist" / "NCBI_BLAST_GUI" / "_internal" / "bin" / "blastn.exe",
            root / "tools" / "ncbi_dist" / "bin" / "blastn.exe",
            root / "vendor" / "blast" / "bin" / "blastn.exe",
            root / "src" / "workbench" / "bin" / "blastn.exe",
        ]
        for candidate in internal_candidates:
            if candidate.exists() and os.access(str(candidate), os.R_OK):
                return str(candidate)

        # 3. 扫描 Windows 常见独立安装目录
        search_patterns = [
            r"C:\Program Files\NCBI\blast-*\bin\blastn.exe",
            r"D:\Program Files\NCBI\blast-*\bin\blastn.exe",
            r"E:\Program Files\NCBI\blast-*\bin\blastn.exe",
            r"C:\Program Files (x86)\NCBI\blast-*\bin\blastn.exe",
        ]
        for pat in search_patterns:
            matches = glob.glob(pat)
            if matches and os.path.exists(matches[0]):
                return matches[0]

        return None

    def _get_safe_workers(self, user_threads: Optional[int] = None) -> int:
        """动态计算安全并发线程数 (保留 2 核心防卡死，上限 30 核心)"""
        cpu_cnt = os.cpu_count() or 4
        if user_threads and user_threads > 0:
            return min(user_threads, max(1, cpu_cnt - 2))
        return max(1, min(cpu_cnt - 2, 30))

    def slice_genome(self, sample_id: str, dna_seq: str) -> List[SliceItem]:
        """将全长基因组 DNA 严格切分为无重叠 1020 bp 切片窗口"""
        clean_seq = dna_seq.strip().upper().replace("\r", "").replace("\n", "")
        total_l = len(clean_seq)
        slices: List[SliceItem] = []
        if total_l == 0:
            return slices

        idx = 0
        cur_pos = 0
        while cur_pos < total_l:
            end_pos = min(cur_pos + self.slice_len, total_l)
            chunk = clean_seq[cur_pos:end_pos]
            # 最后一个片段若低于 100 bp 则舍弃，否则保留
            if len(chunk) >= 100 or cur_pos == 0:
                s_id = f"{sample_id}_sl_{idx}"
                slices.append(SliceItem(s_id, sample_id, chunk, cur_pos + 1, end_pos))
                idx += 1
            cur_pos = end_pos

        return slices

    def calculate_ortho_ani_pair(
        self,
        s1: str,
        s2: str,
        seq1: str,
        seq2: str,
        temp_dir: Path
    ) -> Dict[str, Any]:
        """
        计算两样本间符合国际标准的 OrthoANI (DNA 核酸水平)
        """
        if s1 == s2:
            return {
                "s1": s1,
                "s2": s2,
                "ani": 100.0,
                "af": 100.0,
                "rbh_count": len(self.slice_genome(s1, seq1)),
                "status": "identity",
                "taxonomy_call": "同种噬菌体株系 (Same Species)"
            }

        slices1 = self.slice_genome(s1, seq1)
        slices2 = self.slice_genome(s2, seq2)

        len1 = len(seq1)
        len2 = len(seq2)
        if not slices1 or not slices2 or len1 == 0 or len2 == 0:
            return {
                "s1": s1,
                "s2": s2,
                "ani": None,
                "af": 0.0,
                "rbh_count": 0,
                "status": "no_sequence",
                "taxonomy_call": "缺少序列信息"
            }

        # 优先调用系统 NCBI BLASTN 执行切片比对
        if self.blastn_path:
            return self._calculate_ani_with_blastn(s1, s2, seq1, seq2, slices1, slices2, temp_dir)
        else:
            return self._calculate_ani_fallback(s1, s2, seq1, seq2, slices1, slices2)

    def _calculate_ani_with_blastn(
        self,
        s1: str,
        s2: str,
        seq1: str,
        seq2: str,
        slices1: List[SliceItem],
        slices2: List[SliceItem],
        work_dir: Path
    ) -> Dict[str, Any]:
        """使用 NCBI BLAST+ 2.16.0+ 进行切片集对切片集的严格正交双向最佳命中 (RBH) 比对"""
        pair_prefix = f"{s1}_vs_{s2}"
        q1_file = work_dir / f"{pair_prefix}_sl1.fa"
        q2_file = work_dir / f"{pair_prefix}_sl2.fa"

        # 写入切片 FASTA (每个切片独立作为一个记录)
        with open(q1_file, "w", encoding="utf-8") as f:
            for sl in slices1:
                f.write(f">{sl.slice_id}\n{sl.seq}\n")
        with open(q2_file, "w", encoding="utf-8") as f:
            for sl in slices2:
                f.write(f">{sl.slice_id}\n{sl.seq}\n")

        outfmt = "6 qseqid sseqid pident length mismatch gapopen qstart qend sstart send evalue bitscore"

        # 1. Forward: Slices1 -> Slices2
        cmd_fwd = [
            self.blastn_path,
            "-query", str(q1_file),
            "-subject", str(q2_file),
            "-dust", "no",
            "-soft_masking", "false",
            "-perc_identity", str(self.min_identity),
            "-evalue", "1e-5",
            "-outfmt", outfmt
        ]
        # 2. Reverse: Slices2 -> Slices1
        cmd_rev = [
            self.blastn_path,
            "-query", str(q2_file),
            "-subject", str(q1_file),
            "-dust", "no",
            "-soft_masking", "false",
            "-perc_identity", str(self.min_identity),
            "-evalue", "1e-5",
            "-outfmt", outfmt
        ]

        def run_blast(cmd):
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, check=True)
                return res.stdout
            except Exception as e:
                logger.warning(f"BLASTN 比对异常: {e}")
                return ""

        out_fwd = run_blast(cmd_fwd)
        out_rev = run_blast(cmd_rev)

        map1 = {sl.slice_id: sl for sl in slices1}
        map2 = {sl.slice_id: sl for sl in slices2}

        # 辅助解析器：支持单个切片跨越反向互补/移位边界时的无重叠 HSP 区间贪婪累加
        def parse_blast_with_merged_hsps(out_text: str, slice_map: Dict[str, SliceItem]):
            hits_by_q: Dict[str, List[Dict[str, Any]]] = {}
            for line in out_text.strip().splitlines():
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) < 12:
                    continue
                qid, sid = parts[0], parts[1]
                pid = float(parts[2])
                alen = int(parts[3])
                qs, qe = int(parts[6]), int(parts[7])
                bscore = float(parts[11])

                sl_item = slice_map.get(qid)
                if not sl_item:
                    continue

                if qid not in hits_by_q:
                    hits_by_q[qid] = []
                hits_by_q[qid].append({
                    "sid": sid,
                    "pid": pid,
                    "alen": alen,
                    "qs": min(qs, qe),
                    "qe": max(qs, qe),
                    "bscore": bscore
                })

            best_results: Dict[str, Tuple[str, float, float, int, List[str]]] = {}
            for qid, hlist in hits_by_q.items():
                sl_len = slice_map[qid].length
                # 按 bitscore 降序排序
                hlist.sort(key=lambda x: x["bscore"], reverse=True)
                selected: List[Dict[str, Any]] = []
                total_len = 0
                weighted_pid = 0.0
                for h in hlist:
                    # 检查与已选中区间的重叠（允许跨切片窗口的相邻片段无缝拼接）
                    overlap = any(max(h["qs"], s["qs"]) <= min(h["qe"], s["qe"]) for s in selected)
                    if not overlap:
                        selected.append(h)
                        total_len += h["alen"]
                        weighted_pid += h["pid"] * h["alen"]

                if total_len / sl_len >= self.min_coverage:
                    avg_pid = (weighted_pid / total_len) if total_len > 0 else 0.0
                    primary_sid = selected[0]["sid"]
                    all_target_sids = [s["sid"] for s in selected]
                    best_results[qid] = (primary_sid, selected[0]["bscore"], avg_pid, total_len, all_target_sids)

            return best_results

        best_fwd = parse_blast_with_merged_hsps(out_fwd, map1)
        best_rev = parse_blast_with_merged_hsps(out_rev, map2)

        # 严格正交互为最佳 (Reciprocal Best Hit)
        rbh_hits: List[Tuple[float, int]] = []
        aligned_len1 = 0
        aligned_len2 = 0

        for q1_id, (s2_id, _, pid1, l1, s2_targets) in best_fwd.items():
            if s2_id in best_rev:
                rev_targets = best_rev[s2_id][4]
                if q1_id in rev_targets or best_rev[s2_id][0] == q1_id:
                    pid2 = best_rev[s2_id][2]
                    l2 = best_rev[s2_id][3]
                    avg_pid = (pid1 + pid2) / 2.0
                    avg_l = (l1 + l2) // 2
                    rbh_hits.append((avg_pid, avg_l))
                    aligned_len1 += l1
                    aligned_len2 += l2

        # 清理临时切片文件
        for f_tmp in (q1_file, q2_file):
            try:
                if f_tmp.exists():
                    f_tmp.unlink()
            except Exception:
                pass

        return self._summarize_ani_metrics(
            s1=s1,
            s2=s2,
            rbh_hits=rbh_hits,
            total_len1=len(seq1),
            total_len2=len(seq2),
            aligned_len1=aligned_len1,
            aligned_len2=aligned_len2
        )

    def _calculate_ani_fallback(
        self,
        s1: str,
        s2: str,
        seq1: str,
        seq2: str,
        slices1: List[SliceItem],
        slices2: List[SliceItem]
    ) -> Dict[str, Any]:
        """
        纯 Python 种子锚定双向切片对齐器 (无外部 BLAST+ 时的平滑高精度自备引擎):
        1. 自动正反互补链极速判定与基准链对齐 (Auto Strand Orientation Correction)
        2. 环状染色体倍增展开 (Circular Permutation Wrap-Around Support)
        3. K-mer 种子索引快速锚定目标物理区间
        4. 局部核酸严格比对与正交双向验证 (Bi-directional RBH)
        """
        from collections import Counter

        clean1 = seq1.strip().upper().replace("\r", "").replace("\n", "")
        clean2 = seq2.strip().upper().replace("\r", "").replace("\n", "")
        l1, l2 = len(clean1), len(clean2)
        if l1 == 0 or l2 == 0:
            return self._summarize_ani_metrics(s1, s2, [], l1, l2, 0, 0)

        # 1. 宏观相对朝向极速采样探测 (正链 vs 反向互补链)
        k_seed = 15
        sample_step = max(30, l1 // 100)
        km_sample = {clean1[i:i + k_seed] for i in range(0, min(l1 - k_seed + 1, 10000), sample_step)}

        # 统计正向与反向互补链的种子命中频次
        fwd_hits = sum(1 for seed in km_sample if seed in clean2)

        # 生成 clean2 的反向互补
        comp_trans = str.maketrans("ACGTURYKMSWBDHVN", "TGCAAYRMKWSVHDBN")
        clean2_rc = clean2.translate(comp_trans)[::-1]
        rev_hits = sum(1 for seed in km_sample if seed in clean2_rc)

        # 规范化对齐方向: 若反向匹配显著占优，则对 clean2 取反向互补进行同向拉齐
        use_rc = rev_hits > fwd_hits and rev_hits >= 3
        active_seq2 = clean2_rc if use_rc else clean2

        # 环状染色体倍增展开以支持 pac 包装移位/末端断点跨越
        doubled_seq2 = active_seq2 + active_seq2

        # 2. 构建 target 的 15-mer 稀疏索引 (步长 3 bp)
        s2_idx: Dict[str, int] = {}
        for idx in range(0, len(active_seq2) - k_seed + 1, 3):
            sub = active_seq2[idx:idx + k_seed]
            if sub not in s2_idx:
                s2_idx[sub] = idx

        # 3. 对 slices1 遍历进行锚定与切片比对 (S1 -> S2)
        best_fwd: Dict[int, Tuple[int, float, int]] = {}

        for i, sl in enumerate(slices1):
            chunk = sl.seq
            c_len = sl.length
            # 提取切片内的采样种子进行位置投票
            cand_offsets = []
            for p in range(0, c_len - k_seed + 1, 20):
                seed = chunk[p:p + k_seed]
                if seed in s2_idx:
                    cand_offsets.append(s2_idx[seed] - p)

            if not cand_offsets:
                continue

            target_offset, vote_count = Counter(cand_offsets).most_common(1)[0]
            if vote_count < 2 and c_len > 300:
                continue

            # 处理环状取模偏移
            target_offset = target_offset % len(active_seq2)
            matched_chunk = doubled_seq2[target_offset:target_offset + c_len]
            if len(matched_chunk) < c_len:
                continue

            # 快速计算核酸同一性
            matches = sum(1 for a, b in zip(chunk, matched_chunk) if a == b)
            pid = (matches / c_len) * 100.0
            if pid >= self.min_identity:
                best_fwd[i] = (target_offset, pid, c_len)

        # 4. 反向验证 (S2 -> S1) 构建严格双向命中 RBH
        s1_idx: Dict[str, int] = {}
        doubled_seq1 = clean1 + clean1
        for idx in range(0, l1 - k_seed + 1, 3):
            sub = clean1[idx:idx + k_seed]
            if sub not in s1_idx:
                s1_idx[sub] = idx

        rbh_hits: List[Tuple[float, int]] = []
        aligned_len1 = 0
        aligned_len2 = 0

        # 对 S1 中成功命中的切片，检验反向映射的对称性
        for i, (target_offset, pid1, alen1) in best_fwd.items():
            sl1_origin_pos = slices1[i].start - 1
            chunk2 = doubled_seq2[target_offset:target_offset + alen1]
            rev_offsets = []
            for p in range(0, len(chunk2) - k_seed + 1, 20):
                seed = chunk2[p:p + k_seed]
                if seed in s1_idx:
                    rev_offsets.append(s1_idx[seed] - p)

            if rev_offsets:
                rev_target_offset, _ = Counter(rev_offsets).most_common(1)[0]
                rev_target_offset = rev_target_offset % l1
                # 检验物理区间是否对称吻合 (容许 50 bp 微小断点偏差)
                if abs(rev_target_offset - (sl1_origin_pos % l1)) <= 50:
                    matched_s1 = doubled_seq1[rev_target_offset:rev_target_offset + alen1]
                    matches2 = sum(1 for a, b in zip(chunk2, matched_s1) if a == b)
                    pid2 = (matches2 / alen1) * 100.0 if alen1 > 0 else 0.0
                    avg_pid = (pid1 + pid2) / 2.0
                    rbh_hits.append((avg_pid, alen1))
                    aligned_len1 += alen1
                    aligned_len2 += alen1

        return self._summarize_ani_metrics(
            s1=s1,
            s2=s2,
            rbh_hits=rbh_hits,
            total_len1=l1,
            total_len2=l2,
            aligned_len1=aligned_len1,
            aligned_len2=aligned_len2
        )

    def _summarize_ani_metrics(
        self,
        s1: str,
        s2: str,
        rbh_hits: List[Tuple[float, int]],
        total_len1: int,
        total_len2: int,
        aligned_len1: int,
        aligned_len2: int
    ) -> Dict[str, Any]:
        """按国际标准公式总结 ANI、AF 与分类结论"""
        rbh_count = len(rbh_hits)
        total_genome_len = total_len1 + total_len2
        total_aligned_len = aligned_len1 + aligned_len2

        # 1. 计算对齐覆盖度 AF (Alignment Fraction, 0.0 ~ 100.0%)
        af = (total_aligned_len / total_genome_len * 100.0) if total_genome_len > 0 else 0.0
        af = round(min(100.0, max(0.0, af)), 1)

        # 2. 国际标准门槛判断:
        # a. 若总切片数较多(>=10)，但 RBH 命中数低于阈值(如 <3)，说明仅存在孤立零星匹配，无全基因组同源性
        total_slices = max(total_len1, total_len2) // self.slice_len
        if total_slices >= 10 and rbh_count < self.min_rbh_count:
            return {
                "s1": s1,
                "s2": s2,
                "ani": None,
                "af": af,
                "rbh_count": rbh_count,
                "status": "distinct",
                "taxonomy_call": "远缘 / 异属噬菌体 (Distinct Genus)"
            }

        # b. 若正交切片数为 0 或基因组对齐覆盖度低于最低阈值 (5.0%)
        if rbh_count == 0 or af < self.min_af_threshold:
            return {
                "s1": s1,
                "s2": s2,
                "ani": None,
                "af": af,
                "rbh_count": rbh_count,
                "status": "distinct",
                "taxonomy_call": "远缘 / 异属噬菌体 (Distinct Genus)"
            }

        # 3. 计算加权平均一致性 ANI (仅对通过显著同源性检验的切片求加权均值)
        sum_weighted_ident = sum(pid * weight for pid, weight in rbh_hits)
        sum_weights = sum(weight for _, weight in rbh_hits)
        ani = (sum_weighted_ident / sum_weights) if sum_weights > 0 else 0.0
        ani = round(min(100.0, max(0.0, ani)), 2)

        # 4. ICTV 噬菌体分类等级推断
        if ani >= 95.0 and af >= 85.0:
            call = "同种噬菌体株系 (Same Species)"
        elif ani >= 70.0 and af >= 20.0:
            call = "同属噬菌体株系 (Same Genus)"
        else:
            call = "远缘 / 异属噬菌体 (Distinct Genus)"

        return {
            "s1": s1,
            "s2": s2,
            "ani": ani,
            "af": af,
            "rbh_count": rbh_count,
            "status": "ortholog",
            "taxonomy_call": call
        }

    def calculate_ortho_aai_pair(
        self,
        s1: str,
        s2: str,
        prot_seqs1: List[Tuple[str, Any]],
        prot_seqs2: List[Tuple[str, Any]]
    ) -> Dict[str, Any]:
        """
        纯蛋白质组规范 OrthoAAI (严格基于双向最佳命中 BBH，以命中对数为分母)
        适用于仅提供蛋白 FAA 而缺乏全长核苷酸序列时的自适应降级
        """
        if s1 == s2:
            return {
                "s1": s1,
                "s2": s2,
                "ani": 100.0,
                "af": 100.0,
                "rbh_count": len(prot_seqs1),
                "status": "identity",
                "taxonomy_call": "同种噬菌体株系 (Same Species)"
            }

        n1 = len(prot_seqs1)
        n2 = len(prot_seqs2)
        if n1 == 0 or n2 == 0:
            return {
                "s1": s1,
                "s2": s2,
                "ani": None,
                "af": 0.0,
                "rbh_count": 0,
                "status": "no_sequence",
                "taxonomy_call": "缺少蛋白序列"
            }

        # 1. S1 -> S2 最佳命中
        best_1to2: Dict[int, Tuple[int, float]] = {}
        for i, (sq1, km1) in enumerate(prot_seqs1):
            l1 = len(sq1)
            b_j = -1
            b_ratio = 0.0
            for j, (sq2, km2) in enumerate(prot_seqs2):
                l2 = len(sq2)
                if abs(l1 - l2) / max(l1, l2) > 0.45:
                    continue
                ratio = fast_seq_identity(sq1, sq2, ident_thresh=0.25, cov_thresh=0.4, kmers1=km1, kmers2=km2)
                if ratio > b_ratio:
                    b_ratio = ratio
                    b_j = j
            if b_j >= 0 and b_ratio >= 0.25:
                best_1to2[i] = (b_j, b_ratio)

        # 2. S2 -> S1 最佳命中
        best_2to1: Dict[int, Tuple[int, float]] = {}
        for j, (sq2, km2) in enumerate(prot_seqs2):
            l2 = len(sq2)
            b_i = -1
            b_ratio = 0.0
            for i, (sq1, km1) in enumerate(prot_seqs1):
                l1 = len(sq1)
                if abs(l1 - l2) / max(l1, l2) > 0.45:
                    continue
                ratio = fast_seq_identity(sq2, sq1, ident_thresh=0.25, cov_thresh=0.4, kmers1=km2, kmers2=km1)
                if ratio > b_ratio:
                    b_ratio = ratio
                    b_i = i
            if b_i >= 0 and b_ratio >= 0.25:
                best_2to1[j] = (b_i, b_ratio)

        # 3. 严格正交互为最佳 (BBH)
        bbh_identities: List[float] = []
        for i, (j, r1) in best_1to2.items():
            if j in best_2to1 and best_2to1[j][0] == i:
                r2 = best_2to1[j][1]
                bbh_identities.append(((r1 + r2) / 2.0) * 100.0)

        bbh_count = len(bbh_identities)
        af_prot = round((2.0 * bbh_count / (n1 + n2)) * 100.0, 1)

        # 远缘无显著同源判定: 若总蛋白较多(>=10)但正交命中过少，或无命中/覆盖度低于最低阈值
        if (max(n1, n2) >= 10 and bbh_count < self.min_rbh_count) or bbh_count == 0 or af_prot < self.min_af_threshold:
            return {
                "s1": s1,
                "s2": s2,
                "ani": None,
                "af": af_prot,
                "rbh_count": bbh_count,
                "status": "distinct",
                "taxonomy_call": "远缘 / 异属噬菌体 (Distinct Genus)"
            }

        # 严格以命中正交对数为分母
        mean_aai = round(sum(bbh_identities) / bbh_count, 2)
        call = "同种噬菌体株系 (Same Species)" if mean_aai >= 95.0 and af_prot >= 80.0 else (
            "同属噬菌体株系 (Same Genus)" if mean_aai >= 65.0 and af_prot >= 25.0 else "远缘 / 异属噬菌体 (Distinct Genus)"
        )

        return {
            "s1": s1,
            "s2": s2,
            "ani": mean_aai,
            "af": af_prot,
            "rbh_count": bbh_count,
            "status": "ortholog",
            "taxonomy_call": call
        }

    def compute_matrix(
        self,
        sample_ids: List[str],
        dna_sequences: Dict[str, str],
        sample_prot_seqs: Optional[Dict[str, List[Tuple[str, Any]]]] = None,
        max_workers: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        高并发计算全样本两两矩阵流水线
        """
        workers = self._get_safe_workers(max_workers)
        matrix: Dict[str, Dict[str, Optional[float]]] = {s1: {s2: None for s2 in sample_ids} for s1 in sample_ids}
        af_matrix: Dict[str, Dict[str, float]] = {s1: {s2: 0.0 for s2 in sample_ids} for s1 in sample_ids}
        taxonomy_matrix: Dict[str, Dict[str, str]] = {s1: {s2: "" for s2 in sample_ids} for s1 in sample_ids}

        # 对角线自身比对初始化
        for s in sample_ids:
            matrix[s][s] = 100.0
            af_matrix[s][s] = 100.0
            taxonomy_matrix[s][s] = "自身参照 (Self)"

        # 检查是否全部样本都拥有 DNA 序列
        has_all_dna = all(len(dna_sequences.get(sid, "")) >= 200 for sid in sample_ids)
        metric_type = "OrthoANI (DNA 1020bp RBH)" if has_all_dna else "OrthoAAI (Protein BBH)"

        pairs = [
            (sample_ids[i], sample_ids[j])
            for i in range(len(sample_ids))
            for j in range(i + 1, len(sample_ids))
        ]
        if not pairs:
            return {
                "ani_matrix": matrix,
                "af_matrix": af_matrix,
                "taxonomy_matrix": taxonomy_matrix,
                "metric_type": metric_type
            }

        with tempfile.TemporaryDirectory(prefix="ani_pipe_") as temp_dir_str:
            temp_dir = Path(temp_dir_str)

            def task_runner(p: Tuple[str, str]):
                s1, s2 = p
                if has_all_dna:
                    return self.calculate_ortho_ani_pair(
                        s1, s2, dna_sequences[s1], dna_sequences[s2], temp_dir
                    )
                else:
                    seqs1 = sample_prot_seqs.get(s1, []) if sample_prot_seqs else []
                    seqs2 = sample_prot_seqs.get(s2, []) if sample_prot_seqs else []
                    return self.calculate_ortho_aai_pair(s1, s2, seqs1, seqs2)

            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(task_runner, p) for p in pairs]
                for fut in concurrent.futures.as_completed(futures):
                    res = fut.result()
                    s1, s2 = res["s1"], res["s2"]
                    ani_val = res["ani"]
                    af_val = res["af"]
                    call_val = res["taxonomy_call"]

                    matrix[s1][s2] = ani_val
                    matrix[s2][s1] = ani_val

                    af_matrix[s1][s2] = af_val
                    af_matrix[s2][s1] = af_val

                    taxonomy_matrix[s1][s2] = call_val
                    taxonomy_matrix[s2][s1] = call_val

        return {
            "ani_matrix": matrix,
            "af_matrix": af_matrix,
            "taxonomy_matrix": taxonomy_matrix,
            "metric_type": metric_type
        }
