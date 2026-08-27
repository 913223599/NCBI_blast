# -*- coding: utf-8 -*-
"""
gpu_accelerator.py - 基于 PyTorch CUDA 的 GPU 批量张量序列相似度加速器
负责在 GPU 上批量计算氨基酸 K-mer 频数张量相似度矩阵，将成千上万个基因的粗筛时间缩短至毫秒级。
严格执行物理显存红线控制与显存回收 (torch.cuda.empty_cache())。
"""
import os
import gc
import logging
from typing import List, Tuple, Optional, Set
import numpy as np

logger = logging.getLogger("analysis.pan_genomics.gpu_accelerator")

try:
    import torch
    HAS_TORCH = True
    CUDA_AVAILABLE = torch.cuda.is_available()
except ImportError:
    HAS_TORCH = False
    CUDA_AVAILABLE = False


class GPUSequenceMatcher:
    """GPU 批量张量相似度计算器"""

    def __init__(self, device: Optional[str] = None):
        if device is None:
            self.device = "cuda" if CUDA_AVAILABLE else "cpu"
        else:
            self.device = device
        self.is_cuda = (self.device.startswith("cuda") and CUDA_AVAILABLE)

    def is_available(self) -> bool:
        """检查 GPU 加速是否可用"""
        return self.is_cuda

    def compute_batch_candidate_pairs(
        self,
        seq_list: List[str],
        sim_threshold: float = 0.35,
        batch_size: int = 1024
    ) -> Set[Tuple[int, int]]:
        """
        利用 GPU 批量矩阵乘法快速筛选具有高 K-mer 相似度的候选基因对
        返回: 满足粗筛条件的候选对下标集合 {(i, j), ...} (i < j)
        """
        n_seqs = len(seq_list)
        if n_seqs < 2:
            return set()

        if not self.is_cuda or not HAS_TORCH:
            # 降级到 CPU 向量化处理
            return self._cpu_batch_candidates(seq_list, sim_threshold)

        candidate_pairs: Set[Tuple[int, int]] = set()

        try:
            # 1. 构建序列的 3-mer 特征哈希 (模 2048 投影降低显存占用)
            num_features = 2048
            k = 3
            feature_matrix = np.zeros((n_seqs, num_features), dtype=np.float32)

            for idx, seq in enumerate(seq_list):
                if len(seq) < k:
                    continue
                u_seq = seq.upper()
                val = 0
                for i in range(k - 1):
                    val = (val * 21 + ord(u_seq[i])) % num_features
                for i in range(k - 1, len(u_seq)):
                    val = ((val * 21) + ord(u_seq[i])) % num_features
                    feature_matrix[idx, val] += 1.0

            # L2 归一化 (余弦相似度 = X @ X.T)
            norms = np.linalg.norm(feature_matrix, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            feature_matrix = feature_matrix / norms

            # 2. 分批转送至 GPU 执行矩阵乘法 (严格控制 Batch Size 防止显存溢出)
            tensor_features = torch.from_numpy(feature_matrix).to(self.device, non_blocking=True)

            for start_i in range(0, n_seqs, batch_size):
                end_i = min(start_i + batch_size, n_seqs)
                batch_tensor = tensor_features[start_i:end_i]  # shape: (B, num_features)

                # 批量余弦相似度计算: (B, N)
                sim_matrix = torch.matmul(batch_tensor, tensor_features.t())

                # 提取大于阈值的下标
                mask = sim_matrix >= sim_threshold
                nonzero_indices = torch.nonzero(mask, as_tuple=False).cpu().numpy()

                for row, col in nonzero_indices:
                    global_i = start_i + int(row)
                    global_j = int(col)
                    if global_i < global_j:
                        candidate_pairs.add((global_i, global_j))

                del sim_matrix, batch_tensor, mask
            
            del tensor_features

        except Exception as e:
            logger.warning(f"GPU 加速计算遇到异常，安全回退至 CPU 多核模式: {e}")
            return self._cpu_batch_candidates(seq_list, sim_threshold)
        finally:
            # 严格遵守显存回收红线
            if self.is_cuda and HAS_TORCH:
                torch.cuda.empty_cache()
            gc.collect()

        return candidate_pairs

    def _cpu_batch_candidates(
        self,
        seq_list: List[str],
        sim_threshold: float = 0.35
    ) -> Set[Tuple[int, int]]:
        """CPU 降级版本: 使用 NumPy 稀疏矩阵加速"""
        n_seqs = len(seq_list)
        candidate_pairs: Set[Tuple[int, int]] = set()
        num_features = 1024
        k = 3
        feature_matrix = np.zeros((n_seqs, num_features), dtype=np.float32)

        for idx, seq in enumerate(seq_list):
            if len(seq) < k:
                continue
            u_seq = seq.upper()
            val = 0
            for i in range(k - 1):
                val = (val * 21 + ord(u_seq[i])) % num_features
            for i in range(k - 1, len(u_seq)):
                val = ((val * 21) + ord(u_seq[i])) % num_features
                feature_matrix[idx, val] += 1.0

        norms = np.linalg.norm(feature_matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        feature_matrix = feature_matrix / norms

        # 分块矩阵乘法
        batch_size = 512
        for start_i in range(0, n_seqs, batch_size):
            end_i = min(start_i + batch_size, n_seqs)
            sim_sub = np.dot(feature_matrix[start_i:end_i], feature_matrix.T)
            rows, cols = np.where(sim_sub >= sim_threshold)
            for r, c in zip(rows, cols):
                gi = start_i + int(r)
                gj = int(c)
                if gi < gj:
                    candidate_pairs.add((gi, gj))

        return candidate_pairs
