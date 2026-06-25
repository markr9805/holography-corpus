#!/usr/bin/env python3
"""
Holography Transcript Pipeline
===============================
Step 1: Download captions and audio from YouTube and Vimeo channels.

Supports multiple creators across multiple platforms. Reads creators.json
for channel definitions and catalog.json for tracking downloaded videos.

Usage:
    python3 01_download.py [--creator CREATOR_ID] [--all] [--limit N]
                           [--skip-captions] [--skip-audio] [--resume]

Options:
    --creator ID       Only process videos from this creator
    --all              Process all creators (default)
    --limit N          Only process N videos per creator (for testing)
    --skip-captions    Skip caption download
    --skip-audio       Skip audio download
    --resume           Skip videos that already have files
"""

import argparse
import json
import os
import subprocess
import sys
import time

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
CATALOG_FILE = os.path.join(OUTPUT_DIR, "catalog.json")
CREATORS_FILE = os.path.join(OUTPUT_DIR, "creators.json")
CAPTIONS_DIR = os.path.join(OUTPUT_DIR, "captions")
AUDIO_DIR = os.path.join(OUTPUT_DIR, "audio")


def load_creators():
    """Load creator definitions."""
    with open(CREATORS_FILE) as f:
        return json.load(f)


def load_catalog():
    """Load existing video catalog."""
    if os.path.exists(CATALOG_FILE):
        with open(CATALOG_FILE) as f:
            return json.load(f)
    return []


def save_catalog(catalog):
    """Save video catalog."""
    with open(CATALOG_FILE, "w") as f:
        json.dump(catalog, f, indent=2)


def scan_youtube_channel(creator):
    """Scan a YouTube channel for videos using yt-dlp."""
    channel_url = creator["channel_url"]
    # Ensure we're scanning the videos tab
    if not channel_url.endswith("/videos"):
        channel_url = channel_url.rstrip("/") + "/videos"

    print(f"  Scanning YouTube: {creator['name']} ({channel_url})")
    result = subprocess.run(
        ["yt-dlp", "--flat-playlist", "-J", channel_url],
        capture_output=True, text=True, timeout=300
    )
    if result.returncode != 0:
        print(f"  Error scanning {channel_url}: {result.stderr[:200]}")
        return []

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"  Error parsing response from {channel_url}")
        return []

    videos = []
    entries = data.get("entries", [])
    if entries is None:
        entries = []

    for entry in entries:
        if entry is None:
            continue
        video_id = entry.get("id", "")
        title = entry.get("title", "")
        duration = entry.get("duration", 0) or 0

        videos.append({
            "id": video_id,
            "title": title,
            "duration": duration,
            "creator_id": creator["id"],
            "creator_name": creator["name"],
            "platform": "youtube",
            "channel_url": creator["channel_url"],
            "upload_date": entry.get("upload_date", ""),
            "description": entry.get("description", ""),
        })

    return videos


def scan_vimeo_channel(creator):
    """Scan a Vimeo channel for videos using yt-dlp."""
    channel_url = creator["channel_url"]

    print(f"  Scanning Vimeo: {creator['name']} ({channel_url})")
    result = subprocess.run(
        ["yt-dlp", "--flat-playlist", "-J", channel_url],
        capture_output=True, text=True, timeout=300
    )
    if result.returncode != 0:
        print(f"  Error scanning {channel_url}: {result.stderr[:200]}")
        return []

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"  Error parsing response from {channel_url}")
        return []

    videos = []
    entries = data.get("entries", [])
    if entries is None:
        entries = []

    for entry in entries:
        if entry is None:
            continue
        video_id = entry.get("id", "")
        title = entry.get("title", "")
        duration = entry.get("duration", 0) or 0

        videos.append({
            "id": video_id,
            "title": title,
            "duration": duration,
            "creator_id": creator["id"],
            "creator_name": creator["name"],
            "platform": "vimeo",
            "channel_url": creator["channel_url"],
            "upload_date": entry.get("upload_date", ""),
            "description": entry.get("description", ""),
        })

    return videos


def download_youtube_captions(video_id):
    """Download English auto-captions for a YouTube video."""
    out_file = os.path.join(CAPTIONS_DIR, f"{video_id}.en.srt")
    if os.path.exists(out_file):
        return True

    result = subprocess.run(
        ["yt-dlp", "--write-auto-sub", "--sub-lang", "en",
         "--sub-format", "srt", "--skip-download",
         "-o", os.path.join(CAPTIONS_DIR, video_id),
         f"https://www.youtube.com/watch?v={video_id}"],
        capture_output=True, text=True, timeout=60
    )
    return result.returncode == 0


def download_vimeo_captions(video_id):
    """Download captions for a Vimeo video (if available)."""
    out_file = os.path.join(CAPTIONS_DIR, f"{video_id}.en.srt")
    if os.path.exists(out_file):
        return True

    # Try to get captions from Vimeo
    result = subprocess.run(
        ["yt-dlp", "--write-subs", "--sub-lang", "en",
         "--sub-format", "srt", "--skip-download",
         "-o", os.path.join(CAPTIONS_DIR, video_id),
         f"https://vimeo.com/{video_id}"],
        capture_output=True, text=True, timeout=60
    )
    # Also try auto-subs
    if not os.path.exists(out_file):
        result = subprocess.run(
            ["yt-dlp", "--write-auto-sub", "--sub-lang", "en",
             "--sub-format", "srt", "--skip-download",
             "-o", os.path.join(CAPTIONS_DIR, video_id),
             f"https://vimeo.com/{video_id}"],
            capture_output=True, text=True, timeout=60
        )
    return os.path.exists(out_file)


def download_youtube_audio(video_id):
    """Download audio as WAV from YouTube."""
    out_file = os.path.join(AUDIO_DIR, f"{video_id}.wav")
    if os.path.exists(out_file):
        return True

    result = subprocess.run(
        ["yt-dlp", "-x", "--audio-format", "wav",
         "-o", os.path.join(AUDIO_DIR, f"{video_id}.%(ext)s"),
         f"https://www.youtube.com/watch?v={video_id}"],
        capture_output=True, text=True, timeout=600
    )
    return result.returncode == 0 and os.path.exists(out_file)


def download_vimeo_audio(video_id):
    """Download audio as WAV from Vimeo."""
    out_file = os.path.join(AUDIO_DIR, f"{video_id}.wav")
    if os.path.exists(out_file):
        return True

    result = subprocess.run(
        ["yt-dlp", "-x", "--audio-format", "wav",
         "-o", os.path.join(AUDIO_DIR, f"{video_id}.%(ext)s"),
         f"https://vimeo.com/{video_id}"],
        capture_output=True, text=True, timeout=600
    )
    return result.returncode == 0 and os.path.exists(out_file)


def main():
    parser = argparse.ArgumentParser(description="Download captions and audio from YouTube/Vimeo")
    parser.add_argument("--creator", help="Only process this creator ID")
    parser.add_argument("--all", action="store_true", help="Process all creators (default)")
    parser.add_argument("--limit", type=int, help="Only process N videos per creator")
    parser.add_argument("--skip-captions", action="store_true", help="Skip caption download")
    parser.add_argument("--skip-audio", action="store_true", help="Skip audio download")
    parser.add_argument("--resume", action="store_true", help="Skip videos with existing files")
    parser.add_argument("--scan-only", action="store_true", help="Only scan channels, don't download")
    args = parser.parse_args()

    os.makedirs(CAPTIONS_DIR, exist_ok=True)
    os.makedirs(AUDIO_DIR, exist_ok=True)

    creators = load_creators()
    if args.creator:
        creators = [c for c in creators if c["id"] == args.creator]

    # Filter to downloadable platforms
    downloadable_creators = [c for c in creators if c["platform"] in ("youtube", "vimeo")]
    website_creators = [c for c in creators if c["platform"] == "website"]

    if website_creators:
        print(f"\nNote: {len(website_creators)} website-only creators skipped (use scan_channels.py for URL extraction)")
        for c in website_creators:
            print(f"  - {c['name']} ({c['channel_url']})")

    print(f"\nProcessing {len(downloadable_creators)} creators with video platforms")

    # Load existing catalog
    catalog = load_catalog()
    existing_ids = {v["id"] for v in catalog}

    # Scan each creator for videos
    new_videos = []
    for creator in downloadable_creators:
        print(f"\n{'='*60}")
        print(f"Creator: {creator['name']} ({creator['platform']})")
        print(f"{'='*60}")

        if creator["platform"] == "youtube":
            videos = scan_youtube_channel(creator)
        elif creator["platform"] == "vimeo":
            videos = scan_vimeo_channel(creator)
        else:
            continue

        print(f"  Found {len(videos)} videos")

        # Add new videos to catalog
        added = 0
        for video in videos:
            if video["id"] not in existing_ids:
                catalog.append(video)
                existing_ids.add(video["id"])
                new_videos.append(video)
                added += 1
        print(f"  Added {added} new videos to catalog")

        if args.limit:
            # Limit per creator
            creator_videos = [v for v in videos if v["id"] in existing_ids]
            # We've already added them all; the limit applies to download step

    # Save catalog
    save_catalog(catalog)
    print(f"\nCatalog: {len(catalog)} total videos, {len(new_videos)} new")

    if args.scan_only:
        return

    # Download captions and audio
    videos_to_download = new_videos if not args.resume else [
        v for v in new_videos
        if not (os.path.exists(os.path.join(CAPTIONS_DIR, f"{v['id']}.en.srt"))
                 and os.path.exists(os.path.join(AUDIO_DIR, f"{v['id']}.wav")))
    ]

    if args.limit:
        videos_to_download = videos_to_download[:args.limit]

    print(f"\nDownloading {len(videos_to_download)} videos...")
    print(f"  Captions: {'SKIP' if args.skip_captions else 'DOWNLOAD'}")
    print(f"  Audio:    {'SKIP' if args.skip_audio else 'DOWNLOAD'}")

    caption_ok = 0
    caption_fail = 0
    audio_ok = 0
    audio_fail = 0

    for i, video in enumerate(videos_to_download):
        vid = video["id"]
        platform = video["platform"]
        title = video["title"][:60]
        duration_min = (video.get("duration") or 0) / 60
        creator_name = video.get("creator_name", "unknown")

        print(f"\n[{i+1}/{len(videos_to_download)}] {vid} | {platform} | {duration_min:.1f}min | {creator_name}")
        print(f"  {title}")

        if not args.skip_captions:
            caption_exists = os.path.exists(os.path.join(CAPTIONS_DIR, f"{vid}.en.srt"))
            if caption_exists:
                caption_ok += 1
            elif platform == "youtube":
                if download_youtube_captions(vid):
                    caption_ok += 1
                    print(f"  ✓ Captions downloaded")
                else:
                    caption_fail += 1
                    print(f"  ✗ Captions failed")
            elif platform == "vimeo":
                if download_vimeo_captions(vid):
                    caption_ok += 1
                    print(f"  ✓ Captions downloaded")
                else:
                    caption_fail += 1
                    print(f"  ✗ Captions failed (may not have captions)")

        if not args.skip_audio:
            audio_exists = os.path.exists(os.path.join(AUDIO_DIR, f"{vid}.wav"))
            if audio_exists:
                audio_ok += 1
            elif platform == "youtube":
                if download_youtube_audio(vid):
                    audio_ok += 1
                    print(f"  ✓ Audio downloaded")
                else:
                    audio_fail += 1
                    print(f"  ✗ Audio failed")
            elif platform == "vimeo":
                if download_vimeo_audio(vid):
                    audio_ok += 1
                    print(f"  ✓ Audio downloaded")
                else:
                    audio_fail += 1
                    print(f"  ✗ Audio failed")

        time.sleep(1)

    print(f"\n{'='*60}")
    print(f"COMPLETE")
    print(f"  Captions: {caption_ok} ok, {caption_fail} failed")
    print(f"  Audio:    {audio_ok} ok, {audio_fail} failed")
    print(f"  Catalog:  {len(catalog)} total videos")


if __name__ == "__main__":
    main()