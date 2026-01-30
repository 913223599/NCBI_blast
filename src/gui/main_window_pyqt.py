"""
NCBI Bio-Station Shell (Refactored)
Hosts Navigation and Modules (BLAST, SRA, Tree)
"""
import os
import sys
from pathlib import Path
from PyQt6.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QStackedWidget, 
                             QMenuBar, QMenu, QStatusBar, QMessageBox)
from PyQt6.QtGui import QAction, QIcon

# Modules
# Modules
from src.gui.widgets.web_container import WebContainer
from src.gui.widgets.help_viewer import HelpViewerDialog
from src.gui.widgets.api_key_dialog import ApiKeyDialog
from src.gui.widgets.database_manager_dialog import DatabaseManagerDialog
from src.gui.widgets.cloud_manager_dialog import CloudManagerDialog

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
        
        # State (Dialogs)
        self.db_manager_dialog = None
        self.cloud_manager_dialog = None
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

    def _open_cloud_manager(self):
        # Note: Previous settings logic was tied to BlastWidget. 
        # For now, we open with default settings.
        if not self.cloud_manager_dialog:
            self.cloud_manager_dialog = CloudManagerDialog(self)
        self.cloud_manager_dialog.show()

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

    def closeEvent(self, event):
        # We can communicate with Web App to check if tasks are running via bridge later
        event.accept()

