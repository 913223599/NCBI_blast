# -*- coding: utf-8 -*-
"""
ResourceGuard - CPU 安全核心预算与 GPU 显存红线守卫
"""
import gc
import logging
import os
from typing import Any, Dict

logger = logging.getLogger("phylo.resource_guard")

# 默认保留的系统核心数，防止高并发计算造成主机桌面与主服务卡死
MIN_RESERVED_CORES_HARD = 2
DEFAULT_RESERVED_CORES = 4


def get_total_logical_cores() -> int:
    """获取当前主机逻辑处理器数量。"""
    return max(1, os.cpu_count() or 4)


def get_safe_cpu_budget(requested: int = 0) -> int:
    """
    计算允许使用的安全并发线程数。
    - requested <= 0: 自动模式，保留 4 核（小核主机至少保留 1 核可用）
    - requested > 0: 严格钳位至 [1, total - 2]
    """
    total = get_total_logical_cores()
    hard_cap = max(1, total - MIN_RESERVED_CORES_HARD) if total > 2 else 1
    if requested <= 0:
        if total <= 4:
            return max(1, total - 1)
        return max(1, min(hard_cap, total - DEFAULT_RESERVED_CORES))
    return max(1, min(requested, hard_cap))


class GpuGuard:
    """
    PyTorch CUDA 探测、分块显存预算控制与显存回收守卫。
    严禁显存溢出至主板共享内存引发 PCIe 阻塞。
    """

    @staticmethod
    def probe() -> Dict[str, Any]:
        """探测当前 CUDA GPU 可用状态与显存余额（单位：MB）。"""
        info: Dict[str, Any] = {
            "available": False,
            "name": "",
            "total_vram_mb": 0,
            "free_vram_mb": 0,
        }
        try:
            import torch

            if not torch.cuda.is_available():
                return info
            device_idx = torch.cuda.current_device()
            props = torch.cuda.get_device_properties(device_idx)
            free_bytes, total_bytes = torch.cuda.mem_get_info(device_idx)
            info["available"] = True
            info["name"] = str(props.name)
            info["total_vram_mb"] = total_bytes // (1024 * 1024)
            info["free_vram_mb"] = free_bytes // (1024 * 1024)
            return info
        except Exception as exc:
            logger.debug(f"CUDA probe unavailable: {exc}")
            return info

    @staticmethod
    def compute_pair_chunk_size(
        n_seqs: int,
        seq_len: int,
        max_vram_ratio: float = 0.35,
        max_vram_mb: int = 1536,
    ) -> int:
        """
        根据可用空闲显存动态计算成对距离计算时的行块大小，确保工作张量绝不超过安全红线。
        每批张量近似占用的显存取决于 (chunk_rows * n_seqs * seq_len 或 chunk_rows * seq_len)。
        """
        gpu_info = GpuGuard.probe()
        if not gpu_info["available"]:
            return max(16, min(n_seqs, 128))

        free_mb = max(256, gpu_info["free_vram_mb"])
        budget_mb = min(max_vram_mb, int(free_mb * max_vram_ratio))
        budget_bytes = max(64 * 1024 * 1024, budget_mb * 1024 * 1024)

        # 我们采用矩阵乘法/分块差值方案：单次中间张量主要为 (chunk, seq_len * alphabet) float32
        # 或分块广播 (chunk, chunk_col, seq_len) 约 4 bytes/元素，留 4x 安全余量
        bytes_per_row_pair = max(1, n_seqs * 16)
        est_chunk = max(8, budget_bytes // (bytes_per_row_pair * max(1, min(seq_len, 4096))))
        return max(8, min(n_seqs, est_chunk, 512))

    @staticmethod
    def release_vram() -> None:
        """显式触发 Python 垃圾回收与 PyTorch CUDA 缓存清理。"""
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
        except Exception:
            pass
