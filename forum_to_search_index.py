#!/usr/bin/env python3
"""
Forum Search Index Builder
============================
Adds forum thread data to the holography search index, enabling
search across both video transcripts and forum discussions.

Each thread gets: title, forum, authors, date range, post count,
excerpt, url — searchable by content, author, forum section, topic.

Usage:
    python3 forum_to_search_index.py                  # Build/update forum index
    python3 forum_to_search_index.py --merge          # Merge with video search index
    python3 forum_to_search_index.py --forum 7        # Index only DCG topics
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
FORUM_DIR = SCRIPT_DIR / "forum"
TOPICS_DIR = FORUM_DIR / "topics"
ANALYSIS_DIR = SCRIPT_DIR / "analysis"
FORUM_INDEX_FILE = ANALYSIS_DIR / "forum-search-index.json"
MERGED_INDEX_FILE = ANALYSIS_DIR / "search-index.json"

# Forum definitions
FORUMS = {
    30: ("General Holography (old)", "General-Old"),
    7:  ("DCG - Dichromated Gelatin", "DCG"),
    5:  ("Techniques", "Techniques"),
    45: ("Beginning Holography", "Beginners"),
    32: ("Gallery", "Gallery"),
    9:  ("AgX - Silver Halide Emulsions", "AgX"),
    23: ("Optics", "Optics"),
    6:  ("Equipment", "Equipment"),
    53: ("Events, announcements, and news", "Events"),
    3:  ("ISDH / Symposia", "ISDH"),
    4:  ("Announcements", "Announcements"),
    8:  ("General Holography (new)", "General-New"),
    41: ("Network54 Archived Posts", "Network54"),
    33: ("Links", "Links"),
    39: ("For Sale or Trade", "ForSale"),
    12: ("Off Topic", "OffTopic"),
    34: ("Off Topic (old)", "OffTopic-Old"),
    52: ("Holography Jobs", "Jobs"),
    31: ("Administration", "Admin"),
    54: ("The Dump", "Dump"),
}

# Forum categories for faceted search
FORUM_CATEGORIES = {
    'techniques': ['DCG', 'Techniques', 'AgX', 'Optics'],
    'community': ['General-Old', 'General-New', 'Beginners', 'Gallery', 'Announcements', 'ISDH', 'Events'],
    'resources': ['Equipment', 'Links', 'ForSale', 'Jobs'],
    'archive': ['Network54', 'OffTopic', 'OffTopic-Old', 'Admin', 'Dump'],
}


def get_forum_category(forum_short: str) -> str:
    """Get the category for a forum short name."""
    for cat, forums in FORUM_CATEGORIES.items():
        if forum_short in forums:
            return cat
    return 'other'


def get_excerpt(topic_data: dict, max_chars: int = 500) -> str:
    """Get an excerpt from the first post of a topic."""
    posts = topic_data.get('posts', [])
    if not posts:
        return ''

    # Get first post content
    first_post = posts[0]
    content = first_post.get('content_md', '')

    # Clean up for excerpt
    content = content.strip()
    # Remove markdown image syntax
    import re
    content = re.sub(r'!\[.*?\]\(.*?\)', '', content)
    # Remove URLs but keep link text
    content = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', content)
    # Remove remaining markdown
    content = re.sub(r'[*#>`_~]', '', content)
    # Collapse whitespace
    content = re.sub(r'\s+', ' ', content).strip()

    if len(content) > max_chars:
        content = content[:max_chars].rsplit(' ', 1)[0] + '…'

    return content


def get_all_content(topic_data: dict) -> str:
    """Get all post content concatenated for full-text search."""
    parts = []
    for post in topic_data.get('posts', []):
        content = post.get('content_md', '').strip()
        if content:
            author = post.get('author', '')
            parts.append(f"{author}: {content}")
    return '\n\n'.join(parts)


def build_forum_index(forum_ids: set | None = None) -> dict:
    """Build search index from all scraped topic JSON files."""
    topic_files = sorted(TOPICS_DIR.glob("topic_*.json"))
    if not topic_files:
        print("No topic files found. Run scrape_forum.py first.")
        return {'entries': [], 'generated': '', 'total_topics': 0}

    entries = []
    forum_counts = {}
    author_index = {}

    for tf in topic_files:
        try:
            data = json.loads(tf.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, IOError) as e:
            print(f"  [Error] Reading {tf.name}: {e}")
            continue

        # Filter by forum
        if forum_ids and data.get('forum_id') not in forum_ids:
            continue

        forum_id = data.get('forum_id', 0)
        forum_info = FORUMS.get(forum_id, (f'Forum {forum_id}', f'f{forum_id}'))
        forum_name = forum_info[0]
        forum_short = forum_info[1]

        # Collect authors
        authors = []
        for post in data.get('posts', []):
            author = post.get('author', '')
            if author and author not in authors:
                authors.append(author)
                # Build author index
                if author not in author_index:
                    author_index[author] = []
                author_index[author].append(data['topic_id'])

        # Date range
        dates = []
        for post in data.get('posts', []):
            dt = post.get('post_datetime', '')
            if dt:
                dates.append(dt)

        date_start = ''
        date_end = ''
        if dates:
            date_start = dates[0][:10]  # YYYY-MM-DD
            date_end = dates[-1][:10]

        # Get excerpt
        excerpt = get_excerpt(data)

        # Get full content for search
        full_content = get_all_content(data)

        # Build entry
        entry = {
            'id': f"forum-{data['topic_id']}",
            'type': 'forum-thread',
            'forum_id': forum_id,
            'forum': forum_short,
            'forum_full': forum_name,
            'category': get_forum_category(forum_short),
            'topic_id': data['topic_id'],
            'title': data.get('title', ''),
            'authors': authors[:20],
            'post_count': data.get('post_count', len(data.get('posts', []))),
            'views': data.get('views', 0),
            'date_start': date_start,
            'date_end': date_end,
            'excerpt': excerpt,
            'url': data.get('url', f"https://holographyforum.org/forum/viewtopic.php?t={data['topic_id']}"),
            'has_attachments': data.get('has_attachments', False),
            'is_sticky': data.get('is_sticky', False),
            'is_locked': data.get('is_locked', False),
        }

        entries.append(entry)

        # Track forum counts
        forum_counts[forum_short] = forum_counts.get(forum_short, 0) + 1

    # Sort by date (newest first)
    entries.sort(key=lambda e: e.get('date_start', ''), reverse=True)

    index = {
        'generated': datetime.now().isoformat(),
        'source': 'holographyforum.org',
        'total_topics': len(entries),
        'total_posts': sum(e['post_count'] for e in entries),
        'forum_counts': forum_counts,
        'forums': {fid: {'name': name, 'short': short}
                   for fid, (name, short) in FORUMS.items()},
        'categories': FORUM_CATEGORIES,
        'author_index': {author: {'count': len(topics), 'topics': topics[:50]}
                         for author, topics in author_index.items()},
        'entries': entries,
    }

    return index


def merge_with_video_index(forum_index: dict) -> dict:
    """Merge forum index with the existing video search index."""
    # Load existing video index
    video_index_path = ANALYSIS_DIR / 'search-index.json'
    if not video_index_path.exists():
        # Try the Darante pipeline
        video_index_path = Path(__file__).parent.parent / 'darante-transcript-pilot' / 'analysis' / 'search-index.json'

    video_entries = []
    if video_index_path.exists():
        try:
            video_data = json.loads(video_index_path.read_text())
            video_entries = video_data.get('entries', [])
            print(f"  Loaded {len(video_entries)} video entries from {video_index_path}")
        except (json.JSONDecodeError, IOError) as e:
            print(f"  [Warning] Could not load video index: {e}")

    # Merge entries
    all_entries = video_entries + forum_index['entries']

    # Build merged index
    merged = {
        'generated': datetime.now().isoformat(),
        'total_entries': len(all_entries),
        'video_entries': len(video_entries),
        'forum_entries': len(forum_index['entries']),
        'forum_counts': forum_index.get('forum_counts', {}),
        'categories': FORUM_CATEGORIES,
        'entries': all_entries,
    }

    return merged


def main():
    parser = argparse.ArgumentParser(
        description="Build search index from scraped forum data",
    )
    parser.add_argument('--forum', type=str, default=None,
                        help='Index only topics from this forum ID (comma-separated)')
    parser.add_argument('--merge', action='store_true',
                        help='Merge with existing video search index')
    parser.add_argument('--content', action='store_true',
                        help='Include full post content in index (larger file)')

    args = parser.parse_args()

    # Parse forum filter
    forum_ids = None
    if args.forum:
        forum_ids = set(int(x.strip()) for x in args.forum.split(','))

    # Build forum index
    print("Building forum search index...")
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)

    index = build_forum_index(forum_ids)

    if not index['entries']:
        print("No entries to index.")
        return

    # Optionally include full content
    if args.content:
        print("  Including full content...")
        topic_files = sorted(TOPICS_DIR.glob("topic_*.json"))
        for entry in index['entries']:
            topic_id = entry['topic_id']
            tf = TOPICS_DIR / f"topic_{topic_id}.json"
            if tf.exists():
                data = json.loads(tf.read_text(encoding='utf-8'))
                entry['full_content'] = get_all_content(data)

    # Save forum-specific index
    FORUM_INDEX_FILE.write_text(
        json.dumps(index, indent=2, ensure_ascii=False),
        encoding='utf-8'
    )
    size_kb = FORUM_INDEX_FILE.stat().st_size / 1024
    print(f"  Forum index: {len(index['entries'])} entries, {size_kb:.0f} KB")
    print(f"  Saved to: {FORUM_INDEX_FILE}")

    # Print stats
    print(f"\n  Forum breakdown:")
    for forum, count in sorted(index.get('forum_counts', {}).items(),
                                key=lambda x: -x[1]):
        print(f"    {forum}: {count} topics")

    print(f"\n  Top authors:")
    for author, info in sorted(index.get('author_index', {}).items(),
                                 key=lambda x: -x[1]['count'])[:15]:
        print(f"    {author}: {info['count']} topics")

    # Merge with video index if requested
    if args.merge:
        print("\nMerging with video search index...")
        merged = merge_with_video_index(index)
        MERGED_INDEX_FILE.write_text(
            json.dumps(merged, indent=2, ensure_ascii=False),
            encoding='utf-8'
        )
        size_kb = MERGED_INDEX_FILE.stat().st_size / 1024
        print(f"  Merged index: {merged['total_entries']} entries ({merged['video_entries']} video + {merged['forum_entries']} forum), {size_kb:.0f} KB")
        print(f"  Saved to: {MERGED_INDEX_FILE}")

    print(f"\nDone!")


if __name__ == '__main__':
    main()