#!/usr/bin/env python3
"""Database maintenance: archive old snapshots and VACUUM if needed."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import logging

from youtube_analytics.config import get_config
from youtube_analytics.database import DatabaseManager
from youtube_analytics.logging_config import setup_logging


def main() -> int:
    config = get_config()
    logger = setup_logging(config.logs_dir, "maintenance")

    logger.info("=== Maintenance start ===")

    db = DatabaseManager(config.db_path)
    if not config.db_path.exists():
        logger.error("Database not found: %s", config.db_path)
        return 1

    size_before = db.get_db_size_mb()
    logger.info("DB size before: %.1f MB", size_before)

    if size_before >= config.db_size_archive_mb:
        logger.info("Archiving old snapshots (keep last 90 days)...")
        video_deleted = db.archive_old_snapshots(keep_days=90)
        channel_deleted = db.archive_old_channel_snapshots(keep_days=90)
        logger.info("Archived: %d video rows, %d channel rows", video_deleted, channel_deleted)

        logger.info("Running VACUUM...")
        db.vacuum()

    size_after = db.get_db_size_mb()
    logger.info("DB size after: %.1f MB (saved %.1f MB)", size_after, size_before - size_after)
    logger.info("=== Maintenance complete ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
