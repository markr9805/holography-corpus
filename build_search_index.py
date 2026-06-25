#!/usr/bin/env python3
"""
Build a search index JSON for the holography corpus website.

Generates a compact index with:
- Video metadata (id, title, date, duration, creator, platform, tier)
- Transcript excerpts (first ~500 chars per video for context)
- Creator index
- Platform statistics

Output: analysis/search-index.json
"""

import json
import re
import sys
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
CATALOG_PATH = SCRIPT_DIR / "catalog.json"
CREATORS_PATH = SCRIPT_DIR / "creators.json"
TRANSCRIPTS_DIR = SCRIPT_DIR / "transcripts"
OUTPUT_PATH = SCRIPT_DIR / "analysis" / "search-index.json"


def slugify(text: str) -> str:
    text = text.strip()
    text = text.replace("#", "")
    text = re.sub(r'[/]', ' -', text)
    text = re.sub(r'[\\:*?"<>|]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    if len(text) > 150:
        text = text[:147].rsplit(' ', 1)[0]
    return text


def get_excerpt(video_id: str, max_chars: int = 500) -> str:
    """Get first N chars of transcript as excerpt."""
    for suffix in ['-corrected.txt', '-merged.txt', '-whisper-turbo.txt']:
        txt_path = TRANSCRIPTS_DIR / f"{video_id}{suffix}"
        if txt_path.exists():
            content = txt_path.read_text(encoding='utf-8', errors='replace')
            if len(content) > max_chars:
                content = content[:max_chars].rsplit(' ', 1)[0] + '…'
            return content
    # Try SRT
    for suffix in ['.en.srt']:
        srt_path = TRANSCRIPTS_DIR / f"{video_id}{suffix}"
        if srt_path.exists():
            content = srt_path.read_text(encoding='utf-8', errors='replace')
            lines = content.split('\n')
            text_lines = []
            for line in lines:
                line = line.strip()
                if not line or line.isdigit() or '-->' in line:
                    continue
                text_lines.append(line)
            full_text = ' '.join(text_lines)
            if len(full_text) > max_chars:
                full_text = full_text[:max_chars].rsplit(' ', 1)[0] + '…'
            return full_text
    return ''


def main():
    print("Loading catalog and creators...")
    with open(CATALOG_PATH) as f:
        catalog = json.load(f)
    with open(CREATORS_PATH) as f:
        creators = json.load(f)

    # Filter to only holography and holography-adjacent content
    catalog = [v for v in catalog if v.get('relevance') in ('holography', 'holography-adjacent')]

    creators_by_id = {c['id']: c for c in creators}

    # Build search entries
    entries = []
    for v in catalog:
        video_id = v['id']
        title = v.get('title', video_id)
        creator_id = v.get('creator_id', '')
        creator = creators_by_id.get(creator_id, {})

        # Format date
        date = v.get('upload_date', '')
        if date:
            try:
                date = f"{date[:4]}-{date[4:6]}-{date[6:]}"
            except (ValueError, IndexError):
                pass

        # Duration
        dur = v.get('duration', 0) or 0
        mins = int(dur) // 60
        secs = int(dur) % 60

        # Get transcript excerpt
        excerpt = get_excerpt(video_id, 500)

        entry = {
            'id': video_id,
            'title': title,
            'slug': slugify(title),
            'date': date,
            'duration': f"{mins}:{secs:02d}",
            'duration_secs': dur,
            'platform': v.get('platform', 'unknown'),
            'creator_id': creator_id,
            'creator_name': v.get('creator_name', creator.get('name', '')),
            'tier': creator.get('tier', 0),
            'excerpt': excerpt,
            'url': f"https://youtube.com/watch?v={video_id}" if v.get('platform') == 'youtube'
                   else f"https://vimeo.com/{video_id}" if v.get('platform') == 'vimeo' else '',
        }

        # Skip videos with no transcript data at all
        if not excerpt and not v.get('title'):
            continue

        entries.append(entry)

    # Build creator index
    creator_index = []
    for c in creators:
        creator_videos = [e for e in entries if e['creator_id'] == c['id']]
        total_duration = sum(e['duration_secs'] for e in creator_videos)
        creator_index.append({
            'id': c['id'],
            'name': c['name'],
            'slug': slugify(c['name']),
            'platform': c.get('platform', 'unknown'),
            'tier': c.get('tier', 0),
            'status': c.get('status', 'unknown'),
            'description': c.get('description', ''),
            'video_count': len(creator_videos),
            'total_duration_secs': total_duration,
            'website': c.get('website', ''),
            'channel_url': c.get('channel_url', ''),
        })

    # Platform stats
    platform_stats = {}
    for e in entries:
        p = e['platform']
        if p not in platform_stats:
            platform_stats[p] = {'videos': 0, 'duration': 0, 'creators': set()}
        platform_stats[p]['videos'] += 1
        platform_stats[p]['duration'] += e['duration_secs']
        platform_stats[p]['creators'].add(e['creator_id'])

    # Convert sets to counts
    for p in platform_stats:
        platform_stats[p]['creator_count'] = len(platform_stats[p]['creators'])
        del platform_stats[p]['creators']

    index = {
        'generated': datetime.now().isoformat(),
        'total_videos': len(catalog),
        'indexed_videos': len(entries),
        'total_creators': len(creators),
        'platforms': platform_stats,
        'creators': creator_index,
        'entries': entries,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, 'w') as f:
        json.dump(index, f, separators=(',', ':'))

    size_mb = OUTPUT_PATH.stat().st_size / (1024 * 1024)
    print(f"Built search index: {len(entries)} entries, {len(creator_index)} creators")
    print(f"Index size: {size_mb:.1f} MB")
    print(f"Output: {OUTPUT_PATH}")


if __name__ == '__main__':
    main()