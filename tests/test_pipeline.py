from pathlib import Path
from unittest.mock import patch

import pytest

from app.customers import CustomerStore
from app.mailer import EmailTemplate, MailError, SmtpCredentials
from app.matcher import FilenamePattern
from app.pipeline import Status, build_jobs, run_batch
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


def test_no_match_is_skipped_without_signing(env):
    customers, run_log, unsigned, signed = env
    (unsigned / "Inv_08_9999_01_2026.pdf").write_bytes(b"%PDF fake")
    pattern = FilenamePattern(separator="_", id_position=3)

    jobs = build_jobs(unsigned, pattern, customers, run_log)
    assert jobs[0].status == Status.NO_MATCH

    with patch("app.pipeline.sign_pdf") as mock_sign, patch(
        "app.pipeline.send_invoice_email"
    ) as mock_send:
        run_batch(jobs, signer=object(), signed_dir=signed, run_log=run_log,
                   mail_creds=make_creds(), template=make_template())
        mock_sign.assert_not_called()
        mock_send.assert_not_called()


def test_already_sent_is_skipped(env):
    customers, run_log, unsigned, signed = env
    customers.upsert("0004", "client@example.com", "Client")
    fn = "Inv_08_0004_01_2026.pdf"
    (unsigned / fn).write_bytes(b"%PDF fake")
    run_log.mark_signed(fn, "0004", "client@example.com")
    run_log.mark_sent(fn)

    pattern = FilenamePattern(separator="_", id_position=3)
    jobs = build_jobs(unsigned, pattern, customers, run_log)
    assert jobs[0].status == Status.ALREADY_SENT

    with patch("app.pipeline.sign_pdf") as mock_sign, patch(
        "app.pipeline.send_invoice_email"
    ) as mock_send:
        run_batch(jobs, signer=object(), signed_dir=signed, run_log=run_log,
                   mail_creds=make_creds(), template=make_template())
        mock_sign.assert_not_called()
        mock_send.assert_not_called()


def test_happy_path_signs_and_sends(env):
    customers, run_log, unsigned, signed = env
    customers.upsert("0004", "client@example.com", "Client DOO")
    fn = "Inv_08_0004_01_2026.pdf"
    (unsigned / fn).write_bytes(b"%PDF fake")

    pattern = FilenamePattern(separator="_", id_position=3)
    jobs = build_jobs(unsigned, pattern, customers, run_log)
    assert jobs[0].status == Status.PENDING

    with patch("app.pipeline.sign_pdf") as mock_sign, patch(
        "app.pipeline.send_invoice_email"
    ) as mock_send:
        report = run_batch(jobs, signer=object(), signed_dir=signed, run_log=run_log,
                            mail_creds=make_creds(), template=make_template())
        mock_sign.assert_called_once()
        mock_send.assert_called_once()
        args, kwargs = mock_send.call_args
        assert args[1] == "client@example.com"

    assert report.sent_count == 1
    assert jobs[0].status == Status.SENT
    assert run_log.is_sent(fn) is True


def test_sign_failure_does_not_send_email(env):
    customers, run_log, unsigned, signed = env
    customers.upsert("0004", "client@example.com", "Client DOO")
    fn = "Inv_08_0004_01_2026.pdf"
    (unsigned / fn).write_bytes(b"%PDF fake")

    pattern = FilenamePattern(separator="_", id_position=3)
    jobs = build_jobs(unsigned, pattern, customers, run_log)

    with patch("app.pipeline.sign_pdf", side_effect=SigningError("token error")) as mock_sign, \
         patch("app.pipeline.send_invoice_email") as mock_send:
        report = run_batch(jobs, signer=object(), signed_dir=signed, run_log=run_log,
                            mail_creds=make_creds(), template=make_template())
        mock_sign.assert_called_once()
        mock_send.assert_not_called()

    assert jobs[0].status == Status.SIGN_FAILED
    assert report.failed_count == 1
    assert run_log.is_sent(fn) is False


def test_send_failure_after_successful_sign_keeps_signed_state(env):
    customers, run_log, unsigned, signed = env
    customers.upsert("0004", "client@example.com", "Client DOO")
    fn = "Inv_08_0004_01_2026.pdf"
    (unsigned / fn).write_bytes(b"%PDF fake")

    pattern = FilenamePattern(separator="_", id_position=3)
    jobs = build_jobs(unsigned, pattern, customers, run_log)

    with patch("app.pipeline.sign_pdf") as mock_sign, \
         patch("app.pipeline.send_invoice_email", side_effect=MailError("smtp down")) as mock_send:
        report = run_batch(jobs, signer=object(), signed_dir=signed, run_log=run_log,
                            mail_creds=make_creds(), template=make_template())

    assert jobs[0].status == Status.SEND_FAILED
    assert report.failed_count == 1
    assert run_log.is_sent(fn) is False
    entry = run_log.get(fn)
    assert entry.signed_at is not None  # signing was recorded despite send failure


def test_progress_callback_invoked_for_each_transition(env):
    customers, run_log, unsigned, signed = env
    customers.upsert("0004", "client@example.com", "Client DOO")
    fn = "Inv_08_0004_01_2026.pdf"
    (unsigned / fn).write_bytes(b"%PDF fake")

    pattern = FilenamePattern(separator="_", id_position=3)
    jobs = build_jobs(unsigned, pattern, customers, run_log)

    seen_statuses = []
    with patch("app.pipeline.sign_pdf"), patch("app.pipeline.send_invoice_email"):
        run_batch(
            jobs, signer=object(), signed_dir=signed, run_log=run_log,
            mail_creds=make_creds(), template=make_template(),
            on_progress=lambda job: seen_statuses.append(job.status),
        )

    assert Status.SIGNING in seen_statuses
    assert Status.SIGNED in seen_statuses
    assert Status.SENDING in seen_statuses
    assert Status.SENT in seen_statuses


def test_cancel_stops_before_next_pending_job(env):
    customers, run_log, unsigned, signed = env
    customers.upsert("0001", "a@x.com", "A")
    customers.upsert("0002", "b@x.com", "B")
    (unsigned / "Inv_08_0001_01_2026.pdf").write_bytes(b"%PDF fake")
    (unsigned / "Inv_08_0002_01_2026.pdf").write_bytes(b"%PDF fake")

    pattern = FilenamePattern(separator="_", id_position=3)
    jobs = build_jobs(unsigned, pattern, customers, run_log)

    calls = {"n": 0}

    def cancel_after_first():
        return calls["n"] >= 1

    def fake_sign(*a, **k):
        calls["n"] += 1

    with patch("app.pipeline.sign_pdf", side_effect=fake_sign), \
         patch("app.pipeline.send_invoice_email"):
        run_batch(jobs, signer=object(), signed_dir=signed, run_log=run_log,
                   mail_creds=make_creds(), template=make_template(),
                   should_cancel=cancel_after_first)

    statuses = [j.status for j in jobs]
    assert Status.SENT in statuses  # first job completed
    assert Status.PENDING in statuses  # second job never started
