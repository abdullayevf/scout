"""Matching scoring weights, thresholds, and operational gates.

All values can be overridden at process startup via env vars with the
``MATCHING_`` prefix (e.g. ``MATCHING_W_COSINE=0.55``).
"""

import os


def _f(name: str, default: float) -> float:
    raw = os.getenv(f"MATCHING_{name}")
    return float(raw) if raw is not None else default


def _i(name: str, default: int) -> int:
    raw = os.getenv(f"MATCHING_{name}")
    return int(raw) if raw is not None else default


W_COSINE      = _f("W_COSINE",      0.40)
W_BUDGET      = _f("W_BUDGET",      0.20)
W_COMMUTE     = _f("W_COMMUTE",     0.15)
W_FRESHNESS   = _f("W_FRESHNESS",   0.10)
W_SOURCE_REP  = _f("W_SOURCE_REP",  0.05)
W_AXIS_BONUS  = _f("W_AXIS_BONUS",  0.07)
W_RISK        = _f("W_RISK",        0.10)

INSERT_THRESHOLD          = _f("INSERT_THRESHOLD",          0.20)
COLD_START_REACTIONS      = _i("COLD_START_REACTIONS",      10)
INSTANT_DAILY_CAP         = _i("INSTANT_DAILY_CAP",         3)
QUIET_HOURS_START         = _i("QUIET_HOURS_START",         22)
QUIET_HOURS_END           = _i("QUIET_HOURS_END",           8)
GLOBAL_TOP1PCT_BOOTSTRAP  = _f("GLOBAL_TOP1PCT_BOOTSTRAP",  0.75)
THRESHOLD_MIN_PERSONAL    = _i("THRESHOLD_MIN_PERSONAL",    50)
THRESHOLD_MIN_GLOBAL      = _i("THRESHOLD_MIN_GLOBAL",      200)
THRESHOLD_MIN_REACTIONS   = _i("THRESHOLD_MIN_REACTIONS",   10)
