
import asyncio
import logging
import time
from pathlib import Path
from typing import List, Optional, Dict, Any, Callable

class CommandRunner:
    """
    负责执行底层生物信息工具的通用执行器
    支持：异步执行、日志捕获、执行耗时统计、超时控制
    """
    def __init__(self, step_name: str, logger: Optional[logging.Logger] = None, is_wsl: bool = False):
        self.step_name = step_name
        self.logger = logger or logging.getLogger(f"Assembly.{step_name}")
        self.is_wsl = is_wsl
        self.current_process: Optional[asyncio.subprocess.Process] = None

    def terminate(self):
        """强制终止当前正在执行的进程"""
        if self.current_process:
            try:
                self.current_process.terminate()
                self.logger.warning(f"用户主动终止了进程: {self.step_name}")
            except Exception as e:
                self.logger.error(f"终止进程失败: {e}")

    async def run_command(self, 
                          cmd: List[str], 
                          cwd: Optional[Path] = None,
                          env: Optional[Dict[str, str]] = None,
                          on_output: Optional[Callable[[str], None]] = None,
                          is_shell: bool = False) -> int:
        """
        执行命令并持续监控输出 (支持 WSL 自动转换)
        """
        if self.is_wsl:
            from ..env.wsl_manager import WSLManager
            # 1. 转换参数列表中的所有路径
            final_cmd_args = []
            for arg in cmd:
                arg_str = str(arg)
                # 🔗 关键修复：排除 URL (http/https/ftp)
                is_url = arg_str.startswith(("http://", "https://", "ftp://"))
                
                if not is_url and (":\\" in arg_str or ":/" in arg_str):
                    final_cmd_args.append(WSLManager.to_wsl_path(arg_str))
                else:
                    final_cmd_args.append(arg_str)
            
            # 2. 封装为 WSL 命令
            if is_shell:
                # 管道模式：使用 bash -c
                # 💡 关键修复：内部参数使用单引号，避免与外部 bash -c 的双引号产生转义冲突
                shell_parts = []
                for c in final_cmd_args:
                    c_str = str(c)
                    if " " in c_str and "'" not in c_str:
                        shell_parts.append(f"'{c_str}'")
                    else:
                        shell_parts.append(c_str)
                
                shell_str = " ".join(shell_parts)
                cmd_to_exec = ["wsl", "-d", "Ubuntu", "-u", "root", "bash", "-c", shell_str]
                use_shell = False 
            else:
                # 💡 关键修复：非 shell 模式下严禁手动加引号！
                # subprocess_exec 会自动处理参数中的空格。
                cmd_to_exec = ["wsl", "-d", "Ubuntu", "-u", "root"] + [str(c) for c in final_cmd_args]
                use_shell = False
            cwd_to_exec = None 
        else:
            if is_shell:
                cmd_to_exec = " ".join([f'"{c}"' if " " in str(c) else str(c) for c in cmd])
                use_shell = True
            else:
                cmd_to_exec = cmd
                use_shell = False
            cwd_to_exec = str(cwd) if cwd else None

        start_time = time.time()
        display_cmd = cmd_to_exec if isinstance(cmd_to_exec, str) else " ".join(cmd_to_exec)
        self.logger.info(f"开始执行: {display_cmd}")

        try:
            if use_shell:
                process = await asyncio.create_subprocess_shell(
                    cmd_to_exec,
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

            # 实时读取 stdout 和 stderr (强化解码)
            async def read_stream(stream, is_stderr: bool):
                while True:
                    try:
                        line = await stream.readline()
                        if line:
                            # ⚠️ 修复点: 强制 utf-8 且 ignore 错误字符
                            decoded_line = line.decode('utf-8', errors='ignore').strip()
                            if on_output:
                                on_output(decoded_line)
                            if is_stderr and "error" in decoded_line.lower():
                                self.logger.warning(f"[{self.step_name}] {decoded_line}")
                        else:
                            break
                    except Exception as e:
                        self.logger.error(f"读取流时出错: {str(e)}")
                        break

            await asyncio.gather(
                read_stream(process.stdout, False),
                read_stream(process.stderr, True)
            )

            returncode = await process.wait()
            self.current_process = None
            duration = time.time() - start_time
            
            if returncode == 0:
                self.logger.info(f"命令执行成功 (耗时: {duration:.1f}s)")
            else:
                self.logger.error(f"命令返回异常码: {returncode} (耗时: {duration:.1f}s)")
            
            return returncode

        except Exception as e:
            self.logger.error(f"子进程启动失败: {str(e)}")
            return -1
