"""
项目全量代码质量检查与自动修复脚本
检查项：
1. JSON 文件中的非法注释（// 和 /* */）
2. JSON 文件中的尾部逗号
3. Python 文件中的未使用导入（import os, sys 等）
4. 其他常见语法/格式问题
"""
import ast
import json
import re
from pathlib import Path
from typing import List


class ProjectFixer:
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.exclude_dirs = {'node_modules', '.git', 'dist', 'build', 'test', '.vscode', '.idea', '__pycache__'}
        self.fixed_files = []
        self.error_files = []
        self.skipped_files = []
        
    def is_excluded(self, filepath: Path) -> bool:
        """检查文件是否在排除目录中"""
        return any(exclude_dir in filepath.parts for exclude_dir in self.exclude_dirs)
    
    def fix_json_comments(self, filepath: Path) -> bool:
        """修复 JSON 文件中的注释"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            original = content
            # 移除多行注释
            content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
            # 移除单行注释
            content = re.sub(r'//.*$', '', content, flags=re.MULTILINE)
            
            if content == original:
                return False
            
            # 验证 JSON 合法性
            json.loads(content)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            return True
        except Exception as e:
            print(f"  ❌ JSON注释修复失败 {filepath}: {e}")
            return False
    
    def fix_json_trailing_commas(self, filepath: Path) -> bool:
        """修复 JSON 文件中的尾部逗号"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            original = content
            # 移除对象和数组中的尾部逗号
            content = re.sub(r',\s*([}\]])', r'\1', content)
            
            if content == original:
                return False
            
            # 验证 JSON 合法性
            json.loads(content)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            return True
        except Exception as e:
            print(f"  ❌ JSON尾部逗号修复失败 {filepath}: {e}")
            return False
    
    def check_python_unused_imports(self, filepath: Path) -> List[str]:
        """检查 Python 文件中的未使用导入"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 使用 AST 解析
            tree = ast.parse(content, filename=str(filepath))
            
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append((alias.name, alias.asname or alias.name))
                elif isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        imports.append((alias.name, alias.asname or alias.name))
            
            # 查找未使用的导入
            unused = []
            for name, alias in imports:
                # 跳过常见的必要导入
                if name in {'__future__', 'typing'}:
                    continue
                
                # 检查别名是否在代码中使用
                # 简单检查：如果别名只出现在 import 语句中，则未使用
                pattern = rf'\b{re.escape(alias)}\b'
                matches = list(re.finditer(pattern, content))
                
                # 如果只出现一次（就是 import 本身），则认为未使用
                import_count = sum(1 for line in content.split('\n') if re.search(pattern, line))
                if import_count == 1:
                    unused.append(name)
            
            return unused
        except SyntaxError:
            return []
        except Exception:
            return []
    
    def fix_python_file(self, filepath: Path) -> bool:
        """修复 Python 文件中的问题"""
        unused_imports = self.check_python_unused_imports(filepath)
        if not unused_imports:
            return False
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            # 移除未使用的导入行
            new_lines = []
            removed_count = 0
            for line in lines:
                should_remove = False
                for imp in unused_imports:
                    # 匹配 import 语句
                    if re.match(rf'^\s*import\s+{re.escape(imp)}\s*$', line):
                        should_remove = True
                        break
                    if re.match(rf'^\s*from\s+\S+\s+import\s+.*\b{re.escape(imp)}\b', line):
                        # 处理 from x import y 的情况
                        should_remove = True
                        break
                
                if not should_remove:
                    new_lines.append(line)
                else:
                    removed_count += 1
            
            if removed_count > 0:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.writelines(new_lines)
                return True
            return False
        except Exception as e:
            print(f"  ❌ Python修复失败 {filepath}: {e}")
            return False
    
    def scan_and_fix(self):
        """扫描并修复项目中的所有文件"""
        print(f"🔍 开始扫描项目目录: {self.project_root}")
        print("=" * 60)
        
        # 1. 扫描 JSON 文件
        print("\n📄 检查 JSON 文件...")
        for json_file in self.project_root.rglob('*.json'):
            if self.is_excluded(json_file):
                continue
            
            # 跳过 lock 文件
            if json_file.name.endswith('-lock.json') or json_file.name == 'package-lock.json':
                self.skipped_files.append(json_file)
                continue
            
            fixed = False
            if self.fix_json_comments(json_file):
                print(f"  ✅ 修复JSON注释: {json_file.relative_to(self.project_root)}")
                fixed = True
            
            if self.fix_json_trailing_commas(json_file):
                print(f"  ✅ 修复JSON尾部逗号: {json_file.relative_to(self.project_root)}")
                fixed = True
            
            if fixed:
                self.fixed_files.append(json_file)
        
        # 2. 扫描 Python 文件
        print("\n🐍 检查 Python 文件...")
        for py_file in self.project_root.rglob('*.py'):
            if self.is_excluded(py_file):
                continue
            
            if self.fix_python_file(py_file):
                print(f"  ✅ 修复Python导入: {py_file.relative_to(self.project_root)}")
                self.fixed_files.append(py_file)
        
        # 打印统计信息
        print("\n" + "=" * 60)
        print("📊 修复统计:")
        print(f"  ✅ 成功修复: {len(self.fixed_files)} 个文件")
        print(f"  ⏭️  跳过: {len(self.skipped_files)} 个文件")
        print(f"  📁 检查的JSON: {len(list(self.project_root.rglob('*.json')))}")
        print(f"   检查的Python: {len(list(self.project_root.rglob('*.py')))}")

def main():
    # 自动定位项目根目录，避免硬编码盘符
    project_root = Path(__file__).resolve().parents[2]
    fixer = ProjectFixer(project_root)
    fixer.scan_and_fix()

if __name__ == '__main__':
    main()
