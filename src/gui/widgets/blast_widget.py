"""BLAST Analysis Module
Migrated from original MainWindow
"""
from pathlib import Path

from PyQt6.QtCore import pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFrame,
                             QMessageBox, QDialog)

# Threads and Processors
from src.gui.threads.processing_thread import ProcessingThread, MultiSequenceProcessingThread
from src.gui.widgets.control_panel import ControlPanelWidget
# Import original widgets components
from src.gui.widgets.file_selector import FileSelectorWidget
from src.gui.widgets.parameter_settings import ParameterSettingsWidget
from src.gui.widgets.result_viewer import ResultViewerWidget
from src.gui.widgets.task_name_dialog import TaskNameDialog
from src.utils.config_manager import get_config_manager
from src.blast.local_blast import LocalBatchProcessor as MultiSequenceBatchProcessor


class BlastWidget(QWidget):
    """
    BLAST Analysis Workstation
    Encapsulates the original main window functionality.
    """
    
    # Signals to communicate with the Shell window if needed
    status_message = pyqtSignal(str, int) # message, timeout
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Init variables
        self.sequence_files = []
        self.results = []
        self.is_processing = False
        self.is_cancelling = False
        self.processing_thread = None
        self.batch_processor = None
        self.translation_debugger = None
        
        # UI Setup
        self._create_widgets()
        self._setup_modern_ui()
        self._connect_signals()
        
    def _create_widgets(self):
        """Create UI components"""
        self.file_selector = FileSelectorWidget()
        self.file_selector.setObjectName("FileSelector")
        
        self.parameter_settings = ParameterSettingsWidget()
        self.control_panel = ControlPanelWidget()
        self.result_viewer = ResultViewerWidget()
        
    def _setup_modern_ui(self):
        """Setup Layout (Sidebar + Content)"""
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(15)
        
        # Sidebar
        sidebar_frame = QFrame()
        sidebar_frame.setObjectName("Sidebar")
        sidebar_frame.setFixedWidth(350) 
        sidebar_layout = QVBoxLayout(sidebar_frame)
        sidebar_layout.setContentsMargins(0,0,0,0)
        
        file_card = self._wrap_in_card(self.file_selector)
        param_card = self._wrap_in_card(self.parameter_settings)
        
        sidebar_layout.addWidget(file_card, 1)
        sidebar_layout.addWidget(param_card, 2)
        
        # Content Area
        content_frame = QFrame()
        content_frame.setObjectName("ContentArea")
        content_layout = QVBoxLayout(content_frame)
        content_layout.setContentsMargins(0,0,0,0)
        
        control_card = self._wrap_in_card(self.control_panel)
        control_card.setFixedHeight(100)
        
        result_container = self._wrap_in_card(self.result_viewer)
        
        content_layout.addWidget(control_card)
        content_layout.addWidget(result_container)
        
        main_layout.addWidget(sidebar_frame)
        main_layout.addWidget(content_frame)

    def _wrap_in_card(self, widget):
        card = QFrame()
        card.setObjectName("Card")
        # Apply shadow etc. via QSS in parent
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(widget)
        return card

    def _connect_signals(self):
        self.file_selector.files_selected.connect(self._on_files_selected)
        self.control_panel.start_button.clicked.connect(self._start_processing)
        self.control_panel.stop_button.clicked.connect(self._stop_processing)
        self.result_viewer.signals.retry_blast.connect(self._retry_blast)

    # --- Business Logic (Copied from MainWindow) ---

    def _on_files_selected(self, files):
        self.sequence_files = files
        self.result_viewer.update_sequence_files(files)
        # self.status_message.emit(f"Selected {len(files)} files", 3000)

    def _start_processing(self):
        if not self.sequence_files:
            QMessageBox.warning(self, "Warning", "Please select sequence files first.")
            return

        if self.is_processing:
            return

        # Task Name Dialog
        task_dialog = TaskNameDialog(self)
        if task_dialog.exec() != QDialog.DialogCode.Accepted:
            return
        task_name = task_dialog.get_task_name()

        # UI Updates
        for file in self.sequence_files:
            self.result_viewer.update_file_status({
                "file": file, "status": "processing", "elapsed_time": 0
            })
            
        self._setup_translation_settings()
        self._disconnect_current_thread()
        
        # Create Thread
        self.batch_processor, self.processing_thread = self._create_processor_and_thread(self.sequence_files, task_name)
        if not self.batch_processor:
            return
            
        self.is_processing = True
        self.is_cancelling = False
        self.control_panel.enable_start_button(False)
        self.control_panel.enable_stop_button(True)
        self.control_panel.set_stop_button_text("Stop")
        self.control_panel.update_progress(0)
        self.file_selector.set_processing_state(True)
        
        self._connect_thread_signals()
        self.processing_thread.start()

    def _create_processor_and_thread(self, file_paths, task_name=None):
        try:
            max_workers = self.parameter_settings.get_thread_count()
        except ValueError as e:
            QMessageBox.critical(self, "Error", str(e))
            return None, None

        advanced_settings = self.parameter_settings.get_advanced_settings()
        
        # Check Elastic BLAST
        if advanced_settings.get('elb_enabled'):
            try:
                from src.blast.elastic_blast_processor import ElasticBlastProcessor
                processor = ElasticBlastProcessor(max_workers=1, advanced_settings=advanced_settings, task_name=task_name)
                thread = ProcessingThread(processor, file_paths)
                return processor, thread
            except ImportError:
                QMessageBox.critical(self, "Error", "Elastic BLAST module not available.")
                return None, None
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Elastic BLAST Error: {e}")
                return None, None

        # Standard Processing
        processor = MultiSequenceBatchProcessor(max_workers=max_workers, advanced_settings=advanced_settings, task_name=task_name)
        thread = MultiSequenceProcessingThread(processor, file_paths)
        return processor, thread

    @pyqtSlot()
    def _stop_processing(self):
        if not self.is_processing: return
        
        if not self.is_cancelling:
            if self.batch_processor:
                self.batch_processor.cancel_processing()
            self.is_cancelling = True
            self.control_panel.set_status("Cancelling...")
            self.control_panel.set_stop_button_text("Force Stop")
        else:
            if QMessageBox.question(self, "Force Stop", "Are you sure?") == QMessageBox.StandardButton.Yes:
                self._disconnect_current_thread()
                if self.processing_thread:
                    self.processing_thread.terminate()
                    self.processing_thread.wait()
                self._on_thread_finished()

    # --- Event Handlers ---
    def _on_task_start(self, sequence_file):
        name = Path(sequence_file).name
        self.control_panel.set_status(f"Processing: {name}")

    def _on_progress_update(self, completed, total):
        self.control_panel.update_progress(int((completed/total)*100) if total > 0 else 0)

    def _on_result_received(self, result):
        self.results.append(result)
        self.result_viewer.update_file_status(result)

    def _on_all_tasks_complete(self, total):
        self.control_panel.set_status("Processing Complete")

    def _on_processing_error(self, msg):
        self.is_processing = False
        self.control_panel.enable_start_button(True)
        self.control_panel.enable_stop_button(False)
        self.file_selector.set_processing_state(False)
        QMessageBox.critical(self, "Error", msg)

    def _on_thread_finished(self):
        self.is_processing = False
        self.is_cancelling = False
        self.control_panel.enable_start_button(True)
        self.control_panel.enable_stop_button(False)
        self.file_selector.set_processing_state(False)
        
        if self.batch_processor and self.batch_processor._cancel_flag:
            self.control_panel.set_status("Cancelled")
            self.control_panel.update_progress(0)
        else:
            self.control_panel.update_progress(100)
            successful = sum(1 for r in self.results if r["status"] == "success")
            self.control_panel.set_status(f"Completed: {successful} successes")

    # --- Helpers ---
    def _retry_blast(self, file_name):
        file_path = next((res.get("file") for res in self.results if Path(res.get("file", "")).name == file_name), None)
        if not file_path: return
        self._setup_translation_settings()
        self._disconnect_current_thread()
        self.batch_processor, self.processing_thread = self._create_processor_and_thread([file_path])
        if not self.batch_processor: return
        
        self.is_processing = True
        self.control_panel.enable_start_button(False)
        self.control_panel.enable_stop_button(True)
        self.file_selector.set_processing_state(True)
        self._connect_thread_signals()
        self.processing_thread.start()

    def _disconnect_current_thread(self):
        if self.processing_thread:
            try:
                self.processing_thread.task_started.disconnect()
                self.processing_thread.progress_updated.disconnect()
                self.processing_thread.result_received.disconnect()
                self.processing_thread.all_tasks_completed.disconnect()
                self.processing_thread.processing_error.disconnect()
                self.processing_thread.finished.disconnect()
            except: pass

    def _connect_thread_signals(self):
        if self.processing_thread:
            self.processing_thread.task_started.connect(self._on_task_start)
            self.processing_thread.progress_updated.connect(self._on_progress_update)
            self.processing_thread.result_received.connect(self._on_result_received)
            self.processing_thread.all_tasks_completed.connect(self._on_all_tasks_complete)
            self.processing_thread.processing_error.connect(self._on_processing_error)
            self.processing_thread.finished.connect(self._on_thread_finished)

    def _setup_translation_settings(self):
        advanced = self.parameter_settings.get_advanced_settings()
        settings = {
            'use_ai': advanced.get('use_ai_translation', True),
            'translator_type': advanced.get('translator_type', 'default'),
            'ai_model': advanced.get('ai_translation_model', 'deepseek-r1')
        }
        api_key = None
        try:
             api_key = get_config_manager().get_api_key('dashscope')
        except: pass
        self.result_viewer.set_translation_settings(settings, api_key)
