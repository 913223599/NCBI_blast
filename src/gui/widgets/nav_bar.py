from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLabel, QFrame
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QIcon, QFont

class NavBar(QFrame):
    """
    Vertical Navigation Rail
    """
    
    page_changed = pyqtSignal(int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(80)
        self.setStyleSheet("""
            NavBar {
                background-color: #2c3e50;
                border-right: 1px solid #34495e;
            }
            QPushButton {
                border: none;
                color: #B0B0B0;
                text-align: center;
                padding: 15px 0;
                font-size: 12px;
                background-color: transparent;
            }
            QPushButton:hover {
                color: white;
                background-color: #34495e;
            }
            QPushButton:checked {
                color: #409eff;
                font-weight: bold;
                background-color: #243342;
                border-left: 3px solid #409eff;
            }
        """)
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 20, 0, 20)
        self.layout.setSpacing(10)
        
        self.buttons = []
        
        # Add Modules
        self.add_nav_button(0, "BLAST", "🔍")
        self.add_nav_button(1, "SRA Hub", "📥") 
        self.add_nav_button(2, "Tree Lab", "🌳")
        
        self.layout.addStretch()
        
        # Settings at bottom
        # self.add_nav_button(3, "Settings", "⚙️") # Optional
        
    def add_nav_button(self, index, text, icon_char):
        btn = QPushButton(f"{icon_char}\n{text}")
        btn.setCheckable(True)
        btn.setFixedHeight(80)
        btn.clicked.connect(lambda: self._on_btn_clicked(index))
        self.layout.addWidget(btn)
        self.buttons.append(btn)
        
        if index == 0:
            btn.setChecked(True)
            
    def _on_btn_clicked(self, index):
        for i, btn in enumerate(self.buttons):
            btn.setChecked(i == index)
        self.page_changed.emit(index)
