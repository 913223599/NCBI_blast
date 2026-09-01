"""
ShmManager -- 内存盘 (RAMDisk) 统一资源管理器

核心职责:
  1. 动态配额计算: 根据物理内存和当前进程需求，实时调整 /dev/shm 可用比例
  2. 上下文管理器: 通过 async with 确保申请必释放，杜绝泄漏
  3. 进程内存联动: 自动计算当前进程可安全使用的最大内存
  4. 溢出转储: 当内存盘空间紧张时，自动将低优先级数据转储到 SSD
"""

import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Optional, Dict

logger = logging.getLogger("Assembly.ShmManager")


@dataclass
class ShmWorkspace:
    """一个已分配的内存盘工作空间描述符"""
    path: str
    step_name: str
    is_ramdisk: bool
    allocated_gb: float
    created_at: float = field(default_factory=time.time)


class ShmManager:
    """
    内存盘统一资源管理器

    生命周期: 与 PipelineContext 绑定，一个任务一个实例。
    所有步骤通过 ctx.shm.acquire() 申请空间，退出时自动释放。
    """

    # 策略常量
    SHM_RATIO = 0.50          # 内存盘最大占用物理内存的比例
    SHM_CAP_GB = 24           # 内存盘绝对上限 (GB)
    OS_RESERVE_GB = 4         # 为操作系统和缓存预留的内存 (GB)
    DIAG_RETAIN_SECONDS = 3600  # 诊断现场保留时长 (秒)

    def __init__(self, task_id: str, runner, total_memory_gb: float):
        self.task_id = task_id
        self.runner = runner  # CommandRunner 实例，用于执行 WSL 命令
        self.total_memory_gb = total_memory_gb

        # 活跃工作空间追踪
        self._active: Dict[str, ShmWorkspace] = {}
        # 诊断保留空间 (失败时不立即清理)
        self._retained: Dict[str, ShmWorkspace] = {}

        # 计算初始配额
        self._shm_quota_gb = min(
            self.SHM_CAP_GB,
            int(self.total_memory_gb * self.SHM_RATIO)
        )
        logger.info(
            f"ShmManager 初始化: 物理内存={self.total_memory_gb:.1f}G, "
            f"内存盘配额={self._shm_quota_gb}G, "
            f"进程可用={self.get_process_memory_limit()}G"
        )

    @property
    def shm_quota_gb(self) -> int:
        """当前内存盘配额 (GB)"""
        return self._shm_quota_gb

    def get_process_memory_limit(self) -> int:
        """
        返回当前进程可安全使用的最大内存 (GB)
        = 物理内存 - 活跃内存盘占用 - OS 预留
        """
        active_shm_usage = sum(
            ws.allocated_gb for ws in self._active.values() if ws.is_ramdisk
        )
        available = int(
            self.total_memory_gb - active_shm_usage - self.OS_RESERVE_GB
        )
        return max(4, available)  # 最低保证 4GB

    async def _remount_shm(self, size_gb: int):
        """动态调整 /dev/shm 的大小"""
        try:
            await self.runner.run_command(
                ["bash", "-c", f"mount -o remount,size={size_gb}G /dev/shm"],
                silence_errors=True
            )
            logger.info(f"内存盘已调整至 {size_gb}G")
        except Exception as e:
            logger.warning(f"内存盘调整失败: {e}")

    async def _get_shm_available_gb(self) -> float:
        """探测 /dev/shm 当前可用空间 (GB)"""
        try:
            out = []
            await self.runner.run_command(
                ["bash", "-c", "df -BG /dev/shm"],
                on_output=out.append, silence_errors=True
            )
            # 倒序查找输出行，避免因为 WSL 的代理警告导致提取失败
            for line in reversed(out):
                if "/dev/shm" in line:
                    parts = line.split()
                    if len(parts) >= 4:
                        avail_str = parts[3].replace("G", "")
                        if avail_str.isdigit():
                            return float(avail_str)
        except Exception:
            pass
        return 0.0

    async def _evict_expired_diagnostics(self):
        """清理超时的诊断保留空间"""
        now = time.time()
        expired = [
            name for name, ws in self._retained.items()
            if now - ws.created_at > self.DIAG_RETAIN_SECONDS
        ]
        for name in expired:
            ws = self._retained.pop(name)
            logger.info(f"回收过期诊断现场: {ws.path}")
            await self.runner.run_command(
                ["rm", "-rf", ws.path], silence_errors=True
            )

    @asynccontextmanager
    async def acquire(self, step_name: str, required_gb: float = 5.0,
                      prefer_ramdisk: bool = True):
        """
        申请一个工作空间 (上下文管理器)

        用法:
            async with ctx.shm.acquire("assembler", required_gb=10.0) as ws:
                # ws.path      -> 工作目录路径
                # ws.is_ramdisk -> 是否为内存盘
                await do_work(ws.path)
            # 退出时自动清理

        Args:
            step_name: 步骤标识 (用于日志和路径命名)
            required_gb: 需要的空间大小 (GB)
            prefer_ramdisk: 是否优先使用内存盘
        """
        # 清理过期诊断现场，腾出空间
        await self._evict_expired_diagnostics()

        workspace = await self._allocate(step_name, required_gb, prefer_ramdisk)
        self._active[step_name] = workspace

        try:
            yield workspace
        finally:
            # 正常退出时清理
            if step_name in self._active:
                self._active.pop(step_name)
                logger.info(f"释放工作空间: {workspace.path}")
                await self.runner.run_command(
                    ["rm", "-rf", workspace.path], silence_errors=True
                )

    async def acquire_manual(self, step_name: str, required_gb: float = 5.0,
                             prefer_ramdisk: bool = True) -> ShmWorkspace:
        """
        手动申请工作空间 (不使用上下文管理器)
        调用方必须显式调用 release() 释放！
        """
        await self._evict_expired_diagnostics()
        workspace = await self._allocate(step_name, required_gb, prefer_ramdisk)
        self._active[step_name] = workspace
        return workspace

    async def release(self, step_name: str, retain_for_diagnostics: bool = False):
        """
        手动释放工作空间

        Args:
            step_name: 步骤标识
            retain_for_diagnostics: 是否保留现场用于诊断 (失败时使用)
        """
        ws = self._active.pop(step_name, None)
        if not ws:
            return

        if retain_for_diagnostics:
            self._retained[step_name] = ws
            logger.warning(
                f"诊断保留: {ws.path} "
                f"(将在 {self.DIAG_RETAIN_SECONDS}s 后自动回收)"
            )
        else:
            logger.info(f"释放工作空间: {ws.path}")
            await self.runner.run_command(
                ["rm", "-rf", ws.path], silence_errors=True
            )

    async def _allocate(self, step_name: str, required_gb: float,
                        prefer_ramdisk: bool) -> ShmWorkspace:
        """内部分配逻辑: 决定使用内存盘还是 SSD"""
        safe_id = f"asm_{self.task_id}_{step_name}".replace(" ", "_").lower()
        shm_path = f"/dev/shm/{safe_id}"
        disk_path = f"/tmp/{safe_id}"

        use_ramdisk = False

        if prefer_ramdisk:
            # 动态调整内存盘大小
            await self._remount_shm(self._shm_quota_gb)

            # 检查可用空间
            available = await self._get_shm_available_gb()

            if available >= required_gb:
                use_ramdisk = True
                target_path = shm_path
                logger.info(
                    f"[{step_name}] 内存盘分配: "
                    f"需要={required_gb:.1f}G, 可用={available:.1f}G"
                )
            else:
                target_path = disk_path
                logger.info(
                    f"[{step_name}] 降级至 SSD: "
                    f"需要={required_gb:.1f}G, 内存盘仅剩={available:.1f}G"
                )
        else:
            target_path = disk_path
            logger.info(f"[{step_name}] 直接使用 SSD (不申请内存盘)")

        # 创建目录
        await self.runner.run_command(["rm", "-rf", target_path], silence_errors=True)
        await self.runner.run_command(["mkdir", "-p", target_path], silence_errors=True)

        return ShmWorkspace(
            path=target_path,
            step_name=step_name,
            is_ramdisk=use_ramdisk,
            allocated_gb=required_gb if use_ramdisk else 0
        )

    async def spill_to_disk(self, step_name: str, file_patterns: list[str]):
        """
        将内存盘中的指定文件转储到 SSD，释放内存空间

        用于组装中间阶段：当引擎完成 K-mer 构建后，将中间图谱
        转储到 SSD，为后续阶段腾出内存。

        Args:
            step_name: 步骤标识
            file_patterns: 要转储的文件 glob 模式列表
        """
        ws = self._active.get(step_name)
        if not ws or not ws.is_ramdisk:
            return

        disk_backup = f"/tmp/{os.path.basename(ws.path)}_spill"
        await self.runner.run_command(["mkdir", "-p", disk_backup], silence_errors=True)

        for pattern in file_patterns:
            cmd = f"mv {ws.path}/{pattern} {disk_backup}/ 2>/dev/null || true"
            await self.runner.run_command(
                ["bash", "-c", cmd], silence_errors=True
            )

        logger.info(
            f"[{step_name}] 已将 {len(file_patterns)} 类文件从内存盘转储至 SSD"
        )

    async def cleanup_all(self):
        """
        全局清理: 流水线结束时调用，确保不留任何残余

        清理范围:
          - 所有活跃工作空间
          - 所有诊断保留空间
          - /dev/shm 中本任务的所有残留目录
        """
        # 清理活跃空间
        for name, ws in list(self._active.items()):
            logger.info(f"全局清理: 释放活跃空间 {ws.path}")
            await self.runner.run_command(
                ["rm", "-rf", ws.path], silence_errors=True
            )
        self._active.clear()

        # 清理诊断保留
        for name, ws in list(self._retained.items()):
            logger.info(f"全局清理: 回收诊断现场 {ws.path}")
            await self.runner.run_command(
                ["rm", "-rf", ws.path], silence_errors=True
            )
        self._retained.clear()

        # 扫描 /dev/shm 中可能遗漏的本任务目录
        await self.runner.run_command(
            ["bash", "-c",
             f"find /dev/shm -maxdepth 1 -name 'asm_{self.task_id}_*' "
             f"-exec rm -rf {{}} + 2>/dev/null || true"],
            silence_errors=True
        )
        # 同样清理 /tmp
        await self.runner.run_command(
            ["bash", "-c",
             f"find /tmp -maxdepth 1 -name 'asm_{self.task_id}_*' "
             f"-exec rm -rf {{}} + 2>/dev/null || true"],
            silence_errors=True
        )

        logger.info("全局清理完成")

    def get_usage_report(self) -> dict:
        """生成当前资源使用报告"""
        return {
            "total_memory_gb": self.total_memory_gb,
            "shm_quota_gb": self._shm_quota_gb,
            "process_memory_limit_gb": self.get_process_memory_limit(),
            "active_workspaces": {
                name: {
                    "path": ws.path,
                    "is_ramdisk": ws.is_ramdisk,
                    "allocated_gb": ws.allocated_gb,
                    "age_seconds": int(time.time() - ws.created_at)
                }
                for name, ws in self._active.items()
            },
            "retained_diagnostics": len(self._retained),
        }
