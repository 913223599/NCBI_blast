import subprocess
import glob
from pathlib import Path
import concurrent.futures

TOOLS_ROOT = Path(r"d:\PycharmProjects\NCBI blast\tools\ncbi_dist\bin")
DOCS_ROOT = Path(r"d:\PycharmProjects\NCBI blast\tools\docs\detailed")

def get_help(tool_path):
    tool_name = tool_path.name
    
    # Flags to try in order. 
    # sra-tools prefer --help, tree-tools prefer -help
    flags_to_try = ["--help", "-help"]
    
    final_output = ""
    success = False

    for flag in flags_to_try:
        try:
            cmd = [str(tool_path), flag]
            # Capture output
            process = subprocess.run(cmd, capture_output=True, text=True, timeout=5, encoding='utf-8', errors='ignore')
            output = process.stdout + "\n" + process.stderr
            
            # Check if this output looks like a valid help message
            # Valid help usually contains "Usage:" or "USAGE:" or "DESCRIPTION" or "Options:"
            # and SHOULD NOT contain "*** ERROR ***" (which indicates we passed the wrong flag or args)
            
            is_error = "*** ERROR ***" in output or process.returncode != 0
            
            # Special case: some tools return 0 but still print ERROR if flag is unknown? 
            # Or return non-zero but print Usage.
            # We prioritize a clean output without "ERROR".
            
            if not is_error and output.strip():
                return tool_name, output, True
            
            # If we got usage info but with error code/message, keep it as a backup
            if "USAGE:" in output.upper() or "Usage:" in output:
                 final_output = output
                 # If it has ERROR, we try next flag. If last flag, we use this backup.
        
        except subprocess.TimeoutExpired:
            pass
        except Exception as e:
            final_output = f"Error executing {tool_name}: {e}"

    # If we are here, we didn't find a perfect run. Use whatever we captured that looks like help.
    if final_output:
        return tool_name, final_output, False # Marked as 'not perfect' but has content
        
    return tool_name, "No help available.", False

def main():
    DOCS_ROOT.mkdir(parents=True, exist_ok=True)
    
    exe_files = []
    for section in ["sra-tools", "tree-tools"]:
        path = TOOLS_ROOT / section
        exes = list(path.glob("*.exe"))
        exe_files.extend(exes)
    
    print(f"Found {len(exe_files)} executables. Regenerating docs...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        future_to_tool = {executor.submit(get_help, tool): tool for tool in exe_files}
        
        for future in concurrent.futures.as_completed(future_to_tool):
            tool_name, output, success = future.result()
            
            # Filter out lines that are clearly error messages if we have mixed output
            lines = output.splitlines()
            cleaned_lines = [l for l in lines if not l.startswith("*** ERROR ***") and "Too few positional parameters" not in l and "is not a valid option" not in l]
            cleaned_output = "\n".join(cleaned_lines)
            
            doc_file = DOCS_ROOT / f"{tool_name}.txt"
            with open(doc_file, "w", encoding='utf-8') as f:
                f.write(f"Tool: {tool_name}\n")
                f.write("=" * 40 + "\n\n")
                f.write(cleaned_output.strip())

    print("Done.")

if __name__ == "__main__":
    main()
