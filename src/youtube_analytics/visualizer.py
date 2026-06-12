"""Matplotlib-based chart generation for channel and video analytics."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import matplotlib
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

matplotlib.use("Agg")
matplotlib.rcParams["font.family"] = ["DejaVu Sans", "IPAexGothic", "Noto Sans CJK JP", "sans-serif"]
matplotlib.rcParams["axes.unicode_minus"] = False

from .database import DatabaseManager  # noqa: E402
from .models import DayOfWeekStats, GrowthMetrics, HourStats  # noqa: E402

logger = logging.getLogger(__name__)

_PALETTE = ["#4C9BE8", "#E8744C", "#4CE87A", "#E8D44C", "#9B4CE8", "#4CE8D4", "#E84C9B"]
_DAY_LABELS = ["月", "火", "水", "木", "金", "土", "日"]


class Visualizer:
    """Generates PNG charts and saves them to the graphs directory."""

    def __init__(self, db: DatabaseManager, graphs_dir: Path) -> None:
        self.db = db
        self.graphs_dir = graphs_dir
        self.graphs_dir.mkdir(parents=True, exist_ok=True)

    def _save(self, fig: plt.Figure, name: str) -> str:
        path = self.graphs_dir / name
        fig.savefig(str(path), dpi=120, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        logger.debug("Saved chart: %s", path)
        return str(path)

    # ── Channel view trend ────────────────────────────────────────────────────

    def channel_views_trend(self, channel_id: str, days: int = 30) -> Optional[str]:
        since = datetime.utcnow() - timedelta(days=days)
        rows = self.db.get_channel_snapshots(channel_id, since)
        if len(rows) < 2:
            return None

        dates = [datetime.fromisoformat(r["recorded_at"]) for r in rows]
        views = [r["view_count"] for r in rows]

        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(dates, views, color=_PALETTE[0], linewidth=2)
        ax.fill_between(dates, views, alpha=0.15, color=_PALETTE[0])
        ax.set_title(f"総再生数推移（過去{days}日）", fontsize=13, pad=10)
        ax.set_xlabel("日付")
        ax.set_ylabel("総再生数")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=max(1, days // 10)))
        fig.autofmt_xdate()
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
        ax.grid(axis="y", alpha=0.3)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        return self._save(fig, "channel_views_trend.png")

    # ── Today's hourly view delta (0–23h JST) ────────────────────────────────

    def channel_growth_rate(self, channel_id: str, days: int = 30) -> Optional[str]:
        """Hourly view delta for today (JST 0:00–23:00), replacing the old 30-day bar chart."""
        jst_offset = timedelta(hours=9)
        now_utc = datetime.utcnow()
        now_jst = now_utc + jst_offset

        # JST midnight → UTC
        jst_midnight = now_jst.replace(hour=0, minute=0, second=0, microsecond=0)
        utc_midnight = jst_midnight - jst_offset

        hours: list[int] = []
        deltas: list[Optional[int]] = []

        for h in range(24):
            snap_end_utc = utc_midnight + timedelta(hours=h + 1)
            snap_start_utc = utc_midnight + timedelta(hours=h)
            # Only compute for hours that have already passed
            if snap_start_utc > now_utc:
                break
            snap_end = self.db.get_channel_snapshot_at(channel_id, snap_end_utc)
            snap_start = self.db.get_channel_snapshot_at(channel_id, snap_start_utc)
            hours.append(h)
            if snap_end and snap_start and snap_end["id"] != snap_start["id"]:
                deltas.append(max(0, int(snap_end["view_count"]) - int(snap_start["view_count"])))
            else:
                deltas.append(0)

        if not hours:
            return None

        fig, ax = plt.subplots(figsize=(10, 4))
        colors = [_PALETTE[0] if (d or 0) > 0 else "#cccccc" for d in deltas]
        ax.bar(hours, [d or 0 for d in deltas], color=colors, width=0.8)
        date_str = now_jst.strftime("%Y-%m-%d")
        ax.set_title(f"時間別再生数増加（{date_str} JST）", fontsize=13, pad=10)
        ax.set_xlabel("時刻（JST）")
        ax.set_ylabel("再生数増加（回/時）")
        ax.set_xticks(range(0, 24))
        ax.set_xticklabels([f"{h}時" for h in range(24)], fontsize=7, rotation=45)
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
        ax.grid(axis="y", alpha=0.3)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        return self._save(fig, "channel_growth_rate.png")

    # ── Posting frequency ─────────────────────────────────────────────────────

    def posting_frequency(self, channel_id: str, weeks: int = 12) -> Optional[str]:
        since = datetime.utcnow() - timedelta(weeks=weeks)
        videos = self.db.get_all_videos(channel_id)
        recent = [
            datetime.fromisoformat(v["published_at"])
            for v in videos
            if datetime.fromisoformat(v["published_at"]) >= since
        ]
        if not recent:
            return None

        df = pd.DataFrame({"date": recent})
        df["week"] = df["date"].dt.to_period("W").dt.start_time
        weekly = df.groupby("week").size().reset_index(name="count")

        fig, ax = plt.subplots(figsize=(10, 4))
        ax.bar(weekly["week"], weekly["count"], color=_PALETTE[2], width=5.0)
        ax.set_title(f"週別投稿本数（過去{weeks}週）", fontsize=13, pad=10)
        ax.set_xlabel("週")
        ax.set_ylabel("投稿数")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
        fig.autofmt_xdate()
        ax.grid(axis="y", alpha=0.3)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        return self._save(fig, "posting_frequency.png")

    # ── Video growth comparison (top N) ───────────────────────────────────────

    def video_growth_comparison(
        self, metrics: list[GrowthMetrics], top_n: int = 10
    ) -> Optional[str]:
        top = sorted(metrics, key=lambda m: m.delta_30d, reverse=True)[:top_n]
        if not top:
            return None

        labels = [f"{m.title[:25]}..." if len(m.title) > 25 else m.title for m in top]
        values = [m.delta_30d for m in top]
        colors = [_PALETTE[0] if m.video_type == "shorts" else _PALETTE[1] for m in top]

        fig, ax = plt.subplots(figsize=(10, max(4, top_n * 0.45)))
        ax.barh(range(len(labels)), values, color=colors)
        ax.set_yticks(range(len(labels)))
        ax.set_yticklabels(labels, fontsize=9)
        ax.set_title("動画別30日間再生増加 TOP10", fontsize=13, pad=10)
        ax.set_xlabel("30日間再生増加数（回）")
        ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda x, _: f"{int(x):,}"))

        # Legend
        from matplotlib.patches import Patch
        legend_elements = [
            Patch(color=_PALETTE[0], label="Shorts"),
            Patch(color=_PALETTE[1], label="通常動画"),
        ]
        ax.legend(handles=legend_elements, loc="lower right", fontsize=8)
        ax.grid(axis="x", alpha=0.3)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.invert_yaxis()
        return self._save(fig, "video_growth_comparison.png")

    # ── Shorts ratio trend ────────────────────────────────────────────────────

    def shorts_ratio_trend(self, channel_id: str, days: int = 30) -> Optional[str]:
        summaries = self.db.get_daily_channel_summaries(channel_id, days)
        if len(summaries) < 2:
            return None

        df = pd.DataFrame(
            [(r["date"], r["shorts_count"], r["regular_count"]) for r in summaries],
            columns=["date", "shorts", "regular"],
        )
        df["date"] = pd.to_datetime(df["date"])
        df["total"] = df["shorts"] + df["regular"]
        df = df[df["total"] > 0]
        if df.empty:
            return None
        df["shorts_pct"] = df["shorts"] / df["total"] * 100

        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(df["date"], df["shorts_pct"], color=_PALETTE[0], linewidth=2, marker="o", markersize=3)
        ax.fill_between(df["date"], df["shorts_pct"], alpha=0.15, color=_PALETTE[0])
        ax.set_title("Shorts比率推移", fontsize=13, pad=10)
        ax.set_xlabel("日付")
        ax.set_ylabel("Shorts比率 (%)")
        ax.set_ylim(0, 100)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
        fig.autofmt_xdate()
        ax.grid(alpha=0.3)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        return self._save(fig, "shorts_ratio_trend.png")

    # ── Day-of-week analysis ──────────────────────────────────────────────────

    def day_of_week_analysis(self, stats: list[DayOfWeekStats]) -> Optional[str]:
        if not stats:
            return None

        labels = [s.day_name for s in stats]
        views = [s.avg_views for s in stats]
        counts = [s.video_count for s in stats]

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4))

        ax1.bar(labels, views, color=_PALETTE[3])
        ax1.set_title("曜日別 平均再生数", fontsize=12, pad=8)
        ax1.set_ylabel("平均再生数")
        ax1.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
        ax1.grid(axis="y", alpha=0.3)
        ax1.spines["top"].set_visible(False)
        ax1.spines["right"].set_visible(False)

        ax2.bar(labels, counts, color=_PALETTE[4])
        ax2.set_title("曜日別 投稿本数", fontsize=12, pad=8)
        ax2.set_ylabel("投稿本数")
        ax2.grid(axis="y", alpha=0.3)
        ax2.spines["top"].set_visible(False)
        ax2.spines["right"].set_visible(False)

        fig.suptitle("曜日別分析", fontsize=14, y=1.02)
        return self._save(fig, "day_of_week_analysis.png")

    # ── Hour analysis ─────────────────────────────────────────────────────────

    def hour_analysis(self, stats: list[HourStats]) -> Optional[str]:
        if not stats:
            return None

        hours = [s.hour for s in stats]
        views = [s.avg_views for s in stats]

        fig, ax = plt.subplots(figsize=(12, 4))
        ax.bar(hours, views, color=_PALETTE[5], width=0.8)
        ax.set_title("時間帯別 平均再生数（JST）", fontsize=13, pad=10)
        ax.set_xlabel("投稿時刻（時）")
        ax.set_ylabel("平均再生数")
        ax.set_xticks(range(0, 24, 2))
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
        ax.grid(axis="y", alpha=0.3)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        return self._save(fig, "hour_analysis.png")

    # ── Growth rate ranking ───────────────────────────────────────────────────

    def growth_rate_ranking(
        self, metrics: list[GrowthMetrics], top_n: int = 20
    ) -> Optional[str]:
        top = sorted(metrics, key=lambda m: m.growth_rate_30d, reverse=True)[:top_n]
        top = [m for m in top if m.growth_rate_30d > 0]
        if not top:
            return None

        labels = [f"{m.title[:22]}..." if len(m.title) > 22 else m.title for m in top]
        values = [m.growth_rate_30d * 100 for m in top]
        colors = [_PALETTE[0] if m.video_type == "shorts" else _PALETTE[1] for m in top]

        fig, ax = plt.subplots(figsize=(10, max(4, len(top) * 0.4)))
        ax.barh(range(len(labels)), values, color=colors)
        ax.set_yticks(range(len(labels)))
        ax.set_yticklabels(labels, fontsize=9)
        ax.set_title("30日間成長率ランキング TOP20 (%)", fontsize=13, pad=10)
        ax.set_xlabel("30日成長率 (%)")
        ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda x, _: f"{x:.1f}%"))

        from matplotlib.patches import Patch
        legend_elements = [
            Patch(color=_PALETTE[0], label="Shorts"),
            Patch(color=_PALETTE[1], label="通常動画"),
        ]
        ax.legend(handles=legend_elements, loc="lower right", fontsize=8)
        ax.grid(axis="x", alpha=0.3)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.invert_yaxis()
        return self._save(fig, "growth_rate_ranking.png")

    # ── Generate all charts ───────────────────────────────────────────────────

    def generate_all(
        self,
        channel_id: str,
        metrics: list[GrowthMetrics],
        day_stats: list[DayOfWeekStats],
        hour_stats: list[HourStats],
    ) -> dict[str, str]:
        """Generate all charts, return dict mapping name → file path."""
        paths: dict[str, str] = {}

        charts = [
            ("channel_views_trend", lambda: self.channel_views_trend(channel_id)),
            ("channel_growth_rate", lambda: self.channel_growth_rate(channel_id)),
            ("posting_frequency", lambda: self.posting_frequency(channel_id)),
            ("video_growth_comparison", lambda: self.video_growth_comparison(metrics)),
            ("shorts_ratio_trend", lambda: self.shorts_ratio_trend(channel_id)),
            ("day_of_week_analysis", lambda: self.day_of_week_analysis(day_stats)),
            ("hour_analysis", lambda: self.hour_analysis(hour_stats)),
            ("growth_rate_ranking", lambda: self.growth_rate_ranking(metrics)),
        ]

        for name, fn in charts:
            try:
                path = fn()
                if path:
                    paths[name] = path
            except Exception as exc:
                logger.warning("Failed to generate chart '%s': %s", name, exc)

        logger.info("Generated %d charts", len(paths))
        return paths
