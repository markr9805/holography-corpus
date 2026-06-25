#!/usr/bin/env python3
"""
Holography Transcript Pipeline
===============================
Step 6: Speaker Diarization

Uses pyannote-audio 3.1 to identify who speaks when in each video.
Produces per-video diarization JSON files that can be merged with
the existing transcripts to add speaker labels.

Reused from Darante pipeline with multi-creator catalog support.

Requirements:
  - Use the diarize-env venv (not .venv, which has lib conflicts)
  - HF_TOKEN env var or cached ~/.cache/huggingface/token
  - pyannote/speaker-diarization-3.1 model access (accept terms on HF)

Usage:
    python3 06_diarize.py --video VIDEO_ID
    python3 06_diarize.py --all
    python3 06_diarize.py --creator CREATOR_ID
    python3 06_diarize.py --video VIDEO_ID --num-speakers 2
    python3 06_diarize.py --all --device mps
"""

import argparse
import json
import os
import sys
import time
import warnings

warnings.filterwarnings("ignore", message="std\\(\\): degrees of freedom")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TRANSCRIPTS_DIR = os.path.join(SCRIPT_DIR, "transcripts")
AUDIO_DIR = os.path.join(SCRIPT_DIR, "audio")
CATALOG_FILE = os.path.join(SCRIPT_DIR, "catalog.json")
DIARIZE_VENV = os.path.join(SCRIPT_DIR, "diarize-env")


def get_hf_token():
    """Get HuggingFace token from env var or cached file."""
    token = os.environ.get("HF_TOKEN")
    if token:
        return token
    # Try loading from .env file
    env_file = os.path.join(SCRIPT_DIR, ".env")
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line.startswith("HF_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    if token and token != "your_token_here":
                        return token
    cache_path = os.path.expanduser("~/.cache/huggingface/token")
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            token = f.read().strip()
        if token:
            return token
    return None


def load_catalog():
    """Load video catalog."""
    if not os.path.exists(CATALOG_FILE):
        print(f"Error: catalog.json not found at {CATALOG_FILE}")
        sys.exit(1)
    with open(CATALOG_FILE) as f:
        return json.load(f)


def find_audio(video_id):
    """Find audio file for a video ID."""
    for ext in [".wav", ".mp3", ".m4a", ".flac"]:
        path = os.path.join(AUDIO_DIR, f"{video_id}{ext}")
        if os.path.exists(path):
            return path
    return None


def diarize_video(video_id, pipeline, num_speakers=None, device="cpu"):
    """Run diarization on a single video."""
    audio_path = find_audio(video_id)
    if not audio_path:
        print(f"  No audio found for {video_id}")
        return None

    output_path = os.path.join(TRANSCRIPTS_DIR, f"{video_id}-diarization.json")
    if os.path.exists(output_path):
        print(f"  Already diarized: {video_id}")
        return output_path

    print(f"  Processing {video_id}...")
    start = time.time()

    try:
        kwargs = {}
        if num_speakers:
            kwargs["num_speakers"] = num_speakers

        result = pipeline(audio_path, **kwargs)
        elapsed = time.time() - start

        turns = []
        for turn, _, speaker in result.speaker_diarization.itertracks(yield_label=True):
            turns.append({
                "start": round(turn.start, 2),
                "end": round(turn.end, 2),
                "speaker": speaker,
            })

        output = {
            "video_id": video_id,
            "num_speakers_detected": len(set(t["speaker"] for t in turns)),
            "duration": round(turns[-1]["end"], 2) if turns else 0,
            "processing_time_seconds": round(elapsed, 1),
            "device": device,
            "turns": turns,
        }

        os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(output, f, indent=2)

        speakers = sorted(set(t["speaker"] for t in turns))
        print(f"  Done in {elapsed:.0f}s — {len(turns)} turns, speakers: {speakers}")
        return output_path

    except Exception as e:
        print(f"  Error processing {video_id}: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description="Speaker diarization for holography transcripts")
    parser.add_argument("--video", help="Process a specific video ID")
    parser.add_argument("--creator", help="Process all videos from this creator")
    parser.add_argument("--all", action="store_true", help="Process all videos with audio but no diarization")
    parser.add_argument("--num-speakers", type=int, help="Number of speakers (default: auto-detect)")
    parser.add_argument("--device", default="cpu", choices=["cpu", "mps", "cuda"], help="Compute device")
    parser.add_argument("--min-duration", type=float, default=5.0, help="Skip videos shorter than N seconds")
    parser.add_argument("--batch-size", type=int, default=10, help="Process N videos before reloading pipeline")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if not args.video and not args.all and not args.creator:
        print("Specify --video VIDEO_ID, --creator CREATOR_ID, or --all")
        return

    token = get_hf_token()
    if not token:
        print("Error: No HF_TOKEN found. Set HF_TOKEN env var, add to .env, or login with `huggingface-cli login`")
        sys.exit(1)

    import torch
    from pyannote.audio import Pipeline

    device = args.device
    if device == "mps" and not torch.backends.mps.is_available():
        print("MPS not available, falling back to CPU")
        device = "cpu"

    print(f"Loading pyannote speaker-diarization-3.1 on {device}...")
    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        token=token,
    )

    if device != "cpu":
        pipeline = pipeline.to(torch.device(device))

    print("Pipeline loaded.")

    catalog = load_catalog()

    if args.video:
        videos = [v for v in catalog if v["id"] == args.video]
        if not videos:
            print(f"Video {args.video} not found in catalog")
            return
    elif args.creator:
        videos = [v for v in catalog if v.get("creator_id") == args.creator]
        if not videos:
            print(f"No videos found for creator {args.creator}")
            return
    else:
        # Find videos with audio but no diarization
        videos = []
        for v in catalog:
            audio_path = find_audio(v["id"])
            diar_path = os.path.join(TRANSCRIPTS_DIR, f"{v['id']}-diarization.json")
            if audio_path and not os.path.exists(diar_path):
                videos.append(v)
        # Sort by duration if available (shorter first)
        videos.sort(key=lambda v: v.get("duration", 999999))

    print(f"Found {len(videos)} videos to diarize")

    processed = 0
    failed = 0

    for i, video in enumerate(videos):
        vid = video["id"]
        title = video.get("title", vid)[:60]
        creator = video.get("creator_name", "unknown")
        print(f"\n[{i+1}/{len(videos)}] {vid} — {creator}: {title}")

        result = diarize_video(vid, pipeline, num_speakers=args.num_speakers, device=device)
        if result:
            processed += 1
        else:
            failed += 1

        # Reload pipeline every batch_size videos to free memory
        if (i + 1) % args.batch_size == 0 and i + 1 < len(videos):
            print(f"\n--- Reloading pipeline (batch boundary) ---")
            del pipeline
            torch.cuda.empty_cache() if torch.cuda.is_available() else None
            pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                token=token,
            )
            if device != "cpu":
                pipeline = pipeline.to(torch.device(device))

    print(f"\n{'='*60}")
    print(f"Processed: {processed}, Failed: {failed}, Total: {len(videos)}")


if __name__ == "__main__":
    main()