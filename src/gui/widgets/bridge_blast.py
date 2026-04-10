# -*- coding: utf-8 -*-
"""
WebBridge Mixin: BLAST 任务管理 + CSV 解析 + 共识投票
职责：BLAST 任务的创建/暂停/恢复/删除，结果流推送，CSV 解析及物种共识推举
"""
import csv
import datetime
import json
import os
import re
from collections import Counter
from pathlib import Path

from PyQt6.QtCore import pyqtSlot


class BlastBridgeMixin:
    """BLAST 比对引擎桥接 Mixin
    
    注意：此 Mixin 需要与 BridgeCore 混合使用，依赖以下属性：
    - blast_event: 信号对象
    - logger: 日志记录器
    - blast_manager: BLAST 管理器
    - container: Web 容器
    """
    
    # 内存结果缓存：{csv_path: (mtime, parsed_data)}
    _result_cache = {}
    
    # 实例特性声明（用于 IDE 自动补全和静态分析）
    _active_parsers = set()
    
    # 类型提示声明（用于 IDE 自动补全和静态分析）
    blast_event = None  # pyqtSignal
    logger = None  # logging.Logger
    blast_manager = None  # BlastManager
    container = None  # WebContainer

    def _broadcast_result(self, task_id, data):
        """Internal callback to push single result to JS (with top-50/98% consensus logic)"""
        best_hit = None
        if 'csv_file' in data and os.path.exists(data['csv_file']):
            # 同样使用缓存解析逻辑，避免单条推送时重复解析整个文件
            top_hits = self._parse_blast_csv(data['csv_file'], limit=50)
            best_hit = self._select_consensus_hit(top_hits)
            data['data'] = [best_hit] if best_hit else []

        self.blast_event.emit("single_result_update", json.dumps({
            "task_id": task_id,
            "result": data
        }))

        # Sync with Annotation Manager if we found a good identity
        if best_hit:
            try:
                from src.workbench.models.annotation_manager import get_annotation_manager
                identity = best_hit.get('speciesName') or best_hit.get('species') or best_hit.get('title')
                if identity:
                    match = re.search(r'^([A-Z][a-z]+(?:\s+[a-z]+)?)', identity.strip())
                    if match:
                        identity = match.group(1)
                    else:
                        identity = identity.split(';')[0].split(' strain')[0].split(' genome')[0].strip()

                    self.logger.info(f"Consensus Identity Elected: {identity}")
                    get_annotation_manager().update_annotation(
                        sequence_hash=data.get('sequence_hash'),
                        last_known_id=data.get('sequence_id'),
                        blast_identity=identity
                    )
            except Exception as exc:
                self.logger.error(f"Failed to sync consensus annotation: {exc}")

    @pyqtSlot(str, str)
    def request_batch_blast(self, seq_ids_json, source_rel_path):
        """[One-Click Identity] 从进化树侧直接发起比对任务"""
        try:
            from Bio import SeqIO
            seq_ids = set(json.loads(seq_ids_json))

            results_dir = Path("results/tree_results")
            full_path = results_dir / source_rel_path

            if not full_path.exists():
                matches = list(results_dir.rglob(source_rel_path.split('/')[-1]))
                if matches:
                    full_path = matches[0]
                else:
                    self.logger.error(f"Cannot find source FASTA: {source_rel_path}")
                    return

            queries = []
            for rec in SeqIO.parse(full_path, "fasta"):
                if rec.id in seq_ids:
                    queries.append(f">{rec.id}\n{str(rec.seq)}")

            if not queries:
                self.logger.warning("No matching sequences found in source FASTA")
                return

            timestamp = datetime.datetime.now().strftime('%M%S')
            params = {
                "query": "\n".join(queries),
                "program": "auto",
                "database": "nt",
                "evalue": 0.05,
                "hitlist_size": 50,
                "task_name": f"Identify_{len(queries)}_Seqs_{timestamp}"
            }
            task_id = self.blast_manager.create_task(params)
            self.logger.info(f"Auto-BLAST Task Started: {task_id} for {len(queries)} sequences.")

            self.container.web_view.page().runJavaScript(
                f"if(window.app) window.app.showNotification('已自动发起 {len(queries)} 条序列的身份识别任务...', 'info');"
            )
        except Exception as exc:
            self.logger.error(f"Failed to initiate auto-blast: {exc}")

    @pyqtSlot(str, result=str)
    def run_blast_job(self, params_json):
        """Run BLAST job via BlastManager"""
        self.logger.info(f"BLAST Job Requested via Manager: {params_json}")
        try:
            params = json.loads(params_json)
            if not params.get('query') and not params.get('files'):
                return json.dumps({'status': 'error', 'error': 'No query or files provided'})

            task_id = self.blast_manager.create_task(params)
            return json.dumps({
                'status': 'started',
                'message': 'BLAST job launched in background',
                'task_id': task_id
            })
        except Exception as exc:
            self.logger.error(f"BLAST Launch Error: {exc}")
            return json.dumps({'status': 'error', 'error': str(exc) if exc else "Unknown error"})

    @pyqtSlot(str)
    def stop_blast_job(self, task_id):
        """Cancel a running job"""
        self.blast_manager.stop_task(task_id)

    @pyqtSlot(str)
    def pause_blast_job(self, task_id):
        """Pause a running job"""
        self.blast_manager.pause_task(task_id)

    @pyqtSlot(str)
    def resume_blast_job(self, task_id):
        """Resume a paused job"""
        self.blast_manager.resume_task(task_id)

    @pyqtSlot(str, result=str)
    def get_task_status(self, task_id):
        """Query task status from manager"""
        status = self.blast_manager.get_task_status(task_id)
        return json.dumps(status) if status else "{}"

    @pyqtSlot(str, result=str)
    def get_task_results(self, task_id):
        """Fetch results for a task, using consensus-based best hit selection (Top 50 / 98%)"""
        results = self.blast_manager.get_task_results(task_id)
        for res in results:
            if 'csv_file' in res and os.path.exists(res['csv_file']):
                top_hits = self._parse_blast_csv(res['csv_file'], limit=50)
                best_hit = self._select_consensus_hit(top_hits)
                res['data'] = [best_hit] if best_hit else []
        return json.dumps(results)

    @pyqtSlot(str)
    def get_detailed_blast_results(self, csv_file):
        """[ASYNC] Fetch ALL hits via background worker to prevent UI lag"""
        from src.gui.workers.csv_parser_worker import CSVParserWorker
        
        self.logger.info(f"Async Detail Parse Requested: {csv_file}")
        if not os.path.exists(csv_file):
            self.blast_event.emit("detailed_results_ready", json.dumps([]))
            return

        # 创建并启动解析线程
        worker = CSVParserWorker(csv_file)
        
        # 绑定完成信号
        def on_finished(res_json):
            try:
                hits_count = len(json.loads(res_json))
                self.logger.info(f"Async Detail Parse Finished: {hits_count} hits")
                self.blast_event.emit("detailed_results_ready", res_json)
            except Exception as e:
                self.logger.error(f"Error in on_finished: {e}")
            finally:
                # 自清理引用
                if hasattr(self, '_active_parsers'):
                    self._active_parsers.discard(worker)

        worker.finished.connect(on_finished)
        worker.error.connect(lambda e: self.logger.error(f"Async Detail Parse Worker Error: {e}"))
        
        # 防止被垃圾回收
        if not hasattr(self, '_active_parsers'):
            self._active_parsers = set()
        self._active_parsers.add(worker)
        
        worker.start()

    @pyqtSlot(str, result=str)
    def read_result_file(self, file_path):
        """Read content of a result file for preview"""
        try:
            if os.path.exists(file_path) and os.path.isfile(file_path):
                if os.path.getsize(file_path) > 5 * 1024 * 1024:
                    return "file_too_large"
                with open(file_path, 'r', encoding='utf-8', errors='replace') as fobj:
                    return fobj.read()
            return ""
        except Exception as exc:
            self.logger.error(f"Failed to read result file {file_path}: {exc}")
            return ""

    @pyqtSlot(result=str)
    def get_all_tasks(self):
        """Return list of all current and past tasks"""
        tasks = self.blast_manager.list_tasks()
        return json.dumps(tasks) if tasks else "[]"

    @pyqtSlot()
    def clear_all_history(self):
        """清除所有历史任务，并执行深度内存释放"""
        self.logger.info("JS requested clear all history")
        failed_paths = self.blast_manager.clear_history()
        if failed_paths:
            self.logger.warning(f"Batch clear partially failed. {len(failed_paths)} folders locked.")
            self.blast_event.emit("batch_deletion_failed", json.dumps({"failed_list": failed_paths}))
        
        self.blast_event.emit("status_update", json.dumps({"status": "cleared"}))
        
        # 显式清理结果缓存池并触发垃圾回收
        self._result_cache.clear()
        import gc
        gc.collect()

    @pyqtSlot(str)
    def delete_single_task(self, task_id):
        """Delete specific task and notify on failure"""
        self.logger.info(f"JS requested delete task: {task_id}")
        success, failed_path = self.blast_manager.delete_task(task_id)
        if not success:
            self.logger.warning(f"Deletion failed for {task_id}, path blocked: {failed_path}")
            self.blast_event.emit("deletion_failed", json.dumps({
                "task_id": task_id,
                "path": failed_path
            }))

    @pyqtSlot(str, str)
    def rename_task(self, task_id, new_name):
        """Rename specific task"""
        self.logger.info(f"JS requested rename task {task_id} -> {new_name}")
        self.blast_manager.rename_task(task_id, new_name)

    @pyqtSlot(str)
    def resume_task(self, task_id):
        """Resume a failed/cancelled task"""
        self.logger.info(f"JS requested resume task: {task_id}")
        if self.blast_manager.resume_task(task_id):
            self.blast_event.emit("status_update", json.dumps({"status": "resumed", "task_id": task_id}))

    @pyqtSlot(str)
    def open_results_dir(self, path):
        """Open results directory in explorer"""
        self.logger.info(f"JS requested open folder: {path}")
        self.blast_manager.open_directory(path)

    # --- BLAST CSV 解析 & 共识投票 ---
    def _parse_blast_csv(self, csv_path, limit=None):
        """带有内存缓存机制的 CSV 解析器"""
        csv_path_obj = Path(csv_path)
        if not csv_path_obj.exists():
            return []
        
        # 初始化变量，防止后续未赋值引用
        curr_mtime = None
            
        # 针对全量解析（limit=None）启用缓存策略
        if limit is None:
            curr_mtime = csv_path_obj.stat().st_mtime
            if csv_path in self._result_cache:
                old_mtime, cached_data = self._result_cache[csv_path]
                if curr_mtime <= old_mtime:
                    return cached_data

        data = []
        try:
            with open(csv_path, 'r', encoding='utf-8-sig') as fobj:
                reader = csv.DictReader(fobj)
                count = 0
                for row in reader:
                    # ... 原有的解析逻辑 ...
                    raw_title = row.get('标题', 'Unknown')
                    if '>' in raw_title:
                        raw_title = raw_title.split('>')[0].strip()

                    clean_title = raw_title
                    gi_match = re.match(r'^gi\|\d+\|[a-z]+\|[A-Za-z0-9_.]+\|\s*', raw_title)
                    if gi_match:
                        clean_title = raw_title[gi_match.end():].strip()

                    gene_source = ''
                    source_patterns = [
                        r'(16S\s+ribosomal\s+RNA\s+gene)',
                        r'(23S\s+ribosomal\s+RNA\s+gene)',
                        r'(ITS\s+region)',
                        r'(chromosome[^,]*)',
                        r'(complete\s+genome)',
                        r'(genome\s+assembly)',
                    ]
                    for pattern in source_patterns:
                        source_match = re.search(pattern, clean_title, re.IGNORECASE)
                        if source_match:
                            gene_source = source_match.group(1)
                            break
                    
                    # 智能物种名校准逻辑：防止菌株名（如 Newman）误充当物种名
                    species_raw = row.get('物种', 'N/A').strip()
                    species_final = species_raw
                    if len(species_raw) < 4 or species_raw.lower() in ['newman', 'strain', 'str.', 'subsp.', 'aureus']:
                        match = re.search(r'([A-Z][a-z]+(?:\s+[a-z]+)?)', clean_title)
                        if match:
                            species_final = match.group(1)

                    data.append({
                        'title': clean_title,
                        'len': row.get('长度', '0'),
                        'acc': row.get('访问号', 'N/A'),
                        'species': species_final,
                        'genus': row.get('属名', ''),
                        'strain': row.get('菌株', ''),
                        'gene_type': row.get('基因类型', ''),
                        'seq_type': row.get('序列类型', ''),
                        'host': row.get('宿主信息', ''),
                        'gene_source': gene_source,
                        'hsp_count': row.get('高得分片段对(HSPs)', '0'),
                        'evalue': row.get('E值', 'N/A'),
                        'align_len': row.get('比对长度', '0'),
                        'ident_count': row.get('相同碱基数', '0'),
                        'similarity': row.get('相似度', '0%'),
                        'gaps': row.get('缺口数', '0'),
                        'query_range': row.get('查询起始-结束', ''),
                        'hit_range': row.get('命中起始-结束', '')
                    })
                    count += 1
                    if limit and count >= limit:
                        break
            
            # 存入缓存
            if limit is None:
                self._result_cache[csv_path] = (curr_mtime, data)
                # 策略性维护缓存池：当缓存过大时清理旧的
                if len(self._result_cache) > 10:
                    first_key = next(iter(self._result_cache))
                    del self._result_cache[first_key]

        except Exception as exc:
            import logging
            logging.getLogger(__name__).error(f"CSV Parse Error: {exc}")
        return data

    def _select_consensus_hit(self, hits):
        """Select the best representative hit using majority voting on species."""
        if not hits:
            return None

        high_identity_hits = []
        for hit in hits:
            sim_str = str(hit.get('similarity', '0%')).replace('%', '').strip()
            try:
                sim_val = float(sim_str)
                if sim_val >= 98.0:
                    high_identity_hits.append(hit)
            except (ValueError, TypeError):
                continue

        target_hits = high_identity_hits if high_identity_hits else hits

        if len(target_hits) == 1:
            return target_hits[0]

        generic_names = {'bacterium', 'uncultured bacterium', 'uncultured organism',
                         'unidentified', 'unknown', 'n/a', ''}

        species_counter = Counter()
        species_to_hit = {}

        for hit in target_hits:
            species = (hit.get('species') or '').strip()
            species_lower = species.lower()
            if species_lower and species_lower not in generic_names:
                species_counter[species] += 1
                if species not in species_to_hit:
                    species_to_hit[species] = hit

        if not species_counter:
            return target_hits[0]

        total_valid = sum(species_counter.values())
        top_entries = species_counter.most_common(5)

        prob_parts = []
        consensus_list = []
        for name, count in top_entries:
            pct = (count / total_valid) * 100
            prob_parts.append(f"{name}({pct:.0f}%)")
            consensus_list.append({"name": name, "pct": round(pct)})

        probability_str = ", ".join(prob_parts)

        consensus_species = top_entries[0][0]
        best_hit = dict(species_to_hit[consensus_species])
        best_hit['species'] = probability_str
        best_hit['consensusList'] = consensus_list

        self.logger.info(
            f"Consensus Probabilities (Top 50/98%): {probability_str} "
            f"on high_identity_hits={bool(high_identity_hits)}"
        )
        return best_hit

    def _generate_summary(self, result):
        return f"Processed {os.path.basename(str(result.get('file', '')))} in {result.get('elapsed_time', 0):.2f}s"
