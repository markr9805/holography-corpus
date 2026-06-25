#!/usr/bin/env python3
"""
Holography Transcript Pipeline
===============================
Full pipeline: Download → Whisper Large-V3 → Parakeet TDT → Merge → Label → Correct → Diarize
Processes in batches to manage disk space.

Supports multi-creator catalog with YouTube and Vimeo sources.

Default transcription: Whisper Large-V3 + Parakeet TDT (no Turbo).
Three sources (Large-V3, Parakeet, YouTube captions) are merged for best accuracy.

Usage:
    python3 pipeline.py [--batch-size 15] [--start 0]
                         [--creator CREATOR_ID] [--skip-download] [--skip-whisper]
                         [--skip-parakeet] [--skip-merge] [--skip-label]
                         [--skip-correct] [--skip-diarize] [--no-clean-audio]
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
CATALOG_FILE = os.path.join(PIPELINE_DIR, "catalog.json")
CREATORS_FILE = os.path.join(PIPELINE_DIR, "creators.json")
CAPTIONS_DIR = os.path.join(PIPELINE_DIR, "captions")
AUDIO_DIR = os.path.join(PIPELINE_DIR, "audio")
CHUNKS_DIR = os.path.join(PIPELINE_DIR, "chunks")
TRANSCRIPTS_DIR = os.path.join(PIPELINE_DIR, "transcripts")
VENV_PYTHON = os.path.join(PIPELINE_DIR, "whisper-env", "bin", "python3")

WHISPER_MODEL = "mlx-community/whisper-large-v3-mlx"
PARAKEET_MODEL = "mlx-community/parakeet-tdt-0.6b-v3"
PARAKEET_BIN = os.path.expanduser("~/.local/bin/parakeet-mlx")
DIARIZE_SCRIPT = os.path.join(PIPELINE_DIR, "06_diarize.py")

CHUNK_SECS = 300
CHUNK_OVERLAP_SECS = 10


def load_catalog():
    """Load or fetch video catalog."""
    if not os.path.exists(CATALOG_FILE):
        print("No catalog found. Run 01_download.py or scan_channels.py first.")
        sys.exit(1)
    with open(CATALOG_FILE) as f:
        return json.load(f)


def download_captions(video_ids, platform="youtube"):
    """Download captions for a list of video IDs."""
    os.makedirs(CAPTIONS_DIR, exist_ok=True)
    ok, fail = 0, 0
    for vid in video_ids:
        out_file = os.path.join(CAPTIONS_DIR, f"{vid}.en.srt")
        if os.path.exists(out_file):
            ok += 1
            continue

        if platform == "vimeo":
            url = f"https://vimeo.com/{vid}"
            result = subprocess.run(
                ["yt-dlp", "--write-subs", "--sub-lang", "en",
                 "--sub-format", "srt", "--skip-download",
                 "-o", os.path.join(CAPTIONS_DIR, vid), url],
                capture_output=True, text=True, timeout=60
            )
            if not os.path.exists(out_file):
                result = subprocess.run(
                    ["yt-dlp", "--write-auto-sub", "--sub-lang", "en",
                     "--sub-format", "srt", "--skip-download",
                     "-o", os.path.join(CAPTIONS_DIR, vid), url],
                    capture_output=True, text=True, timeout=60
                )
        else:
            url = f"https://www.youtube.com/watch?v={vid}"
            result = subprocess.run(
                ["yt-dlp", "--write-auto-sub", "--sub-lang", "en",
                 "--sub-format", "srt", "--skip-download",
                 "-o", os.path.join(CAPTIONS_DIR, vid), url],
                capture_output=True, text=True, timeout=60
            )

        if os.path.exists(out_file):
            ok += 1
            print(f"    ✓ {vid} captions")
        else:
            fail += 1
            print(f"    ✗ {vid} captions failed")
        time.sleep(1)
    return ok, fail


def download_audio(video_ids, platform="youtube"):
    """Download audio as WAV for a list of video IDs."""
    os.makedirs(AUDIO_DIR, exist_ok=True)
    ok, fail = 0, 0
    for vid in video_ids:
        out_file = os.path.join(AUDIO_DIR, f"{vid}.wav")
        if os.path.exists(out_file):
            ok += 1
            continue

        if platform == "vimeo":
            url = f"https://vimeo.com/{vid}"
        else:
            url = f"https://www.youtube.com/watch?v={vid}"

        result = subprocess.run(
            ["yt-dlp", "-x", "--audio-format", "wav",
             "-o", os.path.join(AUDIO_DIR, f"{vid}.%(ext)s"), url],
            capture_output=True, text=True, timeout=600
        )
        if result.returncode == 0 and os.path.exists(out_file):
            ok += 1
            print(f"    ✓ {vid} audio")
        else:
            fail += 1
            print(f"    ✗ {vid} audio failed")
        time.sleep(1)
    return ok, fail


def chunk_audio(video_id):
    """Split audio into chunks. Returns list of chunk file paths."""
    audio_file = None
    for ext in [".wav", ".mp3", ".m4a", ".flac"]:
        path = os.path.join(AUDIO_DIR, f"{video_id}{ext}")
        if os.path.exists(path):
            audio_file = path
            break
    if not audio_file:
        return []

    import wave
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
        actual_duration = min(CHUNK_SECS + CHUNK_OVERLAP_SECS, duration - start)
        subprocess.run(
            ["ffmpeg", "-y", "-i", audio_file,
             "-ss", str(start), "-t", str(actual_duration),
             "-c", "copy", chunk_file],
            capture_output=True
        )
        chunks.append(chunk_file)
        i += 1
        start += CHUNK_SECS
    return chunks


def run_whisper(video_id):
    """Run Whisper Large-V3 on chunked audio. Returns True on success."""
    out_file = os.path.join(TRANSCRIPTS_DIR, f"{video_id}-whisper-largev3.txt")
    if os.path.exists(out_file):
        return True

    chunks = chunk_audio(video_id)
    if not chunks:
        return False

    texts = []
    for chunk_file in chunks:
        script = f"""
import mlx_whisper
result = mlx_whisper.transcribe(
    '{chunk_file}',
    path_or_hf_repo='{WHISPER_MODEL}',
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
            print(f"      ERROR on chunk: {result.stderr[:200]}")
            for cf in chunks:
                if os.path.exists(cf):
                    os.remove(cf)
            return False
        texts.append(result.stdout.strip())

    combined = "\n\n".join(texts)
    os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)
    with open(out_file, "w") as f:
        f.write(combined)

    for cf in chunks:
        if os.path.exists(cf):
            os.remove(cf)

    return True


def run_parakeet(video_id):
    """Run Parakeet TDT on audio file. Returns True on success."""
    out_file = os.path.join(TRANSCRIPTS_DIR, f"{video_id}-parakeet.srt")
    if os.path.exists(out_file):
        return True

    audio_file = None
    for ext in [".wav", ".mp3", ".m4a", ".flac"]:
        path = os.path.join(AUDIO_DIR, f"{video_id}{ext}")
        if os.path.exists(path):
            audio_file = path
            break
    if not audio_file:
        return False

    result = subprocess.run(
        [PARAKEET_BIN, "--model", PARAKEET_MODEL, "--format", "srt", audio_file],
        capture_output=True, text=True, timeout=600
    )
    if result.returncode == 0 and result.stdout.strip():
        with open(out_file, "w") as f:
            f.write(result.stdout.strip())
        return True
    else:
        print(f"      Parakeet error: {result.stderr[:200]}")
        return False


def clean_audio(video_ids):
    """Delete audio files for given video IDs to free disk space."""
    freed = 0
    for vid in video_ids:
        for ext in [".wav", ".mp3", ".m4a", ".flac"]:
            audio_file = os.path.join(AUDIO_DIR, f"{vid}{ext}")
            if os.path.exists(audio_file):
                size = os.path.getsize(audio_file)
                os.remove(audio_file)
                freed += size
    return freed / (1024**3)  # GB


def get_disk_free():
    """Get free disk space in GB."""
    stat = os.statvfs(PIPELINE_DIR)
    return (stat.f_bavail * stat.f_frsize) / (1024**3)


def main():
    parser = argparse.ArgumentParser(description="Full holography transcript pipeline")
    parser.add_argument("--batch-size", type=int, default=15, help="Videos per batch")
    parser.add_argument("--start", type=int, default=0, help="Start from video index")
    parser.add_argument("--creator", help="Only process videos from this creator")
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--skip-whisper", action="store_true")
    parser.add_argument("--skip-parakeet", action="store_true")
    parser.add_argument("--skip-merge", action="store_true")
    parser.add_argument("--skip-label", action="store_true")
    parser.add_argument("--skip-correct", action="store_true")
    parser.add_argument("--skip-diarize", action="store_true")
    parser.add_argument("--no-clean-audio", action="store_true", help="Keep audio after transcription (needed for diarization)")
    args = parser.parse_args()

    # Keep audio if diarization is not skipped (diarization needs audio)
    clean_audio_flag = args.skip_diarize and not args.no_clean_audio

    videos = load_catalog()
    if args.creator:
        videos = [v for v in videos if v.get("creator_id") == args.creator]
    videos = videos[args.start:]

    os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)

    total_videos = len(videos)
    batch_num = 0

    print(f"{'='*60}")
    print(f"HOLOGRAPHY TRANSCRIPT PIPELINE")
    print(f"{'='*60}")
    print(f"Videos: {total_videos} (starting from index {args.start})")
    print(f"Batch size: {args.batch_size}")
    print(f"Transcription: Whisper Large-V3 + Parakeet TDT")
    print(f"Diarization: {'enabled' if not args.skip_diarize else 'skipped'}")
    print(f"Clean audio after diarize: {clean_audio_flag}")
    print(f"Disk free: {get_disk_free():.1f} GB")
    print()

    pipeline_start = time.time()

    for i in range(0, total_videos, args.batch_size):
        batch = videos[i:i + args.batch_size]
        batch_ids = [v["id"] for v in batch]
        batch_num += 1

        print(f"\n{'─'*60}")
        print(f"BATCH {batch_num}: {len(batch)} videos (index {args.start + i}-{args.start + i + len(batch) - 1})")
        print(f"Disk free: {get_disk_free():.1f} GB")
        print(f"{'─'*60}")

        # Step 1: Download
        if not args.skip_download:
            print(f"\n  [1/7] Downloading captions + audio...")
            yt_videos = [v for v in batch if v.get("platform") == "youtube"]
            vimeo_videos = [v for v in batch if v.get("platform") == "vimeo"]

            cap_ok, cap_fail = 0, 0
            aud_ok, aud_fail = 0, 0

            if yt_videos:
                c_ok, c_fail = download_captions([v["id"] for v in yt_videos], "youtube")
                cap_ok += c_ok; cap_fail += c_fail
                a_ok, a_fail = download_audio([v["id"] for v in yt_videos], "youtube")
                aud_ok += a_ok; aud_fail += a_fail

            if vimeo_videos:
                c_ok, c_fail = download_captions([v["id"] for v in vimeo_videos], "vimeo")
                cap_ok += c_ok; cap_fail += c_fail
                a_ok, a_fail = download_audio([v["id"] for v in vimeo_videos], "vimeo")
                aud_ok += a_ok; aud_fail += a_fail

            print(f"  Captions: {cap_ok} ok, {cap_fail} fail | Audio: {aud_ok} ok, {aud_fail} fail")

        # Step 2: Whisper Large-V3
        if not args.skip_whisper:
            print(f"\n  [2/7] Running Whisper Large-V3...")
            ok, fail = 0, 0
            for v in batch:
                start = time.time()
                success = run_whisper(v["id"])
                elapsed = time.time() - start
                if success:
                    ok += 1
                else:
                    fail += 1
                    print(f"    ✗ {v['id']} whisper failed ({elapsed:.0f}s)")
            print(f"  Whisper Large-V3: {ok} ok, {fail} fail")

        # Step 3: Parakeet TDT
        if not args.skip_parakeet:
            print(f"\n  [3/7] Running Parakeet TDT...")
            pk_ok, pk_fail = 0, 0
            for v in batch:
                vid = v["id"]
                start = time.time()
                success = run_parakeet(vid)
                elapsed = time.time() - start
                if success:
                    pk_ok += 1
                    print(f"    ✓ {vid} parakeet ({elapsed:.0f}s)")
                else:
                    pk_fail += 1
            print(f"  Parakeet: {pk_ok} ok, {pk_fail} fail")

        # Step 4: Diarize (needs audio, so run before cleaning)
        if not args.skip_diarize:
            print(f"\n  [4/7] Running speaker diarization...")
            diarize_args = [sys.executable, DIARIZE_SCRIPT]
            # Run per-video to match batch
            for v in batch:
                vid = v["id"]
                if not find_audio(vid):
                    continue
                diar_out = os.path.join(TRANSCRIPTS_DIR, f"{vid}-diarization.json")
                if os.path.exists(diar_out):
                    continue
                result = subprocess.run(
                    [sys.executable, DIARIZE_SCRIPT, "--video", vid, "--device", "mps"],
                    capture_output=True, text=True, timeout=600
                )
                if result.returncode == 0:
                    print(f"    ✓ {vid} diarized")
                else:
                    print(f"    ✗ {vid} diarization failed: {result.stderr[:100]}")

        # Clean up audio to free disk space (only after diarization)
        if clean_audio_flag:
            freed = clean_audio(batch_ids)
            print(f"\n  Cleaned audio: freed {freed:.2f} GB")
            print(f"  Disk free: {get_disk_free():.1f} GB")

    # Step 5: Merge
    if not args.skip_merge:
        print(f"\n{'─'*60}")
        print(f"  [5/7] Merging transcripts...")
        result = subprocess.run(
            [sys.executable, os.path.join(PIPELINE_DIR, "03_merge.py"), "--all"],
            capture_output=True, text=True
        )
        print(result.stdout)
        if result.returncode != 0:
            print(f"Merge errors: {result.stderr}")

    # Step 6: Label flags
    if not args.skip_label:
        print(f"\n{'─'*60}")
        print(f"  [6/7] Labelling flags...")
        result = subprocess.run(
            [sys.executable, os.path.join(PIPELINE_DIR, "04_label.py"), "--all"],
            capture_output=True, text=True
        )
        print(result.stdout)
        if result.returncode != 0:
            print(f"Label errors: {result.stderr}")

    # Step 7: Apply corrections
    if not args.skip_correct:
        print(f"\n{'─'*60}")
        print(f"  [7/7] Applying corrections...")
        result = subprocess.run(
            [sys.executable, os.path.join(PIPELINE_DIR, "05_correct.py"), "--all"],
            capture_output=True, text=True
        )
        print(result.stdout)
        if result.returncode != 0:
            print(f"Correction errors: {result.stderr}")

    total_elapsed = time.time() - pipeline_start
    print(f"\n{'='*60}")
    print(f"PIPELINE COMPLETE")
    print(f"Time: {total_elapsed/3600:.1f} hours")
    print(f"Disk free: {get_disk_free():.1f} GB")
    print(f"{'='*60}")


def find_audio(video_id):
    """Find audio file for a video ID."""
    for ext in [".wav", ".mp3", ".m4a", ".flac"]:
        path = os.path.join(AUDIO_DIR, f"{video_id}{ext}")
        if os.path.exists(path):
            return path
    return None


if __name__ == "__main__":
    main()