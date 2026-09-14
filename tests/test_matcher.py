from pathlib import Path

import pytest

from app.customers import CustomerStore
from app.matcher import FilenamePattern, scan_invoices


@pytest.fixture
def store(tmp_path: Path) -> CustomerStore:
    s = CustomerStore(tmp_path / "customers.db")
    yield s
    s.close()


def test_extract_id_default_pattern():
    pattern = FilenamePattern(separator="_", id_position=3)
    assert pattern.extract_id("Inv_08_0004_01_2026.pdf") == "0004"


def test_extract_id_out_of_range_returns_none():
    pattern = FilenamePattern(separator="_", id_position=10)
    assert pattern.extract_id("Inv_08_0004_01_2026.pdf") is None


def test_extract_id_different_separator():
    pattern = FilenamePattern(separator="-", id_position=2)
    assert pattern.extract_id("Inv-0004-01-2026.pdf") == "0004"


def test_scan_invoices_matches_known_customer(store: CustomerStore, tmp_path: Path):
    store.upsert("0004", "client@example.com", "Client DOO")
    folder = tmp_path / "unsigned"
    folder.mkdir()
    (folder / "Inv_08_0004_01_2026.pdf").write_bytes(b"%PDF-1.4 fake")
    (folder / "Inv_08_9999_01_2026.pdf").write_bytes(b"%PDF-1.4 fake")

    pattern = FilenamePattern(separator="_", id_position=3)
    results = scan_invoices(folder, pattern, store)

    assert len(results) == 2
    by_id = {r.extracted_id: r for r in results}
    assert by_id["0004"].matched
    assert by_id["0004"].customer.email == "client@example.com"
    assert not by_id["9999"].matched


def test_scan_invoices_ignores_non_pdf(store: CustomerStore, tmp_path: Path):
    folder = tmp_path / "unsigned"
    folder.mkdir()
    (folder / "Inv_08_0004_01_2026.pdf").write_bytes(b"%PDF-1.4 fake")
    (folder / "notes.txt").write_text("hello")

    pattern = FilenamePattern(separator="_", id_position=3)
    results = scan_invoices(folder, pattern, store)
    assert len(results) == 1
