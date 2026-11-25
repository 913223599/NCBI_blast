# -*- coding: utf-8 -*-
"""
PhyloEtaEstimator - 基于各阶段真实运行吞吐效率的动态剩余时间（ETA）估算器
根据下载进度、ORF 预测、ModelFinder 模型测试、ML 迭代及 Bootstrap 分片实时日志，
采用全周期均值与近期滑窗速率加权计算剩余耗时（秒）。
"""
from collections import deque
from dataclasses import dataclass
import re
import time
from typing import Deque, Literal, Optional, Tuple

_TS_PREFIX_RE = re.compile(r"^\[[0-9]{2}:[0-9]{2}:[0-9]{2}\]\s*")
_RE_REF_DL = re.compile(r"\[RefCurator\]\s*下载进度:\s*(\d+)\s*/\s*(\d+)")
_RE_TERL_ORF = re.compile(r"\[TerL-ORF\]\s*ORF\s*预测进度:\s*(\d+)\s*/\s*(\d+)")
_RE_MF_INIT = re.compile(r"ModelFinder will test up to\s+(\d+).*?models", re.IGNORECASE)
_RE_MF_ROW = re.compile(r"^\s*(\d+)\s+[A-Za-z0-9_.+\-]+\s+-?\d+\.\d+\s+\d+\s+\d+\.\d+")
_RE_MF_DONE = re.compile(
    r"(?:Best-fit model(?:\s+according to [A-Z]+)?|Model of substitution|最佳替换模型|INITIALIZING CANDIDATE TREE SET|Creating fast initial tree)",
    re.IGNORECASE,
)
_RE_IQ_ITER_PAIR = re.compile(r"iteration\s+(\d+)\s*/\s*(\d+)", re.IGNORECASE)
_RE_IQ_ITER_LOGL = re.compile(r"iteration\s+(\d+)\s*/\s*logl", re.IGNORECASE)
_RE_BOOTSTRAP = re.compile(r"(?:已完成|已落盘|Bootstrap)[^0-9]*(\d+)\s*/\s*(\d+)")
_RE_GENERIC_RATIO = re.compile(r"(?:进度|progress)\s*[:：]\s*(\d+)\s*/\s*(\d+)", re.IGNORECASE)


@dataclass
class EtaSnapshot:
    """ETA 与子阶段效率实时快照。"""

    eta_seconds: Optional[float] = None
    eta_updated_at: float = 0.0
    substage_label: str = ""
    substage_done: int = 0
    substage_total: int = 0
    rate_per_sec: Optional[float] = None
    rate_text: str = ""
    confidence: Literal["high", "medium", "low"] = "low"


def _format_rate(rate_per_sec: float, unit: str) -> str:
    if rate_per_sec >= 0.5:
        return f"{rate_per_sec:.1f} {unit}/秒"
    return f"{rate_per_sec * 60.0:.1f} {unit}/分"


class PhyloEtaEstimator:
    """实时解析任务日志与阶段切换，输出平滑可靠的 ETA 估算。"""

    def __init__(self, start_ts: Optional[float] = None) -> None:
        now = start_ts if start_ts is not None else time.time()
        self._job_start_ts: float = now

        self._current_stage: str = "pending"
        self._stage_start_ts: float = now

        self._sub_key: str = ""
        self._sub_label: str = ""
        self._sub_unit: str = ""
        self._sub_confidence: Literal["high", "medium", "low"] = "high"
        self._sub_start_ts: float = now
        self._sub_total: int = 0
        self._sub_done: int = 0
        self._samples: Deque[Tuple[float, int]] = deque(maxlen=12)
        self._last_snapshot: EtaSnapshot = EtaSnapshot(eta_updated_at=now)

    def _reset_substage(self) -> None:
        self._sub_key = ""
        self._sub_label = ""
        self._sub_unit = ""
        self._sub_confidence = "high"
        self._sub_start_ts = 0.0
        self._sub_total = 0
        self._sub_done = 0
        self._samples.clear()

    def _activate_substage(
        self,
        key: str,
        label: str,
        unit: str,
        total: int,
        done: int,
        now: float,
        confidence: Literal["high", "medium", "low"] = "high",
    ) -> bool:
        if total <= 0:
            return False

        if key != self._sub_key or total != self._sub_total:
            self._sub_key = key
            self._sub_label = label
            self._sub_unit = unit
            self._sub_confidence = confidence
            self._sub_total = total
            self._sub_done = max(0, min(done, total))
            # 有明确初始化(done==0)时以初始化时刻为起点；首条日志即带进度(done>0)时回溯至当前阶段启动时刻
            self._sub_start_ts = self._stage_start_ts if self._sub_done > 0 else now
            self._samples.clear()
            if self._sub_done > 0:
                self._samples.append((now, self._sub_done))
            return True

        clamped_done = max(0, min(done, total))
        if clamped_done <= self._sub_done:
            return False

        self._sub_done = clamped_done
        self._samples.append((now, clamped_done))
        return True

    def _build_snapshot(self, now: float) -> EtaSnapshot:
        # 仅在当前存在明确可计数活跃子阶段时输出实测速率与 ETA，禁止跨阶段进度线性外推
        if self._sub_key and self._sub_total > 0:
            label = f"{self._sub_label} ({self._sub_done}/{self._sub_total})"
            rem_items = max(0, self._sub_total - self._sub_done)
            elapsed = max(0.0, now - self._sub_start_ts)
            is_modelfinder = self._sub_key == "modelfinder"
            min_done = 3 if is_modelfinder else 1
            min_elapsed = 3.0 if is_modelfinder else 0.25

            if rem_items > 0 and self._sub_done >= min_done and elapsed >= min_elapsed:
                avg_rate = self._sub_done / elapsed
                rate = avg_rate
                if len(self._samples) >= 2:
                    t0, d0 = self._samples[0]
                    t1, d1 = self._samples[-1]
                    dt = t1 - t0
                    dd = d1 - d0
                    if dt >= 0.25 and dd > 0:
                        win_rate = dd / dt
                        if is_modelfinder:
                            rate = 0.3 * win_rate + 0.7 * avg_rate
                        else:
                            rate = 0.6 * win_rate + 0.4 * avg_rate
                if rate > 1e-6:
                    eta_sec = round(rem_items / rate, 1)
                    snap = EtaSnapshot(
                        eta_seconds=eta_sec,
                        eta_updated_at=now,
                        substage_label=label,
                        substage_done=self._sub_done,
                        substage_total=self._sub_total,
                        rate_per_sec=rate,
                        rate_text=_format_rate(rate, self._sub_unit),
                        confidence=self._sub_confidence,
                    )
                    self._last_snapshot = snap
                    return snap

            snap = EtaSnapshot(
                eta_seconds=None,
                eta_updated_at=now,
                substage_label=label,
                substage_done=self._sub_done,
                substage_total=self._sub_total,
                rate_per_sec=None,
                rate_text="",
                confidence=self._sub_confidence,
            )
            self._last_snapshot = snap
            return snap

        snap = EtaSnapshot(
            eta_seconds=None,
            eta_updated_at=now,
            substage_label="",
            substage_done=0,
            substage_total=0,
            rate_per_sec=None,
            rate_text="",
            confidence="low",
        )
        self._last_snapshot = snap
        return snap

    def on_stage(
        self,
        stage: str,
        status: str,
        progress: int,
        now: Optional[float] = None,
    ) -> EtaSnapshot:
        ts = now if now is not None else time.time()
        _ = progress
        if status in ("cached", "completed", "skipped"):
            self._reset_substage()
        elif status == "running" and stage != self._current_stage:
            self._current_stage = stage
            self._stage_start_ts = ts
            self._reset_substage()

        return self._build_snapshot(ts)

    def on_log(self, line: str, now: Optional[float] = None) -> Tuple[bool, EtaSnapshot]:
        ts = now if now is not None else time.time()
        clean = _TS_PREFIX_RE.sub("", (line or "").strip())
        if not clean:
            return False, self._last_snapshot

        changed = False

        if (m := _RE_REF_DL.search(clean)) is not None:
            changed = self._activate_substage(
                "ref_download", "参考基因组下载", "株", int(m.group(2)), int(m.group(1)), ts, "high"
            )
        elif (m := _RE_TERL_ORF.search(clean)) is not None:
            changed = self._activate_substage(
                "terl_orf", "ORF 蛋白预测", "株", int(m.group(2)), int(m.group(1)), ts, "high"
            )
        elif (m := _RE_MF_INIT.search(clean)) is not None:
            changed = self._activate_substage(
                "modelfinder", "ModelFinder 模型筛选", "模型", int(m.group(1)), 0, ts, "medium"
            )
        elif self._sub_key == "modelfinder" and _RE_MF_DONE.search(clean):
            self._reset_substage()
            return True, self._build_snapshot(ts)
        elif self._sub_key == "modelfinder" and (m := _RE_MF_ROW.match(clean)) is not None:
            changed = self._activate_substage(
                "modelfinder",
                "ModelFinder 模型筛选",
                "模型",
                self._sub_total,
                int(m.group(1)),
                ts,
                "medium",
            )
        elif (m := _RE_IQ_ITER_PAIR.search(clean)) is not None:
            changed = self._activate_substage(
                "iqtree_iter", "IQ-TREE ML 迭代", "轮", int(m.group(2)), int(m.group(1)), ts, "high"
            )
        elif (m := _RE_IQ_ITER_LOGL.search(clean)) is not None:
            done_iter = int(m.group(1))
            est_total = max(100, ((done_iter // 100) + 1) * 100)
            changed = self._activate_substage(
                "iqtree_iter", "IQ-TREE ML 迭代", "轮", est_total, done_iter, ts, "low"
            )
        elif (m := _RE_BOOTSTRAP.search(clean)) is not None:
            changed = self._activate_substage(
                "bootstrap", "Bootstrap 抽样", "次", int(m.group(2)), int(m.group(1)), ts, "high"
            )
        elif (m := _RE_GENERIC_RATIO.search(clean)) is not None:
            changed = self._activate_substage(
                "generic_ratio", "当前子步骤", "项", int(m.group(2)), int(m.group(1)), ts, "medium"
            )

        if not changed:
            return False, self._last_snapshot
        return True, self._build_snapshot(ts)
