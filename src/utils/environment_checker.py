"""
环境检查模块
用于在程序启动前检查必要的依赖和环境配置
"""

import sys
import os
import subprocess
import platform
from typing import List, Tuple


class EnvironmentChecker:
    """环境检查器"""
    
    def __init__(self):
        self.checks = []
        self.errors = []
        self.warnings = []
    
    def check_python_version(self) -> bool:
        """检查Python版本"""
        min_version = (3, 8)
        current_version = sys.version_info[:2]
        
        if current_version < min_version:
            self.errors.append(
                f"Python版本过低。需要Python {min_version[0]}.{min_version[1]}+，"
                f"当前版本: {sys.version_info.major}.{sys.version_info.minor}"
            )
            return False
        else:
            self.checks.append(f"Python版本: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
            return True
    
    def check_pyqt(self) -> bool:
        """检查PyQt库及WebEngine组件是否可用"""
        try:
            from PyQt6.QtWidgets import QApplication
            from PyQt6.QtWebEngineWidgets import QWebEngineView
            self.checks.append("PyQt6 (含 WebEngine) 可用")
            return True
        except ImportError as e:
            if "WebEngine" in str(e):
                 self.errors.append("缺少 PyQt6-WebEngine 组件。请运行: pip install PyQt6-WebEngine")
            else:
                 self.errors.append(f"PyQt6 库不可用: {e}")
            return False
    
    def check_blast_executables(self) -> bool:
        """检查BLAST可执行文件是否存在"""
        # 检查系统PATH中是否存在BLAST命令
        blast_commands = ['blastn', 'blastp', 'blastx', 'tblastn', 'makeblastdb']
        found_commands = []
        
        for cmd in blast_commands:
            if self._command_exists(cmd):
                found_commands.append(cmd)
        
        if found_commands:
            self.checks.append(f"找到BLAST命令: {', '.join(found_commands)}")
            return True
        else:
            self.warnings.append("未找到BLAST命令。如果需要本地BLAST功能，请安装BLAST+套件")
            return True  # 不是错误，只是警告
    
    def _command_exists(self, cmd: str) -> bool:
        """检查命令是否存在"""
        try:
            subprocess.check_output(['where' if platform.system() == 'Windows' else 'which', cmd], 
                                  stderr=subprocess.STDOUT, shell=True)
            return True
        except (subprocess.CalledProcessError, OSError):
            return False
    
    def check_required_modules(self) -> bool:
        """检查必要的Python模块"""
        required_modules = [
            'Bio',  # Biopython
            'requests',
            'numpy',
            'pandas',
            'ete3',
            'toytree'
        ]
        
        missing_modules = []
        for module in required_modules:
            try:
                __import__(module)
            except ImportError:
                missing_modules.append(module)
        
        if missing_modules:
            self.errors.append(f"缺少必要的Python模块: {', '.join(missing_modules)}")
            return False
        else:
            self.checks.append(f"必要的Python模块已安装: {', '.join(required_modules[:3])}...")  # 只显示前几个
            return True
    
    def check_system_dependencies(self) -> bool:
        """检查系统依赖"""
        system_checks = []
        
        # 检查Visual C++ Redistributable (Windows)
        if platform.system() == 'Windows':
            # 在Windows上检查是否有必要的运行时库
            try:
                import ctypes
                system_checks.append("系统: Windows")
            except:
                self.errors.append("无法访问系统库")
                return False
        else:
            system_checks.append(f"系统: {platform.system()}")
        
        self.checks.extend(system_checks)
        return True
    
    def check_disk_space(self, path: str = None, required_space_gb: float = 1.0) -> bool:
        """检查磁盘空间"""
        if path is None:
            path = os.getcwd()
        
        try:
            import shutil
            total, used, free = shutil.disk_usage(path)
            free_gb = free / (1024**3)
            
            if free_gb < required_space_gb:
                self.errors.append(f"磁盘空间不足。需要至少{required_space_gb}GB，当前可用{free_gb:.2f}GB")
                return False
            else:
                self.checks.append(f"磁盘空间充足: {free_gb:.2f}GB可用")
                return True
        except Exception as e:
            self.warnings.append(f"无法检查磁盘空间: {e}")
            return True  # 不是致命错误
    
    def check_config_file(self) -> bool:
        """检查配置文件是否存在"""
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'config.json')
        
        if os.path.exists(config_path):
            self.checks.append("配置文件存在")
            return True
        else:
            self.warnings.append(f"配置文件不存在: {config_path}")
            return True  # 不是致命错误
    
    def check_module_paths(self) -> bool:
        """检查模块路径是否正确设置"""
        # 检查gui模块是否可以被导入 - 修复导入路径
        try:
            from src.gui.application_pyqt import main
            self.checks.append("src.gui模块可以正常导入")
            return True
        except ImportError as e:
            self.errors.append(f"src.gui模块导入失败: {e}")
            return False
    
    def check_all(self) -> Tuple[bool, List[str], List[str]]:
        """执行所有检查"""
        self.errors = []
        self.warnings = []
        self.checks = []
        
        # 执行所有检查
        results = [
            self.check_python_version(),
            self.check_pyqt(),
            self.check_blast_executables(),
            self.check_required_modules(),
            self.check_system_dependencies(),
            self.check_disk_space(),
            self.check_config_file(),
            self.check_module_paths()  # 添加模块路径检查
        ]
        
        # 如果有任何错误，则整体检查失败
        overall_success = all(results) and len(self.errors) == 0
        
        return overall_success, self.errors, self.warnings
    
    def print_report(self):
        """打印检查报告"""
        success, errors, warnings = self.check_all()
        
        print("="*50)
        print("环境检查报告")
        print("="*50)
        
        print("\n检查项目:")
        for check in self.checks:
            print(f"  ✓ {check}")
        
        if warnings:
            print("\n警告:")
            for warning in warnings:
                print(f"  ⚠ {warning}")
        
        if errors:
            print("\n错误:")
            for error in errors:
                print(f"  ✗ {error}")
        
        print("\n" + "="*50)
        if success:
            print("环境检查通过！程序可以正常启动。")
        else:
            print("环境检查失败！请解决以下问题后重试。")
        print("="*50)
        
        return success


def check_environment() -> bool:
    """检查运行环境是否完整"""
    checker = EnvironmentChecker()
    return checker.print_report()


if __name__ == "__main__":
    check_environment()