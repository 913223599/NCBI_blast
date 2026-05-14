import asyncio
import re
import logging
import time
import shlex
from pathlib import Path
from typing import List, Optional, Dict, Any, Callable, Union

class CommandRunner:
    """
    负责执行底层生物信息工具的通用执行器
    支持：异步执行、日志捕获、执行耗时统计、超时控制、WSL透明桥接
    """
    def __init__(self, step_name: str, logger: Optional[logging.Logger] = None, is_wsl: bool = False):
        self.step_name = step_name
        self.logger = logger or logging.getLogger(f"Assembly.{step_name}")
        self.is_wsl = is_wsl
        self.current_process: Optional[asyncio.subprocess.Process] = None

    def terminate(self):
        """强制终止当前正在执行的进程"""
        self.is_aborted = True
        if self.current_process:
            try:
                self.current_process.terminate()
                self.logger.warning(f"用户主动终止了进程: {self.step_name}")
            except Exception as e:
                self.logger.error(f"终止进程失败: {e}")

    async def run_command(self, 
                          cmd: Union[List[str], str], 
                          cwd: Optional[Union[Path, str]] = None,
                          env: Optional[Dict[str, str]] = None,
                          on_output: Optional[Callable[[str], None]] = None,
                          is_shell: bool = False,
                          timeout: Optional[float] = 14400.0,
                          silence_errors: bool = False) -> int:
        """
        执行命令并持续监控输出 (支持 WSL 自动转换与智能路由)
        """
        if getattr(self, 'is_aborted', False):
            self.logger.warning(f"🚫 任务已终止，拒绝执行后续命令")
            return -99

        # ==========================================
        # 1. 参数清洗与路径转换
        # ==========================================
        final_cmd_args = []
        if isinstance(cmd, list):
            for arg in cmd:
                arg_str = arg.replace('\\', '/') if isinstance(arg, str) else str(arg).replace('\\', '/')
                if self.is_wsl and not arg_str.startswith(("http", "ftp")) and re.match(r'^[A-Za-z]:/', arg_str):
                    from ..env.wsl_manager import WSLManager
                    final_cmd_args.append(WSLManager.to_wsl_path(arg_str))
                else:
                    final_cmd_args.append(arg_str)
        else:
            # 字符串模式直接透传，信任调用者已经处理好路径或使用相对路径
            final_cmd_args = [cmd]

        # ==========================================
        # 2. 跨平台执行指令构建
        # ==========================================
        if self.is_wsl:
            if is_shell:
                # 🔗 纠偏：如果是 Shell 片段，将参数合并为单一字符串
                # 警告：不要在这里给 shell_str 加双引号，由 asyncio 处理 argv 的引号
                shell_str = " ".join([str(c) for c in final_cmd_args])
                cmd_to_exec = ["wsl", "-d", "Ubuntu", "-u", "root", "bash", "-c", shell_str]
                use_shell = False 
            else:
                # 列表直调模式
                cmd_to_exec = ["wsl", "-d", "Ubuntu", "-u", "root"] + [str(c) for c in final_cmd_args]
                use_shell = False
            cwd_to_exec = None 
        else:
            if is_shell:
                cmd_to_exec = " ".join([str(c) for c in final_cmd_args])
                use_shell = True
            else:
                cmd_to_exec = final_cmd_args
                use_shell = False
            cwd_to_exec = str(cwd) if cwd else None

        # ==========================================
        # 3. 异步进程监控与执行
        # ==========================================
        start_time = time.time()
        display_cmd = cmd_to_exec if isinstance(cmd_to_exec, str) else " ".join(cmd_to_exec)
        timeout_desc = f"{timeout/3600:.1f}h" if timeout else "无限制"
        self.logger.info(f"开始执行 (超时: {timeout_desc}): {display_cmd}")

        try:
            if use_shell:
                process = await asyncio.create_subprocess_shell(
                    str(cmd_to_exec),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd_to_exec,
                    env=env
                )
            else:
                process = await asyncio.create_subprocess_exec(
                    *cmd_to_exec,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd_to_exec,
                    env=env
                )
            
            self.current_process = process

            async def read_stream(stream, is_stderr: bool):
                buffer = b""
                while True:
                    try:
                        chunk = await stream.read(4096)
                        if not chunk:
                            if buffer:
                                self._process_line(buffer.decode('utf-8', errors='ignore'), is_stderr, on_output)
                            break
                        
                        buffer += chunk
                        while b"\n" in buffer:
                            line_data, buffer = buffer.split(b"\n", 1)
                            self._process_line(line_data.decode('utf-8', errors='ignore'), is_stderr, on_output)
                        
                        if b"\r" in buffer and len(buffer) > 1024:
                             line_data, buffer = buffer.rsplit(b"\r", 1)
                             self._process_line(line_data.decode('utf-8', errors='ignore'), is_stderr, on_output)
                                
                    except Exception as stream_err:
                        self.logger.error(f"读取流时出现紧急错误: {str(stream_err)}")
                        if self.current_process:
                             self.current_process.terminate()
                        raise stream_err 

            async def _run():
                try:
                    await asyncio.gather(
                        read_stream(process.stdout, False),
                        read_stream(process.stderr, True)
                    )
                except Exception:
                    pass 
                return await process.wait()

            try:
                returncode = await asyncio.wait_for(_run(), timeout=timeout)
            except asyncio.TimeoutError:
                self.logger.error(f"⏰ 命令执行超时 ({timeout_desc})，强制终止: {display_cmd[:120]}")
                try:
                    process.terminate()
                    await asyncio.sleep(1)
                    if process.returncode is None:
                        process.kill()
                except Exception:
                    pass
                return -9

            self.current_process = None
            duration = time.time() - start_time
            
            if returncode == 0:
                self.logger.info(f"命令执行成功 (耗时: {duration:.1f}s)")
            elif not silence_errors:
                self.logger.error(f"命令返回异常码: {returncode} (耗时: {duration:.1f}s)")
            
            return returncode

        except Exception as e:
            self.logger.error(f"子进程启动失败: {str(e)}")
            return -1

    def _process_line(self, line: str, is_stderr: bool, on_output: Optional[Callable]):
        line = line.strip()
        if not line: return
        
        if on_output:
            on_output(line)
            
        lower_line = line.lower()
        is_junk_progress = bool(re.search(r'^\d+\.?\d*.*processed$', lower_line))
        
        safe_patterns = [
            r"reads failed due to .*:\s+\d+",
            r"failed.*due to.*:\s+\d+",
            r"0% total errors",
            r"errors reported:\s+0",
            r"invalid reads:\s+\d+",
            r"\"zp:z:fail\" tag",
            r"^\d+\s+fail$",
            r"--force was specified even though",
            r"min_range & max_range is no longer used",
            r"^\d+\s+pass$",
            r"deprecationwarning:"
        ]
        is_known_safe_stat = any(re.search(p, lower_line) for p in safe_patterns)
        
        if is_stderr and not is_known_safe_stat:
            if any(k in lower_line for k in ["error", "warn", "fail", "fatal", "critical"]) and "[info]" not in lower_line:
                self.logger.warning(f"[{self.step_name}] {line}")
        elif not is_junk_progress and not is_stderr:
            self.logger.debug(f"[{self.step_name}] {line}")