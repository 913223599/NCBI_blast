#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NCBI BLAST GUI 完整自动化打包脚本 - 修复版本
自动分析项目结构、提取依赖、生成配置并进行打包
支持后续项目迭代时的一键打包
"""

import ast
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Dict, Set, Tuple


class ProjectAnalyzer:
    """项目分析器"""
    
    def __init__(self, project_root: str):
        self.project_root = Path(project_root)
        self.dependencies = set()
        self.data_files = []
        self.hidden_imports = set()
        self.entry_points = []
        self.python_files = []
        
    def analyze_structure(self) -> Dict:
        """分析项目结构"""
        structure = {
            'root': str(self.project_root),
            'directories': [],
            'python_files': [],
            'data_files': [],
            'entry_points': [],
            'modules': set()
        }
        
        for root, dirs, files in os.walk(self.project_root):
            # 跳过不需要的目录
            if any(skip_dir in str(root) for skip_dir in ['__pycache__', 'dist', 'build', '.git', '.vscode']):
                continue
                
            rel_root = Path(root).relative_to(self.project_root)
            structure['directories'].append(str(rel_root))
            
            for file in files:
                file_path = Path(root) / file
                rel_path = file_path.relative_to(self.project_root)
                
                if file.endswith('.py'):
                    structure['python_files'].append(str(rel_path))
                    self.python_files.append(file_path)
                    if self._is_entry_point(file_path):
                        structure['entry_points'].append(str(rel_path))
                        self.entry_points.append(str(rel_path))
                elif self._is_data_file(file):
                    structure['data_files'].append(str(rel_path))
        
        # 分析模块结构
        structure['modules'] = self._analyze_modules(structure['python_files'])
        
        return structure
    
    def _is_entry_point(self, file_path: Path) -> bool:
        """判断是否为主入口文件"""
        try:
            content = file_path.read_text(encoding='utf-8', errors='ignore')
            return '__main__' in content or 'if __name__ == "__main__"' in content
        except (IOError, OSError):
            return False
    
    def _is_data_file(self, filename: str) -> bool:
        """判断是否为数据文件"""
        data_extensions = ['.json', '.csv', '.txt', '.xml', '.yaml', '.yml', '.fasta', '.fa']
        return any(filename.lower().endswith(ext) for ext in data_extensions)
    
    def _analyze_modules(self, python_files: List[str]) -> Set[str]:
        """分析模块结构"""
        modules = set()
        for py_file in python_files:
            parts = Path(py_file).parts
            # 提取模块路径
            for i, part in enumerate(parts):
                if part.endswith('.py'):
                    module_path = '.'.join(parts[:i])
                    if module_path:
                        modules.add(module_path)
                    break
        return modules
    
    def extract_dependencies(self) -> Set[str]:
        """提取项目依赖"""
        self.dependencies = set()
        
        # 遍历所有Python文件
        for py_file in self.project_root.rglob("*.py"):
            # 跳过不需要的目录
            if any(skip_dir in str(py_file) for skip_dir in ['__pycache__', 'dist', 'build', '.git']):
                continue
            try:
                imports = self._extract_imports_from_file(py_file)
                self.dependencies.update(imports)
            except Exception:
                continue
        
        # 过滤掉内置模块和项目内部模块，只保留第三方库
        external_deps = self._filter_external_deps(self.dependencies)
        return external_deps
    
    def _extract_imports_from_file(self, file_path: Path) -> Set[str]:
        """从单个文件中提取导入"""
        imports = set()
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                if content.strip():
                    tree = ast.parse(content)
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            for alias in node.names:
                                imports.add(alias.name.split('.')[0])
                        elif isinstance(node, ast.ImportFrom):
                            if node.module:
                                imports.add(node.module.split('.')[0])
        except Exception:
            pass
        return imports
    
    def _filter_external_deps(self, imports: Set[str]) -> Set[str]:
        """过滤掉内置模块和项目内部模块，只保留第三方库"""
        # Python内置模块列表
        builtin_modules = {
            '__future__', 'abs', 'aifc', 'argparse', 'array', 'ast', 'asynchat', 'asyncio', 'asyncore', 'atexit',
            'audioop', 'base64', 'bdb', 'binary', 'binascii', 'binhex', 'bisect', 'builtins', 'bz2', 'cProfile',
            'calendar', 'cgi', 'cgitb', 'chunk', 'cmath', 'cmd', 'code', 'codecs', 'codeop', 'collections',
            'colorsys', 'compileall', 'concurrent', 'configparser', 'contextlib', 'contextvars', 'copy', 'copyreg',
            'crypt', 'csv', 'ctypes', 'curses', 'dataclasses', 'datetime', 'dbm', 'decimal', 'difflib', 'dis',
            'distutils', 'doctest', 'dummy_threading', 'email', 'encodings', 'ensurepip', 'enum', 'errno', 'faulthandler',
            'fcntl', 'filecmp', 'fileinput', 'fnmatch', 'formatter', 'fractions', 'ftplib', 'functools', 'gc', 'getopt',
            'getpass', 'gettext', 'glob', 'graphlib', 'grp', 'gzip', 'hashlib', 'heapq', 'hmac', 'html', 'http', 'imaplib',
            'imghdr', 'imp', 'importlib', 'inspect', 'io', 'ipaddress', 'itertools', 'json', 'keyword', 'lib2to3', 'linecache',
            'locale', 'logging', 'lzma', 'mailbox', 'mailcap', 'marshal', 'math', 'mimetypes', 'mmap', 'modulefinder',
            'msilib', 'msvcrt', 'multiprocessing', 'netrc', 'nis', 'nntplib', 'numbers', 'operator', 'optparse', 'os',
            'ossaudiodev', 'parser', 'pathlib', 'pdb', 'pickle', 'pickletools', 'pipes', 'pkgutil', 'platform', 'plistlib',
            'poplib', 'posix', 'pprint', 'profile', 'pstats', 'pty', 'pwd', 'py_compile', 'pyclbr', 'pydoc', 'queue',
            'quopri', 'random', 're', 'readline', 'reprlib', 'resource', 'rlcompleter', 'runpy', 'sched', 'secrets',
            'select', 'selectors', 'shelve', 'shlex', 'shutil', 'signal', 'site', 'smtpd', 'smtplib', 'sndhdr', 'socket',
            'socketserver', 'spwd', 'sqlite3', 'sre', 'sre_compile', 'sre_constants', 'sre_parse', 'ssl', 'stat', 'statistics',
            'string', 'stringprep', 'struct', 'subprocess', 'sunau', 'symbol', 'symtable', 'sys', 'sysconfig', 'syslog',
            'tabnanny', 'tarfile', 'telnetlib', 'tempfile', 'termios', 'test', 'textwrap', 'threading', 'time', 'timeit',
            'tkinter', 'token', 'tokenize', 'trace', 'traceback', 'tracemalloc', 'tty', 'turtle', 'turtledemo', 'types',
            'typing', 'unicodedata', 'unittest', 'urllib', 'uu', 'uuid', 'venv', 'warnings', 'wave', 'weakref', 'webbrowser',
            'winreg', 'winsound', 'wsgiref', 'xdrlib', 'xml', 'xmlrpc', 'zipapp', 'zipfile', 'zipimport', 'zlib', 'zoneinfo'
        }
        
        # 项目内部模块
        project_modules = {'src', 'gui', 'utils', 'blast', 'widgets', 'threads', 'translation', 'main_window_pyqt', 
                          'application_pyqt', 'file_handler', 'config_manager', 'environment_checker', 'taxonomy_parser',
                          'hash_checker', 'term_extractor', 'biology_translator', 'qwen_translator', 'blast_result_translator',
                          'batch_processor', 'executor', 'local_blast', 'parser', 'result_cache', 'result_converter',
                          'processing_thread', 'api_key_dialog', 'control_panel', 'file_selector', 'help_dialog',
                          'parameter_settings', 'result_viewer', 'settings_dialog', 'summary_panel', 'translation_debugger',
                          'gui_main_pyqt', 'main', 'gui_main_packaged'}
        
        # 真正的第三方库
        third_party_libs = {
            'PyQt6', 'PyQt5', 'PySide2', 'PySide6', 'bio', 'Bio', 'biopython', 'requests', 'numpy', 'pandas', 'matplotlib',
            'scipy', 'sklearn', 'tensorflow', 'torch', 'keras', 'lxml', 'beautifulsoup4', 'openai', 'pillow', 'PIL',
            'flask', 'django', 'fastapi', 'sqlalchemy', 'psycopg2', 'mysql-connector-python', 'redis', 'celery',
            'click', 'flask-sqlalchemy', 'flask-login', 'pyjwt', 'cryptography', 'paramiko', 'fabric', 'ansible',
            'jupyter', 'notebook', 'ipython', 'matplotlib', 'seaborn', 'plotly', 'bokeh', 'dash', 'streamlit',
            'selenium', 'playwright', 'requests-html', 'scrapy', 'beautifulsoup4', 'lxml', 'feedparser', 'html5lib',
            'openpyxl', 'pandas', 'numpy', 'scipy', 'matplotlib', 'seaborn', 'plotly', 'xgboost', 'lightgbm', 'catboost',
            'nltk', 'spacy', 'gensim', 'textblob', 'pattern', 'polyglot', 'stanza', 'allennlp', 'transformers',
            'opencv-python', 'cv2', 'imageio', 'scikit-image', 'pillow', 'PIL', 'imutils', 'face-recognition',
            'pytesseract', 'pyocr', 'easyocr', 'paddleocr', 'pyttsx3', 'speechRecognition', 'vosk', 'webrtcvad',
            'pygame', 'arcade', 'kivy', 'pyglet', 'panda3d', 'ursina', 'tkinter', 'kinter', 'wxpython', 'pyqt5', 'pyside2'
        }
        
        # 只保留第三方库
        external_deps = set()
        for imp in imports:
            if imp in third_party_libs or (imp.lower() in [x.lower() for x in third_party_libs]):
                external_deps.add(imp)
            elif imp not in builtin_modules and imp not in project_modules:
                # 对于不确定的模块，我们保守地加入，但需要特别注意
                if imp not in ['ssl', 'tempfile', 'shutil', 'traceback', 'io', 'concurrent', 'glob']:
                    external_deps.add(imp)
        
        return external_deps
    
    def find_data_files(self) -> List[Tuple[str, str]]:
        """查找数据文件"""
        self.data_files = []
        
        # 定义数据文件模式
        data_patterns = [
            ("*.json", "."),
            ("*.csv", "."),
            ("*.txt", "."),
            ("src/utils/translation/*", "src/utils/translation"),
            ("predefined_terms.csv", "."),
            ("translation_data.csv", "."),
            ("*.fasta", "."),
            ("*.fa", "."),
        ]
        
        for pattern, dest_dir in data_patterns:
            for file_path in self.project_root.glob(pattern):
                if file_path.is_file():
                    # 确保不是在dist或build目录中
                    if 'dist' not in str(file_path) and 'build' not in str(file_path):
                        rel_path = str(file_path.relative_to(self.project_root))
                        self.data_files.append((rel_path, dest_dir))
        
        # 查找子目录中的数据文件
        for pattern, dest_dir in data_patterns:
            for file_path in self.project_root.rglob(pattern):
                if file_path.is_file():
                    # 确保不是在dist或build目录中
                    if 'dist' not in str(file_path) and 'build' not in str(file_path):
                        rel_path = str(file_path.relative_to(self.project_root))
                        # 确保不重复添加
                        if (rel_path, dest_dir) not in self.data_files:
                            self.data_files.append((rel_path, dest_dir))
        
        return self.data_files
    
    def generate_hidden_imports(self) -> List[str]:
        """生成隐藏导入列表"""
        self.hidden_imports = set()
        
        # 添加项目特定的模块
        for py_file in self.project_root.rglob("*.py"):
            # 跳过不需要的目录
            if any(skip_dir in str(py_file) for skip_dir in ['__pycache__', 'dist', 'build', '.git']):
                continue
                
            rel_path = py_file.relative_to(self.project_root)
            if not str(rel_path).startswith('__pycache__'):
                # 转换文件路径为模块路径
                parts = [part for part in rel_path.parts if part != '__init__.py' and not part.endswith('.py')]
                
                if rel_path.name != '__init__.py' and rel_path.suffix == '.py':
                    module_name = rel_path.stem
                else:
                    module_name = ''
                
                if parts:
                    if module_name:
                        full_module = '.'.join(parts + [module_name])
                    else:
                        full_module = '.'.join(parts)
                elif module_name:
                    full_module = module_name
                else:
                    continue
                
                if full_module and not full_module.startswith('.'):
                    self.hidden_imports.add(full_module)
        
        # 添加常见的隐藏导入
        common_hidden_imports = [
            'src',
            'src.gui',
            'src.gui.application_pyqt',
            'src.blast',
            'src.utils',
            'src.utils.translation',
            'src.utils.environment_checker',
            'Bio',
            'Bio.Blast',
            'Bio.SeqIO',
            'requests',
            'pandas',
            'lxml',
            'xml.etree.ElementTree',
        ]
        
        self.hidden_imports.update(common_hidden_imports)
        return list(self.hidden_imports)


def verify_entry_point(project_root: Path) -> bool:
    """验证主入口文件是否存在"""
    entry_point = project_root / "src" / "gui_main_packaged.py"
    if not entry_point.exists():
        print(f"错误: 主入口文件不存在: {entry_point}")
        # 尝试寻找其他可能的入口文件
        possible_entries = list(project_root.rglob("*main*.py")) + list(project_root.rglob("*Main*.py"))
        if possible_entries:
            print("可能的入口文件:")
            for entry in possible_entries:
                print(f"  - {entry}")
        return False
    return True


def generate_spec_file(project_analyzer: ProjectAnalyzer, output_name: str = "NCBI_BLAST_GUI") -> str:
    """生成PyInstaller spec文件"""
    
    # 获取分析结果
    data_files = project_analyzer.find_data_files()
    hidden_imports = project_analyzer.generate_hidden_imports()
    
    # 构建spec文件内容，使用原始字符串来避免转义问题
    spec_content = f'# -*- mode: python ; coding: utf-8 -*-\n'
    spec_content += '"""\n'
    spec_content += f'自动生成的 PyInstaller spec 文件\n'
    spec_content += f'用于打包 {output_name} 应用\n'
    # 修复项目根目录路径的转义问题
    project_root_fixed = str(project_analyzer.project_root).replace('\\', '/').replace("'", "\\'")
    spec_content += f'项目根目录: {project_root_fixed}\n'
    spec_content += '"""\n\n'
    spec_content += 'block_cipher = None\n\n'
    spec_content += '# 数据文件\ndatas = [\n'
    
    for src, dst in data_files:
        # 确保路径使用正斜杠并用双反斜杠转义
        src_fixed = str(src).replace('\\', '/').replace("'", "\\'")
        dst_fixed = str(dst).replace('\\', '/').replace("'", "\\'")
        spec_content += f"    (r'{src_fixed}', r'{dst_fixed}'),\n"
    
    spec_content += '    \n]\n\n'
    spec_content += '# 隐藏导入\nhiddenimports = [\n'
    
    for imp in sorted(hidden_imports):
        # 确保导入名称正确处理
        imp_fixed = str(imp).replace("'", "\\'")
        spec_content += f"    r'{imp_fixed}',\n"
    
    spec_content += '    \n]\n\n'
    spec_content += 'a = Analysis(\n'
    spec_content += "    [r'src/gui_main_packaged.py'],  # 主入口文件\n"
    spec_content += f"    pathex=[r'{str(Path('.').resolve()).replace('\\', '/')}/'],  # 当前目录作为路径扩展\n"
    spec_content += "    binaries=[],  # 二进制文件，通常为空\n"
    spec_content += "    datas=datas,  # 数据文件\n"
    spec_content += "    hiddenimports=hiddenimports,  # 隐藏导入\n"
    spec_content += "    hookspath=[],  # 额外的hook路径\n"
    spec_content += "    hooksconfig={},  # hook配置\n"
    spec_content += "    runtime_hooks=[],  # 运行时hook\n"
    spec_content += "    excludes=[  # 排除的模块\n"
    spec_content += "        'tkinter',\n"
    spec_content += "        'matplotlib',\n"
    spec_content += "        'PyQt5',\n"
    spec_content += "        'PySide2',\n"
    spec_content += "        'tensorflow',\n"
    spec_content += "        'torch',\n"
    spec_content += "        'keras',\n"
    spec_content += "        'scipy.spatial.cKDTree',\n"
    spec_content += "        'sklearn',\n"
    spec_content += "    ],\n"
    spec_content += "    win_no_prefer_redirects=False,\n"
    spec_content += "    win_private_assemblies=False,\n"
    spec_content += "    cipher=block_cipher,\n"
    spec_content += "    noarchive=False,  # 不使用归档\n"
    spec_content += ")\n\n"
    spec_content += "pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)\n\n"
    spec_content += "exe = EXE(\n"
    spec_content += "    pyz,\n"
    spec_content += "    a.scripts,  # 脚本\n"
    spec_content += "    a.binaries,  # 二进制文件\n"
    spec_content += "    a.zipfiles,  # zip文件\n"
    spec_content += "    a.datas,  # 数据文件\n"
    spec_content += "    [],  # 选项\n"
    spec_content += f"    name={repr(output_name)},  # 可执行文件名\n"
    spec_content += "    debug=False,  # 调试模式\n"
    spec_content += "    bootloader_ignore_signals=False,  # 忽略引导程序信号\n"
    spec_content += "    strip=False,  # 是否strip\n"
    spec_content += "    upx=True,  # UPX压缩\n"
    spec_content += "    upx_exclude=[],  # UPX排除\n"
    spec_content += "    runtime_tmpdir=None,  # 运行时临时目录\n"
    spec_content += "    console=False,  # 控制台模式，False表示窗口模式\n"
    spec_content += "    disable_windowed_traceback=False,  # 禁用窗口模式回溯\n"
    spec_content += "    argv_emulation=False,  # 参数模拟\n"
    spec_content += "    target_arch=None,  # 目标架构\n"
    spec_content += "    codesign_identity=None,  # 代码签名标识\n"
    spec_content += "    entitlements_file=None,  # 权限文件\n"
    spec_content += "    icon=None,  # 图标文件\n"
    spec_content += ")\n\n"
    spec_content += "coll = COLLECT(\n"
    spec_content += "    exe,\n"
    spec_content += "    a.binaries,\n"
    spec_content += "    a.zipfiles,\n"
    spec_content += "    a.datas,\n"
    spec_content += "    strip=False,\n"
    spec_content += "    upx=True,\n"
    spec_content += "    upx_exclude=[],\n"
    spec_content += f"    name={repr(output_name)},  # 收集目录名\n"
    spec_content += ")\n"
    
    return spec_content


def create_requirements_txt(project_analyzer: ProjectAnalyzer):
    """创建requirements.txt文件"""
    dependencies = project_analyzer.extract_dependencies()
    
    # 映射常见库到标准名称和版本
    dep_mapping = {
        'PyQt6': 'PyQt6>=6.4.0',
        'Bio': 'biopython>=1.80',
        'requests': 'requests>=2.28.0',
        'numpy': 'numpy>=1.21.0',
        'pandas': 'pandas>=1.5.0',
        'lxml': 'lxml>=4.9.0',
        'openai': 'openai>=0.27.0',
    }
    
    req_content = "# 自动生成的依赖文件\n"
    for dep in dependencies:
        if dep in dep_mapping:
            req_content += dep_mapping[dep] + "\n"
        elif dep.lower() in [k.lower() for k in dep_mapping.keys()]:
            # 大小写匹配
            for orig_key, mapped_value in dep_mapping.items():
                if orig_key.lower() == dep.lower():
                    req_content += mapped_value + "\n"
                    break
        # 对于不在映射中的依赖，可以考虑添加，但需要谨慎
        # 这里我们只添加明确知道的第三方库
        elif dep in ['xml', 'urllib', 'os', 'sys', 'json', 'csv', 'pathlib', 're', 'datetime', 'time', 'threading', 'logging', 'dataclasses', 'typing', 'queue', 'hashlib', 'platform', 'ctypes', 'ssl', 'tempfile', 'shutil', 'traceback', 'io', 'concurrent', 'glob']:
            # 这些是内置模块，跳过
            continue
        else:
            # 对于不确定的依赖，暂时跳过
            print(f"跳过可能的内部模块: {dep}")
    
    with open("requirements.txt", "w", encoding="utf-8") as f:
        f.write(req_content)


def install_dependencies():
    """安装依赖"""
    print("正在安装依赖...")
    try:
        # 检查requirements.txt是否存在
        if not Path("requirements.txt").exists():
            print("警告: requirements.txt不存在，跳过依赖安装")
            return True
            
        result = subprocess.run([
            sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "--quiet"
        ], check=True, capture_output=True, text=True)
        print("依赖安装完成")
        return True
    except subprocess.CalledProcessError as e:
        print(f"依赖安装失败: {e}")
        if hasattr(e, 'stderr'):
            print(f"错误输出: {e.stderr}")
        return False
    except FileNotFoundError:
        print("错误: 未找到pip，请确保已安装Python")
        return False


def run_pyinstaller(spec_file: str):
    """运行PyInstaller"""
    print(f"正在使用 {spec_file} 打包应用...")
    try:
        # 首先验证spec文件语法
        print("正在验证spec文件语法...")
        result_syntax = subprocess.run([
            sys.executable, "-m", "py_compile", spec_file
        ], check=True, capture_output=True, text=True, encoding='utf-8')
        print("spec文件语法验证通过")
        
        # 使用二进制模式捕获输出，然后手动解码以避免字符编码问题
        result = subprocess.run([
            sys.executable, "-m", "PyInstaller", spec_file, "--clean"
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        
        # 解码输出时处理可能的编码问题
        stdout_str = result.stdout.decode('utf-8', errors='replace')
        stderr_str = result.stderr.decode('utf-8', errors='replace')
        
        print("打包完成")
        print("详细输出:", stdout_str[-500:] if len(stdout_str) > 500 else stdout_str)  # 只显示最后500个字符
        return True
    except subprocess.CalledProcessError as e:
        print(f"打包失败: {e}")
        # 处理可能的输出解码
        try:
            stderr_str = e.stderr.decode('utf-8', errors='replace') if isinstance(e.stderr, bytes) else str(e.stderr)
        except AttributeError:
            stderr_str = str(e.stderr) if e.stderr else "未知错误"
        print(f"错误输出: {stderr_str}")
        return False
    except FileNotFoundError:
        print("错误: 未找到PyInstaller，请先安装PyInstaller: pip install pyinstaller")
        return False


def backup_existing_dist():
    """备份现有的dist目录"""
    import shutil
    import time
    
    dist_path = Path("dist")
    if dist_path.exists():
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        backup_name = f"dist_backup_{timestamp}"
        print(f"备份现有dist目录到 {backup_name}")
        shutil.move(dist_path, backup_name)


def main():
    """主函数"""
    print("NCBI BLAST GUI 完整自动化打包工具")
    print("=" * 60)
    
    # 检查Python版本
    import sys
    if sys.version_info < (3, 7):
        print("错误: 需要Python 3.7或更高版本")
        return False
    
    # 检查PyInstaller是否已安装
    try:
        import PyInstaller
        print(f"PyInstaller 版本: {PyInstaller.__version__}")
    except ImportError:
        print("警告: PyInstaller未安装，将尝试安装...")
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)
            import PyInstaller
            print(f"PyInstaller 已安装，版本: {PyInstaller.__version__}")
        except Exception as e:
            print(f"PyInstaller安装失败: {e}")
            return False
    
    # 初始化项目分析器
    project_root = Path(__file__).parent
    analyzer = ProjectAnalyzer(project_root)
    
    # 验证入口点
    print("0. 验证主入口文件...")
    if not verify_entry_point(project_root):
        print("   - 入口文件验证失败，退出")
        return False
    
    print("1. 正在分析项目结构...")
    try:
        structure = analyzer.analyze_structure()
        print(f"   - 找到 {len(structure['python_files'])} 个Python文件")
        print(f"   - 找到 {len(structure['data_files'])} 个数据文件")
        print(f"   - 找到 {len(structure['entry_points'])} 个入口点")
        print(f"   - 项目模块: {len(structure['modules'])} 个")
    except Exception as e:
        print(f"   - 项目结构分析失败: {e}")
        return False
    
    print("\n2. 正在提取项目依赖...")
    try:
        dependencies = analyzer.extract_dependencies()
        print(f"   - 提取到 {len(dependencies)} 个外部依赖")
        print(f"   - 依赖列表: {list(dependencies)}")
    except Exception as e:
        print(f"   - 依赖提取失败: {e}")
        return False
    
    print("\n3. 正在查找数据文件...")
    try:
        data_files = analyzer.find_data_files()
        print(f"   - 找到 {len(data_files)} 个数据文件")
    except Exception as e:
        print(f"   - 数据文件查找失败: {e}")
        return False
    
    print("\n4. 正在生成隐藏导入...")
    try:
        hidden_imports = analyzer.generate_hidden_imports()
        print(f"   - 生成 {len(hidden_imports)} 个隐藏导入")
    except Exception as e:
        print(f"   - 隐藏导入生成失败: {e}")
        return False
    
    print("\n5. 生成 spec 文件...")
    try:
        spec_content = generate_spec_file(analyzer, "NCBI_BLAST_GUI")
        spec_file = "auto_build.spec"
        with open(spec_file, "w", encoding="utf-8") as f:
            f.write(spec_content)
        print(f"   - spec 文件已生成: {spec_file}")
    except Exception as e:
        print(f"   - spec文件生成失败: {e}")
        return False
    
    print("\n6. 生成 requirements.txt...")
    try:
        create_requirements_txt(analyzer)
        print("   - requirements.txt 已生成")
    except Exception as e:
        print(f"   - requirements.txt生成失败: {e}")
        return False
    
    print("\n7. 备份现有打包结果...")
    try:
        backup_existing_dist()
    except Exception as e:
        print(f"   - 备份失败: {e}")
        return False
    
    print("\n8. 安装依赖...")
    if not install_dependencies():
        print("   - 依赖安装失败，退出")
        return False
    
    print("\n9. 开始打包...")
    if not run_pyinstaller(spec_file):
        print("   - 打包失败")
        return False
    
    print("\n" + "=" * 60)
    print("✅ 打包完成！")
    print("📁 输出目录: dist/")
    print("🎯 可执行文件: dist/NCBI_BLAST_GUI/NCBI_BLAST_GUI.exe")
    print("📋 打包文件: auto_build.spec")
    print("📋 依赖文件: requirements.txt")
    print("\n💡 提示: 可以将整个 dist/NCBI_BLAST_GUI 目录分发给用户")
    
    return True


if __name__ == "__main__":
    success = main()
    if success:
        print("\n🎉 自动打包成功完成！")
    else:
        print("\n❌ 自动打包失败，请检查错误信息。")
        sys.exit(1)