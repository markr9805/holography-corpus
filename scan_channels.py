#!/usr/bin/env python3
"""
Holography Transcript Pipeline
===============================
Scan ALL channels for new videos and add them to the catalog.

Reads creators.json for channel definitions and catalog.json for
tracking. Supports YouTube, Vimeo, and website (URL extraction) platforms.

Usage:
    python3 scan_channels.py [--creator CREATOR_ID] [--limit N]
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
CATALOG_FILE = SCRIPT_DIR / "catalog.json"
CREATORS_FILE = SCRIPT_DIR / "creators.json"


def load_creators():
    """Load creator definitions."""
    with open(CREATORS_FILE) as f:
        return json.load(f)


def load_catalog():
    """Load existing video catalog."""
    if CATALOG_FILE.exists():
        with open(CATALOG_FILE) as f:
            return json.load(f)
    return []


def save_catalog(catalog):
    """Save video catalog."""
    with open(CATALOG_FILE, "w") as f:
        json.dump(catalog, f, indent=2)


def fetch_youtube_videos(creator, limit=None):
    """Fetch video list from a YouTube channel using yt-dlp."""
    channel_url = creator["channel_url"]
    if not channel_url.endswith("/videos"):
        channel_url = channel_url.rstrip("/") + "/videos"

    cmd = ["yt-dlp", "--flat-playlist", "--dump-json", channel_url]
    if limit:
        cmd.extend(["--playlist-end", str(limit)])

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        print(f"  Error fetching {channel_url}: {result.stderr[:200]}")
        return []

    videos = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            videos.append({
                "id": data["id"],
                "title": data.get("title", ""),
                "duration": data.get("duration", 0) or 0,
                "creator_id": creator["id"],
                "creator_name": creator["name"],
                "platform": "youtube",
                "channel_url": creator["channel_url"],
                "upload_date": data.get("upload_date", ""),
                "description": data.get("description", ""),
            })
        except json.JSONDecodeError:
            continue

    return videos


def fetch_vimeo_videos(creator, limit=None):
    """Fetch video list from a Vimeo channel using yt-dlp."""
    channel_url = creator["channel_url"]

    cmd = ["yt-dlp", "--flat-playlist", "--dump-json", channel_url]
    if limit:
        cmd.extend(["--playlist-end", str(limit)])

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        print(f"  Error fetching {channel_url}: {result.stderr[:200]}")
        return []

    videos = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            videos.append({
                "id": data["id"],
                "title": data.get("title", ""),
                "duration": data.get("duration", 0) or 0,
                "creator_id": creator["id"],
                "creator_name": creator["name"],
                "platform": "vimeo",
                "channel_url": creator["channel_url"],
                "upload_date": data.get("upload_date", ""),
                "description": data.get("description", ""),
            })
        except json.JSONDecodeError:
            continue

    return videos


def fetch_website_video_urls(creator):
    """Extract YouTube/Vimeo video URLs from a website.

    This is a best-effort scraper that looks for embedded video URLs
    on the creator's website. It doesn't download — just finds URLs
    that can be added to the catalog for later download.
    """
    import re

    url = creator["channel_url"]
    print(f"  Fetching {url} for embedded video URLs...")

    try:
        result = subprocess.run(
            ["curl", "-sL", "--max-time", "30", url],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            print(f"  Error fetching {url}")
            return []

        html = result.stdout
        if not html:
            return []

        # Find YouTube video IDs
        yt_pattern = r'(?:youtube\.com/(?:watch\?v=|embed/|v/)|youtu\.be/)([a-zA-Z0-9_-]{11})'
        yt_ids = list(set(re.findall(yt_pattern, html)))

        # Find Vimeo video IDs
        vimeo_pattern = r'vimeo\.com/(?:video/)?(\d+)'
        vimeo_ids = list(set(re.findall(vimeo_pattern, html)))

        videos = []

        for yt_id in yt_ids:
            videos.append({
                "id": yt_id,
                "title": f"[YouTube video from {creator['name']} website]",
                "duration": 0,
                "creator_id": creator["id"],
                "creator_name": creator["name"],
                "platform": "youtube",
                "channel_url": creator["channel_url"],
                "upload_date": "",
                "description": f"Found on {url}",
                "source": "website",
            })

        for vimeo_id in vimeo_ids:
            videos.append({
                "id": vimeo_id,
                "title": f"[Vimeo video from {creator['name']} website]",
                "duration": 0,
                "creator_id": creator["id"],
                "creator_name": creator["name"],
                "platform": "vimeo",
                "channel_url": creator["channel_url"],
                "upload_date": "",
                "description": f"Found on {url}",
                "source": "website",
            })

        return videos

    except Exception as e:
        print(f"  Error scraping {url}: {e}")
        return []


def enrich_video_metadata(video_id, platform):
    """Fetch full metadata for a video using yt-dlp."""
    if platform == "youtube":
        url = f"https://www.youtube.com/watch?v={video_id}"
    elif platform == "vimeo":
        url = f"https://vimeo.com/{video_id}"
    else:
        return {}

    try:
        result = subprocess.run(
            ["yt-dlp", "--dump-json", "--skip-download", url],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return {
                "title": data.get("title", ""),
                "duration": data.get("duration", 0) or 0,
                "upload_date": data.get("upload_date", ""),
                "description": data.get("description", ""),
            }
    except Exception:
        pass
    return {}


def main():
    parser = argparse.ArgumentParser(description="Scan channels for new videos")
    parser.add_argument("--creator", help="Only scan this creator ID")
    parser.add_argument("--limit", type=int, help="Only fetch N most recent videos per channel")
    parser.add_argument("--enrich", action="store_true", help="Enrich metadata for new videos")
    args = parser.parse_args()

    creators = load_creators()
    if args.creator:
        creators = [c for c in creators if c["id"] == args.creator]

    catalog = load_catalog()
    existing_ids = {v["id"] for v in catalog}
    print(f"Current catalog: {len(catalog)} videos")

    total_added = 0

    for creator in creators:
        print(f"\n{'='*60}")
        print(f"Scanning: {creator['name']} ({creator['platform']})")
        print(f"{'='*60}")

        if creator["platform"] == "youtube":
            new_videos = fetch_youtube_videos(creator, args.limit)
        elif creator["platform"] == "vimeo":
            new_videos = fetch_vimeo_videos(creator, args.limit)
        elif creator["platform"] == "website":
            new_videos = fetch_website_video_urls(creator)
        else:
            print(f"  Unsupported platform: {creator['platform']}")
            continue

        print(f"  Found {len(new_videos)} videos on channel")

        added = 0
        for video in new_videos:
            if video["id"] not in existing_ids:
                # Enrich metadata if requested and video has no title/duration
                if args.enrich and (not video.get("title") or video["title"].startswith("[") or video.get("duration", 0) == 0):
                    metadata = enrich_video_metadata(video["id"], video["platform"])
                    if metadata:
                        video.update({k: v for k, v in metadata.items() if v})

                catalog.append(video)
                existing_ids.add(video["id"])
                added += 1
                duration_min = (video.get("duration", 0) or 0) / 60
                print(f"  + {video['id']} ({duration_min:.1f}min) {video.get('title', '')[:60]}")

        total_added += added
        if added == 0:
            print(f"  No new videos")

    if total_added > 0:
        # Sort by creator then by duration for consistent ordering
        catalog.sort(key=lambda v: (v.get("creator_id", ""), v.get("duration", 0)))
        save_catalog(catalog)
        print(f"\nAdded {total_added} new videos. Catalog now has {len(catalog)} videos.")
    else:
        print(f"\nNo new videos found.")

    return total_added


if __name__ == "__main__":
    main()