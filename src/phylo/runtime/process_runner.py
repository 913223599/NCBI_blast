# -*- coding: utf-8 -*-
"""
ProcessRunner - 可观测、可强杀的统一外部进程执行器
支持 Windows 原生进程树与 WSL Linux 进程组的双向精确终止。
"""
import logging
import os
import shlex
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from ..models.errors import PhyloCancelledError

logger = logging.getLogger("phylo.process_runner")


@dataclass
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str
    elapsed_sec: float


class ProcessRunner:
    """
    受控子进程执行器：
    - 全程强制 UTF-8 编码，禁用 GBK；
    - 实时流式采集输出；
    - 支持通过 threading.Event 即时强制终止 Windows 与 WSL 进程树。
    """

    def __init__(
        self,
        cancel_event: Optional[threading.Event] = None,
        on_log: Optional[Callable[[str], None]] = None,
        wsl_distro: str = "Ubuntu",
    ) -> None:
        self.cancel_event = cancel_event or threading.Event()
        self.on_log = on_log
        self.wsl_distro = wsl_distro
        self._lock = threading.Lock()
        self._active_proc: Optional[subprocess.Popen] = None
        self._active_wsl_pgid_file: Optional[Path] = None

    def _emit_log(self, line: str) -> None:
        clean = line.rstrip("\r\n")
        if clean and self.on_log:
            try:
                self.on_log(clean)
            except Exception:
                pass

    def _to_wsl_path(self, win_path: Path) -> str:
        try:
            from src.assembly.env.wsl_manager import WSLManager

            return WSLManager.to_wsl_path(str(win_path.resolve()))
        except Exception:
            resolved = str(win_path.resolve()).replace("\\", "/")
            if ":" in resolved:
                drive, rest = resolved.split(":", 1)
                return f"/mnt/{drive.lower()}{rest}"
            return resolved

    def _kill_windows_tree(self, pid: int) -> None:
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    timeout=5,
                )
            except Exception as exc:
                logger.debug(f"taskkill failed for PID {pid}: {exc}")
        else:
            try:
                os.kill(pid, 9)
            except Exception:
                pass

    def _kill_wsl_pgid(self, pgid_file: Path) -> None:
        if not pgid_file.exists():
            return
        try:
            raw = ""
            # 等待极短时间以防取消发生在 WSL 刚拉起尚未写完 PGID 的瞬间
            for _ in range(15):
                raw = pgid_file.read_text(encoding="utf-8", errors="ignore").strip()
                if raw.isdigit():
                    break
                time.sleep(0.05)
            if not raw.isdigit():
                logger.warning(f"WSL PGID file empty or invalid: {raw!r}")
                return
            pgid = int(raw)
            if pgid <= 1:
                return
            # 同时向进程组 (-pgid)、会话 (-s pgid) 与进程本身 (pgid) 发送 TERM 和 KILL
            kill_cmd = (
                f"kill -TERM -{pgid} {pgid} 2>/dev/null || true; "
                f"sleep 0.2; "
                f"kill -KILL -{pgid} {pgid} 2>/dev/null || true; "
                f"pkill -KILL -s {pgid} 2>/dev/null || true\n"
            )
            subprocess.run(
                ["wsl", "-d", self.wsl_distro, "-u", "root", "bash", "-s"],
                input=kill_cmd.encode("utf-8"),
                capture_output=True,
                timeout=6,
            )
        except Exception as exc:
            logger.debug(f"WSL pgid cleanup error: {exc}")

    def terminate_active(self) -> None:
        """外部或取消监控线程调用：立即强制销毁当前活跃进程及关联 WSL 进程组。"""
        with self._lock:
            proc = self._active_proc
            pgid_file = self._active_wsl_pgid_file

        if pgid_file is not None:
            self._kill_wsl_pgid(pgid_file)

        if proc is not None and proc.poll() is None:
            self._kill_windows_tree(proc.pid)
            try:
                proc.wait(timeout=3)
            except Exception:
                pass

    def run_native(
        self,
        cmd: List[str],
        cwd: Optional[Path] = None,
        stdout_path: Optional[Path] = None,
        env_extra: Optional[Dict[str, str]] = None,
        stream_stdout_to_log: bool = False,
    ) -> ProcessResult:
        """执行本地原生进程。"""
        return self._execute(
            full_cmd=cmd,
            cwd=cwd,
            stdout_path=stdout_path,
            env_extra=env_extra,
            wsl_pgid_file=None,
            stream_stdout_to_log=stream_stdout_to_log,
        )

    def run_wsl(
        self,
        wsl_cmd_args: List[str],
        cwd: Optional[Path] = None,
        stdout_path: Optional[Path] = None,
        stream_stdout_to_log: bool = False,
    ) -> ProcessResult:
        """
        在 WSL 内以独立进程组 (setsid) 执行命令，并记录 PGID 以便即时精准取消。
        """
        pgid_tmp = tempfile.NamedTemporaryFile(
            prefix="phylo_wsl_pgid_", suffix=".pid", delete=False
        )
        pgid_win_path = Path(pgid_tmp.name)
        pgid_tmp.close()

        wsl_pgid_path = self._to_wsl_path(pgid_win_path)
        quoted_cmd = " ".join(shlex.quote(str(a)) for a in wsl_cmd_args)
        stdin_script = (
            f"echo $$ > {shlex.quote(wsl_pgid_path)}\n"
            f'export PATH="/home/administrator/miniforge3/envs/phylo_phage/bin:/usr/local/bin:$PATH"\n'
            f"exec {quoted_cmd}\n"
        ).encode("utf-8")
        full_cmd = [
            "wsl",
            "-d",
            self.wsl_distro,
            "-u",
            "root",
            "setsid",
            "-w",
            "bash",
            "-s",
        ]
        try:
            return self._execute(
                full_cmd=full_cmd,
                cwd=cwd,
                stdout_path=stdout_path,
                env_extra=None,
                wsl_pgid_file=pgid_win_path,
                stdin_bytes=stdin_script,
                stream_stdout_to_log=stream_stdout_to_log,
            )
        finally:
            try:
                pgid_win_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _execute(
        self,
        full_cmd: List[str],
        cwd: Optional[Path],
        stdout_path: Optional[Path],
        env_extra: Optional[Dict[str, str]],
        wsl_pgid_file: Optional[Path],
        stdin_bytes: Optional[bytes] = None,
        stream_stdout_to_log: bool = False,
    ) -> ProcessResult:
        if self.cancel_event.is_set():
            raise PhyloCancelledError("任务在启动外部进程前已被取消")

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        if env_extra:
            env.update(env_extra)

        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]

        stdout_lines: List[str] = []
        stderr_lines: List[str] = []
        out_file_handle = None
        start_ts = time.time()

        try:
            if stdout_path is not None:
                stdout_path.parent.mkdir(parents=True, exist_ok=True)
                out_file_handle = open(stdout_path, "w", encoding="utf-8", newline="\n")
                stdout_target = out_file_handle
            else:
                stdout_target = subprocess.PIPE

            proc = subprocess.Popen(
                full_cmd,
                cwd=str(cwd) if cwd else None,
                stdin=subprocess.PIPE if stdin_bytes is not None else None,
                stdout=stdout_target,
                stderr=subprocess.PIPE,
                text=False,
                bufsize=0,
                env=env,
                creationflags=creationflags,
            )

            if stdin_bytes is not None and proc.stdin is not None:
                try:
                    proc.stdin.write(stdin_bytes)
                    proc.stdin.flush()
                    proc.stdin.close()
                except Exception:
                    pass

            with self._lock:
                self._active_proc = proc
                self._active_wsl_pgid_file = wsl_pgid_file

            def _pump_stream(stream, collector: List[str], log_output: bool) -> None:
                if stream is None:
                    return
                try:
                    for raw_line in iter(stream.readline, b""):
                        line = raw_line.decode("utf-8", errors="replace")
                        collector.append(line)
                        if log_output:
                            self._emit_log(line)
                except Exception:
                    pass
                finally:
                    try:
                        stream.close()
                    except Exception:
                        pass

            threads: List[threading.Thread] = []
            if stdout_path is None and proc.stdout is not None:
                t_out = threading.Thread(
                    target=_pump_stream,
                    args=(proc.stdout, stdout_lines, stream_stdout_to_log),
                    daemon=True,
                )
                t_out.start()
                threads.append(t_out)

            if proc.stderr is not None:
                t_err = threading.Thread(
                    target=_pump_stream, args=(proc.stderr, stderr_lines, True), daemon=True
                )
                t_err.start()
                threads.append(t_err)

            while proc.poll() is None:
                if self.cancel_event.is_set():
                    self.terminate_active()
                    for t in threads:
                        t.join(timeout=1.5)
                    raise PhyloCancelledError("外部计算进程已响应终止信号并清理")
                time.sleep(0.1)

            for t in threads:
                t.join(timeout=2.0)

            if self.cancel_event.is_set():
                raise PhyloCancelledError("任务已被取消")

            return ProcessResult(
                returncode=proc.returncode or 0,
                stdout="".join(stdout_lines),
                stderr="".join(stderr_lines),
                elapsed_sec=round(time.time() - start_ts, 3),
            )
        finally:
            if out_file_handle is not None:
                try:
                    out_file_handle.close()
                except Exception:
                    pass
            with self._lock:
                self._active_proc = None
                self._active_wsl_pgid_file = None
