# -*- coding: utf-8 -*-
"""
噬菌体结构与尾部形态预测集中阈值配置模块 (Thresholds)

职责：
1. 将分布于序列扫描、密码表选择、完整度门控、拆分 TMP 合并、TMP 选尺及形态打分中的
   全部核心阈值收拢至不可变数据类，并附生物学依据注释；
2. 提供纯函数式局部覆盖接口 `override_threshold`，供 T2.1 参数敏感性扫描及消融实验使用，
   杜绝修改全局默认配置实例或引入状态污染。
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Dict


@dataclass(frozen=True)
class HmmScanThresholds:
    """WSL PyHMMER 同源扫描与混淆过滤阈值。"""

    # 锁定有效搜索库规模 Z=200，保证单株与批量混合提交时 E-value 完全不变
    pyhmmer_z: int = 200
    default_evalue_cutoff: float = 1e-4
    # 最低比特分 28.0，滤除随机短 motif 弱碰撞
    default_score_cutoff: float = 28.0
    # 外部标注与 HMM 实质冲突时，低于 50.0 的中等得分不强行推翻已有高可信结构注释
    role_conflict_override_score: float = 50.0
    # 长肽段 (>=60 aa) 四聚体 k-mer 多样性低于 20% 视作胶原/纤维类低复杂度伪重复
    low_complexity_kmer_ratio: float = 0.20
    low_complexity_min_score: float = 250.0


@dataclass(frozen=True)
class GeneticCodeThresholds:
    """遗传密码 11 / 4 / 15 自动判别阈值。"""

    # 过短片段 (<1500 bp) 缺少足够统计自由度以安全切换密码表
    min_seq_bp: int = 1500
    # Pyrodigal 单基因组训练达到稳定收敛且不告警的最小窗口尺度
    train_window_bp: int = 100_000
    # 计入覆盖率与平均长度统计的有效最小 ORF 长度 (75 bp = 25 aa)
    min_orf_bp: int = 75
    # Table 11 编码覆盖度低于 0.78 提示可能存在密码子提前截断
    low_cov_11_ceiling: float = 0.78
    # 在 Table 11 低覆盖前提下，替代密码表至少恢复 8% 编码覆盖率
    min_cov_gain_with_low_11: float = 0.08
    # 若 Table 11 未明显低于 0.78，则需要更高 (>=14%) 覆盖度增益以防标准基因组漂移
    min_cov_gain_standalone: float = 0.14
    # 替代密码表必须至少将平均 ORF 长度拉升至 1.45 倍且减少碎裂数
    min_mean_aa_ratio: float = 1.45


@dataclass(frozen=True)
class CompletenessThresholds:
    """末端重复检测、稀疏 GenBank 诊断与完整度门控阈值。"""

    min_repeat_seq_bp: int = 2500
    dtr_seed_bp: int = 20
    dtr_edge_limit_bp: int = 15_000
    dtr_min_identity: float = 0.95
    itr_window_bp: int = 200
    itr_seed_bp: int = 18
    sparse_gbk_min_bp: int = 8000
    # 原注释覆盖不足 48%，或覆盖不足 68% 且存在 >=14 kb 空白大洞时判定为稀疏遗漏
    sparse_gbk_low_cov: float = 0.48
    sparse_gbk_mid_cov: float = 0.68
    sparse_gbk_max_gap_bp: int = 14_000
    # 完整大亚基末端酶通常 >=300 aa，作为头部包装核心稳健锚点
    terl_full_min_aa: int = 300
    valid_long_tmp_min_aa: int = 350
    # 无末端重复时，至少 >=25 kb 完整包装尺度才允许“有头无长尾 -> 短尾”负向推断
    podo_negative_min_bp: int = 25_000
    podo_t7_pfam_min_prob: float = 0.70


@dataclass(frozen=True)
class SplitTmpThresholds:
    """移码拆分 / 分裂卷尺蛋白合并阈值。"""

    frag_min_aa: int = 180
    frag_max_aa: int = 1600
    verified_hmm_min_score: float = 60.0
    # 允许程序性移码重叠 (-250 bp) 至窄基因间区 (+120 bp)
    min_gap_bp: int = -250
    max_gap_bp: int = 120
    same_pfam_high_hmm_score: float = 100.0
    # 合并重构后总跨度须落入真实尾尺生物物理区间 (600 ~ 3500 aa)
    merged_min_aa: int = 600
    merged_max_aa: int = 3500


@dataclass(frozen=True)
class TmpSelectionThresholds:
    """TMP 优选、操纵子共线性窗口与 α-螺旋标尺换算参数。"""

    # 标准 α-螺旋轴向延伸常数 (0.145 nm/aa, 区间 0.140 ~ 0.150 nm/aa)
    helix_nm_per_aa: float = 0.145
    helix_min_nm_per_aa: float = 0.140
    helix_max_nm_per_aa: float = 0.150
    operon_window: int = 4
    wide_operon_window: int = 8
    circular_edge_max_gap_bp: int = 3500
    ptf_backbone_prob: float = 0.72
    ptf_backbone_min_aa: int = 150
    ptf_neighbor_min_aa: int = 120
    direct_pfam_primary_min_aa: int = 380
    direct_pfam_min_aa: int = 400
    high_conf_verified_hmm_score: float = 80.0
    self_auth_hmm_score: float = 60.0
    self_auth_min_aa: int = 650
    lytic_tmp_min_aa: int = 650
    hmm_tmp_in_operon_min_score: float = 20.0
    hmm_tmp_outside_operon_min_score: float = 30.0
    hmm_tmp_tap_min_aa: int = 300
    hmm_tmp_default_min_aa: int = 380
    hmm_tmp_short_operon_score: float = 45.0
    gp29_min_aa: int = 350
    syntenic_yqaj_min_aa: int = 500
    syntenic_default_min_aa: int = 480
    syntenic_min_score: float = 3.0


@dataclass(frozen=True)
class MorphotypeClassifierThresholds:
    """噬菌体四形态融合打分权重与 Phold 3D 触发门限。"""

    compact_tailless_max_bp: int = 25_000
    compact_tailless_max_orfs: int = 42
    short_p9_atpase_max_aa: int = 280
    tsp_base_weight: float = 6.5
    mtp_base_weight: float = 3.6
    tap_base_weight: float = 2.0
    tmp_base_weight: float = 2.8
    podo_negative_strong_weight: float = 2.6
    podo_negative_weak_weight: float = 1.8
    incomplete_score_cutoff: float = 2.2
    low_margin_warning_cutoff: float = 1.5
    real_long_tmp_min_aa: int = 500
    real_long_tmp_non_n4_min_aa: int = 350
    # 触发 Phold 3D 复核的 Incomplete Contig 最小长度门槛 (15 kb) 与未知蛋白最小长度 (200 aa)
    phold_incomplete_min_bp: int = 15_000
    phold_rescue_min_aa: int = 200


@dataclass(frozen=True)
class PhageStructureThresholds:
    """噬菌体结构与尾部形态预测全局参数总成。"""

    hmm: HmmScanThresholds = HmmScanThresholds()
    genetic_code: GeneticCodeThresholds = GeneticCodeThresholds()
    completeness: CompletenessThresholds = CompletenessThresholds()
    split_tmp: SplitTmpThresholds = SplitTmpThresholds()
    tmp: TmpSelectionThresholds = TmpSelectionThresholds()
    classifier: MorphotypeClassifierThresholds = MorphotypeClassifierThresholds()


DEFAULT_THRESHOLDS = PhageStructureThresholds()


def override_threshold(
    base: PhageStructureThresholds,
    dotted_key: str,
    value: Any,
) -> PhageStructureThresholds:
    """
    纯函数式局部覆盖指定路径（如 'tmp.direct_pfam_min_aa'）并返回全新阈值实例，
    原实例保持完全不可变，供敏感性分析与消融测试安全使用。
    """
    parts = [p.strip() for p in dotted_key.split(".") if p.strip()]
    if len(parts) != 2:
        raise ValueError(f"无效阈值键名（需为 group.field 格式）: {dotted_key}")
    group_name, field_name = parts
    if not hasattr(base, group_name):
        raise KeyError(f"未找到阈值分组: {group_name}")
    group_obj = getattr(base, group_name)
    if not hasattr(group_obj, field_name):
        raise KeyError(f"阈值分组 {group_name} 不存在字段: {field_name}")

    orig_val = getattr(group_obj, field_name)
    if isinstance(orig_val, bool):
        casted: Any = bool(value)
    elif isinstance(orig_val, int):
        casted = int(round(float(value)))
    elif isinstance(orig_val, float):
        casted = float(value)
    else:
        casted = value

    new_group = replace(group_obj, **{field_name: casted})
    return replace(base, **{group_name: new_group})


def list_threshold_keys(base: PhageStructureThresholds = DEFAULT_THRESHOLDS) -> Dict[str, Any]:
    """平铺导出全部 `group.field -> value` 映射供审计与报告记录。"""
    out: Dict[str, Any] = {}
    for g_name in ("hmm", "genetic_code", "completeness", "split_tmp", "tmp", "classifier"):
        g_obj = getattr(base, g_name)
        for k, v in g_obj.__dict__.items():
            out[f"{g_name}.{k}"] = v
    return out
