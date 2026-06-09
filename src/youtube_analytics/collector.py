"""YouTube Data API v3 client with quota-efficient collection and retry logic."""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from googleapiclient.discovery import build  # type: ignore[import-untyped]
from googleapiclient.errors import HttpError  # type: ignore[import-untyped]

from .config import Config
from .models import ChannelSnapshot, Video, VideoSnapshot

logger = logging.getLogger(__name__)

_ISO_DURATION_RE = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")

CONTENT_TYPE_RULES: list[tuple[str, list[str]]] = [
    ("mv", ["MV", "MUSIC VIDEO", "PV", "OFFICIAL VIDEO", "OFFICIAL MV"]),
    ("live", ["ライブ", "LIVE", "CONCERT", "コンサート", "公演", "ZEPP", "武道館", "TOUR"]),
    ("teaser", ["ティザー", "TEASER", "予告", "PREVIEW"]),
    ("making", ["メイキング", "MAKING", "BEHIND", "BTS", "密着"]),
    ("announcement", ["告知", "お知らせ", "INFO", "INFORMATION", "リリース", "RELEASE", "発売"]),
]


def parse_iso_duration(duration: str) -> int:
    """Return total seconds for an ISO 8601 duration string."""
    m = _ISO_DURATION_RE.match(duration)
    if not m:
        return 0
    hours = int(m.group(1) or 0)
    minutes = int(m.group(2) or 0)
    seconds = int(m.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


def classify_video_type(duration_secs: int, title: str, description: str) -> str:
    """Return 'shorts' or 'regular' based on duration and tags."""
    text = f"{title} {description}".lower()
    if duration_secs <= 60 or "#shorts" in text:
        return "shorts"
    return "regular"


def classify_content_type(title: str, description: str, video_type: str) -> str:
    """Classify video into a content category from title/description."""
    if video_type == "shorts":
        return "shorts"
    text = f"{title} {description}".upper()
    for content_type, keywords in CONTENT_TYPE_RULES:
        for kw in keywords:
            if kw in text:
                return content_type
    return "other"


def _retry(func: Any, max_retries: int = 3, initial_delay: float = 1.0) -> Any:
    """Call func with exponential backoff on transient errors."""
    delay = initial_delay
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            return func()
        except HttpError as exc:
            status = exc.resp.status if hasattr(exc, "resp") else 0
            if status in (403, 400):
                raise
            last_exc = exc
            logger.warning("API error (attempt %d/%d): %s", attempt, max_retries, exc)
        except Exception as exc:
            last_exc = exc
            logger.warning("Request error (attempt %d/%d): %s", attempt, max_retries, exc)
        if attempt < max_retries:
            time.sleep(delay)
            delay *= 2
    raise RuntimeError(f"Failed after {max_retries} attempts") from last_exc


class YouTubeCollector:
    """Collects channel and video data from YouTube Data API v3."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._service: Any = None

    @property
    def service(self) -> Any:
        if self._service is None:
            self._service = build(
                "youtube", "v3", developerKey=self.config.youtube_api_key
            )
        return self._service

    # ── Channel resolution ────────────────────────────────────────────────────

    def resolve_channel_id(self) -> tuple[str, str]:
        """Return (channel_id, uploads_playlist_id).

        Uses CHANNEL_ID from config if set; otherwise searches by CHANNEL_NAME.
        """
        if self.config.channel_id:
            return self._get_uploads_playlist(self.config.channel_id)
        return self._search_channel_by_name(self.config.channel_name)

    def _get_uploads_playlist(self, channel_id: str) -> tuple[str, str]:
        def call() -> Any:
            return (
                self.service.channels()
                .list(part="contentDetails", id=channel_id)
                .execute()
            )

        resp = _retry(call)
        items = resp.get("items", [])
        if not items:
            raise ValueError(f"Channel not found: {channel_id}")
        playlist_id: str = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
        return channel_id, playlist_id

    def _search_channel_by_name(self, name: str) -> tuple[str, str]:
        def call() -> Any:
            return (
                self.service.search()
                .list(part="snippet", q=name, type="channel", maxResults=1)
                .execute()
            )

        resp = _retry(call)
        items = resp.get("items", [])
        if not items:
            raise ValueError(f"Channel not found by name: {name}")
        channel_id: str = items[0]["snippet"]["channelId"]
        logger.info("Resolved channel '%s' → %s", name, channel_id)
        return self._get_uploads_playlist(channel_id)

    # ── Channel snapshot ──────────────────────────────────────────────────────

    def get_channel_snapshot(self, channel_id: str) -> ChannelSnapshot:
        """Fetch current channel-level metrics."""

        def call() -> Any:
            return (
                self.service.channels()
                .list(part="statistics", id=channel_id)
                .execute()
            )

        resp = _retry(call)
        items = resp.get("items", [])
        if not items:
            raise ValueError(f"Channel not found: {channel_id}")
        stats = items[0]["statistics"]
        return ChannelSnapshot(
            channel_id=channel_id,
            recorded_at=datetime.now(tz=timezone.utc).replace(tzinfo=None),
            subscriber_count=int(stats.get("subscriberCount", 0)),
            view_count=int(stats.get("viewCount", 0)),
            video_count=int(stats.get("videoCount", 0)),
        )

    # ── Video listing ─────────────────────────────────────────────────────────

    def get_all_video_ids(self, uploads_playlist_id: str) -> list[str]:
        """Return all video IDs in the uploads playlist (paginated)."""
        video_ids: list[str] = []
        page_token: Optional[str] = None

        while True:
            def call(token: Optional[str] = page_token) -> Any:
                return (
                    self.service.playlistItems()
                    .list(
                        part="contentDetails",
                        playlistId=uploads_playlist_id,
                        maxResults=50,
                        pageToken=token,
                    )
                    .execute()
                )

            resp = _retry(call)
            for item in resp.get("items", []):
                vid = item.get("contentDetails", {}).get("videoId")
                if vid:
                    video_ids.append(vid)

            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        logger.info("Found %d videos in uploads playlist", len(video_ids))
        return video_ids

    # ── Video details ─────────────────────────────────────────────────────────

    def get_video_details(
        self, video_ids: list[str], channel_id: str
    ) -> tuple[list[Video], list[VideoSnapshot]]:
        """Fetch full metadata and stats for a list of video IDs (batched in 50s)."""
        videos: list[Video] = []
        snapshots: list[VideoSnapshot] = []
        now = datetime.now(tz=timezone.utc).replace(tzinfo=None)

        for i in range(0, len(video_ids), 50):
            batch = video_ids[i : i + 50]
            batch_str = ",".join(batch)

            def call(ids: str = batch_str) -> Any:
                return (
                    self.service.videos()
                    .list(
                        part="snippet,statistics,contentDetails",
                        id=ids,
                    )
                    .execute()
                )

            resp = _retry(call)
            for item in resp.get("items", []):
                video, snap = self._parse_video_item(item, channel_id, now)
                videos.append(video)
                snapshots.append(snap)

        logger.info("Fetched details for %d videos", len(videos))
        return videos, snapshots

    def _parse_video_item(
        self, item: dict[str, Any], channel_id: str, now: datetime
    ) -> tuple[Video, VideoSnapshot]:
        video_id: str = item["id"]
        snippet: dict[str, Any] = item.get("snippet", {})
        stats: dict[str, Any] = item.get("statistics", {})
        details: dict[str, Any] = item.get("contentDetails", {})

        title: str = snippet.get("title", "")
        description: str = snippet.get("description", "")
        published_str: str = snippet.get("publishedAt", "")
        published_at = _parse_dt(published_str)

        thumbnails: dict[str, Any] = snippet.get("thumbnails", {})
        thumbnail_url: str = (
            thumbnails.get("maxres", {}).get("url")
            or thumbnails.get("high", {}).get("url")
            or thumbnails.get("default", {}).get("url")
            or ""
        )

        duration_str: str = details.get("duration", "PT0S")
        duration_secs = parse_iso_duration(duration_str)
        video_type = classify_video_type(duration_secs, title, description)
        content_type = classify_content_type(title, description, video_type)

        video = Video(
            video_id=video_id,
            channel_id=channel_id,
            title=title,
            description=description,
            published_at=published_at,
            video_url=f"https://www.youtube.com/watch?v={video_id}",
            thumbnail_url=thumbnail_url,
            video_type=video_type,
            content_type=content_type,
        )

        snapshot = VideoSnapshot(
            video_id=video_id,
            recorded_at=now,
            view_count=int(stats.get("viewCount", 0)),
            like_count=int(stats.get("likeCount", 0)),
            comment_count=int(stats.get("commentCount", 0)),
        )

        return video, snapshot

    # ── Convenience: collect everything in one call ────────────────────────────

    def collect_all(self) -> tuple[str, str, ChannelSnapshot, list[Video], list[VideoSnapshot]]:
        """Return (channel_id, uploads_playlist_id, channel_snap, videos, video_snaps)."""
        channel_id, playlist_id = self.resolve_channel_id()
        channel_snap = self.get_channel_snapshot(channel_id)
        video_ids = self.get_all_video_ids(playlist_id)
        videos, snaps = self.get_video_details(video_ids, channel_id)
        return channel_id, playlist_id, channel_snap, videos, snaps


def _parse_dt(dt_str: str) -> datetime:
    """Parse ISO 8601 datetime string to naive UTC datetime."""
    if not dt_str:
        return datetime.utcnow()
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        return datetime.utcnow()


def check_ollama_available(base_url: str) -> bool:
    """Return True if Ollama server responds to a health check."""
    try:
        r = httpx.get(f"{base_url}/api/tags", timeout=5.0)
        return r.status_code == 200
    except Exception:
        return False
