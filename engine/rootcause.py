"""Rule-based explanation ranking, with conservative evidence thresholds."""

from __future__ import annotations

from typing import Any


def rank_range_causes(before: dict[str, Any], recent: dict[str, Any]) -> dict[str, Any]:
    contributions: list[tuple[str, float, str]] = []
    for label, key, direction in (
        ("cold ambient temperature", "ambient_temp", "lower"),
        ("higher HVAC use", "hvac_power", "higher"),
        ("lower tyre pressure", "tyre_pressure", "lower"),
        ("higher driving speed", "speed", "higher"),
    ):
        old, new = before.get(key), recent.get(key)
        if old is None or new is None or old == 0:
            continue
        delta = (old - new) / abs(old) if direction == "lower" else (new - old) / abs(old)
        if delta > 0.03:
            contributions.append((label, delta, f"{old:.1f} to {new:.1f}"))
    contributions.sort(key=lambda item: item[1], reverse=True)
    total = sum(item[1] for item in contributions)
    ranked = [{"cause": name, "contribution_percent": round(part / total * 100, 1), "observed": observed} for name, part, observed in contributions] if total else []
    confidence = "High" if len(ranked) >= 2 else "Med" if ranked else "Low"
    if not ranked or total < 0.05:
        return {"causes": [], "confidence": "Low", "conclusion": "insufficient evidence"}
    return {"causes": ranked, "confidence": confidence, "conclusion": "measured contributors found"}