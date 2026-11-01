"""End-to-end deterministic answer checks against the generated ground truth."""

from __future__ import annotations

import json
import math
import statistics
import subprocess
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

BASE_URL = "http://127.0.0.1:8080/api/ask"
GROUND_TRUTH = Path(__file__).parents[1] / "data" / "ground_truth.json"


def ask(query: str, local: bool = False) -> tuple[dict[str, Any], float]:
    if local:
        sys.path.insert(0, str(Path(__file__).parents[1] / "engine"))
        from engine import answer_query

        started = time.perf_counter()
        result = answer_query(query, db_path=Path(__file__).parents[1] / "data" / "vehicle.db")
        return result, (time.perf_counter() - started) * 1000
    request = urllib.request.Request(BASE_URL, data=json.dumps({"query": query}).encode(), headers={"Content-Type": "application/json"}, method="POST")
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.loads(response.read())
    return result, (time.perf_counter() - started) * 1000


def run() -> int:
    local = "--local" in sys.argv
    if not local:
        subprocess.run(
            ["docker", "compose", "cp", "engine:/data/ground_truth.json", str(GROUND_TRUTH)],
            check=True,
        )
    truth = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))
    checks: list[tuple[str, str, str]] = []
    latencies: list[float] = []

    def check(label: str, query: str, assertion: Any) -> None:
        try:
            result, elapsed = ask(query, local=local)
            latencies.append(result.get("latency_ms", elapsed))
            assertion(result)
            checks.append((label, "PASS", ""))
        except Exception as error:
            checks.append((label, "FAIL", str(error)))

    def range_check(result: dict) -> None:
        change = result["evidence"][0]["change_percent"]
        if not truth["range_drop_percent_min"] <= abs(change) <= truth["range_drop_percent_max"]:
            raise AssertionError(f"range change {change:.1f}% not within ground-truth bounds")
        causes = result["answer"].lower()
        if "cold ambient temperature" not in causes or "higher hvac use" not in causes:
            raise AssertionError("cold temperature and higher HVAC are not both reported")

    def adas_check(result: dict) -> None:
        events = [item for item in result["evidence"] if item.get("type") == "adas_disengagement"]
        if len(events) != 5 or len(events) != len(truth["adas_disengagements_yesterday"]):
            raise AssertionError(f"expected 5 ADAS events, got {len(events)}")

    def timeline_check(result: dict) -> None:
        events = [item for item in result["evidence"] if item.get("type") == "battery_overheating_warning"]
        expected = truth["overheating_event_ts"]
        if not events or events[0]["timestamp"] != expected:
            raise AssertionError(f"expected overheating timestamp {expected}; evidence={events}")
        temperatures = [item["value"] for item in result["evidence"] if item.get("metric") == "battery_temp"]
        if len(temperatures) < 2 or temperatures[-1] <= temperatures[0]:
            raise AssertionError("pre-warning battery temperature ramp not found")

    def changepoint_check(result: dict) -> None:
        found = date.fromisoformat(result["evidence"][0]["date"])
        expected = date.fromisoformat(truth["efficiency_change_point_date"])
        delta = abs((found - expected).days)
        if delta > truth["efficiency_change_point_tolerance_days"]:
            raise AssertionError(f"change point {found} is {delta} days from {expected}")

    def anomaly_check(result: dict) -> None:
        if not result["evidence"] or "anomal" not in result["answer"].lower():
            raise AssertionError("sensor anomaly was not detected")
        if not any(item.get("value") == truth["sensor_anomaly"]["value"] for item in result["evidence"]):
            raise AssertionError("ground-truth tyre pressure spike missing from evidence")

    check("range drop + causes", "Why has my driving range reduced over the last two weeks?", range_check)
    check("overheating timeline", "What happened before the battery overheating warning?", timeline_check)
    check("ADAS events yesterday", "Show all ADAS disengagement events from yesterday", adas_check)
    check("efficiency change point", "When did fuel efficiency drop the most?", changepoint_check)
    check("tyre pressure anomaly", "Find the tyre pressure sensor anomaly", anomaly_check)

    print(f"{'QUERY CHECK':<29} {'RESULT':<8} DETAILS")
    print("-" * 76)
    for label, status, detail in checks:
        print(f"{label:<29} {status:<8} {detail}")
    if latencies:
        ordered = sorted(latencies)
        median = statistics.median(ordered)
        p95 = ordered[min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)]
        print(f"Median engine latency: {median:.2f} ms")
        print(f"P95 engine latency:    {p95:.2f} ms")
    return 0 if all(status == "PASS" for _, status, _ in checks) else 1


if __name__ == "__main__":
    sys.exit(run())