"""
环境检查模块
用于在程序启动前检查必要的依赖和环境配置
"""

import os
import platform
import sys
from typing import List, Tuple


class EnvironmentChecker:
    """环境检查器"""
    
    def __init__(self):
        self.checks: List[str] = []
        self.errors: List[str] = []
        self.warnings: List[str] = []
    
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
    
    def check_blast_executables(self) -> bool:
        """检查BLAST可执行文件是否存在"""
        import shutil
        blast_commands = ['blastn', 'blastp', 'blastx', 'tblastn', 'makeblastdb']
        found_commands = [cmd for cmd in blast_commands if shutil.which(cmd)]
        
        if found_commands:
            self.checks.append(f"找到BLAST命令: {', '.join(found_commands)}")
            return True
        else:
            self.warnings.append("未找到BLAST命令。如果需要本地BLAST功能，请安装BLAST+套件")
            return True  # 不是错误，只是警告
    
    def check_required_modules(self) -> bool:
        """检查必要的Python模块"""
        required_modules = [
            'Bio',       # Biopython
            'requests',
            'numpy',
            'pandas',
            'fastapi',   # 新架构核心依赖
            'uvicorn',
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
            self.checks.append(f"必要的Python模块已安装: {', '.join(required_modules[:4])}...")
            return True
    
    def check_system_dependencies(self) -> bool:
        """检查系统依赖"""
        self.checks.append(f"系统: {platform.system()} {platform.release()}")
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
        except Exception as exc:
            self.warnings.append(f"无法检查磁盘空间: {exc}")
            return True  # 不是致命错误
    
    def check_electron_shell(self) -> bool:
        """检查 Electron 主进程入口是否存在"""
        electron_main = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            'electron-shell', 'main.js'
        )
        if os.path.exists(electron_main):
            self.checks.append("Electron 主进程入口已就绪")
            return True
        else:
            self.warnings.append(f"未找到 Electron 入口: {electron_main}")
            return True  # 不是致命错误
    
    def check_all(self) -> Tuple[bool, List[str], List[str]]:
        """执行所有检查"""
        self.errors = []
        self.warnings = []
        self.checks = []
        
        results = [
            self.check_python_version(),
            self.check_blast_executables(),
            self.check_required_modules(),
            self.check_system_dependencies(),
            self.check_disk_space(),
            self.check_electron_shell(),
        ]
        
        overall_success = all(results) and len(self.errors) == 0
        return overall_success, self.errors, self.warnings
    
    def print_report(self) -> bool:
        """打印检查报告"""
        success, errors, warnings = self.check_all()
        
        print("=" * 50)
        print("环境检查报告")
        print("=" * 50)
        
        print("\n检查项目:")
        for check in self.checks:
            print(f"  [OK] {check}")
        
        if warnings:
            print("\n警告:")
            for warning in warnings:
                print(f"  [!] {warning}")
        
        if errors:
            print("\n错误:")
            for error in errors:
                print(f"  [X] {error}")
        
        print("\n" + "=" * 50)
        if success:
            print("环境检查通过！程序可以正常启动。")
        else:
            print("环境检查失败！请解决以下问题后重试。")
        print("=" * 50)
        
        return success


def check_environment() -> bool:
    """检查运行环境是否完整"""
    checker = EnvironmentChecker()
    return checker.print_report()


if __name__ == "__main__":
    check_environment()