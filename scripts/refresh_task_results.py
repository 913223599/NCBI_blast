# -*- coding: utf-8 -*-
"""
刷新指定历史任务 (ANNO_BB87E1C5) 的注释成果与数据库记录，应用全新的 Swiss-Prot / 安全审计格式化
"""
import sys
import json
from pathlib import Path
from Bio import SeqIO

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.analysis.annotation.types import FeatureItem
from src.analysis.annotation.builtin_annotator import BuiltinAnnotator
from src.analysis.annotation.fuser import AnnotationFuser
from src.analysis.annotation.engines.homology_engine import HomologyEngine
from src.analysis.annotation.deep_audit import DeepSafetyAuditor
from src.analysis.annotation.db import annotation_db

def refresh_task(task_id: str):
    task_dir = PROJECT_ROOT / "results" / "annotations" / task_id
    if not task_dir.exists():
        print(f"Task directory {task_dir} not found")
        return
        
    print(f"=== 正在刷新任务: {task_id} ===")
    
    # 1. 载入原始序列
    fasta_file = task_dir / "input_sequence.fasta"
    with open(fasta_file, "r", encoding="utf-8", errors="ignore") as f:
        records = list(SeqIO.parse(f, "fasta"))
    records_len_dict = {r.id: len(r.seq) for r in records}
    full_seq = "".join(str(r.seq) for r in records)
    
    # 2. 载入已有 features.json
    feat_json_path = task_dir / "features.json"
    with open(feat_json_path, "r", encoding="utf-8") as f:
        feat_raw_list = json.load(f)
    features = [FeatureItem(**item) for item in feat_raw_list]
    print(f"载入初始特征数: {len(features)}")
    
    # 3. 运行多库同源打捞 (包含 Swiss-Prot)
    faa_path = task_dir / "ANNO.faa"
    homo_eng = HomologyEngine()
    updated_cnt = homo_eng.complement_features(
        features=features,
        query_faa=faa_path,
        work_dir=task_dir,
        threads=8
    )
    print(f"同源打捞成功赋予/更新: {updated_cnt} 个基因")
    
    # 4. 运行深度生物安全审计
    auditor = DeepSafetyAuditor()
    safety_audit = auditor.run_safety_audit(
        query_faa=faa_path,
        work_dir=task_dir,
        threads=8
    )
    audit_file = task_dir / "safety_audit.json"
    with open(audit_file, "w", encoding="utf-8") as f:
        json.dump(safety_audit, f, ensure_ascii=False, indent=2)
    print(f"安全审计完成: AMR={len(safety_audit['amr_genes'])}, VF={len(safety_audit['virulent_factors'])}, Acr={len(safety_audit['anti_crispr_genes'])}")
    
    # 5. 反向融合安全证据与 Anti-CRISPR 标记
    fused_acr = AnnotationFuser.integrate_safety_audit(features, safety_audit)
    print(f"融合安全与 Acr 特征数: {fused_acr}")
    
    # 6. 生成标准导出文件
    annotator_helper = BuiltinAnnotator(genetic_code=11, min_orf_len_bp=200, prefix="ANNO")
    _, features, files = annotator_helper.export_features_to_files(
        records=records,
        all_features=features,
        output_dir=task_dir
    )
    
    # 7. 生成全套统计摘要
    comprehensive_summary = AnnotationFuser.generate_summary(
        records_len_dict=records_len_dict,
        full_seq=full_seq,
        features=features
    )
    summary_dict = comprehensive_summary.model_dump()
    summary_file = task_dir / "summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary_dict, f, ensure_ascii=False, indent=2)
    files["summary_json"] = str(summary_file.resolve())
    
    # 特征 JSON 写盘
    features_file = task_dir / "features.json"
    features_dict = [f.model_dump() for f in features]
    with open(features_file, "w", encoding="utf-8") as f:
        json.dump(features_dict, f, ensure_ascii=False)
    files["features_json"] = str(features_file.resolve())
    
    # 8. 更新 SQLite 数据库
    annotation_db.mark_completed(
        task_id=task_id,
        summary=summary_dict,
        files=files,
        safety_audit=safety_audit
    )
    
    print("\n=== 刷新完成！全景摘要 ===")
    print("总特征数:", comprehensive_summary.total_features)
    print("已知功能:", comprehensive_summary.annotated_count)
    print("假定蛋白:", comprehensive_summary.hypothetical_count)
    print("引擎贡献:", comprehensive_summary.engine_contributions)
    print("功能分布:", comprehensive_summary.category_distribution)

if __name__ == "__main__":
    refresh_task("ANNO_BB87E1C5")
