#!/usr/bin/env python3
"""Daily analysis entry point.

Computes daily summaries, scores, AI analysis, charts, and reports.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import logging

from youtube_analytics.ai_analyzer import AIAnalyzer
from youtube_analytics.analyzer import StatisticalAnalyzer
from youtube_analytics.config import get_config
from youtube_analytics.database import DatabaseManager
from youtube_analytics.logging_config import setup_logging
from youtube_analytics.models import DailyChannelSummary, DailyVideoSummary
from youtube_analytics.reporter import Reporter
from youtube_analytics.visualizer import Visualizer


def main() -> int:
    config = get_config()
    logger = setup_logging(config.logs_dir, "daily_analysis")

    errors = config.validate()
    if errors:
        for err in errors:
            logger.error("Config error: %s", err)
        return 1

    logger.info("=== Daily analysis start ===")

    db = DatabaseManager(config.db_path)
    db.initialize()

    # Resolve channel
    channel_row = None
    if config.channel_id:
        channel_row = db.get_channel(config.channel_id)
    if not channel_row:
        logger.error("Channel not found in DB. Run collect.py first.")
        return 1

    channel_id: str = channel_row["channel_id"]
    channel_name: str = channel_row["channel_name"]
    today = datetime.utcnow().strftime("%Y-%m-%d")
    yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")

    analyzer = StatisticalAnalyzer(db, config)

    # ── Compute daily channel summary ─────────────────────────────────────────
    latest_ch = db.get_latest_channel_snapshot(channel_id)
    prev_ch = db.get_channel_snapshot_at(channel_id, datetime.utcnow() - timedelta(hours=24))
    all_videos = db.get_all_videos(channel_id)
    shorts_count = sum(1 for v in all_videos if v["video_type"] == "shorts")
    regular_count = sum(1 for v in all_videos if v["video_type"] == "regular")

    cutoff_yesterday = datetime.utcnow() - timedelta(hours=24)
    new_videos = sum(
        1 for v in all_videos
        if datetime.fromisoformat(v["published_at"]) >= cutoff_yesterday
    )

    if latest_ch:
        daily_ch = DailyChannelSummary(
            channel_id=channel_id,
            date=today,
            subscriber_count=latest_ch["subscriber_count"],
            view_count=latest_ch["view_count"],
            video_count=latest_ch["video_count"],
            subscriber_delta=latest_ch["subscriber_count"] - (prev_ch["subscriber_count"] if prev_ch else latest_ch["subscriber_count"]),
            view_delta=latest_ch["view_count"] - (prev_ch["view_count"] if prev_ch else latest_ch["view_count"]),
            new_video_count=new_videos,
            shorts_count=shorts_count,
            regular_count=regular_count,
        )
        db.upsert_daily_channel_summary(daily_ch)
        logger.info("Daily channel summary saved for %s", today)

    # ── Compute daily video summaries + scores ────────────────────────────────
    saved_summaries = 0
    now = datetime.utcnow()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    for row in all_videos:
        vid = row["video_id"]
        published_at = datetime.fromisoformat(row["published_at"])

        snap_start = db.get_video_snapshot_at(vid, day_start)
        snap_end = db.get_video_snapshot_at(vid, now)

        if not snap_start or not snap_end:
            continue

        summary = DailyVideoSummary(
            video_id=vid,
            date=today,
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
        saved_summaries += 1

    logger.info("Saved %d daily video summaries", saved_summaries)

    # ── Compile full report data ───────────────────────────────────────────────
    report_data = analyzer.compile_report_data(channel_id, channel_name)

    # ── Generate visualizations ───────────────────────────────────────────────
    viz = Visualizer(db, config.graphs_dir)
    graph_paths = viz.generate_all(
        channel_id,
        report_data.all_videos,
        report_data.day_of_week_stats,
        report_data.hour_stats,
    )
    report_data.graph_paths = graph_paths
    logger.info("Generated %d charts", len(graph_paths))

    # ── AI analysis ───────────────────────────────────────────────────────────
    ai = AIAnalyzer(config)
    ai_text, model, tokens = ai.generate_analysis(report_data)
    if ai_text:
        report_data.ai_analysis = ai_text
        db.insert_ai_analysis(
            analysis_type="daily_report",
            model_used=model,
            response=ai_text,
            prompt_tokens=tokens,
        )
        logger.info("AI analysis saved (model=%s, tokens=%d)", model, tokens)

    # ── Generate reports ──────────────────────────────────────────────────────
    reporter = Reporter(config, db)
    md_path, html_path = reporter.generate_full_report(report_data)
    logger.info("Reports: %s | %s", md_path, html_path)

    logger.info("=== Daily analysis complete ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
