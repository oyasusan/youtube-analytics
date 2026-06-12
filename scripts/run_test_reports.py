#!/usr/bin/env python3
"""Generate daily + hourly (live) test reports from test.db.

Reads data/test.db, produces:
  test_output/reports/report_test.html  ← daily report
  test_output/docs/live_test.html       ← hourly live report

Both use the same Jinja2 templates as production.
Run generate_test_data.py first.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from youtube_analytics.analyzer import StatisticalAnalyzer
from youtube_analytics.config import Config
from youtube_analytics.database import DatabaseManager
from youtube_analytics.models import DailyChannelSummary, DailyVideoSummary
from youtube_analytics.reporter import Reporter
from youtube_analytics.visualizer import Visualizer

_PROJECT = Path(__file__).parent.parent
_TEST_DB = _PROJECT / "data" / "test.db"
_TEST_OUT = _PROJECT / "test_output"
_JST = timezone(timedelta(hours=9))

CHANNEL_ID = "UC_TESTCHANNEL_0001"
CHANNEL_NAME = "テストアイドルグループ"


# ── Test-specific Config subclass ─────────────────────────────────────────────

@dataclass
class TestConfig(Config):
    """Config with paths redirected to test_output/."""

    @property
    def db_path(self) -> Path:  # type: ignore[override]
        return _TEST_DB

    @property
    def reports_dir(self) -> Path:  # type: ignore[override]
        return _TEST_OUT / "reports"

    @property
    def graphs_dir(self) -> Path:  # type: ignore[override]
        return _TEST_OUT / "graphs"

    @property
    def docs_dir(self) -> Path:  # type: ignore[override]
        return _TEST_OUT / "docs"


# ── Daily report ──────────────────────────────────────────────────────────────

def _run_daily(db: DatabaseManager, config: TestConfig) -> None:
    print("デイリーレポートを生成中...")

    # "現在時刻"はテストDBの最新スナップショット時刻に合わせる
    latest_ch = db.get_latest_channel_snapshot(CHANNEL_ID)
    if not latest_ch:
        print("ERROR: チャンネルスナップショットが見つかりません")
        return

    now = datetime.fromisoformat(str(latest_ch["recorded_at"]))
    today_jst = (now + timedelta(hours=9)).strftime("%Y-%m-%d")

    prev_ch = db.get_channel_snapshot_at(CHANNEL_ID, now - timedelta(hours=24))
    all_videos = db.get_all_videos(CHANNEL_ID)

    shorts_count = sum(1 for v in all_videos if v["video_type"] == "shorts")
    regular_count = sum(1 for v in all_videos if v["video_type"] == "regular")
    cutoff_yesterday = now - timedelta(hours=24)
    new_videos = sum(
        1 for v in all_videos
        if datetime.fromisoformat(v["published_at"]) >= cutoff_yesterday
    )

    if latest_ch:
        daily_ch = DailyChannelSummary(
            channel_id=CHANNEL_ID,
            date=today_jst,
            subscriber_count=latest_ch["subscriber_count"],
            view_count=latest_ch["view_count"],
            video_count=latest_ch["video_count"],
            subscriber_delta=(
                latest_ch["subscriber_count"]
                - (prev_ch["subscriber_count"] if prev_ch else latest_ch["subscriber_count"])
            ),
            view_delta=(
                latest_ch["view_count"]
                - (prev_ch["view_count"] if prev_ch else latest_ch["view_count"])
            ),
            new_video_count=new_videos,
            shorts_count=shorts_count,
            regular_count=regular_count,
        )
        db.upsert_daily_channel_summary(daily_ch)

    analyzer = StatisticalAnalyzer(db, config)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    saved = 0

    for row in all_videos:
        vid = row["video_id"]
        published_at = datetime.fromisoformat(row["published_at"])

        snap_end = db.get_latest_video_snapshot(vid)
        if not snap_end:
            continue
        snap_start = db.get_video_snapshot_at(vid, day_start)
        if not snap_start or snap_start["id"] == snap_end["id"]:
            continue

        summary = DailyVideoSummary(
            video_id=vid,
            date=today_jst,
            view_count_start=snap_start["view_count"],
            view_count_end=snap_end["view_count"],
            view_count_delta=max(0, snap_end["view_count"] - snap_start["view_count"]),
            like_count_start=snap_start["like_count"],
            like_count_end=snap_end["like_count"],
            like_count_delta=max(0, snap_end["like_count"] - snap_start["like_count"]),
            comment_count_start=snap_start["comment_count"],
            comment_count_end=snap_end["comment_count"],
            comment_count_delta=max(0, snap_end["comment_count"] - snap_start["comment_count"]),
            momentum_index=analyzer.momentum_index(vid),
            buzz_score=analyzer.buzz_score(vid),
        )
        db.upsert_daily_video_summary(summary)

        score = analyzer.compute_video_scores(vid, published_at)
        db.insert_video_score(score)
        saved += 1

    print(f"  動画サマリー {saved} 件保存")

    report_data = analyzer.compile_report_data(CHANNEL_ID, CHANNEL_NAME)
    report_data.report_date = today_jst

    viz = Visualizer(db, config.graphs_dir)
    graph_paths = viz.generate_all(
        CHANNEL_ID,
        report_data.all_videos,
        report_data.day_of_week_stats,
        report_data.hour_stats,
    )
    report_data.graph_paths = graph_paths
    print(f"  グラフ {len(graph_paths)} 件生成")

    reporter = Reporter(config, db)
    _, html_path = reporter.generate_full_report(report_data)
    print(f"  デイリーレポート: {html_path}")


# ── Hourly (live) report ──────────────────────────────────────────────────────

def _run_hourly(db: DatabaseManager, config: TestConfig) -> None:
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    print("アワーリーレポートを生成中...")

    latest_ch = db.get_latest_channel_snapshot(CHANNEL_ID)
    if not latest_ch:
        print("ERROR: チャンネルスナップショットが見つかりません")
        return

    now = datetime.fromisoformat(str(latest_ch["recorded_at"]))

    prev_ch_1h = db.get_channel_snapshot_at(CHANNEL_ID, now - timedelta(hours=1))
    prev_ch_24h = db.get_channel_snapshot_at(CHANNEL_ID, now - timedelta(hours=24))

    def ch_delta(field: str, prev: object) -> int:
        if prev is None:
            return 0
        return int(latest_ch[field]) - int(prev[field])  # type: ignore[index]

    delta_subs_1h = ch_delta("subscriber_count", prev_ch_1h)
    delta_subs_24h = ch_delta("subscriber_count", prev_ch_24h)
    delta_views_1h = ch_delta("view_count", prev_ch_1h)
    delta_views_24h = ch_delta("view_count", prev_ch_24h)

    @dataclass
    class _Row:
        video_id: str
        title: str
        video_type: str
        view_count: int
        delta_1h: int
        delta_3h: int
        delta_24h: int

    all_videos = db.get_all_videos(CHANNEL_ID)
    rows: list[_Row] = []

    for v in all_videos:
        vid: str = v["video_id"]
        snap_latest = db.get_latest_video_snapshot(vid)
        if not snap_latest:
            continue
        cur_views = int(snap_latest["view_count"])
        snap_latest_id: int = snap_latest["id"]
        latest_dt = datetime.fromisoformat(str(snap_latest["recorded_at"]))

        def _delta(
            hours: int,
            _vid: str = vid,
            _cur: int = cur_views,
            _lid: int = snap_latest_id,
            _ldt: datetime = latest_dt,
        ) -> int:
            s = db.get_video_snapshot_at(_vid, _ldt - timedelta(hours=hours))
            if s and int(s["id"]) != _lid:
                return max(0, _cur - int(s["view_count"]))
            return 0

        rows.append(_Row(
            video_id=vid,
            title=v["title"],
            video_type=v["video_type"],
            view_count=cur_views,
            delta_1h=_delta(1),
            delta_3h=_delta(3),
            delta_24h=_delta(24),
        ))

    top_rising = sorted(rows, key=lambda r: r.delta_1h, reverse=True)[:10]
    top_by_views = sorted(rows, key=lambda r: r.view_count, reverse=True)[:10]

    # Hourly chart (today JST 00:00 → now)
    now_jst = now + timedelta(hours=9)
    midnight_jst = now_jst.replace(hour=0, minute=0, second=0, microsecond=0)
    midnight_utc = midnight_jst - timedelta(hours=9)

    chart_labels: list[str] = []
    chart_deltas: list[int | None] = []
    chart_now_idx = 0

    for h in range(1, 25):
        t_end_utc = midnight_utc + timedelta(hours=h)
        t_end_jst = midnight_jst + timedelta(hours=h)
        chart_labels.append("24:00" if h == 24 else t_end_jst.strftime("%H:%M"))
        if t_end_utc <= now:
            chart_now_idx = h - 1
            snap_end = db.get_channel_snapshot_at(CHANNEL_ID, t_end_utc)
            snap_start = db.get_channel_snapshot_at(CHANNEL_ID, t_end_utc - timedelta(hours=1))
            if snap_end and snap_start and snap_end["id"] != snap_start["id"]:
                chart_deltas.append(
                    max(0, int(snap_end["view_count"]) - int(snap_start["view_count"]))
                )
            else:
                chart_deltas.append(None)
        else:
            chart_deltas.append(None)

    generated_at = datetime.now(_JST).strftime("%Y-%m-%d %H:%M JST")

    env = Environment(
        loader=FileSystemLoader(str(config.templates_dir)),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["format_int"] = lambda v: f"{int(v):,}"
    env.filters["fmt_delta"] = lambda v: (f"+{v:,}" if int(v) > 0 else f"{int(v):,}")

    template = env.get_template("live.html.j2")
    content = template.render(
        channel_name=CHANNEL_NAME,
        latest_ch=latest_ch,
        delta_subs_1h=delta_subs_1h,
        delta_views_1h=delta_views_1h,
        delta_subs_24h=delta_subs_24h,
        delta_views_24h=delta_views_24h,
        top_rising=top_rising,
        top_by_views=top_by_views,
        generated_at=generated_at,
        ai_comment="",
        chart_labels_json=json.dumps(chart_labels, ensure_ascii=False),
        chart_deltas_json=json.dumps(chart_deltas),
        chart_now_idx=chart_now_idx,
    )

    docs_dir = config.docs_dir
    docs_dir.mkdir(parents=True, exist_ok=True)
    out_path = docs_dir / "live_test.html"
    out_path.write_text(content, encoding="utf-8")
    print(f"  アワーリーレポート: {out_path}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    if not _TEST_DB.exists():
        print(f"ERROR: テストDBが見つかりません: {_TEST_DB}")
        print("先に scripts/generate_test_data.py を実行してください")
        return 1

    import os
    os.environ.setdefault("YOUTUBE_API_KEY", "dummy")
    os.environ.setdefault("CHANNEL_NAME", CHANNEL_NAME)

    config = TestConfig()
    _TEST_OUT.mkdir(exist_ok=True)

    db = DatabaseManager(_TEST_DB)

    _run_daily(db, config)
    _run_hourly(db, config)

    print()
    print("=== 完了 ===")
    print(f"デイリー: {config.docs_dir}/index.html")
    print(f"アワーリー: {config.docs_dir}/live_test.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
