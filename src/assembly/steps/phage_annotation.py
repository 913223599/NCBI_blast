
import os
import re
import shutil
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
from ..core.base import BaseAssemblyStep
from ...workbench.models.tool_config import ToolConfig

logger = logging.getLogger("Assembly.PhageAnnotationStep")

class PhageAnnotationStep(BaseAssemblyStep):
    """
    噬菌体专项注释步骤 (基于 Pharokka + Phold AI)
    集成 HMM 敏感比对与 AI 结构功能预测
    """
    async def execute(self) -> bool:
        self.status = "running"
        
        # 🔗 0. 初始化项目环境
        win_project_root = self.context.get("project_dir", os.getcwd())
        fasta = self.context.get("assembly_fasta")
        if not fasta:
             self.status = "failed"
             return False

        # 🔗 1. 环境自愈 (强制建立无空格路径映射)
        # 动态获取当前盘符，避免硬编码 /mnt/f
        win_path_obj = Path(win_project_root).resolve()
        drive_letter = win_path_obj.drive.replace(":", "").lower()
        
        # 建立基于当前盘符的临时工作根目录
        safe_root = f"/mnt/{drive_letter}/.ncbi_blast_wsl_tmp"
        
        # 获取标准 /mnt 源路径
        rel_project_path = str(win_path_obj.relative_to(win_path_obj.anchor)).replace("\\", "/")
        mnt_project_root = f"/mnt/{drive_letter}/{rel_project_path}"
        
        # 建立 symlink 以避开 Windows 路径中的空格问题
        await self.runner.run_command(["bash", "-c", f"ln -sfT '{mnt_project_root}' {safe_root}"])
        
        # 💡 [自愈增强] 路径转换助手：将路径映射为 WSL 安全路径 (处理 Path 对象与正反斜杠)
        def to_safe(p):
            p_str = str(p).replace("\\", "/")
            root_str = str(win_project_root).replace("\\", "/")
            return p_str.replace(root_str, safe_root)

        # 🚀 自动化补丁：由于我们更新了安装脚本，此处强制对缺失的小工具执行一次增量自愈
        missing_mandatory = []
        if (await self.runner.run_command(["which", "prodigal-gv"])) != 0: missing_mandatory.append("prodigal-gv")
        
        if missing_mandatory:
            logger.info(f"🧬 发现关键补丁缺失: {missing_mandatory}, 正在执行增量自愈...")
            # 💡 关键修复：使用无空格的 safe_root 路径来调用脚本
            setup_env_wsl = f"{safe_root}/scripts/setup_assembly_env.sh"
            await self.runner.run_command(["bash", setup_env_wsl])
        pharokka_db_default = "/opt/pharokka_db"
        if (await self.runner.run_command(["test", "-d", pharokka_db_default])) != 0:
            if self.on_progress: self.on_progress(2, "初始化 Pharokka 数据库链接...")
            setup_script_wsl = f"{mnt_project_root}/scripts/setup_pharokka.sh"
            await self.runner.run_command(["bash", setup_script_wsl])

        # 🔗 2. 路径映射与性能计算
        win_work_path = self.get_working_dir()
        safe_fasta = to_safe(fasta)
        safe_work_dir = to_safe(win_work_path)
        
        # 建立物理输出子目录 (Windows侧创建，WSL侧通过映射访问)
        win_pharokka_out = win_work_path / "pharokka_res"
        win_phold_out = win_work_path / "phold_res"
        win_pharokka_out.mkdir(parents=True, exist_ok=True)
        win_phold_out.mkdir(parents=True, exist_ok=True)

        try:
            # 🚀 调优：使用 Python 原生 os 获取系统核心数
            sys_cores = os.cpu_count() or 8
            threads = max(1, int(sys_cores * 0.9))
            logger.info(f"[Annotation] 探测到物理/逻辑核心数: {sys_cores}, 分配注释线程: {threads}")
        except Exception as e:
            logger.warning(f"[Annotation] 核心数挂载失败，采取保底 8 线程。原因: {e}")
            threads = 8

        # 🔗 3. CheckV 基因组完整性评估 (质量阔门)
        if self.on_progress: self.on_progress(5, "正在评估基因组完整性 (CheckV)...")
        try:
            # 前置检查: 确认 checkv 可用且数据库已部署
            ret_which = await self.runner.run_command(["which", "checkv"], cwd=safe_work_dir)
            ret_db = await self.runner.run_command(["test", "-d", "/opt/checkv-db"], cwd=safe_work_dir)
            if ret_which != 0 or ret_db != 0:
                logger.info("[CheckV] checkv 未安装或数据库未部署，跳过质量评估 (可运行 scripts/setup_assembly_env.sh 安装)")
                self.context.update("checkv", {"checkv_quality": "Skipped", "error": "Not installed"})
            else:
                checkv_dir = win_work_path / "checkv_res"
                checkv_dir.mkdir(parents=True, exist_ok=True)
                
                checkv_cmd = [
                    "checkv", "end_to_end",
                    safe_fasta,
                    to_safe(checkv_dir),
                    "-t", str(threads), "-d", "/opt/checkv-db"
                ]
                ret_checkv = await self.runner.run_command(checkv_cmd, cwd=safe_work_dir)
                
                # 解析 CheckV 质量报告
                quality_summary = checkv_dir / "quality_summary.tsv"
                checkv_result = self._parse_checkv(quality_summary)
                self.context.update("checkv", checkv_result)
                
                quality_tier = checkv_result.get("checkv_quality", "Unknown")
                completeness = checkv_result.get("completeness", "N/A")
                logger.info(f"[CheckV] 质量评级: {quality_tier} | 完整度: {completeness}")
                
                if self.on_progress: self.on_progress(8, f"CheckV 评估结果: {quality_tier} ({completeness})")
        except Exception as e:
            logger.warning(f"[CheckV] 质量评估失败 (非致命，继续注释): {e}")
            self.context.update("checkv", {"checkv_quality": "Skipped", "error": str(e)})

        # 🔗 4. 执行 Pharokka (带超细粒度进度反馈)
        if self.on_progress: self.on_progress(10, "启动 Pharokka 深度注释流程...")
        
        def pharokka_handler(line: str):
            msg = line.strip()
            if "Phanotate" in msg: self.on_progress(12, "正在进行基因预测 (Phanotate)...")
            elif "MMseqs2" in msg and "PHROGs" in msg: self.on_progress(18, "检索核心蛋白库 (PHROGs)...")
            elif "VFDB" in msg: self.on_progress(25, "检索毒力因子库 (VFDB)...")
            elif "CARD" in msg: self.on_progress(32, "检索耐药基因库 (CARD)...")
            elif "PHROG HMM" in msg: self.on_progress(38, "PHROG HMM 深度比过 (敏感模式)...")
            elif "HMMER" in msg: self.on_progress(42, "HMMER 结构域分析...")
            elif "tRNAscan-SE" in msg: self.on_progress(45, "正在扫描 tRNA 基因...")
            elif "Aragorn" in msg: self.on_progress(48, "正在扫描 tmRNA 基因...")
            elif "CRT" in msg: self.on_progress(50, "正在进行 CRISPR 阵列分析...")
            elif "InTandem" in msg: self.on_progress(52, "正在检测串联重复序列...")
            elif "Dnaapler" in msg: self.on_progress(55, "正在校想起始位点 (Dnaapler)...")
            elif "Pharokka plotting" in msg: self.on_progress(58, "Pharokka 正在生成初步图谱...")

        # 转换为安全 WSL 路径
        safe_pharokka_out = to_safe(win_pharokka_out)
        safe_phold_out = to_safe(win_phold_out)

        pharokka_cmd = [
            "pharokka.py", "-i", safe_fasta, "-o", safe_pharokka_out,
            "-d", "/opt/pharokka_db", "-t", str(threads), "-p", "PHAGE",
            "--dnaapler", "--sensitivity", "8", "-f"
        ]
        await self.runner.run_command(pharokka_cmd, cwd=safe_work_dir, on_output=pharokka_handler)

        # 🔗 4. 执行 Phold AI 结构预测 (带 GPU 状态反馈)
        if self.on_progress: self.on_progress(60, "Pharokka 完成，进入 AI 结构增强模式...")
        
        def phold_handler(line: str):
            msg = line.strip()
            if "cuda" in msg.lower(): self.on_progress(61, "AI 显卡驱动已激活 (CUDA 加速)...")
            elif "Predicting 3Di" in msg: self.on_progress(65, "AI 神经网络正在预测 3Di 指标...")
            elif "MMseqs2" in msg and "functional" in msg: self.on_progress(75, "AI 功能一致性比对中...")
            elif "Foldseek" in msg: self.on_progress(82, "全球蛋白结构库搜索中...")
            elif "annotating_cds" in msg or "Annotating" in msg: self.on_progress(88, "集成 AI 预测至原始产物...")

        safe_gbk_for_phold = to_safe(win_pharokka_out / "PHAGE.gbk")
        phold_cmd = [
            "phold", "run", "-i", safe_gbk_for_phold, "-o", safe_phold_out,
            "-d", "/opt/phold_db", "-t", str(threads), "-f", "--sensitivity", "9.5"
        ]
        ret_phold = await self.runner.run_command(phold_cmd, cwd=safe_work_dir, on_output=phold_handler)

        # 🔗 5. 产物确认与状态标记 (在 Windows 层面验证)
        # 优先使用 Phold 的增强产物，如失败则退而求其次使用 Pharokka 的原始产物
        win_final_gbk = win_phold_out / "phold.gbk" if ret_phold == 0 else win_pharokka_out / "PHAGE.gbk"
        
        if win_final_gbk.exists():
            # 🔗 6. 流水线自动增广：静默比对未知蛋白并回填
            if self.on_progress: self.on_progress(95, "正在扫描未知功能蛋白，准备进行最终补全...")
            try:
                await self._silent_backfill(win_final_gbk, threads)
            except Exception as e:
                logger.warning(f"[Annotation] Silent backfill failed: {e}")
            
            if self.on_progress: self.on_progress(100, "注释任务全部执行完成")

            # 🔗 7. 渲染全景基因组圈图
            if self.on_progress: self.on_progress(92, "正在融合多源注释渲染基因组圈图...")
            try:
                # 显式建立输出目录
                win_plot_dir = win_work_path / "phage_plot"
                win_plot_dir.mkdir(parents=True, exist_ok=True)
                
                # 准备 WSL 安全路径
                safe_plot_dir = to_safe(win_plot_dir)
                safe_gff = to_safe(win_pharokka_out / "PHAGE.gff")
                safe_gbk = win_final_gbk
                
                plot_cmd = [
                    "pharokka_plotter.py", "-i", safe_fasta, 
                    "--gff", safe_gff, "--genbank", to_safe(safe_gbk),
                    "-o", safe_plot_dir, "-f",
                    "-n", "Phage_Integrated_Genome_Map", 
                    "-p", "phage_plot", 
                    "-t", "Phage Integrated Phold-AI Annotation Map"
                ]
                await self.runner.run_command(plot_cmd, cwd=safe_work_dir)
                
                png_files = list(win_plot_dir.glob("*.png"))
                if png_files:
                    final_png = sorted(png_files, key=lambda x: x.stat().st_size, reverse=True)[0]
                    self.context.update("plot_file", final_png)
            except Exception as e:
                logger.warning(f"[Annotation] 圈图渲染过程发生异常: {e}")

            # 🔗 8. 安全性审计 — 双层架构
            if self.on_progress: self.on_progress(97, "正在执行安全性审计 (直接检测 + 参考推断)...")
            try:
                # ─── Tier 1: 直接扫描用户 CDS 注释 (基于实际序列的证据) ───
                anno_tsv = next(win_work_path.glob("Integrated_Final_Annotations.tsv"), None)
                direct_scan = self._direct_safety_scan(anno_tsv)

                # ─── Tier 2: PhageScope 参考元数据查表 (辅助推断) ───
                mash_hit_file = win_pharokka_out / "PHAGE_top_hits_mash_inphared.tsv"
                ref_audit = self._mine_phagescope_metadata(mash_hit_file)

                # ─── Tier 3: 深度宿主溯源挖掘 (基于 300万+ 序列指纹库) ───
                # 💡 核心修复：使用动态 fasta 变量 (polished_assembly.fasta)，而不是硬编码路径
                host_results = await self._deep_host_prediction(fasta, threads)
                self.context.update("host_prediction", host_results)

                # ─── 基于全基因组 Prophage 比对，判定噬菌体生活史 (Temperate 判断) ───
                has_strong_prophage = False
                for hit in host_results.get("top_hits", []):
                    if "Prophage" in hit.get("db_source", "") and hit.get("confidence") == "High":
                        has_strong_prophage = True
                        break
                
                if has_strong_prophage:
                    ref_audit["lifestyle"] = "Temperate (Provirus - High Confidence)"

                # ─── 合并分析结果 ───
                audit_data = self._merge_safety_audit(direct_scan, ref_audit)
                
                # 注入深度宿主预测至最终审计字典 (用于报告生成)
                audit_data["host_prediction_enhanced"] = host_results
                self.context.update("phagescope_audit", audit_data)

                # 同步分类信息
                existing_class = self.context.get("classification") or {}
                existing_class.update(audit_data.get("taxonomy_info", {}))
                self.context.update("classification", existing_class)

                logger.info(
                    f"✅ 安全审计完成: "
                    f"直接检测 AMR={len(direct_scan.get('amr_genes',[]))} VF={len(direct_scan.get('virulent_factors',[]))} "
                    f"ACR={direct_scan.get('anti_crispr','N/A')} | "
                    f"Safety={audit_data['safety_status']}"
                )
            except Exception as e:
                logger.warning(f"[Annotation] Safety audit failed: {e}")

            # 🔗 8.5 自动化硬核生信指标审计 (GC%, Density, tRNA Details)
            if self.on_progress: self.on_progress(99, "正在计算硬核生信指标 (GC%, 基因密度, tRNA 谱系)...")
            try:
                from Bio import SeqIO
                from Bio.SeqUtils import gc_fraction
                
                total_len = 0
                total_gc = 0
                cds_len = 0
                trna_list = []
                is_circular = "Linear"
                
                for rec in SeqIO.parse(win_final_gbk, "genbank"):
                    total_len += len(rec.seq)
                    total_gc = gc_fraction(rec.seq) * 100
                    if "circular" in rec.annotations.get("topology", "").lower():
                        is_circular = "Circular"
                    
                    for feat in rec.features:
                        if feat.type == "CDS":
                            cds_len += int(feat.location.end - feat.location.start)
                        elif feat.type == "tRNA":
                            note = feat.qualifiers.get("note", ["--"])[0]
                            trna_list.append(note.replace("tRNA-", ""))

                metrics = {
                    "gc_content": f"{total_gc:.2f}%",
                    "coding_density": f"{(cds_len/total_len*100):.2f}%" if total_len > 0 else "0%",
                    "topology": is_circular,
                    "tRNA_details": ", ".join(sorted(set(trna_list))) if trna_list else "None"
                }
                self.context.update("genomic_metrics", metrics)
                logger.info(f"🧬 生信审计完成: GC={metrics['gc_content']}, Density={metrics['coding_density']}")
            except Exception as e:
                logger.warning(f"[Annotation] Hardcore metrics calculation failed: {e}")

            # 将产物路径存入上下文
            self.context.update("annotation_dir", win_final_gbk.parent)
            self.context.update("gbk_file", win_final_gbk)
            self.status = "completed"
            if self.on_progress: self.on_progress(100, "深度注释及 PhageScope 专家审计成功")
            return True

        self.status = "failed"
        return False
    def _direct_safety_scan(self, annotation_tsv: Path) -> dict:
        """
        Tier 1: 基于序列比对的安全性直接检测。
        从用户注释结果提取 CDS 蛋白序列，blastp 比对本地 PhageScope 蛋白库
        (phagescope_proteins, 105万条序列)，然后将命中蛋白 ID 交叉查询
        AMR/VF/Anti-CRISPR 元数据表，判定安全性。
        """
        import csv
        import subprocess

        result = {
            "amr_genes": [],
            "virulent_factors": [],
            "anti_crispr": "Not Detected",
            "anti_crispr_genes": [],
            "lysogeny_markers": [],
        }

        if not annotation_tsv or not annotation_tsv.exists():
            logger.warning("[SafetyScan] 注释文件未找到，跳过直接安全检测")
            return result

        # ─── 1. 从注释结果提取 CDS 蛋白序列 ───
        query_faa = annotation_tsv.parent / "query_proteins.faa"
        try:
            n_proteins = 0
            with open(annotation_tsv, "r", encoding="utf-8") as f_in, \
                 open(query_faa, "w", encoding="utf-8") as f_out:
                reader = csv.DictReader(f_in, delimiter="\t")
                for row in reader:
                    if row.get("Type") == "CDS" and row.get("Translation"):
                        cds_id = row.get("ID", f"CDS_{n_proteins}")
                        product = row.get("Product", "")
                        f_out.write(f">{cds_id} {product}\n{row['Translation']}\n")
                        n_proteins += 1
            logger.info(f"[SafetyScan] 提取 {n_proteins} 条 CDS 蛋白序列")
        except Exception as e:
            logger.warning(f"[SafetyScan] 蛋白序列提取失败: {e}")
            return result

        if n_proteins == 0:
            return result

        # ─── 2. 定位本地 PhageScope 蛋白库 ───
        project_root = Path(self.context.get("project_dir", os.getcwd())).resolve()
        phagescope_db = project_root / "database" / "phagescope"
        blast_db = phagescope_db / "phagescope_proteins"
        meta_base = phagescope_db / "metadata"

        # 检查 BLAST 索引是否存在
        if not blast_db.with_suffix(".psq").exists():
            logger.warning(f"[SafetyScan] PhageScope BLAST 数据库不存在: {blast_db}.psq")
            return result

        # ─── 3. 构建安全蛋白 ID 索引 (从元数据表) ───
        amr_index = {}   # protein_id -> CARD hit description
        vf_index = {}    # protein_id -> VFDB hit description
        acr_index = {}   # protein_id -> source

        for tsv_file in (meta_base / "amr").glob("*.tsv"):
            try:
                with open(tsv_file, encoding="utf-8") as mf:
                    for row in csv.DictReader(mf, delimiter="\t"):
                        pid = row.get("Protein_id", "")
                        if pid:
                            amr_index[pid] = row.get("Aligned_Protein_in_CARD", "")
            except Exception:
                pass

        for tsv_file in (meta_base / "virulent_factor").glob("*.tsv"):
            try:
                with open(tsv_file, encoding="utf-8") as mf:
                    for row in csv.DictReader(mf, delimiter="\t"):
                        pid = row.get("Protein_id", "")
                        if pid:
                            vf_index[pid] = row.get("Aligned_Protein_in_VFDB", "")
            except Exception:
                pass

        for tsv_file in (meta_base / "anti_crispr").glob("*.tsv"):
            try:
                with open(tsv_file, encoding="utf-8") as mf:
                    for row in csv.DictReader(mf, delimiter="\t"):
                        pid = row.get("Protein_ID", "")
                        if pid:
                            acr_index[pid] = row.get("Source", "")
            except Exception:
                pass

        logger.info(
            f"[SafetyScan] 安全蛋白索引: AMR={len(amr_index)}, "
            f"VF={len(vf_index)}, ACR={len(acr_index)}"
        )

        # ─── 4. blastp 比对 PhageScope 蛋白库 ───
        def to_wsl(p: Path) -> str:
            s = str(p.resolve()).replace("\\", "/")
            if len(s) >= 2 and s[1] == ":":
                return f"/mnt/{s[0].lower()}/{s[2:].lstrip('/')}"
            return s

        out_file = annotation_tsv.parent / "phagescope_blast_hits.tsv"
        wsl_db_dir = to_wsl(phagescope_db)
        wsl_query = to_wsl(query_faa)
        wsl_out = to_wsl(out_file)

        # BLAST -db 不支持路径中的空格，通过 symlink 解决
        blast_script = (
            f'ln -sf "{wsl_db_dir}" /tmp/phagescope_db && '
            f'blastp '
            f'-query "{wsl_query}" '
            f'-db /tmp/phagescope_db/phagescope_proteins '
            f'-out "{wsl_out}" '
            f'-outfmt "6 qseqid sseqid pident length evalue bitscore" '
            f'-evalue 1e-10 -max_target_seqs 5 -num_threads 4'
        )
        cmd = ["wsl", "-d", "Ubuntu", "--", "bash", "-c", blast_script]

        try:
            logger.info("[SafetyScan] 正在运行 blastp vs PhageScope 蛋白库 (105万条)...")
            subprocess.run(cmd, timeout=300, capture_output=True, text=True)
        except Exception as e:
            logger.warning(f"[SafetyScan] blastp 运行异常: {e}")
            return result

        # ─── 5. 解析命中结果并交叉查询安全元数据 ───
        if out_file.exists():
            with open(out_file, "r", encoding="utf-8") as f:
                for line in f:
                    cols = line.strip().split("\t")
                    if len(cols) < 6:
                        continue

                    cds_id = cols[0]
                    target_id = cols[1]  # PhageScope 蛋白 ID
                    identity = float(cols[2])
                    evalue = cols[4]
                    bitscore = float(cols[5])

                    hit_info = {
                        "cds_id": cds_id,
                        "target_id": target_id,
                        "identity": identity,
                        "evalue": evalue,
                        "bitscore": bitscore,
                        "evidence": "sequence_alignment",
                    }

                    # 交叉查询 AMR 表
                    if target_id in amr_index:
                        hit_info["description"] = amr_index[target_id]
                        result["amr_genes"].append(hit_info)

                    # 交叉查询 VF 表
                    if target_id in vf_index:
                        hit_info_vf = dict(hit_info)
                        hit_info_vf["description"] = vf_index[target_id]
                        result["virulent_factors"].append(hit_info_vf)

                    # 交叉查询 Anti-CRISPR 表
                    if target_id in acr_index:
                        hit_info_acr = dict(hit_info)
                        hit_info_acr["source"] = acr_index[target_id]
                        result["anti_crispr_genes"].append(hit_info_acr)

        if result["anti_crispr_genes"]:
            n = len(result["anti_crispr_genes"])
            result["anti_crispr"] = f"Detected ({n} Acr proteins)"

        # ─── 6. 溶源性标志扫描 (从注释文本) ───
        LYSOGENY_KEYWORDS = [
            "integrase", "recombinase", "excisionase",
            "repressor", "transposase", "lysogeny", "prophage",
        ]
        try:
            with open(annotation_tsv, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f, delimiter="\t")
                for row in reader:
                    text = " ".join([
                        row.get("Product", ""),
                        row.get("Function", ""),
                    ]).lower()
                    for kw in LYSOGENY_KEYWORDS:
                        if kw in text:
                            result["lysogeny_markers"].append({
                                "cds_id": row.get("ID", "?"),
                                "product": row.get("Product", ""),
                                "keyword": kw,
                            })
                            break
        except Exception:
            pass

        logger.info(
            f"[SafetyScan] 序列比对检测完成: "
            f"AMR={len(result['amr_genes'])}, "
            f"VF={len(result['virulent_factors'])}, "
            f"ACR={len(result['anti_crispr_genes'])}, "
            f"Lysogeny={len(result['lysogeny_markers'])}"
        )
        return result

    def _merge_safety_audit(self, direct: dict, reference: dict) -> dict:
        """
        合并双层审计结果:
        - direct: Tier 1 直接检测 (基于用户 CDS 注释, 高置信)
        - reference: Tier 2 参考推断 (基于 PhageScope 元数据, 辅助)

        直接检测结果优先级高于参考推断。
        """
        merged = dict(reference)  # 以参考数据为基础 (含 taxonomy, lifestyle 等)

        # ─── AMR: 直接检测优先 ───
        direct_amr = direct.get("amr_genes", [])
        ref_amr = reference.get("amr_genes", [])
        merged["amr_genes_direct"] = direct_amr
        merged["amr_genes_reference"] = ref_amr
        # 合并为统一列表
        merged["amr_genes"] = direct_amr if direct_amr else ref_amr

        # ─── VF: 直接检测优先 ───
        direct_vf = direct.get("virulent_factors", [])
        ref_vf = reference.get("virulent_factors", [])
        merged["virulent_factors_direct"] = direct_vf
        merged["virulent_factors_reference"] = ref_vf
        merged["virulent_factors"] = direct_vf if direct_vf else ref_vf

        # ─── Anti-CRISPR: 直接检测优先 ───
        direct_acr = direct.get("anti_crispr", "Not Detected")
        ref_acr = reference.get("anti_crispr", "Not Detected")
        if "Detected" in str(direct_acr):
            merged["anti_crispr"] = direct_acr
            merged["anti_crispr_evidence"] = "direct"
        elif "Detected" in str(ref_acr):
            merged["anti_crispr"] = ref_acr
            merged["anti_crispr_evidence"] = "reference"
        else:
            merged["anti_crispr"] = "Not Detected"
            merged["anti_crispr_evidence"] = "none"

        # ─── 溶源性标志 ───
        merged["lysogeny_markers"] = direct.get("lysogeny_markers", [])

        # ─── 综合安全评级 ───
        has_amr = bool(merged["amr_genes"])
        has_vf = bool(merged["virulent_factors"])
        has_acr = "Detected" in str(merged["anti_crispr"])
        has_lysogeny = bool(merged["lysogeny_markers"])

        if has_amr and has_vf:
            merged["safety_status"] = "Caution (AMR + VF Detected)"
        elif has_amr:
            merged["safety_status"] = "Warning (AMR Detected)"
        elif has_vf:
            merged["safety_status"] = "Warning (VF Detected)"
        elif has_lysogeny:
            merged["safety_status"] = "Review (Lysogeny Markers Found)"
        else:
            merged["safety_status"] = "Secure (Clear)"

        return merged

    def _mine_phagescope_metadata(self, mash_hit_path: Path) -> dict:
        """多维挖掘 PhageScope 专家知识库"""
        import csv
        audit = {
            "lifestyle": "Unknown",
            "host_origin": "--",
            "environment": "Unknown",
            "safety_status": "Secure (Clear)",
            "amr_genes": [],
            "virulent_factors": [],
            "anti_crispr": "Not Detected",
            "taxonomy_info": {}
        }
        
        if not mash_hit_path.exists(): return audit

        try:
            # 1. 获取 Top Hit ID 并计算相似度
            top_id = ""
            with open(mash_hit_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                if len(lines) > 1:
                    cols = lines[1].split("\t")
                    top_id = cols[1].strip()
                    dist = float(cols[0].strip()) if cols[0].strip() else 1.0
                    similarity = max(0, min(100, (1.0 - dist) * 100))
                    
                    audit["taxonomy_info"] = {
                        "top_hit_id": top_id,
                        "top_hit_name": cols[5].strip(),
                        "similarity": f"{similarity:.2f}%",
                        "Classification": cols[6].strip(),
                        "Genus": cols[20].strip(),
                        "Family": cols[22].strip(),
                        "Host": cols[18].strip()
                    }
                    audit["host_origin"] = cols[18].strip()

            if not top_id: return audit

            project_root = Path(self.context.get("project_dir", os.getcwd())).resolve()
            meta_base = project_root / "database" / "phagescope" / "metadata"

            # 2. 生活史、宿主与【环境溯源】深度匹配
            phage_meta_dir = meta_base / "phage"
            for f_name in ["refseq_phage_meta_data.tsv", "genbank_phage_meta_data.tsv"]:
                p = phage_meta_dir / f_name
                if not p.exists(): continue
                with open(p, "r", encoding="utf-8") as mf:
                    reader = csv.DictReader(mf, delimiter="\t")
                    for row in reader:
                        if row.get("Phage_ID") == top_id or row.get("Accession") == top_id:
                            audit["lifestyle"] = row.get("Lifestyle", "Unknown")
                            audit["host_origin"] = row.get("Host", audit["host_origin"])
                            audit["environment"] = row.get("Isolation_source") or row.get("Environment", "Unknown")
                            break
                    if audit["lifestyle"] != "Unknown": break

            # 3. 抗生素耐药 (AMR) 审计
            # 实际文件: Genbank_antimicrobial_resistance_gene_data.tsv, RefSeq_...
            # 表结构: Protein_id | Aligned_Protein_in_CARD | Phage_id | Phage_Source
            amr_dir = meta_base / "amr"
            if amr_dir.exists():
                for amr_file in amr_dir.glob("*.tsv"):
                    try:
                        with open(amr_file, "r", encoding="utf-8") as mf:
                            reader = csv.DictReader(mf, delimiter="\t")
                            for row in reader:
                                if row.get("Phage_id") == top_id:
                                    hit = row.get("Aligned_Protein_in_CARD", "")
                                    audit["amr_genes"].append(hit)
                                    audit["safety_status"] = "Warning (AMR Detected)"
                    except Exception as e:
                        logger.debug(f"[PhageScope] AMR scan {amr_file.name}: {e}")

            # 4. 毒力因子 (VF) 审计
            # 实际文件: Genbank_virulent_factor_data.tsv, RefSeq_...
            # 表结构: Protein_id | Aligned_Protein_in_VFDB | Phage_id | Phage_Source
            vf_dir = meta_base / "virulent_factor"
            if vf_dir.exists():
                for vf_file in vf_dir.glob("*.tsv"):
                    try:
                        with open(vf_file, "r", encoding="utf-8") as mf:
                            reader = csv.DictReader(mf, delimiter="\t")
                            for row in reader:
                                if row.get("Phage_id") == top_id:
                                    hit = row.get("Aligned_Protein_in_VFDB", "")
                                    audit["virulent_factors"].append(hit)
                                    if "Warning" not in audit["safety_status"]:
                                        audit["safety_status"] = "Warning (VF Detected)"
                                    else:
                                        audit["safety_status"] = "Caution (AMR+VF)"
                    except Exception as e:
                        logger.debug(f"[PhageScope] VF scan {vf_file.name}: {e}")

            # 5. Anti-CRISPR 检测
            # 实际文件: genbank_phage_anticrispr_protein_meta_data.tsv, refseq_..., phagesdb_...
            # 表结构: Phage_ID | Protein_ID | Source | Phage_source
            acr_dir = meta_base / "anti_crispr"
            acr_proteins = []
            if acr_dir.exists():
                for acr_file in acr_dir.glob("*.tsv"):
                    try:
                        with open(acr_file, "r", encoding="utf-8") as mf:
                            reader = csv.DictReader(mf, delimiter="\t")
                            for row in reader:
                                if row.get("Phage_ID") == top_id:
                                    acr_proteins.append(row.get("Protein_ID", ""))
                    except Exception as e:
                        logger.debug(f"[PhageScope] ACR scan {acr_file.name}: {e}")
            if acr_proteins:
                audit["anti_crispr"] = f"Detected ({len(acr_proteins)} Acr proteins)"
                audit["anti_crispr_proteins"] = acr_proteins

            # 6. [新增] 蛋白深层理化与功能分类挖掘 (Deep Protein Audit)
            logger.info(f"[PhageScope] 正在为 {top_id} 提取深层蛋白功能谱...")
            p_meta_dir = meta_base / "annotated_protein"
            protein_map = {}
            for f_name in ["refseq_phage_annotated_protein_meta_data.tsv", "genbank_phage_annotated_protein_meta_data.tsv"]:
                p_file = p_meta_dir / f_name
                if not p_file.exists(): continue
                
                with open(p_file, "r", encoding="utf-8") as pf:
                    # 注意：这些表很大，我们采用流式搜索以保持内存效率
                    reader = csv.DictReader(pf, delimiter="\t")
                    for row in reader:
                        if row.get("Phage_ID") == top_id:
                            p_id = row.get("Protein_ID")
                            # 稳定性逻辑评估
                            try:
                                inst_idx = float(row.get("Instability_index", 999))
                                stability_label = "Stable" if inst_idx <= 40 else "Unstable"
                            except:
                                stability_label = "Unknown"

                            protein_map[p_id] = {
                                "category": row.get("Protein_classification", "unknown"),
                                "pi": row.get("Isoelectric_point", "--"),
                                "stability": f"{stability_label} ({row.get('Instability_index', '--')})",
                                "mw": row.get("Molecular_weight", "--")
                            }
                    if protein_map: break
            audit["protein_functional_map"] = protein_map

        except Exception as e:
            logger.warning(f"[PhageScope Audit] Process error: {e}")
            
        return audit

    async def _deep_host_prediction(self, fasta_path: Path, threads: int) -> dict:
        """
        基于分块 Mash 库的低内存宿主指认
        策略：先查小库(Phage 17K)，再逐块查大库(Prophage chunk_*.msh)
        每块查完释放内存，峰值内存控制在 ~3GB
        """
        result = {
            "top_hits": [],
            "status": "No database found",
            "source": "Local Phage/Prophage Chunked Fingerprints"
        }

        db_dir = ToolConfig.DATABASE_ROOT
        from ..env.wsl_manager import WSLManager
        safe_fasta = WSLManager.to_wsl_path(str(fasta_path))

        # 构建数据库列表：小库 + 分块大库
        dbs = []
        small_db = db_dir / "Phage.17770sequence.fasta.gz.msh"
        if small_db.exists():
            dbs.append(("Phage.17K", small_db))

        # 自动发现分块索引 (chunk_01.msh ~ chunk_XX.msh)
        chunk_files = sorted(db_dir.glob("chunk_*.msh"))
        for cf in chunk_files:
            dbs.append((f"Prophage.{cf.stem}", cf))

        # 兼容旧版：如果没有分块但有完整大库，退回使用完整库
        if not chunk_files:
            full_db = db_dir / "Prophage.3281395sequence.fasta.gz.msh"
            if full_db.exists():
                dbs.append(("Prophage.Full", full_db))

        if not dbs:
            return result

        all_hits = []
        total_dbs = len(dbs)
        for idx, (db_name, db_path) in enumerate(dbs, 1):
            safe_db = WSLManager.to_wsl_path(str(db_path))
            cmd = ["mash", "dist", "-p", str(threads), safe_db, safe_fasta]

            if self.on_progress:
                self.on_progress(
                    97, f"Host prediction: querying {db_name} ({idx}/{total_dbs})..."
                )
            logger.info(f"[HostPred] Chunk {idx}/{total_dbs}: {db_name}")

            output = []
            def capture_out(line): output.append(line)

            ret = await self.runner.run_command(cmd, on_output=capture_out)
            if ret == 0:
                # 只保留每个块的 Top 20（避免内存膨胀）
                chunk_hits = []
                for line in output:
                    cols = line.strip().split("\t")
                    if len(cols) >= 5:
                        try:
                            dist = float(cols[2])
                        except ValueError:
                            continue
                        if dist < 0.10:
                            # 估算置信度: distance < 0.05 -> High, < 0.10 -> Med
                            if dist < 0.05:
                                conf_level = "High"
                            else:
                                conf_level = "Medium"
                                
                            chunk_hits.append({
                                "accession": cols[0].split("|")[0].split(".")[0],
                                "full_id": cols[0],
                                "distance": dist,
                                "similarity": f"{(1.0 - dist)*100:.2f}%",
                                "confidence": conf_level,
                                "p_value": cols[3],
                                "hashes": cols[4],
                                "db_source": db_name
                            })
                # 每块只取前 20，释放余下数据
                chunk_hits.sort(key=lambda x: x["distance"])
                all_hits.extend(chunk_hits[:20])
                del output, chunk_hits

            logger.info(f"[HostPred] Chunk {idx}/{total_dbs} done, cumulative hits: {len(all_hits)}")

        if not all_hits:
            result["status"] = "No significant match found"
            return result

        # 全局排序，取前 50
        all_hits.sort(key=lambda x: x["distance"])
        top_candidates = all_hits[:50]

        # 加载本地映射表补全描述
        meta_cache = {}
        for tsv_name in ["Phage.17770sequence.metadata.tsv", "Prophage.3281395sequence.metadata.tsv"]:
            tsv_path = db_dir / tsv_name
            if tsv_path.exists():
                meta_cache[tsv_name] = tsv_path

        for cand in top_candidates:
            cand["description"] = "Unknown"
            for tsv_name, tsv_path in meta_cache.items():
                try:
                    with open(tsv_path, "r", encoding="utf-8") as f:
                        for line in f:
                            if cand["full_id"] in line:
                                parts = line.strip().split("\t")
                                if len(parts) > 1 and parts[1] != "Unknown":
                                    cand["description"] = parts[1]
                                break
                except Exception:
                    pass
                if cand["description"] != "Unknown":
                    break

        # 对前 15 名中仍为 Unknown 的进行 NCBI 在线嗅探
        if self.on_progress:
            self.on_progress(98, "Host prediction: resolving taxonomy via NCBI...")

        for cand in top_candidates[:15]:
            if cand["description"] == "Unknown":
                ext_info = await self._silent_ncbi_fetch(cand["accession"])
                if ext_info:
                    cand["description"] = ext_info

        result["top_hits"] = top_candidates[:10]
        result["status"] = "Success"
        return result

    async def _silent_ncbi_fetch(self, accession: str) -> Optional[str]:
        """
        静默向 NCBI 索取物种描述元数据
        支持 WGS accession（如 DAGGVC010000033）通过 nuccore 页面标题解析
        """
        import urllib.request
        import json

        # 方案 1: NCBI nuccore docsum 页面（对 WGS accession 最可靠）
        try:
            url = f"https://www.ncbi.nlm.nih.gov/nuccore/{accession}.1?report=docsum"
            req = urllib.request.Request(url, headers={"User-Agent": "PhageScope/1.0"})
            with urllib.request.urlopen(req, timeout=8) as response:
                html = response.read().decode("utf-8", errors="ignore")
                # 页面 title 格式: "TPA_asm: Klebsiella pneumoniae strain XXX ..."
                import re
                title_match = re.search(r"<title>(?:TPA_asm:\s*)?(.+?)\s*-\s*(?:Nucleotide)?", html)
                if title_match:
                    title = title_match.group(1).strip()
                    # 提取物种名（通常是前两个词: Genus species）
                    words = title.split()
                    if len(words) >= 2:
                        organism = f"{words[0]} {words[1]}"
                        return organism
        except Exception:
            pass

        # 方案 2: Entrez esummary API
        try:
            search_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=nuccore&term={accession}&retmode=json"
            with urllib.request.urlopen(search_url, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                uid_list = data.get("esearchresult", {}).get("idlist", [])
                if uid_list:
                    sum_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=nuccore&id={uid_list[0]}&retmode=json"
                    with urllib.request.urlopen(sum_url, timeout=5) as resp2:
                        summary = json.loads(resp2.read().decode())
                        uid = uid_list[0]
                        organism = summary.get("result", {}).get(uid, {}).get("organism")
                        if organism:
                            return organism
        except Exception:
            pass

        # 方案 3: datasets CLI（如果系统安装了 NCBI datasets）
        try:
            cmd = ["datasets", "summary", "genome", "accession", accession, "--format", "json"]
            output = []
            def capture_out(line): output.append(line)
            ret = await self.runner.run_command(cmd, on_output=capture_out)
            if ret == 0:
                data = json.loads("".join(output))
                reports = data.get("reports", [])
                if reports:
                    org = reports[0].get("assembly_info", {}).get("biosample", {}).get("description", {}).get("organism", {})
                    name = org.get("organism_name") or org.get("scientific_name")
                    if name:
                        return name
        except Exception:
            pass

        return None


    async def _silent_backfill(self, gbk_path: Path, threads: int):
        """静默自动比对并回填注释 (使用本地 PhageScope 蛋白库)"""
        from Bio import SeqIO
        from Bio.SeqRecord import SeqRecord
        import csv
        import os
        import subprocess

        # 1. 提取未知蛋白
        records = list(SeqIO.parse(gbk_path, "genbank"))
        unknown_records = []
        for rec in records:
            for feat in rec.features:
                if feat.type == "CDS":
                    prod = feat.qualifiers.get("product", [""])[0].lower()
                    if not prod or "unknown" in prod or "hypothetical" in prod:
                        seq_ptr = feat.extract(rec.seq).translate(table=11, to_stop=True)
                        cid = feat.qualifiers.get("locus_tag", [feat.qualifiers.get("ID", ["unknown"])[0]])[0]
                        unknown_records.append(SeqRecord(seq_ptr, id=cid, description="unknown protein"))

        if not unknown_records:
            return

        faa_path = gbk_path.parent / "unknowns_for_refinement.faa"
        with open(faa_path, "w") as f:
            SeqIO.write(unknown_records, f, "fasta")

        # 2. 执行本地比对 (使用 PhageScope 高精度蛋白库，完全离线)
        if self.on_progress: self.on_progress(95, f"发现 {len(unknown_records)} 个未知蛋白，正在本地 PhageScope 库比对...")

        import shutil
        project_root = Path(self.context.get("project_dir", os.getcwd())).resolve()
        ps_db = project_root / "database" / "phagescope" / "phagescope_proteins"
        db_dir = str(ps_db.parent)
        db_name = ps_db.name

        # CWD-based: 将查询文件复制到 DB 目录下，用相对路径规避 Windows 空格路径问题
        local_query = ps_db.parent / "_tmp_backfill_query.faa"
        local_tsv = ps_db.parent / "_tmp_backfill_result.tsv"
        shutil.copy2(faa_path, local_query)

        blast_cmd = [
            "blastp",
            "-query", local_query.name,
            "-db", db_name,
            "-out", local_tsv.name,
            "-outfmt", "6 qseqid sseqid stitle evalue",
            "-max_target_seqs", "1",
            "-evalue", "1e-5",
            "-num_threads", str(threads)
        ]

        try:
            result = subprocess.run(
                blast_cmd, capture_output=True, text=True,
                timeout=300, cwd=db_dir
            )
            ret = result.returncode
        except Exception as e:
            logger.warning(f"[Annotation] Local PhageScope BLAST failed: {e}")
            ret = 1
        finally:
            # 清理临时文件
            local_query.unlink(missing_ok=True)

        # 将结果复制回注释目录
        win_tsv_out = str(faa_path).replace(".faa", ".tsv")
        if ret == 0 and local_tsv.exists():
            shutil.copy2(local_tsv, win_tsv_out)
            local_tsv.unlink(missing_ok=True)

        if ret == 0:
            win_tsv = Path(win_tsv_out)
            if win_tsv.exists():
                # 3. 解析结果并更新 GBK
                hits = {}
                with open(win_tsv, "r", encoding="utf-8") as f:
                    reader = csv.reader(f, delimiter="\t")
                    for row in reader:
                        if len(row) >= 4:
                            hits[row[0]] = {"product": row[2], "evalue": row[3]}

                if hits:
                    updated = 0
                    total_cds = sum(1 for r in records for f in r.features if f.type == "CDS")
                    for rec in records:
                        for feat in rec.features:
                            if feat.type == "CDS":
                                cid = feat.qualifiers.get("locus_tag", [feat.qualifiers.get("ID", [""])[0]])[0]
                                if cid in hits:
                                    h = hits[cid]
                                    feat.qualifiers["product"] = [h["product"]]
                                    # 🔗 存入 E-value 和可信度标签
                                    feat.qualifiers["e_value"] = [h.get("evalue", "1e-5")]
                                    feat.qualifiers["bit_score"] = [h.get("bitscore", "0")]
                                    feat.qualifiers["note"] = feat.qualifiers.get("note", []) + [f"Refined by PhageScope local BLASTp; E-value: {hits[cid]['evalue']}"]
                                    updated += 1

                    if updated > 0:
                        with open(gbk_path, "w", encoding="utf-8") as f:
                            SeqIO.write(records, f, "genbank")
                        if self.on_progress: self.on_progress(99, f"回填完成：已自动修复 {updated} 个注释")

                    # 写出结构化回填摘要供报告解析器使用
                    import json
                    summary = {
                        "total_cds": total_cds,
                        "unknown_before": len(unknown_records),
                        "hits": updated,
                        "hit_rate": round(updated / len(unknown_records) * 100, 1) if unknown_records else 0,
                        "details": [
                            {"cds_id": k, "product": v["product"], "evalue": v["evalue"]}
                            for k, v in hits.items()
                        ]
                    }
                    summary_path = gbk_path.parent / "phagescope_backfill_summary.json"
                    with open(gbk_path.parent / "phagescope_backfill_summary.json", "w", encoding="utf-8") as f:
                        json.dump(summary, f, ensure_ascii=False, indent=2)

        # 4. 无论是否触发回填，将最终汇总了 Pharokka + Phold + PhageScope 全部心血的产物写出一份终极 TSV
        try:
            final_tsv = gbk_path.parent.parent / "Integrated_Final_Annotations.tsv"
            with open(final_tsv, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f, delimiter="\t")
                writer.writerow(["Contig", "Type", "ID", "Start", "End", "Strand", "Function", "Product", "Notes", "Translation"])
                for rec in records:
                    for feat in rec.features:
                        if feat.type in ["CDS", "tRNA", "tmRNA", "pseudogene", "misc_feature"]:
                            cid = feat.qualifiers.get("locus_tag", [feat.qualifiers.get("ID", [""])[0]])[0]
                            start = int(feat.location.start) + 1
                            end = int(feat.location.end)
                            strand = "+" if feat.location.strand >= 0 else "-"
                            func = feat.qualifiers.get("function", [""])[0]
                            prod = feat.qualifiers.get("product", [""])[0]
                            notes = " ; ".join(feat.qualifiers.get("note", []))
                            translation = feat.qualifiers.get("translation", [""])[0]
                            writer.writerow([rec.id, feat.type, cid, start, end, strand, func, prod, notes, translation])
            logger.info(f"✅ 生成终极整合注释表: {final_tsv}")
        except Exception as e:
            logger.warning(f"[Annotation] 生成终极注释表失败: {e}")
        logger.info(f"[Annotation] PhageScope backfill: {updated}/{len(unknown_records)} refined, summary -> {summary_path.name}")

    def _parse_summary(self, path: Path) -> dict:
        """解析 Pharokka 摘要文件"""
        res = {"total_cds": 0, "functional_assigned": 0}
        try:
            with open(path, "r", encoding='utf-8') as f:
                for line in f:
                    if "Total CDS" in line:
                        res["total_cds"] = int(line.split(":")[-1].strip())
                    elif "Assigned function" in line:
                        res["functional_assigned"] = int(line.split(":")[-1].strip())
        except Exception:
            pass
        return res

    def _parse_checkv(self, quality_summary_path: Path) -> dict:
        """
        解析 CheckV 质量评估报告 (quality_summary.tsv)
        返回结构化的完整度、污染度及质量评级信息
        """
        import csv
        result = {
            "checkv_quality": "Unknown",
            "completeness": "N/A",
            "completeness_method": "N/A",
            "contamination": "N/A",
            "gene_count": 0,
            "viral_genes": 0,
            "host_genes": 0,
            "contig_length": 0,
            "provirus": "No",
            "warnings": []
        }
        try:
            if not quality_summary_path.exists():
                result["warnings"].append("quality_summary.tsv not found")
                return result
            
            with open(quality_summary_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f, delimiter="\t")
                for row in reader:
                    result["checkv_quality"] = row.get("checkv_quality", "Unknown")
                    result["completeness"] = row.get("completeness", "N/A")
                    result["completeness_method"] = row.get("completeness_method", "N/A")
                    result["contamination"] = row.get("contamination", "N/A")
                    result["gene_count"] = int(row.get("gene_count", 0) or 0)
                    result["viral_genes"] = int(row.get("viral_genes", 0) or 0)
                    result["host_genes"] = int(row.get("host_genes", 0) or 0)
                    result["contig_length"] = int(row.get("contig_length", 0) or 0)
                    result["provirus"] = row.get("provirus", "No")
                    
                    if result["host_genes"] > 0:
                        result["warnings"].append(
                            f"检测到 {result['host_genes']} 个疑似宿主基因 (可能存在宿主污染)")
                    if result["checkv_quality"] in ("Low-quality", "Not-determined"):
                        result["warnings"].append("基因组完整度评级较低，建议检查组装结果")
                    break  # 噬菌体通常只有 1 条 contig，取首行即可
        except Exception as e:
            logger.warning(f"[CheckV] 解析质量报告失败: {e}")
            result["warnings"].append(str(e))
        return result
