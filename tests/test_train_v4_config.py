# -*- coding: utf-8 -*-
"""
TrainV4Config 配置对象与 train_distilled_student_v4 精简签名回归测试。
"""
from __future__ import annotations

import inspect
import pytest

from src.phage_discovery.student.distilled_student_v4 import (
    TrainV4Config,
    train_distilled_student_v4,
)

pytestmark = pytest.mark.ml


def test_train_v4_signature_is_concise_and_supports_config() -> None:
    sig = inspect.signature(train_distilled_student_v4)
    assert len(sig.parameters) <= 8
    assert "config" in sig.parameters
    assert any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())


def test_train_v4_config_overrides_and_unknown_key_guard() -> None:
    base = TrainV4Config(epochs=10, batch_size=32, use_functional=True)
    merged = TrainV4Config.from_overrides(base, epochs=4, seed=99)
    assert merged.epochs == 4
    assert merged.batch_size == 32
    assert merged.use_functional is True
    assert merged.seed == 99

    with pytest.raises(TypeError, match="未定义参数"):
        TrainV4Config.from_overrides(base, nonexistent_hyperparam=123)
