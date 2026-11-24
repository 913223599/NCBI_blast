# -*- coding: utf-8 -*-
"""
MrBayesEngine - 可选高级贝叶斯 MCMC 系统发育推断引擎
支持 DNA 与蛋白数据、安全短 ID、流式日志与即时取消。
"""
import logging
import re
import threading
from pathlib import Path
from typing import Callable, Optional

from ...core.fasta_io import read_fasta_records
from ...models.errors import PhyloCancelledError, PhyloError, ToolUnavailableError
from ...runtime.process_runner import ProcessRunner
from ...runtime.tool_registry import get_tool_registry

logger = logging.getLogger("phylo.mrbayes")


class MrBayesEngine:
    """MrBayes 贝叶斯构树包装器。"""

    def __init__(
        self,
        cancel_event: Optional[threading.Event] = None,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.cancel_event = cancel_event or threading.Event()
        self.on_log = on_log
        self.registry = get_tool_registry()
        self.runner = ProcessRunner(
            cancel_event=self.cancel_event,
            on_log=self.on_log,
            wsl_distro=self.registry.wsl_distro or "Ubuntu",
        )

    def terminate_active(self) -> None:
        self.runner.terminate_active()

    def build(
        self,
        msa_fasta: Path,
        output_nwk: Path,
        work_dir: Path,
        mol_type: str = "dna",
        ngen: int = 10000,
    ) -> Path:
        if self.cancel_event.is_set():
            raise PhyloCancelledError("MrBayes 开始前任务已取消")

        desc = self.registry.get("mrbayes")
        if not desc.available:
            raise ToolUnavailableError("mrbayes", f"MrBayes 不可用: {desc.notes}")

        records = read_fasta_records(msa_fasta)
        if len(records) < 4:
            raise PhyloError("MrBayes 贝叶斯分析至少需要 4 条序列。")

        mb_dir = work_dir / "mrbayes_run"
        mb_dir.mkdir(parents=True, exist_ok=True)
        nex_file = mb_dir / "analysis.nex"

        datatype = "PROTEIN" if mol_type == "protein" else "DNA"
        nchar = len(records[0].seq)
        samplefreq = max(10, ngen // 200)
        printfreq = max(100, ngen // 20)

        with open(nex_file, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("#NEXUS\n\nBEGIN DATA;\n")
            fh.write(f"  DIMENSIONS NTAX={len(records)} NCHAR={nchar};\n")
            fh.write(f"  FORMAT DATATYPE={datatype} MISSING=? GAP=-;\n")
            fh.write("  MATRIX\n")
            for rec in records:
                fh.write(f"    {rec.id:<16} {str(rec.seq)}\n")
            fh.write("  ;\nEND;\n\n")
            fh.write("BEGIN MRBAYES;\n")
            fh.write("  set autoclose=yes nowarn=yes;\n")
            if mol_type == "protein":
                fh.write("  prset aamodelpr=mixed;\n")
            else:
                fh.write("  lset nst=6 rates=invgamma;\n")
            fh.write(f"  mcmc ngen={ngen} samplefreq={samplefreq} printfreq={printfreq} nchains=2 nruns=1;\n")
            fh.write("  sump relburnin=yes burninfrac=0.25;\n")
            fh.write("  sumt relburnin=yes burninfrac=0.25;\n")
            fh.write("END;\n")

        if desc.runtime == "wsl":
            from src.assembly.env.wsl_manager import WSLManager

            cmd = [desc.path, WSLManager.to_wsl_path(str(nex_file.resolve()))]
            res = self.runner.run_wsl(cmd, cwd=mb_dir, stream_stdout_to_log=True)
        else:
            cmd = [desc.path, str(nex_file.resolve())]
            res = self.runner.run_native(cmd, cwd=mb_dir, stream_stdout_to_log=True)

        if res.returncode != 0:
            raise PhyloError(f"MrBayes 执行失败 (exit={res.returncode})", detail=res.stderr[-1000:])

        con_tree = mb_dir / "analysis.nex.con.tre"
        if not con_tree.is_file():
            raise PhyloError(f"MrBayes 共识树文件未找到: {con_tree}")

        nwk_text = self._extract_newick_from_nexus(con_tree)
        output_nwk.parent.mkdir(parents=True, exist_ok=True)
        output_nwk.write_text(nwk_text + "\n", encoding="utf-8")
        return output_nwk

    @staticmethod
    def _extract_newick_from_nexus(con_tree_path: Path) -> str:
        """从 MrBayes 输出的 NEXUS 共识树提取并映射回真实标签的 Newick。"""
        text = con_tree_path.read_text(encoding="utf-8", errors="replace")
        translate_map: dict[str, str] = {}
        in_translate = False
        for line in text.splitlines():
            stripped = line.strip()
            low = stripped.lower()
            if low.startswith("translate"):
                in_translate = True
                continue
            if in_translate:
                if stripped == ";":
                    in_translate = False
                    continue
                m = re.match(r"^(\d+)\s+([^,;]+?)[,;]?$", stripped)
                if m:
                    translate_map[m.group(1)] = m.group(2).strip("'\"")

        tree_match = re.search(r"tree\s+\S+\s*=\s*(?:\[[^\]]*\]\s*)?(\(.*\);)", text, re.IGNORECASE)
        if not tree_match:
            raise PhyloError("未能从 MrBayes 输出中解析出有效 Newick 树。")

        raw_nwk = tree_match.group(1)

        # 提取内部节点后验概率 prob 转为 0~100 百分制支持率
        def _extract_prob(m: re.Match[str]) -> str:
            try:
                val = float(m.group(1))
                pct = int(round(val * 100)) if val <= 1.0 else int(round(val))
                return f"){pct}"
            except ValueError:
                return ")"

        with_support = re.sub(
            r"\)\[&[^\]]*\bprob=([0-9.eE+-]+)[^\]]*\]",
            _extract_prob,
            raw_nwk,
        )
        # 移除其余 NEXUS 内部注解块 [&...]
        clean_nwk = re.sub(r"\[&[^\]]*\]", "", with_support)

        if translate_map:
            def _map_num(m: re.Match[str]) -> str:
                prefix, num, suffix = m.group(1), m.group(2), m.group(3)
                return f"{prefix}{translate_map.get(num, num)}{suffix}"

            clean_nwk = re.sub(r"([(,])(\d+)([,:)])", _map_num, clean_nwk)

        return clean_nwk
