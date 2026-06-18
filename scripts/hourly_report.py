#!/usr/bin/env python3
"""Hourly live report generator.

Reads from DB only — no YouTube API calls, no matplotlib.
Writes docs/live.html with per-hour deltas for fast feedback.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from jinja2 import Environment, FileSystemLoader, select_autoescape

from youtube_analytics.config import get_config
from youtube_analytics.database import DatabaseManager
from youtube_analytics.logging_config import setup_logging


def _generate_live_comment(
    api_key: str,
    base_url: str,
    model: str,
    channel_name: str,
    subscribers: int,
    delta_views_1h: int,
    top_rising: list[LiveVideoRow],
) -> str:
    """Call Groq/OpenAI-compatible API for a 2-3 line live comment. Returns '' on failure."""
    if not api_key:
        return ""
    try:
        from openai import OpenAI

        top3 = "\n".join(
            f"{i + 1}. 「{v.title[:30]}」 +{v.delta_1h:,}回"
            for i, v in enumerate(top_rising[:3])
            if (v.delta_1h or 0) > 0
        ) or "（目立った変化なし）"

        prompt = (
            f"チャンネル「{channel_name}」の直近1時間のデータ：\n"
            f"登録者: {subscribers:,}人\n"
            f"過去1時間の総再生増加: +{delta_views_1h:,}回\n\n"
            f"急上昇動画（+1h）:\n{top3}\n\n"
            f"この状況をチャンネル運営者向けに2〜3文で簡潔にコメントしてください。"
            f"数字に基づいて具体的に。"
        )
        client = OpenAI(api_key=api_key, base_url=base_url)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=250,
            temperature=0.7,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception:
        return ""

_JST = timezone(timedelta(hours=9))


@dataclass
class LiveVideoRow:
    video_id: str
    title: str
    video_type: str
    view_count: int
    delta_1h: int | None
    delta_3h: int | None
    delta_24h: int | None


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
    now = datetime.now(timezone.utc)

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
        snap_latest = db.get_latest_video_snapshot(vid)
        if not snap_latest:
            continue
        cur_views = int(snap_latest["view_count"])
        snap_latest_id: int = snap_latest["id"]
        latest_dt = datetime.fromisoformat(str(snap_latest["recorded_at"]))

        def _delta(  # noqa: E501
            hours: int, _vid: str = vid, _cur: int = cur_views,
            _lid: int = snap_latest_id, _ldt: datetime = latest_dt,
        ) -> int | None:
            s = db.get_video_snapshot_at(_vid, _ldt - timedelta(hours=hours))
            if s is None:
                return None
            if int(s["id"]) != _lid:
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

    # View totals/deltas: sum of per-video snapshots so the KPI always
    # matches the rising-videos table (channel-level snapshots can lag)
    total_views = sum(r.view_count for r in rows)
    delta_views_1h = sum(r.delta_1h or 0 for r in rows)
    delta_views_24h = sum(r.delta_24h or 0 for r in rows)

    top_rising = sorted(rows, key=lambda r: r.delta_1h or 0, reverse=True)[:10]
    top_by_views = sorted(rows, key=lambda r: r.view_count, reverse=True)[:10]
    generated_at = datetime.now(_JST).strftime("%Y-%m-%d %H:%M JST")

    # Today's hourly view increase (00:00 JST → 23:00 JST)
    now_jst = now + timedelta(hours=9)
    midnight_jst = now_jst.replace(hour=0, minute=0, second=0, microsecond=0)
    midnight_utc = midnight_jst - timedelta(hours=9)

    chart_labels: list[str] = []
    chart_deltas: list[int | None] = []
    chart_now_idx = 0

    for h in range(1, 25):  # 01:00 ~ 24:00
        t_end_utc = midnight_utc + timedelta(hours=h)
        t_start_utc = t_end_utc - timedelta(hours=1)
        t_end_jst = midnight_jst + timedelta(hours=h)
        chart_labels.append("24:00" if h == 24 else t_end_jst.strftime("%H:%M"))
        if t_end_utc <= now:
            chart_now_idx = h - 1
            bucket_delta = 0
            has_data = False
            for r in rows:
                snap_e = db.get_video_snapshot_at(r.video_id, t_end_utc)
                if snap_e:
                    has_data = True
                    snap_s = db.get_video_snapshot_at(r.video_id, t_start_utc)
                    if snap_s and int(snap_e["id"]) != int(snap_s["id"]):
                        bucket_delta += max(0, int(snap_e["view_count"]) - int(snap_s["view_count"]))
            chart_deltas.append(bucket_delta if has_data else None)
        else:
            chart_deltas.append(None)

    chart_labels_json = json.dumps(chart_labels, ensure_ascii=False)
    chart_deltas_json = json.dumps(chart_deltas)

    ai_comment = _generate_live_comment(
        api_key=config.openai_api_key,
        base_url=config.openai_base_url,
        model=config.openai_model,
        channel_name=channel_name,
        subscribers=int(latest_ch["subscriber_count"]),
        delta_views_1h=delta_views_1h,
        top_rising=top_rising,
    )
    if ai_comment:
        logger.info("Live AI comment generated (%d chars)", len(ai_comment))

    env = Environment(
        loader=FileSystemLoader(str(config.templates_dir)),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["format_int"] = lambda v: f"{int(v):,}"
    env.filters["fmt_delta"] = lambda v: "-" if v is None else (f"+{v:,}" if int(v) > 0 else f"{int(v):,}")

    template = env.get_template("live.html.j2")
    content = template.render(
        channel_name=channel_name,
        latest_ch=latest_ch,
        total_views=total_views,
        delta_subs_1h=delta_subs_1h,
        delta_views_1h=delta_views_1h,
        delta_subs_24h=delta_subs_24h,
        delta_views_24h=delta_views_24h,
        top_rising=top_rising,
        top_by_views=top_by_views,
        generated_at=generated_at,
        ai_comment=ai_comment,
        chart_labels_json=chart_labels_json,
        chart_deltas_json=chart_deltas_json,
        chart_now_idx=chart_now_idx,
    )

    docs_dir = config.docs_dir
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "live.html").write_text(content, encoding="utf-8")
    logger.info("Live report generated: %s/live.html", docs_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
