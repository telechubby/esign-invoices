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

    signing_mode: str = "pkcs11"  # "pkcs11" (real token) or "pkcs12" (test certificate)

    pkcs11_driver_path: str = ""
    pkcs11_slot: str = ""  # blank = auto-detect

    pkcs12_path: str = ""  # only used when signing_mode == "pkcs12", for trying the
    # app out before the real token is available - never use for real invoices.

    gmail_address: str = ""
    email_subject: str = "Фактура {invoice_id}"
    email_body: str = (
        "Почитувани {customer_name},\n\n"
        "Во прилог ја доставуваме потпишаната фактура за {month}/{year}.\n\n"
        "Со почит."
    )

    signature_reason: str = ""
    signature_location: str = ""

    # Visible signature stamp position/size on the first page, as % of
    # page width/height (y measured from the bottom, PDF convention).
    # Defaults are a wide box in the bottom-left - adjust in Settings to
    # fit your actual invoice layout. The box needs to stay reasonably
    # wide for the stamp text to fit without being cut off.
    sig_x_pct: float = 5.0
    sig_y_pct: float = 3.0
    sig_width_pct: float = 60.0
    sig_height_pct: float = 14.0

    # Stamp appearance: the text template (supports %(signer)s and %(ts)s)
    # and an optional background watermark image shown faintly behind it.
    sig_stamp_text: str = "%(signer)s\nДигитално потпишано\n%(ts)s"
    sig_background_image: str = ""
    sig_background_opacity: float = 0.35

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


def get_pkcs12_password(pkcs12_path: str) -> str | None:
    if not pkcs12_path:
        return None
    return keyring.get_password(KEYRING_SERVICE, f"pkcs12:{pkcs12_path}")


def set_pkcs12_password(pkcs12_path: str, password: str) -> None:
    keyring.set_password(KEYRING_SERVICE, f"pkcs12:{pkcs12_path}", password)
