"""Tests for Reporter and template rendering."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from youtube_analytics.models import (
    ChannelGrowthMetrics,
    ContentTypeStats,
    DayOfWeekStats,
    GrowthMetrics,
    HourStats,
    ReportData,
)
from youtube_analytics.reporter import Reporter


def make_minimal_report_data() -> ReportData:
    cm = ChannelGrowthMetrics(
        channel_id="UC123",
        channel_name="テストチャンネル",
        current_subscribers=10000,
        current_views=500000,
        current_video_count=50,
        delta_subscribers_24h=100,
        delta_views_24h=5000,
        posts_per_month=8.0,
        shorts_ratio=0.4,
    )
    dummy_video = GrowthMetrics(
        video_id="VID001",
        title="テスト動画",
        video_type="regular",
        content_type="mv",
        published_at=datetime.utcnow(),
        current_views=10000,
        current_likes=400,
        current_comments=50,
        delta_24h=500,
        delta_7d=2000,
        delta_30d=5000,
        growth_rate_30d=0.1,
        momentum_index=1.5,
        buzz_score=65.0,
    )
    return ReportData(
        report_date="2024-01-01",
        channel_metrics=cm,
        all_videos=[dummy_video],
        rising_videos=[dummy_video],
        declining_videos=[],
        top_today=[dummy_video],
        top_week=[dummy_video],
        top_month=[dummy_video],
        longtail_videos=[],
        hit_predictions=[dummy_video],
        content_type_stats=[ContentTypeStats("mv", 1, 10000.0, 0.1, 10000)],
        member_stats=[],
        day_of_week_stats=[DayOfWeekStats(0, "月曜", 5, 8000.0, 0.05)],
        hour_stats=[HourStats(20, 3, 12000.0, 0.08)],
        shorts_growth_rate=0.05,
        regular_growth_rate=0.03,
        ai_analysis="## テスト分析\nこれはAI分析のテストです。",
    )


class TestMarkdownReport:
    def test_generates_file(
        self, tmp_path: Path, test_config: object, tmp_db: object
    ) -> None:
        from youtube_analytics.config import Config
        from youtube_analytics.database import DatabaseManager

        assert isinstance(test_config, Config)
        assert isinstance(tmp_db, DatabaseManager)

        reporter = Reporter(test_config, tmp_db)
        data = make_minimal_report_data()
        path = reporter.generate_markdown(data, "2024-01-01")
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "テストチャンネル" in content
        assert "KPI" in content

    def test_contains_ai_analysis(
        self, tmp_path: Path, test_config: object, tmp_db: object
    ) -> None:
        from youtube_analytics.config import Config
        from youtube_analytics.database import DatabaseManager

        assert isinstance(test_config, Config)
        assert isinstance(tmp_db, DatabaseManager)

        reporter = Reporter(test_config, tmp_db)
        data = make_minimal_report_data()
        path = reporter.generate_markdown(data, "2024-01-01")
        content = path.read_text(encoding="utf-8")
        assert "テスト分析" in content


class TestHtmlReport:
    def test_generates_valid_html(
        self, tmp_path: Path, test_config: object, tmp_db: object
    ) -> None:
        from youtube_analytics.config import Config
        from youtube_analytics.database import DatabaseManager

        assert isinstance(test_config, Config)
        assert isinstance(tmp_db, DatabaseManager)

        reporter = Reporter(test_config, tmp_db)
        data = make_minimal_report_data()
        path = reporter.generate_html(data, "2024-01-01")
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in content
        assert "テストチャンネル" in content
        assert "bootstrap" in content.lower()

    def test_kpi_values_present(
        self, tmp_path: Path, test_config: object, tmp_db: object
    ) -> None:
        from youtube_analytics.config import Config
        from youtube_analytics.database import DatabaseManager

        assert isinstance(test_config, Config)
        assert isinstance(tmp_db, DatabaseManager)

        reporter = Reporter(test_config, tmp_db)
        data = make_minimal_report_data()
        path = reporter.generate_html(data, "2024-01-01")
        content = path.read_text(encoding="utf-8")
        assert "10,000" in content  # subscribers
        assert "500,000" in content  # views
