#!/usr/bin/env python3
"""
Forum JSON → Markdown Converter
================================
Converts scraped forum topic JSON files into structured Markdown documents
suitable for Obsidian vault ingestion, search indexing (QMD), and website display.

Each topic becomes one Markdown file with YAML frontmatter and formatted posts.

Usage:
    python3 forum_to_markdown.py                    # Convert all topics
    python3 forum_to_markdown.py --forum 7          # Convert DCG topics only
    python3 forum_to_markdown.py --topic 11416      # Convert specific topic
    python3 forum_to_markdown.py --force             # Overwrite existing files

Output:
    transcripts/forum/
        DCG - Dichromated Gelatin - 2025 International Symposium on Display Holography.md
        ...
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
FORUM_DIR = SCRIPT_DIR / "forum"
TOPICS_DIR = FORUM_DIR / "topics"
OUTPUT_DIR = SCRIPT_DIR / "transcripts" / "forum"

# Forum definitions (must match scrape_forum.py)
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


def slugify(text: str) -> str:
    """Convert text to a filesystem-safe slug."""
    text = text.strip()
    # Replace special chars
    text = text.replace('#', '')
    text = re.sub(r'[/]', ' -', text)
    text = re.sub(r'[\\:*?"<>|]', '', text)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    # Truncate
    if len(text) > 120:
        text = text[:117].rsplit(' ', 1)[0]
    return text


def format_date(date_str: str) -> str:
    """Format a date string to YYYY-MM-DD."""
    if not date_str:
        return ""
    # Handle ISO format: 2025-03-23T16:28:05+00:00
    try:
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        return dt.strftime('%Y-%m-%d')
    except (ValueError, AttributeError):
        pass

    # Handle phpBB format: "Sun Mar 23, 2025 11:28 am"
    formats = [
        '%a %b %d, %Y %I:%M %p',
        '%a %b %d, %Y %I:%M%p',
        '%b %d, %Y',
        '%Y-%m-%d',
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.strftime('%Y-%m-%d')
        except ValueError:
            continue

    return date_str


def format_datetime(date_str: str) -> str:
    """Format a datetime string to a readable format."""
    if not date_str:
        return ""
    # Handle ISO format
    try:
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        return dt.strftime('%Y-%m-%d %I:%M %p')
    except (ValueError, AttributeError):
        pass

    # Handle phpBB format
    formats = [
        '%a %b %d, %Y %I:%M %p',
        '%a %b %d, %Y %I:%M%p',
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.strftime('%Y-%m-%d %I:%M %p')
        except ValueError:
            continue

    return date_str


def format_time_short(date_str: str) -> str:
    """Format a datetime to just time: '3:22pm'."""
    if not date_str:
        return ""
    try:
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        return dt.strftime('%-I:%M%p').lower()
    except (ValueError, AttributeError):
        pass

    formats = [
        '%a %b %d, %Y %I:%M %p',
        '%a %b %d, %Y %I:%M%p',
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.strftime('%-I:%M%p').lower()
        except ValueError:
            continue

    return date_str


def topic_to_markdown(topic_data: dict) -> str:
    """Convert a topic dict to a Markdown document."""
    posts = topic_data.get('posts', [])
    if not posts:
        return ""

    topic_id = topic_data['topic_id']
    title = topic_data.get('title', f'Topic {topic_id}')
    forum_id = topic_data.get('forum_id', 0)
    forum_info = FORUMS.get(forum_id, (f'Forum {forum_id}', f'f{forum_id}'))
    forum_name = forum_info[0]
    forum_short = forum_info[1]

    # Collect authors
    authors = []
    seen_authors = set()
    for post in posts:
        author = post.get('author', '')
        if author and author not in seen_authors:
            authors.append(author)
            seen_authors.add(author)

    # Date range
    dates = []
    for post in posts:
        dt = post.get('post_datetime', '')
        if dt:
            dates.append(dt)
        elif post.get('post_date', ''):
            dates.append(post['post_date'])

    date_start = format_date(min(dates)) if dates else ""
    date_end = format_date(max(dates)) if dates else ""

    # Build YAML frontmatter
    frontmatter = {
        'type': 'forum-thread',
        'forum': forum_short,
        'forum_full': forum_name,
        'forum_id': forum_id,
        'topic_id': topic_id,
        'topic_title': title,
        'authors': authors[:20],  # Limit to 20
        'post_count': len(posts),
        'date_start': date_start,
        'date_end': date_end,
        'url': topic_data.get('url', f'https://holographyforum.org/forum/viewtopic.php?t={topic_id}'),
        'created': datetime.now().strftime('%Y-%m-%d'),
    }

    if topic_data.get('is_sticky'):
        frontmatter['sticky'] = True
    if topic_data.get('is_locked'):
        frontmatter['locked'] = True
    if topic_data.get('views'):
        frontmatter['views'] = topic_data['views']

    # Format frontmatter
    fm_lines = ['---']
    for key, value in frontmatter.items():
        if isinstance(value, list):
            fm_lines.append(f'{key}:')
            for item in value:
                # Escape special YAML chars in strings
                item_str = str(item)
                if any(c in item_str for c in [':', '#', '{', '}', '[', ']', ',', '&', '*', '?', '|', '-', '<', '>', '=', '!', '%', '@', '`', '"', "'"]):
                    fm_lines.append(f'  - "{item_str}"')
                else:
                    fm_lines.append(f'  - {item_str}')
        elif isinstance(value, bool):
            fm_lines.append(f'{key}: {str(value).lower()}')
        elif isinstance(value, (int, float)):
            fm_lines.append(f'{key}: {value}')
        else:
            # Escape strings with special chars
            val_str = str(value)
            if any(c in val_str for c in [':', '#', '{', '}', '"', "'"]):
                fm_lines.append(f'{key}: "{val_str}"')
            else:
                fm_lines.append(f'{key}: {val_str}')
    fm_lines.append('---')
    fm_text = '\n'.join(fm_lines)

    # Build document body
    body_parts = []

    # Title and header
    starter = topic_data.get('starter', '') or (posts[0].get('author', '') if posts else '')
    body_parts.append(f'# {title}')
    body_parts.append('')
    body_parts.append(f'*Forum: {forum_name} | Started by {starter} on {date_start}*')
    if topic_data.get('views'):
        body_parts.append(f'*Views: {topic_data["views"]:,} | Posts: {len(posts)}*')
    body_parts.append('')

    # Source URL
    body_parts.append(f'🔗 [View on forum]({topic_data.get("url", "")})')
    body_parts.append('')
    body_parts.append('---')

    # Posts
    for i, post in enumerate(posts):
        author = post.get('author', 'Unknown')
        post_datetime = post.get('post_datetime', '')
        post_date = post.get('post_date', '')
        content = post.get('content_md', '').strip()
        signature = post.get('signature', '').strip()
        attachments = post.get('attachments', [])
        quotes = post.get('quotes', [])

        # Format date
        if post_datetime:
            date_display = format_datetime(post_datetime)
        elif post_date:
            date_display = post_date
        else:
            date_display = 'Unknown date'

        # Post header
        body_parts.append('')
        body_parts.append(f'## {author} — {date_display}')
        body_parts.append('')

        # Quote context (who they're replying to)
        if quotes:
            for q in quotes[:1]:  # Show first quote only
                body_parts.append(f'> **{q["author"]}:** {q["excerpt"][:100]}…')
                body_parts.append('')

        # Post content
        if content:
            body_parts.append(content)

        # Attachments — only show non-image files (images are already inline in content)
        if attachments:
            non_image_attachments = [a for a in attachments if a['type'] != 'image']
            if non_image_attachments:
                body_parts.append('')
                for att in non_image_attachments:
                    body_parts.append(f'📎 [{att.get("filename", "file")}]({att["url"]})')

        # Signature (only show for first occurrence per author in this topic)
        if signature and i < 3:  # Only show sig for first few posts
            body_parts.append('')
            body_parts.append(f'*— {signature}*')

        body_parts.append('')
        body_parts.append('---')

    # Combine
    doc = fm_text + '\n\n' + '\n'.join(body_parts)
    return doc


def get_output_filename(topic_data: dict) -> str:
    """Generate a filesystem-safe filename for a topic."""
    topic_id = topic_data['topic_id']
    title = topic_data.get('title', f'Topic {topic_id}')
    forum_id = topic_data.get('forum_id', 0)
    forum_info = FORUMS.get(forum_id, (f'Forum {forum_id}', f'f{forum_id}'))
    forum_short = forum_info[1]

    # Clean title for filename
    clean_title = slugify(title)
    filename = f"{forum_short} - {clean_title}.md"
    return filename


def convert_topic(topic_file: Path, force: bool = False) -> str | None:
    """Convert a single topic JSON file to Markdown."""
    try:
        topic_data = json.loads(topic_file.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, IOError) as e:
        print(f"  [Error] Reading {topic_file.name}: {e}")
        return None

    if not topic_data.get('posts'):
        print(f"  [Skip] No posts in {topic_file.name}")
        return None

    # Generate output filename
    filename = get_output_filename(topic_data)
    output_path = OUTPUT_DIR / filename

    # Check if already converted
    if output_path.exists() and not force:
        # Compare modification times
        if output_path.stat().st_mtime > topic_file.stat().st_mtime:
            print(f"  [Skip] Already up to date: {filename}")
            return str(output_path)

    # Convert
    markdown = topic_to_markdown(topic_data)
    if not markdown:
        return None

    # Write
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding='utf-8')
    print(f"  [OK] {filename} ({topic_data.get('post_count', 0)} posts)")

    return str(output_path)


def main():
    parser = argparse.ArgumentParser(
        description="Convert scraped forum JSON to Markdown",
    )
    parser.add_argument('--forum', type=str, default=None,
                        help='Convert only topics from this forum ID (comma-separated)')
    parser.add_argument('--topic', type=int, default=None,
                        help='Convert a specific topic by ID')
    parser.add_argument('--force', action='store_true',
                        help='Overwrite existing Markdown files')

    args = parser.parse_args()

    # Determine which topics to convert
    if args.topic:
        topic_file = TOPICS_DIR / f"topic_{args.topic}.json"
        if not topic_file.exists():
            print(f"Topic file not found: {topic_file}")
            sys.exit(1)
        convert_topic(topic_file, force=args.force)
        return

    # Find all topic files
    topic_files = sorted(TOPICS_DIR.glob("topic_*.json"))
    if not topic_files:
        print("No topic files found. Run scrape_forum.py first.")
        sys.exit(1)

    # Filter by forum
    if args.forum:
        forum_ids = set(int(x.strip()) for x in args.forum.split(','))
        filtered = []
        for tf in topic_files:
            try:
                data = json.loads(tf.read_text(encoding='utf-8'))
                if data.get('forum_id') in forum_ids:
                    filtered.append(tf)
            except:
                pass
        topic_files = filtered

    print(f"Converting {len(topic_files)} topics to Markdown...")
    print(f"Output directory: {OUTPUT_DIR}")
    print()

    converted = 0
    skipped = 0
    errors = 0

    for tf in topic_files:
        result = convert_topic(tf, force=args.force)
        if result:
            converted += 1
        elif tf.stat().st_size > 0:
            skipped += 1
        else:
            errors += 1

    print(f"\n{'='*60}")
    print(f"Conversion complete!")
    print(f"  Converted: {converted}")
    print(f"  Skipped:   {skipped}")
    print(f"  Errors:    {errors}")
    print(f"  Output:    {OUTPUT_DIR}")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()