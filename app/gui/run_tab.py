from __future__ import annotations

import csv
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app import strings as S
from app.config import AppConfig, get_gmail_app_password, get_pkcs12_password
from app.customers import CustomerStore
from app.gui.batch_worker import SendBatchWorker, SignBatchWorker
from app.mailer import EmailTemplate, SmtpCredentials
from app.matcher import FilenamePattern
from app.pipeline import BatchReport, InvoiceJob, Status, build_jobs
from app.runlog import RunLog
from app.signer import SignatureOptions

_STATUS_TEXT = {
    Status.PENDING: S.RUN_STATUS_PENDING,
    Status.NO_MATCH: S.RUN_STATUS_NO_MATCH,
    Status.ALREADY_SENT: S.RUN_STATUS_ALREADY_SENT,
    Status.SIGNING: S.RUN_STATUS_SIGNING,
    Status.SIGNED: S.RUN_STATUS_SIGNED,
    Status.SIGN_FAILED: S.RUN_STATUS_SIGN_FAILED,
    Status.SENDING: S.RUN_STATUS_SENDING,
    Status.SENT: S.RUN_STATUS_SENT,
    Status.SEND_FAILED: S.RUN_STATUS_SEND_FAILED,
}


class RunTab(QWidget):
    def __init__(self, config: AppConfig, customers: CustomerStore, run_log: RunLog, parent=None):
        super().__init__(parent)
        self.config = config
        self.customers = customers
        self.run_log = run_log
        self.jobs: list[InvoiceJob] = []
        self.worker: SignBatchWorker | SendBatchWorker | None = None

        layout = QVBoxLayout(self)

        btn_row = QHBoxLayout()
        self.scan_btn = QPushButton(S.RUN_SCAN)
        self.scan_btn.clicked.connect(self._scan)
        self.sign_btn = QPushButton(S.RUN_SIGN)
        self.sign_btn.clicked.connect(self._start_sign)
        self.open_folder_btn = QPushButton(S.RUN_OPEN_SIGNED_FOLDER)
        self.open_folder_btn.clicked.connect(self._open_signed_folder)
        self.send_btn = QPushButton(S.RUN_SEND)
        self.send_btn.clicked.connect(self._start_send)
        self.cancel_btn = QPushButton(S.RUN_CANCEL)
        self.cancel_btn.clicked.connect(self._cancel)
        self.cancel_btn.setEnabled(False)
        self.export_btn = QPushButton(S.RUN_EXPORT_REPORT)
        self.export_btn.clicked.connect(self._export_report)
        self.export_btn.setEnabled(False)
        for b in (
            self.scan_btn,
            self.sign_btn,
            self.open_folder_btn,
            self.send_btn,
            self.cancel_btn,
            self.export_btn,
        ):
            btn_row.addWidget(b)
        layout.addLayout(btn_row)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            [S.RUN_TABLE_FILE, S.RUN_TABLE_CUSTOMER, S.RUN_TABLE_EMAIL, S.RUN_TABLE_STATUS]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

        self.progress = QProgressBar()
        layout.addWidget(self.progress)

        self.summary_label = QLineEdit()
        self.summary_label.setReadOnly(True)
        layout.addWidget(self.summary_label)

    def _pattern(self) -> FilenamePattern:
        return FilenamePattern(
            separator=self.config.filename_separator,
            id_position=self.config.filename_id_position,
        )

    def _scan(self) -> None:
        unsigned_dir = Path(self.config.unsigned_dir)
        signed_dir = Path(self.config.signed_dir)
        if not unsigned_dir.exists():
            QMessageBox.critical(self, S.ERROR_TITLE, S.RUN_ERROR_FOLDER_MISSING.format(path=unsigned_dir))
            return

        self.jobs = build_jobs(unsigned_dir, signed_dir, self._pattern(), self.customers, self.run_log)
        self.table.setRowCount(len(self.jobs))
        for row_idx, job in enumerate(self.jobs):
            self._render_row(row_idx, job)

        self.export_btn.setEnabled(False)
        self.summary_label.setText("")
        if not self.jobs:
            QMessageBox.information(self, S.RUN_SCAN, S.RUN_NO_FILES)

    def _render_row(self, row_idx: int, job: InvoiceJob) -> None:
        customer = job.match.customer
        self.table.setItem(row_idx, 0, QTableWidgetItem(job.filename))
        self.table.setItem(row_idx, 1, QTableWidgetItem(customer.name if customer else ""))
        self.table.setItem(row_idx, 2, QTableWidgetItem(customer.email if customer else ""))
        self.table.setItem(row_idx, 3, QTableWidgetItem(_STATUS_TEXT.get(job.status, job.status)))

    def _job_row_index(self, job: InvoiceJob) -> int | None:
        for i, j in enumerate(self.jobs):
            if j is job:
                return i
        return None

    def _open_signed_folder(self) -> None:
        signed_dir = Path(self.config.signed_dir)
        signed_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(signed_dir)))

    # -- sign step -----------------------------------------------------

    def _start_sign(self) -> None:
        is_pkcs12 = self.config.signing_mode == "pkcs12"
        if is_pkcs12 and not self.config.pkcs12_path:
            QMessageBox.warning(self, S.ERROR_TITLE, S.RUN_ERROR_NO_PKCS12)
            return
        if not is_pkcs12 and not self.config.pkcs11_driver_path:
            QMessageBox.warning(self, S.ERROR_TITLE, S.RUN_ERROR_NO_DRIVER)
            return

        pending = [j for j in self.jobs if j.status == Status.PENDING]
        if not pending:
            QMessageBox.information(self, S.RUN_SIGN, S.RUN_ERROR_NO_PENDING)
            return

        confirm = QMessageBox.question(
            self, S.RUN_CONFIRM_TITLE, S.RUN_CONFIRM_SIGN_MSG.format(count=len(pending))
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        sig_options = SignatureOptions(
            reason=self.config.signature_reason,
            location=self.config.signature_location,
            x_pct=self.config.sig_x_pct,
            y_pct=self.config.sig_y_pct,
            width_pct=self.config.sig_width_pct,
            height_pct=self.config.sig_height_pct,
            stamp_text=self.config.sig_stamp_text,
            background_image_path=self.config.sig_background_image,
            background_opacity=self.config.sig_background_opacity,
        )
        self._tracked_job_ids = {id(j) for j in pending}
        self._begin_progress(len(pending))

        if is_pkcs12:
            password, ok = QInputDialog.getText(
                self, S.RUN_PKCS12_PASSWORD_TITLE, S.RUN_PKCS12_PASSWORD_LABEL, QLineEdit.EchoMode.Password,
                get_pkcs12_password(self.config.pkcs12_path) or "",
            )
            if not ok:
                return
            self.worker = SignBatchWorker(
                jobs=self.jobs,
                signed_dir=Path(self.config.signed_dir),
                run_log=self.run_log,
                sig_options=sig_options,
                mode="pkcs12",
                pkcs12_path=Path(self.config.pkcs12_path),
                pkcs12_password=password,
            )
        else:
            pin, ok = QInputDialog.getText(
                self, S.RUN_PIN_TITLE, S.RUN_PIN_LABEL, QLineEdit.EchoMode.Password
            )
            if not ok or not pin:
                return
            slot_no = int(self.config.pkcs11_slot) if self.config.pkcs11_slot.strip().isdigit() else None
            self.worker = SignBatchWorker(
                jobs=self.jobs,
                signed_dir=Path(self.config.signed_dir),
                run_log=self.run_log,
                sig_options=sig_options,
                mode="pkcs11",
                driver_path=Path(self.config.pkcs11_driver_path),
                pin=pin,
                slot_no=slot_no,
                cert_label=self.config.pkcs11_cert_label or None,
            )

        self.worker.job_updated.connect(self._on_job_updated)
        self.worker.finished_batch.connect(self._on_sign_finished)
        self.worker.failed.connect(self._on_failed)
        self._set_buttons_running(True)
        self.worker.start()

    def _on_sign_finished(self, report: BatchReport) -> None:
        self.summary_label.setText(
            S.RUN_SIGN_SUMMARY.format(
                ok=report.signed_count, failed=report.failed_count, no_match=report.no_match_count
            )
        )
        self._set_buttons_running(False)
        self.export_btn.setEnabled(True)
        self.worker = None

    # -- send step -----------------------------------------------------

    def _start_send(self) -> None:
        app_password = get_gmail_app_password(self.config.gmail_address)
        if not self.config.gmail_address or not app_password:
            QMessageBox.warning(self, S.ERROR_TITLE, S.RUN_ERROR_NO_CREDS)
            return

        signed = [j for j in self.jobs if j.status == Status.SIGNED]
        if not signed:
            QMessageBox.information(self, S.RUN_SEND, S.RUN_ERROR_NO_SIGNED)
            return

        confirm = QMessageBox.question(
            self, S.RUN_CONFIRM_TITLE, S.RUN_CONFIRM_SEND_MSG.format(count=len(signed))
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        template = EmailTemplate(subject=self.config.email_subject, body=self.config.email_body)
        creds = SmtpCredentials(address=self.config.gmail_address, app_password=app_password)

        self._tracked_job_ids = {id(j) for j in signed}
        self._begin_progress(len(signed))
        self.worker = SendBatchWorker(
            jobs=self.jobs,
            run_log=self.run_log,
            mail_creds=creds,
            template=template,
        )
        self.worker.job_updated.connect(self._on_job_updated)
        self.worker.finished_batch.connect(self._on_send_finished)
        self.worker.failed.connect(self._on_failed)
        self._set_buttons_running(True)
        self.worker.start()

    def _on_send_finished(self, report: BatchReport) -> None:
        self.summary_label.setText(
            S.RUN_SEND_SUMMARY.format(ok=report.sent_count, failed=report.failed_count)
        )
        self._set_buttons_running(False)
        self.export_btn.setEnabled(True)
        self.worker = None

    # -- shared ---------------------------------------------------------

    def _begin_progress(self, total: int) -> None:
        self.progress.setMinimum(0)
        self.progress.setMaximum(total)
        self.progress.setValue(0)
        self._done_count = 0
        if not hasattr(self, "_tracked_job_ids"):
            self._tracked_job_ids: set[int] = set()

    def _set_buttons_running(self, running: bool) -> None:
        self.scan_btn.setEnabled(not running)
        self.sign_btn.setEnabled(not running)
        self.send_btn.setEnabled(not running)
        self.cancel_btn.setEnabled(running)

    def _on_job_updated(self, job: InvoiceJob) -> None:
        row_idx = self._job_row_index(job)
        if row_idx is not None:
            self._render_row(row_idx, job)
        if id(job) in self._tracked_job_ids and job.status in (
            Status.SENT,
            Status.SIGNED,
            Status.SIGN_FAILED,
            Status.SEND_FAILED,
        ):
            self._done_count += 1
            self.progress.setValue(min(self._done_count, self.progress.maximum()))

    def _on_failed(self, message: str) -> None:
        QMessageBox.critical(self, S.ERROR_TITLE, S.RUN_ERROR_BATCH.format(error=message))
        self._set_buttons_running(False)
        self.worker = None

    def _cancel(self) -> None:
        if self.worker:
            self.worker.cancel()
        self.cancel_btn.setEnabled(False)

    def _export_report(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, S.RUN_EXPORT_REPORT, "", "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow([S.RUN_TABLE_FILE, S.RUN_TABLE_CUSTOMER, S.RUN_TABLE_EMAIL, S.RUN_TABLE_STATUS, "Грешка"])
            for job in self.jobs:
                customer = job.match.customer
                writer.writerow(
                    [
                        job.filename,
                        customer.name if customer else "",
                        customer.email if customer else "",
                        _STATUS_TEXT.get(job.status, job.status),
                        job.error or "",
                    ]
                )
