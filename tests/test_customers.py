import csv
import tempfile
from pathlib import Path

import pytest

from app.customers import CustomerStore


@pytest.fixture
def store(tmp_path: Path) -> CustomerStore:
    s = CustomerStore(tmp_path / "customers.db")
    yield s
    s.close()


def write_csv(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["ID", "Email", "Name"])
        writer.writeheader()
        writer.writerows(rows)


def test_upsert_and_get(store: CustomerStore):
    store.upsert("0004", "client@example.com", "Client DOO")
    c = store.get("0004")
    assert c is not None
    assert c.email == "client@example.com"
    assert c.name == "Client DOO"


def test_get_missing_returns_none(store: CustomerStore):
    assert store.get("nope") is None


def test_delete(store: CustomerStore):
    store.upsert("0004", "a@x.com")
    store.delete("0004")
    assert store.get("0004") is None


def test_import_new_rows(store: CustomerStore, tmp_path: Path):
    csv_path = tmp_path / "in.csv"
    write_csv(csv_path, [{"ID": "0001", "Email": "a@x.com", "Name": "A"}])
    rows = CustomerStore.read_csv_rows(csv_path, "ID", "Email", "Name")
    preview = store.build_preview(rows)
    assert len(preview.new) == 1
    assert len(preview.unchanged) == 0
    assert len(preview.conflicts) == 0

    added, updated = store.apply_import(preview)
    assert added == 1
    assert updated == 0
    assert store.get("0001").email == "a@x.com"


def test_import_unchanged_row_not_flagged_as_conflict(store: CustomerStore, tmp_path: Path):
    store.upsert("0001", "a@x.com", "A")
    csv_path = tmp_path / "in.csv"
    write_csv(csv_path, [{"ID": "0001", "Email": "a@x.com", "Name": "A"}])
    rows = CustomerStore.read_csv_rows(csv_path, "ID", "Email", "Name")
    preview = store.build_preview(rows)
    assert len(preview.new) == 0
    assert len(preview.unchanged) == 1
    assert len(preview.conflicts) == 0


def test_import_conflict_detected_on_different_email(store: CustomerStore, tmp_path: Path):
    store.upsert("0001", "old@x.com", "A")
    csv_path = tmp_path / "in.csv"
    write_csv(csv_path, [{"ID": "0001", "Email": "new@x.com", "Name": "A"}])
    rows = CustomerStore.read_csv_rows(csv_path, "ID", "Email", "Name")
    preview = store.build_preview(rows)
    assert len(preview.conflicts) == 1
    row, existing = preview.conflicts[0]
    assert row.email == "new@x.com"
    assert existing.email == "old@x.com"


def test_conflict_not_applied_unless_resolved(store: CustomerStore, tmp_path: Path):
    store.upsert("0001", "old@x.com", "A")
    csv_path = tmp_path / "in.csv"
    write_csv(csv_path, [{"ID": "0001", "Email": "new@x.com", "Name": "A"}])
    rows = CustomerStore.read_csv_rows(csv_path, "ID", "Email", "Name")
    preview = store.build_preview(rows)

    added, updated = store.apply_import(preview)  # no resolutions passed
    assert added == 0
    assert updated == 0
    assert store.get("0001").email == "old@x.com"  # untouched


def test_conflict_applied_when_resolved_to_use_new(store: CustomerStore, tmp_path: Path):
    store.upsert("0001", "old@x.com", "A")
    csv_path = tmp_path / "in.csv"
    write_csv(csv_path, [{"ID": "0001", "Email": "new@x.com", "Name": "A"}])
    rows = CustomerStore.read_csv_rows(csv_path, "ID", "Email", "Name")
    preview = store.build_preview(rows)

    added, updated = store.apply_import(preview, conflict_resolutions={"0001": True})
    assert updated == 1
    assert store.get("0001").email == "new@x.com"


def test_import_ignores_rows_with_blank_id_or_email(store: CustomerStore, tmp_path: Path):
    csv_path = tmp_path / "in.csv"
    write_csv(
        csv_path,
        [
            {"ID": "", "Email": "a@x.com", "Name": "A"},
            {"ID": "0002", "Email": "", "Name": "B"},
            {"ID": "0003", "Email": "c@x.com", "Name": "C"},
        ],
    )
    rows = CustomerStore.read_csv_rows(csv_path, "ID", "Email", "Name")
    assert len(rows) == 1
    assert rows[0].id == "0003"
