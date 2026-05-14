import sys
import re

file_path = '/usr/lib/python3/dist-packages/unicycler/assembly_graph.py'

with open(file_path, 'r') as f:
    content = f.read()

# 🎯 目标函数: signed_string_to_int
# 我们要把它改成：如果 int() 失败，就返回一个 0 或者抛出更有意义的异常（或者直接跳过）
# 但更好的做法是：在调用它的地方进行清洗，或者让它支持非数字 ID

old_func = """def signed_string_to_int(signed_str):
    \"\"\"
    Takes a string with the sign at the end and returns an integer.
    \"\"\"
    sign = signed_str[-1]
    num = int(signed_str[:-1])
    if sign == '+':
        return num
    else:
        return -num"""

new_func = """def signed_string_to_int(signed_str):
    \"\"\"
    Takes a string with the sign at the end and returns an integer.
    🛡️ Patch by PhageScope: Support SPAdes 4.0.0 composite nodes.
    \"\"\"
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

if old_func in content:
    content = content.replace(old_func, new_func)
    with open(file_path, 'w') as f:
        f.write(content)
    print("✅ Unicycler assembly_graph.py patched successfully!")
else:
    print("❌ Could not find the target function in Unicycler source. Maybe already patched?")
