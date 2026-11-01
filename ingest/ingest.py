"""Single-writer vehicle data ingestion for SIM and SocketCAN sources."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from simulator import SIGNALS, build_dataset, write_ground_truth

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DB_PATH = DATA_DIR / "vehicle.db"
SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS signals(
  ts_mono INTEGER NOT NULL, ts_utc TEXT NOT NULL, source TEXT NOT NULL,
  signal_id TEXT NOT NULL, value, unit TEXT NOT NULL, quality TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, type TEXT NOT NULL,
  severity TEXT NOT NULL, context_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS aggregates(
  ts_start TEXT NOT NULL, grain TEXT NOT NULL, signal_id TEXT NOT NULL,
  avg_value REAL, min_value REAL, max_value REAL, count INTEGER NOT NULL,
  value_text TEXT, unit TEXT NOT NULL,
  PRIMARY KEY(ts_start, grain, signal_id)
);
CREATE VIRTUAL TABLE IF NOT EXISTS event_text USING fts5(event_id UNINDEXED, text);
CREATE INDEX IF NOT EXISTS idx_signals_ts ON signals(ts_utc);
CREATE INDEX IF NOT EXISTS idx_signals_id_ts ON signals(signal_id, ts_utc);
CREATE INDEX IF NOT EXISTS idx_events_type_ts ON events(type, ts);
CREATE INDEX IF NOT EXISTS idx_aggregates_id_ts ON aggregates(signal_id, ts_start);
"""


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA temp_store=MEMORY")
    connection.executescript(SCHEMA)
    return connection


def _insert_events(connection: sqlite3.Connection, events: list[dict[str, Any]]) -> None:
    for event in events:
        cursor = connection.execute(
            "INSERT INTO events(ts,type,severity,context_json) VALUES(?,?,?,?)",
            (event["ts"].strftime("%Y-%m-%dT%H:%M:%SZ"), event["type"], event["severity"], json.dumps(event["context"])),
        )
        connection.execute(
            "INSERT INTO event_text(event_id,text) VALUES(?,?)",
            (cursor.lastrowid, event["context"].get("description", event["type"])),
        )


def _make_aggregates(connection: sqlite3.Connection) -> None:
    # SQLite computes rollups before raw rows are pruned, preserving long-range queries.
    for grain, bucket in (("1m", "%Y-%m-%dT%H:%M:00Z"), ("1h", "%Y-%m-%dT%H:00:00Z")):
        connection.execute(
            """INSERT OR REPLACE INTO aggregates(ts_start,grain,signal_id,avg_value,min_value,max_value,count,value_text,unit)
               SELECT strftime(?,ts_utc),?,signal_id,
                 AVG(CASE WHEN typeof(value) IN ('integer','real') THEN value END),
                 MIN(CASE WHEN typeof(value) IN ('integer','real') THEN value END),
                 MAX(CASE WHEN typeof(value) IN ('integer','real') THEN value END),COUNT(*),
                 MAX(CASE WHEN typeof(value)='text' THEN value END),MAX(unit)
               FROM signals GROUP BY strftime(?,ts_utc),signal_id""",
            (bucket, grain, bucket),
        )


def _retain(connection: sqlite3.Connection) -> None:
    now = datetime.now(timezone.utc)
    raw_cutoff = datetime.fromtimestamp(now.timestamp() - 7 * 86400, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    connection.execute("DELETE FROM signals WHERE ts_utc < ?", (raw_cutoff,))
    minute_cutoff = datetime.fromtimestamp(now.timestamp() - 90 * 86400, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    hour_cutoff = datetime.fromtimestamp(now.timestamp() - 365 * 86400, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    connection.execute("DELETE FROM aggregates WHERE grain='1m' AND ts_start < ?", (minute_cutoff,))
    connection.execute("DELETE FROM aggregates WHERE grain='1h' AND ts_start < ?", (hour_cutoff,))


def ingest_sim() -> None:
    signals, events, ground_truth = build_dataset(seed=int(os.environ.get("SIM_SEED", "20261101")))
    write_ground_truth(DATA_DIR / "ground_truth.json", ground_truth)
    connection = connect()
    # SIM is a reproducible fixture generator, so reseeding replaces its previous fixture.
    connection.executescript("DELETE FROM signals; DELETE FROM events; DELETE FROM event_text; DELETE FROM aggregates;")
    start = datetime.fromisoformat(ground_truth["generated_start"])
    batch: list[tuple] = []
    for record in signals:
        ts = record["ts"]
        batch.append((int((ts - start).total_seconds()), ts.strftime("%Y-%m-%dT%H:%M:%SZ"), "sim", record["signal_id"], record["value"], record["unit"], "good"))
        if len(batch) >= 10000:
            connection.executemany("INSERT INTO signals VALUES(?,?,?,?,?,?,?)", batch)
            batch.clear()
    if batch:
        connection.executemany("INSERT INTO signals VALUES(?,?,?,?,?,?,?)", batch)
    _insert_events(connection, events)
    _make_aggregates(connection)
    _retain(connection)
    connection.commit()
    connection.close()
    print(f"SIM ingest complete; {len(signals)} rows generated from {ground_truth['generated_start']}", flush=True)


def ingest_socketcan() -> None:
    """Decode the configured CAN interface continuously into the shared schema."""
    import can  # Optional runtime dependency, only imported in SOCKETCAN mode.
    import cantools

    interface = os.environ.get("CAN_IFACE", "can0")
    database = cantools.database.load_file(str(Path(__file__).with_name("signals.dbc")))
    connection = connect()
    bus = can.Bus(interface="socketcan", channel=interface)
    print(f"SocketCAN ingest listening on {interface}", flush=True)
    last_rollup = time.monotonic()
    try:
        for message in bus:
            try:
                decoded = database.decode_message(message.arbitration_id, message.data)
            except KeyError:
                continue
            stamp = datetime.now(timezone.utc)
            rows = []
            for name, value in decoded.items():
                rows.append((time.monotonic_ns() // 1_000_000_000, stamp.strftime("%Y-%m-%dT%H:%M:%SZ"), "socketcan", name.lower(), value, "raw", "good"))
            connection.executemany("INSERT INTO signals VALUES(?,?,?,?,?,?,?)", rows)
            connection.commit()
            if time.monotonic() - last_rollup >= 60:
                _make_aggregates(connection)
                _retain(connection)
                connection.commit()
                last_rollup = time.monotonic()
    finally:
        bus.shutdown()
        connection.close()


def main() -> None:
    os.umask(0o002)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.chmod(0o2775)
    mode = os.environ.get("INGEST_MODE", "SIM").upper()
    if mode == "SIM":
        ingest_sim()
    elif mode == "SOCKETCAN":
        ingest_socketcan()
    else:
        raise ValueError(f"Unsupported INGEST_MODE: {mode}")


if __name__ == "__main__":
    main()