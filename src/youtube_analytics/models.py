"""Data models used throughout the analytics system."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class ChannelSnapshot:
    """Point-in-time snapshot of channel metrics."""

    channel_id: str
    recorded_at: datetime
    subscriber_count: int
    view_count: int
    video_count: int
    id: Optional[int] = None


@dataclass
class Video:
    """Video master record."""

    video_id: str
    channel_id: str
    title: str
    description: str
    published_at: datetime
    video_url: str
    thumbnail_url: str
    video_type: str  # "shorts" | "regular"
    content_type: str = "other"  # mv | live | teaser | making | announcement | shorts | other
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class VideoSnapshot:
    """Point-in-time snapshot of video metrics."""

    video_id: str
    recorded_at: datetime
    view_count: int
    like_count: int
    comment_count: int
    id: Optional[int] = None


@dataclass
class DailyVideoSummary:
    """Aggregated daily metrics for a video."""

    video_id: str
    date: str  # YYYY-MM-DD
    view_count_start: int
    view_count_end: int
    view_count_delta: int
    like_count_start: int
    like_count_end: int
    like_count_delta: int
    comment_count_start: int
    comment_count_end: int
    comment_count_delta: int
    momentum_index: float = 0.0
    buzz_score: float = 0.0
    id: Optional[int] = None


@dataclass
class DailyChannelSummary:
    """Aggregated daily metrics for the channel."""

    channel_id: str
    date: str  # YYYY-MM-DD
    subscriber_count: int
    view_count: int
    video_count: int
    subscriber_delta: int
    view_delta: int
    new_video_count: int
    shorts_count: int
    regular_count: int
    id: Optional[int] = None


@dataclass
class VideoScore:
    """Computed scores for a single video."""

    video_id: str
    scored_at: datetime
    momentum_score: float = 0.0
    growth_score: float = 0.0
    buzz_score: float = 0.0
    longtail_score: float = 0.0
    fan_acquisition_score: float = 0.0


@dataclass
class GrowthMetrics:
    """Growth metrics calculated for a video over different periods."""

    video_id: str
    title: str
    video_type: str
    content_type: str
    published_at: datetime
    current_views: int
    current_likes: int
    current_comments: int
    delta_1h: int = 0
    delta_24h: int = 0
    delta_7d: int = 0
    delta_30d: int = 0
    growth_rate_24h: float = 0.0
    growth_rate_7d: float = 0.0
    growth_rate_30d: float = 0.0
    momentum_index: float = 0.0
    buzz_score: float = 0.0
    is_buzzing: bool = False
    is_longtail: bool = False
    hit_prediction_score: float = 0.0


@dataclass
class ChannelGrowthMetrics:
    """Growth metrics for the channel."""

    channel_id: str
    channel_name: str
    current_subscribers: int
    current_views: int
    current_video_count: int
    delta_subscribers_24h: int = 0
    delta_views_24h: int = 0
    delta_subscribers_7d: int = 0
    delta_views_7d: int = 0
    delta_subscribers_30d: int = 0
    delta_views_30d: int = 0
    growth_rate_subscribers_30d: float = 0.0
    growth_rate_views_30d: float = 0.0
    posts_per_week: float = 0.0
    posts_per_month: float = 0.0
    shorts_ratio: float = 0.0


@dataclass
class ContentTypeStats:
    """Statistics grouped by content type."""

    content_type: str
    video_count: int
    avg_views: float
    avg_growth_rate: float
    total_views: int


@dataclass
class MemberStats:
    """Statistics grouped by member mention."""

    member_name: str
    video_count: int
    avg_views: float
    avg_growth_rate: float
    total_views: int


@dataclass
class DayOfWeekStats:
    """Statistics grouped by day of week."""

    day_of_week: int  # 0=Monday … 6=Sunday
    day_name: str
    video_count: int
    avg_views: float
    avg_growth_rate: float


@dataclass
class HourStats:
    """Statistics grouped by hour of day (JST)."""

    hour: int
    video_count: int
    avg_views: float
    avg_growth_rate: float


@dataclass
class ReportData:
    """All data compiled for report generation."""

    report_date: str
    channel_metrics: ChannelGrowthMetrics
    all_videos: list[GrowthMetrics]
    rising_videos: list[GrowthMetrics]
    declining_videos: list[GrowthMetrics]
    top_today: list[GrowthMetrics]
    top_week: list[GrowthMetrics]
    top_month: list[GrowthMetrics]
    top_by_views: list[GrowthMetrics]
    longtail_videos: list[GrowthMetrics]
    hit_predictions: list[GrowthMetrics]
    content_type_stats: list[ContentTypeStats]
    member_stats: list[MemberStats]
    day_of_week_stats: list[DayOfWeekStats]
    hour_stats: list[HourStats]
    shorts_growth_rate: float
    regular_growth_rate: float
    ai_analysis: str = ""
    graph_paths: dict[str, str] = field(default_factory=dict)
    hourly_chart_labels_json: str = ""
    hourly_chart_deltas_json: str = ""
    hourly_chart_date: str = ""
