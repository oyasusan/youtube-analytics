"""Shared pytest fixtures."""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from youtube_analytics.config import Config, reset_config
from youtube_analytics.database import DatabaseManager
from youtube_analytics.models import ChannelSnapshot, Video, VideoSnapshot


@pytest.fixture(autouse=True)
def reset_config_singleton() -> None:
    """Reset config singleton between tests."""
    reset_config()
    yield
    reset_config()


@pytest.fixture
def tmp_db(tmp_path: Path) -> DatabaseManager:
    """Return an initialized in-memory-like DatabaseManager in a temp dir."""
    db = DatabaseManager(tmp_path / "test.db")
    db.initialize()
    return db


@pytest.fixture
def test_config(tmp_path: Path) -> Config:
    return Config(
        project_root=tmp_path,
        youtube_api_key="test_api_key",
        channel_id="UCtest123",
        channel_name="テストチャンネル",
        ai_provider="none",
    )


@pytest.fixture
def sample_channel_id() -> str:
    return "UCtest123"


@pytest.fixture
def sample_channel(tmp_db: DatabaseManager, sample_channel_id: str) -> str:
    tmp_db.upsert_channel(sample_channel_id, "テストチャンネル", "PLtest123")
    return sample_channel_id


@pytest.fixture
def sample_videos(tmp_db: DatabaseManager, sample_channel: str) -> list[Video]:
    videos = [
        Video(
            video_id=f"vid{i:03d}",
            channel_id=sample_channel,
            title=f"テスト動画 #{i:03d}",
            description=f"説明 {i}",
            published_at=datetime.utcnow() - timedelta(days=i),
            video_url=f"https://www.youtube.com/watch?v=vid{i:03d}",
            thumbnail_url="https://example.com/thumb.jpg",
            video_type="shorts" if i % 3 == 0 else "regular",
            content_type="mv" if i % 5 == 0 else "other",
        )
        for i in range(1, 21)
    ]
    for v in videos:
        tmp_db.upsert_video(v)
    return videos


@pytest.fixture
def sample_snapshots(
    tmp_db: DatabaseManager, sample_videos: list[Video]
) -> list[VideoSnapshot]:
    """Create 3 snapshots per video at -24h, -12h, and now."""
    snaps: list[VideoSnapshot] = []
    now = datetime.utcnow()

    for video in sample_videos:
        base_views = (hash(video.video_id) % 10000) + 1000
        for hours_ago, multiplier in [(24, 0.8), (12, 0.9), (0, 1.0)]:
            snap = VideoSnapshot(
                video_id=video.video_id,
                recorded_at=now - timedelta(hours=hours_ago),
                view_count=int(base_views * multiplier),
                like_count=int(base_views * multiplier * 0.04),
                comment_count=int(base_views * multiplier * 0.01),
            )
            snaps.append(snap)

    tmp_db.insert_video_snapshots_bulk(snaps)
    return snaps


@pytest.fixture
def channel_snapshots(tmp_db: DatabaseManager, sample_channel: str) -> None:
    now = datetime.utcnow()
    for hours_ago in [48, 24, 12, 0]:
        snap = ChannelSnapshot(
            channel_id=sample_channel,
            recorded_at=now - timedelta(hours=hours_ago),
            subscriber_count=10000 - hours_ago * 5,
            view_count=500000 + (48 - hours_ago) * 1000,
            video_count=50,
        )
        tmp_db.insert_channel_snapshot(snap)
