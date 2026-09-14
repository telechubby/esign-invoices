from pathlib import Path

from app.config import AppConfig, load_config, save_config


def test_load_missing_file_returns_defaults(tmp_path: Path):
    cfg = load_config(tmp_path / "does_not_exist.json")
    assert cfg.filename_separator == "_"
    assert cfg.filename_id_position == 3


def test_save_and_load_roundtrip(tmp_path: Path):
    path = tmp_path / "settings.json"
    cfg = AppConfig(
        unsigned_dir="/x/unsigned",
        signed_dir="/x/signed",
        filename_separator="-",
        filename_id_position=2,
        gmail_address="me@gmail.com",
    )
    save_config(cfg, path)

    loaded = load_config(path)
    assert loaded.unsigned_dir == "/x/unsigned"
    assert loaded.filename_separator == "-"
    assert loaded.filename_id_position == 2
    assert loaded.gmail_address == "me@gmail.com"


def test_load_corrupt_file_returns_defaults(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text("not valid json {{{", encoding="utf-8")
    cfg = load_config(path)
    assert cfg.filename_separator == "_"
