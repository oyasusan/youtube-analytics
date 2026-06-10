#!/usr/bin/env python3
"""Hourly live report generator.

Reads from DB only — no YouTube API calls, no matplotlib.
Writes docs/live.html with per-hour deltas for fast feedback.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from jinja2 import Environment, FileSystemLoader, select_autoescape

from youtube_analytics.config import get_config
from youtube_analytics.database import DatabaseManager
from youtube_analytics.logging_config import setup_logging

_JST = timezone(timedelta(hours=9))


@dataclass
class LiveVideoRow:
    video_id: str
    title: str
    video_type: str
    view_count: int
    delta_1h: int
    delta_3h: int
    delta_24h: int


def main() -> int:
    config = get_config()
    logger = setup_logging(config.logs_dir, "hourly_report")

    db = DatabaseManager(config.db_path)

    channel_row = db.get_channel(config.channel_id) if config.channel_id else None
    if not channel_row:
        logger.error("Channel not found in DB. Run collect.py first.")
        return 1

    channel_id: str = channel_row["channel_id"]
    channel_name: str = channel_row["channel_name"]
    now = datetime.utcnow()

    latest_ch = db.get_latest_channel_snapshot(channel_id)
    if not latest_ch:
        logger.error("No channel snapshot found.")
        return 1

    # Subscriber delta: channel-level only (no video-level equivalent)
    prev_ch_1h = db.get_channel_snapshot_at(channel_id, now - timedelta(hours=1))
    prev_ch_24h = db.get_channel_snapshot_at(channel_id, now - timedelta(hours=24))

    def ch_delta(field: str, prev: object) -> int:
        if prev is None:
            return 0
        return int(latest_ch[field]) - int(prev[field])  # type: ignore[index]

    delta_subs_1h = ch_delta("subscriber_count", prev_ch_1h)
    delta_subs_24h = ch_delta("subscriber_count", prev_ch_24h)

    all_videos = db.get_all_videos(channel_id)
    rows: list[LiveVideoRow] = []
    for v in all_videos:
        vid: str = v["video_id"]
        snap_now = db.get_video_snapshot_at(vid, now)
        if not snap_now:
            continue
        cur_views = int(snap_now["view_count"])
        snap_now_id: int = snap_now["id"]

        def _delta(hours: int, _vid: str = vid, _cur: int = cur_views, _sid: int = snap_now_id) -> int:
            s = db.get_video_snapshot_at(_vid, now - timedelta(hours=hours))
            if s and int(s["id"]) != _sid:
                return max(0, _cur - int(s["view_count"]))
            return 0

        rows.append(
            LiveVideoRow(
                video_id=vid,
                title=v["title"],
                video_type=v["video_type"],
                view_count=cur_views,
                delta_1h=_delta(1),
                delta_3h=_delta(3),
                delta_24h=_delta(24),
            )
        )

    # View deltas: sum across all videos (more responsive than channel-level API cache)
    delta_views_1h = sum(r.delta_1h for r in rows)
    delta_views_24h = sum(r.delta_24h for r in rows)

    top_rising = sorted(rows, key=lambda r: r.delta_1h, reverse=True)[:20]
    top_by_views = sorted(rows, key=lambda r: r.view_count, reverse=True)[:20]
    generated_at = datetime.now(_JST).strftime("%Y-%m-%d %H:%M JST")

    env = Environment(
        loader=FileSystemLoader(str(config.templates_dir)),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["format_int"] = lambda v: f"{int(v):,}"
    env.filters["fmt_delta"] = lambda v: (f"+{v:,}" if int(v) > 0 else f"{int(v):,}")

    template = env.get_template("live.html.j2")
    content = template.render(
        channel_name=channel_name,
        latest_ch=latest_ch,
        delta_subs_1h=delta_subs_1h,
        delta_views_1h=delta_views_1h,
        delta_subs_24h=delta_subs_24h,
        delta_views_24h=delta_views_24h,
        top_rising=top_rising,
        top_by_views=top_by_views,
        generated_at=generated_at,
    )

    docs_dir = config.docs_dir
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "live.html").write_text(content, encoding="utf-8")
    logger.info("Live report generated: %s/live.html", docs_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
