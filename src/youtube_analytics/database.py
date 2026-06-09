"""SQLite database layer with schema management and CRUD operations."""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Generator, Optional

from .models import (
    ChannelSnapshot,
    DailyChannelSummary,
    DailyVideoSummary,
    Video,
    VideoScore,
    VideoSnapshot,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

DDL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS channels (
    channel_id TEXT PRIMARY KEY,
    channel_name TEXT NOT NULL,
    uploads_playlist_id TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS channel_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id TEXT NOT NULL REFERENCES channels(channel_id),
    recorded_at DATETIME NOT NULL,
    subscriber_count INTEGER NOT NULL DEFAULT 0,
    view_count INTEGER NOT NULL DEFAULT 0,
    video_count INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS videos (
    video_id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL REFERENCES channels(channel_id),
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    published_at DATETIME NOT NULL,
    video_url TEXT NOT NULL,
    thumbnail_url TEXT NOT NULL DEFAULT '',
    video_type TEXT NOT NULL DEFAULT 'regular',
    content_type TEXT NOT NULL DEFAULT 'other',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS video_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL REFERENCES videos(video_id),
    recorded_at DATETIME NOT NULL,
    view_count INTEGER NOT NULL DEFAULT 0,
    like_count INTEGER NOT NULL DEFAULT 0,
    comment_count INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS daily_video_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL REFERENCES videos(video_id),
    date TEXT NOT NULL,
    view_count_start INTEGER NOT NULL DEFAULT 0,
    view_count_end INTEGER NOT NULL DEFAULT 0,
    view_count_delta INTEGER NOT NULL DEFAULT 0,
    like_count_start INTEGER NOT NULL DEFAULT 0,
    like_count_end INTEGER NOT NULL DEFAULT 0,
    like_count_delta INTEGER NOT NULL DEFAULT 0,
    comment_count_start INTEGER NOT NULL DEFAULT 0,
    comment_count_end INTEGER NOT NULL DEFAULT 0,
    comment_count_delta INTEGER NOT NULL DEFAULT 0,
    momentum_index REAL NOT NULL DEFAULT 0.0,
    buzz_score REAL NOT NULL DEFAULT 0.0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(video_id, date)
);

CREATE TABLE IF NOT EXISTS daily_channel_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id TEXT NOT NULL REFERENCES channels(channel_id),
    date TEXT NOT NULL,
    subscriber_count INTEGER NOT NULL DEFAULT 0,
    view_count INTEGER NOT NULL DEFAULT 0,
    video_count INTEGER NOT NULL DEFAULT 0,
    subscriber_delta INTEGER NOT NULL DEFAULT 0,
    view_delta INTEGER NOT NULL DEFAULT 0,
    new_video_count INTEGER NOT NULL DEFAULT 0,
    shorts_count INTEGER NOT NULL DEFAULT 0,
    regular_count INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(channel_id, date)
);

CREATE TABLE IF NOT EXISTS video_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL REFERENCES videos(video_id),
    scored_at DATETIME NOT NULL,
    momentum_score REAL NOT NULL DEFAULT 0.0,
    growth_score REAL NOT NULL DEFAULT 0.0,
    buzz_score REAL NOT NULL DEFAULT 0.0,
    longtail_score REAL NOT NULL DEFAULT 0.0,
    fan_acquisition_score REAL NOT NULL DEFAULT 0.0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ai_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analyzed_at DATETIME NOT NULL,
    analysis_type TEXT NOT NULL,
    model_used TEXT NOT NULL DEFAULT '',
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    response TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS report_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_at DATETIME NOT NULL,
    report_type TEXT NOT NULL,
    report_date TEXT NOT NULL,
    file_path_md TEXT NOT NULL DEFAULT '',
    file_path_html TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_channel_snapshots_channel_recorded
    ON channel_snapshots(channel_id, recorded_at);
CREATE INDEX IF NOT EXISTS idx_video_snapshots_video_recorded
    ON video_snapshots(video_id, recorded_at);
CREATE INDEX IF NOT EXISTS idx_video_snapshots_recorded
    ON video_snapshots(recorded_at);
CREATE INDEX IF NOT EXISTS idx_videos_channel_id
    ON videos(channel_id);
CREATE INDEX IF NOT EXISTS idx_videos_published_at
    ON videos(published_at);
CREATE INDEX IF NOT EXISTS idx_daily_video_summaries_date
    ON daily_video_summaries(date);
"""


class DatabaseManager:
    """Manages all SQLite operations for the analytics system."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path), detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        """Create schema and apply initial version."""
        with self.connect() as conn:
            conn.executescript(DDL)
            row = conn.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()
            if row is None:
                conn.execute("INSERT INTO schema_version(version) VALUES(?)", (SCHEMA_VERSION,))
        logger.info("Database initialized at %s", self.db_path)

    # ── Channel ──────────────────────────────────────────────────────────────

    def upsert_channel(self, channel_id: str, channel_name: str, uploads_playlist_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO channels(channel_id, channel_name, uploads_playlist_id, updated_at)
                VALUES(?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(channel_id) DO UPDATE SET
                    channel_name = excluded.channel_name,
                    uploads_playlist_id = excluded.uploads_playlist_id,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (channel_id, channel_name, uploads_playlist_id),
            )

    def get_channel(self, channel_id: str) -> Optional[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM channels WHERE channel_id = ?", (channel_id,)
            ).fetchone()

    def insert_channel_snapshot(self, snap: ChannelSnapshot) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO channel_snapshots
                    (channel_id, recorded_at, subscriber_count, view_count, video_count)
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    snap.channel_id,
                    snap.recorded_at.isoformat(),
                    snap.subscriber_count,
                    snap.view_count,
                    snap.video_count,
                ),
            )

    def get_channel_snapshots(
        self, channel_id: str, since: datetime, until: Optional[datetime] = None
    ) -> list[sqlite3.Row]:
        until = until or datetime.utcnow()
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM channel_snapshots
                WHERE channel_id = ? AND recorded_at BETWEEN ? AND ?
                ORDER BY recorded_at ASC
                """,
                (channel_id, since.isoformat(), until.isoformat()),
            ).fetchall()

    def get_latest_channel_snapshot(self, channel_id: str) -> Optional[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM channel_snapshots
                WHERE channel_id = ?
                ORDER BY recorded_at DESC LIMIT 1
                """,
                (channel_id,),
            ).fetchone()

    def get_channel_snapshot_at(
        self, channel_id: str, at: datetime
    ) -> Optional[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM channel_snapshots
                WHERE channel_id = ? AND recorded_at <= ?
                ORDER BY recorded_at DESC LIMIT 1
                """,
                (channel_id, at.isoformat()),
            ).fetchone()

    # ── Videos ───────────────────────────────────────────────────────────────

    def upsert_video(self, video: Video) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO videos
                    (video_id, channel_id, title, description, published_at,
                     video_url, thumbnail_url, video_type, content_type, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(video_id) DO UPDATE SET
                    title = excluded.title,
                    description = excluded.description,
                    thumbnail_url = excluded.thumbnail_url,
                    video_type = excluded.video_type,
                    content_type = excluded.content_type,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    video.video_id,
                    video.channel_id,
                    video.title,
                    video.description,
                    video.published_at.isoformat(),
                    video.video_url,
                    video.thumbnail_url,
                    video.video_type,
                    video.content_type,
                ),
            )

    def get_all_videos(self, channel_id: str) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM videos WHERE channel_id = ? ORDER BY published_at DESC",
                (channel_id,),
            ).fetchall()

    def get_video(self, video_id: str) -> Optional[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM videos WHERE video_id = ?", (video_id,)
            ).fetchone()

    # ── Video snapshots ───────────────────────────────────────────────────────

    def insert_video_snapshot(self, snap: VideoSnapshot) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO video_snapshots(video_id, recorded_at, view_count, like_count, comment_count)
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    snap.video_id,
                    snap.recorded_at.isoformat(),
                    snap.view_count,
                    snap.like_count,
                    snap.comment_count,
                ),
            )

    def insert_video_snapshots_bulk(self, snaps: list[VideoSnapshot]) -> None:
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO video_snapshots(video_id, recorded_at, view_count, like_count, comment_count)
                VALUES(?, ?, ?, ?, ?)
                """,
                [
                    (s.video_id, s.recorded_at.isoformat(), s.view_count, s.like_count, s.comment_count)
                    for s in snaps
                ],
            )

    def get_video_snapshot_at(
        self, video_id: str, at: datetime
    ) -> Optional[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM video_snapshots
                WHERE video_id = ? AND recorded_at <= ?
                ORDER BY recorded_at DESC LIMIT 1
                """,
                (video_id, at.isoformat()),
            ).fetchone()

    def get_latest_video_snapshot(self, video_id: str) -> Optional[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM video_snapshots
                WHERE video_id = ?
                ORDER BY recorded_at DESC LIMIT 1
                """,
                (video_id,),
            ).fetchone()

    def get_video_snapshots(
        self, video_id: str, since: datetime, until: Optional[datetime] = None
    ) -> list[sqlite3.Row]:
        until = until or datetime.utcnow()
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM video_snapshots
                WHERE video_id = ? AND recorded_at BETWEEN ? AND ?
                ORDER BY recorded_at ASC
                """,
                (video_id, since.isoformat(), until.isoformat()),
            ).fetchall()

    # ── Daily summaries ───────────────────────────────────────────────────────

    def upsert_daily_video_summary(self, summary: DailyVideoSummary) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO daily_video_summaries
                    (video_id, date, view_count_start, view_count_end, view_count_delta,
                     like_count_start, like_count_end, like_count_delta,
                     comment_count_start, comment_count_end, comment_count_delta,
                     momentum_index, buzz_score)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(video_id, date) DO UPDATE SET
                    view_count_end = excluded.view_count_end,
                    view_count_delta = excluded.view_count_delta,
                    like_count_end = excluded.like_count_end,
                    like_count_delta = excluded.like_count_delta,
                    comment_count_end = excluded.comment_count_end,
                    comment_count_delta = excluded.comment_count_delta,
                    momentum_index = excluded.momentum_index,
                    buzz_score = excluded.buzz_score
                """,
                (
                    summary.video_id,
                    summary.date,
                    summary.view_count_start,
                    summary.view_count_end,
                    summary.view_count_delta,
                    summary.like_count_start,
                    summary.like_count_end,
                    summary.like_count_delta,
                    summary.comment_count_start,
                    summary.comment_count_end,
                    summary.comment_count_delta,
                    summary.momentum_index,
                    summary.buzz_score,
                ),
            )

    def upsert_daily_channel_summary(self, summary: DailyChannelSummary) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO daily_channel_summaries
                    (channel_id, date, subscriber_count, view_count, video_count,
                     subscriber_delta, view_delta, new_video_count, shorts_count, regular_count)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(channel_id, date) DO UPDATE SET
                    subscriber_count = excluded.subscriber_count,
                    view_count = excluded.view_count,
                    video_count = excluded.video_count,
                    subscriber_delta = excluded.subscriber_delta,
                    view_delta = excluded.view_delta,
                    new_video_count = excluded.new_video_count,
                    shorts_count = excluded.shorts_count,
                    regular_count = excluded.regular_count
                """,
                (
                    summary.channel_id,
                    summary.date,
                    summary.subscriber_count,
                    summary.view_count,
                    summary.video_count,
                    summary.subscriber_delta,
                    summary.view_delta,
                    summary.new_video_count,
                    summary.shorts_count,
                    summary.regular_count,
                ),
            )

    def get_daily_channel_summaries(
        self, channel_id: str, days: int = 30
    ) -> list[sqlite3.Row]:
        since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM daily_channel_summaries
                WHERE channel_id = ? AND date >= ?
                ORDER BY date ASC
                """,
                (channel_id, since),
            ).fetchall()

    def get_daily_video_summaries_for_date(self, date: str) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM daily_video_summaries WHERE date = ?", (date,)
            ).fetchall()

    # ── Scores ────────────────────────────────────────────────────────────────

    def insert_video_score(self, score: VideoScore) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO video_scores
                    (video_id, scored_at, momentum_score, growth_score, buzz_score,
                     longtail_score, fan_acquisition_score)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    score.video_id,
                    score.scored_at.isoformat(),
                    score.momentum_score,
                    score.growth_score,
                    score.buzz_score,
                    score.longtail_score,
                    score.fan_acquisition_score,
                ),
            )

    # ── AI analyses ───────────────────────────────────────────────────────────

    def insert_ai_analysis(
        self,
        analysis_type: str,
        model_used: str,
        response: str,
        prompt_tokens: int = 0,
        metadata: Optional[dict[str, object]] = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO ai_analyses
                    (analyzed_at, analysis_type, model_used, prompt_tokens, response, metadata)
                VALUES(CURRENT_TIMESTAMP, ?, ?, ?, ?, ?)
                """,
                (
                    analysis_type,
                    model_used,
                    prompt_tokens,
                    response,
                    json.dumps(metadata or {}),
                ),
            )

    def get_latest_ai_analysis(self, analysis_type: str) -> Optional[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM ai_analyses
                WHERE analysis_type = ?
                ORDER BY analyzed_at DESC LIMIT 1
                """,
                (analysis_type,),
            ).fetchone()

    # ── Report history ────────────────────────────────────────────────────────

    def insert_report_history(
        self,
        report_type: str,
        report_date: str,
        file_path_md: str,
        file_path_html: str,
        summary: str,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO report_history
                    (generated_at, report_type, report_date, file_path_md, file_path_html, summary)
                VALUES(CURRENT_TIMESTAMP, ?, ?, ?, ?, ?)
                """,
                (report_type, report_date, file_path_md, file_path_html, summary),
            )

    def get_recent_reports(self, limit: int = 30) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM report_history
                ORDER BY generated_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()

    # ── Maintenance ───────────────────────────────────────────────────────────

    def get_db_size_mb(self) -> float:
        return self.db_path.stat().st_size / (1024 * 1024) if self.db_path.exists() else 0.0

    def archive_old_snapshots(self, keep_days: int = 90) -> int:
        """Compress snapshots older than keep_days into daily summaries, return rows deleted."""
        cutoff = (datetime.utcnow() - timedelta(days=keep_days)).isoformat()
        with self.connect() as conn:
            result = conn.execute(
                "DELETE FROM video_snapshots WHERE recorded_at < ? AND id IN ("
                "  SELECT id FROM video_snapshots WHERE recorded_at < ?"
                "  GROUP BY video_id, date(recorded_at)"
                "  HAVING id != MAX(id)"
                ")",
                (cutoff, cutoff),
            )
            deleted = result.rowcount
        logger.info("Archived %d old video snapshots", deleted)
        return deleted

    def archive_old_channel_snapshots(self, keep_days: int = 90) -> int:
        cutoff = (datetime.utcnow() - timedelta(days=keep_days)).isoformat()
        with self.connect() as conn:
            result = conn.execute(
                "DELETE FROM channel_snapshots WHERE recorded_at < ? AND id IN ("
                "  SELECT id FROM channel_snapshots WHERE recorded_at < ?"
                "  GROUP BY channel_id, date(recorded_at)"
                "  HAVING id != MAX(id)"
                ")",
                (cutoff, cutoff),
            )
            deleted = result.rowcount
        logger.info("Archived %d old channel snapshots", deleted)
        return deleted

    def vacuum(self) -> None:
        with self.connect() as conn:
            conn.execute("VACUUM")
        logger.info("Database VACUUM completed")
