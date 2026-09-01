import os
import re
import csv
import json
import shutil
import asyncio
import logging
import urllib.request
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from Bio import SeqIO
from Bio.SeqRecord import SeqRecord

# 引入核心组件与配置
from ..core.base import BaseAssemblyStep
from ...workbench.models.tool_config import ToolConfig
from ..env.wsl_manager import WSLManager

logger = logging.getLogger("Assembly.PhageAnnotationStep")

class PhageAnnotationStep(BaseAssemblyStep):
    """
    噬菌体专项注释与安全性评估步骤 (Phage-Specific Annotation & Safety Audit)
    
    架构级特性：
    1. 全异步非阻塞架构 (Fully Asynchronous & Non-blocking): 彻底消除 urllib 和长时子进程对 Event Loop 的阻塞。
    2. 内存级 I/O 复用 (In-Memory Pipeline): SeqRecord 仅加载一次，经 Phold, Backfill, dbAPIS 流转后统一落盘，杜绝冗余反序列化。
    3. Grep 极速检表引擎: 摒弃 Python 原生遍历百万行 TSV，利用底层 grep 加速元数据检索。
    4. NCBI 呼吸锁限流机制 (Rate Limit Defense): 保护公共 API 访问，防范 IP 封禁。
    """

    @property
    def name(self) -> str:
        return "Phage Annotation (噬菌体智能注释)"

    async def execute(self) -> bool:
        """主执行流程控制"""
        self.status = "running"
        try:
            # ---------------------------------------------------------
            # 1. 基础环境与路径准备
            # ---------------------------------------------------------
            win_project_root = self.context.get("project_dir", os.getcwd())
            fasta = self.context.get("assembly_fasta")
            if not fasta:
                self.logger.error("未找到输入序列 (assembly_fasta)，注释流中止。")
                self.status = "failed"
                return False
            
            win_project_root = str(self.context.get("project_dir") or os.getcwd())
            win_path_obj = Path(win_project_root).resolve()
            drive_letter = win_path_obj.drive.replace(":", "").lower()
            safe_root = f"/mnt/{drive_letter}/.ncbi_blast_wsl_tmp"
            
            rel_project_path = str(win_path_obj.relative_to(win_path_obj.anchor)).replace("\\", "/")
            mnt_project_root = f"/mnt/{drive_letter}/{rel_project_path}"
            
            # 建立软链接以规避 Windows 长路径或特殊字符问题
            await self.runner.run_command(["bash", "-c", f"ln -sfT '{mnt_project_root}' {safe_root}"])
            
            def to_safe(p: str | Path) -> str:
                """路径安全转换闭包"""
                p_str = str(p).replace("\\", "/")
                root_str = win_project_root.replace("\\", "/")
                return p_str.replace(root_str, safe_root)

            # ---------------------------------------------------------
            # 2. 依赖工具自检与自愈
            # ---------------------------------------------------------
            missing_mandatory = []
            if (await self.runner.run_command(["which", "prodigal-gv"])) != 0: 
                missing_mandatory.append("prodigal-gv")
            
            if missing_mandatory:
                logger.info(f" 发现关键依赖缺失: {missing_mandatory}, 正在执行增量环境自愈...")
                setup_env_wsl = f"{safe_root}/scripts/setup_assembly_env.sh"
                if (await self.runner.run_command(["test", "-f", setup_env_wsl])) == 0:
                    await self.runner.run_command(["bash", setup_env_wsl])
                else:
                    logger.warning(f"自愈脚本不存在: {setup_env_wsl}，尝试继续执行...")

            pharokka_db_default = "/opt/pharokka_db"
            if (await self.runner.run_command(["test", "-d", pharokka_db_default])) != 0:
                if self.on_progress: self.on_progress(2, "初始化 Pharokka 数据库链接...")
                setup_script_wsl = f"{mnt_project_root}/scripts/setup_pharokka.sh"
                if (await self.runner.run_command(["test", "-f", setup_script_wsl])) == 0:
                    await self.runner.run_command(["bash", setup_script_wsl])

            # ---------------------------------------------------------
            # 3. 初始化工作空间
            # ---------------------------------------------------------
            win_work_path = self.get_working_dir()
            safe_fasta = to_safe(fasta)
            safe_work_dir = to_safe(win_work_path)
            
            win_pharokka_out = win_work_path / "pharokka_res"
            win_phold_out = win_work_path / "phold_res"
            win_checkv_dir = win_work_path / "checkv_res"
            
            for path in [win_pharokka_out, win_phold_out, win_checkv_dir]:
                path.mkdir(parents=True, exist_ok=True)

            sys_cores = os.cpu_count() or 8
            threads = max(1, int(sys_cores * 0.9))

            # ---------------------------------------------------------
            # 4. CheckV 质量评估 (基因组完整性)
            # ---------------------------------------------------------
            if self.on_progress: self.on_progress(5, "正在评估基因组完整性 (CheckV)...")
            try:
                ret_which = await self.runner.run_command(["which", "checkv"], cwd=safe_work_dir)
                ret_db = await self.runner.run_command(["test", "-d", "/opt/checkv-db"], cwd=safe_work_dir)
                
                if ret_which == 0 and ret_db == 0:
                    checkv_cmd = [
                        "checkv", "end_to_end", safe_fasta, to_safe(win_checkv_dir), 
                        "-t", str(threads), "-d", "/opt/checkv-db"
                    ]
                    logger.info("启动 CheckV 全流程评估...")
                    await self.runner.run_command(checkv_cmd, cwd=safe_work_dir)
                    quality_summary = win_checkv_dir / "quality_summary.tsv"
                    checkv_result = self._parse_checkv(quality_summary)
                    self.context.update("checkv", checkv_result)
                    
                    # 4.1 CheckV 质量关卡 (Quality Gate)
                    # 利用 CheckV 的评估结果，在进入 Pharokka 注释之前，
                    # 过滤掉确认为非病毒的细菌垃圾碎片。
                    # 只保留: viral_genes > 0 或 checkv_quality 为 High/Medium/Complete 的序列。
                    filtered_fasta = win_work_path / "checkv_filtered.fasta"
                    gate_kept = self._checkv_quality_gate(quality_summary, Path(str(fasta)), filtered_fasta)
                    if gate_kept > 0:
                        fasta = filtered_fasta
                        safe_fasta = to_safe(filtered_fasta)
                        self.context.update("assembly_fasta", filtered_fasta)
                    
                    # 4.2 统一多序列处理 (Unified Multi-FASTA Processing)
                    # 取消了原有的多分支切割与重型 AI 循环，将 CheckV 过滤后的所有高质量
                    # Contigs 作为一个单一实体 (Multi-FASTA) 发送给下游工具链，这符合组装分析
                    # 的真实状态并能百倍加速运行。
                    
                    if not fasta or not fasta.exists() or fasta.stat().st_size == 0:
                        logger.error("经过 CheckV 质量关卡后，没有足够高质量的序列。")
                        self.status = "failed"
                        return False
                        
                    logger.info(f" 统一批处理模式: 将整体组装产物作为单实体发送进行并行注释...")
                    
                    # 假名 p_id 用于统一命名输出画图与文件前缀
                    p_id = "Phage_Assembly" 
                    unified_result = await self._process_phage_assembly(
                        p_id, fasta, safe_fasta, win_work_path, threads, to_safe
                    )
                    
                    if unified_result:
                        self.context.update("gbk_file", str(unified_result.get("gbk_file", "")))
                        self.context.update("plot_file", str(unified_result.get("plot_file", "")))
                        self.context.update("phagescope_audit", unified_result.get("audit_data"))
                        self.context.update("genomic_metrics", unified_result.get("genomic_metrics"))
                        self.context.update("annotation_dir", str(unified_result.get("annotation_dir", "")))
                        
                    self.status = "completed"
                    if self.on_progress: self.on_progress(100, "多路智能注释与审计任务执行完成")
                    return True

                else:
                    logger.warning("[CheckV] 引擎或数据库未找到，已跳过质量评估模块。")
                    self.context.update("checkv", {"checkv_quality": "Skipped (CheckV not found)"})
                    self.status = "failed"
                    return False
            except Exception as e:
                logger.warning(f"[CheckV] 质量评估模块抛出异常 (非致命): {e}")
                self.status = "failed"
                return False

        except Exception as e:
            logger.error(f" [Annotation] 核心流程执行过程中发生严重异常: {e}", exc_info=True)
            self.status = "failed"
            return False

    async def _process_phage_assembly(self, p_id: str, fasta: Path, safe_fasta: str, parent_dir: Path, threads: int, to_safe) -> dict:
        """处理整个 Multi-FASTA 序列实体的全套注释、结构预测与画图流水线"""
        win_work_path = parent_dir / "unified_annotation"
        win_work_path.mkdir(exist_ok=True)
        safe_work_dir = to_safe(win_work_path)
        
        win_pharokka_out = win_work_path / "pharokka_res"
        win_phold_out = win_work_path / "phold_res"
        win_pharokka_out.mkdir(exist_ok=True)
        win_phold_out.mkdir(exist_ok=True)
        
        from typing import Any
        result_dict: dict[str, Any] = {"contig_id": p_id, "fasta": str(fasta)}
        
        logger.info(f" 开始处理噬菌体实体: {p_id}")
        
        # 5. Pharokka 主干基因注释
        def pharokka_handler(line: str):
            if self.on_progress: self.on_progress(15, f"[{p_id}] 正在运行 Pharokka 注释...")

        safe_pharokka_out = to_safe(win_pharokka_out)
        pharokka_cmd = [
            "pharokka.py", "-i", safe_fasta, "-o", safe_pharokka_out,
            "-d", "/opt/pharokka_db", "-t", str(threads), "-p", "PHAGE",
            "--dnaapler", "--sensitivity", "8", "-f"
        ]
        
        pharokka_success = False
        try:
            ret_pharokka = await self.runner.run_command(pharokka_cmd, cwd=safe_work_dir, on_output=pharokka_handler, silence_errors=True)
            if ret_pharokka == 0 and (win_pharokka_out / "PHAGE.gbk").exists():
                pharokka_success = True
        except Exception as e:
            logger.warning(f"[{p_id}] Pharokka 运行异常: {e}")

        if not pharokka_success:
            logger.warning(f"[{p_id}] Pharokka (--dnaapler) 运行未能正常生成 GBK (可能是未找到大亚基等原因)，准备降级重试 (移除 dnaapler)...")
            pharokka_fallback_cmd = [
                "pharokka.py", "-i", safe_fasta, "-o", safe_pharokka_out,
                "-d", "/opt/pharokka_db", "-t", str(threads), "-p", "PHAGE",
                "--sensitivity", "8", "-f"
            ]
            await self.runner.run_command(pharokka_fallback_cmd, cwd=safe_work_dir, on_output=pharokka_handler)
        
        # 6. Phold AI 结构深度增强
        def phold_handler(line: str):
            if self.on_progress: self.on_progress(60, f"[{p_id}] AI 结构折叠中...")
            
        safe_gbk_for_phold = to_safe(win_pharokka_out / "PHAGE.gbk")
        phold_base_cmd = " ".join([
            "phold", "run", "-i", safe_gbk_for_phold, "-o", to_safe(win_phold_out), 
            "-d", "/opt/phold_db", "-t", str(threads), "-f", "--sensitivity", "9.5"
        ])
        
        offline_env = "export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1"
        hf_token = os.environ.get("HF_TOKEN") or (self.context.get("params") or {}).get("hf_token")
        if hf_token: offline_env += f" HF_TOKEN={hf_token}"
        
        phold_cmd = ["bash", "-c", f"{offline_env} && {phold_base_cmd}"]
        ret_phold = await self.runner.run_command(phold_cmd, cwd=safe_work_dir, on_output=phold_handler, is_shell=True)
        
        win_final_gbk = win_phold_out / "phold.gbk" if ret_phold == 0 else win_pharokka_out / "PHAGE.gbk"

        if win_final_gbk.exists():
            records = list(SeqIO.parse(win_final_gbk, "genbank"))

            # 7. 内存级注释精修
            if self.on_progress: self.on_progress(90, f"[{p_id}] 专家库回填与防御系统扫描...")
            await self._silent_backfill(records, win_final_gbk.parent, threads)
            apis_hits = await self._run_apis_hmm_scan(records, win_final_gbk.parent)
            
            with open(win_final_gbk, "w", encoding="utf-8") as f:
                SeqIO.write(records, f, "genbank")

            integrated_tsv = win_work_path / "Integrated_Final_Annotations.tsv"
            await asyncio.to_thread(self._generate_final_tsv, records, integrated_tsv)

            # 8. 深度安全性与分类审计 (默认跳过，通过参数开启)
            audit_data = None
            enable_deep_audit = (self.context.get("params") or {}).get("enable_deep_audit", False)
            
            if enable_deep_audit:
                try:
                    direct_scan = await self._direct_safety_scan(integrated_tsv, threads)
                    mash_hit_tsv = win_pharokka_out / "PHAGE_top_hits_mash_inphared.tsv"
                    ref_audit = await asyncio.to_thread(self._mine_phagescope_metadata, mash_hit_tsv)
                    
                    host_results = await self._deep_host_prediction(fasta, threads)
                    lifecycle_results = await self._run_bacphlip_prediction(win_final_gbk)
                    
                    audit_data = self._merge_safety_audit(direct_scan, ref_audit)
                    audit_data["host_prediction_enhanced"] = host_results
                    audit_data["amr_genes_direct"] = direct_scan.get("amr_genes", [])
                    audit_data["amr_genes_reference"] = ref_audit.get("amr_genes", [])
                    audit_data["virulent_factors_direct"] = direct_scan.get("virulent_factors", [])
                    audit_data["virulent_factors_reference"] = ref_audit.get("virulent_factors", [])
                    audit_data["anti_crispr_evidence"] = "direct" if "Detected" in str(direct_scan.get("anti_crispr", "")) else "reference"
                    if apis_hits: audit_data["defense_systems"] = apis_hits
                    
                    result_dict["audit_data"] = audit_data
                    result_dict["host_prediction"] = host_results
                    result_dict["lifecycle_prediction"] = lifecycle_results

                    win_plot_dir = win_work_path / "phage_plot"
                    win_plot_dir.mkdir(parents=True, exist_ok=True)
                    tree_png = win_plot_dir / "phage_phylogeny.png"
                    await asyncio.to_thread(self._generate_phylogeny_image, audit_data, tree_png)
                    if tree_png.exists(): result_dict["phylogeny_file"] = str(tree_png)
                except Exception as audit_e: 
                    logger.error(f"[{p_id}] 安全审计模块异常: {audit_e}")
            else:
                logger.info(f"[{p_id}] 深度安全审计和宿主预测已被设置为跳过 (默认不选)")
                # 即使跳过了重度审计，也将轻量级的防御系统扫描结果塞入 audit_data 中供前端展示
                audit_data = {}
                if apis_hits: audit_data["defense_systems"] = apis_hits
                result_dict["audit_data"] = audit_data

            # 10. 硬核生信指标统计
            try:
                total_len, total_gc_bases, cds_len = 0, 0, 0
                trna_list, is_circular = [], "Linear"
                for rec in records:
                    seq_len = len(rec.seq)
                    total_len += seq_len
                    seq_upper = str(rec.seq).upper()
                    total_gc_bases += seq_upper.count("G") + seq_upper.count("C")
                    if "circular" in rec.annotations.get("topology", "").lower(): is_circular = "Circular"
                    for feat in rec.features:
                        if feat.type == "CDS": cds_len += int(feat.location.end - feat.location.start)
                        elif feat.type == "tRNA":
                            note = feat.qualifiers.get("note", ["--"])[0]
                            trna_list.append(note.replace("tRNA-", ""))
                
                gc_content = (total_gc_bases / total_len * 100) if total_len > 0 else 0
                metrics = {
                    "total_length": total_len,
                    "gc_content": f"{gc_content:.2f}%",
                    "coding_density": f"{(cds_len/total_len*100):.2f}%" if total_len > 0 else "0%",
                    "topology": is_circular,
                    "tRNA_details": ", ".join(sorted(set(trna_list))) if trna_list else "None"
                }
                result_dict["genomic_metrics"] = metrics
            except Exception as e: 
                logger.warning(f"[{p_id}] 指标计算失败: {e}")

            # 11. 全景基因组圈图绘制
            win_plot_dir = win_work_path / "phage_plot"
            try:
                if audit_data:
                    for rec in records:
                        for feat in rec.features:
                            if feat.type in ["CDS", "tRNA", "tmRNA"]:
                                cid = feat.qualifiers.get("locus_tag", [feat.qualifiers.get("ID", [""])[0]])[0]
                                if cid:
                                    for hit in audit_data.get("amr_genes_direct", []):
                                        if hit.get("cds_id") == cid:
                                            feat.qualifiers["AMR_Gene_Family"] = [hit.get("description", "AMR_Gene")]
                                    for hit in audit_data.get("virulent_factors_direct", []):
                                        if hit.get("cds_id") == cid:
                                            feat.qualifiers["vfdb_short_name"] = [hit.get("description", "Virulence_Factor")]
                
                with open(win_final_gbk, "w", encoding="utf-8") as f:
                    SeqIO.write(records, f, "genbank")

                updated_gff = win_work_path / "updated_phage.gff"
                await asyncio.to_thread(self._sync_gff_annotations, records, win_pharokka_out / "PHAGE.gff", updated_gff, audit_data)
                
                win_plot_dir.mkdir(parents=True, exist_ok=True)
                # 修改点：将画图名称改为噬菌体 ID
                plot_cmd = [
                    "pharokka_plotter.py", "-i", to_safe(fasta), 
                    "--gff", to_safe(updated_gff), 
                    "--genbank", to_safe(win_final_gbk), 
                    "-o", to_safe(win_plot_dir), "-f", "-p", p_id.replace("|", "_")
                ]
                await self.runner.run_command(plot_cmd, cwd=safe_work_dir)
                png_files = list(win_plot_dir.glob("*.png"))
                if png_files: result_dict["plot_file"] = str(png_files[0])
            except Exception as e: 
                logger.warning(f"[{p_id}] 圈图绘制失败: {e}")

            result_dict["annotation_dir"] = str(win_final_gbk.parent)
            result_dict["gbk_file"] = str(win_final_gbk)
            
        return result_dict



    # =========================================================================
    # 辅助核心子程序 (Auxiliary Sub-routines)
    # =========================================================================

    def _generate_final_tsv(self, records: List[SeqRecord], output_tsv: Path):
        """将 BioPython 内存对象写入易于前端展现的 TSV"""
        try:
            with open(output_tsv, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f, delimiter="\t")
                writer.writerow(["Contig", "Type", "ID", "Start", "End", "Strand", "Function", "Product", "Notes", "Translation"])
                
                for rec in records:
                    for feat in rec.features:
                        if feat.type in ["CDS", "tRNA", "tmRNA", "pseudogene", "misc_feature"]:
                            cid = feat.qualifiers.get("locus_tag", [feat.qualifiers.get("ID", [""])[0]])[0]
                            start = int(str(feat.location.start).strip('<>')) + 1 if feat.location else 0  # 转换为 1-based
                            end = int(str(feat.location.end).strip('<>')) if feat.location else 0
                            strand = "+" if feat.location and feat.location.strand and feat.location.strand >= 0 else "-"
                            func = feat.qualifiers.get("function", [""])[0]
                            prod = feat.qualifiers.get("product", [""])[0]
                            notes = " ; ".join(feat.qualifiers.get("note", []))
                            translation = feat.qualifiers.get("translation", [""])[0]
                            
                            writer.writerow([rec.id, feat.type, cid, start, end, strand, func, prod, notes, translation])
            logger.info(f" 生成终极整合注释表: {output_tsv.name}")
        except Exception as e:
            logger.warning(f"生成终极注释表失败: {e}")

    def _sync_gff_annotations(self, records: List[SeqRecord], orig_gff: Path, new_gff: Path, audit_data: dict | None = None):
        """同步内存中的最新注释 (product/function) 回写到 GFF，并注入耐药/毒力因子标签以供绘图使用"""
        try:
            import urllib.parse
            if not orig_gff.exists():
                return
            prod_map = {}
            func_map = {}
            for rec in records:
                for feat in rec.features:
                    if feat.type in ["CDS", "tRNA", "tmRNA"]:
                        cid = feat.qualifiers.get("locus_tag", [feat.qualifiers.get("ID", [""])[0]])[0]
                        prod = feat.qualifiers.get("product", [""])[0]
                        func = feat.qualifiers.get("function", [""])[0]
                        if cid:
                            if prod: prod_map[cid] = prod
                            if func: func_map[cid] = func
            
            # 解析耐药和毒力基因映射
            amr_vf_map = {}
            if audit_data:
                for hit in audit_data.get("amr_genes_direct", []):
                    if hit.get("cds_id"):
                        val = hit.get("description", "AMR_Gene")
                        amr_vf_map[hit["cds_id"]] = ("AMR_Gene_Family", urllib.parse.quote(val))
                for hit in audit_data.get("virulent_factors_direct", []):
                    if hit.get("cds_id"):
                        val = hit.get("description", "Virulence_Factor")
                        amr_vf_map[hit["cds_id"]] = ("vfdb_short_name", urllib.parse.quote(val))
                            
            with open(orig_gff, "r", encoding="utf-8") as fin, open(new_gff, "w", encoding="utf-8") as fout:
                for line in fin:
                    if line.startswith("#") or not line.strip():
                        fout.write(line)
                        continue
                    parts = line.strip().split("\t")
                    if len(parts) >= 9:
                        attrs = parts[8].split(";")
                        new_attrs = []
                        cid = None
                        for attr in attrs:
                            if attr.startswith("ID="):
                                cid = attr[3:]
                                break
                        
                        if cid in prod_map or cid in func_map or cid in amr_vf_map:
                            for attr in attrs:
                                if attr.startswith("product=") and cid in prod_map:
                                    new_attrs.append(f"product={prod_map[cid]}")
                                elif attr.startswith("function=") and cid in func_map:
                                    new_attrs.append(f"function={func_map[cid]}")
                                else:
                                    new_attrs.append(attr)
                            
                            if cid in prod_map and not any(a.startswith("product=") for a in new_attrs):
                                new_attrs.append(f"product={prod_map[cid]}")
                            if cid in func_map and not any(a.startswith("function=") for a in new_attrs):
                                new_attrs.append(f"function={func_map[cid]}")
                            if cid in amr_vf_map:
                                key, val = amr_vf_map[cid]
                                if not any(a.startswith(f"{key}=") for a in new_attrs):
                                    new_attrs.append(f"{key}={val}")
                                
                            parts[8] = ";".join(new_attrs)
                            fout.write("\t".join(parts) + "\n")
                        else:
                            fout.write(line)
                    else:
                        fout.write(line)
            logger.info(f" 生成同步后用于绘图的 GFF 文件: {new_gff.name}")
        except Exception as e:
            logger.warning(f"同步更新 GFF 文件失败: {e}")
            import shutil
            if orig_gff.exists():
                shutil.copy2(orig_gff, new_gff)

    async def _direct_safety_scan(self, annotation_tsv: Path, threads: int) -> dict:
        """基于直接序列 Blast 的安全性扫描 (异步重构，避免主线程阻塞)"""
        result = {
            "amr_genes": [], "virulent_factors": [],
            "anti_crispr": "Not Detected", "anti_crispr_genes": [],
            "lysogeny_markers": [],
        }

        if not annotation_tsv or not annotation_tsv.exists(): 
            return result

        query_faa = annotation_tsv.parent / "query_proteins.faa"
        n_proteins = 0
        
        # 提取翻译的蛋白质序列为 FASTA
        with open(annotation_tsv, "r", encoding="utf-8") as f_in, open(query_faa, "w", encoding="utf-8") as f_out:
            reader = csv.DictReader(f_in, delimiter="\t")
            for row in reader:
                if row.get("Type") == "CDS" and row.get("Translation"):
                    cds_id = row.get("ID", f"CDS_{n_proteins}")
                    f_out.write(f">{cds_id} {row.get('Product', '')}\n{row['Translation']}\n")
                    n_proteins += 1
                    
                    # 提取溶原性标记基因
                    text = f"{row.get('Product', '')} {row.get('Function', '')}".lower()
                    for kw in ["integrase", "recombinase", "excisionase", "repressor", "transposase", "lysogeny", "prophage"]:
                        if kw in text:
                            result["lysogeny_markers"].append({"cds_id": cds_id, "product": row.get("Product", ""), "keyword": kw})
                            break
                            
        if n_proteins == 0: 
            return result

        project_root = Path(str(self.context.get("project_dir") or os.getcwd())).resolve()
        meta_base = project_root / "database" / "phagescope" / "metadata"
        blast_db = project_root / "database" / "phagescope" / "phagescope_proteins"

        # 内存映射表
        amr_index, vf_index, acr_index = {}, {}, {}

        def load_meta(d_path: Path, key_id: str, key_val: str, target_dict: dict):
            """闭包：装载 TSV 到字典以供内存极速查询"""
            if d_path.exists():
                for t_file in d_path.glob("*.tsv"):
                    try:
                        with open(t_file, encoding="utf-8") as mf:
                            for r in csv.DictReader(mf, delimiter="\t"):
                                pid = r.get(key_id, "")
                                if pid: target_dict[pid] = r.get(key_val, "")
                    except Exception: pass

        # 使用线程池并发装载字典，防止大文件解析卡顿
        await asyncio.to_thread(load_meta, meta_base / "amr", "Protein_id", "Aligned_Protein_in_CARD", amr_index)
        await asyncio.to_thread(load_meta, meta_base / "virulent_factor", "Protein_id", "Aligned_Protein_in_VFDB", vf_index)
        await asyncio.to_thread(load_meta, meta_base / "anti_crispr", "Protein_ID", "Source", acr_index)

        out_file = annotation_tsv.parent / "phagescope_blast_hits.tsv"
        
        # 绝对路径净化，调用纯净 BASH
        blast_cmd = [
            "blastp",
            "-query", WSLManager.to_wsl_path(str(query_faa)),
            "-db", WSLManager.to_wsl_path(str(blast_db)),
            "-out", WSLManager.to_wsl_path(str(out_file)),
            "-outfmt", "6 qseqid sseqid pident length evalue bitscore",
            "-evalue", "1e-10", "-max_target_seqs", "5", "-num_threads", str(threads)
        ]

        logger.info(f"[SafetyScan] 启动异步 blastp 对抗 PhageScope 蛋白库 ({n_proteins} CDS)...")
        ret = await self.runner.run_command(blast_cmd, silence_errors=True)
        
        # 解析比对结果并进行专家标注映射
        if ret == 0 and out_file.exists():
            with open(out_file, "r", encoding="utf-8") as f:
                for line in f:
                    cols = line.strip().split("\t")
                    if len(cols) < 6: continue
                    cds_id, target_id, identity, _, evalue, bitscore = cols[:6]

                    hit_info = {
                        "cds_id": cds_id, "target_id": target_id, "identity": float(identity),
                        "evalue": evalue, "bitscore": float(bitscore), "evidence": "sequence_alignment",
                    }
                    if target_id in amr_index:
                        h = dict(hit_info); h["description"] = amr_index[target_id]
                        result["amr_genes"].append(h)
                    if target_id in vf_index:
                        h = dict(hit_info); h["description"] = vf_index[target_id]
                        result["virulent_factors"].append(h)
                    if target_id in acr_index:
                        h = dict(hit_info); h["source"] = acr_index[target_id]
                        result["anti_crispr_genes"].append(h)

        if result["anti_crispr_genes"]: 
            result["anti_crispr"] = f"Detected ({len(result['anti_crispr_genes'])} Acr proteins)"
            
        return result

    def _merge_safety_audit(self, direct: dict, reference: dict) -> dict:
        """合并序列直接扫描 (Direct) 与相似度溯源 (Reference) 的安全性审计结果"""
        merged = dict(reference)
        
        def merge_list(list1, list2, key):
            combined = {item.get(key): item for item in (list1 + list2) if item.get(key)}.values()
            return list(combined)

        merged["amr_genes"] = merge_list(direct.get("amr_genes", []), reference.get("amr_genes", []), "description")
        merged["virulent_factors"] = merge_list(direct.get("virulent_factors", []), reference.get("virulent_factors", []), "description")
        
        direct_acr = direct.get("anti_crispr", "Not Detected")
        merged["anti_crispr"] = direct_acr if "Detected" in str(direct_acr) else reference.get("anti_crispr", "Not Detected")
        merged["lysogeny_markers"] = direct.get("lysogeny_markers", [])

        has_amr = bool(merged["amr_genes"])
        has_vf = bool(merged["virulent_factors"])
        has_lysogeny = bool(merged["lysogeny_markers"])

        if has_amr and has_vf: merged["safety_status"] = "Caution (AMR + VF Detected)"
        elif has_amr: merged["safety_status"] = "Warning (AMR Detected)"
        elif has_vf: merged["safety_status"] = "Warning (VF Detected)"
        elif has_lysogeny: merged["safety_status"] = "Review (Lysogeny Markers Found)"
        else: merged["safety_status"] = "Secure (Clear)"

        return merged

    def _mine_phagescope_metadata(self, mash_hit_path: Path) -> dict:
        """从 Mash 命中结果反向挖掘宿主、分类学与环境元数据 (在线程池中执行)"""
        audit = {
            "lifestyle": "Unknown", "host_origin": "--", "environment": "Unknown",
            "safety_status": "Secure (Clear)", "amr_genes": [], "virulent_factors": [],
            "anti_crispr": "Not Detected", "taxonomy_info": {}, "top_hits_metadata": []
        }
        if not mash_hit_path.exists(): return audit

        try:
            with open(mash_hit_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f, delimiter="\t")
                count = 0
                for row in reader:
                    if count >= 30: break
                    acc = row.get("Accession")
                    if not acc: continue
                    is_inphared = "no_inphared" not in acc
                    
                    try:
                        mash_dist = float(row.get("mash_distance", 0.5))
                    except (ValueError, TypeError):
                        mash_dist = 0.5

                    hit_info = {
                        "accession": acc.replace("no_inphared_", ""), 
                        "distance": mash_dist,
                        "description": row.get("Description", "Unknown"),
                        "classification": row.get("Classification") or row.get("Taxonomy", ""),
                        "genus": row.get("Genus", ""), "family": row.get("Family", ""),
                        "host": row.get("Host", ""), "completeness": row.get("Completeness", "N/A"),
                        "is_expert_curated": is_inphared
                    }
                    audit["top_hits_metadata"].append(hit_info)
                    
                    if count == 0:
                        audit["taxonomy_info"] = {
                            "top_hit_id": hit_info["accession"], 
                            "top_hit_name": hit_info["description"],
                            "similarity": f"{(1.0 - hit_info['distance'])*100:.2f}%",
                            "Classification": hit_info["classification"],
                            "Genus": hit_info["genus"], "Family": hit_info["family"], "Host": hit_info["host"]
                        }
                        audit["host_origin"] = hit_info["host"]
                    count += 1

            if not audit["top_hits_metadata"]: return audit
            top_id = audit["top_hits_metadata"][0]["accession"]
            
            project_root = Path(str(self.context.get("project_dir") or os.getcwd())).resolve()
            meta_base = project_root / "database" / "phagescope" / "metadata"

            # 基于最佳命中去库中拉取关联生态信息
            for f_name in ["refseq_phage_meta_data.tsv", "genbank_phage_meta_data.tsv"]:
                p = meta_base / "phage" / f_name
                if not p.exists(): continue
                with open(p, "r", encoding="utf-8") as mf:
                    for row in csv.DictReader(mf, delimiter="\t"):
                        if row.get("Phage_ID") == top_id or row.get("Accession") == top_id:
                            audit["lifestyle"] = row.get("Lifestyle", "Unknown")
                            audit["host_origin"] = row.get("Host", audit["host_origin"])
                            audit["environment"] = row.get("Isolation_source") or row.get("Environment", "Unknown")
                            break
                    if audit["lifestyle"] != "Unknown": break

        except Exception as e:
            logger.warning(f"[PhageScope Audit] Metadata extraction error: {e}")
            
        return audit

    def _generate_phylogeny_image(self, audit_data: dict, output_path: Path):
        """基于分类学血缘关系绘制系统发育树形图"""
        try:
            import matplotlib
            matplotlib.use('Agg')  # 无头模式，防止引发 GUI 线程崩溃
            import matplotlib.pyplot as plt
            from Bio import Phylo
            from Bio.Phylo.BaseTree import Tree, Clade

            hits = audit_data.get("top_hits_metadata", [])[:30]
            if not hits: return

            taxonomy_nodes = {}
            root = Clade(name="Phage_World_Root", branch_length=0.1)

            def get_or_create_clade(path_list):
                current = root
                path_str = ""
                for rank in path_list:
                    path_str += "/" + rank
                    if path_str not in taxonomy_nodes:
                        new_node = Clade(name=rank, branch_length=0.08)
                        current.clades.append(new_node)
                        taxonomy_nodes[path_str] = new_node
                    current = taxonomy_nodes[path_str]
                return current

            for hit in hits:
                raw_class = hit.get("classification", "")
                if not raw_class:
                    desc_parts = hit.get("description", "").split()
                    raw_class = f"Viruses; Unclassified; {' '.join(desc_parts[:2])}" if len(desc_parts) >= 2 else f"Viruses; Unclassified; {hit['accession']}"

                ranks = [r.strip() for r in raw_class.replace(";", " ").split() if r.strip()]
                v_index = ranks.index("Viruses") if "Viruses" in ranks else -1
                path = ranks[v_index:][::-1][:6] if v_index != -1 else ["Unclassified"]

                leaf = Clade(name=f"{hit.get('description', 'Unknown')[:37]}... ({hit.get('accession', 'N/A')})", branch_length=max(0.01, float(hit.get("distance", 0.3))))
                get_or_create_clade(path).clades.append(leaf)

            root.clades.insert(0, Clade(name=" QUERY_PHAGE", branch_length=0.05))
            
            plt_height = max(8, len(hits) * 0.45)
            fig = plt.figure(figsize=(12, plt_height))
            ax = fig.add_subplot(1, 1, 1)

            Phylo.draw(Tree(root=root, rooted=True), axes=ax, do_show=False, show_confidence=False, label_func=lambda x: str(x.name) if x.name and len(x.clades) == 0 else "")

            for text in ax.texts:
                if "QUERY_PHAGE" in text.get_text():
                    text.set_color("#e11d48"); text.set_fontweight("bold"); text.set_fontsize(12)
                else:
                    text.set_fontsize(10); text.set_color("#1e293b")
            
            ax.set_title("Evolutionary Taxonomy Relationship (Clustered by Lineage)", fontsize=14, fontweight='bold', pad=20)
            ax.set_xlabel("Relative Genomic Distance", fontsize=10, color="#64748b")
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            ax.spines['left'].set_color('#e2e8f0')
            plt.tight_layout()
            plt.savefig(output_path, dpi=180, bbox_inches='tight')
            plt.close()

        except Exception as e:
            logger.warning(f"[Phylogeny] 生成层级进化树失败: {e}")

    async def _deep_host_prediction(self, fasta_path: Path, threads: int) -> dict:
        """深层宿主预测体系 (包含 Mash 块搜索与异步 Grep)"""
        result = {"top_hits": [], "status": "No database found", "source": "Local Phage/Prophage Chunked Fingerprints"}
        if not fasta_path.exists() or fasta_path.stat().st_size < 100: 
            return result

        db_dir = ToolConfig.DATABASE_ROOT
        
        # 建立独立的高速缓存沙盒
        local_work_dir = "/dev/shm/host_pred_" + os.urandom(4).hex()
        await self.runner.run_command(["mkdir", "-p", local_work_dir])
        local_fasta = f"{local_work_dir}/query.fasta"
        await self.runner.run_command(["cp", WSLManager.to_wsl_path(str(fasta_path)), local_fasta])

        dbs = []
        if (db_dir / "Phage.17770sequence.fasta.gz.msh").exists(): 
            dbs.append(("Phage.17K", db_dir / "Phage.17770sequence.fasta.gz.msh"))
        dbs.extend((f"Prophage.{cf.stem}", cf) for cf in sorted(db_dir.glob("chunk_*.msh")))

        all_hits = []
        try:
            # 块状 Mash 查询
            for idx, (db_name, db_path) in enumerate(dbs, 1):
                output = []
                ret = await self.runner.run_command(
                    ["mash", "dist", "-p", str(threads), WSLManager.to_wsl_path(str(db_path)), local_fasta], 
                    on_output=lambda l: output.append(l), silence_errors=True
                )
                if ret == 0:
                    for line in output:
                        parts = line.strip().split("\t")
                        if len(parts) >= 3 and float(parts[2]) < 0.10:
                            all_hits.append({
                                "accession": parts[0].split("|")[0].split(".")[0], 
                                "full_id": parts[0],
                                "distance": float(parts[2]), 
                                "similarity": f"{(1.0 - float(parts[2]))*100:.2f}%",
                                "confidence": "High" if float(parts[2]) < 0.05 else "Medium", 
                                "db_source": db_name
                            })
        finally:
            await self.runner.run_command(["rm", "-rf", local_work_dir])

        if not all_hits:
            result["status"] = "No significant match found"
            return result

        top_candidates = sorted(all_hits, key=lambda x: x["distance"])[:50]
        target_ids = {c["full_id"] for c in top_candidates}
        
        # 极速 Grep 字典检表逻辑：取代 Python 级别的千万次字符串比较
        id_list_file = self.get_working_dir() / f"target_ids_{os.urandom(4).hex()}.txt"
        id_list_file.write_text("\n".join(target_ids), encoding="utf-8")
        
        descriptions = {}
        for tsv_name in ["Phage.17770sequence.metadata.tsv", "Prophage.3281395sequence.metadata.tsv"]:
            tsv_path = db_dir / tsv_name
            if not tsv_path.exists(): continue
            
            grep_out = []
            await self.runner.run_command(
                ["grep", "-F", "-f", WSLManager.to_wsl_path(str(id_list_file)), WSLManager.to_wsl_path(str(tsv_path))], 
                on_output=lambda l: grep_out.append(l), silence_errors=True
            )
            
            for line in grep_out:
                parts = line.strip().split("\t")
                if len(parts) > 1 and parts[0] in target_ids:
                    descriptions[parts[0]] = parts[1]
                    
        id_list_file.unlink(missing_ok=True)

        for cand in top_candidates:
            cand["description"] = descriptions.get(cand["full_id"], "Unknown")

        # NCBI API 回填与速率锁
        for cand in top_candidates[:15]:
            if cand["description"] == "Unknown":
                ext_info = await self._silent_ncbi_fetch(cand["accession"])
                if ext_info: 
                    cand["description"] = ext_info
                # Rate Limit Defense: 防止触发 HTTP 429 封锁
                await asyncio.sleep(0.4) 

        result["top_hits"] = top_candidates[:10]
        result["status"] = "Success"
        return result

    async def _silent_ncbi_fetch(self, accession: str) -> Optional[str]:
        """静默向 NCBI 请求数据 (基于 aio-threads，防阻塞主引擎)"""
        def sync_fetch():
            try:
                url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=nuccore&term={accession}&retmode=json"
                req = urllib.request.Request(url, headers={"User-Agent": "PhageScope/2.0"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode())
                    uid_list = data.get("esearchresult", {}).get("idlist", [])
                    if uid_list:
                        sum_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=nuccore&id={uid_list[0]}&retmode=json"
                        with urllib.request.urlopen(urllib.request.Request(sum_url, headers={"User-Agent": "PhageScope/2.0"}), timeout=5) as resp2:
                            sum_data = json.loads(resp2.read().decode())
                            return sum_data.get("result", {}).get(uid_list[0], {}).get("organism")
            except Exception as e: 
                logger.debug(f"NCBI Entrez API 抓取失败 {accession}: {e}")
            return None
            
        return await asyncio.to_thread(sync_fetch)

    async def _silent_backfill(self, records: List[SeqRecord], out_dir: Path, threads: int):
        """将 Hypothetical Protein 提取并投喂给 PhageScope 专业库进行挽救性注释"""
        unknown_records = []
        for rec in records:
            for feat in rec.features:
                if feat.type == "CDS":
                    prod = feat.qualifiers.get("product", [""])[0].lower()
                    # 打捞未知蛋白
                    if not prod or "unknown" in prod or "hypothetical" in prod:
                        seq_ptr = feat.extract(rec.seq).translate(table=11, to_stop=True)
                        cid = feat.qualifiers.get("locus_tag", [feat.qualifiers.get("ID", ["unknown"])[0]])[0]
                        unknown_records.append(SeqRecord(seq_ptr, id=cid, description="unknown protein"))

        if not unknown_records: 
            return

        faa_path = out_dir / "unknowns_for_refinement.faa"
        win_tsv_out = faa_path.with_suffix(".tsv") 
        
        with open(faa_path, "w") as f:
            SeqIO.write(unknown_records, f, "fasta")

        project_root = Path(str(self.context.get("project_dir") or os.getcwd())).resolve()
        ps_db = project_root / "database" / "phagescope" / "phagescope_proteins"

        blast_cmd = [
            "blastp", "-query", WSLManager.to_wsl_path(str(faa_path)),
            "-db", WSLManager.to_wsl_path(str(ps_db)),
            "-out", WSLManager.to_wsl_path(str(win_tsv_out)),
            "-outfmt", "6 qseqid sseqid stitle evalue",
            "-max_target_seqs", "1", "-evalue", "1e-5", "-num_threads", str(threads)
        ]

        logger.info(f"[Annotation] 启动 PhageScope 专家库二次打捞 ({len(unknown_records)} records)...")
        ret = await self.runner.run_command(blast_cmd, silence_errors=True)

        updated = 0
        if ret == 0 and win_tsv_out.exists():
            hits = {}
            with open(win_tsv_out, "r", encoding="utf-8") as f:
                for row in csv.reader(f, delimiter="\t"):
                    if len(row) >= 4: hits[row[0]] = {"product": row[2], "evalue": row[3]}

            if hits:
                for rec in records:
                    for feat in rec.features:
                        if feat.type == "CDS":
                            cid = feat.qualifiers.get("locus_tag", [feat.qualifiers.get("ID", [""])[0]])[0]
                            if cid in hits:
                                h = hits[cid]
                                feat.qualifiers["product"] = [h["product"]]
                                feat.qualifiers["e_value"] = [h.get("evalue", "1e-5")]
                                feat.qualifiers["note"] = feat.qualifiers.get("note", []) + [f"Refined by PhageScope local BLASTp; E-value: {h['evalue']}"]
                                updated += 1

        faa_path.unlink(missing_ok=True)
        win_tsv_out.unlink(missing_ok=True)
        logger.info(f"[Annotation] 打捞完成: 成功挽救了 {updated}/{len(unknown_records)} 个未知蛋白的注释。")

    def _parse_checkv(self, quality_summary_path: Path) -> dict:
        """提取并格式化 CheckV 评估指标，并智能选取'冠军序列'"""
        result = {"checkv_quality": "Unknown", "completeness": "N/A", "contamination": "N/A", "warnings": [], "champion_id": None}
        quality_rank = {"High-quality": 1, "Medium-quality": 2, "Low-quality": 3, "Not-determined": 4, "Unknown": 5}
        
        try:
            best_score = 999
            best_row = None
            
            with open(quality_summary_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f, delimiter="\t")
                rows = list(reader)
                if not rows: return result
                
                for row in rows:
                    q = row.get("checkv_quality", "Unknown")
                    score = quality_rank.get(q, 5)
                    
                    # 冠军选取算法：优先看质量等级，再看完整度
                    try:
                        comp = float(row.get("completeness", 0) if row.get("completeness") != "NA" else 0)
                    except: comp = 0
                    
                    if score < best_score:
                        best_score = score
                        best_row = row
                    elif score == best_score and best_row:
                        # 如果等级并列，看完整度
                        try:
                            current_best_comp = float(best_row.get("completeness", 0) if best_row.get("completeness") != "NA" else 0)
                        except: current_best_comp = 0
                        if comp > current_best_comp:
                            best_row = row

                if best_row:
                    result.update({k: best_row.get(k, "N/A") for k in ["checkv_quality", "completeness", "contamination", "provirus"]})
                    result["gene_count"] = int(best_row.get("gene_count") or 0)
                    result["champion_id"] = best_row.get("contig_id")
                    
                    if int(best_row.get("host_genes") or 0) > 0: 
                        result["warnings"].append(f"️ 警告：冠军序列 {result['champion_id']} 检测到显著宿主污染。")
        except Exception as e: 
            logger.warning(f"解析 CheckV 报告或选取冠军时发生错误: {e}")
        return result

    def _checkv_quality_gate(self, quality_tsv: Path, input_fasta: Path, output_fasta: Path) -> int:
        """
        CheckV 质量关卡：基于 quality_summary.tsv 过滤输入 FASTA，
        只保留经 CheckV 确认含有病毒基因或达到中等以上质量的序列。
        
        保留条件 (满足任一即可):
          1. viral_genes > 0 (含有病毒特征基因)
          2. checkv_quality 为 High-quality / Medium-quality / Complete
          3. 序列被标记为 provirus (前噬菌体区段)
        
        Returns: 保留的序列数量。如果过滤后为空则回退到原始输入。
        """
        import csv
        
        if not quality_tsv.exists() or not input_fasta.exists():
            return 0
        
        # Step 1: 解析 CheckV 结果，标记通过质量关卡的 contig ID
        accepted_quality = {"High-quality", "Medium-quality", "Complete"}
        passed_ids = set()
        total_contigs = 0
        
        try:
            with open(quality_tsv, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f, delimiter="\t")
                for row in reader:
                    total_contigs += 1
                    contig_id = row.get("contig_id", "")
                    quality = row.get("checkv_quality", "Not-determined")
                    provirus = row.get("provirus", "No")
                    
                    try:
                        viral_genes = int(row.get("viral_genes", 0))
                    except (ValueError, TypeError):
                        viral_genes = 0
                    
                    # 判定条件
                    if viral_genes > 0:
                        passed_ids.add(contig_id)
                        logger.info(f"  [QualityGate] PASS (viral_genes={viral_genes}): {contig_id}")
                    elif quality in accepted_quality:
                        passed_ids.add(contig_id)
                        logger.info(f"  [QualityGate] PASS (quality={quality}): {contig_id}")
                    elif provirus == "Yes":
                        passed_ids.add(contig_id)
                        logger.info(f"  [QualityGate] PASS (provirus): {contig_id}")
                    else:
                        logger.debug(f"  [QualityGate] REJECT: {contig_id} (quality={quality}, viral_genes={viral_genes})")
        except Exception as e:
            logger.warning(f"[QualityGate] 解析 CheckV 质量报告失败: {e}")
            return 0
        
        if not passed_ids:
            logger.warning(f"[QualityGate] CheckV 未发现任何合格病毒序列，跳过过滤以保留原始数据")
            return 0
        
        # Step 2: 过滤 FASTA
        kept_records = []
        rejected_count = 0
        for rec in SeqIO.parse(str(input_fasta), "fasta"):
            if rec.id in passed_ids:
                kept_records.append(rec)
            else:
                rejected_count += 1
        
        if not kept_records:
            logger.warning(f"[QualityGate] 过滤后无剩余序列，回退到原始输入")
            return 0
        
        # Step 3: 写入过滤后的 FASTA
        with open(output_fasta, "w") as f:
            SeqIO.write(kept_records, f, "fasta")
        
        logger.info(
            f"[QualityGate] CheckV 质量关卡执行完毕: "
            f"{total_contigs} -> {len(kept_records)} 条 "
            f"(剔除 {rejected_count} 条非病毒垃圾碎片)"
        )
        return len(kept_records)

    async def _reorder_fasta_for_best_results(self, input_fa: Path, output_fa: Path, champion_id: str) -> bool:
        """重排 FASTA 文件，确保冠军序列排在第一位，以利于 Pharokka 绘图"""
        try:
            records = list(SeqIO.parse(input_fa, "fasta"))
            champion = None
            others = []
            
            for rec in records:
                # 兼容不同工具可能产生的 ID 差异
                if rec.id == champion_id or rec.id.split()[0] == champion_id:
                    champion = rec
                else:
                    others.append(rec)
            
            if champion:
                with open(output_fa, "w") as f:
                    SeqIO.write([champion] + others, f, "fasta")
                return True
        except Exception as e:
            logger.warning(f"重排 FASTA 失败: {e}")
        return False

    async def _run_bacphlip_prediction(self, gbk_path: Path) -> dict:
        """基于 BACPHLIP 的噬菌体生活史 (Lifestyle) 预测"""
        result = {"lifestyle": "Unknown", "temperate_score": 0.0, "virulent_score": 0.0}
        faa_path = gbk_path.parent / "proteins_for_bacphlip.faa"
        try:
            records = list(SeqIO.parse(gbk_path, "genbank"))
            with open(faa_path, "w") as f_out:
                for rec in records:
                    for feat in rec.features:
                        if feat.type == "CDS" and "translation" in feat.qualifiers:
                            locus = feat.qualifiers.get("locus_tag", [feat.qualifiers.get("ID", ["??"])[0]])[0]
                            # 数据清洗：替换掉 HMMER 不喜欢的非标准氨基酸
                            clean_translation = feat.qualifiers['translation'][0].upper().replace("MSE", "M").replace("B", "D").replace("Z", "E").replace("J", "L").replace("X", "A")
                            f_out.write(f">{locus}\n{clean_translation}\n")
            
            cmd = ["bacphlip", "-i", WSLManager.to_wsl_path(str(faa_path)), "--multi_fasta"]
            
            # 检测工具并执行预测
            if (await self.runner.run_command(["which", "bacphlip"], silence_errors=True)) == 0:
                if await self.runner.run_command(cmd, silence_errors=True) == 0:
                    bac_out = faa_path.with_suffix(".faa.bacphlip")
                    if bac_out.exists():
                        cols = bac_out.read_text().splitlines()[1].split("\t")
                        result["virulent_score"], result["temperate_score"] = float(cols[1]), float(cols[2])
                        result["lifestyle"] = "Temperate" if float(cols[2]) > 0.5 else "Virulent"
        except Exception as e: 
            logger.warning(f"[Bacphlip] 生活史预测失败: {e}")
            
        return result

    async def _run_apis_hmm_scan(self, records: List[SeqRecord], out_dir: Path) -> dict:
        """利用 HMM 配置文件扫描基因序列中的抗噬菌体防御系统"""
        hits = {}
        faa_path = out_dir / "proteins_for_apis.faa"
        project_root = Path(str(self.context.get("project_dir") or os.getcwd())).resolve()
        hmm_path = project_root / "database" / "phagescope" / "defense_systems" / "dbAPIS.hmm"
        
        if not hmm_path.exists(): 
            return hits

        try:
            with open(faa_path, "w") as f_out:
                for rec in records:
                    for feat in rec.features:
                        if feat.type == "CDS" and "translation" in feat.qualifiers:
                            locus = feat.qualifiers.get("locus_tag", [feat.qualifiers.get("ID", ["??"])[0]])[0]
                            f_out.write(f">{locus}\n{feat.qualifiers['translation'][0]}\n")
            
            # 若 HMMER 压库文件不存在，自动进行索引构建
            if not (hmm_path.parent / (hmm_path.name + ".h3m")).exists():
                await self.runner.run_command(["hmmpress", "-f", WSLManager.to_wsl_path(str(hmm_path))])

            domtbl = out_dir / "apis.domtbl"
            cmd = [
                "hmmscan", "--domtblout", WSLManager.to_wsl_path(str(domtbl)), 
                "--cpu", "4", "-E", "1e-5", 
                WSLManager.to_wsl_path(str(hmm_path)), 
                WSLManager.to_wsl_path(str(faa_path))
            ]
            
            if await self.runner.run_command(cmd, silence_errors=True) == 0 and domtbl.exists():
                with open(domtbl, "r") as f:
                    for line in f:
                        if line.startswith("#") or not line.strip(): continue
                        parts = line.split()
                        # HMMER 域表格列 12 是 E-value
                        if len(parts) >= 14 and float(parts[12]) < 1e-10:
                            hits[parts[3]] = {"system": parts[0], "evalue": float(parts[12])}
                
                # 再次回填入 SeqRecord
                for rec in records:
                    for feat in rec.features:
                        if feat.type == "CDS":
                            cid = feat.qualifiers.get("locus_tag", [feat.qualifiers.get("ID", [""])[0]])[0]
                            if cid in hits:
                                feat.qualifiers["product"] = [f"Antiphage defense system: {hits[cid]['system']}"]
                                feat.qualifiers["note"] = feat.qualifiers.get("note", []) + [f"Detected by dbAPIS (E-value: {hits[cid]['evalue']})"]
                                
            return hits
        except Exception as e: 
            logger.warning(f"dbAPIS HMM 扫描失败: {e}")
            return hits
        finally: 
            faa_path.unlink(missing_ok=True)