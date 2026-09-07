"""Application entry point for keyTAB 2."""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

if sys.platform == "darwin" and os.path.isdir("/opt/homebrew/lib"):
    existing_library_path = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH")
    os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = ":".join(
        filter(None, ("/opt/homebrew/lib", existing_library_path))
    )

from icons import get_qicon
from ui.main_window import MainWindow
from ui.theme import apply_theme


def main() -> int:
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs)
    app = QApplication(sys.argv)
    app.setApplicationName("keyTAB 2")
    app.setOrganizationName("keyTAB")
    app.setWindowIcon(get_qicon("keyTAB"))
    apply_theme(app, "dark")

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())