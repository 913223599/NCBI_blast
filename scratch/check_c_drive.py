import os

def get_size(start_path = 'C:\\'):
    total_size = 0
    try:
        for dirpath, dirnames, filenames in os.walk(start_path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                # skip if it is symbolic link
                if not os.path.islink(fp):
                    total_size += os.path.getsize(fp)
            # Only go one level deep for general view
            break 
    except Exception:
        pass
    return total_size

paths = [
    'C:\\Windows',
    'C:\\Program Files',
    'C:\\Program Files (x86)',
    'C:\\Users',
    'C:\\ProgramData'
]

print(f"{'Path':<30} {'Size (GB)':<10}")
print("-" * 40)

for p in paths:
    if os.path.exists(p):
        # We need a recursive size for these
        # But walking the whole C:\Windows is slow.
        # Let's use 'du' equivalent logic but limited
        pass

# Actually, let's just use shell commands to get folder sizes quickly
# du -sh in WSL for C drive folders is actually quite fast for metadata
