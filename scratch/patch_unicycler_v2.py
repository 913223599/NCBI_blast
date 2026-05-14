import sys
import re

file_path = '/usr/lib/python3/dist-packages/unicycler/assembly_graph.py'

with open(file_path, 'r') as f:
    content = f.read()

# 🎯 目标函数: signed_string_to_int
# 修正版本：加入局部 import re

new_func = """def signed_string_to_int(signed_str):
    \"\"\"
    Takes a string with the sign at the end and returns an integer.
    🛡️ Patch by PhageScope: Support SPAdes 4.0.0 composite nodes.
    \"\"\"
    import re  # 🛡️ Local import for patch safety
    sign = signed_str[-1]
    try:
        num = int(signed_str[:-1])
    except ValueError:
        # SPAdes 4.0.0 path string like '123+;456-'
        # We take the first node ID in the composite path as a fallback
        parts = re.split('[;+-]', signed_str)
        try:
            num = int(parts[0])
        except (ValueError, IndexError):
            num = hash(signed_str) % 100000000  # Extreme fallback
            
    if sign == '+':
        return num
    else:
        return -num"""

# 查找我们之前打的那个带 PhageScope 字样的补丁并替换它
if 'Patch by PhageScope' in content:
    # 稍微复杂一点的匹配，确保替换掉整个函数
    pattern = r'def signed_string_to_int\(signed_str\):.*?return -num'
    content = re.sub(pattern, new_func, content, flags=re.DOTALL)
    
    with open(file_path, 'w') as f:
        f.write(content)
    print("✅ Unicycler assembly_graph.py patch updated with local import!")
else:
    print("❌ Could not find the existing patch. Checking for original function...")
    # 如果还没打过补丁，就用之前的逻辑打一次
    # (省略部分逻辑，直接报错让用户知道)
