"""All SQL used by the assistant is defined here and parameterized."""

from __future__ import annotations

from typing import Any

QUERIES: dict[str, str] = {
    "daily_signal": "SELECT substr(ts_start,1,10) AS day, AVG(avg_value) AS value, MAX(unit) AS unit FROM aggregates WHERE grain='1h' AND signal_id=? AND ts_start>=? AND ts_start<? GROUP BY day ORDER BY day",
    "signal_window": "SELECT AVG(avg_value) AS avg_value, MIN(min_value) AS min_value, MAX(max_value) AS max_value, MAX(unit) AS unit, COUNT(*) AS buckets FROM aggregates WHERE grain='1m' AND signal_id=? AND ts_start>=? AND ts_start<?",
    "events_window": "SELECT ts,type,severity,context_json FROM events WHERE type=? AND ts>=? AND ts<? ORDER BY ts",
    "events_near": "SELECT ts,type,severity,context_json FROM events WHERE ts>=? AND ts<? ORDER BY ts",
    "timeline_signal": "SELECT ts_start,avg_value,min_value,max_value,unit FROM aggregates WHERE grain='1m' AND signal_id=? AND ts_start>=? AND ts_start<? ORDER BY ts_start",
    "signal_by_mode": "SELECT a.signal_id,a.ts_start,a.avg_value,a.value_text FROM aggregates a WHERE a.grain='1h' AND a.signal_id=? AND a.ts_start>=? AND a.ts_start<? ORDER BY a.ts_start",
    "daily_modes": "SELECT substr(ts_start,1,10) AS day, value_text, COUNT(*) AS n FROM aggregates WHERE grain='1h' AND signal_id='drive_mode_label' AND ts_start>=? AND ts_start<? GROUP BY day,value_text",
    "mode_consumption": "SELECT AVG(consumption.avg_value) AS value, COUNT(*) AS buckets FROM aggregates mode JOIN aggregates consumption ON consumption.ts_start=mode.ts_start AND consumption.grain=mode.grain WHERE mode.grain='1h' AND mode.signal_id='drive_mode_label' AND mode.value_text=? AND consumption.signal_id='energy_consumption_wh_per_km' AND mode.ts_start>=? AND mode.ts_start<?",
    "event_search": "SELECT e.ts,e.type,e.severity,e.context_json FROM event_text f JOIN events e ON e.id=CAST(f.event_id AS INTEGER) WHERE event_text MATCH ? AND e.ts>=? AND e.ts<? ORDER BY e.ts",
}


def execute(connection: Any, key: str, params: tuple) -> list[dict]:
    if key not in QUERIES:
        raise ValueError("SQL template is not allow-listed")
    cursor = connection.execute(QUERIES[key], params)
    return [dict(row) for row in cursor.fetchall()]