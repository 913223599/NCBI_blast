import subprocess
import logging

logger = logging.getLogger("GPUManager")

class GPUManager:
    """
    Manages WSL bridge and path translation for Linux-based bioinformatics tools.
    """
    
    _wsl_capability_cache: Dict[str, bool] = {}

    @classmethod
    def check_wsl_command(cls, cmd_name: str) -> bool:
        """
        Verifies if a specific command is available within the WSL environment.
        """
        if cmd_name in cls._wsl_capability_cache:
            return cls._wsl_capability_cache[cmd_name]

        try:
            # Check standard WSL path
            res = subprocess.run(["wsl", "which", cmd_name], capture_output=True, encoding='utf-8', errors='replace')
            if res.returncode == 0 and res.stdout.strip():
                cls._wsl_capability_cache[cmd_name] = True
                return True
            
            # Fallback specifically to Ubuntu distro as root for verification
            res = subprocess.run(["wsl", "-d", "Ubuntu", "-u", "root", "which", cmd_name], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5)
            is_ready = res.returncode == 0 and res.stdout.strip() != ""
            cls._wsl_capability_cache[cmd_name] = is_ready
            return is_ready
        except:
            return False

    @staticmethod
    def to_wsl_path(win_path: str) -> str:
        """
        Converts a Windows absolute path to a WSL path via wslpath utility.
        """
        if not win_path:
            return ""
        
        try:
            # Try via native wslpath if possible
            res = subprocess.run(["wsl", "-d", "Ubuntu", "wslpath", win_path], capture_output=True, encoding='utf-8', errors='replace')
            if res.returncode == 0:
                return res.stdout.strip()
        except:
            pass

        # Fallback to standard /mnt/<drive> manual translation
        path = win_path.replace("\\", "/")
        if ":" in path:
            drive, rest = path.split(":", 1)
            return f"/mnt/{drive.lower()}{rest}"
        return path

    @classmethod
    def detect_gpu(cls) -> Dict[str, Any]:
        """Simplified detection for backward compatibility."""
        return {"available": False, "error": "GPU acceleration disabled as per project stabilization goals."}
