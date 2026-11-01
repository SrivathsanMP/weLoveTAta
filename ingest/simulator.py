"""Deterministic vehicle signal simulator used by the prototype ingest path."""

from __future__ import annotations

import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

SIGNALS: dict[str, tuple[str, float]] = {
    "speed": ("km/h", 0),
    "soc": ("%", 0),
    "battery_temp": ("degC", 0),
    "motor_power": ("kW", 0),
    "energy_consumption_wh_per_km": ("Wh/km", 0),
    "estimated_range_km": ("km", 0),
    "ambient_temp": ("degC", 0),
    "hvac_power": ("kW", 0),
    "tyre_pressure": ("bar", 0),
    "odometer": ("km", 0),
    "drive_mode_label": ("label", 0),
    "adas_state": ("label", 0),
}


def build_dataset(seed: int = 20261101, end: datetime | None = None) -> tuple[list[dict], list[dict], dict]:
    """Return minute-level signals, events, and exact ground truth for one run."""
    rng = random.Random(seed)
    end = (end or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(second=0, microsecond=0)
    start = end - timedelta(days=30)
    yesterday = (end - timedelta(days=1)).date()
    adas_times = [datetime.combine(yesterday, datetime.min.time(), timezone.utc) + timedelta(hours=h) for h in (7, 9, 12, 16, 19)]
    adas_times = [stamp.replace(minute=15, second=0) for stamp in adas_times]
    # Keep every injected event within the generated horizon for unusual test dates.
    adas_times = [stamp for stamp in adas_times if start <= stamp <= end]
    overheating = end - timedelta(days=4, hours=2)
    overheating = overheating.replace(second=0, microsecond=0)
    change_point = end - timedelta(days=18)
    change_point = change_point.replace(hour=0, minute=0, second=0, microsecond=0)
    signals: list[dict] = []
    events: list[dict] = []
    odometer = 18240.0
    # Five-minute samples keep the simulator comfortably inside its memory cap.
    steps = int((end - start).total_seconds() // 300)
    for index in range(steps + 1):
        stamp = start + timedelta(minutes=index * 5)
        day_index = (stamp - start).days
        minute_of_day = stamp.hour * 60 + stamp.minute
        driving = 6 <= stamp.hour <= 22 and minute_of_day % 90 < 42
        city = (stamp.hour % 6) < 4
        speed = max(0.0, (25 if city else 72) + rng.gauss(0, 9)) if driving else 0.0
        ambient = 16.0 - 0.42 * max(0, 20 - stamp.timetuple().tm_yday % 30) + 2.5 * math.sin(day_index / 3)
        cold_period = stamp >= end - timedelta(days=14)
        if cold_period:
            ambient -= 7.0
        hvac = (2.7 if cold_period else 0.8) + (0.8 if driving else 0.0) + rng.random() * 0.2
        consumption = (158 if city else 184) + hvac * (12 if driving else 0) + rng.gauss(0, 4)
        if stamp >= change_point:
              consumption += 55
        battery_temp = 25 + (4 if driving else 0) + rng.gauss(0, 0.5)
        if overheating - timedelta(minutes=10) <= stamp <= overheating:
            battery_temp = 44 + (stamp - (overheating - timedelta(minutes=10))).total_seconds() / 60 * 1.15
        tyre_pressure = 2.45 + rng.gauss(0, 0.025)
        if stamp == start + timedelta(days=11, hours=3):
            tyre_pressure = 4.8
        soc = max(18.0, 88.0 - 3.0 * index / steps)
        values = {
            "speed": (speed, "km/h"), "soc": (soc, "%"), "battery_temp": (battery_temp, "degC"),
            "motor_power": (max(0.0, speed * 0.12 + rng.gauss(0, 0.5)) if driving else 0.0, "kW"),
            "energy_consumption_wh_per_km": (consumption, "Wh/km"),
            "estimated_range_km": (soc * (3.15 if not cold_period else 2.53), "km"),
            "ambient_temp": (ambient, "degC"), "hvac_power": (hvac, "kW"),
            "tyre_pressure": (tyre_pressure, "bar"), "odometer": (odometer, "km"),
            "drive_mode_label": ("city" if city else "highway", "label"),
            "adas_state": ("engaged" if driving else "standby", "label"),
        }
        for signal_id, (value, unit) in values.items():
            signals.append({"ts": stamp, "signal_id": signal_id, "value": value, "unit": unit})
        if speed > 0:
            odometer += speed * 5 / 60_000
    for stamp in adas_times:
        events.append({"ts": stamp, "type": "adas_disengagement", "severity": "warning", "context": {"reason": "driver_override", "description": "ADAS disengaged by driver"}})
    events.append({"ts": overheating, "type": "battery_overheating_warning", "severity": "critical", "context": {"threshold_degC": 55.0, "description": "Battery temperature exceeded warning threshold"}})
    events.append({"ts": start + timedelta(days=11, hours=3), "type": "sensor_anomaly", "severity": "warning", "context": {"signal_id": "tyre_pressure", "description": "Tyre pressure sensor spike"}})
    ordered = sorted(events, key=lambda event: event["ts"])
    ground_truth = {
        "generated_start": start.isoformat(), "generated_end": end.isoformat(),
        "range_drop_percent_min": 15.0, "range_drop_percent_max": 25.0,
        "range_cause": ["cold ambient temperature", "higher HVAC use"],
        "overheating_event_ts": overheating.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "adas_disengagements_yesterday": [stamp.isoformat() for stamp in adas_times],
        "efficiency_change_point_date": change_point.date().isoformat(),
        "efficiency_change_point_tolerance_days": 2,
        "sensor_anomaly": {"signal_id": "tyre_pressure", "ts": (start + timedelta(days=11, hours=3)).isoformat(), "value": 4.8},
    }
    return signals, ordered, ground_truth


def write_ground_truth(path: Path, ground_truth: dict) -> None:
    path.write_text(json.dumps(ground_truth, indent=2), encoding="utf-8")


def iter_signal_rows(signals: list[dict]) -> Iterator[dict]:
    yield from signals