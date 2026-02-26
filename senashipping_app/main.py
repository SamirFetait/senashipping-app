"""
Application entry point for the senashipping desktop app.

This sets up the Qt application, main window, and high-level navigation.
"""

import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from senashipping_app.views.main_window import MainWindow  # type: ignore[import]
from senashipping_app.config.settings import Settings, init_logging  # type: ignore[import]
from senashipping_app.repositories.database import init_database  # type: ignore[import]


def main() -> None:
    """Bootstraps the senashipping desktop application."""
    # Initialize logging & settings
    settings = Settings.default()
    init_logging(settings)

    # Initialize database (SQLite) and ORM mappings
    init_database(settings.db_path)

    app = QApplication(sys.argv)
    app.setApplicationName("Osama bay app")

    main_window = MainWindow(settings=settings)
    main_window.show()

    exit_code = app.exec()
    # Optionally perform any graceful shutdown / cleanup here
    sys.exit(exit_code)


if __name__ == "__main__":
    # Allow running as a script: `python -m senashipping_app.main`
    # or `python senashipping_app/main.py` (when cwd is project root)
    # Ensure working directory is project root for relative paths
    project_root = Path(__file__).resolve().parents[1]
    if project_root.exists():
        sys.path.insert(0, str(project_root))
    main()

