"""Persisted app settings (paths, filename pattern, token, email template).

The Gmail app password is deliberately NOT stored in settings.json (plain
text on disk); it goes through `keyring`, which uses the OS credential
store (Windows Credential Manager / macOS Keychain). The PKCS#11 PIN is
never persisted at all - it is entered once per run and kept in memory only.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import keyring

from app.paths import app_dir, settings_path

KEYRING_SERVICE = "esign-invoices"


@dataclass
class AppConfig:
    unsigned_dir: str = str(app_dir() / "invoices" / "unsigned")
    signed_dir: str = str(app_dir() / "invoices" / "signed")

    filename_separator: str = "_"
    filename_id_position: int = 3  # 1-based

    pkcs11_driver_path: str = ""
    pkcs11_slot: str = ""  # blank = auto-detect

    gmail_address: str = ""
    email_subject: str = "Фактура {invoice_id}"
    email_body: str = (
        "Почитувани {customer_name},\n\n"
        "Во прилог ја доставуваме потпишаната фактура за {month}/{year}.\n\n"
        "Со почит."
    )

    signature_reason: str = ""
    signature_location: str = ""

    def to_json_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json_dict(cls, data: dict) -> "AppConfig":
        known = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        return cls(**known)


def load_config(path: Path | None = None) -> AppConfig:
    path = path or settings_path()
    if not path.exists():
        return AppConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return AppConfig()
    return AppConfig.from_json_dict(data)


def save_config(config: AppConfig, path: Path | None = None) -> None:
    path = path or settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(config.to_json_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_gmail_app_password(gmail_address: str) -> str | None:
    if not gmail_address:
        return None
    return keyring.get_password(KEYRING_SERVICE, gmail_address)


def set_gmail_app_password(gmail_address: str, app_password: str) -> None:
    keyring.set_password(KEYRING_SERVICE, gmail_address, app_password)
