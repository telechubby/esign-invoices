"""Resolves where the app's data lives: always next to the program itself
(the folder containing the .exe when frozen by PyInstaller, or the project
root when running from source) - not a hidden per-user AppData folder -
so the customer list, settings, and logs are easy to find and back up.
"""
from __future__ import annotations

import sys
from pathlib import Path


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    d = app_dir() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def customers_db_path() -> Path:
    return data_dir() / "customers.db"


def runlog_db_path() -> Path:
    return data_dir() / "runlog.db"


def settings_path() -> Path:
    return data_dir() / "settings.json"
