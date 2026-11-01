"""Deterministic summaries of database measurements."""

from __future__ import annotations

import math
from statistics import mean, pstdev
from typing import Any


def period_change(before: float, after: float) -> float | None:
    if not before:
        return None
    return (after - before) / abs(before) * 100


def max_delta_changepoint(rows: list[dict[str, Any]], window: int = 3) -> dict[str, Any] | None:
    points = [(row["day"], row["value"]) for row in rows if row.get("value") is not None]
    if len(points) < window * 2:
        return None
    best: tuple[float, int, float, float] | None = None
    for index in range(window, len(points) - window + 1):
        before = mean(value for _, value in points[index - window:index])
        after = mean(value for _, value in points[index:index + window])
        delta = abs(after - before)
        if best is None or delta > best[0]:
            best = (delta, index, before, after)
    if best is None:
        return None
    _, index, before, after = best
    return {"date": points[index][0], "before": before, "after": after, "change_percent": period_change(before, after)}


def zscore_anomalies(rows: list[dict[str, Any]], threshold: float = 3.0) -> list[dict[str, Any]]:
    values = [row["avg_value"] for row in rows if row.get("avg_value") is not None]
    if len(values) < 3:
        return []
    center, spread = mean(values), pstdev(values)
    if spread == 0:
        return []
    return [{**row, "z_score": (row["avg_value"] - center) / spread} for row in rows if row.get("avg_value") is not None and abs((row["avg_value"] - center) / spread) >= threshold]


def confidence(sample_count: int, relative_signal: float | None = None) -> str:
    if sample_count >= 20 and (relative_signal is None or relative_signal >= 0.1):
        return "High"
    if sample_count >= 5:
        return "Med"
    return "Low"