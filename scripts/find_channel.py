#!/usr/bin/env python3
"""Utility: look up a YouTube channel ID by name and print it."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from youtube_analytics.config import get_config
from youtube_analytics.collector import YouTubeCollector


def main() -> int:
    config = get_config()
    if not config.youtube_api_key:
        print("ERROR: YOUTUBE_API_KEY is not set", file=sys.stderr)
        return 1

    name = sys.argv[1] if len(sys.argv) > 1 else config.channel_name
    print(f"Searching for channel: {name}")

    collector = YouTubeCollector(config)
    try:
        channel_id, playlist_id = collector._search_channel_by_name(name)
        print(f"Channel ID:  {channel_id}")
        print(f"Playlist ID: {playlist_id}")
        print(f"\nAdd to .env or GitHub Variables:")
        print(f"CHANNEL_ID={channel_id}")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
