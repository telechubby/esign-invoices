"""Extracts a company/customer ID from an invoice filename and matches it
against the local customer store.

The filename pattern is configurable (separator + 1-based token position)
since different exports may use different conventions, e.g.
"Inv_08_0004_01_2026.pdf" split on "_" with the ID at position 3 -> "0004".
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.customers import Customer, CustomerStore


@dataclass
class FilenamePattern:
    separator: str = "_"
    id_position: int = 3  # 1-based

    def extract_id(self, filename: str) -> str | None:
        stem = Path(filename).stem
        parts = stem.split(self.separator)
        idx = self.id_position - 1
        if idx < 0 or idx >= len(parts):
            return None
        token = parts[idx].strip()
        return token or None


@dataclass
class MatchResult:
    file_path: Path
    extracted_id: str | None
    customer: Customer | None

    @property
    def matched(self) -> bool:
        return self.customer is not None


def scan_invoices(
    folder: Path,
    pattern: FilenamePattern,
    store: CustomerStore,
    extension: str = ".pdf",
) -> list[MatchResult]:
    results: list[MatchResult] = []
    for path in sorted(Path(folder).glob(f"*{extension}")):
        if not path.is_file():
            continue
        cid = pattern.extract_id(path.name)
        customer = store.get(cid) if cid else None
        results.append(MatchResult(file_path=path, extracted_id=cid, customer=customer))
    return results
