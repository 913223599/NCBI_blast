import os
import re

def clean_styles(directory):
    patterns = [
        r'box-shadow\s*:\s*.*?;',
        r'backdrop-filter\s*:\s*.*?;',
        r'-webkit-backdrop-filter\s*:\s*.*?;'
    ]
    
    file_count = 0
    change_count = 0
    
    if not os.path.exists(directory):
        print(f'Directory NOT FOUND: {directory}')
        return

    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith(('.vue', '.css', '.ts')):
                path = os.path.join(root, file)
                # Keep the global.css reset rule intact
                if 'global.css' in path: continue
                
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                    
                    new_lines = []
                    modified = False
                    for line in lines:
                        original_line = line
                        for p in patterns:
                            line = re.sub(p, '', line, flags=re.IGNORECASE)
                        
                        # If the line was not empty but after removal it is effectively pure whitespace,
                        # and it wasn't just a closing brace or something, we can consider it modified.
                        # Actually, a safer way is to just replace the property with an empty string.
                        
                        if line != original_line:
                            modified = True
                        
                        # If the line becomes empty after trimming, but wasn't before, we might want to skip it
                        # to avoid leaving blank lines. But let's keep it simple for now and just check if changed.
                        new_lines.append(line)
                    
                    if modified:
                        with open(path, 'w', encoding='utf-8') as f:
                            f.writelines(new_lines)
                        print(f'Cleaned: {path}')
                        change_count += 1
                    file_count += 1
                except Exception as e:
                    print(f'Error processing {path}: {e}')
    
    print(f'\nTotal files scanned: {file_count}')
    print(f'Total files modified: {change_count}')

if __name__ == "__main__":
    target_dir = Path(__file__).resolve().parents[2] / "src" / "web-next" / "src"
    clean_styles(target_dir)
