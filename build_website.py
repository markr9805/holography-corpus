#!/usr/bin/env python3
"""
Generate a static website for the holography transcript corpus.

Produces a clean, modern dark-themed static site with:
- Home page with corpus stats and visualization
- Creator index page listing all creators
- Per-creator pages with their videos
- Per-video pages with transcript, embed, and metadata
- Search page with client-side Lunr.js search

Output: website/ directory

Usage:
    python3 build_website.py
"""

import json
import os
import re
import html
from pathlib import Path
from datetime import datetime

PIPELINE_DIR = Path(__file__).parent
CATALOG_PATH = PIPELINE_DIR / "catalog.json"
CREATORS_PATH = PIPELINE_DIR / "creators.json"
TRANSCRIPTS_DIR = PIPELINE_DIR / "transcripts"
OUTPUT_DIR = PIPELINE_DIR / "website"
SEARCH_INDEX_PATH = PIPELINE_DIR / "analysis" / "search-index.json"


def slugify(text: str) -> str:
    """Create URL-safe slug from text."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    text = re.sub(r'-+', '-', text)
    text = text.strip('-')
    if len(text) > 80:
        text = text[:77].rsplit('-', 1)[0]
    return text or 'untitled'


def format_duration(seconds: float) -> str:
    """Format seconds as human-readable duration."""
    if not seconds:
        return "0m"
    m = int(seconds) // 60
    s = int(seconds) % 60
    if m >= 60:
        h = m // 60
        m = m % 60
        return f"{h}h {m}m"
    return f"{m}m {s}s"


def format_date(date_str: str) -> str:
    """Format YYYYMMDD or YYYY-MM-DD date."""
    if not date_str:
        return "Unknown"
    try:
        clean = date_str.replace('-', '')[:8]
        dt = datetime.strptime(clean, '%Y%m%d')
        return dt.strftime('%B %d, %Y')
    except (ValueError, IndexError):
        return date_str


def get_embed_html(video):
    """Get embed HTML for a video based on platform."""
    platform = video.get('platform', 'youtube')
    vid = video['id']
    if platform == 'youtube':
        return f'<div class="video-embed"><iframe src="https://www.youtube.com/embed/{vid}" frameborder="0" allowfullscreen loading="lazy"></iframe></div>'
    elif platform == 'vimeo':
        return f'<div class="video-embed"><iframe src="https://player.vimeo.com/video/{vid}" frameborder="0" allowfullscreen loading="lazy"></iframe></div>'
    return ''


def get_video_url(video):
    """Get the watch URL for a video."""
    platform = video.get('platform', 'youtube')
    vid = video['id']
    if platform == 'youtube':
        return f"https://www.youtube.com/watch?v={vid}"
    elif platform == 'vimeo':
        return f"https://vimeo.com/{vid}"
    return f"https://www.youtube.com/watch?v={vid}"


def get_transcript_text(video_id: str) -> str:
    """Get full transcript text for a video."""
    # Prefer corrected > merged > whisper-turbo > whisper-largev3 > parakeet
    for suffix in ['-corrected.txt', '-merged.txt', '-whisper-turbo.txt', '-whisper-largev3.txt']:
        path = TRANSCRIPTS_DIR / f"{video_id}{suffix}"
        if path.exists():
            return path.read_text(encoding='utf-8', errors='replace')
    # Try parakeet SRT (strip timestamps)
    srt_path = TRANSCRIPTS_DIR / f"{video_id}-parakeet.srt"
    if srt_path.exists():
        return srt_to_text(srt_path.read_text(encoding='utf-8', errors='replace'))
    return ''


def srt_to_text(srt_content: str) -> str:
    """Convert SRT format to plain text."""
    lines = []
    for line in srt_content.strip().split('\n'):
        line = line.strip()
        # Skip sequence numbers, timestamps, and blank lines
        if not line or line.isdigit() or '-->' in line:
            continue
        lines.append(line)
    return ' '.join(lines)


def get_excerpt(text: str, max_chars: int = 300) -> str:
    """Get a short excerpt from transcript text."""
    if not text:
        return ''
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(' ', 1)[0] + '…'


# CSS for the dark theme
CSS = """
:root {
    --bg-primary: #0d1117;
    --bg-secondary: #161b22;
    --bg-tertiary: #21262d;
    --border: #30363d;
    --text-primary: #f0f6fc;
    --text-secondary: #c9d1d9;
    --text-muted: #8b949e;
    --accent: #58a6ff;
    --accent-hover: #79c0ff;
    --accent-dim: #1f6feb;
    --success: #3fb950;
    --warning: #d29922;
    --danger: #f85149;
    --tier1: #58a6ff;
    --tier2: #3fb950;
    --tier3: #d29922;
    --tier4: #8b949e;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
    background: var(--bg-primary);
    color: var(--text-secondary);
    line-height: 1.6;
    -webkit-font-smoothing: antialiased;
}

a { color: var(--accent); text-decoration: none; }
a:hover { color: var(--accent-hover); text-decoration: underline; }

.container {
    max-width: 1200px;
    margin: 0 auto;
    padding: 0 20px;
}

header {
    background: var(--bg-secondary);
    border-bottom: 1px solid var(--border);
    padding: 16px 0;
    position: sticky;
    top: 0;
    z-index: 100;
}

header .container {
    display: flex;
    align-items: center;
    justify-content: space-between;
}

.logo {
    font-size: 1.2em;
    font-weight: 700;
    color: var(--text-primary);
}

.logo span { color: var(--accent); }

nav { display: flex; gap: 24px; }

nav a {
    color: var(--text-muted);
    font-size: 0.9em;
    font-weight: 500;
    transition: color 0.2s;
}

nav a:hover { color: var(--accent); text-decoration: none; }

main { padding: 32px 0; }

h1 { color: var(--text-primary); font-size: 2em; margin-bottom: 16px; }
h2 { color: var(--text-primary); font-size: 1.5em; margin: 32px 0 16px; }
h3 { color: var(--text-primary); font-size: 1.2em; margin: 24px 0 12px; }

.stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 16px;
    margin: 24px 0;
}

.stat-card {
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 20px;
    text-align: center;
}

.stat-value { font-size: 2em; color: var(--accent); font-weight: 700; }
.stat-label { color: var(--text-muted); font-size: 0.85em; margin-top: 4px; }

.card-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
    gap: 20px;
    margin: 24px 0;
}

.card {
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 20px;
    transition: border-color 0.2s;
}

.card:hover { border-color: var(--accent); }

.card h3 {
    color: var(--text-primary);
    font-size: 1em;
    margin: 0 0 8px 0;
    line-height: 1.4;
}

.card-meta {
    color: var(--text-muted);
    font-size: 0.8em;
    margin-bottom: 8px;
}
.off-topic-note {
    background: #1a1a2e;
    border: 1px solid #333;
    border-radius: 8px;
    padding: 0.75rem 1rem;
    margin-bottom: 1rem;
    color: #aaa;
    font-size: 0.9rem;
}
.off-topic-note a {
    color: #00d4ff;
}
.relevance-filter {
    display: flex;
    gap: 0.5rem;
    margin-bottom: 1.5rem;
    flex-wrap: wrap;
}
.filter-btn {
    padding: 0.4rem 1rem;
    border: 1px solid #333;
    border-radius: 20px;
    background: #1a1a2e;
    color: #ccc;
    cursor: pointer;
    font-size: 0.85rem;
    transition: all 0.2s;
}
.filter-btn:hover {
    border-color: #00d4ff;
    color: #00d4ff;
}
.filter-btn.active {
    background: #00d4ff;
    color: #000;
    border-color: #00d4ff;
}

.card-excerpt {
    color: var(--text-secondary);
    font-size: 0.85em;
    line-height: 1.5;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
}

.tier-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 0.75em;
    font-weight: 600;
}

.tier-1 { background: rgba(88,166,255,0.2); color: var(--tier1); }
.tier-2 { background: rgba(63,185,80,0.2); color: var(--tier2); }
.tier-3 { background: rgba(210,153,34,0.2); color: var(--tier3); }
.tier-4 { background: rgba(139,148,158,0.2); color: var(--tier4); }

.status-dot {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    margin-right: 4px;
}

.status-active { background: var(--success); }
.status-semi-active { background: var(--warning); }
.status-inactive { background: var(--danger); }
.status-unknown { background: var(--text-muted); }

.video-embed {
    position: relative;
    padding-bottom: 56.25%;
    height: 0;
    overflow: hidden;
    border-radius: 8px;
    margin: 16px 0;
}

.video-embed iframe {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
}

.transcript {
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 24px;
    margin: 16px 0;
    max-height: 600px;
    overflow-y: auto;
    font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
    font-size: 0.85em;
    line-height: 1.7;
    white-space: pre-wrap;
    word-wrap: break-word;
}

.meta-table {
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px 20px;
    margin: 16px 0;
}

.meta-table table { width: 100%; border-collapse: collapse; }
.meta-table td { padding: 6px 0; }
.meta-table td:first-child { color: var(--text-muted); width: 140px; }

.search-box {
    display: flex;
    gap: 12px;
    margin: 24px 0;
}

.search-box input {
    flex: 1;
    padding: 12px 16px;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text-primary);
    font-size: 1em;
    outline: none;
}

.search-box input:focus { border-color: var(--accent); }

.search-box button {
    padding: 12px 24px;
    background: var(--accent-dim);
    border: none;
    border-radius: 8px;
    color: white;
    font-size: 1em;
    cursor: pointer;
}

.search-box button:hover { background: var(--accent); }

.search-results { margin: 16px 0; }

.search-result {
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    margin-bottom: 12px;
}

.search-result h3 { margin: 0 0 4px 0; font-size: 1em; }
.search-result p { margin: 4px 0; font-size: 0.85em; color: var(--text-muted); }
.search-result .highlight { background: rgba(88,166,255,0.3); padding: 1px 3px; border-radius: 2px; }

.creator-header {
    display: flex;
    align-items: flex-start;
    gap: 24px;
    margin: 24px 0;
}

.creator-info { flex: 1; }

.creator-description {
    color: var(--text-secondary);
    margin: 12px 0;
    line-height: 1.6;
}

.platform-tag {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 0.75em;
    font-weight: 600;
    background: var(--bg-tertiary);
    color: var(--text-secondary);
    margin-left: 8px;
}

footer {
    background: var(--bg-secondary);
    border-top: 1px solid var(--border);
    padding: 24px 0;
    margin-top: 48px;
    text-align: center;
    color: var(--text-muted);
    font-size: 0.85em;
}

@media (max-width: 768px) {
    .container { padding: 0 16px; }
    .stats-grid { grid-template-columns: repeat(2, 1fr); }
    .card-grid { grid-template-columns: 1fr; }
    .creator-header { flex-direction: column; }
    h1 { font-size: 1.5em; }
}
"""


def build_home_page(catalog, creators, search_index):
    """Build the home page."""
    total_videos = len(catalog)
    total_creators = len(creators)
    total_duration = sum(v.get('duration', 0) for v in catalog)
    total_hours = int(total_duration) // 3600

    platform_counts = {}
    for v in catalog:
        p = v.get('platform', 'unknown')
        platform_counts[p] = platform_counts.get(p, 0) + 1

    # Recent videos (last 10 with dates)
    dated = [v for v in catalog if v.get('upload_date')]
    recent = sorted(dated, key=lambda x: x.get('upload_date', ''), reverse=True)[:10]

    # Creators with content (sorted by video count, show top 12)
    active_creators = sorted(
        [c for c in creators if sum(1 for v in catalog if v.get('creator_id') == c['id']) > 0],
        key=lambda x: sum(1 for v in catalog if v.get('creator_id') == x['id']),
        reverse=True
    )[:12]

    html_parts = [
        '<!DOCTYPE html>',
        '<html lang="en">',
        '<head>',
        '<meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
        '<title>Holography Corpus — Transcript Archive</title>',
        f'<style>{CSS}</style>',
        '</head>',
        '<body>',
        '<header>',
        '<div class="container">',
        '<div class="logo">🔬 <span>Holography</span> Corpus</div>',
        '<nav>',
        '<a href="index.html">Home</a>',
        '<a href="creators/index.html">Creators</a>',
        '<a href="search/index.html">Search</a>',
        '</nav>',
        '</div>',
        '</header>',
        '<main class="container">',
        '<h1>Holography Transcript Corpus</h1>',
        '<p>Complete transcript archive for holography content creators across YouTube, Vimeo, and the web.</p>',

        # Stats
        '<div class="stats-grid">',
        f'<div class="stat-card"><div class="stat-value">{total_videos}</div><div class="stat-label">Videos</div></div>',
        f'<div class="stat-card"><div class="stat-value">{total_creators}</div><div class="stat-label">Creators</div></div>',
        f'<div class="stat-card"><div class="stat-value">{total_hours}h</div><div class="stat-label">Total Hours</div></div>',
        f'<div class="stat-card"><div class="stat-value">{len(platform_counts)}</div><div class="stat-label">Platforms</div></div>',
        '</div>',

        # Platform breakdown
        '<h2>By Platform</h2>',
        '<div class="stats-grid">',
    ]

    for platform, count in sorted(platform_counts.items()):
        html_parts.append(
            f'<div class="stat-card"><div class="stat-value">{count}</div><div class="stat-label">{platform.title()}</div></div>'
        )

    html_parts.extend([
        '</div>',

        # Active creators
        '<h2>Active Creators</h2>',
        '<div class="card-grid">',
    ])

    for c in active_creators:
        tier = c.get('tier', 4)
        slug = slugify(c['name'])
        vid_count = sum(1 for v in catalog if v.get('creator_id') == c['id'])
        dur = sum(v.get('duration', 0) for v in catalog if v.get('creator_id') == c['id'])
        desc = c.get('description', '')[:200]
        html_parts.append(f'''
        <a href="creators/{slug}.html" class="card">
            <h3><span class="status-dot status-active"></span>{html.escape(c['name'])}
                <span class="tier-badge tier-{tier}">Tier {tier}</span>
                <span class="platform-tag">{c.get('platform', '').title()}</span>
            </h3>
            <div class="card-meta">{vid_count} videos · {format_duration(dur)}</div>
            <div class="card-excerpt">{html.escape(desc)}</div>
        </a>''')

    html_parts.extend([
        '</div>',

        # Recent videos
        '<h2>Recent Videos</h2>',
        '<div class="card-grid">',
    ])

    for v in recent:
        vid = v['id']
        title = v.get('title', vid)
        creator = v.get('creator_name', 'Unknown')
        date = format_date(v.get('upload_date', ''))
        dur = format_duration(v.get('duration', 0))
        platform = v.get('platform', 'youtube')
        video_slug = slugify(title)
        html_parts.append(f'''
        <a href="videos/{video_slug}.html" class="card">
            <h3>{html.escape(title)}</h3>
            <div class="card-meta">{html.escape(creator)} · {date} · {dur} · {platform.title()}</div>
        </a>''')

    html_parts.extend([
        '</div>',
        '</main>',
        '<footer>',
        '<div class="container">',
        f'<p>Holography Corpus · Generated {datetime.now().strftime("%Y-%m-%d")} · {total_videos} videos from {total_creators} creators</p>',
        '</div>',
        '</footer>',
        '</body>',
        '</html>',
    ])

    return '\n'.join(html_parts)


def build_creators_page(catalog, creators):
    """Build the creators index page."""
    creators_by_id = {c['id']: c for c in creators}

    html_parts = [
        '<!DOCTYPE html>',
        '<html lang="en">',
        '<head>',
        '<meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
        '<title>Creators — Holography Corpus</title>',
        f'<style>{CSS}</style>',
        '</head>',
        '<body>',
        '<header>',
        '<div class="container">',
        '<div class="logo">🔬 <span>Holography</span> Corpus</div>',
        '<nav>',
        '<a href="../index.html">Home</a>',
        '<a href="index.html">Creators</a>',
        '<a href="../search/index.html">Search</a>',
        '</nav>',
        '</div>',
        '</header>',
        '<main class="container">',
        '<h1>Holography Creators</h1>',
        '<p>All holography content creators indexed in the corpus, organized by tier.</p>',
    ]

    # Group by tier
    for tier in [1, 2, 3, 4]:
        tier_creators = sorted(
            [c for c in creators if c.get('tier') == tier],
            key=lambda x: x.get('name', '')
        )
        if not tier_creators:
            continue

        tier_names = {1: 'Primary', 2: 'Secondary', 3: 'Tertiary', 4: 'Supplementary'}
        html_parts.append(f'<h2>Tier {tier} — {tier_names[tier]}</h2>')
        html_parts.append('<div class="card-grid">')

        for c in tier_creators:
            slug = slugify(c['name'])
            vid_count = sum(1 for v in catalog if v.get('creator_id') == c['id'])
            dur = sum(v.get('duration', 0) for v in catalog if v.get('creator_id') == c['id'])
            status = c.get('status', 'unknown')
            desc = c.get('description', '')[:200]
            html_parts.append(f'''
            <a href="{slug}.html" class="card">
                <h3><span class="status-dot status-{status}"></span>{html.escape(c['name'])}
                    <span class="tier-badge tier-{tier}">Tier {tier}</span>
                    <span class="platform-tag">{c.get('platform', '').title()}</span>
                </h3>
                <div class="card-meta">{vid_count} videos · {format_duration(dur)}</div>
                <div class="card-excerpt">{html.escape(desc)}</div>
            </a>''')

        html_parts.append('</div>')

    html_parts.extend([
        '</main>',
        '<footer>',
        '<div class="container">',
        f'<p>Holography Corpus · {len(creators)} creators</p>',
        '</div>',
        '</footer>',
        '</body>',
        '</html>',
    ])

    return '\n'.join(html_parts)


def build_creator_page(creator, catalog, off_topic_count=0):
    """Build a single creator page."""
    creator_videos = sorted(
        [v for v in catalog if v.get('creator_id') == creator['id']],
        key=lambda x: x.get('upload_date', ''),
        reverse=True
    )
    total_duration = sum(v.get('duration', 0) for v in creator_videos)
    slug = slugify(creator['name'])

    html_parts = [
        '<!DOCTYPE html>',
        '<html lang="en">',
        '<head>',
        '<meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
        f'<title>{html.escape(creator["name"])} — Holography Corpus</title>',
        f'<style>{CSS}</style>',
        '</head>',
        '<body>',
        '<header>',
        '<div class="container">',
        '<div class="logo">🔬 <span>Holography</span> Corpus</div>',
        '<nav>',
        '<a href="../index.html">Home</a>',
        '<a href="index.html">Creators</a>',
        '<a href="../search/index.html">Search</a>',
        '</nav>',
        '</div>',
        '</header>',
        '<main class="container">',
        '<div class="creator-header">',
        '<div class="creator-info">',
        f'<h1><span class="status-dot status-{creator.get("status", "unknown")}"></span>{html.escape(creator["name"])} <span class="tier-badge tier-{creator.get("tier", 4)}">Tier {creator.get("tier", 4)}</span></h1>',
        f'<p class="creator-description">{html.escape(creator.get("description", ""))}</p>',
        '<div class="stats-grid">',
        f'<div class="stat-card"><div class="stat-value">{len(creator_videos)}</div><div class="stat-label">Videos</div></div>',
        f'<div class="stat-card"><div class="stat-value">{format_duration(total_duration)}</div><div class="stat-label">Total Duration</div></div>',
        f'<div class="stat-card"><div class="stat-value">{creator.get("platform", "").title()}</div><div class="stat-label">Platform</div></div>',
        '</div>',
        '<p>',
    ]

    # Links
    html_parts.append(f'<a href="{html.escape(creator.get("channel_url", ""))}" target="_blank">🔗 Channel</a>')
    if creator.get('website'):
        html_parts.append(f' · <a href="{html.escape(creator["website"])}" target="_blank">🌐 Website</a>')
    if creator.get('patreon'):
        html_parts.append(f' · <a href="{html.escape(creator["patreon"])}" target="_blank">💰 Patreon</a>')

    html_parts.extend(['</p>', '</div>', '</div>'])

    # Off-topic content note
    if off_topic_count > 0:
        channel_url = creator.get('channel_url', '')
        html_parts.append(f'''
        <div class="off-topic-note">
            <p>📌 This creator has {off_topic_count} additional video{'s' if off_topic_count > 1 else ''} outside the scope of this corpus (film, animation, personal content, etc.).
            {' <a href="' + html.escape(channel_url) + '" target="_blank">View full channel on YouTube →</a>' if channel_url else ''}</p>
        </div>''')

    # Relevance filter buttons
    from collections import Counter
    relevance_counts = Counter(v.get('relevance', 'other') for v in creator_videos)
    filter_html = '<div class="relevance-filter">'
    filter_html += '<button class="filter-btn active" data-filter="all">All</button>'
    if 'holography' in relevance_counts:
        filter_html += f'<button class="filter-btn" data-filter="holography">🔬 Holography ({relevance_counts["holography"]})</button>'
    if 'holography-adjacent' in relevance_counts:
        filter_html += f'<button class="filter-btn" data-filter="holography-adjacent">🔗 Adjacent ({relevance_counts["holography-adjacent"]})</button>'
    if 'off-topic' in relevance_counts:
        filter_html += f'<button class="filter-btn" data-filter="off-topic">📎 Off-topic ({relevance_counts["off-topic"]})</button>'
    filter_html += '</div>'
    html_parts.append(filter_html)

    # Videos list
    html_parts.append('<h2>Videos</h2>')
    html_parts.append('<div class="card-grid" id="video-grid">')

    for v in creator_videos:
        vid = v['id']
        title = v.get('title', vid)
        video_slug = slugify(title)
        date = format_date(v.get('upload_date', ''))
        dur = format_duration(v.get('duration', 0))
        platform = v.get('platform', 'youtube')
        excerpt = get_excerpt(get_transcript_text(vid), 200)

        relevance = v.get('relevance', 'other')
        relevance_label = {'holography': '🔬 Holography', 'holography-adjacent': '🔗 Adjacent', 'off-topic': '📎 Off-topic'}.get(relevance, '')

        html_parts.append(f'''
        <a href="../videos/{video_slug}.html" class="card" data-relevance="{relevance}">
            <h3>{html.escape(title)}</h3>
            <div class="card-meta">{date} · {dur} · {platform.title()} {relevance_label}</div>
            <div class="card-excerpt">{html.escape(excerpt)}</div>
        </a>''')

    html_parts.extend([
        '</div>',
        '</main>',
        '<footer>',
        '<div class="container">',
        f'<p>{html.escape(creator["name"])} · {len(creator_videos)} videos</p>',
        '</div>',
        '</footer>',
        '<script>',
        'document.querySelectorAll(".filter-btn").forEach(btn => {',
        '  btn.addEventListener("click", () => {',
        '    document.querySelectorAll(".filter-btn").forEach(b => b.classList.remove("active"));',
        '    btn.classList.add("active");',
        '    const filter = btn.dataset.filter;',
        '    document.querySelectorAll("#video-grid .card").forEach(card => {',
        '      card.style.display = (filter === "all" || card.dataset.relevance === filter) ? "" : "none";',
        '    });',
        '  });',
        '});',
        '</script>',
        '</body>',
        '</html>',
    ])

    return '\n'.join(html_parts)


def build_video_page(video, creator):
    """Build a single video page."""
    vid = video['id']
    title = video.get('title', vid)
    slug = slugify(title)
    platform = video.get('platform', 'youtube')
    creator_name = video.get('creator_name', 'Unknown')
    creator_slug = slugify(creator_name)
    date = format_date(video.get('upload_date', ''))
    dur = format_duration(video.get('duration', 0))
    tier = creator.get('tier', 0) if creator else 0

    transcript = get_transcript_text(vid)
    embed = get_embed_html(video)

    html_parts = [
        '<!DOCTYPE html>',
        '<html lang="en">',
        '<head>',
        '<meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
        f'<title>{html.escape(title)} — Holography Corpus</title>',
        f'<style>{CSS}</style>',
        '</head>',
        '<body>',
        '<header>',
        '<div class="container">',
        '<div class="logo">🔬 <span>Holography</span> Corpus</div>',
        '<nav>',
        '<a href="../index.html">Home</a>',
        '<a href="../creators/index.html">Creators</a>',
        '<a href="../search/index.html">Search</a>',
        '</nav>',
        '</div>',
        '</header>',
        '<main class="container">',
        f'<h1>{html.escape(title)}</h1>',

        # Embed
        embed,

        # Metadata
        '<div class="meta-table">',
        '<table>',
        f'<tr><td>Creator</td><td><a href="../creators/{creator_slug}.html">{html.escape(creator_name)}</a> <span class="tier-badge tier-{tier}">Tier {tier}</span></td></tr>',
        f'<tr><td>Date</td><td>{date}</td></tr>',
        f'<tr><td>Duration</td><td>{dur}</td></tr>',
        f'<tr><td>Platform</td><td>{platform.title()}</td></tr>',
        f'<tr><td>Watch</td><td><a href="{get_video_url(video)}" target="_blank">{get_video_url(video)}</a></td></tr>',
        '</table>',
        '</div>',
    ]

    if transcript:
        html_parts.extend([
            '<h2>Transcript</h2>',
            f'<div class="transcript">{html.escape(transcript)}</div>',
        ])
    else:
        html_parts.append('<p><em>Transcript not yet available for this video.</em></p>')

    html_parts.extend([
        '</main>',
        '<footer>',
        '<div class="container">',
        f'<p>{html.escape(title)} · {html.escape(creator_name)}</p>',
        '</div>',
        '</footer>',
        '</body>',
        '</html>',
    ])

    return '\n'.join(html_parts)


def build_search_page():
    """Build the search page with Lunr.js client-side search."""
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Search — Holography Corpus</title>
<style>{CSS}</style>
</head>
<body>
<header>
<div class="container">
<div class="logo">🔬 <span>Holography</span> Corpus</div>
<nav>
<a href="../index.html">Home</a>
<a href="../creators/index.html">Creators</a>
<a href="index.html">Search</a>
</nav>
</div>
</header>
<main class="container">
<h1>Search the Corpus</h1>
<p>Search across all transcripts and video metadata.</p>

<div class="search-box">
<input type="text" id="search-input" placeholder="Search transcripts, creators, topics..." autofocus>
<button onclick="doSearch()">Search</button>
</div>

<div id="search-results" class="search-results"></div>
</main>
<footer>
<div class="container">
<p>Holography Corpus · Client-side search powered by Lunr.js</p>
</div>
</footer>

<script src="https://cdn.jsdelivr.net/npm/lunr@2.3.9/lunr.min.js"></script>
<script>
let searchIndex;
let documents = [];

fetch('../analysis/search-index.json')
  .then(r => r.json())
  .then(data => {{
    documents = data.entries;
    searchIndex = lunr(function() {{
      this.ref('id');
      this.field('title', {{ boost: 10 }});
      this.field('creator_name', {{ boost: 5 }});
      this.field('excerpt');
      this.field('platform');

      data.entries.forEach(doc => {{
        this.add(doc);
      }});
    }});

    // Check for URL query param
    const params = new URLSearchParams(window.location.search);
    const q = params.get('q');
    if (q) {{
      document.getElementById('search-input').value = q;
      doSearch();
    }}
  }});

function doSearch() {{
  const query = document.getElementById('search-input').value.trim();
  const resultsDiv = document.getElementById('search-results');

  if (!query) {{
    resultsDiv.innerHTML = '<p>Enter a search term.</p>';
    return;
  }}

  if (!searchIndex) {{
    resultsDiv.innerHTML = '<p>Search index is loading...</p>';
    return;
  }}

  try {{
    const results = searchIndex.search(query);
    if (results.length === 0) {{
      resultsDiv.innerHTML = '<p>No results found for "' + query + '"</p>';
      return;
    }}

    resultsDiv.innerHTML = '<p>Found ' + results.length + ' results:</p>';

    results.forEach(result => {{
      const doc = documents.find(d => d.id === result.ref);
      if (!doc) return;

      const div = document.createElement('div');
      div.className = 'search-result';
      div.innerHTML = '<h3><a href="../videos/' + doc.slug + '.html">' + doc.title + '</a></h3>' +
        '<p>' + doc.creator_name + ' · ' + doc.date + ' · ' + doc.duration + '</p>' +
        '<p>' + doc.excerpt.substring(0, 200) + '</p>';
      resultsDiv.appendChild(div);
    }});
  }} catch(e) {{
    resultsDiv.innerHTML = '<p>Search error: ' + e.message + '</p>';
  }}
}}

document.getElementById('search-input').addEventListener('keydown', function(e) {{
  if (e.key === 'Enter') doSearch();
}});
</script>
</body>
</html>'''
    return html


def main():
    print("Loading catalog and creators...")
    with open(CATALOG_PATH) as f:
        full_catalog = json.load(f)
    with open(CREATORS_PATH) as f:
        creators = json.load(f)

    # Filter to only holography and holography-adjacent content
    catalog = [v for v in full_catalog if v.get('relevance') in ('holography', 'holography-adjacent')]
    removed = len(full_catalog) - len(catalog)
    print(f"Filtered catalog: {len(catalog)} videos (removed {removed} off-topic)")

    # Count off-topic per creator for notes
    from collections import Counter
    off_topic_counts = Counter()
    for v in full_catalog:
        if v.get('relevance') == 'off-topic':
            off_topic_counts[v.get('creator_id')] += 1

    creators_by_id = {c['id']: c for c in creators}

    # Create output directories
    (OUTPUT_DIR / "creators").mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "videos").mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "search").mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "static").mkdir(parents=True, exist_ok=True)

    # Write CSS
    with open(OUTPUT_DIR / "static" / "style.css", 'w') as f:
        f.write(CSS)

    # Build search index first (needed for home page)
    print("Building search index...")
    import subprocess
    subprocess.run([sys.executable, str(PIPELINE_DIR / "build_search_index.py")], check=True)

    # Home page
    print("Building home page...")
    search_index = None
    if SEARCH_INDEX_PATH.exists():
        with open(SEARCH_INDEX_PATH) as f:
            search_index = json.load(f)

    home_html = build_home_page(catalog, creators, search_index)
    with open(OUTPUT_DIR / "index.html", 'w') as f:
        f.write(home_html)

    # Creators index
    print("Building creators page...")
    creators_html = build_creators_page(catalog, creators)
    with open(OUTPUT_DIR / "creators" / "index.html", 'w') as f:
        f.write(creators_html)

    # Individual creator pages
    print("Building creator pages...")
    for creator in creators:
        slug = slugify(creator['name'])
        off_topic = off_topic_counts.get(creator['id'], 0)
        page_html = build_creator_page(creator, catalog, off_topic_count=off_topic)
        with open(OUTPUT_DIR / "creators" / f"{slug}.html", 'w') as f:
            f.write(page_html)

    # Video pages
    print("Building video pages...")
    for i, video in enumerate(catalog):
        vid = video['id']
        title = video.get('title', vid)
        slug = slugify(title)
        creator = creators_by_id.get(video.get('creator_id'), {})
        page_html = build_video_page(video, creator)
        with open(OUTPUT_DIR / "videos" / f"{slug}.html", 'w') as f:
            f.write(page_html)
        if (i + 1) % 100 == 0:
            print(f"  ... {i + 1} video pages built")

    # Search page
    print("Building search page...")
    search_html = build_search_page()
    with open(OUTPUT_DIR / "search" / "index.html", 'w') as f:
        f.write(search_html)

    # Copy search index to website for serving
    if SEARCH_INDEX_PATH.exists():
        import shutil
        (OUTPUT_DIR / "analysis").mkdir(parents=True, exist_ok=True)
        shutil.copy2(SEARCH_INDEX_PATH, OUTPUT_DIR / "analysis" / "search-index.json")

    print(f"\n✅ Website built at {OUTPUT_DIR}")
    print(f"   {len(catalog)} video pages (holography + adjacent only)")
    print(f"   {len(creators)} creator pages")
    print(f"   Home, creators index, and search pages")
    print(f"\nTo serve locally: cd {OUTPUT_DIR} && python3 -m http.server 8000")


if __name__ == '__main__':
    import sys
    main()