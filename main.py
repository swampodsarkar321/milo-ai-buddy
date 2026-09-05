"""Milo — AI Voice Partner. Entry point: `python main.py` (run from nova_assistant/)."""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

# allow `python main.py` from the project folder
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> int:
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
    except ImportError:
        print("PySide6 is not installed. Run: pip install -r requirements.txt")
        return 1

    try:
        from config import AppConfig, DB_PATH
        from memory.database import Database
        from ui.main_window import MainWindow

        config = AppConfig.load()
        db = Database(DB_PATH)

        app = QApplication(sys.argv)
        app.setApplicationName(config.brand.app_name)
        win = MainWindow(config, db)
        win.show()
        return app.exec()
    except Exception:
        traceback.print_exc()
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            a = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None, "Could not start", "Please restart the app.")
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
