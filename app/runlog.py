"""Persistent record of which invoices have already been signed/sent.

Exists so that re-running a batch (after a crash, a cancelled run, or just
running the tool twice by mistake) never re-signs or re-emails an invoice
that already went out.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class LogEntry:
    filename: str
    customer_id: str | None
    email: str | None
    signed_at: str | None
    sent_at: str | None
    error: str | None


class RunLog:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: the batch runs on a background QThread
        # while the GUI thread stays idle, so this connection is only ever
        # used by one thread at a time, just not always the same one.
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS invoice_log (
                filename TEXT PRIMARY KEY,
                customer_id TEXT,
                email TEXT,
                signed_at TEXT,
                sent_at TEXT,
                error TEXT
            )
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def get(self, filename: str) -> LogEntry | None:
        row = self._conn.execute(
            "SELECT * FROM invoice_log WHERE filename = ?", (filename,)
        ).fetchone()
        return LogEntry(**dict(row)) if row else None

    def is_sent(self, filename: str) -> bool:
        entry = self.get(filename)
        return entry is not None and entry.sent_at is not None

    def mark_signed(self, filename: str, customer_id: str, email: str) -> None:
        self._conn.execute(
            """
            INSERT INTO invoice_log (filename, customer_id, email, signed_at, error)
            VALUES (?, ?, ?, ?, NULL)
            ON CONFLICT(filename) DO UPDATE SET
                customer_id = excluded.customer_id,
                email = excluded.email,
                signed_at = excluded.signed_at,
                error = NULL
            """,
            (filename, customer_id, email, self._now()),
        )
        self._conn.commit()

    def mark_sent(self, filename: str) -> None:
        self._conn.execute(
            "UPDATE invoice_log SET sent_at = ?, error = NULL WHERE filename = ?",
            (self._now(), filename),
        )
        self._conn.commit()

    def mark_error(self, filename: str, error: str) -> None:
        self._conn.execute(
            """
            INSERT INTO invoice_log (filename, error) VALUES (?, ?)
            ON CONFLICT(filename) DO UPDATE SET error = excluded.error
            """,
            (filename, error),
        )
        self._conn.commit()
