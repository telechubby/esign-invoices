from __future__ import annotations

import csv

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app import strings as S
from app.customers import CustomerStore, ImportPreview


class ImportDialog(QDialog):
    def __init__(self, store: CustomerStore, parent=None):
        super().__init__(parent)
        self.store = store
        self.preview: ImportPreview | None = None
        self.csv_path: str | None = None
        self.setWindowTitle(S.IMPORT_TITLE)
        self.resize(700, 500)

        layout = QVBoxLayout(self)

        file_row = QHBoxLayout()
        self.file_label = QLabel("—")
        choose_btn = QPushButton(S.IMPORT_CHOOSE_FILE)
        choose_btn.clicked.connect(self._choose_file)
        file_row.addWidget(choose_btn)
        file_row.addWidget(self.file_label, stretch=1)
        layout.addLayout(file_row)

        col_row = QHBoxLayout()
        self.id_combo = QComboBox()
        self.email_combo = QComboBox()
        self.name_combo = QComboBox()
        col_row.addWidget(QLabel(S.IMPORT_COL_ID))
        col_row.addWidget(self.id_combo)
        col_row.addWidget(QLabel(S.IMPORT_COL_EMAIL))
        col_row.addWidget(self.email_combo)
        col_row.addWidget(QLabel(S.IMPORT_COL_NAME))
        col_row.addWidget(self.name_combo)
        layout.addLayout(col_row)

        preview_btn = QPushButton(S.IMPORT_PREVIEW_TITLE)
        preview_btn.clicked.connect(self._build_preview)
        layout.addWidget(preview_btn)

        self.summary_label = QLabel("")
        layout.addWidget(self.summary_label)

        layout.addWidget(QLabel(S.IMPORT_NEW))
        self.new_table = QTableWidget(0, 3)
        self.new_table.setHorizontalHeaderLabels([S.CUST_TABLE_ID, S.CUST_TABLE_EMAIL, S.CUST_TABLE_NAME])
        layout.addWidget(self.new_table)

        layout.addWidget(QLabel(S.IMPORT_CONFLICTS))
        self.conflict_table = QTableWidget(0, 4)
        self.conflict_table.setHorizontalHeaderLabels(
            ["ID", S.CUST_TABLE_EMAIL + " (стара)", S.CUST_TABLE_EMAIL + " (нова)", "Резолуција"]
        )
        layout.addWidget(self.conflict_table)

        btn_row = QHBoxLayout()
        apply_btn = QPushButton(S.IMPORT_APPLY)
        apply_btn.clicked.connect(self._apply)
        cancel_btn = QPushButton(S.IMPORT_CANCEL)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(apply_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def _choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, S.IMPORT_CHOOSE_FILE, "", "CSV (*.csv)")
        if not path:
            return
        self.csv_path = path
        self.file_label.setText(path)
        try:
            with open(path, newline="", encoding="utf-8-sig") as f:
                header = next(csv.reader(f))
        except Exception as exc:
            QMessageBox.critical(self, S.ERROR_TITLE, S.IMPORT_ERROR_READ.format(error=exc))
            return

        for combo in (self.id_combo, self.email_combo, self.name_combo):
            combo.clear()
            combo.addItems(header)
        self.name_combo.insertItem(0, "")
        self.name_combo.setCurrentIndex(0)

    def _build_preview(self) -> None:
        if not self.csv_path:
            return
        id_col = self.id_combo.currentText()
        email_col = self.email_combo.currentText()
        name_col = self.name_combo.currentText() or None
        if not id_col or not email_col:
            QMessageBox.warning(self, S.ERROR_TITLE, S.IMPORT_ERROR_NO_COLUMNS)
            return

        try:
            rows = CustomerStore.read_csv_rows(self.csv_path, id_col, email_col, name_col)
        except Exception as exc:
            QMessageBox.critical(self, S.ERROR_TITLE, S.IMPORT_ERROR_READ.format(error=exc))
            return

        self.preview = self.store.build_preview(rows)
        self._render_preview()

    def _render_preview(self) -> None:
        assert self.preview is not None
        self.summary_label.setText(
            S.IMPORT_SUMMARY.format(
                new=len(self.preview.new),
                unchanged=len(self.preview.unchanged),
                conflicts=len(self.preview.conflicts),
            )
        )

        self.new_table.setRowCount(len(self.preview.new))
        for row_idx, row in enumerate(self.preview.new):
            self.new_table.setItem(row_idx, 0, QTableWidgetItem(row.id))
            self.new_table.setItem(row_idx, 1, QTableWidgetItem(row.email))
            self.new_table.setItem(row_idx, 2, QTableWidgetItem(row.name))

        self.conflict_table.setRowCount(len(self.preview.conflicts))
        for row_idx, (incoming, existing) in enumerate(self.preview.conflicts):
            self.conflict_table.setItem(row_idx, 0, QTableWidgetItem(incoming.id))
            self.conflict_table.setItem(row_idx, 1, QTableWidgetItem(existing.email))
            self.conflict_table.setItem(row_idx, 2, QTableWidgetItem(incoming.email))
            resolution_combo = QComboBox()
            resolution_combo.addItems([S.IMPORT_CONFLICT_KEEP_EXISTING, S.IMPORT_CONFLICT_USE_NEW])
            self.conflict_table.setCellWidget(row_idx, 3, resolution_combo)

    def _apply(self) -> None:
        if self.preview is None:
            return
        resolutions: dict[str, bool] = {}
        for row_idx, (incoming, _existing) in enumerate(self.preview.conflicts):
            widget = self.conflict_table.cellWidget(row_idx, 3)
            use_new = isinstance(widget, QComboBox) and widget.currentText() == S.IMPORT_CONFLICT_USE_NEW
            resolutions[incoming.id] = use_new

        added, updated = self.store.apply_import(self.preview, resolutions)
        QMessageBox.information(self, S.IMPORT_TITLE, S.IMPORT_DONE.format(added=added, updated=updated))
        self.accept()
