import glob
from pathlib import Path

DOCS_ROOT = Path(r"d:\PycharmProjects\NCBI blast\tools\docs\detailed")

def scan_errors():
    files = list(DOCS_ROOT.glob("*.txt"))
    error_files = []
    
    for f in files:
        with open(f, 'r', encoding='utf-8', errors='ignore') as fp:
            content = fp.read()
            
        # Indicators of failure to get clean help
        indicators = [
            "*** ERROR ***", 
            "not a valid option",
            "Too few positional parameters",
            "Unknown option",
            "Timed out waiting for help"
        ]
        
        # Check if any indicator is present
        issues = [ind for ind in indicators if ind in content]
        
        # Also check if content is suspiciously short (e.g., just the header)
        if len(content.splitlines()) < 4:
            issues.append("Content too short")
            
        if issues:
            error_files.append((f.name, issues))

    print(f"Found {len(error_files)} potentially problematic files:")
    for name, issues in error_files:
        print(f"{name}: {', '.join(issues)}")

if __name__ == "__main__":
    scan_errors()
