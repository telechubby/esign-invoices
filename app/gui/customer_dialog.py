from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLineEdit

from app import strings as S
from app.customers import Customer


class CustomerDialog(QDialog):
    def __init__(self, parent=None, customer: Customer | None = None):
        super().__init__(parent)
        self.setWindowTitle(S.CUST_ADD if customer is None else S.CUST_EDIT)
        self._editing_existing = customer is not None

        self.id_edit = QLineEdit(customer.id if customer else "")
        self.name_edit = QLineEdit(customer.name if customer else "")
        self.email_edit = QLineEdit(customer.email if customer else "")
        if self._editing_existing:
            self.id_edit.setReadOnly(True)

        form = QFormLayout(self)
        form.addRow(S.CUST_TABLE_ID, self.id_edit)
        form.addRow(S.CUST_TABLE_NAME, self.name_edit)
        form.addRow(S.CUST_TABLE_EMAIL, self.email_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> tuple[str, str, str]:
        return (
            self.id_edit.text().strip(),
            self.email_edit.text().strip(),
            self.name_edit.text().strip(),
        )
