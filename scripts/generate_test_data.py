#!/usr/bin/env python3
"""Generate 1 month of realistic dummy data for testing.

Creates data/test.db with:
  - 1 test channel
  - 20 videos (MV / live / shorts / regular / performance)
  - Hourly channel + video snapshots for the past 30 days
"""

from __future__ import annotations

import math
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from youtube_analytics.database import DatabaseManager
from youtube_analytics.models import ChannelSnapshot, Video, VideoSnapshot

TEST_DB = Path(__file__).parent.parent / "data" / "test.db"
CHANNEL_ID = "UC_TESTCHANNEL_0001"
CHANNEL_NAME = "テストアイドルグループ"
PLAYLIST_ID = "UU_TESTCHANNEL_0001"

# 固定シードで再現性を確保
random.seed(42)

# ── Video definitions ─────────────────────────────────────────────────────────

_VIDEOS: list[dict] = [
    # (video_id, title, video_type, content_type, days_ago, base_views, like_ratio, comment_ratio)
    # ── MV (公開日: 5日〜60日前) ─────────────────────────────────────────────
    {"id": "tv_mv_001", "title": "テストグループ / 夢色ロマンス｜Music Video",
     "type": "regular", "content": "mv", "days_ago": 60,
     "base_views": 42000, "like_r": 0.06, "comment_r": 0.008},
    {"id": "tv_mv_002", "title": "テストグループ / 君のそばで｜Music Video",
     "type": "regular", "content": "mv", "days_ago": 45,
     "base_views": 28000, "like_r": 0.07, "comment_r": 0.010},
    {"id": "tv_mv_003", "title": "テストグループ / 恋のシグナル｜Music Video",
     "type": "regular", "content": "mv", "days_ago": 5,
     "base_views": 4200, "like_r": 0.08, "comment_r": 0.012},
    # ── Live ─────────────────────────────────────────────────────────────────
    {"id": "tv_live_001", "title": "テストグループ｜春のワンマンライブ 2026",
     "type": "regular", "content": "live", "days_ago": 50,
     "base_views": 18000, "like_r": 0.05, "comment_r": 0.009},
    {"id": "tv_live_002", "title": "テストグループ / アコースティックライブ｜Live Video",
     "type": "regular", "content": "live", "days_ago": 10,
     "base_views": 3200, "like_r": 0.06, "comment_r": 0.007},
    # ── Performance ───────────────────────────────────────────────────────────
    {"id": "tv_perf_001", "title": "テストグループ / 夢色ロマンス｜Performance Video",
     "type": "regular", "content": "other", "days_ago": 58,
     "base_views": 5200, "like_r": 0.04, "comment_r": 0.005},
    {"id": "tv_perf_002", "title": "テストグループ / 君のそばで｜Performance Video",
     "type": "regular", "content": "other", "days_ago": 43,
     "base_views": 3800, "like_r": 0.04, "comment_r": 0.004},
    {"id": "tv_perf_003", "title": "テストグループ / 恋のシグナル｜Performance Video",
     "type": "regular", "content": "other", "days_ago": 4,
     "base_views": 800, "like_r": 0.05, "comment_r": 0.006},
    {"id": "tv_perf_004", "title": "テストグループ / ときめきメロディー｜Performance Video",
     "type": "regular", "content": "other", "days_ago": 35,
     "base_views": 2800, "like_r": 0.04, "comment_r": 0.005},
    {"id": "tv_perf_005", "title": "テストグループ / ハートブレイカー｜Performance Video",
     "type": "regular", "content": "other", "days_ago": 22,
     "base_views": 1900, "like_r": 0.04, "comment_r": 0.005},
    # ── Making / Rec ──────────────────────────────────────────────────────────
    {"id": "tv_rec_001", "title": "テストグループ / 春の記録映像｜Rec Video",
     "type": "regular", "content": "making", "days_ago": 48,
     "base_views": 9500, "like_r": 0.05, "comment_r": 0.007},
    {"id": "tv_rec_002", "title": "テストグループ / メンバー密着｜Behind the Scenes",
     "type": "regular", "content": "making", "days_ago": 7,
     "base_views": 3100, "like_r": 0.06, "comment_r": 0.009},
    # ── Announcement ─────────────────────────────────────────────────────────
    {"id": "tv_ann_001", "title": "テストグループ / ニューシングル発売告知",
     "type": "regular", "content": "announcement", "days_ago": 8,
     "base_views": 2400, "like_r": 0.04, "comment_r": 0.006},
    {"id": "tv_ann_002", "title": "テストグループ / ワンマンライブ開催告知",
     "type": "regular", "content": "announcement", "days_ago": 3,
     "base_views": 1200, "like_r": 0.05, "comment_r": 0.008},
    {"id": "tv_other_001", "title": "テストグループ / オフショット公開！♡",
     "type": "regular", "content": "other", "days_ago": 55,
     "base_views": 7200, "like_r": 0.05, "comment_r": 0.006},
    # ── Shorts ────────────────────────────────────────────────────────────────
    {"id": "tv_sh_001", "title": "今日の練習！🎵 #テストグループ #shorts",
     "type": "shorts", "content": "shorts", "days_ago": 2,
     "base_views": 12000, "like_r": 0.03, "comment_r": 0.002},
    {"id": "tv_sh_002", "title": "メンバー紹介してみた♡ #テストグループ #shorts",
     "type": "shorts", "content": "shorts", "days_ago": 6,
     "base_views": 8500, "like_r": 0.03, "comment_r": 0.002},
    {"id": "tv_sh_003", "title": "ライブ名場面集🔥 #テストグループ #shorts",
     "type": "shorts", "content": "shorts", "days_ago": 40,
     "base_views": 22000, "like_r": 0.04, "comment_r": 0.003},
    {"id": "tv_sh_004", "title": "新曲サビ先行公開🎤 #テストグループ #shorts",
     "type": "shorts", "content": "shorts", "days_ago": 16,
     "base_views": 15000, "like_r": 0.05, "comment_r": 0.003},
    {"id": "tv_sh_005", "title": "推しカメラ撮ってみた📸 #テストグループ #shorts",
     "type": "shorts", "content": "shorts", "days_ago": 52,
     "base_views": 11000, "like_r": 0.03, "comment_r": 0.002},
]


# ── Growth model ──────────────────────────────────────────────────────────────

def _views_at(base_views: int, total_age_days: int, elapsed_days: float) -> int:
    """Simulate cumulative views using a log-growth + noise model."""
    if elapsed_days <= 0:
        return 0
    frac = elapsed_days / max(total_age_days, 1)
    # Log growth: rapid early, slow later
    raw = base_views * math.log1p(frac * 9) / math.log1p(9)
    # Small random fluctuation per day
    noise = random.gauss(0, raw * 0.01)
    return max(0, int(raw + noise))


def _engagements(views: int, like_r: float, comment_r: float) -> tuple[int, int]:
    likes = int(views * like_r * random.uniform(0.9, 1.1))
    comments = int(views * comment_r * random.uniform(0.9, 1.1))
    return likes, comments


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    if TEST_DB.exists():
        TEST_DB.unlink()
        print(f"既存のテストDBを削除: {TEST_DB}")

    db = DatabaseManager(TEST_DB)
    db.initialize()

    # UTCの「現在時刻」を固定（最新スナップショット時刻）
    now_utc = datetime(2026, 6, 12, 8, 0, 0)
    max_days_ago = max(v["days_ago"] for v in _VIDEOS)
    start_utc = now_utc - timedelta(days=max_days_ago)

    # ── Channel ───────────────────────────────────────────────────────────────
    db.upsert_channel(CHANNEL_ID, CHANNEL_NAME, PLAYLIST_ID)

    # ── Videos ───────────────────────────────────────────────────────────────
    for vdef in _VIDEOS:
        published = now_utc - timedelta(days=vdef["days_ago"])
        video = Video(
            video_id=vdef["id"],
            channel_id=CHANNEL_ID,
            title=vdef["title"],
            description="",
            published_at=published,
            video_url=f"https://www.youtube.com/watch?v={vdef['id']}",
            thumbnail_url="",
            video_type=vdef["type"],
            content_type=vdef["content"],
        )
        db.upsert_video(video)

    print(f"{len(_VIDEOS)} 本の動画を登録しました")

    # ── Hourly snapshots (max_days × 24h per entity) ──────────────────────────
    total_hours = max_days_ago * 24
    video_snaps: list[VideoSnapshot] = []

    for h in range(total_hours + 1):
        t = start_utc + timedelta(hours=h)
        channel_views = 0
        channel_subs = 950 + int(h * 0.03)  # 緩やかに増加

        for vdef in _VIDEOS:
            pub = now_utc - timedelta(days=vdef["days_ago"])
            if t < pub:
                continue  # 公開前はスキップ

            elapsed = (t - pub).total_seconds() / 86400
            views = _views_at(vdef["base_views"], vdef["days_ago"], elapsed)
            likes, comments = _engagements(views, vdef["like_r"], vdef["comment_r"])
            channel_views += views

            video_snaps.append(VideoSnapshot(
                video_id=vdef["id"],
                recorded_at=t,
                view_count=views,
                like_count=likes,
                comment_count=comments,
            ))

        db.insert_channel_snapshot(ChannelSnapshot(
            channel_id=CHANNEL_ID,
            recorded_at=t,
            subscriber_count=channel_subs,
            view_count=channel_views,
            video_count=len(_VIDEOS),
        ))

    db.insert_video_snapshots_bulk(video_snaps)

    print(f"チャンネルスナップショット: {total_hours + 1} 件")
    print(f"動画スナップショット: {len(video_snaps)} 件")
    print(f"テストDB作成完了: {TEST_DB}")


if __name__ == "__main__":
    main()
