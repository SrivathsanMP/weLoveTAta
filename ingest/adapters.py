"""Adapter contracts for platform-specific sources writing the common schema."""

from __future__ import annotations

import sqlite3
from typing import Any


class CommonSchemaWriter:
    """Small shared write boundary; adapt decoded platform samples here."""

    def __init__(self, connection: sqlite3.Connection, source: str) -> None:
        self.connection = connection
        self.source = source

    def write_signal(self, ts_mono: int, ts_utc: str, signal_id: str, value: Any, unit: str, quality: str = "good") -> None:
        self.connection.execute(
            "INSERT INTO signals VALUES(?,?,?,?,?,?,?)",
            (ts_mono, ts_utc, self.source, signal_id, value, unit, quality),
        )

    def write_event(self, ts_utc: str, event_type: str, severity: str, context_json: str) -> None:
        self.connection.execute(
            "INSERT INTO events(ts,type,severity,context_json) VALUES(?,?,?,?)",
            (ts_utc, event_type, severity, context_json),
        )


class SomeIpAdapter(CommonSchemaWriter):
    """TODO: map vsomeip service/event IDs and payload units to canonical signals."""


class AndroidVhalAdapter(CommonSchemaWriter):
    """TODO: map Android VHAL property IDs and timestamps to canonical signals."""


class QnxSlog2Adapter(CommonSchemaWriter):
    """TODO: map QNX slog2 records and diagnostic text to canonical events."""