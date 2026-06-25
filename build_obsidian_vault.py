#!/usr/bin/env python3
"""
Convert holography transcript corpus into an Obsidian vault.

Reads from holography-transcript-pipeline/ and writes structured Obsidian notes
to ~/Obsidian/Holography-Corpus/.

Each video becomes a note with:
- YAML frontmatter (video ID, creator, platform, date, duration, tier, YouTube/Vimeo link)
- Full transcript with speaker labels
- Wikilinks to creator pages and theme pages

Usage:
    python3 build_obsidian_vault.py [--full] [--incremental]
"""

import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime

PIPELINE_DIR = Path(__file__).parent
CATALOG_PATH = PIPELINE_DIR / "catalog.json"
CREATORS_PATH = PIPELINE_DIR / "creators.json"
TRANSCRIPTS_DIR = PIPELINE_DIR / "transcripts"
VAULT_DIR = Path.home() / "Obsidian" / "Holography-Corpus"

# Obsidian folders
TRANSCRIPTS_FOLDER = VAULT_DIR / "Transcripts"
CREATORS_FOLDER = VAULT_DIR / "Creators"
THEMES_FOLDER = VAULT_DIR / "Themes"
PLATFORMS_FOLDER = VAULT_DIR / "Platforms"
TEMPLATES_FOLDER = VAULT_DIR / "Templates"


def slugify(text: str) -> str:
    """Slugify a string for use as a filename."""
    text = text.strip()
    text = text.replace("#", "")
    text = re.sub(r'[/]', ' -', text)
    text = re.sub(r'[\\:*?"<>|]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    if len(text) > 150:
        text = text[:147].rsplit(' ', 1)[0]
    return text


def parse_srt(srt_path: Path) -> list[dict]:
    """Parse SRT file into list of {start, end, text} dicts."""
    blocks = []
    if not srt_path.exists():
        return blocks

    content = srt_path.read_text(encoding='utf-8', errors='replace')
    chunks = re.split(r'\n\s*\n', content.strip())

    for chunk in chunks:
        lines = chunk.strip().split('\n')
        if len(lines) < 3:
            continue
        time_line = lines[1]
        text_lines = lines[2:]

        time_match = re.match(
            r'(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})',
            time_line
        )
        if not time_match:
            continue

        g = time_match.groups()
        start = int(g[0])*3600 + int(g[1])*60 + int(g[2]) + int(g[3])/1000
        end = int(g[4])*3600 + int(g[5])*60 + int(g[6]) + int(g[7])/1000

        text = ' '.join(text_lines).strip()
        if text:
            blocks.append({'start': start, 'end': end, 'text': text})

    return blocks


def format_timestamp(seconds: float) -> str:
    """Format seconds as HH:MM:SS or MM:SS."""
    h = int(seconds) // 3600
    m = (int(seconds) % 3600) // 60
    s = int(seconds) % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def format_duration(seconds: float) -> str:
    """Format duration in human-readable form."""
    m = int(seconds) // 60
    s = int(seconds) % 60
    if m >= 60:
        h = m // 60
        m = m % 60
        return f"{h}h {m}m"
    return f"{m}m {s}s"


def load_diarization(video_id: str) -> dict:
    """Load diarization data for a video."""
    dia_path = TRANSCRIPTS_DIR / f"{video_id}-diarization.json"
    if dia_path.exists():
        return json.loads(dia_path.read_text())
    return None


def assign_speakers(srt_blocks: list[dict], diarization: dict) -> list[dict]:
    """Assign speaker labels to SRT blocks using diarization overlap."""
    if not diarization or not diarization.get('turns'):
        return [{'start': b['start'], 'end': b['end'], 'text': b['text'], 'speaker': 'Speaker'}
                for b in srt_blocks]

    turns = diarization['turns']
    result = []
    for block in srt_blocks:
        best_speaker = 'Speaker'
        best_overlap = 0

        for turn in turns:
            overlap_start = max(block['start'], turn['start'])
            overlap_end = min(block['end'], turn['end'])
            overlap = max(0, overlap_end - overlap_start)
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = turn['speaker']

        result.append({
            'start': block['start'],
            'end': block['end'],
            'text': block['text'],
            'speaker': best_speaker
        })

    return result


def get_video_url(video):
    """Get the watch URL for a video based on its platform."""
    platform = video.get("platform", "youtube")
    vid = video["id"]
    if platform == "youtube":
        return f"https://youtube.com/watch?v={vid}"
    elif platform == "vimeo":
        return f"https://vimeo.com/{vid}"
    return f"https://youtube.com/watch?v={vid}"


def build_creator_note(creator: dict, video_count: int, total_duration: float) -> str:
    """Build an Obsidian note for a creator."""
    lines = ['---']
    lines.append(f'type: creator')
    lines.append(f'creator_id: "{creator["id"]}"')
    lines.append(f'name: "{creator["name"]}"')
    lines.append(f'platform: {creator["platform"]}')
    lines.append(f'tier: {creator.get("tier", 0)}')
    lines.append(f'status: {creator.get("status", "unknown")}')
    lines.append(f'video_count: {video_count}')
    lines.append(f'total_duration: {int(total_duration)}')
    lines.append(f'total_duration_label: "{format_duration(total_duration)}"')
    if creator.get("website"):
        lines.append(f'website: "{creator["website"]}"')
    if creator.get("instagram"):
        lines.append(f'instagram: "{creator["instagram"]}"')
    if creator.get("patreon"):
        lines.append(f'patreon: "{creator["patreon"]}"')
    lines.append('---')
    lines.append('')
    lines.append(f'# {creator["name"]}')
    lines.append('')
    lines.append(creator.get("description", ""))
    lines.append('')

    # Stats
    hours = int(total_duration) // 3600
    minutes = (int(total_duration) % 3600) // 60
    lines.append(f'## Stats')
    lines.append('')
    lines.append(f'| Metric | Value |')
    lines.append(f'|---|---|')
    lines.append(f'| Videos | {video_count} |')
    lines.append(f'| Total Duration | {format_duration(total_duration)} |')
    lines.append(f'| Platform | {creator["platform"].title()} |')
    lines.append(f'| Tier | {creator.get("tier", "?")} |')
    lines.append(f'| Status | {creator.get("status", "unknown").title()} |')
    lines.append('')

    # Links
    lines.append(f'## Links')
    lines.append('')
    lines.append(f'- 🔗 Channel: [{creator["name"]}]({creator["channel_url"]})')
    if creator.get("website"):
        lines.append(f'- 🌐 Website: [{creator["website"]}]({creator["website"]})')
    if creator.get("instagram"):
        lines.append(f'- 📸 Instagram: {creator["instagram"]}')
    if creator.get("patreon"):
        lines.append(f'- 💰 Patreon: [Support]({creator["patreon"]})')
    lines.append('')

    lines.append(f'## Videos')
    lines.append('')
    lines.append(f'```query')
    lines.append(f'type: transcript')
    lines.append(f'creator_id: {creator["id"]}')
    lines.append(f'```')
    lines.append('')

    return '\n'.join(lines)


def build_transcript_note(video: dict, srt_blocks: list[dict], diarization: dict,
                          creator: dict) -> str:
    """Build a full Obsidian note for one video."""
    video_id = video['id']
    title = video.get('title', video_id)
    slug = slugify(title)
    platform = video.get('platform', 'youtube')
    creator_id = video.get('creator_id', 'unknown')
    creator_name = video.get('creator_name', 'Unknown')

    # Frontmatter
    fm = {
        'video_id': video_id,
        'title': title,
        'creator_id': creator_id,
        'creator_name': creator_name,
        'platform': platform,
        'url': get_video_url(video),
        'duration': video.get('duration', 0),
        'duration_label': format_duration(video.get('duration', 0)),
    }

    if video.get('upload_date'):
        date_str = video['upload_date']
        try:
            dt = datetime.strptime(date_str, '%Y%m%d')
            fm['date'] = dt.strftime('%Y-%m-%d')
            fm['year'] = dt.year
        except ValueError:
            fm['date'] = date_str

    if creator:
        fm['tier'] = creator.get('tier', 0)

    if diarization and diarization.get('turns'):
        speakers = sorted(set(t['speaker'] for t in diarization['turns']))
        fm['speakers'] = speakers
        fm['num_speakers'] = len(speakers)

    # Build YAML frontmatter
    lines = ['---']
    for key, value in fm.items():
        if isinstance(value, list):
            lines.append(f'{key}:')
            for item in value:
                lines.append(f'  - "{item}"')
        elif isinstance(value, str) and ('\n' in value or ':' in value or '"' in value):
            escaped = value.replace('"', '\\"')
            lines.append(f'{key}: "{escaped}"')
        elif isinstance(value, bool):
            lines.append(f'{key}: true')
        else:
            lines.append(f'{key}: {json.dumps(value) if not isinstance(value, (int, float)) else value}')
    lines.append('---')
    lines.append('')

    # Title
    lines.append(f'# {title}')
    lines.append('')

    # Metadata table
    lines.append('| | |')
    lines.append('|---|---|')
    lines.append(f'| 🎤 Creator | [[{slugify(creator_name)}\\|{creator_name}]] |')
    lines.append(f'| 📅 Date | {fm.get("date", "Unknown")} |')
    lines.append(f'| ⏱️ Duration | {fm["duration_label"]} |')
    lines.append(f'| 🎬 Platform | {platform.title()} |')
    lines.append(f'| 🔗 Watch | [Link]({fm["url"]}) |')
    if fm.get('speakers'):
        lines.append(f'| 🗣️ Speakers | {", ".join(fm["speakers"])} |')
    lines.append('')

    # Transcript
    lines.append('## Transcript')
    lines.append('')

    annotated = assign_speakers(srt_blocks, diarization)

    current_speaker = None
    current_text = []

    for block in annotated:
        speaker = block['speaker']
        ts = format_timestamp(block['start'])

        if speaker != current_speaker:
            if current_speaker is not None and current_text:
                lines.append(f'**{current_speaker}** {current_text[0][1]}')
                for _, text in current_text[1:]:
                    lines.append(text)
                lines.append('')
            current_speaker = speaker
            current_text = [(ts, block['text'])]
        else:
            current_text.append((ts, block['text']))

    if current_speaker is not None and current_text:
        lines.append(f'**{current_speaker}** {current_text[0][1]}')
        for _, text in current_text[1:]:
            lines.append(text)
        lines.append('')

    # Footer
    lines.append('---')
    lines.append('')
    lines.append(f'Up: [[Holography Corpus - Index]]')
    lines.append(f'Creator: [[{slugify(creator_name)}\\|{creator_name}]]')
    lines.append('')

    return '\n'.join(lines)


def build_platform_note(platform: str, videos: list[dict], creators: list[dict]) -> str:
    """Build a platform index note."""
    lines = ['---']
    lines.append(f'type: platform')
    lines.append(f'platform: "{platform}"')
    lines.append(f'video_count: {len(videos)}')
    lines.append(f'creator_count: {len(creators)}')
    lines.append('---')
    lines.append('')
    lines.append(f'# {platform.title()} Videos')
    lines.append('')
    lines.append(f'{len(videos)} videos from {len(creators)} creators on {platform.title()}.')
    lines.append('')
    lines.append('## Creators')
    lines.append('')
    for c in sorted(creators, key=lambda x: x.get('name', '')):
        lines.append(f'- [[{slugify(c["name"])}\\|{c["name"]}]]')
    lines.append('')

    return '\n'.join(lines)


def build_index(catalog: list[dict], creators: list[dict]) -> str:
    """Build the main index note."""
    # Calculate stats
    total_duration = sum(v.get('duration', 0) for v in catalog)
    total_hours = int(total_duration) // 3600
    total_minutes = (int(total_duration) % 3600) // 60

    platforms = {}
    for v in catalog:
        p = v.get('platform', 'unknown')
        platforms[p] = platforms.get(p, 0) + 1

    creator_ids = set(v.get('creator_id') for v in catalog if v.get('creator_id'))

    lines = ['---']
    lines.append('type: index')
    lines.append(f'video_count: {len(catalog)}')
    lines.append(f'creator_count: {len(creator_ids)}')
    lines.append(f'total_duration: {int(total_duration)}')
    lines.append('---')
    lines.append('')
    lines.append('# Holography Corpus — Transcript Archive')
    lines.append('')
    lines.append(f'Complete transcript archive for holography content creators across YouTube, Vimeo, and the web.')
    lines.append(f'{len(catalog)} videos transcribed from {len(creator_ids)} creators.')
    lines.append('')

    # Stats
    lines.append('## Corpus Stats')
    lines.append('')
    lines.append('| Metric | Value |')
    lines.append('|---|---|')
    lines.append(f'| Total Videos | {len(catalog)} |')
    lines.append(f'| Total Duration | {total_hours}h {total_minutes}m |')
    lines.append(f'| Creators | {len(creator_ids)} |')
    for p, count in sorted(platforms.items()):
        lines.append(f'| {p.title()} Videos | {count} |')
    lines.append('')

    # Creators by tier
    lines.append('## Creators by Tier')
    lines.append('')
    for tier in [1, 2, 3, 4]:
        tier_creators = [c for c in creators if c.get('tier') == tier]
        if tier_creators:
            lines.append(f'### Tier {tier} — {"Primary" if tier == 1 else "Secondary" if tier == 2 else "Tertiary" if tier == 3 else "Supplementary"}')
            lines.append('')
            for c in sorted(tier_creators, key=lambda x: x.get('name', '')):
                status = '🟢' if c.get('status') == 'active' else '🟡' if c.get('status') == 'semi-active' else '🔴'
                plat = c.get('platform', 'unknown')
                vid_count = sum(1 for v in catalog if v.get('creator_id') == c['id'])
                lines.append(f'- {status} [[{slugify(c["name"])}\\|{c["name"]}]] ({plat}, {vid_count} videos)')
            lines.append('')

    # Recent videos
    lines.append('## Recent Videos')
    lines.append('')
    dated = [v for v in catalog if v.get('upload_date')]
    for v in sorted(dated, key=lambda x: x.get('upload_date', ''), reverse=True)[:20]:
        slug = slugify(v.get('title', v['id']))
        date = v.get('upload_date', '')
        try:
            date = f"{date[:4]}-{date[4:6]}-{date[6:]}"
        except (ValueError, IndexError):
            pass
        creator = v.get('creator_name', 'Unknown')
        lines.append(f'- [[{slug}\\|{v.get("title", v["id"])}]] — {date} — {creator}')
    lines.append('')

    lines.append('## Structure')
    lines.append('')
    lines.append('- `Transcripts/` — One note per video with full transcript and metadata')
    lines.append('- `Creators/` — One note per creator with bio and stats')
    lines.append('- `Platforms/` — Index pages for YouTube, Vimeo, etc.')
    lines.append('- `Themes/` — Theme pages linking to related videos')
    lines.append('')

    return '\n'.join(lines)


def main(mode='auto'):
    """
    mode='full'       — rebuild entire vault from scratch
    mode='incremental' — only add/update notes for new/changed videos
    mode='auto'        — full if vault is empty, incremental otherwise
    """
    print("Loading catalog and creators...")
    with open(CATALOG_PATH) as f:
        catalog = json.load(f)
    with open(CREATORS_PATH) as f:
        creators_list = json.load(f)

    creators_by_id = {c['id']: c for c in creators_list}
    print(f"Found {len(catalog)} videos in catalog, {len(creators_list)} creators")

    # Create vault directories
    for d in [TRANSCRIPTS_FOLDER, CREATORS_FOLDER, THEMES_FOLDER, PLATFORMS_FOLDER, TEMPLATES_FOLDER]:
        d.mkdir(parents=True, exist_ok=True)

    if mode == 'auto':
        has_notes = any(TRANSCRIPTS_FOLDER.glob('*.md'))
        mode = 'incremental' if has_notes else 'full'
        print(f"Auto-detected mode: {mode}")

    # Build creator notes
    print("Building creator notes...")
    for creator in creators_list:
        creator_videos = [v for v in catalog if v.get('creator_id') == creator['id']]
        total_duration = sum(v.get('duration', 0) for v in creator_videos)
        note = build_creator_note(creator, len(creator_videos), total_duration)
        note_path = CREATORS_FOLDER / f"{slugify(creator['name'])}.md"
        note_path.write_text(note, encoding='utf-8')

    # Build platform notes
    print("Building platform notes...")
    for platform in ['youtube', 'vimeo', 'website']:
        platform_videos = [v for v in catalog if v.get('platform') == platform]
        platform_creators = [c for c in creators_list if c.get('platform') == platform]
        if platform_videos or platform_creators:
            note = build_platform_note(platform, platform_videos, platform_creators)
            note_path = PLATFORMS_FOLDER / f"{platform.title()}.md"
            note_path.write_text(note, encoding='utf-8')

    # Build transcript notes
    if mode == 'full':
        written = 0
        skipped = 0
        for video in catalog:
            video_id = video['id']
            title = video.get('title', video_id)
            slug = slugify(title)
            creator = creators_by_id.get(video.get('creator_id'), {})

            # Find transcript
            srt_path = TRANSCRIPTS_DIR / f"{video_id}.en.srt"
            if not srt_path.exists():
                skipped += 1
                continue

            srt_blocks = parse_srt(srt_path)
            if not srt_blocks:
                skipped += 1
                continue

            diarization = load_diarization(video_id)
            note_content = build_transcript_note(video, srt_blocks, diarization, creator)
            note_path = TRANSCRIPTS_FOLDER / f"{slug}.md"
            note_path.write_text(note_content, encoding='utf-8')
            written += 1
            if written % 50 == 0:
                print(f"  ... {written} notes written")

        print(f"Wrote {written} transcript notes, skipped {skipped}")

    elif mode == 'incremental':
        existing_notes = {}
        for note_path in TRANSCRIPTS_FOLDER.glob('*.md'):
            content = note_path.read_text(encoding='utf-8')
            fm_match = re.search(r'^video_id:\s*"?([^"\n]+)', content, re.MULTILINE)
            if fm_match:
                existing_notes[fm_match.group(1)] = note_path

        added = 0
        updated = 0
        skipped = 0

        for video in catalog:
            video_id = video['id']
            title = video.get('title', video_id)
            slug = slugify(title)
            creator = creators_by_id.get(video.get('creator_id'), {})

            srt_path = TRANSCRIPTS_DIR / f"{video_id}.en.srt"
            if not srt_path.exists():
                skipped += 1
                continue

            srt_blocks = parse_srt(srt_path)
            if not srt_blocks:
                skipped += 1
                continue

            diarization = load_diarization(video_id)
            note_content = build_transcript_note(video, srt_blocks, diarization, creator)
            note_path = TRANSCRIPTS_FOLDER / f"{slug}.md"

            if video_id in existing_notes:
                old_content = existing_notes[video_id].read_text(encoding='utf-8')
                if old_content != note_content:
                    if existing_notes[video_id] != note_path:
                        existing_notes[video_id].unlink(missing_ok=True)
                    note_path.write_text(note_content, encoding='utf-8')
                    updated += 1
            else:
                note_path.write_text(note_content, encoding='utf-8')
                added += 1

        # Remove notes for videos no longer in catalog
        removed = 0
        catalog_ids = {v['id'] for v in catalog}
        for video_id, note_path in existing_notes.items():
            if video_id not in catalog_ids:
                note_path.unlink(missing_ok=True)
                removed += 1

        print(f"Added {added}, updated {updated}, removed {removed}, skipped {skipped}")

    # Always rebuild index
    index = build_index(catalog, creators_list)
    (VAULT_DIR / "Holography Corpus - Index.md").write_text(index, encoding='utf-8')

    # Write vault README
    written_count = len(list(TRANSCRIPTS_FOLDER.glob('*.md')))
    readme = f"""# Holography Corpus — Transcript Archive

Obsidian vault containing transcribed and indexed content from holography creators across YouTube, Vimeo, and the web.

## Stats
- **{len(catalog)}** videos transcribed
- **{len(creators_list)}** creators indexed
- **{written_count}** transcript notes

## Structure
- `Transcripts/` — One note per video with full transcript and metadata
- `Creators/` — One note per creator with bio and stats
- `Platforms/` — Index pages for YouTube, Vimeo, etc.
- `Themes/` — Theme pages linking to related videos
- `Holography Corpus - Index` — Main hub page

## Generated
- Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}
- Source: holography-transcript-pipeline catalog.json + creators.json
- Pipeline: Whisper Turbo + Large-V3 (local MLX) + pyannote diarization
"""
    (VAULT_DIR / "README.md").write_text(readme, encoding='utf-8')

    print(f"\n✅ Vault complete at {VAULT_DIR}")
    print(f"   {written_count} transcript notes")
    print(f"   {len(creators_list)} creator notes")
    print(f"   {len(list(PLATFORMS_FOLDER.glob('*.md')))} platform notes")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Build/update Holography Corpus Obsidian vault')
    parser.add_argument('--full', action='store_true', help='Full rebuild')
    parser.add_argument('--incremental', action='store_true', help='Only add/update changed notes')
    args = parser.parse_args()

    if args.full:
        main(mode='full')
    elif args.incremental:
        main(mode='incremental')
    else:
        main(mode='auto')