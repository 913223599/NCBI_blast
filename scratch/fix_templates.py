import os

def fix_corrupted_templates(directory):
    print(f"Fixing templates in: {directory}")
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith('.vue'):
                path = os.path.join(root, file)
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # 移除错误的转义反斜杠
                    # 寻找 \'left\' 并替换为 'left'
                    new_content = content.replace("\\'left\\'", "'left'")
                    new_content = new_content.replace("\\'right\\'", "'right'")
                    
                    if content != new_content:
                        with open(path, 'w', encoding='utf-8') as f:
                            f.write(new_content)
                        print(f'Fixed template: {path}')
                except Exception as e:
                    print(f'Error: {path} - {e}')

if __name__ == "__main__":
    fix_corrupted_templates(r'd:\NCBI blast\src\web-next\src')
