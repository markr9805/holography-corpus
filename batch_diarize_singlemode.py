#!/usr/bin/env python3
"""
Batch diarize singlemode (HoloTalk) videos.
Downloads audio on demand, diarizes with num_speakers=2, cleans up audio after.
Loads pyannote pipeline once for efficiency.
"""

import json
import os
import subprocess
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CATALOG_FILE = os.path.join(SCRIPT_DIR, "catalog.json")
TRANSCRIPTS_DIR = os.path.join(SCRIPT_DIR, "transcripts")
AUDIO_DIR = os.path.join(SCRIPT_DIR, "audio")

# Use Darante's diarize-env which has pyannote working
DIARIZE_VENV = "/Users/mark/.openclaw/workspace/foster/darante-transcript-pilot/diarize-env"

def get_hf_token():
    token = os.environ.get("HF_TOKEN")
    if token:
        return token
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


def download_audio(video_id):
    """Download audio as WAV from YouTube."""
    out_file = os.path.join(AUDIO_DIR, f"{video_id}.wav")
    if os.path.exists(out_file):
        return True
    os.makedirs(AUDIO_DIR, exist_ok=True)
    result = subprocess.run(
        ["yt-dlp", "-x", "--audio-format", "wav",
         "-o", os.path.join(AUDIO_DIR, f"{video_id}.%(ext)s"),
         f"https://www.youtube.com/watch?v={video_id}"],
        capture_output=True, text=True, timeout=600
    )
    return os.path.exists(out_file)


def main():
    token = get_hf_token()
    if not token:
        print("Error: No HF_TOKEN found")
        sys.exit(1)

    # Find singlemode videos that are transcribed but not diarized
    with open(CATALOG_FILE) as f:
        catalog = json.load(f)
    
    transcripts = set(os.listdir(TRANSCRIPTS_DIR))
    
    sm = [v for v in catalog if v.get("creator_id") == "singlemode"]
    need_diarize = []
    for v in sm:
        vid = v["id"]
        has_transcript = (f"{vid}-parakeet.srt" in transcripts or 
                         f"{vid}-whisper-largev3.txt" in transcripts)
        has_diarization = f"{vid}-diarization.json" in transcripts
        if has_transcript and not has_diarization:
            need_diarize.append(v)
    
    # Sort by duration (shorter first for quick wins)
    need_diarize.sort(key=lambda v: v.get("duration", 999999))
    
    print(f"Found {len(need_diarize)} singlemode videos to diarize")
    
    # Load pyannote pipeline once
    sys.path.insert(0, os.path.join(DIARIZE_VENV, "lib"))
    import torch
    from pyannote.audio import Pipeline
    
    print("Loading pyannote speaker-diarization-3.1...")
    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        token=token,
    )
    print("Pipeline loaded.")
    
    processed = 0
    failed = 0
    
    for i, video in enumerate(need_diarize):
        vid = video["id"]
        title = video.get("title", vid)[:60]
        duration = video.get("duration", 0)
        
        print(f"\n[{i+1}/{len(need_diarize)}] {vid} ({duration:.0f}s) — {title}")
        
        # Download audio if needed
        audio_path = os.path.join(AUDIO_DIR, f"{vid}.wav")
        if not os.path.exists(audio_path):
            print(f"  Downloading audio...")
            if not download_audio(vid):
                print(f"  FAILED to download audio, skipping")
                failed += 1
                continue
        
        # Diarize
        output_path = os.path.join(TRANSCRIPTS_DIR, f"{vid}-diarization.json")
        start = time.time()
        try:
            result = pipeline(audio_path, num_speakers=2)
            elapsed = time.time() - start
            
            turns = []
            for turn, _, speaker in result.itertracks(yield_label=True):
                turns.append({
                    "start": round(turn.start, 2),
                    "end": round(turn.end, 2),
                    "speaker": speaker,
                })
            
            output = {
                "video_id": vid,
                "num_speakers_detected": len(set(t["speaker"] for t in turns)),
                "num_speakers_hint": 2,
                "duration": round(turns[-1]["end"], 2) if turns else 0,
                "processing_time_seconds": round(elapsed, 1),
                "device": "cpu",
                "turns": turns,
            }
            
            with open(output_path, "w") as f:
                json.dump(output, f, indent=2)
            
            speakers = sorted(set(t["speaker"] for t in turns))
            print(f"  Done in {elapsed:.0f}s — {len(turns)} turns, speakers: {speakers}")
            processed += 1
            
        except Exception as e:
            print(f"  Error: {e}")
            failed += 1
        
        # Clean up audio to save disk
        if os.path.exists(audio_path) and os.path.exists(output_path):
            os.remove(audio_path)
            print(f"  Cleaned up audio")
    
    print(f"\n{'='*60}")
    print(f"Processed: {processed}, Failed: {failed}, Total: {len(need_diarize)}")


if __name__ == "__main__":
    main()