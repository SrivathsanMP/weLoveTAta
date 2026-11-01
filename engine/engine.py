"""Read-only deterministic vehicle query service over a Unix domain socket."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from analytics import confidence, max_delta_changepoint, zscore_anomalies
from intents import parse_intent
from llm import load_model
from rootcause import rank_range_causes
from sql_templates import execute

DB_PATH = Path(os.environ.get("DB_PATH", "/data/vehicle.db"))
SOCKET_PATH = Path(os.environ.get("SOCKET_PATH", "/ipc/engine.sock"))
MODEL = load_model()


def open_database(path: Path = DB_PATH) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=2)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _window(intent: dict[str, Any]) -> tuple[str, str]:
    bounds = intent["time_range"]
    return bounds["start"], bounds["end"]


def _measurement(connection: sqlite3.Connection, signal: str, start: str, end: str) -> dict[str, Any] | None:
    rows = execute(connection, "signal_window", (signal, start, end))
    if not rows or rows[0]["buckets"] == 0:
        return None
    return rows[0]


def _iso_day_bounds(day: str) -> tuple[str, str]:
    start = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
    return start.strftime("%Y-%m-%dT%H:%M:%SZ"), (start + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _response(answer: str, start: str, end: str, evidence: list[dict], confidence_value: str, path: str, timings: dict[str, float]) -> dict[str, Any]:
    return {"answer": answer, "time_range": {"start": start, "end": end}, "evidence": evidence,
            "confidence": confidence_value, "latency_ms": round(sum(timings.values()), 2),
            "latency_breakdown": {key: round(value, 2) for key, value in timings.items()}, "path": path}


def answer_query(query: str, db_path: Path = DB_PATH, now: datetime | None = None) -> dict[str, Any]:
    timings: dict[str, float] = {}
    mark = time.perf_counter()
    intent, path = parse_intent(query, MODEL, now)
    timings["intent"] = (time.perf_counter() - mark) * 1000
    start, end = _window(intent)
    if intent["intent"] == "unknown":
        return _response("I can answer questions about range, efficiency, ADAS events, warnings, and sensor anomalies. Try: 'Why has my driving range reduced over the last two weeks?', 'Show all ADAS disengagement events from yesterday', or 'What happened before the battery overheating warning?'", start, end, [], "Low", path, timings)
    mark = time.perf_counter()
    connection = open_database(db_path)
    timings["database_open"] = (time.perf_counter() - mark) * 1000
    try:
        mark = time.perf_counter()
        kind = intent["intent"]
        evidence: list[dict[str, Any]] = []
        answer = "No data for that period."
        confidence_value = "Low"
        if kind == "range_analysis":
            window_start = datetime.fromisoformat(start.replace("Z", "+00:00"))
            window_end = datetime.fromisoformat(end.replace("Z", "+00:00"))
            duration = window_end - window_start
            old_start = (window_start - duration).strftime("%Y-%m-%dT%H:%M:%SZ")
            old_end, new_start = start, start
            old = _measurement(connection, "estimated_range_km", old_start, old_end)
            recent = _measurement(connection, "estimated_range_km", new_start, end)
            before = {signal: _measurement(connection, signal, old_start, old_end) for signal in ("ambient_temp", "hvac_power", "tyre_pressure", "speed")}
            current = {signal: _measurement(connection, signal, new_start, end) for signal in before}
            if old and recent:
                drop = (old["avg_value"] - recent["avg_value"]) / old["avg_value"] * 100 if old["avg_value"] else 0
                cause = rank_range_causes({k: v["avg_value"] for k, v in before.items() if v}, {k: v["avg_value"] for k, v in current.items() if v})
                answer = f"Average estimated range fell {drop:.1f}% ({old['avg_value']:.1f} to {recent['avg_value']:.1f} km). Main measured contributors: " + (", ".join(item["cause"] for item in cause["causes"][:2]) if cause["causes"] else "insufficient evidence") + "."
                evidence = [{"metric": "estimated_range_km", "baseline": round(old["avg_value"], 2), "recent": round(recent["avg_value"], 2), "unit": "km", "change_percent": round(-drop, 2), "baseline_period": {"start": old_start, "end": old_end}, "recent_period": {"start": new_start, "end": end}}]
                evidence += [{"metric": key, "baseline": round(before[key]["avg_value"], 2), "recent": round(current[key]["avg_value"], 2), "unit": before[key]["unit"]} for key in before if before[key] and current[key]]
                confidence_value = cause["confidence"]
        elif kind == "adas_disengagements":
            events = execute(connection, "events_window", ("adas_disengagement", start, end))
            if events:
                answer = f"Found {len(events)} ADAS disengagement events."
                evidence = [{"timestamp": row["ts"], "type": row["type"], "severity": row["severity"], "context": json.loads(row["context_json"])} for row in events]
                confidence_value = "High"
        elif kind == "pre_event_timeline":
            events = execute(connection, "events_window", ("battery_overheating_warning", start, end))
            if not events:
                events = execute(connection, "events_window", ("battery_overheating_warning", "0000", "9999"))[-1:]
            if events:
                event = events[0]
                event_time = datetime.fromisoformat(event["ts"].replace("Z", "+00:00"))
                before_time = (event_time - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
                after_time = (event_time + timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
                timeline = execute(connection, "timeline_signal", ("battery_temp", before_time, after_time))
                evidence = [{"timestamp": row["ts_start"], "metric": "battery_temp", "value": row["avg_value"], "unit": row["unit"]} for row in timeline]
                evidence.append({"timestamp": event["ts"], "type": event["type"], "severity": event["severity"], "context": json.loads(event["context_json"])})
                if timeline:
                    answer = f"Battery temperature rose from {timeline[0]['avg_value']:.1f} to {timeline[-1]['avg_value']:.1f} degC in the 10 minutes before the warning at {event['ts']}."
                    confidence_value = "High"
        elif kind == "city_vs_highway_compare":
            groups = {mode: execute(connection, "mode_consumption", (mode, start, end))[0] for mode in ("city", "highway")}
            if all(groups[mode]["value"] is not None for mode in groups):
                city_avg, highway_avg = groups["city"]["value"], groups["highway"]["value"]
                answer = f"Average energy consumption was {city_avg:.1f} Wh/km in city driving and {highway_avg:.1f} Wh/km on highways."
                evidence = [{"mode": mode, "average": round(groups[mode]["value"], 2), "buckets": groups[mode]["buckets"], "unit": "Wh/km"} for mode in groups]
                confidence_value = "High" if min(groups[mode]["buckets"] for mode in groups) >= 20 else "Med"
        elif kind == "efficiency_drop_changepoint":
            rows = execute(connection, "daily_signal", ("energy_consumption_wh_per_km", start, end))
            point = max_delta_changepoint(rows)
            if point:
                answer = f"The largest measured efficiency change was near {point['date']}: average consumption shifted from {point['before']:.1f} to {point['after']:.1f} Wh/km ({point['change_percent']:+.1f}%)."
                evidence = [{"date": point["date"], "before": round(point["before"], 2), "after": round(point["after"], 2), "change_percent": round(point["change_percent"], 2), "unit": "Wh/km"}]
                confidence_value = confidence(len(rows))
        elif kind == "sensor_anomaly":
            rows = execute(connection, "timeline_signal", ("tyre_pressure", start, end))
            anomalies = zscore_anomalies([{"timestamp": row["ts_start"], "avg_value": row["avg_value"], "unit": row["unit"]} for row in rows])
            anomalies = [row for row in anomalies if row["avg_value"] < 1.8 or row["avg_value"] > 3.5]
            if anomalies:
                answer = f"Detected {len(anomalies)} tyre-pressure sensor anomaly; the largest reading was {max(anomalies, key=lambda row: abs(row['z_score']))['avg_value']:.2f} bar."
                evidence = [{"timestamp": row["timestamp"], "value": row["avg_value"], "unit": row["unit"], "z_score": round(row["z_score"], 2)} for row in anomalies]
                confidence_value = "High"
        timings["query_analytics"] = (time.perf_counter() - mark) * 1000
    finally:
        connection.close()
    return _response(answer, start, end, evidence, confidence_value, path, timings)


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while line := await reader.readline():
            try:
                request = json.loads(line)
                response = await asyncio.to_thread(answer_query, str(request.get("query", "")))
            except Exception as error:
                response = {"answer": "Engine unavailable", "error": str(error), "time_range": {}, "evidence": [], "confidence": "Low", "latency_ms": 0, "path": "fast"}
            writer.write((json.dumps(response, separators=(",", ":")) + "\n").encode())
            await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()


async def serve() -> None:
    SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        try:
            connection = open_database()
            ready = connection.execute("SELECT COUNT(*) FROM aggregates").fetchone()[0] > 0
            connection.close()
            if ready:
                break
        except sqlite3.Error:
            pass
        await asyncio.sleep(1)
    else:
        raise RuntimeError(f"Vehicle database was not ready at {DB_PATH}")
    try:
        SOCKET_PATH.unlink()
    except FileNotFoundError:
        pass
    server = await asyncio.start_unix_server(handle_client, path=str(SOCKET_PATH))
    os.chmod(SOCKET_PATH, 0o660)
    print(f"Engine ready on Unix socket {SOCKET_PATH}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(serve())