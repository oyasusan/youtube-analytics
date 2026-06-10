"""Tests for StatisticalAnalyzer."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from youtube_analytics.analyzer import StatisticalAnalyzer
from youtube_analytics.database import DatabaseManager
from youtube_analytics.models import ChannelSnapshot, Video, VideoSnapshot


def make_video(
    db: DatabaseManager,
    channel_id: str,
    video_id: str = "VID001",
    video_type: str = "regular",
    days_old: int = 5,
) -> Video:
    video = Video(
        video_id=video_id,
        channel_id=channel_id,
        title=f"テスト動画 {video_id}",
        description="",
        published_at=datetime.utcnow() - timedelta(days=days_old),
        video_url=f"https://www.youtube.com/watch?v={video_id}",
        thumbnail_url="",
        video_type=video_type,
    )
    db.upsert_video(video)
    return video


def add_snapshots(
    db: DatabaseManager,
    video_id: str,
    *,
    views_24h_ago: int,
    views_now: int,
    likes_now: int = 100,
    comments_now: int = 10,
) -> None:
    now = datetime.utcnow()
    db.insert_video_snapshot(
        VideoSnapshot(video_id, now - timedelta(hours=24), views_24h_ago, likes_now, comments_now)
    )
    db.insert_video_snapshot(
        VideoSnapshot(video_id, now, views_now, likes_now, comments_now)
    )


class TestMomentumIndex:
    def test_growing_video(
        self, tmp_db: DatabaseManager, test_config: object, sample_channel: str
    ) -> None:
        from youtube_analytics.config import Config

        assert isinstance(test_config, Config)
        analyzer = StatisticalAnalyzer(tmp_db, test_config)
        make_video(tmp_db, sample_channel, "VID001", days_old=15)
        now = datetime.utcnow()
        # 30-day snapshot (low base)
        tmp_db.insert_video_snapshot(
            VideoSnapshot("VID001", now - timedelta(days=30), 1000, 40, 4)
        )
        # 24h ago
        tmp_db.insert_video_snapshot(
            VideoSnapshot("VID001", now - timedelta(hours=24), 5000, 200, 20)
        )
        # Now
        tmp_db.insert_video_snapshot(
            VideoSnapshot("VID001", now, 7000, 280, 28)
        )

        mi = analyzer.momentum_index("VID001")
        assert mi > 1.0  # 2000 / (6000/30) = 10

    def test_no_snapshots_returns_zero(
        self, tmp_db: DatabaseManager, test_config: object, sample_channel: str
    ) -> None:
        from youtube_analytics.config import Config

        assert isinstance(test_config, Config)
        analyzer = StatisticalAnalyzer(tmp_db, test_config)
        make_video(tmp_db, sample_channel, "NOXXX")
        mi = analyzer.momentum_index("NOXXX")
        assert mi == 0.0


class TestBuzzScore:
    def test_high_growth_gives_high_score(
        self, tmp_db: DatabaseManager, test_config: object, sample_channel: str
    ) -> None:
        from youtube_analytics.config import Config

        assert isinstance(test_config, Config)
        analyzer = StatisticalAnalyzer(tmp_db, test_config)
        make_video(tmp_db, sample_channel, "VID002")
        add_snapshots(tmp_db, "VID002", views_24h_ago=1000, views_now=5000)
        score = analyzer.buzz_score("VID002")
        assert score > 50.0

    def test_no_growth_gives_low_score(
        self, tmp_db: DatabaseManager, test_config: object, sample_channel: str
    ) -> None:
        from youtube_analytics.config import Config

        assert isinstance(test_config, Config)
        analyzer = StatisticalAnalyzer(tmp_db, test_config)
        make_video(tmp_db, sample_channel, "VID003")
        add_snapshots(tmp_db, "VID003", views_24h_ago=5000, views_now=5001)
        score = analyzer.buzz_score("VID003")
        assert score < 10.0

    def test_score_within_range(
        self, tmp_db: DatabaseManager, test_config: object, sample_channel: str
    ) -> None:
        from youtube_analytics.config import Config

        assert isinstance(test_config, Config)
        analyzer = StatisticalAnalyzer(tmp_db, test_config)
        make_video(tmp_db, sample_channel, "VID004")
        add_snapshots(tmp_db, "VID004", views_24h_ago=100, views_now=100000)
        score = analyzer.buzz_score("VID004")
        assert 0.0 <= score <= 100.0


class TestGrowthMetrics:
    def test_compile_returns_all_videos(
        self,
        tmp_db: DatabaseManager,
        test_config: object,
        sample_channel: str,
        sample_snapshots: list[VideoSnapshot],
    ) -> None:
        from youtube_analytics.config import Config

        assert isinstance(test_config, Config)
        analyzer = StatisticalAnalyzer(tmp_db, test_config)
        metrics = analyzer.compute_growth_metrics(sample_channel)
        assert len(metrics) > 0

    def test_delta_values_are_non_negative(
        self,
        tmp_db: DatabaseManager,
        test_config: object,
        sample_channel: str,
        sample_snapshots: list[VideoSnapshot],
    ) -> None:
        from youtube_analytics.config import Config

        assert isinstance(test_config, Config)
        analyzer = StatisticalAnalyzer(tmp_db, test_config)
        for m in analyzer.compute_growth_metrics(sample_channel):
            assert m.delta_1h >= 0
            assert m.delta_24h >= 0


class TestRankings:
    def test_top_by_delta_24h(
        self,
        tmp_db: DatabaseManager,
        test_config: object,
        sample_channel: str,
        sample_snapshots: list[VideoSnapshot],
    ) -> None:
        from youtube_analytics.config import Config

        assert isinstance(test_config, Config)
        analyzer = StatisticalAnalyzer(tmp_db, test_config)
        metrics = analyzer.compute_growth_metrics(sample_channel)
        top = analyzer.top_by_delta(metrics, "24h", 5)
        assert len(top) <= 5
        if len(top) >= 2:
            assert top[0].delta_24h >= top[1].delta_24h


class TestShortsAnalysis:
    def test_returns_two_floats(
        self,
        tmp_db: DatabaseManager,
        test_config: object,
        sample_channel: str,
        sample_snapshots: list[VideoSnapshot],
    ) -> None:
        from youtube_analytics.config import Config

        assert isinstance(test_config, Config)
        analyzer = StatisticalAnalyzer(tmp_db, test_config)
        metrics = analyzer.compute_growth_metrics(sample_channel)
        shorts_gr, regular_gr = analyzer.shorts_vs_regular_growth(metrics)
        assert isinstance(shorts_gr, float)
        assert isinstance(regular_gr, float)
