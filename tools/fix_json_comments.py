import json
import re
from pathlib import Path

def strip_json_comments(json_str):
    """移除 JSON 字符串中的注释（// 和 /* */）"""
    # 使用正则表达式匹配并移除注释
    # 注意：这不会处理字符串内的注释，但对于配置文件通常足够
    # 移除多行注释
    json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)
    # 移除单行注释
    json_str = re.sub(r'//.*$', '', json_str, flags=re.MULTILINE)
    return json_str

def fix_json_file(filepath):
    """修复单个 JSON 文件"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 检查是否包含注释
        has_comments = bool(re.search(r'//|/\*', content))
        if not has_comments:
            return False
        
        # 移除注释
        cleaned_content = strip_json_comments(content)
        
        # 验证是否为合法 JSON
        json.loads(cleaned_content)
        
        # 写回文件
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(cleaned_content)
        
        return True
    except json.JSONDecodeError as e:
        print(f"  ❌ {filepath}: JSON 解析失败 - {e}")
        return False
    except Exception as e:
        print(f"  ❌ {filepath}: 处理失败 - {e}")
        return False

def main():
    """主函数：扫描并修复项目中的所有 JSON 文件"""
    project_root = Path(__file__).parent.parent  # D:\NCBI blast
    print(f"🔍 正在扫描项目目录: {project_root}")
    
    fixed_count = 0
    error_count = 0
    skipped_count = 0
    
    # 排除目录
    exclude_dirs = {'node_modules', '.git', 'dist', 'build', 'test', '.vscode', '.idea'}
    
    for json_file in project_root.rglob('*.json'):
        # 跳过排除目录
        if any(exclude_dir in json_file.parts for exclude_dir in exclude_dirs):
            continue
        
        # 跳过 lock 文件（通常很大且由工具生成）
        if json_file.name.endswith('-lock.json') or json_file.name == 'package-lock.json':
            skipped_count += 1
            continue
        
        try:
            result = fix_json_file(json_file)
            if result:
                print(f"  ✅ 已修复: {json_file.relative_to(project_root)}")
                fixed_count += 1
        except Exception as e:
            print(f"  ❌ {json_file.relative_to(project_root)}: {e}")
            error_count += 1
    
    print(f"\n📊 修复完成:")
    print(f"  ✅ 成功修复: {fixed_count} 个文件")
    print(f"  ❌ 失败: {error_count} 个文件")
    print(f"  ⏭️  跳过: {skipped_count} 个文件 (lock 文件)")

if __name__ == '__main__':
    main()
