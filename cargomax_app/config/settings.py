"""
Basic settings and logging configuration for the senashipping desktop app.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class Settings:
    """Application-level settings."""

    project_root: Path
    data_dir: Path
    db_path: Path

    @classmethod
    def default(cls) -> "Settings":
        """Create default settings based on the current file location."""
        project_root = Path(__file__).resolve().parents[2]
        data_dir = project_root / "senashipping_app_data"
        data_dir.mkdir(exist_ok=True)
        db_path = data_dir / "senashipping.db"
        return cls(project_root=project_root, data_dir=data_dir, db_path=db_path)


def init_logging(settings: Settings) -> None:
    """Configure basic logging to console and optional file."""
    log_file = settings.data_dir / "senashipping.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )

    logging.getLogger(__name__).info("Logging initialized. DB at %s", settings.db_path)

