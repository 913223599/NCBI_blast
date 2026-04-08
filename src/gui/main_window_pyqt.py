"""
NCBI Bio-Station Shell (Refactored)
Hosts Navigation and Modules (BLAST, SRA, Tree)
"""
import os
import sys
from pathlib import Path
from PyQt6.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QStackedWidget, 
                             QMenuBar, QMenu, QStatusBar, QMessageBox, QApplication)
from PyQt6.QtCore import QProcess, QUrl
from PyQt6.QtGui import QAction, QIcon

# Modules
# Modules
from src.gui.widgets.web_container import WebContainer
from src.gui.widgets.help_viewer import HelpViewerDialog
from src.gui.widgets.api_key_dialog import ApiKeyDialog
from src.gui.widgets.database_manager_dialog import DatabaseManagerDialog

# Project Root
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def ensure_results_folders():
    try:
        root_results_path = Path(project_root) / "results"
        root_results_path.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"Error creating results: {e}")

class MainWindow(QMainWindow):
    """
    Bio-Station Shell (WebOS Mode)
    Hosts the integrated Web Container as the primary interface.
    """
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NCBI BLAST 专业版 | 工作台")
        self.resize(1400, 900) # Slightly larger for web view
        self.setMinimumSize(1240, 800) # Lock minimum size to ensure UI integrity
        
        ensure_results_folders()
        self._apply_theme()
        
        # UI Setup
        self._setup_layout() # Must be first to init web_container
        # Menu bar removed as per user request
        
        # Connect Web Bridge Signals
        if hasattr(self.web_container, 'bridge'):
            self.web_container.bridge.help_requested.connect(self._open_help_dialog)
            
        # Global Shortcuts
        refresh_action = QAction(self)
        refresh_action.setShortcut("F5")
        refresh_action.triggered.connect(self.web_container.reload)
        self.addAction(refresh_action)

        self.addAction(refresh_action)
        
        # State (Dialogs)
        self.db_manager_dialog = None
        self.help_viewer_dialog = None
        self.api_key_dialog = None
        
    def _apply_theme(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #f0f2f5; }
            QWidget { font-family: 'Segoe UI', sans-serif; }
            QStatusBar { background-color: #fff; border-top: 1px solid #ddd; }
        """)

    def _setup_layout(self):
        # The entire window is now the Web Container
        self.web_container = WebContainer()
        self.setCentralWidget(self.web_container)
        
        self._create_status_bar()
        
    def _create_status_bar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Bio-Station System Ready")

    # --- Dialog Actions ---
    
    def _open_history_dialog(self):
        # Legacy: Moved to Web UI sidebar
        pass

    def _open_db_manager_dialog(self):
        if not self.db_manager_dialog:
            self.db_manager_dialog = DatabaseManagerDialog(self)
        self.db_manager_dialog.show()


    def _open_help_dialog(self):
        if not self.help_viewer_dialog:
            self.help_viewer_dialog = HelpViewerDialog(self)
        self.help_viewer_dialog.show()


    def _open_api_key_dialog(self):
        if not self.api_key_dialog:
            self.api_key_dialog = ApiKeyDialog()
        self.api_key_dialog.show()

    def _open_global_settings(self):
        from src.gui.widgets.global_settings_dialog import GlobalSettingsDialog
        dialog = GlobalSettingsDialog(self)
        dialog.exec()

    def changeEvent(self, event):
        """拦截窗口状态变更（全屏/窗口化）并通知刷新"""
        from PyQt6.QtCore import QEvent, QTimer
        if event.type() == QEvent.Type.WindowStateChange:
            if hasattr(self, 'web_container'):
                # 状态切换可能导致 GPU 缓冲区重建，需要强制重绘
                self.web_container.handle_resize_event()
                
                # v4 补丁：执行“物理抖动”策略
                # 延迟 200ms（等待全屏动画基本结束）后微调窗口尺寸以强制驱动 OS 合成器同步
                def trigger_jiggle():
                    if not self.isFullScreen():
                        curr_size = self.size()
                        self.resize(curr_size.width(), curr_size.height() + 1)
                        QTimer.singleShot(50, lambda: self.resize(curr_size))
                
                QTimer.singleShot(200, trigger_jiggle)
        super().changeEvent(event)

    def resizeEvent(self, event):
        """窗口大小变更时通知 Web 容器强制重绘"""
        super().resizeEvent(event)
        if hasattr(self, 'web_container'):
            self.web_container.handle_resize_event()

    def closeEvent(self, event):
        # We can communicate with Web App to check if tasks are running via bridge later
        event.accept()



