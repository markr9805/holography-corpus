#!/usr/bin/env python3
"""
Holography Transcript Pipeline
===============================
Step 5: Apply correction dictionary to merged transcripts.

Reads the growing corrections.json and applies known corrections
to merged transcripts before final output.

Reused from Darante pipeline with holography-specific term support.

Usage:
    python3 05_correct.py [--video VIDEO_ID] [--all] [--dry-run]
"""

import argparse
import json
import os
import re

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
TRANSCRIPTS_DIR = os.path.join(OUTPUT_DIR, "transcripts")
CORRECTIONS_FILE = os.path.join(OUTPUT_DIR, "corrections.json")


def load_corrections():
    """Load correction dictionary."""
    if os.path.exists(CORRECTIONS_FILE):
        with open(CORRECTIONS_FILE) as f:
            return json.load(f)
    return {
        "version": 1,
        "description": "Correction dictionary for holography transcripts",
        "entries": [],
        "patterns": [],
    }


def apply_word_corrections(text, corrections):
    """Apply specific word-level corrections to text."""
    for entry in corrections.get("entries", []):
        wrong = entry.get("wrong", "")
        right = entry.get("right", "")
        context = entry.get("context", "")

        if not wrong or not right:
            continue

        if context:
            pattern = re.compile(re.escape(wrong), re.IGNORECASE)
            for match in pattern.finditer(text):
                start = max(0, match.start() - 50)
                end = min(len(text), match.end() + 50)
                surrounding = text[start:end].lower()
                if context.lower() in surrounding:
                    text = text[:match.start()] + right + text[match.end():]
                    break
        else:
            text = text.replace(wrong, right)

    return text


def apply_pattern_corrections(text, corrections):
    """Apply regex pattern corrections to text."""
    for pattern_entry in corrections.get("patterns", []):
        pattern = pattern_entry.get("pattern", "")
        replacement = pattern_entry.get("replacement", "")
        if pattern and replacement is not None:
            text = re.sub(pattern, replacement, text)
    return text


def correct_video(video_id, corrections, dry_run=False):
    """Apply corrections to a single video's merged transcript."""
    merged_file = os.path.join(TRANSCRIPTS_DIR, f"{video_id}-merged.txt")
    if not os.path.exists(merged_file):
        print(f"  No merged transcript for {video_id}")
        return None

    with open(merged_file) as f:
        original = f.read()

    corrected = original
    corrections_applied = 0

    # Apply correction dictionary entries
    for entry in corrections.get("entries", []):
        wrong = entry.get("wrong", "")
        right = entry.get("right", "")
        if wrong and right and wrong in corrected:
            count = corrected.count(wrong)
            corrected = corrected.replace(wrong, right)
            corrections_applied += count
            if count > 0:
                print(f"    Applied: '{wrong}' → '{right}' ({count}x)")

    # Apply pattern corrections
    for pattern_entry in corrections.get("patterns", []):
        pattern = pattern_entry.get("pattern", "")
        replacement = pattern_entry.get("replacement", "")
        if pattern:
            new_text = re.sub(pattern, replacement, corrected)
            if new_text != corrected:
                corrections_applied += 1
                corrected = new_text

    if not dry_run and corrections_applied > 0:
        corrected_file = os.path.join(TRANSCRIPTS_DIR, f"{video_id}-corrected.txt")
        with open(corrected_file, 'w') as f:
            f.write(corrected)

    return corrections_applied


def main():
    parser = argparse.ArgumentParser(description="Apply corrections to merged transcripts")
    parser.add_argument("--video", help="Process a specific video ID")
    parser.add_argument("--all", action="store_true", help="Process all videos with merged transcripts")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be corrected without saving")
    args = parser.parse_args()

    if not args.video and not args.all:
        print("Specify --video VIDEO_ID or --all")
        return

    corrections = load_corrections()

    if not corrections.get("entries") and not corrections.get("patterns"):
        print("Correction dictionary is empty. Add entries to corrections.json or label flags first.")
        print(f"File: {CORRECTIONS_FILE}")
        return

    # Find merged files
    if args.video:
        videos = [args.video]
    else:
        videos = []
        for f in os.listdir(TRANSCRIPTS_DIR):
            if f.endswith("-merged.txt"):
                videos.append(f.replace("-merged.txt", ""))

    total_corrections = 0
    for vid in videos:
        print(f"\n{vid}:")
        n = correct_video(vid, corrections, dry_run=args.dry_run)
        if n is not None:
            total_corrections += n

    print(f"\n{'='*60}")
    print(f"Total corrections applied: {total_corrections}")
    if args.dry_run:
        print("(dry run — no files changed)")


if __name__ == "__main__":
    main()