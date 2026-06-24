"""SQLite olay deposu — Faz 1. DB'de görselin yalnızca anahtarı/uri'si durur, görselin
kendisi DEĞİL.

Thread-safe: tek bağlantı + lock (FastAPI async + arka plan worker'ları için yeterli).
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from interfaces import EventStore
from models import ChargingStatus, EventState, ViolationEvent

_SCHEMA = """
CREATE TABLE IF NOT EXISTS violations (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id       TEXT NOT NULL,
    detected_at      TEXT NOT NULL,
    telemetry_status TEXT NOT NULL,
    image_key        TEXT,
    image_uri        TEXT,
    source           TEXT NOT NULL DEFAULT 'manual',
    state            TEXT NOT NULL DEFAULT 'OPEN',
    forward_attempts INTEGER NOT NULL DEFAULT 0,
    forwarded_at     TEXT,
    note             TEXT DEFAULT '',
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_station_time ON violations(station_id, detected_at);
CREATE INDEX IF NOT EXISTS ix_state ON violations(state);
"""


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _dt(s: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(s) if s else None


class SqliteEventStore(EventStore):
    def __init__(self, db_path: Path) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def _row_to_event(self, r: sqlite3.Row) -> ViolationEvent:
        return ViolationEvent(
            id=r["id"],
            station_id=r["station_id"],
            detected_at=_dt(r["detected_at"]),
            telemetry_status=ChargingStatus.parse(r["telemetry_status"]),
            image_key=r["image_key"],
            image_uri=r["image_uri"],
            source=r["source"],
            state=EventState(r["state"]),
            forward_attempts=r["forward_attempts"],
            forwarded_at=_dt(r["forwarded_at"]),
            note=r["note"] or "",
            created_at=_dt(r["created_at"]),
        )

    def save(self, e: ViolationEvent) -> ViolationEvent:
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO violations
                   (station_id, detected_at, telemetry_status, image_key, image_uri,
                    source, state, forward_attempts, forwarded_at, note, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (e.station_id, _iso(e.detected_at), e.telemetry_status.value,
                 e.image_key, e.image_uri, e.source, e.state.value,
                 e.forward_attempts, _iso(e.forwarded_at), e.note, _iso(e.created_at)),
            )
            self._conn.commit()
            e.id = cur.lastrowid
            return e

    def get(self, event_id: int) -> Optional[ViolationEvent]:
        with self._lock:
            r = self._conn.execute("SELECT * FROM violations WHERE id=?",
                                   (event_id,)).fetchone()
        return self._row_to_event(r) if r else None

    def list(self, limit: int = 100) -> list[ViolationEvent]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM violations ORDER BY detected_at DESC LIMIT ?",
                (limit,)).fetchall()
        return [self._row_to_event(r) for r in rows]

    def last_violation_at(self, station_id: str) -> Optional[datetime]:
        with self._lock:
            r = self._conn.execute(
                "SELECT MAX(detected_at) AS m FROM violations WHERE station_id=?",
                (station_id,)).fetchone()
        return _dt(r["m"]) if r and r["m"] else None

    def list_pending_forward(self) -> list[ViolationEvent]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM violations WHERE state=? ORDER BY detected_at ASC",
                (EventState.OPEN.value,)).fetchall()
        return [self._row_to_event(r) for r in rows]

    def mark_forwarded(self, event_id: int, at: datetime) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE violations SET state=?, forwarded_at=? WHERE id=?",
                (EventState.FORWARDED.value, _iso(at), event_id))
            self._conn.commit()

    def bump_forward_attempt(self, event_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE violations SET forward_attempts=forward_attempts+1 WHERE id=?",
                (event_id,))
            self._conn.commit()

    def list_images_older_than(self, cutoff: datetime) -> list[ViolationEvent]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM violations WHERE image_key IS NOT NULL "
                "AND detected_at < ? AND state != ?",
                (_iso(cutoff), EventState.RETENTION_PURGED.value)).fetchall()
        return [self._row_to_event(r) for r in rows]

    def mark_image_purged(self, event_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE violations SET image_key=NULL, image_uri=NULL, state=?, "
                "note=note || ' [retention: gorsel silindi]' WHERE id=?",
                (EventState.RETENTION_PURGED.value, event_id))
            self._conn.commit()
