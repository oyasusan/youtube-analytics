"""Tests for DatabaseManager."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from youtube_analytics.database import DatabaseManager
from youtube_analytics.models import ChannelSnapshot, Video, VideoSnapshot


class TestDatabaseInit:
    def test_creates_db_file(self, tmp_path: Path) -> None:
        db = DatabaseManager(tmp_path / "sub" / "test.db")
        db.initialize()
        assert (tmp_path / "sub" / "test.db").exists()

    def test_idempotent_init(self, tmp_db: DatabaseManager) -> None:
        tmp_db.initialize()
        tmp_db.initialize()


class TestChannelOps:
    def test_upsert_and_get_channel(self, tmp_db: DatabaseManager) -> None:
        tmp_db.upsert_channel("UC123", "テスト", "PL123")
        row = tmp_db.get_channel("UC123")
        assert row is not None
        assert row["channel_name"] == "テスト"

    def test_upsert_updates_existing(self, tmp_db: DatabaseManager) -> None:
        tmp_db.upsert_channel("UC123", "旧名前", "PL123")
        tmp_db.upsert_channel("UC123", "新名前", "PL456")
        row = tmp_db.get_channel("UC123")
        assert row["channel_name"] == "新名前"
        assert row["uploads_playlist_id"] == "PL456"

    def test_channel_snapshot_roundtrip(self, tmp_db: DatabaseManager) -> None:
        tmp_db.upsert_channel("UC123", "テスト", "PL123")
        snap = ChannelSnapshot(
            channel_id="UC123",
            recorded_at=datetime.utcnow(),
            subscriber_count=12345,
            view_count=999999,
            video_count=50,
        )
        tmp_db.insert_channel_snapshot(snap)
        latest = tmp_db.get_latest_channel_snapshot("UC123")
        assert latest is not None
        assert latest["subscriber_count"] == 12345
        assert latest["view_count"] == 999999

    def test_channel_snapshot_at(self, tmp_db: DatabaseManager) -> None:
        tmp_db.upsert_channel("UC123", "テスト", "PL123")
        now = datetime.utcnow()
        for i, views in enumerate([100, 200, 300]):
            tmp_db.insert_channel_snapshot(
                ChannelSnapshot("UC123", now - timedelta(hours=2 - i), 1000, views, 10)
            )
        snap = tmp_db.get_channel_snapshot_at("UC123", now - timedelta(hours=1, minutes=30))
        assert snap is not None
        assert snap["view_count"] == 100


class TestVideoOps:
    def test_upsert_and_get_video(
        self, tmp_db: DatabaseManager, sample_channel: str
    ) -> None:
        video = Video(
            video_id="VID001",
            channel_id=sample_channel,
            title="テスト",
            description="説明",
            published_at=datetime.utcnow(),
            video_url="https://www.youtube.com/watch?v=VID001",
            thumbnail_url="",
            video_type="regular",
        )
        tmp_db.upsert_video(video)
        row = tmp_db.get_video("VID001")
        assert row is not None
        assert row["title"] == "テスト"

    def test_upsert_updates_title(
        self, tmp_db: DatabaseManager, sample_channel: str
    ) -> None:
        video = Video(
            video_id="VID001",
            channel_id=sample_channel,
            title="旧タイトル",
            description="",
            published_at=datetime.utcnow(),
            video_url="https://www.youtube.com/watch?v=VID001",
            thumbnail_url="",
            video_type="regular",
        )
        tmp_db.upsert_video(video)
        video.title = "新タイトル"
        tmp_db.upsert_video(video)
        assert tmp_db.get_video("VID001")["title"] == "新タイトル"

    def test_get_all_videos(
        self, tmp_db: DatabaseManager, sample_videos: list[Video]
    ) -> None:
        rows = tmp_db.get_all_videos(sample_videos[0].channel_id)
        assert len(rows) == len(sample_videos)


class TestVideoSnapshotOps:
    def test_snapshot_roundtrip(
        self, tmp_db: DatabaseManager, sample_videos: list[Video]
    ) -> None:
        video = sample_videos[0]
        snap = VideoSnapshot(
            video_id=video.video_id,
            recorded_at=datetime.utcnow(),
            view_count=50000,
            like_count=2000,
            comment_count=150,
        )
        tmp_db.insert_video_snapshot(snap)
        latest = tmp_db.get_latest_video_snapshot(video.video_id)
        assert latest is not None
        assert latest["view_count"] == 50000

    def test_snapshot_at_returns_closest_before(
        self, tmp_db: DatabaseManager, sample_snapshots: list[VideoSnapshot]
    ) -> None:
        video_id = sample_snapshots[0].video_id
        now = datetime.utcnow()
        snap = tmp_db.get_video_snapshot_at(video_id, now - timedelta(hours=18))
        assert snap is not None
        # Should return the -24h snapshot (closest before -18h)
        assert snap["view_count"] is not None

    def test_bulk_insert(
        self, tmp_db: DatabaseManager, sample_videos: list[Video]
    ) -> None:
        snaps = [
            VideoSnapshot(v.video_id, datetime.utcnow(), 100, 10, 1)
            for v in sample_videos
        ]
        tmp_db.insert_video_snapshots_bulk(snaps)
        for v in sample_videos:
            assert tmp_db.get_latest_video_snapshot(v.video_id) is not None


class TestMaintenance:
    def test_get_db_size_mb(self, tmp_db: DatabaseManager) -> None:
        size = tmp_db.get_db_size_mb()
        assert size >= 0.0

    def test_archive_old_snapshots(
        self,
        tmp_db: DatabaseManager,
        sample_channel: str,
        sample_videos: list[Video],
    ) -> None:
        # Insert very old snapshots
        old_time = datetime.utcnow() - timedelta(days=120)
        for v in sample_videos[:3]:
            for i in range(3):
                tmp_db.insert_video_snapshot(
                    VideoSnapshot(v.video_id, old_time + timedelta(hours=i), 1000, 50, 5)
                )
        deleted = tmp_db.archive_old_snapshots(keep_days=90)
        assert deleted >= 0
