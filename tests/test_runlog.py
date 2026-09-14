from pathlib import Path

import pytest

from app.runlog import RunLog


@pytest.fixture
def log(tmp_path: Path) -> RunLog:
    l = RunLog(tmp_path / "runlog.db")
    yield l
    l.close()


def test_not_sent_by_default(log: RunLog):
    assert log.is_sent("Inv_08_0004_01_2026.pdf") is False


def test_mark_signed_then_sent(log: RunLog):
    fn = "Inv_08_0004_01_2026.pdf"
    log.mark_signed(fn, "0004", "client@example.com")
    assert log.is_sent(fn) is False  # signed but not yet sent
    log.mark_sent(fn)
    assert log.is_sent(fn) is True


def test_mark_error_does_not_mark_sent(log: RunLog):
    fn = "Inv_08_0004_01_2026.pdf"
    log.mark_signed(fn, "0004", "client@example.com")
    log.mark_error(fn, "SMTP down")
    assert log.is_sent(fn) is False
    entry = log.get(fn)
    assert entry.error == "SMTP down"
