#!/usr/bin/env python3
"""
Holography Transcript Pipeline
===============================
Step 4: Label and classify merge flags.

Auto-resolves predictable categories (morphology, function words, profanity,
cascades) and surfaces only content-level disagreements for human review.

Reused from Darante pipeline with holography-specific additions.

Produces:
  - transcripts/{video_id}-labels.json: classified flags with auto-resolutions
  - transcripts/{video_id}-review-filtered.md: only flags needing human eyes

Usage:
    python3 04_label.py [--video VIDEO_ID] [--all] [--verbose]
"""

import argparse
import json
import os
import re
from collections import Counter

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
TRANSCRIPTS_DIR = os.path.join(OUTPUT_DIR, "transcripts")
CORRECTIONS_FILE = os.path.join(OUTPUT_DIR, "corrections.json")

# Function words that rarely carry content meaning
STOPWORDS = {
    'the','a','an','and','or','but','so','to','of','in','it','is','s','m','re',
    've','ll','t','you','i','me','my','we','they','he','she','him','her','us',
    'our','your','his','its','was','were','been','being','have','has','had','do',
    'does','did','will','would','could','should','can','may','might','shall','must',
    'that','this','these','those','what','which','who','whom','whose','where','when',
    'why','how','not','no','nor','if','then','than','too','very','just','also',
    'now','here','there','up','out','on','off','at','by','for','with','from',
    'into','about','like','through','over','after','before','between','under',
    'again','further','once','during','each','few','more','most','other','some',
    'such','only','own','same','all','both','any','many','much','don','doesn',
    'didn','isn','aren','wasn','weren','won','wouldn','couldn','shouldn','hasn',
    'haven','hadn','let','got','get','getting','go','going','gone','went','come',
    'coming','make','making','made','take','taking','took','know','knew','think',
    'thinking','thought','say','said','saying','see','saw','seeing','want','wanted',
    'wanting','tell','told','telling','give','gave','giving','use','used','using',
    'find','found','finding','put','putting','thing','things','really','actually',
}

# Holography-specific terms that Whisper commonly mishears
HOLOGRAPHY_TERMS = {
    'hologram', 'holograms', 'holography', 'holographic', 'holographer',
    'holographers', 'holo', 'denisyuk', 'lippmann', 'bragg', 'rainbow',
    'stereogram', 'stereograms', 'transmission', 'reflection', 'dcg',
    'silver', 'halide', 'emulsion', 'photopolymer', 'photoresist',
    'laser', 'lasers', 'coherent', 'interference', 'diffraction',
    'reference', 'object', 'beam', 'beamsplitter', 'collimating',
    'spatial', 'filter', 'pinhole', 'plate', 'plates', 'film',
    'exposure', 'develop', 'developer', 'bleach', 'bleaching',
    'rehalogenating', 'fixing', 'process', 'processing',
    'pulsed', 'ruby', 'nd:yag', 'helium', 'neon', 'hen',
    'argon', 'krypton', 'diode', 'dpss',
    'optoclone', 'holoprint', 'holocenter', 'holoconference',
    'isdh', 'isdb', 'mosaic', 'multiplex',
}

# Profanity markers that YouTube censors
PROFANITY_MARKERS = {'__', '[ __ ]', '[music]', '[Music]', '*', '#', '@@@@'}

# Label categories
LABEL_MORPHOLOGY = "morphology"
LABEL_FUNCTION = "function_word"
LABEL_PROFANITY = "profanity"
LABEL_CASCADE = "cascade"
LABEL_CONTENT = "content"
LABEL_MINOR = "minor"
LABEL_HOLOGRAPHY = "holography_term"


def load_corrections():
    """Load existing correction dictionary."""
    if os.path.exists(CORRECTIONS_FILE):
        with open(CORRECTIONS_FILE) as f:
            return json.load(f)
    return {"entries": [], "patterns": []}


def is_morphology_variant(word1, word2):
    """Check if two words are morphological variants of each other."""
    w1 = word1.lower().strip("'")
    w2 = word2.lower().strip("'")
    if w1 == w2:
        return True
    for suffix in ['s', 'es', 'ed', 'ing', 'er', 'est', 'ly', 'tion', 'ment', 'ness']:
        if w1.rstrip(suffix) == w2 or w2.rstrip(suffix) == w1:
            return True
        if w1 == w2.rstrip(suffix) or w2 == w1.rstrip(suffix):
            return True
    if len(w1) > 4 and len(w2) > 4:
        if w1.startswith(w2[:4]) or w2.startswith(w1[:4]):
            stem = w1[:4] if len(w1) <= len(w2) else w2[:4]
            if stem in ['beli', 'conv', 'disc', 'past', 'star', 'grow', 'need',
                        'holog', 'holod', 'laser', 'opto']:
                return True
    return False


def is_holography_mismatch(word1, word2):
    """Check if one word is a holography term the other misheard."""
    w1 = word1.lower().strip("'")
    w2 = word2.lower().strip("'")
    if w1 in HOLOGRAPHY_TERMS and w2 not in HOLOGRAPHY_TERMS:
        return True, w1  # w1 is the correct holography term
    if w2 in HOLOGRAPHY_TERMS and w1 not in HOLOGRAPHY_TERMS:
        return True, w2  # w2 is the correct holography term
    return False, None


def is_cascade(flags, idx, window=5):
    """Check if a flag is part of an LV3 hallucination cascade."""
    if idx >= len(flags) or idx < 0:
        return False
    current = flags[idx]
    lv3_word = (current.get('word_lv3') or '').lower()
    if not lv3_word or len(lv3_word) < 3:
        return False
    same_word_count = 0
    for j in range(max(0, idx - window), min(len(flags), idx + window + 1)):
        other_lv3 = (flags[j].get('word_lv3') or '').lower()
        if other_lv3 == lv3_word:
            same_word_count += 1
    return same_word_count >= 3


def is_lv3_hallucination(flag):
    """Check if a flag represents an LV3 hallucination."""
    ftype = flag.get('type', 'word_mismatch')
    lw = (flag.get('word_lv3') or '') or ''
    tw = (flag.get('word_turbo') or '') or ''

    if ftype == 'insert_only_in_lv3' and len(lw.split()) >= 3:
        return True
    if ftype == 'length_mismatch':
        lv3_words = len(lw.split())
        turbo_words = len(tw.split())
        if lv3_words > max(turbo_words, 1) * 2:
            return True
    if lw:
        words = lw.split()
        if len(words) >= 3:
            for i in range(len(words) - 2):
                if words[i] == words[i+1] == words[i+2]:
                    return True
    return False


def is_profanity_censor(flag):
    """Check if YouTube censored a word that Whisper transcribed accurately."""
    yt_word = flag.get('word_youtube')
    if yt_word and yt_word in PROFANITY_MARKERS:
        return True
    ctx = (flag.get('context_turbo') or '').lower()
    if '__' in ctx and any(w in ctx for w in ['shit', 'fuck', 'damn', 'hell', 'ass']):
        return True
    return False


def classify_flag(flag, flags_list, idx):
    """Classify a single flag into a label category."""
    tw = (flag.get('word_turbo') or '').lower()
    lw = (flag.get('word_lv3') or '').lower()
    yw = flag.get('word_youtube')
    if yw:
        yw = yw.lower()
    ftype = flag.get('type', 'word_mismatch')

    # 1. Holography term mismatch
    is_holo, correct_term = is_holography_mismatch(tw, lw)
    if is_holo:
        return LABEL_HOLOGRAPHY, "holography_term_mismatch", correct_term

    # 2. Profanity censorship
    if is_profanity_censor(flag):
        return LABEL_PROFANITY, "youtube_censored", tw

    # 3. LV3 hallucination detection
    if is_cascade(flags_list, idx) or is_lv3_hallucination(flag):
        return LABEL_CASCADE, "lv3_hallucination", tw

    # 4. Insert/delete flags
    if ftype in ('insert_only_in_lv3', 'delete_only_in_turbo'):
        source_word = tw if ftype == 'delete_only_in_turbo' else lw
        if source_word:
            words = source_word.split()
            fillers = {'mmm', 'mm', 'hmm', 'yeah', 'yep', 'yup', 'uh', 'um', 'ah',
                        'okay', 'ok', 'right', 'like', 'you know', 'i mean',
                        'hey', 'mm hmm', 'mhm', 'shit', 'damn', 'lord'}
            if source_word.lower().strip() in fillers:
                return LABEL_FUNCTION, f"{ftype}_filler", source_word.lower().strip()
            if len(words) <= 2:
                return LABEL_MINOR, f"{ftype}_short", None
        return LABEL_CONTENT, ftype, None

    # 5. Length mismatches
    if ftype == 'length_mismatch':
        tw_words = tw.split() if tw else []
        lw_words = lw.split() if lw else []
        if len(tw_words) <= 2 and len(lw_words) <= 2:
            return LABEL_MINOR, "length_mismatch_short", None
        return LABEL_CONTENT, "length_mismatch", None

    # 6. Morphology variants
    if tw and lw and is_morphology_variant(tw, lw):
        return LABEL_MORPHOLOGY, "morphology_variant", None

    # 7. Function word swaps
    if tw in STOPWORDS or lw in STOPWORDS:
        return LABEL_FUNCTION, "function_word_swap", None

    # 8. Minor phonetic variants
    if tw and lw and len(tw) > 2 and len(lw) > 2:
        if len(tw) == len(lw):
            diffs = sum(1 for a, b in zip(tw, lw) if a != b)
            if diffs <= 1:
                return LABEL_MINOR, "phonetic_variant", None

    # 9. Everything else is a content disagreement
    return LABEL_CONTENT, "content_disagreement", None


def auto_resolve(label, flag, resolution_hint):
    """Determine the auto-resolution for a classified flag."""
    tw = flag.get('word_turbo', '')
    lw = flag.get('word_lv3', '')

    if label == LABEL_HOLOGRAPHY:
        return resolution_hint  # The correct holography term

    if label == LABEL_PROFANITY:
        return tw

    if label == LABEL_CASCADE:
        return tw

    if label == LABEL_MORPHOLOGY:
        candidates = [w for w in [tw, lw, flag.get('word_youtube', '')] if w and w.lower() not in STOPWORDS]
        if candidates:
            return max(candidates, key=len)
        return tw or lw

    if label == LABEL_FUNCTION:
        return tw

    if label == LABEL_MINOR:
        return tw

    return None  # Content flags need human review


def label_video(video_id, flags, verbose=False):
    """Classify all flags for a video and produce labelled output."""
    labelled = []
    category_counts = Counter()
    auto_resolved = 0
    needs_review = 0

    for i, flag in enumerate(flags):
        label, subtype, resolution_hint = classify_flag(flag, flags, i)
        resolution = auto_resolve(label, flag, resolution_hint)

        entry = {
            **flag,
            "label": label,
            "subtype": subtype,
            "auto_resolution": resolution,
        }

        if resolution:
            auto_resolved += 1
        else:
            needs_review += 1

        labelled.append(entry)
        category_counts[label] += 1

    return labelled, category_counts, auto_resolved, needs_review


def generate_filtered_review(video_id, video_title, labelled_flags, creator_name="", platform="youtube"):
    """Generate a review file with only content-level flags needing human eyes."""
    content_flags = [f for f in labelled_flags if f['label'] == LABEL_CONTENT]
    holo_flags = [f for f in labelled_flags if f['label'] == LABEL_HOLOGRAPHY]

    if not content_flags and not holo_flags:
        return f"# {video_title}\n\nNo content-level flags need review. Auto-resolved all disagreements."

    lines = []
    lines.append(f"# {video_title}")
    lines.append(f"")
    lines.append(f"**Video ID:** {video_id}")
    lines.append(f"**Creator:** {creator_name}")
    lines.append(f"**Platform:** {platform}")
    lines.append(f"**Content flags:** {len(content_flags)} | **Holography terms:** {len(holo_flags)}")
    lines.append(f"")

    if holo_flags:
        lines.append(f"## Holography Term Mismatches ({len(holo_flags)})")
        lines.append(f"Whisper misheard holography-specific terms. Auto-resolved to the known term.")
        lines.append(f"")
        for f in holo_flags:
            ts = f.get('timestamp', 0)
            ts_str = f"{int(ts)//60:02d}:{int(ts)%60:02d}" if ts else "??:??"
            url = f.get('video_url', f"https://www.youtube.com/watch?v={video_id}")
            lines.append(f"- **{f.get('word_turbo', '?')}** → **{f.get('auto_resolution', '?')}** ({ts_str})")
        lines.append(f"")

    if content_flags:
        lines.append(f"## Content Disagreements ({len(content_flags)})")
        lines.append(f"Needs human review.")
        lines.append(f"")
        for f in content_flags:
            ts = f.get('timestamp', 0)
            ts_str = f"{int(ts)//60:02d}:{int(ts)%60:02d}" if ts else "??:??"
            url = f.get('video_url', f"https://www.youtube.com/watch?v={video_id}")
            tw = f.get('word_turbo', '?')
            lw = f.get('word_lv3', '?')
            yw = f.get('word_youtube', '?')
            ctx = f.get('context_turbo', '')[:100]
            subtype = f.get('subtype', 'unknown')

            lines.append(f"### [{ts_str}]({url})")
            lines.append(f"- **Turbo:** {tw} | **LV3:** {lw} | **Captions:** {yw}")
            lines.append(f"- Context: ...{ctx}...")
            lines.append(f"- Type: {subtype}")
            lines.append(f"- → Correct word: `______`")
            lines.append(f"")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Label and classify merge flags")
    parser.add_argument("--video", help="Process a specific video ID")
    parser.add_argument("--all", action="store_true", help="Process all videos with flags")
    parser.add_argument("--verbose", action="store_true", help="Show detailed output")
    args = parser.parse_args()

    if not args.video and not args.all:
        print("Specify --video VIDEO_ID or --all")
        return

    # Find flag files
    if args.video:
        flag_files = [(args.video, os.path.join(TRANSCRIPTS_DIR, f"{args.video}-flags.json"))]
    else:
        flag_files = []
        for f in os.listdir(TRANSCRIPTS_DIR):
            if f.endswith("-flags.json"):
                vid = f.replace("-flags.json", "")
                flag_files.append((vid, os.path.join(TRANSCRIPTS_DIR, f)))

    # Load video catalog for titles and metadata
    catalog_file = os.path.join(OUTPUT_DIR, "catalog.json")
    titles = {}
    creators = {}
    platforms = {}
    if os.path.exists(catalog_file):
        with open(catalog_file) as f:
            for v in json.load(f):
                titles[v['id']] = v.get('title', v['id'])
                creators[v['id']] = v.get('creator_name', 'unknown')
                platforms[v['id']] = v.get('platform', 'youtube')

    total_auto = 0
    total_review = 0
    total_counts = Counter()

    for vid, flag_file in flag_files:
        if not os.path.exists(flag_file):
            print(f"No flags file for {vid}")
            continue

        flags = json.load(open(flag_file))
        labelled, counts, auto_resolved, needs_review = label_video(vid, flags, args.verbose)

        # Save labelled flags
        labels_file = os.path.join(TRANSCRIPTS_DIR, f"{vid}-labels.json")
        with open(labels_file, 'w') as f:
            json.dump(labelled, f, indent=2)

        # Save filtered review
        title = titles.get(vid, vid)
        creator = creators.get(vid, "unknown")
        platform = platforms.get(vid, "youtube")
        review = generate_filtered_review(vid, title, labelled, creator, platform)
        review_file = os.path.join(TRANSCRIPTS_DIR, f"{vid}-review-filtered.md")
        with open(review_file, 'w') as f:
            f.write(review)

        total_auto += auto_resolved
        total_review += needs_review
        total_counts += counts

        print(f"\n{vid} ({title[:50]})")
        print(f"  Total flags: {len(flags)}")
        print(f"  Auto-resolved: {auto_resolved}")
        print(f"  Needs review: {needs_review}")
        for label, count in sorted(counts.items()):
            print(f"    {label}: {count}")

    print(f"\n{'='*60}")
    print(f"TOTALS across {len(flag_files)} videos")
    print(f"  Auto-resolved: {total_auto}")
    print(f"  Needs review: {total_review}")
    print(f"  Reduction: {total_auto/(total_auto+total_review)*100:.0f}% auto-resolved" if (total_auto+total_review) > 0 else "  No flags")
    for label, count in sorted(total_counts.items()):
        print(f"    {label}: {count}")


if __name__ == "__main__":
    main()