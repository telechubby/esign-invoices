from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from app.mailer import EmailTemplate, SmtpCredentials
from app.pipeline import BatchReport, InvoiceJob, run_batch
from app.runlog import RunLog
from app.signer import SignatureOptions, SigningError, pkcs11_signing_session


class BatchWorker(QThread):
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
        mail_creds: SmtpCredentials,
        template: EmailTemplate,
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
        self.mail_creds = mail_creds
        self.template = template
        self.sig_options = sig_options
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            with pkcs11_signing_session(self.driver_path, self.pin, slot_no=self.slot_no) as signer:
                report = run_batch(
                    self.jobs,
                    signer,
                    self.signed_dir,
                    self.run_log,
                    self.mail_creds,
                    self.template,
                    self.sig_options,
                    on_progress=lambda job: self.job_updated.emit(job),
                    should_cancel=lambda: self._cancel_event.is_set(),
                )
            self.finished_batch.emit(report)
        except SigningError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - surface anything unexpected to the GUI
            self.failed.emit(str(exc))
