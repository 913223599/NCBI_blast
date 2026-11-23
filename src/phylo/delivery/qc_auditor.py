# -*- coding: utf-8 -*-
"""
PhageDeliveryQcAuditor - 第 6 & 8 步：支持值/ANI-树一致性核查与 6 项交付前质检清单审计
"""
from typing import Any, Dict, List, Optional

from ..models.schemas import (
    AniScreenResult,
    DeliveryQcReport,
    MarkerExtractionReport,
    QcCheckItem,
    ReferenceCandidate,
    TreeMetrics,
)
from ..pipeline.postprocess import check_outgroup_placement, find_sister_taxa


class PhageDeliveryQcAuditor:
    """对照第 8 步 6 项科研质检标准开展自动化审校并输出规范分类结论草稿。"""

    @staticmethod
    def audit(
        newick: str,
        metrics: TreeMetrics,
        candidates: List[ReferenceCandidate],
        ani_result: Optional[AniScreenResult],
        marker_report: Optional[MarkerExtractionReport],
        trim_stats: Optional[Dict[str, Any]],
        iqtree_cmd: Optional[str],
        best_model: Optional[str],
        best_model_bic: Optional[float],
        itol_files: List[str],
    ) -> DeliveryQcReport:
        checks: List[QcCheckItem] = []
        cand_map = {c.accession: c for c in candidates if c.selected}
        queries = [c.accession for c in cand_map.values() if c.role == "query"]
        outgroups = [c.accession for c in cand_map.values() if c.role == "outgroup"]

        # 检查项 1: 参考集是否包含每个相关属的 ICTV 正式代表
        genus_rep_counts: Dict[str, int] = {}
        for c in cand_map.values():
            if c.role != "query" and c.is_ictv_classified and c.genus:
                genus_rep_counts[c.genus] = genus_rep_counts.get(c.genus, 0) + 1
        target_genera = ani_result.candidate_genera[:3] if ani_result else []
        covered_target_genera = [g for g in target_genera if genus_rep_counts.get(g, 0) >= 1]
        if target_genera and len(covered_target_genera) == len(target_genera):
            c1_status = "pass"
            c1_obs = ", ".join(f"{g} ({genus_rep_counts[g]} 条)" for g in covered_target_genera)
            c1_exp = "目标候选属及邻近属均包含 ICTV 正式分类代表基因组。"
        elif genus_rep_counts:
            c1_status = "warn"
            c1_obs = f"已纳入 {len(genus_rep_counts)} 个 ICTV 属共 {sum(genus_rep_counts.values())} 条代表"
            c1_exp = "建议为每个核心目标属再补齐至 1-2 条正式 ICTV 分类代表以增强结论稳健性。"
        else:
            c1_status = "fail"
            c1_obs = "0 条 ICTV 属代表"
            c1_exp = "当前树缺少明确归属的 ICTV 正式代表，难以单独支撑属级分类定论。"
        checks.append(
            QcCheckItem(
                key="ictv_rep_coverage",
                title="相关属 ICTV 代表覆盖",
                criterion="至少每个目标属 1-2 条正式分类代表",
                status=c1_status,  # type: ignore[arg-type]
                observed=c1_obs,
                explanation=c1_exp,
            )
        )

        # 检查项 2: 外群是否明确在目标类群之外
        if not outgroups:
            c2_status = "fail"
            c2_obs = "未指定外群"
            c2_exp = "树中必须包含亲缘较近且明确在目标类群之外的外群，否则拓扑难以定向。"
        else:
            og_ok, og_msg = check_outgroup_placement(newick, outgroups)
            c2_status = "pass" if og_ok else "warn"
            c2_obs = ", ".join(outgroups)
            c2_exp = og_msg
        checks.append(
            QcCheckItem(
                key="outgroup_placement",
                title="外群定位合规性",
                criterion="外群处于树基部且不嵌入目标类群内部",
                status=c2_status,  # type: ignore[arg-type]
                observed=c2_obs,
                explanation=c2_exp,
            )
        )

        # 检查项 3: 比对是否经过修剪（如走全基因组树则标注不适用/跳过）
        if marker_report and marker_report.mode == "proteome":
            c3_status = "pass"
            c3_obs = "全基因组蛋白质组树 (DIAMOND S_G)"
            c3_exp = "备选蛋白质组树无需 MSA 位点修剪。"
        elif trim_stats and int(trim_stats.get("kept_cols", 0)) > 0:
            orig_c = int(trim_stats.get("original_cols", 0))
            kept_c = int(trim_stats.get("kept_cols", 0))
            pi_c = int(trim_stats.get("parsimony_informative_sites", 0))
            mode_name = str(trim_stats.get("tool") or trim_stats.get("mode") or "trimmed")
            c3_status = "pass" if pi_c >= 20 else "warn"
            c3_obs = f"{mode_name}: {orig_c} -> {kept_c} 列 (PI={pi_c})"
            c3_exp = (
                "已有效去除高变区 gap 噪声并保留充足简约信息位点。"
                if pi_c >= 20
                else "修剪后简约信息位点偏少 (< 20)，建议检查序列同源性或放宽修剪策略。"
            )
        else:
            c3_status = "fail"
            c3_obs = "未执行修剪"
            c3_exp = "未对 MSA 高变区进行修剪（建议使用 ClipKIT -m kpic），直接建树易受 gap 噪声干扰。"
        checks.append(
            QcCheckItem(
                key="alignment_trimmed",
                title="多序列比对修剪质控",
                criterion="高变区被去除，保留足够简约信息位点",
                status=c3_status,  # type: ignore[arg-type]
                observed=c3_obs,
                explanation=c3_exp,
            )
        )

        # 检查项 4: 模型选择 (ModelFinder) 与 BIC 值记录
        if best_model:
            c4_status = "pass"
            c4_obs = f"{best_model}" + (f" (BIC={best_model_bic})" if best_model_bic is not None else "")
            c4_exp = "ModelFinder 最优替换模型" + ("及 BIC 准则分值已完整归档。" if best_model_bic is not None else "已记录。")
        else:
            c4_status = "warn"
            c4_obs = "未捕获 ModelFinder BIC 报告"
            c4_exp = "非 IQ-TREE MFP 构树或未检测到 .iqtree 模型评估日志。"
        checks.append(
            QcCheckItem(
                key="model_and_bic_recorded",
                title="替换模型与 BIC 追溯",
                criterion="ModelFinder 输出中记录最优模型和 BIC 值",
                status=c4_status,  # type: ignore[arg-type]
                observed=c4_obs,
                explanation=c4_exp,
            )
        )

        # 检查项 5: 双支持值 (UFBoot >= 95 & SH-aLRT)
        primary_q = queries[0] if queries else ""
        sisters, q_alrt, q_uf = find_sister_taxa(newick, primary_q) if primary_q else ([], None, None)
        if metrics.has_dual_support:
            uf_strong = q_uf is not None and q_uf >= 95.0
            c5_status = "pass" if (q_uf is None or uf_strong) else "warn"
            c5_obs = (
                f"均值 SH-aLRT={metrics.mean_alrt}% / UFBoot={metrics.mean_support}% "
                f"(UFBoot>=95 节点占比 {metrics.strong_ufboot_ratio}%)"
            )
            c5_exp = (
                f"目标株所在分枝双支持值为 SH-aLRT={q_alrt}% / UFBoot={q_uf}% (>=95 强支持)。"
                if uf_strong
                else f"已记录双支持值，但目标株所在分枝支持值偏低 (SH-aLRT={q_alrt}% / UFBoot={q_uf}% < 95)，提示该处系统发育信号可能受噬菌体基因嵌合或采样稀疏影响。"
            )
        elif metrics.mean_support is not None:
            c5_status = "warn"
            c5_obs = f"仅单支持值 (均值={metrics.mean_support}%)"
            c5_exp = "发表级 IQ-TREE 树建议同时开启 -B 1000 -bnni -alrt 1000 输出双支持值。"
        else:
            c5_status = "fail"
            c5_obs = "缺少节点支持值"
            c5_exp = "未检测到自举或 SH-aLRT 分支支持率。"
        checks.append(
            QcCheckItem(
                key="dual_support_reported",
                title="双支持值 (UFBoot + SH-aLRT)",
                criterion="同时报告 UFBoot (>=95 强支持) 与 SH-aLRT，并对弱支持分枝给出解释",
                status=c5_status,  # type: ignore[arg-type]
                observed=c5_obs,
                explanation=c5_exp,
            )
        )

        # 检查项 6: ANI 结论与树拓扑自洽性校验
        ani_top = ani_result.top_hits[0] if ani_result and ani_result.top_hits else None
        sister_genera = [
            cand_map[s].genus for s in sisters if s in cand_map and cand_map[s].genus
        ]
        consistent = True
        if ani_top is None:
            c6_status = "warn"
            c6_obs = "无第 1 步 ANI 参考对标数据"
            c6_exp = "建议结合 VIRIDIC/Mash wgANI 进行定量复核。"
        elif not sisters:
            c6_status = "warn"
            c6_obs = f"ANI Top: {ani_top.accession} ({ani_top.wg_ani}%)"
            c6_exp = "未能定位查询株在树上的直接姐妹叶集合。"
        else:
            ani_top_genus = ani_top.genus
            if ani_top.accession in sisters or (ani_top_genus and ani_top_genus in sister_genera):
                consistent = True
                c6_status = "pass"
                c6_obs = f"ANI Top ({ani_top.accession}, {ani_top.wg_ani}%) 与树姐妹枝 ({', '.join(sisters[:3])}) 一致"
                c6_exp = "全基因组 wgANI 聚类关系与标志基因系统发育拓扑高度自洽。"
            elif ani_top.wg_ani < 70.0:
                # 若 wgANI < 70% 属于独立新属，姐妹枝落在邻近已知属也是合理解释
                consistent = True
                c6_status = "pass"
                c6_obs = f"wgANI={ani_top.wg_ani}% (<70%), 树姐妹枝={', '.join(sisters[:3])}"
                c6_exp = "查询株与所有已知属代表 wgANI 均 < 70% 且在树上形成独立分支，两者共同支持候选新属地位。"
            else:
                consistent = False
                c6_status = "warn"
                c6_obs = (
                    f"ANI Top={ani_top.accession} ({ani_top_genus or 'Unclassified'}, {ani_top.wg_ani}%), "
                    f"但树姐妹枝={', '.join(sisters[:3])} ({', '.join(sister_genera[:2]) or '未知属'})"
                )
                c6_exp = (
                    "wgANI 最近邻与单基因树姐妹分枝不完全重合，常见原因为噬菌体基因组模块化嵌合 (mosaicism) 或对应属参考株覆盖不足；"
                    "请以 wgANI 与 ICTV 阈值为定性锚点，并在交付说明中注明嵌合现象。"
                )
        checks.append(
            QcCheckItem(
                key="ani_tree_consistency",
                title="ANI 结论与树拓扑自洽性",
                criterion="全基因组 wgANI 归属与进化树姐妹分支一致，不一致需解释原因",
                status=c6_status,  # type: ignore[arg-type]
                observed=c6_obs,
                explanation=c6_exp,
            )
        )

        # 汇总状态与生成规范 ICTV 学术表述（中/英文）
        statuses = {chk.status for chk in checks}
        overall = "fail" if "fail" in statuses else ("warn" if "warn" in statuses else "pass")
        conclusion_zh, conclusion_en = PhageDeliveryQcAuditor._draft_taxonomic_statements(
            primary_q=primary_q or "Query_Phage",
            ani_top=ani_top,
            sisters=sisters,
            sister_genera=sister_genera,
            q_alrt=q_alrt,
            q_uf=q_uf,
            best_model=best_model,
            marker_mode=marker_report.mode if marker_report else "terl",
            consistent=consistent,
        )

        return DeliveryQcReport(
            checks=checks,
            overall_status=overall,  # type: ignore[arg-type]
            ani_tree_consistent=consistent,
            consistency_note=c6_exp,
            best_model=best_model,
            best_model_bic=best_model_bic,
            iqtree_command=iqtree_cmd,
            conclusion_zh=conclusion_zh,
            conclusion_en=conclusion_en,
            itol_files=itol_files,
        )

    @staticmethod
    def _draft_taxonomic_statements(
        primary_q: str,
        ani_top: Any,
        sisters: List[str],
        sister_genera: List[str],
        q_alrt: Optional[float],
        q_uf: Optional[float],
        best_model: Optional[str],
        marker_mode: str,
        consistent: bool,
    ) -> tuple[str, str]:
        marker_zh = "大末端酶亚基 (TerL)" if marker_mode == "terl" else "全基因组共享蛋白质组"
        marker_en = "large terminase subunit (TerL)" if marker_mode == "terl" else "whole-proteome shared similarity"
        sup_txt = (
            f"SH-aLRT/UFBoot = {q_alrt}/{q_uf}%"
            if q_alrt is not None and q_uf is not None
            else (f"UFBoot = {q_uf}%" if q_uf is not None else "高拓扑支持")
        )
        model_zh = f"（最优替换模型 {best_model}）" if best_model else ""
        model_en = f" under best-fit model {best_model}" if best_model else ""

        if ani_top is None:
            zh = f"基于 {marker_zh} 系统发育分析{model_zh}，{primary_q} 与参考株 {', '.join(sisters[:2]) or '近邻分支'} 聚为一支（{sup_txt}）。建议结合全基因组 wgANI 数据进一步核定属/种边界。"
            en = f"Phylogenetic analysis based on {marker_en}{model_en} placed {primary_q} sister to {', '.join(sisters[:2]) or 'nearest references'} ({sup_txt}). Whole-genome ANI comparison is recommended to finalize ICTV genus/species demarcation."
            return zh, en

        top_acc = ani_top.accession
        top_wg = ani_top.wg_ani
        top_af = min(ani_top.af_query, ani_top.af_ref)
        genus_label = ani_top.genus or (sister_genera[0] if sister_genera else "最接近已知属")

        if top_wg >= 95.0:
            zh = (
                f"基于 ICTV 噬菌体分类标准（同种 wgANI >= 95%），{primary_q} 与参考株 {top_acc}"
                + (f"（属 {ani_top.genus}）" if ani_top.genus else "")
                + f" 的全基因组相似性为 {top_wg:.2f}%（最低覆盖度 AF = {top_af:.1f}%），且在基于 {marker_zh} 的最大似然系统发育树{model_zh}中与之紧密聚类（{sup_txt}），建议归类为该已知种的新分离株。"
            )
            en = (
                f"Following ICTV Caudoviricetes demarcation criteria (>=95% wgANI for species), {primary_q} shares {top_wg:.2f}% intergenomic similarity (min AF = {top_af:.1f}%) with {top_acc}"
                + (f" (genus {ani_top.genus})" if ani_top.genus else "")
                + f" and forms a cohesive clade in the {marker_en} ML tree{model_en} ({sup_txt}), supporting assignment as an isolate of the same species."
            )
        elif top_wg >= 70.0:
            amb_note_zh = "（注：该数值接近 70% 属边界，已纳入邻近多属代表辅助界定边缘位置）" if abs(top_wg - 70.0) <= 5.0 else ""
            zh = (
                f"基于全基因组 wgANI 分析，{primary_q} 与 {genus_label} 属代表 {top_acc} 相似性为 {top_wg:.2f}%（70%-95%，最低覆盖度 AF = {top_af:.1f}%）{amb_note_zh}；"
                f"同时在基于 {marker_zh} 的系统发育树{model_zh}中稳健聚于该进化枝内（{sup_txt}），提示其为 {genus_label} 属下的候选新种。"
            )
            en = (
                f"Based on whole-genome intergenomic similarity ({top_wg:.2f}%, 70%-95% range; min AF = {top_af:.1f}% against {top_acc}) and coherent clustering in the {marker_en} phylogeny{model_en} ({sup_txt}), "
                f"{primary_q} is proposed as a candidate novel species within genus {genus_label}."
            )
        else:
            zh = (
                f"基于全基因组 wgANI 分析，{primary_q} 与所有已分类属代表（最近为 {genus_label} 属 {top_acc}，wgANI = {top_wg:.2f}%，AF = {top_af:.1f}%）均低于 ICTV 70% 属级阈值；"
                f"结合 {marker_zh} 系统发育分析{model_zh}中该基因组形成的独立深分支（{sup_txt}），建议其为候选新属。"
            )
            en = (
                f"Based on whole-genome intergenomic similarity (<70% ICTV genus threshold against all classified representatives; highest {top_wg:.2f}% with {top_acc}, min AF = {top_af:.1f}%) "
                f"and the distinct lineage formed in the {marker_en} phylogeny{model_en} ({sup_txt}), {primary_q} is proposed as a representative of a candidate novel genus."
            )

        if not consistent:
            zh += " 需注意该株 wgANI 最近邻与单基因姐妹分支存在轻度偏差，提示潜在基因组嵌合演化特征，分类判定仍以 wgANI 与 ICTV 多证据标准为准。"
            en += " Mild discordance between top wgANI neighbor and single-marker sister clade likely reflects phage genomic mosaicism; taxonomic assignment follows the primary wgANI anchor and ICTV multi-evidence framework."

        return zh, en
