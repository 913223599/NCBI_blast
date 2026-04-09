import logging
import os
import subprocess
import time
from pathlib import Path

from src.workbench.models.tool_config import ToolConfig


class WrapperError(Exception):
    """Base exception for wrapper operations."""
    def __init__(self, message: str, tool_name: str = None, original_error: Exception = None):
        super().__init__(message)
        self.tool_name = tool_name
        self.original_error = original_error

class BaseWrapper:
    """
    Abstract base class for all tool wrappers.
    Handles subprocess execution, logging, and error management.
    """
    
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        # Ensure results dir and environment are ready for vendor tools
        ToolConfig.ensure_directories()
        ToolConfig.initialize_env()
        
    def _run_command(self, 
                    tool_name: str, 
                    args: List[str], 
                    cwd: Optional[Path] = None,
                    timeout: Optional[int] = None) -> subprocess.CompletedProcess:
        """
        Execute a binary tool with arguments.
        
        Args:
            tool_name: Name of the tool executable.
            args: List of command line arguments.
            cwd: Working directory (defaults to Project Root).
            timeout: execution timeout in seconds.
            
        Returns:
            CompletedProcess instance.
            
        Raises:
            subprocess.CalledProcessError: If command fails (non-zero exit code).
            FileNotFoundError: If tool is missing.
        """
        tool_path = ToolConfig.get_tool_path(tool_name)
        # Ensure all paths are absolute and quoted for Windows space handling
        cmd = [str(tool_path.absolute())] + [str(Path(arg).absolute()) if (isinstance(arg, (str, Path)) and os.path.isabs(str(arg))) else str(arg) for arg in args]
        
        # Isolation: Run inside the tool's parent directory if needed, 
        # but mostly ensured correctly via ToolConfig.
        # Isolation & Environment Guard (Ensures UTF-8 across all threads)
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        
        self.logger.info(f"Executing: {' '.join(cmd)}")
        start_time = time.time()
        
        try:
            # Using Popen-like behavior via run
            process = subprocess.run(
                cmd,
                cwd=(cwd if cwd else ToolConfig.PROJECT_ROOT).absolute(),
                capture_output=True,
                text=True,
                check=False,
                encoding='utf-8', 
                errors='replace',
                env=env,
                timeout=timeout
            )
            
            duration = time.time() - start_time
            if process.returncode == 0:
                self.logger.info(f"Command successful ({duration:.2f}s)")
            else:
                self.logger.error(f"Command failed with exit code {process.returncode}")
                self.logger.error(f"Stdout: {process.stdout}")
                self.logger.error(f"Stderr: {process.stderr}")
                # Re-raise if we want to stop the workflow, 
                # but now with better logs already in the stream.
                raise subprocess.CalledProcessError(process.returncode, cmd, output=process.stdout, stderr=process.stderr)
                
            return process
        except subprocess.CalledProcessError as e:
            self.logger.critical(f"Execution error: {str(e)}")
            raise WrapperError(
                message=f"Tool '{tool_name}' failed with exit code {e.returncode}",
                tool_name=tool_name,
                original_error=e
            ) from e
        except FileNotFoundError as e:
            self.logger.critical(f"Tool not found: {tool_name}")
            raise WrapperError(
                message=f"Tool executable not found: {tool_name}",
                tool_name=tool_name,
                original_error=e
            ) from e
        except Exception as e:
            self.logger.critical(f"Unexpected execution error: {str(e)}")
            raise WrapperError(
                message=f"An unexpected error occurred while running {tool_name}: {str(e)}",
                tool_name=tool_name,
                original_error=e
            ) from e
            
    def validate_file(self, file_path: Union[str, Path]) -> Path:
        """Helper to validate input files exist."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Input file not found: {path}")
        return path
