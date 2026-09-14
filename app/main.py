from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app.config import load_config
from app.customers import CustomerStore
from app.gui.main_window import MainWindow
from app.paths import customers_db_path, runlog_db_path
from app.runlog import RunLog


def main() -> int:
    app = QApplication(sys.argv)

    config = load_config()
    customers = CustomerStore(customers_db_path())
    run_log = RunLog(runlog_db_path())

    window = MainWindow(config, customers, run_log)
    window.show()

    exit_code = app.exec()
    customers.close()
    run_log.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
