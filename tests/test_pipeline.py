from pathlib import Path
from unittest.mock import patch

import pytest

from app.customers import CustomerStore
from app.mailer import EmailTemplate, MailError, SmtpCredentials
from app.matcher import FilenamePattern
from app.pipeline import Status, build_jobs, send_jobs, sign_jobs
from app.runlog import RunLog
from app.signer import SigningError


@pytest.fixture
def env(tmp_path: Path):
    customers = CustomerStore(tmp_path / "customers.db")
    run_log = RunLog(tmp_path / "runlog.db")
    unsigned = tmp_path / "unsigned"
    signed = tmp_path / "signed"
    unsigned.mkdir()
    signed.mkdir()
    yield customers, run_log, unsigned, signed
    customers.close()
    run_log.close()


def make_template() -> EmailTemplate:
    return EmailTemplate(subject="Фактура {invoice_id}", body="Почитувани {customer_name},")


def make_creds() -> SmtpCredentials:
    return SmtpCredentials(address="me@gmail.com", app_password="x")


def build(customers, run_log, unsigned, signed):
    pattern = FilenamePattern(separator="_", id_position=3)
    return build_jobs(unsigned, signed, pattern, customers, run_log)


# -- build_jobs classification -------------------------------------------


def test_no_match_classified(env):
    customers, run_log, unsigned, signed = env
    (unsigned / "Inv_08_9999_01_2026.pdf").write_bytes(b"%PDF fake")
    jobs = build(customers, run_log, unsigned, signed)
    assert jobs[0].status == Status.NO_MATCH


def test_unprocessed_invoice_is_pending(env):
    customers, run_log, unsigned, signed = env
    customers.upsert("0004", "client@example.com", "Client")
    (unsigned / "Inv_08_0004_01_2026.pdf").write_bytes(b"%PDF fake")
    jobs = build(customers, run_log, unsigned, signed)
    assert jobs[0].status == Status.PENDING


def test_signed_but_unsent_invoice_is_signed_status(env):
    customers, run_log, unsigned, signed = env
    customers.upsert("0004", "client@example.com", "Client")
    fn = "Inv_08_0004_01_2026.pdf"
    (unsigned / fn).write_bytes(b"%PDF fake")
    (signed / fn).write_bytes(b"%PDF signed fake")
    run_log.mark_signed(fn, "0004", "client@example.com")

    jobs = build(customers, run_log, unsigned, signed)
    assert jobs[0].status == Status.SIGNED
    assert jobs[0].signed_path == signed / fn


def test_signed_record_but_missing_file_falls_back_to_pending(env):
    customers, run_log, unsigned, signed = env
    customers.upsert("0004", "client@example.com", "Client")
    fn = "Inv_08_0004_01_2026.pdf"
    (unsigned / fn).write_bytes(b"%PDF fake")
    run_log.mark_signed(fn, "0004", "client@example.com")  # no file actually written to signed/

    jobs = build(customers, run_log, unsigned, signed)
    assert jobs[0].status == Status.PENDING


def test_sent_invoice_is_already_sent(env):
    customers, run_log, unsigned, signed = env
    customers.upsert("0004", "client@example.com", "Client")
    fn = "Inv_08_0004_01_2026.pdf"
    (unsigned / fn).write_bytes(b"%PDF fake")
    (signed / fn).write_bytes(b"%PDF signed fake")
    run_log.mark_signed(fn, "0004", "client@example.com")
    run_log.mark_sent(fn)

    jobs = build(customers, run_log, unsigned, signed)
    assert jobs[0].status == Status.ALREADY_SENT


# -- sign_jobs -------------------------------------------------------------


def test_sign_jobs_only_processes_pending(env):
    customers, run_log, unsigned, signed = env
    customers.upsert("0001", "a@x.com", "A")
    customers.upsert("0002", "b@x.com", "B")
    (unsigned / "Inv_08_0001_01_2026.pdf").write_bytes(b"%PDF fake")
    (unsigned / "Inv_08_0002_01_2026.pdf").write_bytes(b"%PDF fake")
    (signed / "Inv_08_0002_01_2026.pdf").write_bytes(b"%PDF signed fake")
    run_log.mark_signed("Inv_08_0002_01_2026.pdf", "0002", "b@x.com")  # already signed

    jobs = build(customers, run_log, unsigned, signed)
    with patch("app.pipeline.sign_pdf") as mock_sign:
        report = sign_jobs(jobs, signer=object(), signed_dir=signed, run_log=run_log)
        mock_sign.assert_called_once()  # only the PENDING one

    assert report.signed_count == 2  # one freshly signed + one already SIGNED
    assert not any(j.status == Status.SEND_FAILED for j in jobs)


def test_sign_jobs_does_not_touch_email(env):
    customers, run_log, unsigned, signed = env
    customers.upsert("0004", "client@example.com", "Client")
    fn = "Inv_08_0004_01_2026.pdf"
    (unsigned / fn).write_bytes(b"%PDF fake")

    jobs = build(customers, run_log, unsigned, signed)
    with patch("app.pipeline.sign_pdf"), patch("app.pipeline.send_invoice_email") as mock_send:
        sign_jobs(jobs, signer=object(), signed_dir=signed, run_log=run_log)
        mock_send.assert_not_called()

    assert jobs[0].status == Status.SIGNED
    assert run_log.is_sent(fn) is False


def test_sign_failure_marks_sign_failed(env):
    customers, run_log, unsigned, signed = env
    customers.upsert("0004", "client@example.com", "Client")
    fn = "Inv_08_0004_01_2026.pdf"
    (unsigned / fn).write_bytes(b"%PDF fake")
    jobs = build(customers, run_log, unsigned, signed)

    with patch("app.pipeline.sign_pdf", side_effect=SigningError("token error")):
        report = sign_jobs(jobs, signer=object(), signed_dir=signed, run_log=run_log)

    assert jobs[0].status == Status.SIGN_FAILED
    assert report.failed_count == 1


def test_sign_cancel_stops_before_next_pending(env):
    customers, run_log, unsigned, signed = env
    customers.upsert("0001", "a@x.com", "A")
    customers.upsert("0002", "b@x.com", "B")
    (unsigned / "Inv_08_0001_01_2026.pdf").write_bytes(b"%PDF fake")
    (unsigned / "Inv_08_0002_01_2026.pdf").write_bytes(b"%PDF fake")
    jobs = build(customers, run_log, unsigned, signed)

    calls = {"n": 0}

    def fake_sign(*a, **k):
        calls["n"] += 1

    with patch("app.pipeline.sign_pdf", side_effect=fake_sign):
        sign_jobs(jobs, signer=object(), signed_dir=signed, run_log=run_log,
                   should_cancel=lambda: calls["n"] >= 1)

    statuses = [j.status for j in jobs]
    assert statuses.count(Status.SIGNED) == 1
    assert statuses.count(Status.PENDING) == 1


# -- send_jobs ---------------------------------------------------------------


def test_send_jobs_only_processes_signed(env):
    customers, run_log, unsigned, signed = env
    customers.upsert("0004", "client@example.com", "Client")
    fn = "Inv_08_0004_01_2026.pdf"
    (unsigned / fn).write_bytes(b"%PDF fake")
    (signed / fn).write_bytes(b"%PDF signed fake")
    run_log.mark_signed(fn, "0004", "client@example.com")

    jobs = build(customers, run_log, unsigned, signed)
    assert jobs[0].status == Status.SIGNED

    with patch("app.pipeline.send_invoice_email") as mock_send:
        report = send_jobs(jobs, run_log, make_creds(), make_template())
        mock_send.assert_called_once()
        args, _ = mock_send.call_args
        assert args[1] == "client@example.com"

    assert jobs[0].status == Status.SENT
    assert report.sent_count == 1
    assert run_log.is_sent(fn) is True


def test_send_jobs_ignores_pending_and_no_match(env):
    customers, run_log, unsigned, signed = env
    customers.upsert("0004", "client@example.com", "Client")
    (unsigned / "Inv_08_0004_01_2026.pdf").write_bytes(b"%PDF fake")  # not signed yet
    (unsigned / "Inv_08_9999_01_2026.pdf").write_bytes(b"%PDF fake")  # no match

    jobs = build(customers, run_log, unsigned, signed)
    with patch("app.pipeline.send_invoice_email") as mock_send:
        send_jobs(jobs, run_log, make_creds(), make_template())
        mock_send.assert_not_called()


def test_send_failure_marks_send_failed_but_stays_recorded_as_signed(env):
    customers, run_log, unsigned, signed = env
    customers.upsert("0004", "client@example.com", "Client")
    fn = "Inv_08_0004_01_2026.pdf"
    (unsigned / fn).write_bytes(b"%PDF fake")
    (signed / fn).write_bytes(b"%PDF signed fake")
    run_log.mark_signed(fn, "0004", "client@example.com")
    jobs = build(customers, run_log, unsigned, signed)

    with patch("app.pipeline.send_invoice_email", side_effect=MailError("smtp down")):
        report = send_jobs(jobs, run_log, make_creds(), make_template())

    assert jobs[0].status == Status.SEND_FAILED
    assert report.failed_count == 1
    assert run_log.is_sent(fn) is False
    assert run_log.get(fn).signed_at is not None


def test_send_can_run_in_a_separate_session_after_sign(env):
    """Simulates: sign in one run, quit, reopen, send in a later run."""
    customers, run_log, unsigned, signed = env
    customers.upsert("0004", "client@example.com", "Client")
    fn = "Inv_08_0004_01_2026.pdf"
    (unsigned / fn).write_bytes(b"%PDF fake")

    jobs = build(customers, run_log, unsigned, signed)
    with patch("app.pipeline.sign_pdf"):
        sign_jobs(jobs, signer=object(), signed_dir=signed, run_log=run_log)
    assert jobs[0].status == Status.SIGNED
    # pretend the signed file was actually written (mocked sign_pdf doesn't write it)
    (signed / fn).write_bytes(b"%PDF signed fake")

    # fresh scan, as if the app was restarted
    jobs2 = build(customers, run_log, unsigned, signed)
    assert jobs2[0].status == Status.SIGNED

    with patch("app.pipeline.send_invoice_email") as mock_send:
        send_jobs(jobs2, run_log, make_creds(), make_template())
        mock_send.assert_called_once()
    assert jobs2[0].status == Status.SENT
