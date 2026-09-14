from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from app.mailer import EmailTemplate, SmtpCredentials
from app.pipeline import BatchReport, InvoiceJob, send_jobs, sign_jobs
from app.runlog import RunLog
from app.signer import SignatureOptions, SigningError, pkcs11_signing_session


class SignBatchWorker(QThread):
    """Opens one PKCS#11 session (one PIN entry) and signs all PENDING jobs.
    Does not send anything - that is a separate, later step."""

    job_updated = Signal(object)  # InvoiceJob
    finished_batch = Signal(object)  # BatchReport
    failed = Signal(str)

    def __init__(
        self,
        jobs: list[InvoiceJob],
        driver_path: Path,
        pin: str,
        slot_no: int | None,
        signed_dir: Path,
        run_log: RunLog,
        sig_options: SignatureOptions,
        parent=None,
    ):
        super().__init__(parent)
        self.jobs = jobs
        self.driver_path = driver_path
        self.pin = pin
        self.slot_no = slot_no
        self.signed_dir = signed_dir
        self.run_log = run_log
        self.sig_options = sig_options
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            with pkcs11_signing_session(self.driver_path, self.pin, slot_no=self.slot_no) as signer:
                report = sign_jobs(
                    self.jobs,
                    signer,
                    self.signed_dir,
                    self.run_log,
                    self.sig_options,
                    on_progress=lambda job: self.job_updated.emit(job),
                    should_cancel=lambda: self._cancel_event.is_set(),
                )
            self.finished_batch.emit(report)
        except SigningError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - surface anything unexpected to the GUI
            self.failed.emit(str(exc))


class SendBatchWorker(QThread):
    """Emails all SIGNED jobs. No token/PIN involved - can run any time
    after the sign step, in the same session or a later one."""

    job_updated = Signal(object)
    finished_batch = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        jobs: list[InvoiceJob],
        run_log: RunLog,
        mail_creds: SmtpCredentials,
        template: EmailTemplate,
        parent=None,
    ):
        super().__init__(parent)
        self.jobs = jobs
        self.run_log = run_log
        self.mail_creds = mail_creds
        self.template = template
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            report = send_jobs(
                self.jobs,
                self.run_log,
                self.mail_creds,
                self.template,
                on_progress=lambda job: self.job_updated.emit(job),
                should_cancel=lambda: self._cancel_event.is_set(),
            )
            self.finished_batch.emit(report)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
