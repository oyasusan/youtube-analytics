#!/usr/bin/env python3
"""Hourly data collection entry point.

Fetches channel + all video stats from YouTube API and saves to SQLite.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running as script without package installation
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import logging

from youtube_analytics.config import get_config
from youtube_analytics.collector import YouTubeCollector
from youtube_analytics.database import DatabaseManager
from youtube_analytics.logging_config import setup_logging


def main() -> int:
    config = get_config()
    logger = setup_logging(config.logs_dir, "collect")

    errors = config.validate()
    if errors:
        for err in errors:
            logger.error("Config error: %s", err)
        return 1

    logger.info("=== Hourly collection start ===")

    db = DatabaseManager(config.db_path)
    db.initialize()

    size_mb = db.get_db_size_mb()
    logger.info("DB size: %.1f MB", size_mb)
    if size_mb >= config.db_size_warn_mb:
        logger.warning("DB size (%.1f MB) approaching limit (%d MB)", size_mb, config.db_size_archive_mb)
    if size_mb >= config.db_size_archive_mb:
        logger.warning("DB size exceeded archive threshold; run scripts/maintenance.py")

    collector = YouTubeCollector(config)

    try:
        channel_id, playlist_id, channel_snap, videos, video_snaps = collector.collect_all()
    except Exception as exc:
        logger.error("Collection failed: %s", exc, exc_info=True)
        return 1

    # Persist channel
    db.upsert_channel(channel_id, config.channel_name, playlist_id)
    db.insert_channel_snapshot(channel_snap)
    logger.info(
        "Channel: %s subs=%d views=%d videos=%d",
        channel_id,
        channel_snap.subscriber_count,
        channel_snap.view_count,
        channel_snap.video_count,
    )

    # Persist videos
    for video in videos:
        db.upsert_video(video)

    # Persist snapshots in bulk
    db.insert_video_snapshots_bulk(video_snaps)
    logger.info("Saved %d video snapshots", len(video_snaps))

    logger.info("=== Hourly collection complete ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
