from __future__ import annotations

from PySide6.QtWidgets import QMainWindow, QTabWidget

from app import strings as S
from app.config import AppConfig
from app.customers import CustomerStore
from app.gui.customers_tab import CustomersTab
from app.gui.responsive import screen_fit_size
from app.gui.run_tab import RunTab
from app.gui.settings_tab import SettingsTab
from app.runlog import RunLog


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig, customers: CustomerStore, run_log: RunLog):
        super().__init__()
        self.setWindowTitle(S.APP_TITLE)
        w, h = screen_fit_size(1000, 700)
        self.resize(w, h)

        self.config = config
        self.customers = customers
        self.run_log = run_log

        tabs = QTabWidget()
        self.run_tab = RunTab(config, customers, run_log)
        self.customers_tab = CustomersTab(customers)
        self.settings_tab = SettingsTab(config, on_saved=self._on_settings_saved)

        tabs.addTab(self.run_tab, S.TAB_RUN)
        tabs.addTab(self.customers_tab, S.TAB_CUSTOMERS)
        tabs.addTab(self.settings_tab, S.TAB_SETTINGS)

        self.setCentralWidget(tabs)

    def _on_settings_saved(self) -> None:
        # Run tab reads the shared AppConfig instance live, nothing to push.
        pass
