from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app import strings as S
from app.customers import Customer, CustomerStore
from app.gui.customer_dialog import CustomerDialog
from app.gui.import_dialog import ImportDialog


class CustomersTab(QWidget):
    def __init__(self, store: CustomerStore, parent=None):
        super().__init__(parent)
        self.store = store
        self._all_customers: list[Customer] = []

        layout = QVBoxLayout(self)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(S.CUST_SEARCH_PLACEHOLDER)
        self.search_edit.textChanged.connect(self._apply_filter)
        layout.addWidget(self.search_edit)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            [S.CUST_TABLE_ID, S.CUST_TABLE_NAME, S.CUST_TABLE_EMAIL, S.CUST_TABLE_UPDATED]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.doubleClicked.connect(self._edit_selected)
        layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        add_btn = QPushButton(S.CUST_ADD)
        add_btn.clicked.connect(self._add)
        edit_btn = QPushButton(S.CUST_EDIT)
        edit_btn.clicked.connect(self._edit_selected)
        delete_btn = QPushButton(S.CUST_DELETE)
        delete_btn.clicked.connect(self._delete_selected)
        import_btn = QPushButton(S.CUST_IMPORT_CSV)
        import_btn.clicked.connect(self._import_csv)
        for b in (add_btn, edit_btn, delete_btn, import_btn):
            btn_row.addWidget(b)
        layout.addLayout(btn_row)

        self.refresh()

    def refresh(self) -> None:
        self._all_customers = self.store.list_all()
        self._apply_filter()

    def _apply_filter(self) -> None:
        query = self.search_edit.text().strip().lower()
        rows = [
            c
            for c in self._all_customers
            if not query
            or query in c.id.lower()
            or query in c.name.lower()
            or query in c.email.lower()
        ]
        self.table.setRowCount(len(rows))
        for row_idx, c in enumerate(rows):
            self.table.setItem(row_idx, 0, QTableWidgetItem(c.id))
            self.table.setItem(row_idx, 1, QTableWidgetItem(c.name))
            self.table.setItem(row_idx, 2, QTableWidgetItem(c.email))
            self.table.setItem(row_idx, 3, QTableWidgetItem(c.updated_at))

    def _selected_id(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.text() if item else None

    def _add(self) -> None:
        dialog = CustomerDialog(self)
        if dialog.exec():
            cid, email, name = dialog.values()
            if cid and email:
                self.store.upsert(cid, email, name)
                self.refresh()

    def _edit_selected(self) -> None:
        cid = self._selected_id()
        if not cid:
            return
        customer = self.store.get(cid)
        dialog = CustomerDialog(self, customer)
        if dialog.exec():
            _, email, name = dialog.values()
            if email:
                self.store.upsert(cid, email, name)
                self.refresh()

    def _delete_selected(self) -> None:
        cid = self._selected_id()
        if not cid:
            return
        answer = QMessageBox.question(
            self,
            S.CUST_CONFIRM_DELETE_TITLE,
            S.CUST_CONFIRM_DELETE_MSG.format(id=cid),
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.store.delete(cid)
            self.refresh()

    def _import_csv(self) -> None:
        dialog = ImportDialog(self.store, self)
        if dialog.exec():
            self.refresh()
