#!/usr/bin/env python3
"""
Holography Transcript Pipeline
===============================
Step 3: Merge transcript sources and flag disagreements with timestamps.

Adapted from Darante pipeline for multi-creator support. Each transcript
includes creator metadata from the catalog.

Produces:
  - transcripts/{video_id}-merged.txt: Best-guess merged transcript
  - transcripts/{video_id}-flags.json: Disagreements with timestamps and links

Usage:
    python3 03_merge.py [--limit N] [--creator CREATOR_ID] [--confidence-threshold 0.66]
"""

import argparse
import json
import os
import re
import difflib

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
CATALOG_FILE = os.path.join(OUTPUT_DIR, "catalog.json")
CAPTIONS_DIR = os.path.join(OUTPUT_DIR, "captions")
TRANSCRIPTS_DIR = os.path.join(OUTPUT_DIR, "transcripts")


def srt_to_segments(srt_text):
    """Parse SRT format into list of {start, end, text} segments."""
    segments = []
    blocks = re.split(r'\n\n+', srt_text.strip())
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 3:
            continue
        ts_match = re.match(
            r'(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})',
            lines[1]
        )
        if not ts_match:
            continue
        g = ts_match.groups()
        start = int(g[0])*3600 + int(g[1])*60 + int(g[2]) + int(g[3])/1000
        end = int(g[4])*3600 + int(g[5])*60 + int(g[6]) + int(g[7])/1000
        text = ' '.join(lines[2:]).strip()
        if text and text != '[Music]' and text != '[ __ ]':
            segments.append({"start": start, "end": end, "text": text})
    return segments


def plain_to_words(text):
    """Split plain text into word list."""
    return re.findall(r'\w+', text.lower())


def get_video_url(video):
    """Get the watch URL for a video based on its platform."""
    platform = video.get("platform", "youtube")
    vid = video["id"]
    if platform == "youtube":
        return f"https://www.youtube.com/watch?v={vid}"
    elif platform == "vimeo":
        return f"https://vimeo.com/{vid}"
    return f"https://www.youtube.com/watch?v={vid}"


def merge_transcripts(video_id, video_title, platform="youtube", confidence_threshold=0.66):
    """Merge YouTube/Vimeo captions + Whisper transcripts and flag disagreements."""

    # Load all available sources
    yt_srt = os.path.join(CAPTIONS_DIR, f"{video_id}.en.srt")
    wh_turbo = os.path.join(TRANSCRIPTS_DIR, f"{video_id}-whisper-turbo.txt")
    wh_turbo_srt = os.path.join(TRANSCRIPTS_DIR, f"{video_id}-whisper-turbo.srt")
    wh_lv3 = os.path.join(TRANSCRIPTS_DIR, f"{video_id}-whisper-largev3.txt")
    parakeet_srt = os.path.join(TRANSCRIPTS_DIR, f"{video_id}-parakeet.srt")

    sources = {}
    if os.path.exists(yt_srt):
        with open(yt_srt) as f:
            sources["youtube"] = srt_to_segments(f.read())
    if os.path.exists(wh_turbo):
        with open(wh_turbo) as f:
            sources["turbo"] = f.read().strip()
    if os.path.exists(wh_turbo_srt):
        with open(wh_turbo_srt) as f:
            sources["turbo_srt"] = srt_to_segments(f.read())
    if os.path.exists(wh_lv3):
        with open(wh_lv3) as f:
            sources["lv3"] = f.read().strip()
    if os.path.exists(parakeet_srt):
        with open(parakeet_srt) as f:
            sources["parakeet"] = srt_to_segments(f.read())

    if not sources:
        return None, []

    # Use Whisper Turbo as the base (best punctuation + profanity handling)
    base_text = sources.get("turbo", sources.get("lv3", ""))
    if not base_text:
        if "parakeet" in sources:
            base_text = " ".join(s["text"] for s in sources["parakeet"])
        elif "youtube" in sources:
            base_text = " ".join(s["text"] for s in sources["youtube"])
        else:
            return None, []

    yt_segments = sources.get("youtube", [])

    # Find disagreements by aligning word sequences
    base_words = plain_to_words(base_text)
    flags = []

    # Build word lists from all available sources
    turbo_words = plain_to_words(sources["turbo"]) if "turbo" in sources else []
    lv3_words = plain_to_words(sources["lv3"]) if "lv3" in sources else []
    parakeet_words = plain_to_words(" ".join(s["text"] for s in sources["parakeet"])) if "parakeet" in sources else []

    yt_words_list = []
    if "youtube" in sources and yt_segments:
        yt_text = " ".join(s["text"] for s in yt_segments).lower()
        yt_words_list = plain_to_words(yt_text)

    # Compare Turbo vs Large-V3 (if both available)
    if turbo_words and lv3_words:
        sm = difflib.SequenceMatcher(None, turbo_words, lv3_words, autojunk=False)
        window = 5

        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == 'equal':
                continue

            if tag == 'replace':
                for ti, li in zip(range(i1, i2), range(j1, j2)):
                    if turbo_words[ti] != lv3_words[li]:
                        context_start = max(0, ti - window)
                        context_end = min(len(turbo_words), ti + window + 1)

                        approx_time = None
                        if yt_segments:
                            progress = ti / max(len(turbo_words), 1)
                            total_duration = yt_segments[-1]["end"] if yt_segments else 0
                            approx_time = progress * total_duration

                        yt_word = None
                        if yt_words_list:
                            yt_pos = int(ti / len(turbo_words) * len(yt_words_list))
                            yt_pos = min(yt_pos, len(yt_words_list) - 1)
                            yt_word = yt_words_list[yt_pos]

                        # Also check Parakeet for this position
                        parakeet_word = None
                        if parakeet_words:
                            pk_pos = int(ti / len(turbo_words) * len(parakeet_words))
                            pk_pos = min(pk_pos, len(parakeet_words) - 1)
                            parakeet_word = parakeet_words[pk_pos]

                        # Build URL based on platform
                        video_url = f"https://www.youtube.com/watch?v={video_id}"
                        if approx_time:
                            video_url += f"&t={int(approx_time)}s"

                        flag = {
                            "position": ti,
                            "timestamp": approx_time,
                            "video_url": video_url,
                            "context_turbo": " ".join(turbo_words[context_start:context_end]),
                            "context_lv3": " ".join(lv3_words[max(0,li-window):min(len(lv3_words),li+window+1)]),
                            "word_turbo": turbo_words[ti],
                            "word_lv3": lv3_words[li],
                            "word_youtube": yt_word,
                            "word_parakeet": parakeet_word,
                            "confidence": "low",
                            "decision": None,
                        }

                        # If any two sources agree, medium confidence
                        words = [turbo_words[ti], lv3_words[li]]
                        if yt_word:
                            words.append(yt_word)
                        if parakeet_word:
                            words.append(parakeet_word)
                        from collections import Counter
                        counts = Counter(words)
                        if counts.most_common(1)[0][1] >= 2:
                            flag["confidence"] = "medium"

                        flags.append(flag)

                if (i2 - i1) != (j2 - j1):
                    extra_turbo = turbo_words[i1:i2]
                    extra_lv3 = lv3_words[j1:j2]
                    if len(extra_turbo) != len(extra_lv3):
                        context_start = max(0, i1 - window)
                        context_end = min(len(turbo_words), i2 + window)

                        approx_time = None
                        if yt_segments:
                            progress = i1 / max(len(turbo_words), 1)
                            total_duration = yt_segments[-1]["end"] if yt_segments else 0
                            approx_time = progress * total_duration

                        video_url = f"https://www.youtube.com/watch?v={video_id}"
                        if approx_time:
                            video_url += f"&t={int(approx_time)}s"

                        flag = {
                            "position": i1,
                            "timestamp": approx_time,
                            "video_url": video_url,
                            "context_turbo": " ".join(turbo_words[context_start:context_end]),
                            "context_lv3": " ".join(lv3_words[max(0,j1-window):min(len(lv3_words),j2+window)]),
                            "word_turbo": " ".join(extra_turbo),
                            "word_lv3": " ".join(extra_lv3),
                            "word_youtube": None,
                            "word_parakeet": None,
                            "confidence": "low",
                            "decision": None,
                            "type": "length_mismatch",
                        }
                        flags.append(flag)

            elif tag in ('insert', 'delete'):
                context_start = max(0, i1 - window)
                context_end = min(len(turbo_words), i2 + window)

                approx_time = None
                if yt_segments:
                    progress = i1 / max(len(turbo_words), 1)
                    total_duration = yt_segments[-1]["end"] if yt_segments else 0
                    approx_time = progress * total_duration

                video_url = f"https://www.youtube.com/watch?v={video_id}"
                if approx_time:
                    video_url += f"&t={int(approx_time)}s"

                present_in = "turbo" if tag == 'delete' else "lv3"
                present_words = turbo_words[i1:i2] if tag == 'delete' else lv3_words[j1:j2]

                # Check Parakeet for this position
                parakeet_word = None
                if parakeet_words:
                    pk_pos = int(i1 / len(turbo_words) * len(parakeet_words))
                    pk_pos = min(pk_pos, len(parakeet_words) - 1)
                    parakeet_word = parakeet_words[pk_pos]

                flag = {
                    "position": i1,
                    "timestamp": approx_time,
                    "video_url": video_url,
                    "context_turbo": " ".join(turbo_words[context_start:context_end]),
                    "context_lv3": " ".join(lv3_words[max(0,j1-window):min(len(lv3_words),j2+window)]),
                    "word_turbo": " ".join(turbo_words[i1:i2]) if tag == 'delete' else None,
                    "word_lv3": " ".join(lv3_words[j1:j2]) if tag == 'insert' else None,
                    "word_youtube": None,
                    "word_parakeet": parakeet_word,
                    "confidence": "low",
                    "decision": None,
                    "type": f"{tag}_only_in_{present_in}",
                }
                flags.append(flag)

    # Create merged output
    merged = {
        "video_id": video_id,
        "title": video_title,
        "platform": platform,
        "base_text": base_text,
        "sources_available": list(sources.keys()),
        "flag_count": len(flags),
    }

    return merged, flags


def format_timestamp(seconds):
    """Format seconds as MM:SS."""
    if seconds is None:
        return "??:??"
    mins = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{mins:02d}:{secs:02d}"


def generate_review_note(video, merged, flags):
    """Generate an Obsidian-compatible review note."""
    video_id = video["id"]
    title = video.get("title", video_id)
    platform = video.get("platform", "youtube")
    creator_name = video.get("creator_name", "unknown")
    video_url = get_video_url(video)

    lines = []
    lines.append(f"# {title}")
    lines.append(f"")
    lines.append(f"**Video ID:** {video_id}")
    lines.append(f"**Creator:** {creator_name}")
    lines.append(f"**Platform:** {platform}")
    lines.append(f"**URL:** {video_url}")
    lines.append(f"**Sources:** {', '.join(merged['sources_available'])}")
    lines.append(f"**Flags:** {len(flags)} disagreements to review")
    lines.append(f"")

    low = [f for f in flags if f["confidence"] == "low"]
    medium = [f for f in flags if f["confidence"] == "medium"]

    if low:
        lines.append(f"## Low Confidence ({len(low)} flags)")
        lines.append(f"All three sources disagree. Listen and decide.")
        lines.append(f"")
        for f in low:
            ts = format_timestamp(f["timestamp"])
            url = f.get("video_url", f"https://www.youtube.com/watch?v={video_id}")
            lines.append(f"### [{ts}]({url})")
            lines.append(f"- **Turbo:** ...{f['context_turbo']}...")
            lines.append(f"- **LV3:** ...{f['context_lv3']}...")
            if f["word_youtube"]:
                lines.append(f"- **Captions:** {f['word_youtube']}")
            lines.append(f"- → Decision: `______`")
            lines.append(f"")

    if medium:
        lines.append(f"## Medium Confidence ({len(medium)} flags)")
        lines.append(f"Two of three sources agree. Verify the majority is correct.")
        lines.append(f"")
        for f in medium:
            ts = format_timestamp(f["timestamp"])
            url = f.get("video_url", f"https://www.youtube.com/watch?v={video_id}")
            lines.append(f"### [{ts}]({url})")
            lines.append(f"- **Turbo:** {f['word_turbo']} | **LV3:** {f['word_lv3']} | **Captions:** {f['word_youtube']}")
            lines.append(f"- Context: ...{f['context_turbo']}...")
            lines.append(f"- → Decision: `______`")
            lines.append(f"")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Merge transcripts and flag disagreements")
    parser.add_argument("--limit", type=int, help="Only process N videos")
    parser.add_argument("--creator", help="Only process videos from this creator")
    parser.add_argument("--confidence-threshold", type=float, default=0.66)
    args = parser.parse_args()

    with open(CATALOG_FILE) as f:
        videos = json.load(f)
    if args.creator:
        videos = [v for v in videos if v.get("creator_id") == args.creator]
    if args.limit:
        videos = videos[:args.limit]

    print(f"Merging transcripts for {len(videos)} videos...")

    total_flags = 0
    processed = 0

    for video in videos:
        vid = video["id"]
        title = video.get("title", vid)
        platform = video.get("platform", "youtube")

        merged, flags = merge_transcripts(vid, title, platform, args.confidence_threshold)
        if merged is None:
            continue

        processed += 1
        total_flags += len(flags)

        # Save merged transcript
        merged_file = os.path.join(TRANSCRIPTS_DIR, f"{vid}-merged.txt")
        with open(merged_file, "w") as f:
            f.write(merged["base_text"])

        # Save flags
        flags_file = os.path.join(TRANSCRIPTS_DIR, f"{vid}-flags.json")
        with open(flags_file, "w") as f:
            json.dump(flags, f, indent=2)

        # Generate review note
        review_file = os.path.join(TRANSCRIPTS_DIR, f"{vid}-review.md")
        review_note = generate_review_note(video, merged, flags)
        with open(review_file, "w") as f:
            f.write(review_note)

        low = len([f for f in flags if f["confidence"] == "low"])
        med = len([f for f in flags if f["confidence"] == "medium"])
        creator = video.get("creator_name", "unknown")
        print(f"  {vid} | {len(flags)} flags ({low} low, {med} med) | {creator} | {title[:40]}")

    print(f"\n{'='*60}")
    print(f"PROCESSED: {processed} videos")
    print(f"TOTAL FLAGS: {total_flags} disagreements to review")


if __name__ == "__main__":
    main()