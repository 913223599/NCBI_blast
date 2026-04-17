import os
from pathlib import Path

def run():
    src_dir = Path(__file__).resolve().parents[2] / "src" / "web-next" / "src"
    count = 0
    for root, dirs, files in os.walk(src_dir):
        for name in files:
            if name.endswith((".ts", ".vue")):
                path = os.path.join(root, name)
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                
                new_content = content.replace("'../bridge/pyqt-bridge'", "'../bridge'")
                new_content = new_content.replace("'./bridge/pyqt-bridge'", "'./bridge'")
                new_content = new_content.replace('"../bridge/pyqt-bridge"', '"../bridge"')
                new_content = new_content.replace('"./bridge/pyqt-bridge"', '"./bridge"')
                
                new_content = new_content.replace("'../bridge/pyqt-bridge.ts'", "'../bridge'")
                new_content = new_content.replace("'./bridge/pyqt-bridge.ts'", "'./bridge'")
                
                if new_content != content:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(new_content)
                    print(f"Updated: {path}")
                    count += 1
    print(f"Total updated files: {count}")

if __name__ == "__main__":
    run()
