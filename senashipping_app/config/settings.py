"""
Basic settings and logging configuration for the senashipping desktop app.
"""

from __future__ import annotations

import logging
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


def _get_resource_root() -> Path:

    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[2]


def _get_user_data_dir(resource_root: Path) -> Path:

    if getattr(sys, "frozen", False):
        exe_path = Path(getattr(sys, "executable", resource_root))
        return exe_path.parent / "senashipping_app_data"
    return resource_root / "senashipping_app_data"


@dataclass(slots=True)
class Settings:
    """Application-level settings."""

    project_root: Path
    data_dir: Path
    db_path: Path

    @classmethod
    def default(cls) -> "Settings":
        resource_root = _get_resource_root()
        data_dir = _get_user_data_dir(resource_root)
        data_dir.mkdir(exist_ok=True)

        db_path = data_dir / "senashipping.db"

        # On first run, seed the writable DB from a bundled default if present.
        if not db_path.exists():
            bundled_db = resource_root / "senashipping_app_data" / "senashipping.db"
            if bundled_db.exists():
                try:
                    shutil.copy2(bundled_db, db_path)
                except OSError:
                    # If copy fails, we fall back to an empty DB at db_path.
                    pass

        return cls(project_root=resource_root, data_dir=data_dir, db_path=db_path)


def init_logging(settings: Settings) -> None:
    """Configure basic logging to console and optional file."""
    log_file = settings.data_dir / "senashipping.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )

    logging.getLogger(__name__).info("Logging initialized. DB at %s", settings.db_path)

