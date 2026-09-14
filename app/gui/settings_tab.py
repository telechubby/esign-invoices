from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app import strings as S
from app.config import (
    AppConfig,
    get_gmail_app_password,
    get_pkcs12_password,
    save_config,
    set_gmail_app_password,
    set_pkcs12_password,
)
from app.matcher import FilenamePattern
from app.signer import SigningError, list_pkcs11_certificates

EXAMPLE_FILENAME = "Inv_08_0004_01_2026.pdf"

if sys.platform == "win32":
    DRIVER_FILE_FILTER = "PKCS#11 driver (*.dll)"
elif sys.platform == "darwin":
    DRIVER_FILE_FILTER = "PKCS#11 driver (*.dylib *.so)"
else:
    DRIVER_FILE_FILTER = "PKCS#11 driver (*.so)"

PKCS12_FILE_FILTER = "PKCS12 (*.p12 *.pfx)"


def _browse_row(line_edit: QLineEdit, is_dir: bool = True, file_filter: str = "") -> QHBoxLayout:
    row = QHBoxLayout()
    row.addWidget(line_edit, stretch=1)
    btn = QPushButton(S.SET_BROWSE)

    def _browse():
        if is_dir:
            path = QFileDialog.getExistingDirectory(None, S.SET_BROWSE, line_edit.text())
        else:
            path, _ = QFileDialog.getOpenFileName(None, S.SET_BROWSE, line_edit.text(), file_filter)
        if path:
            line_edit.setText(path)

    btn.clicked.connect(_browse)
    row.addWidget(btn)
    return row


class SettingsTab(QWidget):
    def __init__(self, config: AppConfig, on_saved=None, parent=None):
        super().__init__(parent)
        self.config = config
        self.on_saved = on_saved

        outer = QVBoxLayout(self)

        # -- paths --
        paths_group = QGroupBox(S.SET_PATHS_GROUP)
        paths_form = QFormLayout(paths_group)
        self.unsigned_edit = QLineEdit(config.unsigned_dir)
        self.signed_edit = QLineEdit(config.signed_dir)
        paths_form.addRow(S.SET_UNSIGNED_DIR, _wrap(_browse_row(self.unsigned_edit)))
        paths_form.addRow(S.SET_SIGNED_DIR, _wrap(_browse_row(self.signed_edit)))
        outer.addWidget(paths_group)

        # -- filename pattern --
        pattern_group = QGroupBox(S.SET_FILENAME_GROUP)
        pattern_form = QFormLayout(pattern_group)
        self.separator_edit = QLineEdit(config.filename_separator)
        self.separator_edit.setMaxLength(3)
        self.id_position_spin = QSpinBox()
        self.id_position_spin.setMinimum(1)
        self.id_position_spin.setMaximum(20)
        self.id_position_spin.setValue(config.filename_id_position)
        self.example_label = QLabel()
        pattern_form.addRow(S.SET_FILENAME_SEPARATOR, self.separator_edit)
        pattern_form.addRow(S.SET_FILENAME_ID_INDEX, self.id_position_spin)
        pattern_form.addRow("", self.example_label)
        self.separator_edit.textChanged.connect(self._update_example)
        self.id_position_spin.valueChanged.connect(self._update_example)
        self._update_example()
        outer.addWidget(pattern_group)

        # -- signing mode --
        mode_group = QGroupBox(S.SET_SIGNING_MODE_GROUP)
        mode_form = QFormLayout(mode_group)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem(S.SET_SIGNING_MODE_PKCS11, userData="pkcs11")
        self.mode_combo.addItem(S.SET_SIGNING_MODE_PKCS12, userData="pkcs12")
        self.mode_combo.setCurrentIndex(1 if config.signing_mode == "pkcs12" else 0)
        self.mode_combo.currentIndexChanged.connect(self._update_mode_visibility)
        mode_form.addRow(S.SET_SIGNING_MODE_LABEL, self.mode_combo)
        outer.addWidget(mode_group)

        # -- token (PKCS#11, real token) --
        self.token_group = QGroupBox(S.SET_TOKEN_GROUP)
        token_form = QFormLayout(self.token_group)
        self.driver_edit = QLineEdit(config.pkcs11_driver_path)
        self.slot_edit = QLineEdit(config.pkcs11_slot)
        token_form.addRow(
            S.SET_TOKEN_DRIVER,
            _wrap(_browse_row(self.driver_edit, is_dir=False, file_filter=DRIVER_FILE_FILTER)),
        )
        token_form.addRow(S.SET_TOKEN_SLOT, self.slot_edit)
        list_certs_btn = QPushButton(S.SET_TOKEN_LIST_CERTS)
        list_certs_btn.clicked.connect(self._list_certs)
        token_form.addRow("", list_certs_btn)
        outer.addWidget(self.token_group)

        # -- test certificate (PKCS12) --
        self.pkcs12_group = QGroupBox(S.SET_SIGNING_MODE_PKCS12)
        pkcs12_form = QFormLayout(self.pkcs12_group)
        self.pkcs12_path_edit = QLineEdit(config.pkcs12_path)
        self.pkcs12_password_edit = QLineEdit(get_pkcs12_password(config.pkcs12_path) or "")
        self.pkcs12_password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        pkcs12_form.addRow(
            S.SET_PKCS12_PATH,
            _wrap(_browse_row(self.pkcs12_path_edit, is_dir=False, file_filter=PKCS12_FILE_FILTER)),
        )
        pkcs12_form.addRow(S.SET_PKCS12_PASSWORD, self.pkcs12_password_edit)
        warning_label = QLabel(S.SET_SIGNING_MODE_WARNING)
        warning_label.setWordWrap(True)
        pkcs12_form.addRow("", warning_label)
        outer.addWidget(self.pkcs12_group)

        self._update_mode_visibility()

        # -- email --
        email_group = QGroupBox(S.SET_EMAIL_GROUP)
        email_form = QFormLayout(email_group)
        self.gmail_edit = QLineEdit(config.gmail_address)
        self.app_password_edit = QLineEdit(get_gmail_app_password(config.gmail_address) or "")
        self.app_password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.subject_edit = QLineEdit(config.email_subject)
        self.body_edit = QTextEdit(config.email_body)
        self.body_edit.setFixedHeight(100)
        hint = QLabel(S.SET_EMAIL_PLACEHOLDERS_HINT)
        email_form.addRow(S.SET_EMAIL_ADDRESS, self.gmail_edit)
        email_form.addRow(S.SET_EMAIL_APP_PASSWORD, self.app_password_edit)
        email_form.addRow(S.SET_EMAIL_SUBJECT, self.subject_edit)
        email_form.addRow(S.SET_EMAIL_BODY, self.body_edit)
        email_form.addRow("", hint)
        outer.addWidget(email_group)

        save_btn = QPushButton(S.SET_SAVE)
        save_btn.clicked.connect(self._save)
        outer.addWidget(save_btn)
        outer.addStretch(1)

    def _update_mode_visibility(self) -> None:
        is_pkcs12 = self.mode_combo.currentData() == "pkcs12"
        self.token_group.setVisible(not is_pkcs12)
        self.pkcs12_group.setVisible(is_pkcs12)

    def _update_example(self) -> None:
        pattern = FilenamePattern(
            separator=self.separator_edit.text() or "_",
            id_position=self.id_position_spin.value(),
        )
        extracted = pattern.extract_id(EXAMPLE_FILENAME) or "?"
        self.example_label.setText(S.SET_FILENAME_EXAMPLE.format(example=EXAMPLE_FILENAME, extracted=extracted))

    def _list_certs(self) -> None:
        driver = self.driver_edit.text().strip()
        if not driver:
            return
        try:
            labels = list_pkcs11_certificates(Path(driver))
        except SigningError as exc:
            QMessageBox.critical(self, S.ERROR_TITLE, str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, S.ERROR_TITLE, str(exc))
            return
        QMessageBox.information(self, S.SET_TOKEN_LIST_CERTS, "\n".join(labels) or "—")

    def _save(self) -> None:
        self.config.unsigned_dir = self.unsigned_edit.text().strip()
        self.config.signed_dir = self.signed_edit.text().strip()
        self.config.filename_separator = self.separator_edit.text() or "_"
        self.config.filename_id_position = self.id_position_spin.value()
        self.config.signing_mode = self.mode_combo.currentData()
        self.config.pkcs11_driver_path = self.driver_edit.text().strip()
        self.config.pkcs11_slot = self.slot_edit.text().strip()
        self.config.pkcs12_path = self.pkcs12_path_edit.text().strip()
        self.config.gmail_address = self.gmail_edit.text().strip()
        self.config.email_subject = self.subject_edit.text()
        self.config.email_body = self.body_edit.toPlainText()

        save_config(self.config)
        if self.config.gmail_address and self.app_password_edit.text():
            set_gmail_app_password(self.config.gmail_address, self.app_password_edit.text())
        if self.config.pkcs12_path and self.pkcs12_password_edit.text():
            set_pkcs12_password(self.config.pkcs12_path, self.pkcs12_password_edit.text())

        QMessageBox.information(self, S.SET_SAVE, S.SET_SAVED)
        if self.on_saved:
            self.on_saved()


def _wrap(layout: QHBoxLayout) -> QWidget:
    w = QWidget()
    w.setLayout(layout)
    return w
