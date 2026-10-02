"""SQLite persistence: quotes (audit trail), live factory state, accounts and usage.

SQLite in WAL mode comfortably handles the write volume of an instant-quote
portal; swap for PostgreSQL behind the same functions if you scale out
horizontally.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from dataclasses import dataclass
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
CREATE TABLE IF NOT EXISTS accounts (
    id                     TEXT PRIMARY KEY,
    email                  TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash          TEXT NOT NULL,
    company                TEXT,
    plan                   TEXT NOT NULL DEFAULT 'free',
    stripe_customer_id     TEXT,
    stripe_subscription_id TEXT,
    api_key_hash           TEXT UNIQUE,
    created_at             TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL
);
-- One row per (account or guest IP hash, calendar month): the plan quota counter.
CREATE TABLE IF NOT EXISTS usage (
    subject TEXT NOT NULL,
    period  TEXT NOT NULL,
    quotes  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (subject, period)
);
"""


@dataclass(frozen=True)
class Account:
    id: str
    email: str
    company: str | None
    plan: str
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    has_api_key: bool
    created_at: str


_ACCOUNT_COLS = (
    "id, email, company, plan, stripe_customer_id, stripe_subscription_id, api_key_hash IS NOT NULL, created_at"
)


def _period(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).strftime("%Y-%m")


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
        self._migrate()
        self._lock = threading.Lock()

    def _migrate(self) -> None:
        # v1.0 databases predate accounts: add the owner column in place.
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(quotes)")}
        if "account_id" not in cols:
            self._conn.execute("ALTER TABLE quotes ADD COLUMN account_id TEXT")
        self._conn.execute("CREATE INDEX IF NOT EXISTS quotes_account ON quotes(account_id, created_at)")

    def close(self) -> None:
        self._conn.close()

    # ---------------------------------------------------------------- quotes
    def save_quote(
        self,
        response: QuoteResponse,
        file_sha256: str | None,
        preview_stl: bytes | None,
        account_id: str | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO quotes (id, created_at, file_sha256, engine, feasibility, net_eur, response, preview_stl,"
                " account_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    response.quote.quote_id,
                    response.commercial.created_at,
                    file_sha256,
                    response.analysis.engine,
                    response.quote.feasibility,
                    response.quote.cost_breakdown.net_total_eur,
                    response.model_dump_json(),
                    preview_stl,
                    account_id,
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

    def list_quotes(self, account_id: str, limit: int = 50) -> list[dict]:
        """Compact rows for the account's quote history, newest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, created_at, feasibility, net_eur,"
                " json_extract(response, '$.commercial.file_name'),"
                " json_extract(response, '$.quote.selected_process'),"
                " json_extract(response, '$.commercial.quantity')"
                " FROM quotes WHERE account_id = ? ORDER BY created_at DESC LIMIT ?",
                (account_id, limit),
            ).fetchall()
        keys = ("quote_id", "created_at", "feasibility", "net_total_eur", "file_name", "selected_process", "quantity")
        return [dict(zip(keys, row, strict=True)) for row in rows]

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

    # -------------------------------------------------------------- accounts
    def _account(self, where: str, value: str) -> Account | None:
        with self._lock:
            row = self._conn.execute(f"SELECT {_ACCOUNT_COLS} FROM accounts WHERE {where} = ?", (value,)).fetchone()  # noqa: S608 - where is a constant
        return Account(*row[:6], bool(row[6]), row[7]) if row else None

    def create_account(self, account_id: str, email: str, password_hash: str, company: str | None) -> Account | None:
        """Returns None if the e-mail address is already registered."""
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT INTO accounts (id, email, password_hash, company, created_at) VALUES (?, ?, ?, ?, ?)",
                    (account_id, email, password_hash, company, datetime.now(UTC).isoformat(timespec="seconds")),
                )
        except sqlite3.IntegrityError:
            return None
        return self._account("id", account_id)

    def get_account(self, account_id: str) -> Account | None:
        return self._account("id", account_id)

    def password_hash_for(self, email: str) -> tuple[str, str] | None:
        with self._lock:
            row = self._conn.execute("SELECT id, password_hash FROM accounts WHERE email = ?", (email,)).fetchone()
        return (row[0], row[1]) if row else None

    def account_by_api_key(self, key_hash: str) -> Account | None:
        return self._account("api_key_hash", key_hash)

    def account_by_stripe_customer(self, customer_id: str) -> Account | None:
        return self._account("stripe_customer_id", customer_id)

    def update_account(self, account_id: str, **fields: str | None) -> None:
        allowed = {"plan", "stripe_customer_id", "stripe_subscription_id", "api_key_hash", "company"}
        if not fields or set(fields) - allowed:
            raise ValueError(f"cannot update {sorted(set(fields) - allowed)}")
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self._lock:
            self._conn.execute(f"UPDATE accounts SET {sets} WHERE id = ?", (*fields.values(), account_id))  # noqa: S608 - keys whitelisted

    # -------------------------------------------------------------- sessions
    def create_session(self, token_hash: str, account_id: str) -> None:
        expires = datetime.now(UTC) + timedelta(days=self._settings.session_ttl_days)
        with self._lock:
            self._conn.execute(
                "INSERT INTO sessions (token_hash, account_id, expires_at) VALUES (?, ?, ?)",
                (token_hash, account_id, expires.isoformat()),
            )

    def account_for_session(self, token_hash: str) -> Account | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT account_id FROM sessions WHERE token_hash = ? AND expires_at > ?",
                (token_hash, datetime.now(UTC).isoformat()),
            ).fetchone()
        return self.get_account(row[0]) if row else None

    def delete_session(self, token_hash: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))

    # ----------------------------------------------------------------- usage
    def quotes_used(self, subject: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT quotes FROM usage WHERE subject = ? AND period = ?", (subject, _period())
            ).fetchone()
        return row[0] if row else 0

    def consume_quote(self, subject: str, limit: int | None) -> bool:
        """Atomically count one quote against ``subject``'s monthly quota; False if exhausted."""
        period = _period()
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT quotes FROM usage WHERE subject = ? AND period = ?", (subject, period)
                ).fetchone()
                used = row[0] if row else 0
                if limit is not None and used >= limit:
                    self._conn.execute("ROLLBACK")
                    return False
                self._conn.execute(
                    "INSERT INTO usage (subject, period, quotes) VALUES (?, ?, 1)"
                    " ON CONFLICT(subject, period) DO UPDATE SET quotes = quotes + 1",
                    (subject, period),
                )
                self._conn.execute("COMMIT")
                return True
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def refund_quote(self, subject: str) -> None:
        """Give a quota unit back when the quote could not be produced (bad file etc.)."""
        with self._lock:
            self._conn.execute(
                "UPDATE usage SET quotes = MAX(quotes - 1, 0) WHERE subject = ? AND period = ?", (subject, _period())
            )
