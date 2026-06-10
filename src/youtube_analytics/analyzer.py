"""Statistical analysis engine: growth metrics, scoring, trend detection."""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta
from typing import Optional

from .config import Config
from .database import DatabaseManager
from .models import (
    ChannelGrowthMetrics,
    ContentTypeStats,
    DayOfWeekStats,
    GrowthMetrics,
    HourStats,
    MemberStats,
    ReportData,
    VideoScore,
)

logger = logging.getLogger(__name__)

_DAY_NAMES = ["月曜", "火曜", "水曜", "木曜", "金曜", "土曜", "日曜"]


class StatisticalAnalyzer:
    """Computes all statistics and scores from the stored database."""

    def __init__(self, db: DatabaseManager, config: Config) -> None:
        self.db = db
        self.config = config

    # ── Core helpers ──────────────────────────────────────────────────────────

    def _view_delta(
        self, video_id: str, hours_ago: int, reference_time: Optional[datetime] = None
    ) -> int:
        """Return view count increase over the last `hours_ago` hours."""
        now = reference_time or datetime.utcnow()
        then = now - timedelta(hours=hours_ago)
        latest = self.db.get_video_snapshot_at(video_id, now)
        old = self.db.get_video_snapshot_at(video_id, then)
        if not latest or not old:
            return 0
        return max(0, latest["view_count"] - old["view_count"])

    def _safe_rate(self, new_val: float, old_val: float) -> float:
        """Return (new - old) / old as a fraction, or 0 if old is zero."""
        if old_val <= 0:
            return 0.0
        return (new_val - old_val) / old_val

    # ── Momentum index ────────────────────────────────────────────────────────

    def momentum_index(self, video_id: str) -> float:
        """24h view increase / 30-day average daily view increase."""
        now = datetime.utcnow()
        latest = self.db.get_video_snapshot_at(video_id, now)
        ago_24h = self.db.get_video_snapshot_at(video_id, now - timedelta(hours=24))
        ago_30d = self.db.get_video_snapshot_at(video_id, now - timedelta(days=30))

        if not latest or not ago_24h:
            return 0.0
        delta_24h = max(0, latest["view_count"] - ago_24h["view_count"])

        if ago_30d:
            avg_daily = max(1, (latest["view_count"] - ago_30d["view_count"]) / 30)
        else:
            first = self.db.get_video_snapshots(video_id, now - timedelta(days=365), now)
            if len(first) < 2:
                return 0.0
            days_span = max(1, (now - datetime.fromisoformat(first[0]["recorded_at"])).days)
            avg_daily = max(1, (latest["view_count"] - first[0]["view_count"]) / days_span)

        return delta_24h / avg_daily

    # ── Buzz score ────────────────────────────────────────────────────────────

    def buzz_score(self, video_id: str) -> float:
        """Weighted 0-100 score combining view/like/comment 24h growth rates."""
        now = datetime.utcnow()
        latest = self.db.get_video_snapshot_at(video_id, now)
        old = self.db.get_video_snapshot_at(video_id, now - timedelta(hours=24))
        if not latest or not old:
            return 0.0

        view_rate = self._safe_rate(latest["view_count"], old["view_count"])
        like_rate = self._safe_rate(latest["like_count"], old["like_count"])
        comment_rate = self._safe_rate(latest["comment_count"], old["comment_count"])

        raw = view_rate * 0.6 + like_rate * 0.2 + comment_rate * 0.2
        # tanh soft-clip: raw=0.1 → ~47, raw=0.3 → ~90, raw=0.5 → ~98
        return min(100.0, max(0.0, math.tanh(raw * 5) * 100))

    # ── Video scores ──────────────────────────────────────────────────────────

    def compute_video_scores(self, video_id: str, published_at: datetime) -> VideoScore:
        now = datetime.utcnow()
        age_days = max(1, (now - published_at).days)
        latest = self.db.get_video_snapshot_at(video_id, now)

        if not latest:
            return VideoScore(video_id=video_id, scored_at=now)

        total_views = latest["view_count"]

        momentum = self.momentum_index(video_id)
        buzz = self.buzz_score(video_id)

        # Growth score: views / sqrt(age_days), normalised by tanh
        growth_raw = total_views / math.sqrt(age_days)
        growth_score = min(100.0, math.tanh(growth_raw / 50000) * 100)

        # Longtail: age > 30 days AND still getting views
        if age_days > 30:
            delta_7d = self._view_delta(video_id, 7 * 24)
            weekly_avg_expected = total_views / age_days * 7
            longtail_score = min(100.0, max(0.0, (delta_7d / max(1, weekly_avg_expected)) * 50))
        else:
            longtail_score = 0.0

        # Fan acquisition: high like/view ratio suggests engaged new viewers
        like_ratio = latest["like_count"] / max(1, total_views)
        fan_acquisition_score = min(100.0, math.tanh(like_ratio * 20) * 100)

        return VideoScore(
            video_id=video_id,
            scored_at=now,
            momentum_score=min(100.0, momentum * 20),
            growth_score=growth_score,
            buzz_score=buzz,
            longtail_score=longtail_score,
            fan_acquisition_score=fan_acquisition_score,
        )

    # ── Growth metrics for all videos ────────────────────────────────────────

    def compute_growth_metrics(self, channel_id: str) -> list[GrowthMetrics]:
        now = datetime.utcnow()
        videos = self.db.get_all_videos(channel_id)
        results: list[GrowthMetrics] = []

        for row in videos:
            video_id: str = row["video_id"]
            published_at = datetime.fromisoformat(row["published_at"])

            latest = self.db.get_video_snapshot_at(video_id, now)
            if not latest:
                continue

            current_views: int = latest["view_count"]
            current_likes: int = latest["like_count"]
            current_comments: int = latest["comment_count"]

            def delta_h(h: int, _vid: str = video_id, _views: int = current_views) -> int:
                snap = self.db.get_video_snapshot_at(_vid, now - timedelta(hours=h))
                return max(0, _views - snap["view_count"]) if snap else 0

            d1h = delta_h(1)
            d24h = delta_h(24)
            d7d = delta_h(7 * 24)
            d30d = delta_h(30 * 24)

            snap_24h = self.db.get_video_snapshot_at(video_id, now - timedelta(hours=24))
            snap_7d = self.db.get_video_snapshot_at(video_id, now - timedelta(days=7))
            snap_30d = self.db.get_video_snapshot_at(video_id, now - timedelta(days=30))

            gr_24h = self._safe_rate(current_views, snap_24h["view_count"]) if snap_24h else 0.0
            gr_7d = self._safe_rate(current_views, snap_7d["view_count"]) if snap_7d else 0.0
            gr_30d = self._safe_rate(current_views, snap_30d["view_count"]) if snap_30d else 0.0

            momentum = self.momentum_index(video_id)
            buzz = self.buzz_score(video_id)
            age_days = (now - published_at).days

            is_buzzing = momentum >= self.config.momentum_threshold and d24h > 0
            is_longtail = age_days >= 30 and d7d > 0

            hit_score = self._hit_prediction_score(
                video_id, published_at, current_views, current_likes, current_comments, d24h
            )

            results.append(
                GrowthMetrics(
                    video_id=video_id,
                    title=row["title"],
                    video_type=row["video_type"],
                    content_type=row["content_type"],
                    published_at=published_at,
                    current_views=current_views,
                    current_likes=current_likes,
                    current_comments=current_comments,
                    delta_1h=d1h,
                    delta_24h=d24h,
                    delta_7d=d7d,
                    delta_30d=d30d,
                    growth_rate_24h=gr_24h,
                    growth_rate_7d=gr_7d,
                    growth_rate_30d=gr_30d,
                    momentum_index=momentum,
                    buzz_score=buzz,
                    is_buzzing=is_buzzing,
                    is_longtail=is_longtail,
                    hit_prediction_score=hit_score,
                )
            )

        return results

    # ── Hit prediction (rule-based) ───────────────────────────────────────────

    def _hit_prediction_score(
        self,
        video_id: str,
        published_at: datetime,
        views: int,
        likes: int,
        comments: int,
        delta_24h: int,
    ) -> float:
        """Rule-based score 0-100 predicting growth in next 7 days."""
        now = datetime.utcnow()
        age_days = (now - published_at).days
        if age_days > 30:
            return 0.0

        score = 0.0

        # Rule 1: accelerating growth (last 24h > previous 24h)
        snap_48h = self.db.get_video_snapshot_at(video_id, now - timedelta(hours=48))
        snap_24h = self.db.get_video_snapshot_at(video_id, now - timedelta(hours=24))
        if snap_48h and snap_24h:
            prev_delta = snap_24h["view_count"] - snap_48h["view_count"]
            if prev_delta > 0 and delta_24h > prev_delta:
                score += 30.0 * min(2.0, delta_24h / max(1, prev_delta))

        # Rule 2: high engagement ratio
        engagement = (likes + comments) / max(1, views)
        if engagement > 0.05:
            score += 25.0
        elif engagement > 0.02:
            score += 10.0

        # Rule 3: new video (<7 days) getting significant views
        if age_days < 7 and delta_24h > 1000:
            score += 20.0

        # Rule 4: momentum index high
        momentum = self.momentum_index(video_id)
        if momentum > 2.0:
            score += 25.0
        elif momentum > 1.5:
            score += 10.0

        return min(100.0, score)

    # ── Channel growth metrics ────────────────────────────────────────────────

    def compute_channel_metrics(self, channel_id: str, channel_name: str) -> ChannelGrowthMetrics:
        now = datetime.utcnow()
        latest = self.db.get_latest_channel_snapshot(channel_id)
        if not latest:
            return ChannelGrowthMetrics(
                channel_id=channel_id,
                channel_name=channel_name,
                current_subscribers=0,
                current_views=0,
                current_video_count=0,
            )

        def delta_snap(hours: int) -> tuple[int, int]:
            snap = self.db.get_channel_snapshot_at(channel_id, now - timedelta(hours=hours))
            if not snap:
                return 0, 0
            return (
                latest["subscriber_count"] - snap["subscriber_count"],
                latest["view_count"] - snap["view_count"],
            )

        d_sub_24h, d_view_24h = delta_snap(24)
        d_sub_7d, d_view_7d = delta_snap(7 * 24)
        d_sub_30d, d_view_30d = delta_snap(30 * 24)

        snap_30d = self.db.get_channel_snapshot_at(channel_id, now - timedelta(days=30))
        gr_sub_30d = self._safe_rate(latest["subscriber_count"], snap_30d["subscriber_count"]) if snap_30d else 0.0
        gr_view_30d = self._safe_rate(latest["view_count"], snap_30d["view_count"]) if snap_30d else 0.0

        videos = self.db.get_all_videos(channel_id)
        shorts = sum(1 for v in videos if v["video_type"] == "shorts")
        total = max(1, len(videos))

        # Posts per week/month from past 30 days
        cutoff_30d = now - timedelta(days=30)
        recent_videos = [
            v for v in videos
            if datetime.fromisoformat(v["published_at"]) >= cutoff_30d
        ]
        posts_per_month = float(len(recent_videos))
        posts_per_week = posts_per_month / 4.33

        return ChannelGrowthMetrics(
            channel_id=channel_id,
            channel_name=channel_name,
            current_subscribers=latest["subscriber_count"],
            current_views=latest["view_count"],
            current_video_count=latest["video_count"],
            delta_subscribers_24h=d_sub_24h,
            delta_views_24h=d_view_24h,
            delta_subscribers_7d=d_sub_7d,
            delta_views_7d=d_view_7d,
            delta_subscribers_30d=d_sub_30d,
            delta_views_30d=d_view_30d,
            growth_rate_subscribers_30d=gr_sub_30d,
            growth_rate_views_30d=gr_view_30d,
            posts_per_week=posts_per_week,
            posts_per_month=posts_per_month,
            shorts_ratio=shorts / total,
        )

    # ── Growth rankings ───────────────────────────────────────────────────────

    def top_by_delta(
        self, metrics: list[GrowthMetrics], period: str, n: int = 10
    ) -> list[GrowthMetrics]:
        """Return top-N videos sorted by view delta for a given period."""
        key_map = {"1h": "delta_1h", "24h": "delta_24h", "7d": "delta_7d", "30d": "delta_30d"}
        attr = key_map.get(period, "delta_24h")
        return sorted(metrics, key=lambda m: getattr(m, attr), reverse=True)[:n]

    def rising_videos(self, metrics: list[GrowthMetrics], n: int = 10) -> list[GrowthMetrics]:
        """Videos with above-average momentum in the past 24h."""
        buzzing = [m for m in metrics if m.is_buzzing or m.momentum_index >= self.config.buzz_threshold]
        return sorted(buzzing, key=lambda m: m.momentum_index, reverse=True)[:n]

    def declining_videos(
        self, metrics: list[GrowthMetrics], n: int = 10
    ) -> list[GrowthMetrics]:
        """Videos that were growing 7d ago but have slowed in the past 24h."""
        candidates = [
            m for m in metrics
            if m.delta_7d > 1000 and m.delta_24h < m.delta_7d / 14
        ]
        return sorted(candidates, key=lambda m: m.delta_7d - m.delta_24h * 7, reverse=True)[:n]

    def longtail_videos(self, metrics: list[GrowthMetrics], n: int = 10) -> list[GrowthMetrics]:
        return sorted([m for m in metrics if m.is_longtail], key=lambda m: m.delta_7d, reverse=True)[:n]

    def hit_predictions(self, metrics: list[GrowthMetrics], n: int = 10) -> list[GrowthMetrics]:
        candidates = [m for m in metrics if m.hit_prediction_score > 0]
        return sorted(candidates, key=lambda m: m.hit_prediction_score, reverse=True)[:n]

    # ── Content-type breakdown ────────────────────────────────────────────────

    def content_type_stats(self, metrics: list[GrowthMetrics]) -> list[ContentTypeStats]:
        groups: dict[str, list[GrowthMetrics]] = {}
        for m in metrics:
            groups.setdefault(m.content_type, []).append(m)

        result: list[ContentTypeStats] = []
        for ct, items in groups.items():
            total_views = sum(i.current_views for i in items)
            avg_views = total_views / max(1, len(items))
            avg_gr = sum(i.growth_rate_30d for i in items) / max(1, len(items))
            result.append(
                ContentTypeStats(
                    content_type=ct,
                    video_count=len(items),
                    avg_views=avg_views,
                    avg_growth_rate=avg_gr,
                    total_views=total_views,
                )
            )
        return sorted(result, key=lambda x: x.total_views, reverse=True)

    # ── Member mention analysis ───────────────────────────────────────────────

    def member_stats(
        self, channel_id: str, metrics: list[GrowthMetrics]
    ) -> list[MemberStats]:
        if not self.config.member_names:
            return []

        metrics_map = {m.video_id: m for m in metrics}
        result: list[MemberStats] = []

        for name in self.config.member_names:
            name_lower = name.lower()
            matching: list[GrowthMetrics] = []
            for row in self.db.get_all_videos(channel_id):
                text = f"{row['title']} {row['description']}".lower()
                if name_lower in text:
                    m = metrics_map.get(row["video_id"])
                    if m:
                        matching.append(m)
            if not matching:
                continue
            total = sum(m.current_views for m in matching)
            avg_views = total / len(matching)
            avg_gr = sum(m.growth_rate_30d for m in matching) / len(matching)
            result.append(
                MemberStats(
                    member_name=name,
                    video_count=len(matching),
                    avg_views=avg_views,
                    avg_growth_rate=avg_gr,
                    total_views=total,
                )
            )

        return sorted(result, key=lambda x: x.total_views, reverse=True)

    # ── Day-of-week analysis ──────────────────────────────────────────────────

    def day_of_week_stats(
        self, channel_id: str, metrics: list[GrowthMetrics]
    ) -> list[DayOfWeekStats]:
        metrics_map = {m.video_id: m for m in metrics}
        groups: dict[int, list[GrowthMetrics]] = {i: [] for i in range(7)}

        for row in self.db.get_all_videos(channel_id):
            pub = datetime.fromisoformat(row["published_at"])
            # Convert UTC to JST (+9)
            jst_pub = pub + timedelta(hours=9)
            dow = jst_pub.weekday()
            m = metrics_map.get(row["video_id"])
            if m:
                groups[dow].append(m)

        result: list[DayOfWeekStats] = []
        for dow in range(7):
            items = groups[dow]
            if not items:
                result.append(
                    DayOfWeekStats(day_of_week=dow, day_name=_DAY_NAMES[dow], video_count=0, avg_views=0.0, avg_growth_rate=0.0)
                )
                continue
            avg_views = sum(i.current_views for i in items) / len(items)
            avg_gr = sum(i.growth_rate_30d for i in items) / len(items)
            result.append(
                DayOfWeekStats(
                    day_of_week=dow,
                    day_name=_DAY_NAMES[dow],
                    video_count=len(items),
                    avg_views=avg_views,
                    avg_growth_rate=avg_gr,
                )
            )
        return result

    # ── Hour-of-day analysis ──────────────────────────────────────────────────

    def hour_stats(self, channel_id: str, metrics: list[GrowthMetrics]) -> list[HourStats]:
        metrics_map = {m.video_id: m for m in metrics}
        groups: dict[int, list[GrowthMetrics]] = {h: [] for h in range(24)}

        for row in self.db.get_all_videos(channel_id):
            pub = datetime.fromisoformat(row["published_at"])
            jst_pub = pub + timedelta(hours=9)
            hour = jst_pub.hour
            m = metrics_map.get(row["video_id"])
            if m:
                groups[hour].append(m)

        result: list[HourStats] = []
        for hour in range(24):
            items = groups[hour]
            if not items:
                result.append(HourStats(hour=hour, video_count=0, avg_views=0.0, avg_growth_rate=0.0))
                continue
            avg_views = sum(i.current_views for i in items) / len(items)
            avg_gr = sum(i.growth_rate_30d for i in items) / len(items)
            result.append(
                HourStats(
                    hour=hour,
                    video_count=len(items),
                    avg_views=avg_views,
                    avg_growth_rate=avg_gr,
                )
            )
        return result

    # ── Shorts vs regular ─────────────────────────────────────────────────────

    def shorts_vs_regular_growth(self, metrics: list[GrowthMetrics]) -> tuple[float, float]:
        """Return (shorts_avg_growth_rate_30d, regular_avg_growth_rate_30d)."""
        shorts = [m for m in metrics if m.video_type == "shorts"]
        regular = [m for m in metrics if m.video_type == "regular"]
        shorts_gr = sum(m.growth_rate_30d for m in shorts) / max(1, len(shorts))
        regular_gr = sum(m.growth_rate_30d for m in regular) / max(1, len(regular))
        return shorts_gr, regular_gr

    # ── Full report data ──────────────────────────────────────────────────────

    def compile_report_data(self, channel_id: str, channel_name: str) -> ReportData:
        now = datetime.utcnow()
        today = now.strftime("%Y-%m-%d")

        channel_metrics = self.compute_channel_metrics(channel_id, channel_name)
        all_metrics = self.compute_growth_metrics(channel_id)

        shorts_gr, regular_gr = self.shorts_vs_regular_growth(all_metrics)

        return ReportData(
            report_date=today,
            channel_metrics=channel_metrics,
            all_videos=all_metrics,
            rising_videos=self.rising_videos(all_metrics),
            declining_videos=self.declining_videos(all_metrics),
            top_today=self.top_by_delta(all_metrics, "24h", 10),
            top_week=self.top_by_delta(all_metrics, "7d", 10),
            top_month=self.top_by_delta(all_metrics, "30d", 10),
            longtail_videos=self.longtail_videos(all_metrics),
            hit_predictions=self.hit_predictions(all_metrics),
            content_type_stats=self.content_type_stats(all_metrics),
            member_stats=self.member_stats(channel_id, all_metrics),
            day_of_week_stats=self.day_of_week_stats(channel_id, all_metrics),
            hour_stats=self.hour_stats(channel_id, all_metrics),
            shorts_growth_rate=shorts_gr,
            regular_growth_rate=regular_gr,
        )
