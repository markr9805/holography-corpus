#!/usr/bin/env python3
"""
Holography Transcript Pipeline
===============================
Step 2: Run Whisper (Turbo + Large-V3) on chunked audio.

Adapted from the Darante pipeline. Supports multi-creator catalog.

Usage:
    python3 02_whisper.py [--limit N] [--model MODEL] [--resume] [--chunk-secs 300]
                          [--creator CREATOR_ID]
"""

import argparse
import json
import os
import subprocess
import sys
import time
import wave

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
CATALOG_FILE = os.path.join(OUTPUT_DIR, "catalog.json")
AUDIO_DIR = os.path.join(OUTPUT_DIR, "audio")
CHUNKS_DIR = os.path.join(OUTPUT_DIR, "chunks")
TRANSCRIPTS_DIR = os.path.join(OUTPUT_DIR, "transcripts")

MODELS = {
    "turbo": "mlx-community/whisper-large-v3-turbo",
    "largev3": "mlx-community/whisper-large-v3-mlx",
}

VENV_PYTHON = os.path.join(OUTPUT_DIR, "whisper-env", "bin", "python3")


def get_videos(creator_id=None):
    """Load video list from catalog."""
    with open(CATALOG_FILE) as f:
        videos = json.load(f)
    if creator_id:
        videos = [v for v in videos if v.get("creator_id") == creator_id]
    return videos


def chunk_audio(video_id, chunk_secs=300, overlap_secs=10):
    """Split audio into chunks with overlap. Returns list of chunk file paths."""
    audio_file = None
    for ext in [".wav", ".mp3", ".m4a", ".flac"]:
        path = os.path.join(AUDIO_DIR, f"{video_id}{ext}")
        if os.path.exists(path):
            audio_file = path
            break
    if not audio_file:
        return []

    with wave.open(audio_file, 'rb') as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        duration = frames / rate

    os.makedirs(CHUNKS_DIR, exist_ok=True)
    chunks = []
    start = 0
    i = 0
    while start < duration:
        chunk_file = os.path.join(CHUNKS_DIR, f"{video_id}_chunk_{i:03d}.wav")
        actual_duration = min(chunk_secs + overlap_secs, duration - start)

        cmd = [
            "ffmpeg", "-y", "-i", audio_file,
            "-ss", str(start), "-t", str(actual_duration),
            "-c", "copy", chunk_file
        ]
        subprocess.run(cmd, capture_output=True)
        chunks.append(chunk_file)
        i += 1
        start += chunk_secs

    return chunks


def transcribe_chunk(chunk_file, model_name, model_repo):
    """Run Whisper on a single chunk. Returns transcript text."""
    script = f"""
import mlx_whisper
result = mlx_whisper.transcribe(
    '{chunk_file}',
    path_or_hf_repo='{model_repo}',
    language='en',
    word_timestamps=False
)
print(result['text'])
"""
    result = subprocess.run(
        [VENV_PYTHON, "-c", script],
        capture_output=True, text=True, timeout=600
    )
    if result.returncode != 0:
        print(f"  ERROR: {result.stderr[:200]}", file=sys.stderr)
        return None
    return result.stdout.strip()


def transcribe_video(video_id, model_key, model_repo, chunk_secs, resume):
    """Transcribe a full video using chunked processing."""
    out_file = os.path.join(TRANSCRIPTS_DIR, f"{video_id}-whisper-{model_key}.txt")
    if resume and os.path.exists(out_file):
        return True

    chunks = chunk_audio(video_id, chunk_secs)
    if not chunks:
        return False

    texts = []
    for i, chunk_file in enumerate(chunks):
        text = transcribe_chunk(chunk_file, model_key, model_repo)
        if text is None:
            # Clean up chunks
            for cf in chunks:
                if os.path.exists(cf):
                    os.remove(cf)
            return False
        texts.append(text)

    combined = "\n\n".join(texts)
    os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)
    with open(out_file, "w") as f:
        f.write(combined)

    # Clean up chunks
    for cf in chunks:
        if os.path.exists(cf):
            os.remove(cf)

    return True


def main():
    parser = argparse.ArgumentParser(description="Run Whisper transcription")
    parser.add_argument("--limit", type=int, help="Only process N videos")
    parser.add_argument("--creator", help="Only process videos from this creator")
    parser.add_argument("--model", choices=["largev3", "turbo", "both"], default="largev3",
                        help="Whisper model (default: largev3 for best accuracy on holography terminology)")
    parser.add_argument("--resume", action="store_true", help="Skip existing transcripts")
    parser.add_argument("--chunk-secs", type=int, default=300, help="Chunk duration in seconds")
    args = parser.parse_args()

    os.makedirs(CHUNKS_DIR, exist_ok=True)
    os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)

    videos = get_videos(args.creator)
    if args.limit:
        videos = videos[:args.limit]

    models_to_run = []
    if args.model in ("turbo", "both"):
        models_to_run.append(("turbo", MODELS["turbo"]))
    if args.model in ("largev3", "both"):
        models_to_run.append(("largev3", MODELS["largev3"]))

    print(f"\nProcessing {len(videos)} videos with {len(models_to_run)} model(s)")
    print(f"  Models: {[m[0] for m in models_to_run]}")
    print(f"  Chunk size: {args.chunk_secs}s")

    total_start = time.time()
    stats = {m[0]: {"ok": 0, "fail": 0} for m in models_to_run}

    for i, video in enumerate(videos):
        vid = video["id"]
        creator = video.get("creator_name", "unknown")
        print(f"[{i+1}/{len(videos)}] {vid} ({creator})")

        for model_key, model_repo in models_to_run:
            out_file = os.path.join(TRANSCRIPTS_DIR, f"{vid}-whisper-{model_key}.txt")
            if args.resume and os.path.exists(out_file):
                print(f"  {model_key}: SKIP (exists)")
                stats[model_key]["ok"] += 1
                continue

            start = time.time()
            ok = transcribe_video(vid, model_key, model_repo, args.chunk_secs, args.resume)
            elapsed = time.time() - start

            if ok:
                stats[model_key]["ok"] += 1
                print(f"  {model_key}: ✓ ({elapsed:.1f}s)")
            else:
                stats[model_key]["fail"] += 1
                print(f"  {model_key}: ✗ ({elapsed:.1f}s)")

    total_elapsed = time.time() - total_start
    print(f"\n{'='*60}")
    print(f"COMPLETE in {total_elapsed/3600:.1f} hours")
    for model_key, model_repo in models_to_run:
        s = stats[model_key]
        print(f"  {model_key}: {s['ok']} ok, {s['fail']} failed")


if __name__ == "__main__":
    main()