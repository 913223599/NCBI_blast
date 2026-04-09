# -*- coding: utf-8 -*-
"""
WebBridge Mixin: 进化树工作区管理
职责：序列文件暂存、分析触发、归档召回、工作区清理
"""
import datetime
import json
import os
import re
import shutil
from pathlib import Path

from PyQt6.QtCore import pyqtSlot


class TreeBridgeMixin:
    """进化树工作区桥接 Mixin"""

    @pyqtSlot(str, str, result=bool)
    def save_file(self, content, filename_hint="export.txt"):
        """Save text content to valid local file via Dialog"""
        from PyQt6.QtWidgets import QFileDialog
        try:
            file_filter = "All Files (*.*)"
            if filename_hint.endswith("svg"):
                file_filter = "SVG Files (*.svg);;All Files (*.*)"
            elif filename_hint.endswith("png"):
                file_filter = "PNG Files (*.png);;All Files (*.*)"
            elif filename_hint.endswith("nwk"):
                file_filter = "Newick Files (*.nwk *.tree);;All Files (*.*)"

            path, _ = QFileDialog.getSaveFileName(self.container, "Save File", filename_hint, file_filter)

            if path:
                encoding = 'utf-8-sig' if path.lower().endswith('.csv') else 'utf-8'
                with open(path, 'w', encoding=encoding) as fobj:
                    fobj.write(content)
                self.logger.info(f"File saved successfully to: {path} (encoding={encoding})")
                return True
            return False
        except Exception as exc:
            self.logger.error(f"Save File Error: {exc}")
            return False

    @pyqtSlot(str)
    def save_tree_sequences(self, fasta_content):
        """保存手动输入的序列到工作空间，支持 Tree Station 2.0"""
        try:
            workspace = Path("results/tree_workspace")
            workspace.mkdir(parents=True, exist_ok=True)

            first_header = "Station_Input"
            match = re.search(r'^>\s*(.+)', fasta_content, re.M)
            if match:
                header_line = match.group(1).strip()
                first_header = "".join(
                    c if c.isalnum() or c in (' ', '.', '_', '-') else '_' for c in header_line
                ).strip()
                first_header = first_header.replace(' ', '_')[:40]

            timestamp = datetime.datetime.now().strftime("%y%m%d_%H%M")
            file_name = f"{first_header}_{timestamp}.fasta"
            file_path = workspace / file_name

            with open(file_path, "w", encoding="utf-8") as fobj:
                fobj.write(fasta_content)
            self.logger.info(f"User sequences saved to {file_path}")
            return True
        except Exception as exc:
            self.logger.error(f"Failed to save sequences: {exc}")
            return False

    @pyqtSlot(str)
    def recall_tree_sequences(self, source_filename):
        """Recall original sequences from results back to active workspace for re-analysis"""
        try:
            results_dir = Path("results/tree_results")
            workspace_dir = Path("results/tree_workspace")
            workspace_dir.mkdir(parents=True, exist_ok=True)

            potential_file = results_dir / source_filename
            if not potential_file.exists():
                matches = list(results_dir.rglob(source_filename))
                if matches:
                    potential_file = matches[0]
                else:
                    self.logger.info(f"Precise match failed for {source_filename}, trying recursive wildcard matching...")
                    matches = list(results_dir.rglob(f"{source_filename}*"))
                    if matches:
                        potential_file = matches[0]
                    else:
                        self.logger.error(f"Recall Failed: No file matches {source_filename}")
                        self.recall_event.emit(False, f"Not Found: {source_filename}")
                        return

            pure_name = potential_file.name
            match = re.match(r'^Tree_\d{8}_\d{6}_(.+)$', pure_name)
            if match:
                pure_name = match.group(1)

            target_path = workspace_dir / pure_name
            shutil.copy2(potential_file, target_path)
            self.logger.info(f"BRIDGE: [SUCCESS] Recalled {potential_file.name} to workspace as {pure_name}.")
            self.recall_event.emit(True, pure_name)
        except Exception as exc:
            self.logger.error(f"Recall Logic Error: {exc}")
            self.recall_event.emit(False, str(exc))

    @pyqtSlot(str)
    def delete_tree_archive(self, rel_path):
        """Physically delete a single tree archive file or a whole project folder"""
        try:
            target = Path("results/tree_results") / rel_path
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                    self.logger.info(f"BRIDGE: [SUCCESS] Physically deleted project folder: {target}")
                else:
                    target.unlink()
                    self.logger.info(f"BRIDGE: [SUCCESS] Physically deleted archive file: {target}")
            else:
                self.logger.warning(f"BRIDGE: [WARNING] Delete target not found: {rel_path}")
        except Exception as exc:
            self.logger.error(f"BRIDGE: [ERROR] Failed to delete archive {rel_path}: {exc}")

    @pyqtSlot(str)
    def request_tree_analysis(self, params_json):
        """Handle tree analysis request with params"""
        self.logger.info(f"JS requested tree analysis: {params_json}")
        try:
            params = json.loads(params_json)
            self.container.run_tree_analysis(params=params)
        except Exception as exc:
            self.logger.error(f"Failed to start tree: {exc}")
            self.container.web_view.page().runJavaScript(
                f"if(window.app) window.app.showNotification('启动分析失败: {str(exc)}', 'error');"
            )

    @pyqtSlot(result=str)
    def list_tree_sequences(self):
        """List files in tree workspace with multi-extension support"""
        try:
            workspace = Path("results/tree_workspace")
            workspace.mkdir(parents=True, exist_ok=True)
            files = []
            for ext in ("*.fasta", "*.seq", "*.fa", "*.fna", "*.nwk", "*.txt"):
                files.extend([f.name for f in workspace.glob(ext)])
            return json.dumps(sorted(list(set(files))))
        except Exception as exc:
            self.logger.error(f"Failed to list tree workspace: {exc}")
            return "[]"

    @pyqtSlot(str, result=bool)
    def add_tree_workspace_files(self, paths_json):
        """Copy local files directly into the tree workspace"""
        try:
            paths = json.loads(paths_json)
            workspace = Path("results/tree_workspace")
            workspace.mkdir(parents=True, exist_ok=True)
            for p_str in paths:
                src_path = Path(p_str)
                if src_path.exists():
                    shutil.copy(src_path, workspace / src_path.name)
            return True
        except Exception as exc:
            self.logger.error(f"Failed to add workspace files: {exc}")
            return False

    @pyqtSlot(result=bool)
    def clear_tree_workspace(self):
        """Delete all files in tree workspace"""
        try:
            workspace = Path("results/tree_workspace")
            if workspace.exists():
                for fobj in workspace.iterdir():
                    if fobj.is_file():
                        os.remove(fobj)
            return True
        except Exception as exc:
            self.logger.error(f"Failed to clear workspace: {exc}")
            return False

    @pyqtSlot(str)
    def delete_analysis_files(self, paths_json):
        """物理删除磁盘上的分析结果文件"""
        try:
            paths = json.loads(paths_json)
            for p_str in paths:
                target = Path(p_str)
                if target.exists() and target.is_file():
                    target.unlink()
                    self.logger.info(f"Physical file deleted: {p_str}")
            return True
        except Exception as exc:
            self.logger.error(f"Failed to delete physical files: {exc}")
            return False

    @pyqtSlot(str)
    def request_tree_reroot(self, node_id):
        """Handle reroot request"""
        self.logger.info(f"JS requested reroot at: {node_id}")
        self.container.run_tree_reroot(node_id)

    @pyqtSlot(str, result=str)
    def get_tree_content(self, filename):
        """Read .nwk tree file content for direct loading"""
        try:
            path = Path("results/tree_workspace") / filename
            if path.exists():
                return path.read_text(encoding='utf-8', errors='ignore')
            return ""
        except Exception as exc:
            self.logger.error(f"get_tree_content error: {exc}")
            return ""
