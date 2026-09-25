"""SQLite persistence for quotes (audit trail) and the live factory state.

SQLite in WAL mode comfortably handles the write volume of an instant-quote
portal; swap for PostgreSQL behind the same functions if you scale out
horizontally.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import UTC, datetime, timedelta

from app.catalog.machines import Process
from app.config import Settings
from app.schemas import FactoryState, FactoryStatus, MachineAvailability, QuoteResponse

_SCHEMA = """
CREATE TABLE IF NOT EXISTS quotes (
    id           TEXT PRIMARY KEY,
    created_at   TEXT NOT NULL,
    file_sha256  TEXT,
    engine       TEXT NOT NULL,
    feasibility  TEXT NOT NULL,
    net_eur      REAL NOT NULL,
    response     TEXT NOT NULL,
    preview_stl  BLOB
);
CREATE INDEX IF NOT EXISTS quotes_created_at ON quotes(created_at);
CREATE TABLE IF NOT EXISTS factory_state (
    id         INTEGER PRIMARY KEY CHECK (id = 1),
    updated_at TEXT NOT NULL,
    state      TEXT NOT NULL
);
"""


class Store:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        path = settings.database_path
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        self._lock = threading.Lock()

    def close(self) -> None:
        self._conn.close()

    # ---------------------------------------------------------------- quotes
    def save_quote(self, response: QuoteResponse, file_sha256: str | None, preview_stl: bytes | None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO quotes (id, created_at, file_sha256, engine, feasibility, net_eur, response, preview_stl)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    response.quote.quote_id,
                    response.commercial.created_at,
                    file_sha256,
                    response.analysis.engine,
                    response.quote.feasibility,
                    response.quote.cost_breakdown.net_total_eur,
                    response.model_dump_json(),
                    preview_stl,
                ),
            )

    def get_quote(self, quote_id: str) -> QuoteResponse | None:
        with self._lock:
            row = self._conn.execute("SELECT response FROM quotes WHERE id = ?", (quote_id,)).fetchone()
        return QuoteResponse.model_validate_json(row[0]) if row else None

    def get_preview(self, quote_id: str) -> bytes | None:
        with self._lock:
            row = self._conn.execute("SELECT preview_stl FROM quotes WHERE id = ?", (quote_id,)).fetchone()
        return row[0] if row and row[0] else None

    def purge_expired(self) -> int:
        cutoff = (datetime.now(UTC) - timedelta(days=self._settings.quote_retention_days)).isoformat()
        with self._lock:
            cur = self._conn.execute("DELETE FROM quotes WHERE created_at < ?", (cutoff,))
        return cur.rowcount

    # --------------------------------------------------------- factory state
    def _default_factory(self) -> FactoryState:
        s = self._settings
        return FactoryState(
            factory_status=FactoryStatus(
                machine_availability=MachineAvailability(), current_backlog_days=s.default_backlog_days
            ),
            energy_surcharge_percent=s.default_energy_surcharge_percent,
            target_margin_percent=s.default_target_margin_percent,
            machine_hourly_rates={
                Process.CNC_3_AXIS: s.rate_cnc_3_axis_eur_h,
                Process.CNC_5_AXIS: s.rate_cnc_5_axis_eur_h,
                Process.LATHE: s.rate_lathe_eur_h,
            },
        )

    def get_factory(self) -> FactoryState:
        with self._lock:
            row = self._conn.execute("SELECT state FROM factory_state WHERE id = 1").fetchone()
        return FactoryState.model_validate_json(row[0]) if row else self._default_factory()

    def put_factory(self, state: FactoryState) -> FactoryState:
        with self._lock:
            self._conn.execute(
                "INSERT INTO factory_state (id, updated_at, state) VALUES (1, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET updated_at = excluded.updated_at, state = excluded.state",
                (datetime.now(UTC).isoformat(), json.dumps(state.model_dump(mode="json"))),
            )
        return state
