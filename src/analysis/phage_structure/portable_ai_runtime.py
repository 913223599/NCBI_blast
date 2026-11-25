# -*- coding: utf-8 -*-
"""
零 scikit-learn 版本依赖的 PhageStructure 双轨 AI 便携推理运行时 (PortableAIRuntime)

职责：
1. 提供与 scikit-learn 推理语义完全等价的纯 NumPy 确定性推理组件
   （StandardScaler / PCA / ColumnTransformer / LogisticRegression /
   HistGradientBoostingClassifier / VotingClassifier / Pipeline）；
2. 将训练好的 `.joblib` 双轨模型导出为 `.portable.npz`（数值数组）+ `.portable.json`
   （拓扑结构与元数据），加载时禁用 pickle（`allow_pickle=False`），彻底消除跨
   scikit-learn 版本的反序列化崩溃（如 `No module named '_loss'`）；
3. 为历史 `.joblib` 提供线程/上下文安全的兼容加载兜底 (`safe_joblib_load`)，
   并在加载后自动将 `HistGradientBoostingClassifier` 转为纯 NumPy 推理器。
"""
from __future__ import annotations

import contextlib
import importlib
import json
import sys
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

_LOSS_ALIAS_LOCK = threading.Lock()


def _softmax(logits: np.ndarray) -> np.ndarray:
    arr = np.asarray(logits, dtype=np.float64)
    if arr.ndim == 1:
        arr = arr[None, :]
    shifted = arr - np.max(arr, axis=1, keepdims=True)
    exp_v = np.exp(shifted)
    return exp_v / np.sum(exp_v, axis=1, keepdims=True)


def _sigmoid(x: np.ndarray) -> np.ndarray:
    arr = np.asarray(x, dtype=np.float64)
    out = np.empty_like(arr, dtype=np.float64)
    pos = arr >= 0
    out[pos] = 1.0 / (1.0 + np.exp(-arr[pos]))
    exp_x = np.exp(arr[~pos])
    out[~pos] = exp_x / (1.0 + exp_x)
    return out


class PortableStandardScaler:
    """纯 NumPy StandardScaler 推理器。"""

    def __init__(
        self,
        *,
        mean: Optional[np.ndarray],
        scale: Optional[np.ndarray],
        with_mean: bool = True,
        with_std: bool = True,
    ) -> None:
        self.mean_ = np.asarray(mean, dtype=np.float64) if mean is not None else None
        self.scale_ = np.asarray(scale, dtype=np.float64) if scale is not None else None
        self.with_mean = bool(with_mean)
        self.with_std = bool(with_std)

    def transform(self, X: np.ndarray) -> np.ndarray:
        arr = np.asarray(X, dtype=np.float64).copy()
        if self.with_mean and self.mean_ is not None:
            arr -= self.mean_
        if self.with_std and self.scale_ is not None:
            safe_scale = np.where(self.scale_ == 0.0, 1.0, self.scale_)
            arr /= safe_scale
        return arr


class PortablePCA:
    """纯 NumPy PCA 推理器。"""

    def __init__(
        self,
        *,
        mean: Optional[np.ndarray],
        components: np.ndarray,
        explained_variance: Optional[np.ndarray] = None,
        whiten: bool = False,
    ) -> None:
        self.mean_ = np.asarray(mean, dtype=np.float64) if mean is not None else None
        self.components_ = np.asarray(components, dtype=np.float64)
        self.explained_variance_ = (
            np.asarray(explained_variance, dtype=np.float64)
            if explained_variance is not None
            else None
        )
        self.whiten = bool(whiten)

    def transform(self, X: np.ndarray) -> np.ndarray:
        arr = np.asarray(X, dtype=np.float64)
        if self.mean_ is not None:
            arr = arr - self.mean_
        proj = arr @ self.components_.T
        if self.whiten and self.explained_variance_ is not None:
            proj = proj / np.sqrt(np.maximum(self.explained_variance_, 1e-12))
        return proj


class PortableColumnTransformer:
    """纯 NumPy ColumnTransformer（按切片列块依次变换后横向拼接）。"""

    def __init__(self, transformers: Sequence[Tuple[str, Any, Tuple[int, int]]]) -> None:
        self.transformers: List[Tuple[str, Any, Tuple[int, int]]] = [
            (str(name), tr, (int(sl[0]), int(sl[1]))) for name, tr, sl in transformers
        ]

    def transform(self, X: np.ndarray) -> np.ndarray:
        arr = np.asarray(X, dtype=np.float64)
        parts: List[np.ndarray] = []
        for _name, tr, (start, stop) in self.transformers:
            sub = arr[:, start:stop]
            if tr is None or tr == "passthrough":
                parts.append(sub)
            elif tr == "drop":
                continue
            else:
                parts.append(np.asarray(tr.transform(sub), dtype=np.float64))
        return np.hstack(parts)


class PortableLogisticRegression:
    """纯 NumPy LogisticRegression 概率推理器。"""

    def __init__(
        self,
        *,
        coef: np.ndarray,
        intercept: np.ndarray,
        classes: Optional[np.ndarray] = None,
    ) -> None:
        self.coef_ = np.asarray(coef, dtype=np.float64)
        self.intercept_ = np.asarray(intercept, dtype=np.float64)
        self.classes_ = np.asarray(classes) if classes is not None else None

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        arr = np.asarray(X, dtype=np.float64)
        scores = arr @ self.coef_.T + self.intercept_
        if scores.ndim == 1:
            scores = scores[:, None]
        if self.coef_.shape[0] == 1:
            p1 = _sigmoid(scores[:, 0])
            return np.column_stack([1.0 - p1, p1])
        return _softmax(scores)


class PortableHistGBClassifier:
    """纯 NumPy HistGradientBoostingClassifier 推理器（严格对齐 sklearn 数值节点遍历与 NaN 路由）。"""

    def __init__(
        self,
        *,
        baseline_prediction: np.ndarray,
        n_iter: int,
        n_trees_per_iteration: int,
        tree_offsets: np.ndarray,
        feature_idx: np.ndarray,
        num_threshold: np.ndarray,
        missing_go_to_left: np.ndarray,
        left: np.ndarray,
        right: np.ndarray,
        is_leaf: np.ndarray,
        value: np.ndarray,
        classes: Optional[np.ndarray] = None,
    ) -> None:
        self.baseline_prediction = np.asarray(baseline_prediction, dtype=np.float64)
        self.n_iter = int(n_iter)
        self.n_trees_per_iteration = int(n_trees_per_iteration)
        self.tree_offsets = np.asarray(tree_offsets, dtype=np.int64)
        self.feature_idx = np.asarray(feature_idx, dtype=np.int64)
        self.num_threshold = np.asarray(num_threshold, dtype=np.float64)
        self.missing_go_to_left = np.asarray(missing_go_to_left, dtype=np.uint8)
        self.left = np.asarray(left, dtype=np.int64)
        self.right = np.asarray(right, dtype=np.int64)
        self.is_leaf = np.asarray(is_leaf, dtype=np.uint8)
        self.value = np.asarray(value, dtype=np.float64)
        self.classes_ = np.asarray(classes) if classes is not None else None

    def _predict_single_tree(self, X: np.ndarray, base_offset: int) -> np.ndarray:
        n_samples = X.shape[0]
        cur = np.full(n_samples, base_offset, dtype=np.int64)
        active = self.is_leaf[cur] == 0
        while np.any(active):
            idx_rows = np.flatnonzero(active)
            nodes = cur[idx_rows]
            f_idx = self.feature_idx[nodes]
            vals = X[idx_rows, f_idx]
            is_nan = np.isnan(vals)
            thresh = self.num_threshold[nodes]
            go_left_nan = self.missing_go_to_left[nodes] != 0
            # sklearn 语义：NaN 看 missing_go_to_left；非 NaN 严格执行 val <= num_threshold 走左子树
            go_left = np.where(is_nan, go_left_nan, vals <= thresh)
            cur[idx_rows] = np.where(
                go_left,
                base_offset + self.left[nodes],
                base_offset + self.right[nodes],
            )
            active = self.is_leaf[cur] == 0
        return self.value[cur]

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        arr = np.asarray(X, dtype=np.float64)
        n_samples = arr.shape[0]
        if n_samples == 0:
            n_out = 2 if self.n_trees_per_iteration == 1 else self.n_trees_per_iteration
            return np.zeros((0, n_out), dtype=np.float64)

        raw = np.repeat(self.baseline_prediction.reshape(1, -1), n_samples, axis=0).astype(np.float64)
        total_trees = self.n_iter * self.n_trees_per_iteration
        for t_idx in range(total_trees):
            k = t_idx % self.n_trees_per_iteration
            raw[:, k] += self._predict_single_tree(arr, int(self.tree_offsets[t_idx]))

        if self.n_trees_per_iteration == 1:
            p1 = _sigmoid(raw[:, 0])
            return np.column_stack([1.0 - p1, p1])
        return _softmax(raw)


class PortableVotingClassifier:
    """纯 NumPy soft VotingClassifier 推理器。"""

    def __init__(
        self,
        *,
        estimators: Sequence[Any],
        weights: Optional[Sequence[float]] = None,
        voting: str = "soft",
    ) -> None:
        if voting != "soft":
            raise ValueError(f"PortableVotingClassifier 仅支持 soft voting，收到: {voting}")
        self.estimators = list(estimators)
        self.weights = [float(w) for w in weights] if weights is not None else None
        self.voting = voting

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        arr = np.asarray(X, dtype=np.float64)
        probs = [np.asarray(est.predict_proba(arr), dtype=np.float64) for est in self.estimators]
        if self.weights is None:
            return np.mean(probs, axis=0)
        w = np.asarray(self.weights, dtype=np.float64)
        w = w / np.sum(w)
        out = np.zeros_like(probs[0], dtype=np.float64)
        for weight, p in zip(w, probs, strict=True):
            out += weight * p
        return out


class PortablePipeline:
    """纯 NumPy 串联推理管线，接口兼容 sklearn.pipeline.Pipeline。"""

    def __init__(self, steps: Sequence[Tuple[str, Any]]) -> None:
        self.steps: List[Tuple[str, Any]] = [(str(name), step) for name, step in steps]

    def transform(self, X: np.ndarray) -> np.ndarray:
        cur = np.asarray(X, dtype=np.float64)
        for _name, step in self.steps:
            cur = np.asarray(step.transform(cur), dtype=np.float64)
        return cur

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        cur = np.asarray(X, dtype=np.float64)
        for _name, step in self.steps[:-1]:
            if step is not None and step != "passthrough":
                cur = np.asarray(step.transform(cur), dtype=np.float64)
        return np.asarray(self.steps[-1][1].predict_proba(cur), dtype=np.float64)


# ---------------------------------------------------------------------------
# sklearn 对象 -> 纯 NumPy 便携表示转换与 NPZ/JSON 序列化
# ---------------------------------------------------------------------------

def _class_name(obj: Any) -> str:
    return f"{type(obj).__module__}.{type(obj).__name__}"


def _convert_histgb_to_portable(est: Any) -> PortableHistGBClassifier:
    predictors = getattr(est, "_predictors", None)
    if not predictors:
        raise ValueError("HistGradientBoostingClassifier 缺少 _predictors 属性")
    n_iter = len(predictors)
    n_trees_per_iter = len(predictors[0])

    offsets: List[int] = [0]
    feat_parts: List[np.ndarray] = []
    thresh_parts: List[np.ndarray] = []
    miss_parts: List[np.ndarray] = []
    left_parts: List[np.ndarray] = []
    right_parts: List[np.ndarray] = []
    leaf_parts: List[np.ndarray] = []
    val_parts: List[np.ndarray] = []

    cursor = 0
    for it_trees in predictors:
        for tree_pred in it_trees:
            nodes = tree_pred.nodes
            if np.any(nodes["is_categorical"] != 0):
                raise ValueError("当前便携推理器仅支持纯数值树节点，不支持 categorical 分裂")
            cnt = len(nodes)
            feat_parts.append(nodes["feature_idx"].astype(np.int64))
            thresh_parts.append(nodes["num_threshold"].astype(np.float64))
            miss_parts.append(nodes["missing_go_to_left"].astype(np.uint8))
            left_parts.append(nodes["left"].astype(np.int64))
            right_parts.append(nodes["right"].astype(np.int64))
            leaf_parts.append(nodes["is_leaf"].astype(np.uint8))
            val_parts.append(nodes["value"].astype(np.float64))
            cursor += cnt
            offsets.append(cursor)

    return PortableHistGBClassifier(
        baseline_prediction=np.asarray(est._baseline_prediction, dtype=np.float64),
        n_iter=n_iter,
        n_trees_per_iteration=n_trees_per_iter,
        tree_offsets=np.asarray(offsets[:-1], dtype=np.int64),
        feature_idx=np.concatenate(feat_parts),
        num_threshold=np.concatenate(thresh_parts),
        missing_go_to_left=np.concatenate(miss_parts),
        left=np.concatenate(left_parts),
        right=np.concatenate(right_parts),
        is_leaf=np.concatenate(leaf_parts),
        value=np.concatenate(val_parts),
        classes=getattr(est, "classes_", None),
    )


def convert_sklearn_to_portable(obj: Any) -> Any:
    """将常见 sklearn Pipeline / Estimator 递归转为零 pickle 依赖的便携推理对象。"""
    if isinstance(
        obj,
        (
            PortablePipeline,
            PortableColumnTransformer,
            PortableStandardScaler,
            PortablePCA,
            PortableLogisticRegression,
            PortableHistGBClassifier,
            PortableVotingClassifier,
        ),
    ):
        return obj

    cname = type(obj).__name__
    if cname == "Pipeline":
        return PortablePipeline([(name, convert_sklearn_to_portable(step)) for name, step in obj.steps])
    if cname == "ColumnTransformer":
        items = []
        for name, tr, cols in obj.transformers_:
            if not isinstance(cols, slice) or cols.step not in (None, 1):
                raise ValueError(f"ColumnTransformer 仅支持连续 slice 列选择，收到: {cols}")
            items.append((name, convert_sklearn_to_portable(tr) if tr not in ("drop", "passthrough", None) else tr, (cols.start or 0, cols.stop)))
        return PortableColumnTransformer(items)
    if cname == "StandardScaler":
        return PortableStandardScaler(
            mean=getattr(obj, "mean_", None),
            scale=getattr(obj, "scale_", None),
            with_mean=getattr(obj, "with_mean", True),
            with_std=getattr(obj, "with_std", True),
        )
    if cname == "PCA":
        return PortablePCA(
            mean=getattr(obj, "mean_", None),
            components=obj.components_,
            explained_variance=getattr(obj, "explained_variance_", None),
            whiten=getattr(obj, "whiten", False),
        )
    if cname == "LogisticRegression":
        return PortableLogisticRegression(
            coef=obj.coef_,
            intercept=obj.intercept_,
            classes=getattr(obj, "classes_", None),
        )
    if cname == "HistGradientBoostingClassifier":
        return _convert_histgb_to_portable(obj)
    if cname == "VotingClassifier":
        return PortableVotingClassifier(
            estimators=[convert_sklearn_to_portable(e) for e in obj.estimators_],
            weights=getattr(obj, "weights", None),
            voting=getattr(obj, "voting", "soft"),
        )
    raise TypeError(f"暂不支持转换为便携推理器的对象类型: {_class_name(obj)}")


class _NpzPacker:
    """将层级便携对象树序列化为 JSON 拓扑 + 扁平 NPZ 数组字典。"""

    def __init__(self) -> None:
        self.arrays: Dict[str, np.ndarray] = {}
        self._counter = 0

    def put(self, tag: str, arr: Optional[np.ndarray]) -> Optional[str]:
        if arr is None:
            return None
        key = f"a{self._counter:04d}_{tag}"
        self._counter += 1
        self.arrays[key] = np.asarray(arr)
        return key

    def serialize(self, obj: Any) -> Any:
        if isinstance(obj, PortablePipeline):
            return {
                "type": "Pipeline",
                "steps": [[name, self.serialize(step)] for name, step in obj.steps],
            }
        if isinstance(obj, PortableColumnTransformer):
            return {
                "type": "ColumnTransformer",
                "transformers": [
                    [name, self.serialize(tr) if not isinstance(tr, str) and tr is not None else tr, [sl[0], sl[1]]]
                    for name, tr, sl in obj.transformers
                ],
            }
        if isinstance(obj, PortableStandardScaler):
            return {
                "type": "StandardScaler",
                "with_mean": obj.with_mean,
                "with_std": obj.with_std,
                "mean": self.put("ss_mean", obj.mean_),
                "scale": self.put("ss_scale", obj.scale_),
            }
        if isinstance(obj, PortablePCA):
            return {
                "type": "PCA",
                "whiten": obj.whiten,
                "mean": self.put("pca_mean", obj.mean_),
                "components": self.put("pca_comp", obj.components_),
                "explained_variance": self.put("pca_ev", obj.explained_variance_),
            }
        if isinstance(obj, PortableLogisticRegression):
            return {
                "type": "LogisticRegression",
                "coef": self.put("lr_coef", obj.coef_),
                "intercept": self.put("lr_int", obj.intercept_),
                "classes": self.put("lr_cls", obj.classes_),
            }
        if isinstance(obj, PortableHistGBClassifier):
            return {
                "type": "HistGBClassifier",
                "n_iter": obj.n_iter,
                "n_trees_per_iteration": obj.n_trees_per_iteration,
                "baseline_prediction": self.put("hgb_base", obj.baseline_prediction),
                "tree_offsets": self.put("hgb_off", obj.tree_offsets),
                "feature_idx": self.put("hgb_fidx", obj.feature_idx),
                "num_threshold": self.put("hgb_thr", obj.num_threshold),
                "missing_go_to_left": self.put("hgb_miss", obj.missing_go_to_left),
                "left": self.put("hgb_left", obj.left),
                "right": self.put("hgb_right", obj.right),
                "is_leaf": self.put("hgb_leaf", obj.is_leaf),
                "value": self.put("hgb_val", obj.value),
                "classes": self.put("hgb_cls", obj.classes_),
            }
        if isinstance(obj, PortableVotingClassifier):
            return {
                "type": "VotingClassifier",
                "voting": obj.voting,
                "weights": obj.weights,
                "estimators": [self.serialize(e) for e in obj.estimators],
            }
        raise TypeError(f"无法序列化未知便携类型: {type(obj).__name__}")


def _deserialize_node(spec: Any, arrays: Dict[str, np.ndarray]) -> Any:
    if spec is None or isinstance(spec, str):
        return spec
    t = spec["type"]
    if t == "Pipeline":
        return PortablePipeline([(name, _deserialize_node(st, arrays)) for name, st in spec["steps"]])
    if t == "ColumnTransformer":
        return PortableColumnTransformer([
            (name, _deserialize_node(tr, arrays), (int(sl[0]), int(sl[1])))
            for name, tr, sl in spec["transformers"]
        ])
    if t == "StandardScaler":
        return PortableStandardScaler(
            mean=arrays[spec["mean"]] if spec.get("mean") else None,
            scale=arrays[spec["scale"]] if spec.get("scale") else None,
            with_mean=bool(spec.get("with_mean", True)),
            with_std=bool(spec.get("with_std", True)),
        )
    if t == "PCA":
        return PortablePCA(
            mean=arrays[spec["mean"]] if spec.get("mean") else None,
            components=arrays[spec["components"]],
            explained_variance=arrays[spec["explained_variance"]] if spec.get("explained_variance") else None,
            whiten=bool(spec.get("whiten", False)),
        )
    if t == "LogisticRegression":
        return PortableLogisticRegression(
            coef=arrays[spec["coef"]],
            intercept=arrays[spec["intercept"]],
            classes=arrays[spec["classes"]] if spec.get("classes") else None,
        )
    if t == "HistGBClassifier":
        return PortableHistGBClassifier(
            baseline_prediction=arrays[spec["baseline_prediction"]],
            n_iter=int(spec["n_iter"]),
            n_trees_per_iteration=int(spec["n_trees_per_iteration"]),
            tree_offsets=arrays[spec["tree_offsets"]],
            feature_idx=arrays[spec["feature_idx"]],
            num_threshold=arrays[spec["num_threshold"]],
            missing_go_to_left=arrays[spec["missing_go_to_left"]],
            left=arrays[spec["left"]],
            right=arrays[spec["right"]],
            is_leaf=arrays[spec["is_leaf"]],
            value=arrays[spec["value"]],
            classes=arrays[spec["classes"]] if spec.get("classes") else None,
        )
    if t == "VotingClassifier":
        return PortableVotingClassifier(
            estimators=[_deserialize_node(e, arrays) for e in spec["estimators"]],
            weights=spec.get("weights"),
            voting=str(spec.get("voting", "soft")),
        )
    raise ValueError(f"未知的便携推理节点类型: {t}")


def get_portable_model_paths(joblib_path: Path) -> Tuple[Path, Path]:
    """根据 `.joblib` 模型路径返回对应的 `.portable.npz` 与 `.portable.json` 路径。"""
    p = Path(joblib_path)
    return p.with_suffix(".portable.npz"), p.with_suffix(".portable.json")


def has_portable_model_files(joblib_path: Path) -> bool:
    """判断给定模型路径对应的零 pickle 便携推理包是否成对存在。"""
    npz_p, json_p = get_portable_model_paths(joblib_path)
    return npz_p.is_file() and json_p.is_file()


@contextlib.contextmanager
def _sklearn_loss_alias_ctx() -> Iterable[None]:
    """兼容加载在 sklearn 1.7.x 序列化、将 CyHalfMultinomialLoss 指向顶层 `_loss` 的 joblib。"""
    with _LOSS_ALIAS_LOCK:
        had_loss = "_loss" in sys.modules
        prev_loss = sys.modules.get("_loss")
        injected = False
        if not had_loss:
            try:
                sklearn_loss = importlib.import_module("sklearn._loss._loss")
                sys.modules["_loss"] = sklearn_loss
                injected = True
            except Exception:
                injected = False
        try:
            yield
        finally:
            if injected:
                if had_loss:
                    sys.modules["_loss"] = prev_loss  # type: ignore[assignment]
                else:
                    sys.modules.pop("_loss", None)


def safe_joblib_load(joblib_path: Path, *, convert_pipelines: bool = True) -> Any:
    """安全加载历史 `.joblib` 模型包：自动兼容 `_loss` 模块别名并可现场转换为便携推理器。"""
    import joblib

    with _sklearn_loss_alias_ctx():
        obj = joblib.load(joblib_path)

    if convert_pipelines and isinstance(obj, dict):
        converted = dict(obj)
        for key in ("deep_only_pipeline", "fusion_pipeline"):
            if key in converted and converted[key] is not None:
                converted[key] = convert_sklearn_to_portable(converted[key])
        return converted
    return obj


def export_portable_bundle_from_joblib(joblib_path: Path) -> Tuple[Path, Path]:
    """将 `.joblib` 双轨 AI 权重包转换为 `.portable.npz` + `.portable.json` 并落盘。"""
    raw_bundle = safe_joblib_load(Path(joblib_path), convert_pipelines=False)
    if not isinstance(raw_bundle, dict):
        raise ValueError(f"无效的模型权重包格式（非 dict）: {joblib_path}")

    packer = _NpzPacker()
    meta_doc: Dict[str, Any] = {
        "schema_version": 1,
        "model_version": str(raw_bundle.get("model_version") or "morphotype_ai_v1"),
        "judge_version": str(raw_bundle.get("judge_version") or "Unified V4.3"),
        "classes": [str(c) for c in (raw_bundle.get("classes") or ())],
        "deep_only_head": str(raw_bundle.get("deep_only_head") or ""),
        "deep_only_temperature": float(raw_bundle.get("deep_only_temperature", 1.0)),
        "fusion_feature_mode": str(raw_bundle.get("fusion_feature_mode") or ""),
        "fusion_head": str(raw_bundle.get("fusion_head") or ""),
        "fusion_temperature": float(raw_bundle.get("fusion_temperature", 1.0)),
        "trained_at_utc": str(raw_bundle.get("trained_at_utc") or ""),
    }
    if "fine_role_channels" in raw_bundle:
        meta_doc["fine_role_channels"] = [str(c) for c in raw_bundle["fine_role_channels"]]
    if "fine_role_mlp_in_dim" in raw_bundle:
        meta_doc["fine_role_mlp_in_dim"] = int(raw_bundle["fine_role_mlp_in_dim"])

    if raw_bundle.get("deep_only_pipeline") is not None:
        deep_port = convert_sklearn_to_portable(raw_bundle["deep_only_pipeline"])
        meta_doc["deep_only_pipeline"] = packer.serialize(deep_port)

    if raw_bundle.get("fusion_pipeline") is not None:
        fusion_port = convert_sklearn_to_portable(raw_bundle["fusion_pipeline"])
        meta_doc["fusion_pipeline"] = packer.serialize(fusion_port)

    state_dict = raw_bundle.get("fine_role_mlp_state_dict")
    if isinstance(state_dict, dict):
        sd_map: Dict[str, str] = {}
        for k, tensor in state_dict.items():
            np_val = tensor.detach().cpu().numpy() if hasattr(tensor, "detach") else np.asarray(tensor)
            sd_map[str(k)] = packer.put(f"mlp_{k}", np_val.astype(np.float32)) or ""
        meta_doc["fine_role_mlp_state_dict"] = sd_map

    npz_path, json_path = get_portable_model_paths(Path(joblib_path))
    tmp_npz = npz_path.with_suffix(".npz.tmp")
    tmp_json = json_path.with_suffix(".json.tmp")
    with tmp_npz.open("wb") as fh:
        np.savez_compressed(fh, **packer.arrays)
    tmp_json.write_text(json.dumps(meta_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_npz.replace(npz_path)
    tmp_json.replace(json_path)
    return npz_path, json_path


def load_portable_ai_bundle(npz_path: Path, json_path: Path) -> Dict[str, Any]:
    """从 `.portable.npz` + `.portable.json` 加载 AI 双轨权重包（零 pickle / 零 sklearn 依赖）。"""
    import torch

    meta_doc = json.loads(Path(json_path).read_text(encoding="utf-8"))
    with np.load(Path(npz_path), allow_pickle=False) as npz_data:
        arrays: Dict[str, np.ndarray] = {k: npz_data[k] for k in npz_data.files}

    bundle: Dict[str, Any] = {
        "model_version": meta_doc.get("model_version", "morphotype_ai_v1"),
        "judge_version": meta_doc.get("judge_version", "Unified V4.3"),
        "classes": tuple(meta_doc.get("classes") or ()),
        "deep_only_head": meta_doc.get("deep_only_head", ""),
        "deep_only_temperature": float(meta_doc.get("deep_only_temperature", 1.0)),
        "fusion_feature_mode": meta_doc.get("fusion_feature_mode", ""),
        "fusion_head": meta_doc.get("fusion_head", ""),
        "fusion_temperature": float(meta_doc.get("fusion_temperature", 1.0)),
        "trained_at_utc": meta_doc.get("trained_at_utc", ""),
        "runtime_backend": "portable_numpy",
    }
    if "fine_role_channels" in meta_doc:
        bundle["fine_role_channels"] = tuple(meta_doc["fine_role_channels"])
    if "fine_role_mlp_in_dim" in meta_doc:
        bundle["fine_role_mlp_in_dim"] = int(meta_doc["fine_role_mlp_in_dim"])

    if "deep_only_pipeline" in meta_doc:
        bundle["deep_only_pipeline"] = _deserialize_node(meta_doc["deep_only_pipeline"], arrays)
    if "fusion_pipeline" in meta_doc:
        bundle["fusion_pipeline"] = _deserialize_node(meta_doc["fusion_pipeline"], arrays)

    sd_map = meta_doc.get("fine_role_mlp_state_dict")
    if isinstance(sd_map, dict):
        bundle["fine_role_mlp_state_dict"] = {
            k: torch.from_numpy(np.array(arrays[arr_key], copy=True))
            for k, arr_key in sd_map.items()
        }

    return bundle
