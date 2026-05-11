import importlib
import os

import pytest


def test_default_weights_sum_reasonable():
    from apps.shared.matching import config as c
    pos = c.W_COSINE + c.W_BUDGET + c.W_COMMUTE + c.W_FRESHNESS + c.W_SOURCE_REP + c.W_AXIS_BONUS
    assert 0.9 <= pos <= 1.1, f"positive weights should sum near 1.0, got {pos}"


def test_insert_threshold_in_unit_range():
    from apps.shared.matching import config as c
    assert 0.0 < c.INSERT_THRESHOLD < 1.0


def test_quiet_hours_bound():
    from apps.shared.matching import config as c
    assert 0 <= c.QUIET_HOURS_END < c.QUIET_HOURS_START <= 24


def test_env_override(monkeypatch):
    monkeypatch.setenv("MATCHING_W_COSINE", "0.55")
    import apps.shared.matching.config as cfg_mod
    importlib.reload(cfg_mod)
    try:
        assert cfg_mod.W_COSINE == pytest.approx(0.55)
    finally:
        monkeypatch.delenv("MATCHING_W_COSINE")
        importlib.reload(cfg_mod)
