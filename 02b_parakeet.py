#!/usr/bin/env python3
"""
Holography Transcript Pipeline
===============================
Step 2b: Run Parakeet TDT on audio files.

Parakeet TDT is a fast, accurate transcription model that complements Whisper.
It's particularly good at proper nouns and technical terms.

Usage:
    python3 02b_parakeet.py [--limit N] [--creator CREATOR_ID] [--resume]
"""

import argparse
import json
import os
import subprocess
import sys
import time

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
CATALOG_FILE = os.path.join(OUTPUT_DIR, "catalog.json")
AUDIO_DIR = os.path.join(OUTPUT_DIR, "audio")
TRANSCRIPTS_DIR = os.path.join(OUTPUT_DIR, "transcripts")

PARAKEET_BIN = os.path.expanduser("~/.local/bin/parakeet-mlx")
PARAKEET_MODEL = "mlx-community/parakeet-tdt-0.6b-v3"


def get_videos(creator_id=None):
    """Load video list from catalog."""
    with open(CATALOG_FILE) as f:
        videos = json.load(f)
    if creator_id:
        videos = [v for v in videos if v.get("creator_id") == creator_id]
    return videos


def transcribe_video(video_id):
    """Run Parakeet TDT on a single video's audio file. Returns SRT text."""
    # Find audio file
    audio_file = None
    for ext in [".wav", ".mp3", ".m4a", ".flac"]:
        path = os.path.join(AUDIO_DIR, f"{video_id}{ext}")
        if os.path.exists(path):
            audio_file = path
            break

    if not audio_file:
        print(f"  No audio file found for {video_id}")
        return None

    # Run Parakeet
    cmd = [
        PARAKEET_BIN,
        "--model", PARAKEET_MODEL,
        "--format", "srt",
        audio_file
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    if result.returncode != 0:
        print(f"  ERROR: {result.stderr[:200]}", file=sys.stderr)
        return None

    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description="Run Parakeet TDT transcription")
    parser.add_argument("--limit", type=int, help="Only process N videos")
    parser.add_argument("--creator", help="Only process videos from this creator")
    parser.add_argument("--resume", action="store_true", help="Skip existing transcripts")
    args = parser.parse_args()

    os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)

    videos = get_videos(args.creator)
    if args.limit:
        videos = videos[:args.limit]

    # Filter to videos that have audio
    processable = []
    for v in videos:
        vid = v["id"]
        out_file = os.path.join(TRANSCRIPTS_DIR, f"{vid}-parakeet.srt")
        if args.resume and os.path.exists(out_file):
            continue
        has_audio = any(
            os.path.exists(os.path.join(AUDIO_DIR, f"{vid}{ext}"))
            for ext in [".wav", ".mp3", ".m4a", ".flac"]
        )
        if has_audio:
            processable.append(v)

    print(f"\nParakeet TDT Transcription")
    print(f"  Videos to process: {len(processable)}")
    print(f"  Model: {PARAKEET_MODEL}")

    total_start = time.time()
    ok = 0
    fail = 0

    for i, video in enumerate(processable):
        vid = video["id"]
        creator = video.get("creator_name", "unknown")
        title = video.get("title", vid)[:50]
        print(f"[{i+1}/{len(processable)}] {vid} | {creator} | {title}")

        start = time.time()
        srt_text = transcribe_video(vid)
        elapsed = time.time() - start

        if srt_text:
            out_file = os.path.join(TRANSCRIPTS_DIR, f"{vid}-parakeet.srt")
            with open(out_file, "w") as f:
                f.write(srt_text)
            ok += 1
            print(f"  ✓ ({elapsed:.1f}s)")
        else:
            fail += 1
            print(f"  ✗ ({elapsed:.1f}s)")

    total_elapsed = time.time() - total_start
    print(f"\n{'='*60}")
    print(f"COMPLETE in {total_elapsed/3600:.1f} hours")
    print(f"  OK: {ok}, Failed: {fail}")


if __name__ == "__main__":
    main()