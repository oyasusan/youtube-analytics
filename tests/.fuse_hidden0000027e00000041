"""Tests for the YouTube data collector utilities."""

from __future__ import annotations

import pytest

from youtube_analytics.collector import (
    classify_content_type,
    classify_video_type,
    parse_iso_duration,
)


class TestParseIsoDuration:
    def test_seconds_only(self) -> None:
        assert parse_iso_duration("PT30S") == 30

    def test_minutes_and_seconds(self) -> None:
        assert parse_iso_duration("PT1M30S") == 90

    def test_hours_minutes_seconds(self) -> None:
        assert parse_iso_duration("PT1H2M3S") == 3723

    def test_minutes_only(self) -> None:
        assert parse_iso_duration("PT5M") == 300

    def test_empty(self) -> None:
        assert parse_iso_duration("") == 0

    def test_pt0s(self) -> None:
        assert parse_iso_duration("PT0S") == 0


class TestClassifyVideoType:
    def test_short_by_duration(self) -> None:
        assert classify_video_type(60, "", "") == "shorts"

    def test_short_by_duration_under_60(self) -> None:
        assert classify_video_type(45, "", "") == "shorts"

    def test_regular_over_60(self) -> None:
        assert classify_video_type(61, "", "") == "regular"

    def test_short_by_hashtag_title(self) -> None:
        assert classify_video_type(120, "#Shorts テスト", "") == "shorts"

    def test_short_by_hashtag_description(self) -> None:
        assert classify_video_type(120, "", "チェック #shorts") == "shorts"

    def test_long_video(self) -> None:
        assert classify_video_type(600, "Long video", "") == "regular"


class TestClassifyContentType:
    def test_shorts_type(self) -> None:
        assert classify_content_type("テスト", "", "shorts") == "shorts"

    def test_mv_title(self) -> None:
        assert classify_content_type("テスト MV", "", "regular") == "mv"

    def test_mv_official_video(self) -> None:
        assert classify_content_type("Song Official Video", "", "regular") == "mv"

    def test_live_japanese(self) -> None:
        assert classify_content_type("ライブ映像", "", "regular") == "live"

    def test_teaser(self) -> None:
        assert classify_content_type("ティザー映像", "", "regular") == "teaser"

    def test_making(self) -> None:
        assert classify_content_type("メイキング映像", "", "regular") == "making"

    def test_announcement(self) -> None:
        assert classify_content_type("リリース告知", "", "regular") == "announcement"

    def test_other(self) -> None:
        assert classify_content_type("普通の動画タイトル", "", "regular") == "other"

    def test_case_insensitive(self) -> None:
        assert classify_content_type("official mv", "", "regular") == "mv"
