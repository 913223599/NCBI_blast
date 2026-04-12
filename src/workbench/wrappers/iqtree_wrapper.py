"""
IQTreeWrapper - IQ-TREE 3 最大似然树推断的封装

修复历史：
- 序列填充逻辑：统一使用 SequenceProcessor.pad_sequences()
- Bootstrap 参数：静默修正改为显式警告
- WSL 路径转换：统一使用 GPUManager.to_wsl_path()
- 临时文件管理：使用 TemporaryDirectory 确保清理
- 硬编码路径消除：提取为命名常量
"""
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from .base_wrapper import BaseWrapper

logger = logging.getLogger(__name__)

# ─── 配置常量（Issues #11, #13：消除硬编码路径和魔法数字）───
# IQ-TREE 3 在 WSL 中的默认安装路径
IQTREE_WSL_BINARY_PATH = "/opt/iqtree3/iqtree-3.1.1-Linux-intel/bin/iqtree3"
# IQ-TREE UFBoot 算法的最小自展检验次数
UFBOOT_MINIMUM_REPLICATES = 1000
# WSL 分发版名称
WSL_DISTRO_NAME = "Ubuntu"


class IQTreeWrapper(BaseWrapper):
    """
    Wrapper for IQ-TREE 2/3 (Maximum Likelihood Tree Inference).
    Source: vendor/iqtree3
    """

    def build_tree(
        self,
        input_fasta: Path,
        output_dir: Path,
        model: str = "JC",  # Use JC for test speed/simplicity
        bootstrap: int = 1000,
        threads: Optional[int] = None,
        use_gpu: bool = False,
    ) -> Path:
        """
        Execute IQ-Tree 3 to infer a Maximum Likelihood tree (CPU Optimized).

        Args:
            input_fasta: 输入 FASTA 文件
            output_dir: 输出目录
            model: 进化模型
            bootstrap: 自展检验次数
            threads: 线程数，None 时自动检测
            use_gpu: 是否使用 GPU（当前禁用）

        Returns:
            生成的 treefile 路径

        Raises:
            ValueError: 输入文件为空
            RuntimeError: IQ-TREE 执行失败
            FileNotFoundError: 结果文件未找到
        """
        self.validate_file(input_fasta)

        # 核心增强：确保输入是严格对齐的（IQ-TREE 要求所有序列长度一致）
        from .tree_sequence_processor import SequenceProcessor

        temp_dir = None
        effective_input = input_fasta
        needs_cleanup = False

        try:
            # 使用 TemporaryDirectory 确保临时文件一定被清理（Issue #2）
            temp_dir = tempfile.TemporaryDirectory(prefix="iqtree_pad_")
            padded_output = Path(temp_dir.name) / f"padded_{input_fasta.name}"
            effective_input, needs_cleanup = SequenceProcessor.pad_sequences(
                input_fasta, padded_output
            )

            output_dir.mkdir(parents=True, exist_ok=True)

            # Consistent prefix
            prefix = output_dir / f"{effective_input.stem}_iqtree"

            thread_count = str(threads) if threads else "AUTO"

            # --- Issue #7：Bootstrap 参数显式警告而非静默修正 ---
            original_bootstrap = int(bootstrap)
            actual_bootstrap = original_bootstrap
            if original_bootstrap < UFBOOT_MINIMUM_REPLICATES:
                actual_bootstrap = UFBOOT_MINIMUM_REPLICATES
                self.logger.warning(
                    f"IQ-TREE UFBoot requires >= {UFBOOT_MINIMUM_REPLICATES} replicates. "
                    f"User requested {original_bootstrap}, auto-corrected to {actual_bootstrap}. "
                    f"Set bootstrap >= {UFBOOT_MINIMUM_REPLICATES} to suppress this warning."
                )

            self.logger.info(
                f"IQ-TREE 3 (CPU): Params - Model: {model}, Replicates: {actual_bootstrap}, "
                f"Threads: {thread_count}"
            )

            args = [
                "-s", str(effective_input.absolute()),
                "-m", model,
                "-pre", str(prefix.absolute()),
                "-nt", thread_count,
                "-redo",
                "-bb", str(actual_bootstrap),
            ]

            # --- Issue #6：统一 WSL 路径转换 ---
            from ..models.gpu_manager import GPUManager

            wsl_args = []
            for val in args:
                str_val = str(val)
                # 检测 Windows 路径特征（包含驱动器号和路径分隔符）
                if ":" in str_val and ("/" in str_val or "\\" in str_val):
                    wsl_args.append(GPUManager.to_wsl_path(str_val))
                else:
                    wsl_args.append(str_val)

            # Execute via WSL
            wsl_full_cmd = [
                "wsl", "-d", WSL_DISTRO_NAME, "-u", "root",
                IQTREE_WSL_BINARY_PATH,
            ] + wsl_args
            self.logger.info(f"Executing IQ-TREE 3 via WSL: {' '.join(wsl_full_cmd)}")

            # 使用标准 run 进行执行，强制 utf-8 声明防止 gbk 冲突
            result = subprocess.run(
                wsl_full_cmd,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )

            if result.returncode != 0:
                raise RuntimeError(
                    f"IQ-TREE 3 WSL Execution Failed with code {result.returncode}"
                )

            # Check for output (IQ-Tree can append .treefile or .iqtree.treefile)
            for ext in [".treefile", ".iqtree.treefile"]:
                res_path = Path(f"{prefix}{ext}")
                if res_path.exists():
                    return res_path
            raise FileNotFoundError(f"IQ-TREE result file not found near {prefix}")

        except Exception as exc:
            # Enhanced error report
            err_msg = str(exc)
            if hasattr(exc, "stderr") and exc.stderr:
                err_msg += f"\nSTDERR: {exc.stderr}"
            self.logger.error(f"IQ-TREE ERROR: {err_msg}")
            raise RuntimeError(f"IQ-TREE Failure: {err_msg}") from exc

        finally:
            # 清理临时目录（Issue #2：保证清理即使异常也执行）
            if temp_dir is not None:
                try:
                    temp_dir.cleanup()
                except OSError as cleanup_err:
                    self.logger.warning(f"Failed to cleanup temp dir: {cleanup_err}")
