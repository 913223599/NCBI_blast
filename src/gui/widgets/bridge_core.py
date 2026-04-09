# -*- coding: utf-8 -*-
"""
WebBridge Mixin: 核心信号 & 基础功能
职责：页面就绪、日志转发、帮助系统、Annotation Hash 查询、外部 URL 打开
"""
import re
import json
from PyQt6.QtCore import pyqtSlot


class CoreBridgeMixin:
    """核心基础功能桥接 Mixin"""

    def notify_arrearage(self):
        """Notify JS about AI account arrearage"""
        self.logger.warning("AI Translation Arrearage detected, notifying UI")
        js_code = (
            "if(window.app && window.app.showNotification) "
            "window.app.showNotification('AI 翻译账户欠费或访问受限，已自动切换为本地翻译模式。', 'error', 10000);"
        )
        self.container.web_view.page().runJavaScript(js_code)

    @pyqtSlot()
    def request_help(self):
        """Handle help request from JS"""
        self.logger.info("JS requested help dialog")
        self.help_requested.emit()

    @pyqtSlot(result=list)
    def get_help_structure(self):
        """Return the help category structure to JS"""
        from src.utils.help_manager import get_help_manager
        return get_help_manager().get_help_structure()

    @pyqtSlot(str, result=str)
    def get_help_content(self, topic_id):
        """Return markdown content for a topic"""
        from src.utils.help_manager import get_help_manager
        return get_help_manager().get_help_content(topic_id)

    @pyqtSlot(str)
    def on_js_error(self, message):
        self.logger.error(f"[JS Error] {message}")

    @pyqtSlot(str)
    def on_js_log(self, message):
        self.logger.info(f"[JS Log] {message}")

    @pyqtSlot()
    def on_page_ready(self):
        self.logger.info("Web Container Report: Ready")
        self.page_ready.emit()

    @pyqtSlot(str)
    def request_file_load(self, file_type):
        """Handle file load request from JS"""
        self.logger.info(f"BRIDGE: JS requested file load for type: {file_type}")
        try:
            self.container.open_file_dialog(file_type)
        except Exception as exc:
            self.logger.error(f"BRIDGE ERROR in open_file_dialog: {exc}")

    @pyqtSlot(str)
    def open_external_url(self, url):
        """Open URL in system default browser"""
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices
        self.logger.info(f"Opening external URL: {url}")
        QDesktopServices.openUrl(QUrl(url))

    @pyqtSlot(str, result=str)
    def get_annotations_by_hashes(self, hashes_json):
        """Fetch human-readable names via Content Hash (MD5) lookup with runtime cleaning"""
        try:
            from src.workbench.models.annotation_manager import get_annotation_manager
            hashes = json.loads(hashes_json)
            mapping = get_annotation_manager().get_annotations_by_hashes(hashes)

            clean_mapping = {}
            for hash_key, identity in mapping.items():
                if identity:
                    match = re.search(r'^([A-Z][a-z]+(?:\s+[a-z]+))', identity.strip())
                    if match:
                        clean_mapping[hash_key] = match.group(1)
                    else:
                        clean_mapping[hash_key] = identity.split(';')[0].split(' strain')[0].split(' genome')[0].strip()
                else:
                    clean_mapping[hash_key] = identity

            return json.dumps(clean_mapping)
        except Exception as exc:
            self.logger.error(f"Failed to get annotations (Hash): {exc}")
            return "{}"

    @pyqtSlot(str)
    def log_message(self, message):
        """Log message from frontend"""
        self.logger.info(f"[Frontend] {message}")
