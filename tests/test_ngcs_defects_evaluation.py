# -*- coding: utf-8 -*-
"""
NGCS 组装引擎长读长缺陷基准评估测试套件 (Defects Baseline Evaluation Suite)

本测试套件严格重现与量化 NGCS 组装引擎当前生产代码中的三大核心缺陷：
1. 幽灵片段过滤缺陷：当前后处理缺乏读长覆盖度接口，无法根据真实测序深度过滤 1x~3x 假装配片段；
2. 三代长读长 Dovetail 零容错缺陷：当前无法在 2%~4% 测序噪声下完成重叠片段融合；
3. 环化闭合缺陷：当前在轻微测序噪声下无法识别首尾重叠（DTR），导致 is_circular 丢失。
"""

import unittest
import sys
import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.assembly.utils.path_resolver import resolve_ngcs_root

_NGCS_ROOT = str(resolve_ngcs_root())
if _NGCS_ROOT not in sys.path:
    sys.path.append(_NGCS_ROOT)

from ngcs.consensus.post_processor import AssemblyPostProcessor
from ngcs.spectral.circular_trimmer import trim_circular_wrap


def generate_pseudo_random_dna(length: int, seed: int = 42) -> str:
    """生成具有高复杂度、信息熵接近 2.0 的伪随机真实 DNA 序列"""
    bases = ['A', 'C', 'G', 'T']
    res = []
    state = seed
    for _ in range(length):
        state = (state * 1103515245 + 12345) & 0x7fffffff
        res.append(bases[(state >> 16) % 4])
    return "".join(res)


class TestNGCSCurrentDefectsEvaluation(unittest.TestCase):
    """当前 NGCS 引擎缺陷基线评估测试"""

    def setUp(self):
        self.processor = AssemblyPostProcessor(verbose=False)

    def test_defect_1_spurious_low_coverage_ghost_contigs(self):
        """
        [缺陷评估 1] 幽灵片段未能过滤基线测试
        构造 1 条真实高深度染色体 (600x) 与 2 条只有 1x~2x 深度的假装配幽灵片段（真实高复杂度序列）。
        当前 AssemblyPostProcessor 的 stitch_chromosomes 根本不支持接收覆盖度字典，
        无法根据真实测序深度剔除假片段。
        """
        true_chromosome = generate_pseudo_random_dna(5000, seed=101)
        ghost_contig_1 = generate_pseudo_random_dna(2000, seed=202) # 假片段 1 (深度 1.0x)
        ghost_contig_2 = generate_pseudo_random_dna(2000, seed=303) # 假片段 2 (深度 1.5x)

        raw_contigs = [
            ("contig_real", true_chromosome, False),
            ("contig_ghost_1", ghost_contig_1, False),
            ("contig_ghost_2", ghost_contig_2, False),
        ]

        # 当前生产代码没有 coverage 过滤参数
        curated = self.processor.stitch_chromosomes(raw_contigs)

        print("\n--- [Defect 1 Baseline Evaluation] ---")
        print(f"输入片段数: {len(raw_contigs)}, 当前后处理产出片段数: {len(curated)}")
        for c in curated:
            print(f"  产出片段: {c[0]} (Length={len(c[1])} bp, Circular={c[2]})")

        # 基线断言：当前后处理完全没有覆盖度过滤能力，3 个片段全部保留
        self.assertEqual(len(curated), 3, "基线确认：当前生产代码无法过滤高复杂度但低深度的 1x 幽灵片段")

    def test_defect_2_dovetail_zero_tolerance_failure(self):
        """
        [缺陷评估 2] 三代长读长 Dovetail 零容错断裂基线测试
        构造两条两端存在 480 bp 重叠的片段，重叠区引入 3% 单分子测序残余噪声。
        """
        prefix = generate_pseudo_random_dna(800, seed=401)
        overlap_true = generate_pseudo_random_dna(480, seed=402)
        suffix = generate_pseudo_random_dna(800, seed=403)

        seqA = prefix + overlap_true
        
        # 在 seqB 的重叠区人为引入 3% 变异（模拟单分子测序噪声）
        overlap_noisy_list = list(overlap_true)
        for i in range(10, len(overlap_noisy_list), 33):
            overlap_noisy_list[i] = 'A' if overlap_noisy_list[i] != 'A' else 'T'
        overlap_noisy = "".join(overlap_noisy_list)

        seqB = overlap_noisy + suffix

        # 运行当前生产代码的 find_dovetail_overlap (未传 max_error_rate)
        ovlp_len, fused = self.processor.find_dovetail_overlap(seqA, seqB, min_ovlp=50)

        print("\n--- [Defect 2 Baseline Evaluation] ---")
        print(f"真实物理重叠长度: 480 bp (含 3% 噪声)")
        print(f"当前生产代码 find_dovetail_overlap 识别结果: overlap={ovlp_len}, fused_len={len(fused)}")

        # 基线断言：当前默认 0 容错，导致 Dovetail 识别失败
        self.assertEqual(ovlp_len, 0, "基线确认：当前生产代码因 0 容错缺陷，无法融合 3% 噪声的长读长重叠")
        self.assertEqual(fused, "", "基线确认：当前生产代码无法产出融合序列")

    def test_defect_3_circular_closure_missing_on_noisy_overlap(self):
        """
        [缺陷评估 3] 首尾重叠但带有残余测序噪声时，环化判定丢失基线测试
        构造一条自然环状噬菌体基因组，首尾端到端重叠 600 bp（含 2.5% 残余测序噪声）。
        """
        core = generate_pseudo_random_dna(1500, seed=501)
        dtr_true = generate_pseudo_random_dna(600, seed=502)

        # 首尾带有 DTR 重叠，且末端含有 2.5% 残余噪声
        dtr_noisy = list(dtr_true)
        for i in range(15, len(dtr_noisy), 40):
            dtr_noisy[i] = 'G' if dtr_noisy[i] != 'G' else 'C'
        dtr_noisy_str = "".join(dtr_noisy)

        # 模拟组装出的线性重叠片段: DTR + Core + DTR(轻微噪声)
        concatenated_seq = dtr_true + core + dtr_noisy_str

        trimmed_seq, is_circ, period = trim_circular_wrap(concatenated_seq, min_period=300, min_overhang=50)

        print("\n--- [Defect 3 Baseline Evaluation] ---")
        print(f"原始环状序列包含首尾 DTR (600 bp 重叠)")
        print(f"当前 trim_circular_wrap 识别结果: is_circular={is_circ}, trimmed_len={len(trimmed_seq)}, period={period}")

        # 基线断言：当前代码丢失环化
        self.assertFalse(is_circ, "基线确认：当前生产代码在轻微测序噪声下丢失环化闭合识别")


if __name__ == "__main__":
    unittest.main()
