"""Local, editable customer (company ID -> email) store, backed by SQLite.

The database file lives next to the app so it survives updates and is
independent of whatever external DB the CSV export originally came from.
"""
from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class Customer:
    id: str
    email: str
    name: str = ""
    updated_at: str = ""


@dataclass
class ImportRow:
    id: str
    email: str
    name: str = ""


@dataclass
class ImportPreview:
    new: list[ImportRow]
    unchanged: list[ImportRow]
    conflicts: list[tuple[ImportRow, Customer]]  # (incoming row, existing customer)


class CustomerStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS customers (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # -- basic CRUD -----------------------------------------------------

    def list_all(self) -> list[Customer]:
        rows = self._conn.execute(
            "SELECT id, email, name, updated_at FROM customers ORDER BY id"
        ).fetchall()
        return [Customer(**dict(r)) for r in rows]

    def get(self, customer_id: str) -> Customer | None:
        row = self._conn.execute(
            "SELECT id, email, name, updated_at FROM customers WHERE id = ?",
            (customer_id,),
        ).fetchone()
        return Customer(**dict(row)) if row else None

    def upsert(self, customer_id: str, email: str, name: str = "") -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._conn.execute(
            """
            INSERT INTO customers (id, email, name, updated_at) VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET email = excluded.email,
                                           name = excluded.name,
                                           updated_at = excluded.updated_at
            """,
            (customer_id, email, name, now),
        )
        self._conn.commit()

    def delete(self, customer_id: str) -> None:
        self._conn.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
        self._conn.commit()

    # -- CSV import with diff/conflict detection -------------------------

    @staticmethod
    def read_csv_rows(
        csv_path: Path,
        id_column: str,
        email_column: str,
        name_column: str | None = None,
        encoding: str = "utf-8-sig",
    ) -> list[ImportRow]:
        rows: list[ImportRow] = []
        with open(csv_path, newline="", encoding=encoding) as f:
            reader = csv.DictReader(f)
            for raw in reader:
                cid = (raw.get(id_column) or "").strip()
                email = (raw.get(email_column) or "").strip()
                name = (raw.get(name_column) or "").strip() if name_column else ""
                if not cid or not email:
                    continue
                rows.append(ImportRow(id=cid, email=email, name=name))
        return rows

    def build_preview(self, rows: list[ImportRow]) -> ImportPreview:
        new: list[ImportRow] = []
        unchanged: list[ImportRow] = []
        conflicts: list[tuple[ImportRow, Customer]] = []

        for row in rows:
            existing = self.get(row.id)
            if existing is None:
                new.append(row)
            elif existing.email.strip().lower() == row.email.strip().lower():
                unchanged.append(row)
            else:
                conflicts.append((row, existing))

        return ImportPreview(new=new, unchanged=unchanged, conflicts=conflicts)

    def apply_import(
        self,
        preview: ImportPreview,
        conflict_resolutions: dict[str, bool] | None = None,
    ) -> tuple[int, int]:
        """Apply a previously built preview.

        conflict_resolutions maps customer id -> True (use new email) / False
        (keep existing). Any conflict id missing from the dict is skipped
        (kept as-is).
        """
        conflict_resolutions = conflict_resolutions or {}
        added = 0
        updated = 0

        for row in preview.new:
            self.upsert(row.id, row.email, row.name)
            added += 1

        for row, _existing in preview.conflicts:
            use_new = conflict_resolutions.get(row.id)
            if use_new:
                self.upsert(row.id, row.email, row.name)
                updated += 1

        return added, updated
