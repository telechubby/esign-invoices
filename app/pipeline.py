"""Orchestrates the batch as two separate, independently-runnable steps:

1. sign_jobs()  - sign matched invoices, write them to the signed folder.
2. send_jobs()  - email invoices that are already signed.

They are deliberately not combined into one pass: someone should be able to
look at the signed PDFs (or just let them sit) before they go out by email,
and the two steps don't even need to happen in the same app session - a
job that was signed earlier (recorded in the run log) but never sent is
picked up as SIGNED on the next scan, ready for the send step alone.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable

from app.customers import CustomerStore
from app.mailer import EmailTemplate, MailError, SmtpCredentials, send_invoice_email
from app.matcher import FilenamePattern, MatchResult, scan_invoices
from app.runlog import RunLog
from app.signer import SignatureOptions, SigningError, sign_pdf
from app.signer import Signer as PyHankoSigner  # re-exported type alias


class Status(str, Enum):
    PENDING = "pending"
    NO_MATCH = "no_match"
    ALREADY_SENT = "already_sent"
    SIGNING = "signing"
    SIGNED = "signed"
    SIGN_FAILED = "sign_failed"
    SENDING = "sending"
    SENT = "sent"
    SEND_FAILED = "send_failed"


@dataclass
class InvoiceJob:
    match: MatchResult
    status: Status = Status.PENDING
    error: str | None = None
    signed_path: Path | None = None

    @property
    def filename(self) -> str:
        return self.match.file_path.name


@dataclass
class BatchReport:
    jobs: list[InvoiceJob] = field(default_factory=list)

    @property
    def sent_count(self) -> int:
        return sum(1 for j in self.jobs if j.status == Status.SENT)

    @property
    def signed_count(self) -> int:
        return sum(1 for j in self.jobs if j.status == Status.SIGNED)

    @property
    def failed_count(self) -> int:
        return sum(
            1
            for j in self.jobs
            if j.status in (Status.SIGN_FAILED, Status.SEND_FAILED)
        )

    @property
    def no_match_count(self) -> int:
        return sum(1 for j in self.jobs if j.status == Status.NO_MATCH)


def build_jobs(
    unsigned_dir: Path,
    signed_dir: Path,
    pattern: FilenamePattern,
    customers: CustomerStore,
    run_log: RunLog,
) -> list[InvoiceJob]:
    """Classifies every invoice in unsigned_dir by matching it to a customer
    and consulting the run log, so previously-signed-but-unsent invoices
    come back as SIGNED (ready for the send step) rather than PENDING."""
    matches = scan_invoices(unsigned_dir, pattern, customers)
    jobs: list[InvoiceJob] = []
    for m in matches:
        if not m.matched:
            jobs.append(InvoiceJob(match=m, status=Status.NO_MATCH))
            continue

        entry = run_log.get(m.file_path.name)
        signed_path = signed_dir / m.file_path.name

        if entry and entry.sent_at:
            jobs.append(InvoiceJob(match=m, status=Status.ALREADY_SENT, signed_path=signed_path))
        elif entry and entry.signed_at and signed_path.exists():
            jobs.append(InvoiceJob(match=m, status=Status.SIGNED, signed_path=signed_path))
        else:
            jobs.append(InvoiceJob(match=m, status=Status.PENDING))
    return jobs


def sign_jobs(
    jobs: list[InvoiceJob],
    signer: PyHankoSigner,
    signed_dir: Path,
    run_log: RunLog,
    sig_options: SignatureOptions | None = None,
    on_progress: Callable[[InvoiceJob], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> BatchReport:
    report = BatchReport(jobs=jobs)

    for job in jobs:
        if job.status != Status.PENDING:
            if on_progress:
                on_progress(job)
            continue
        if should_cancel and should_cancel():
            break

        customer = job.match.customer
        assert customer is not None  # PENDING implies matched

        job.status = Status.SIGNING
        if on_progress:
            on_progress(job)

        out_path = signed_dir / job.filename
        try:
            sign_pdf(job.match.file_path, out_path, signer, sig_options)
        except SigningError as exc:
            job.status = Status.SIGN_FAILED
            job.error = str(exc)
            run_log.mark_error(job.filename, job.error)
            if on_progress:
                on_progress(job)
            continue

        job.signed_path = out_path
        job.status = Status.SIGNED
        run_log.mark_signed(job.filename, customer.id, customer.email)
        if on_progress:
            on_progress(job)

    return report


def send_jobs(
    jobs: list[InvoiceJob],
    run_log: RunLog,
    mail_creds: SmtpCredentials,
    template: EmailTemplate,
    on_progress: Callable[[InvoiceJob], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> BatchReport:
    report = BatchReport(jobs=jobs)

    for job in jobs:
        if job.status != Status.SIGNED:
            if on_progress:
                on_progress(job)
            continue
        if should_cancel and should_cancel():
            break

        customer = job.match.customer
        assert customer is not None and job.signed_path is not None

        job.status = Status.SENDING
        if on_progress:
            on_progress(job)

        subject, body = template.render(
            invoice_id=job.filename,
            customer_name=customer.name or customer.id,
        )
        try:
            send_invoice_email(mail_creds, customer.email, subject, body, job.signed_path)
        except MailError as exc:
            job.status = Status.SEND_FAILED
            job.error = str(exc)
            run_log.mark_error(job.filename, job.error)
            if on_progress:
                on_progress(job)
            continue

        job.status = Status.SENT
        run_log.mark_sent(job.filename)
        if on_progress:
            on_progress(job)

    return report
