# -*- coding: utf-8 -*-
r"""
NGCS 组装引擎长读长缺陷解决方案沙盒原型与评估 (Defects Solution Sandboxed Prototype)

在正式修改 E:\NGCS 生产代码之前，本模块在隔离沙盒中实现拟议的增强算法原型，
并与基线测试进行对比验证，确保方案的严谨性与可行性：
1. 覆盖度感知后处理 (Coverage-Aware Purging)：精准过滤低覆盖幽灵片段；
2. 自适应容错 Dovetail (Adaptive Noise-Tolerant Dovetail)：支持 2%~5% 残余测序噪声下的精准重叠识别与无缝融合；
3. 容错首尾环化闭合 (Noise-Tolerant Circularization)：识别含有残余测序噪声的首尾 DTR 并精确闭合成环。
"""

import unittest
import sys
import os
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional

_TESTS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TESTS_DIR.parent
for _p in (str(_TESTS_DIR), str(_PROJECT_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from src.assembly.utils.path_resolver import resolve_ngcs_root

_NGCS_ROOT = str(resolve_ngcs_root())
if _NGCS_ROOT not in sys.path:
    sys.path.append(_NGCS_ROOT)

from ngcs.utils.edlib_compat import edlib
from ngcs.spectral.backbone import reverse_complement
from test_ngcs_defects_evaluation import generate_pseudo_random_dna


class EnhancedPostProcessorPrototype:
    """沙盒增强型后处理引擎原型"""

    def __init__(self, min_length: int = 500, min_coverage_ratio: float = 0.08, min_absolute_coverage: float = 15.0):
        self.min_length = min_length
        self.min_coverage_ratio = min_coverage_ratio
        self.min_absolute_coverage = min_absolute_coverage

    def purge_low_coverage_artifacts(
        self,
        contigs: List[Tuple[str, str, bool]],
        coverage_map: Optional[Dict[str, float]] = None,
        global_mean_cov: float = 0.0
    ) -> List[Tuple[str, str, bool]]:
        """
        [解决方案 1] 基于真实物理测序深度的幽灵片段过滤
        """
        if not coverage_map or global_mean_cov <= 0:
            return contigs

        retained = []
        # 设定动态阈值：至少高于全局均值的 8%，且不低于绝对阈值 (如 15x)
        cutoff = max(self.min_absolute_coverage, global_mean_cov * self.min_coverage_ratio)

        for name, seq, is_circ in contigs:
            cov = coverage_map.get(name, 0.0)
            if cov < cutoff and not is_circ:
                # 剔除低覆盖非环状伪装配片段
                continue
            retained.append((name, seq, is_circ))

        return retained

    def find_dovetail_overlap_adaptive(
        self,
        seqA: str,
        seqB: str,
        min_ovlp: int = 40,
        max_error_rate: float = 0.05
    ) -> Tuple[int, str]:
        """
        [解决方案 2] 自适应三代长读长容错 Dovetail 识别与无缝融合
        克服原版单一 25-mer 精确匹配遇错配即断裂的严重缺陷。
        """
        LA, LB = len(seqA), len(seqB)
        if LA < min_ovlp or LB < min_ovlp:
            return 0, ""

        # 多探针尺度快速锚定
        probe_sizes = [250, 120, 60, 30]
        best_overlap = 0
        best_fused = ""
        best_error = 1.0

        for p_sz in probe_sizes:
            if LB < p_sz or LA < p_sz:
                continue
            probe = seqB[:p_sz]
            k_probe_err = max(2, int(p_sz * max_error_rate))
            
            # 在 seqA 末尾扫描 probe 的对齐位置
            search_window_sz = min(LA, max(p_sz * 8, 4000))
            tail_seqA = seqA[-search_window_sz:]
            aln = edlib.align(probe, tail_seqA, mode="HW", task="locations", k=k_probe_err)

            if aln['editDistance'] != -1 and aln.get('locations'):
                for loc in aln['locations']:
                    # loc 是在 tail_seqA 中的坐标
                    probe_start_in_tail = loc[0]
                    # 计算由该位置推导出的 seqA 尾部与 seqB 开头的重叠长度
                    cand_ovlp = search_window_sz - probe_start_in_tail
                    if cand_ovlp < min_ovlp or cand_ovlp > LB or cand_ovlp > LA:
                        continue

                    # 全局半全局比对 (NW/HW) 校验整个重叠区
                    subA = seqA[-cand_ovlp:]
                    subB = seqB[:cand_ovlp]
                    k_full_err = max(3, int(cand_ovlp * max_error_rate))
                    full_aln = edlib.align(subA, subB, mode="NW", k=k_full_err)

                    ed = full_aln.get('editDistance', -1)
                    if ed != -1 and ed <= k_full_err:
                        err = float(ed) / float(cand_ovlp)
                        if err <= max_error_rate and cand_ovlp > best_overlap:
                            best_overlap = cand_ovlp
                            best_error = err
                            # 融合：seqA 前半段 + seqB
                            best_fused = seqA[:-cand_ovlp] + seqB
                if best_overlap >= min_ovlp:
                    break

        return best_overlap, best_fused

    def trim_circular_dtr_adaptive(
        self,
        seq: str,
        min_ovlp: int = 150,
        max_error_rate: float = 0.05
    ) -> Tuple[str, bool, int]:
        """
        [解决方案 3] 自适应首尾 DTR 环化识别与冗余末端修剪
        解决带有 2%~5% 测序噪声时丢失环化闭合的缺陷。
        """
        L = len(seq)
        if L < min_ovlp * 2:
            return seq, False, 0

        # 检查 seq 的末端是否与 seq 的开头以容错方式重叠 (DTR)
        # 噬菌体末端冗余通常在 200 bp ~ 5,000 bp 之间
        max_test_ovlp = min(L // 2, 8000)
        probe_sz = 100

        head_probe = seq[:probe_sz]
        k_err = max(2, int(probe_sz * max_error_rate))

        tail_window = seq[-max_test_ovlp:]
        aln = edlib.align(head_probe, tail_window, mode="HW", task="locations", k=k_err)

        if aln['editDistance'] != -1 and aln.get('locations'):
            for loc in aln['locations']:
                cand_ovlp = len(tail_window) - loc[0]
                if cand_ovlp < min_ovlp or cand_ovlp > max_test_ovlp:
                    continue

                sub_tail = seq[-cand_ovlp:]
                sub_head = seq[:cand_ovlp]
                k_full = max(3, int(cand_ovlp * max_error_rate))
                full_aln = edlib.align(sub_tail, sub_head, mode="NW", k=k_full)
                
                ed = full_aln.get('editDistance', -1)
                if ed != -1 and ed <= k_full:
                    err = float(ed) / float(cand_ovlp)
                    if err <= max_error_rate:
                        # 成功识别首尾闭环！修剪掉末端的重复冗余，返回真实染色体
                        trimmed_chromosome = seq[:-cand_ovlp]
                        return trimmed_chromosome, True, cand_ovlp

        return seq, False, 0


class TestNGCSDefectsSolutionPrototype(unittest.TestCase):
    """验证沙盒原型解决方案对三大缺陷的修复效果"""

    def setUp(self):
        self.proto = EnhancedPostProcessorPrototype()

    def test_prototype_solution_1_purge_ghost_contigs(self):
        """[方案验证 1] 验证覆盖度感知过滤能 100% 滤除 1x~3x 幽灵片段"""
        true_chromosome = generate_pseudo_random_dna(5000, seed=101)
        ghost_contig_1 = generate_pseudo_random_dna(2000, seed=202)
        ghost_contig_2 = generate_pseudo_random_dna(2000, seed=303)

        raw_contigs = [
            ("contig_real", true_chromosome, False),
            ("contig_ghost_1", ghost_contig_1, False),
            ("contig_ghost_2", ghost_contig_2, False),
        ]

        # 真实物理覆盖度
        coverage_map = {
            "contig_real": 635.0,
            "contig_ghost_1": 1.0,
            "contig_ghost_2": 1.9,
        }
        global_mean = 635.0

        retained = self.proto.purge_low_coverage_artifacts(raw_contigs, coverage_map, global_mean)

        print("\n--- [Solution 1 Prototype Validation] ---")
        print(f"输入片段数: {len(raw_contigs)}, 过滤后保留片段数: {len(retained)}")
        for r in retained:
            print(f"  保留片段: {r[0]} (Coverage={coverage_map[r[0]]}x)")

        self.assertEqual(len(retained), 1, "方案验证成功：成功清除全部 1x~2x 幽灵片段！")
        self.assertEqual(retained[0][0], "contig_real")

    def test_prototype_solution_2_adaptive_dovetail(self):
        """[方案验证 2] 验证自适应容错 Dovetail 能在 3% 噪声下完美融合重叠片段"""
        prefix = generate_pseudo_random_dna(800, seed=401)
        overlap_true = generate_pseudo_random_dna(480, seed=402)
        suffix = generate_pseudo_random_dna(800, seed=403)

        seqA = prefix + overlap_true
        overlap_noisy_list = list(overlap_true)
        for i in range(10, len(overlap_noisy_list), 33):
            overlap_noisy_list[i] = 'A' if overlap_noisy_list[i] != 'A' else 'T'
        overlap_noisy = "".join(overlap_noisy_list)
        seqB = overlap_noisy + suffix

        ovlp_len, fused = self.proto.find_dovetail_overlap_adaptive(seqA, seqB, min_ovlp=50, max_error_rate=0.05)

        print("\n--- [Solution 2 Prototype Validation] ---")
        print(f"真实物理重叠: 480 bp, 容错 Dovetail 识别重叠: {ovlp_len} bp")
        print(f"预期融合后长度: 2080 bp, 实际融合长度: {len(fused)} bp")

        self.assertGreaterEqual(ovlp_len, 450, "方案验证成功：准确识别出 >450 bp 容错重叠！")
        self.assertEqual(len(fused), 2080, "方案验证成功：融合后长度正好为 2080 bp！")
        self.assertTrue(fused.startswith(prefix))
        self.assertTrue(fused.endswith(suffix))

    def test_prototype_solution_3_adaptive_circularization(self):
        """[方案验证 3] 验证自适应环化算法能在带有 2.5% 残余噪声时精准闭合成环"""
        core = generate_pseudo_random_dna(1500, seed=501)
        dtr_true = generate_pseudo_random_dna(600, seed=502)

        dtr_noisy = list(dtr_true)
        for i in range(15, len(dtr_noisy), 40):
            dtr_noisy[i] = 'G' if dtr_noisy[i] != 'G' else 'C'
        dtr_noisy_str = "".join(dtr_noisy)

        concatenated_seq = dtr_true + core + dtr_noisy_str # 2700 bp

        trimmed_seq, is_circ, ovlp = self.proto.trim_circular_dtr_adaptive(concatenated_seq, min_ovlp=150, max_error_rate=0.05)

        print("\n--- [Solution 3 Prototype Validation] ---")
        print(f"拼接序列含 600 bp 噪声 DTR (全长: {len(concatenated_seq)} bp)")
        print(f"自适应环化结果: is_circular={is_circ}, 识别 DTR={ovlp} bp, 修剪后纯环长={len(trimmed_seq)} bp")

        self.assertTrue(is_circ, "方案验证成功：自适应环化成功识别闭环！")
        self.assertEqual(len(trimmed_seq), 2100, "方案验证成功：精准修剪掉 600 bp 冗余 DTR，还原 2100 bp 真实染色体！")


if __name__ == "__main__":
    unittest.main()
