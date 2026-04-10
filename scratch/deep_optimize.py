import os
import re

def deep_optimize_css(directory):
    print(f"Scanning directory: {directory}")
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith(('.vue', '.css')):
                path = os.path.join(root, file)
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    new_content = content
                    
                    # 针对进度条的动画优化 (从 width 改为 transform)
                    # 处理 Vue 模板中的动态 style
                    new_content = re.sub(r':style="\{\s*width\s*:\s*(getFreezerUsageRate\(freezer\)|getTypePercentage\(.+?\))\s*\+\s*\'%\'\s*\}"', 
                                         r':style="{ transform: `scaleX(${(\1) / 100})`, transformOrigin: \'left\' }"', new_content)
                    
                    # 针对进度条 CSS (StatisticsPanel 等)
                    new_content = re.sub(r'transition\s*:\s*width\s+([^;]+);', r'transition: transform \1; transform-origin: left;', new_content)

                    # 给所有 transition 添加 GPU 提示，防止重绘闪烁
                    # re.sub(r'(transition\s*:\s*[^;]+;)(?!\s*backface-visibility)', ...) 
                    # 用简单循环处理
                    lines = new_content.splitlines()
                    optimized_lines = []
                    for line in lines:
                        if 'transition:' in line and 'backface-visibility' not in line:
                            # 在分号前插入
                            line = line.replace(';', '; backface-visibility: hidden; -webkit-backface-visibility: hidden;')
                        optimized_lines.append(line)
                    new_content = "\n".join(optimized_lines)

                    if content != new_content:
                        with open(path, 'w', encoding='utf-8') as f:
                            f.write(new_content)
                        print(f'Enhanced: {path}')
                except Exception as e:
                    print(f'Error: {path} - {e}')

if __name__ == "__main__":
    deep_optimize_css(r'd:\NCBI blast\src\web-next\src')
