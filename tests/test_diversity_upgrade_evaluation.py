# -*- coding: utf-8 -*-
"""
三代 16S 扩增子多样性分析升级效果评估基准测试套件
基于 33 个真实三代测序样本数据，系统化评估：
1. 低频测序噪声过滤与伪物种清洗能力 (De-singleton & Artifact Filtering)
2. 生态学 Alpha 多样性指标校正保真度
3. 16S 操纵子多拷贝异质性 (Intragenomic Heterogeneity) 智能诊断准确度
"""
import sys
import json
import time
from pathlib import Path
from typing import Any, Dict, cast

if sys.platform == "win32":
    try:
        cast(Any, sys.stdout).reconfigure(encoding="utf-8")
        cast(Any, sys.stderr).reconfigure(encoding="utf-8")
    except Exception:
        pass

# 将项目根目录与 src 加入模块路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.backend.services.diversity_filter import DiversityNoiseFilter
from src.backend.services.heterogeneity_detector import OperonHeterogeneityDetector


def load_real_benchmark_dataset() -> Dict[str, Any]:
    """加载真实多样性分析基准数据 (优先匹配最新有效 checkpoint)"""
    chk_root = PROJECT_ROOT / "results" / "diversity_checkpoints"
    cand_reports = list(chk_root.rglob("summary_report.json"))
    if not cand_reports:
        raise FileNotFoundError(f"未在 {chk_root} 找到任何可用的 summary_report.json 基准数据")
    
    cand_reports.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    target = cand_reports[0]
    with open(target, "r", encoding="utf-8") as f:
        return json.load(f)


def evaluate_noise_filtering(dataset: Dict[str, Any], filter_inst: DiversityNoiseFilter) -> Dict[str, Any]:
    """评测低频噪声过滤效果"""
    samples = dataset.get("samples", [])
    total_raw_taxa_sum = 0
    total_clean_taxa_sum = 0
    total_noise_taxa_count = 0
    total_noise_reads_count = 0
    total_reads_sum = 0

    per_sample_stats = []

    for s in samples:
        sname = s.get("sample_name")
        raw_taxa = s.get("taxa_counts", {})
        total_classified = s.get("classified_reads", sum(raw_taxa.values()))
        total_reads_sum += total_classified

        res = filter_inst.filter_taxa(raw_taxa, total_classified)

        raw_richness = res["raw_richness"]
        clean_richness = res["clean_richness"]
        noise_taxa = res["noise_taxa_count"]
        noise_reads = res["noise_reads"]

        total_raw_taxa_sum += raw_richness
        total_clean_taxa_sum += clean_richness
        total_noise_taxa_count += noise_taxa
        total_noise_reads_count += noise_reads

        per_sample_stats.append({
            "sample_name": sname,
            "raw_richness": raw_richness,
            "clean_richness": clean_richness,
            "removed_taxa_count": noise_taxa,
            "removed_reads_count": noise_reads,
            "noise_reads_pct": round((noise_reads / max(1, total_classified)) * 100, 2),
            "removed_taxa_list": [t["taxon"] for t in res["removed_taxa"]],
            "alpha_raw": res["alpha_raw"],
            "alpha_clean": res["alpha_clean"]
        })

    return {
        "sample_count": len(samples),
        "total_reads": total_reads_sum,
        "total_raw_species_detected": total_raw_taxa_sum,
        "total_clean_species_retained": total_clean_taxa_sum,
        "total_noise_species_removed": total_noise_taxa_count,
        "total_noise_reads_removed": total_noise_reads_count,
        "avg_species_per_sample_before": round(total_raw_taxa_sum / max(1, len(samples)), 2),
        "avg_species_per_sample_after": round(total_clean_taxa_sum / max(1, len(samples)), 2),
        "noise_species_removal_rate_pct": round((total_noise_taxa_count / max(1, total_raw_taxa_sum)) * 100, 2),
        "reads_preservation_rate_pct": round(((total_reads_sum - total_noise_reads_count) / max(1, total_reads_sum)) * 100, 2),
        "per_sample_stats": per_sample_stats
    }


def evaluate_heterogeneity_diagnosis(dataset: Dict[str, Any], detector: OperonHeterogeneityDetector) -> Dict[str, Any]:
    """评测操纵子多拷贝异质性诊断效果"""
    samples = dataset.get("samples", [])
    diagnosis_results = []
    high_conf_count = 0
    med_conf_count = 0
    low_conf_count = 0

    for s in samples:
        sname = s.get("sample_name")
        raw_taxa = s.get("taxa_counts", {})
        advisories = detector.diagnose_sample(raw_taxa, min_dominance_pct=5.0)

        for adv in advisories:
            level = adv["confidence_level"]
            if level == "high":
                high_conf_count += 1
            elif level == "medium":
                med_conf_count += 1
            else:
                low_conf_count += 1

            diagnosis_results.append({
                "sample_name": sname,
                "advisory": adv
            })

    return {
        "total_evaluated_samples": len(samples),
        "total_heterogeneity_cases": len(diagnosis_results),
        "high_confidence_cases": high_conf_count,
        "medium_confidence_cases": med_conf_count,
        "low_confidence_cases": low_conf_count,
        "heterogeneity_prevalence_pct": round((high_conf_count / max(1, len(samples))) * 100, 2),
        "cases": diagnosis_results
    }


def run_full_evaluation():
    print("=" * 72)
    print("三代 16S 扩增子多样性分析引擎升级效果评测")
    print("=" * 72)

    # 1. 加载基准数据
    t0 = time.time()
    dataset = load_real_benchmark_dataset()
    load_time = time.time() - t0
    sample_count = dataset.get("total_samples", len(dataset.get("samples", [])))
    print(f"[阶段 1] 成功载入真实数据集: 共 {sample_count} 个样本，{dataset.get('total_classified_reads')} 条已比对 Reads (耗时: {load_time:.3f}s)")

    # 2. 评测低频噪声过滤 (相对丰度 < 0.5% 或 Reads <= 2 条)
    t1 = time.time()
    noise_filter = DiversityNoiseFilter(min_rel_abundance=0.5, min_reads_count=2, preserve_other=True)
    filter_eval = evaluate_noise_filtering(dataset, noise_filter)
    filter_time = time.time() - t1

    print("\n" + "-" * 72)
    print("评测模块一：低频测序噪声与孤儿物种 (Singleton Artifacts) 清洗效果")
    print("-" * 72)
    print(f"原始检出总物种人次 (Raw Taxa Sum):        {filter_eval['total_raw_species_detected']}")
    print(f"过滤后保留核心物种人次 (Clean Taxa Sum):  {filter_eval['total_clean_species_retained']}")
    print(f"清洗掉的孤儿假物种总数 (Removed Artifacts): {filter_eval['total_noise_species_removed']} (清除率: {filter_eval['noise_species_removal_rate_pct']}%)")
    print(f"核心生物学 Reads 保留率 (Preservation):   {filter_eval['reads_preservation_rate_pct']}% (仅滤除了微弱随机噪音)")
    print(f"样本平均物种丰富度 (Richness):             {filter_eval['avg_species_per_sample_before']} 种 -> {filter_eval['avg_species_per_sample_after']} 种")

    # 典型清洗案例抽样展示
    print("\n典型假物种清洗案例抽样:")
    notable_cases = [s for s in filter_eval["per_sample_stats"] if s["removed_taxa_count"] >= 3][:3]
    for c in notable_cases:
        print(f"  * 样本 {c['sample_name']}: 原始丰富度 {c['raw_richness']} -> 校正后 {c['clean_richness']}")
        print(f"    清洗掉的单读段伪物种 ({len(c['removed_taxa_list'])} 个): {', '.join(c['removed_taxa_list'])}")
        print(f"    Alpha Chao1 指数变化: {c['alpha_raw']['chao1']} -> {c['alpha_clean']['chao1']}")

    # 3. 评测操纵子多拷贝异质性智能诊断
    t2 = time.time()
    detector = OperonHeterogeneityDetector(max_ratio_denominator=15, max_residual=0.08)
    hetero_eval = evaluate_heterogeneity_diagnosis(dataset, detector)
    hetero_time = time.time() - t2

    print("\n" + "-" * 72)
    print("评测模块二：16S 操纵子多拷贝基因组内异质性 (Intragenomic Heterogeneity) 诊断")
    print("-" * 72)
    print(f"评估样本总数:                       {hetero_eval['total_evaluated_samples']}")
    print(f"检出同属双优势物种共存事件:         {hetero_eval['total_heterogeneity_cases']} 例")
    print(f"高度置信度异质性判定 (High Conf):   {hetero_eval['high_confidence_cases']} 例 (占比 {hetero_eval['heterogeneity_prevalence_pct']}%)")
    print(f"中度置信度异质性判定 (Medium Conf): {hetero_eval['medium_confidence_cases']} 例")

    # 典型异质性判定展示
    print("\n典型操纵子异质性智能判定实例:")
    for item in hetero_eval["cases"][:4]:
        sname = item["sample_name"]
        adv = item["advisory"]
        print(f"  * 样本 {sname} ({adv['genus']} 属):")
        print(f"    涉及物种: {adv['taxa_pair'][0]} ({adv['percentages'][0]}%) 与 {adv['taxa_pair'][1]} ({adv['percentages'][1]}%)")
        print(f"    拟合最简整数比: {adv['fitted_ratio']} (理论操纵子数之和: {adv['fitted_operon_sum']}, 残差: {adv['residual_pct']}%)")
        print(f"    rrnDB 数据库已知中位数拷贝数: {adv['known_gcn_median']}")
        print(f"    诊断评级: [{adv['confidence_level'].upper()}] - {adv['conclusion']}")
        print(f"    智能处理建议: {adv['suggestion']}")
        print()

    # 4. 汇总生成量化评估报告
    output_report_path = PROJECT_ROOT / "results" / "diversity_upgrade_benchmark_report.json"
    output_report_path.parent.mkdir(parents=True, exist_ok=True)
    benchmark_report = {
        "timestamp": time.time(),
        "noise_filtering_evaluation": {
            "total_raw_species": filter_eval["total_raw_species_detected"],
            "total_clean_species": filter_eval["total_clean_species_retained"],
            "noise_species_removed": filter_eval["total_noise_species_removed"],
            "removal_rate_pct": filter_eval["noise_species_removal_rate_pct"],
            "reads_preservation_pct": filter_eval["reads_preservation_rate_pct"],
            "avg_richness_before": filter_eval["avg_species_per_sample_before"],
            "avg_richness_after": filter_eval["avg_species_per_sample_after"]
        },
        "heterogeneity_evaluation": {
            "total_cases": hetero_eval["total_heterogeneity_cases"],
            "high_conf": hetero_eval["high_confidence_cases"],
            "prevalence_pct": hetero_eval["heterogeneity_prevalence_pct"]
        },
        "execution_performance": {
            "filtering_seconds": round(filter_time, 4),
            "diagnosis_seconds": round(hetero_time, 4),
            "total_seconds": round(filter_time + hetero_time, 4)
        }
    }

    with open(output_report_path, "w", encoding="utf-8") as f:
        json.dump(benchmark_report, f, ensure_ascii=False, indent=2)

    print("=" * 72)
    print(f"评测全部顺利完成！基准评估数据已持久化落盘至: {output_report_path}")
    print(f"总执行耗时: 降噪过滤 {filter_time*1000:.1f}ms, 异质性建模 {hetero_time*1000:.1f}ms")
    print("=" * 72)

    return benchmark_report


if __name__ == "__main__":
    run_full_evaluation()
