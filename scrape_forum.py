#!/usr/bin/env python3
"""
Holography Forum (holographyforum.org) phpBB Scraper
=====================================================
Scrapes all topics and posts from the Holography Forum, producing
structured JSON output per topic with full post content, author info,
dates, quote chains, images, and attachments.

Usage:
    python3 scrape_forum.py                    # Scrape all high-value forums
    python3 scrape_forum.py --forum 7          # Scrape DCG forum only
    python3 scrape_forum.py --forum 7,5,30     # Scrape multiple forums
    python3 scrape_forum.py --all-forums        # Scrape every forum
    python3 scrape_forum.py --dry-run          # List what would be scraped
    python3 scrape_forum.py --limit 5          # Limit topics per forum (testing)
    python3 scrape_forum.py --resume            # Resume from last checkpoint

Output structure:
    forum/
        raw/                    # Raw HTML for re-parsing
        topics/                  # Parsed topic JSON
        forum_progress.json      # Resume state
        forum_stats.json         # Scraping statistics
"""

import argparse
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

# ── Configuration ──────────────────────────────────────────────────────────

BASE_URL = "https://holographyforum.org/forum/"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
REQUEST_DELAY = 1.5  # seconds between requests
MAX_RETRIES = 3
BACKOFF_BASE = 5  # seconds, exponential backoff

SCRIPT_DIR = Path(__file__).parent
FORUM_DIR = SCRIPT_DIR / "forum"
RAW_DIR = FORUM_DIR / "raw"
TOPICS_DIR = FORUM_DIR / "topics"
PROGRESS_FILE = FORUM_DIR / "forum_progress.json"
STATS_FILE = FORUM_DIR / "forum_stats.json"

# Forum definitions: id → (name, short_name, priority)
FORUMS = {
    # High-value (priority 1)
    53: ("Events, announcements, and news", "Events", 1),
    30: ("General Holography (old)", "General-Old", 1),
    7:  ("DCG - Dichromated Gelatin", "DCG", 1),
    5:  ("Techniques", "Techniques", 1),
    45: ("Beginning Holography", "Beginners", 1),
    32: ("Gallery", "Gallery", 1),
    9:  ("AgX - Silver Halide Emulsions", "AgX", 1),
    23: ("Optics", "Optics", 1),
    6:  ("Equipment", "Equipment", 1),
    53: ("Events, announcements, and news", "Events", 1),
    3:  ("ISDH / Symposia", "ISDH", 1),
    4:  ("Announcements", "Announcements", 1),
    8:  ("General Holography (new)", "General-New", 1),
    # Lower priority (priority 2)
    41: ("Network54 Archived Posts", "Network54", 2),
    33: ("Links", "Links", 2),
    39: ("For Sale or Trade", "ForSale", 2),
    12: ("Off Topic", "OffTopic", 2),
    34: ("Off Topic (old)", "OffTopic-Old", 2),
    52: ("Holography Jobs", "Jobs", 2),
    31: ("Administration", "Admin", 2),
    54: ("The Dump", "Dump", 2),
}

# Parent forum sections (for breadcrumb context)
PARENT_FORUMS = {
    15: "Forum",
    53: "Events, announcements, and news",
}

TOPICS_PER_PAGE = 25  # phpBB default
POSTS_PER_PAGE = 10    # phpBB default


# ── HTTP Session ───────────────────────────────────────────────────────────

class ForumSession:
    """Manages HTTP session with rate limiting and retries."""

    def __init__(self, delay=REQUEST_DELAY, max_retries=MAX_RETRIES):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        })
        self.delay = delay
        self.max_retries = max_retries
        self.request_count = 0
        self.error_count = 0
        self.last_request_time = 0

    def fetch(self, url: str) -> str | None:
        """Fetch a URL with rate limiting and retries. Returns HTML or None."""
        # Rate limiting
        elapsed = time.time() - self.last_request_time
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)

        for attempt in range(self.max_retries):
            try:
                resp = self.session.get(url, timeout=30)
                self.last_request_time = time.time()
                self.request_count += 1

                if resp.status_code == 200:
                    return resp.text
                elif resp.status_code == 404:
                    print(f"  [404] Not found: {url}")
                    return None
                elif resp.status_code == 429:
                    wait = BACKOFF_BASE * (2 ** attempt)
                    print(f"  [429] Rate limited, waiting {wait}s...")
                    time.sleep(wait)
                    continue
                elif resp.status_code == 403:
                    print(f"  [403] Forbidden: {url}")
                    return None
                else:
                    print(f"  [{resp.status_code}] Error fetching: {url}")
                    if attempt < self.max_retries - 1:
                        time.sleep(BACKOFF_BASE * (2 ** attempt))
                        continue
                    return None
            except requests.RequestException as e:
                self.error_count += 1
                if attempt < self.max_retries - 1:
                    wait = BACKOFF_BASE * (2 ** attempt)
                    print(f"  [Error] {e.__class__.__name__}: {e} — retry in {wait}s")
                    time.sleep(wait)
                else:
                    print(f"  [Error] {e.__class__.__name__}: {e} — giving up")
                    return None

        return None


# ── URL Helpers ────────────────────────────────────────────────────────────

def clean_url(url: str) -> str:
    """Remove session ID (sid) from URLs for clean storage."""
    # Remove &sid=... or ?sid=...
    url = re.sub(r'[?&]sid=[a-f0-9]+', '', url)
    # Fix double ? or & issues
    url = url.replace('?&', '?').replace('&&', '&')
    # Remove trailing & or ?
    url = url.rstrip('&?')
    return url


def make_forum_url(forum_id: int, start: int = 0) -> str:
    """Build a forum listing URL."""
    url = f"{BASE_URL}viewforum.php?f={forum_id}"
    if start > 0:
        url += f"&start={start}"
    return url


def make_topic_url(topic_id: int, start: int = 0) -> str:
    """Build a topic view URL."""
    url = f"{BASE_URL}viewtopic.php?t={topic_id}"
    if start > 0:
        url += f"&start={start}"
    return url


def make_post_url(post_id: int) -> str:
    """Build a direct post URL."""
    return f"{BASE_URL}viewtopic.php?p={post_id}#p{post_id}"


# ── HTML Parsing ───────────────────────────────────────────────────────────

def html_to_markdown(element: Tag) -> str:
    """Convert a BeautifulSoup element to Markdown text."""
    if element is None:
        return ""

    parts = []
    _convert_element(element, parts)
    text = "".join(parts)

    # Clean up whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' +', ' ', text)
    text = text.strip()

    return text


def _convert_element(element, parts: list):
    """Recursively convert HTML element to markdown parts."""
    if isinstance(element, NavigableString):
        text = str(element)
        # Don't collapse whitespace inside pre/code blocks
        parts.append(text)
        return

    if not isinstance(element, Tag):
        return

    tag = element.name

    # Skip hidden elements
    if element.get('style', '').replace(' ', '').lower().startswith('display:none'):
        return

    # Skip script, style, nav elements
    if tag in ('script', 'style', 'nav', 'button', 'noscript'):
        return

    # Handle specific tags
    if tag == 'br':
        parts.append('\n')
        return

    if tag == 'p':
        parts.append('\n')
        for child in element.children:
            _convert_element(child, parts)
        parts.append('\n')
        return

    if tag == 'a':
        href = element.get('href', '')
        link_text = element.get_text(strip=True)
        if href:
            # Resolve relative URLs
            if href.startswith('./'):
                href = BASE_URL + href[2:]
            elif href.startswith('/'):
                href = "https://holographyforum.org" + href
            # Clean session IDs
            href = clean_url(href)
            # Skip internal phpBB links (login, post, search)
            if any(x in href for x in ['posting.php', 'ucp.php', 'search.php', 'memberlist.php?mode=email']):
                parts.append(link_text)
            else:
                parts.append(f'[{link_text}]({href})')
        else:
            parts.append(link_text)
        return

    if tag == 'img':
        src = element.get('src', '')
        alt = element.get('alt', '')
        if src:
            if src.startswith('./'):
                src = BASE_URL + src[2:]
            elif src.startswith('/'):
                src = "https://holographyforum.org" + src
            src = clean_url(src)
            # Skip BBCode-style broken image references like [attachment=0]...[/attachment]
            if '[attachment=' in alt or '%5Battachment=' in alt or '%5Battachment%3D' in src:
                # This is a phpBB attachment placeholder — the actual attachment
                # is in the attachbox dl, not this broken img tag
                return
            # Skip smilies and tiny icons
            w = element.get('width', '')
            h = element.get('height', '')
            if w and int(w) < 30:
                return
            if h and int(h) < 30:
                return
            # Skip phpBB style images
            if 'smilies' in src or 'icon_' in src:
                return
            # Skip images that are inside attachment dls (they'll be handled there)
            parent_dl = element.find_parent('dl', class_='file')
            if parent_dl:
                # This image is inside a file download dl — handle it there
                return
            parts.append(f'![{alt}]({src})')
        return

    if tag in ('strong', 'b'):
        inner = element.get_text(strip=True)
        if inner:
            parts.append(f'**{inner}**')
        return

    if tag in ('em', 'i'):
        inner = element.get_text(strip=True)
        if inner:
            parts.append(f'*{inner}*')
        return

    if tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
        level = int(tag[1])
        inner = element.get_text(strip=True)
        if inner:
            parts.append(f'\n{"#" * level} {inner}\n')
        return

    if tag in ('ul', 'ol'):
        parts.append('\n')
        for li in element.find_all('li', recursive=False):
            parts.append('- ')
            for child in li.children:
                _convert_element(child, parts)
            parts.append('\n')
        return

    if tag == 'li':
        parts.append('- ')
        for child in element.children:
            _convert_element(child, parts)
        parts.append('\n')
        return

    if tag == 'blockquote':
        # Check if it's a phpBB quote block
        cite = element.find('cite')
        if cite:
            author = cite.get_text(strip=True)
            # Remove the author prefix like "Username wrote:"
            author = re.sub(r'\s*wrote:\s*$', '', author)
            cite.decompose()
            inner_text = element.get_text(strip=True)
            parts.append(f'\n> **{author}:** {inner_text}\n')
        else:
            inner_text = element.get_text(strip=True)
            parts.append(f'\n> {inner_text}\n')
        return

    if tag == 'code':
        inner = element.get_text()
        # Check for codebox wrapper
        dt = element.find_parent('dl', class_='codebox')
        if dt:
            # Get the code language from dt
            dt_tag = dt.find('dt')
            lang = ''
            if dt_tag:
                lang_text = dt_tag.get_text(strip=True)
                # Extract language from "Code: Select all" or "Language: Select all"
                lang_match = re.match(r'(\w+)', lang_text)
                if lang_match:
                    lang = lang_match.group(1).lower()
                    if lang == 'code':
                        lang = ''
            parts.append(f'\n```{lang}\n{inner}\n```\n')
        else:
            parts.append(f'`{inner}`')
        return

    if tag == 'dl':
        # Handle attachment boxes — these appear AFTER the content div
        # They often duplicate images already shown inline, so we skip image attachments here
        if 'attachbox' in element.get('class', []):
            # Only process non-image file downloads
            for dd in element.select('dd'):
                inner_dl = dd.select_one('dl.file')
                if inner_dl:
                    img = inner_dl.select_one('img.postimage')
                    if img:
                        # Image attachment — already rendered inline, skip to avoid duplicates
                        continue
                    else:
                        # File download link
                        a = inner_dl.select_one('dt a')
                        if a:
                            href = a.get('href', '')
                            text = a.get_text(strip=True)
                            if href.startswith('./'):
                                href = BASE_URL + href[2:]
                            href = clean_url(href)
                            size_dd = inner_dl.select_one('dd')
                            size_info = size_dd.get_text(strip=True) if size_dd else ''
                            parts.append(f'\n📎 [{text}]({href}) {size_info}')
            return

        # Handle codebox
        if 'codebox' in element.get('class', []):
            code_tag = element.find('code')
            if code_tag:
                dt_tag = element.find('dt')
                lang = ''
                if dt_tag:
                    lang_text = dt_tag.get_text(strip=True)
                    lang_match = re.match(r'(\w+)', lang_text)
                    if lang_match:
                        lang = lang_match.group(1).lower()
                        if lang == 'code':
                            lang = ''
                inner = code_tag.get_text()
                parts.append(f'\n```{lang}\n{inner}\n```\n')
            return

        # Handle postprofile (author info) — skip in content parsing
        if 'postprofile' in element.get('class', []):
            return

        # Handle inline-attachment dl.file
        if 'inline-attachment' in ' '.join(element.get('class', [])) or element.select_one('dl.file'):
            # Process inline attachments
            for child in element.children:
                _convert_element(child, parts)
            return

        # Generic dl/dd/dt
        for child in element.children:
            _convert_element(child, parts)
        return

    if tag == 'div':
        classes = element.get('class', [])
        # Skip signature blocks (handled separately)
        if 'signature' in classes:
            return
        # Skip post buttons
        if 'post-buttons' in classes:
            return
        # Skip responsive-show divs (duplicates)
        if 'responsive-show' in classes:
            return
        # Handle inline-attachment — render image and skip file info text
        if 'inline-attachment' in classes:
            for child in element.children:
                if isinstance(child, Tag):
                    if child.name == 'dl' and 'file' in child.get('class', []):
                        # Extract image from dt.attach-image
                        img = child.select_one('dt.attach-image img.postimage')
                        if img:
                            src = img.get('src', '')
                            alt = img.get('alt', '')
                            if src:
                                if src.startswith('./'):
                                    src = BASE_URL + src[2:]
                                src = clean_url(src)
                                parts.append(f'\n![{alt}]({src})\n')
                        else:
                            # File download link
                            a = child.select_one('dt a')
                            if a:
                                href = a.get('href', '')
                                text = a.get_text(strip=True)
                                if href.startswith('./'):
                                    href = BASE_URL + href[2:]
                                href = clean_url(href)
                                parts.append(f'\n📎 [{text}]({href})\n')
                        # Skip the dd (file info text)
                    else:
                        _convert_element(child, parts)
                else:
                    parts.append(str(child))
            return
        # Handle content div — this is the main post content
        if 'content' in classes:
            for child in element.children:
                _convert_element(child, parts)
            # Clean up broken phpBB [attachment=0]...[/attachment] image references
            # These appear as ![Image](%5Battachment=0%5D...%5B/attachment%5D)
            result = ''.join(parts)
            # Remove broken attachment image references
            result = re.sub(r'!?\[Image\]\([^)]*%5Battachment[^)]*\)', '', result)
            result = re.sub(r'!?\[[^\]]*\]\([^)]*%5Battachment[^)]*\)', '', result)
            parts.clear()
            parts.append(result)
            return

    # Default: recurse into children
    for child in element.children:
        _convert_element(child, parts)


def parse_forum_page(html: str, forum_id: int) -> list[dict]:
    """Parse a forum listing page and extract topic info."""
    soup = BeautifulSoup(html, 'html.parser')
    topics = []

    for row in soup.select('ul.topiclist.topics li'):
        # Skip header row
        if 'header' in row.get('class', []):
            continue

        # Skip announcements/sticky if they're in a separate list
        # (we want all topics regardless)

        # Extract topic title and link
        title_link = row.select_one('a.topictitle')
        if not title_link:
            continue

        title = title_link.get_text(strip=True)
        href = title_link.get('href', '')

        # Extract topic ID from URL
        topic_id = None
        m = re.search(r't=(\d+)', href)
        if m:
            topic_id = int(m.group(1))

        if not topic_id:
            continue

        # Extract reply count (phpBB formats as "9Replies" with no space)
        replies = 0
        replies_dd = row.select_one('dd.posts')
        if replies_dd:
            try:
                m = re.match(r'(\d+)', replies_dd.get_text(strip=True))
                if m:
                    replies = int(m.group(1))
            except (ValueError, AttributeError):
                pass

        # Extract view count (phpBB formats as "7516Views" with no space)
        views = 0
        views_dd = row.select_one('dd.views')
        if views_dd:
            try:
                m = re.match(r'(\d+)', views_dd.get_text(strip=True))
                if m:
                    views = int(m.group(1))
            except (ValueError, AttributeError):
                pass

        # Extract topic starter
        starter = ""
        starter_link = row.select_one('.topic-poster a.username')
        if starter_link:
            starter = starter_link.get_text(strip=True)

        # Extract last post date
        last_post_time = ""
        time_tag = row.select_one('dd.lastpost time')
        if time_tag:
            last_post_time = time_tag.get('datetime', time_tag.get_text(strip=True))

        # Check for attachment icon
        has_attachments = bool(row.select_one('.icon.fa-paperclip'))

        # Check for pagination (multi-page topic)
        pages = 1
        pagination = row.select_one('.pagination')
        if pagination:
            page_links = pagination.select('a.button')
            if page_links:
                try:
                    # Last page number
                    last_page = page_links[-1].get_text(strip=True)
                    pages = int(last_page)
                except (ValueError, IndexError):
                    pass

        # Check if topic is locked, sticky, or announcement
        row_classes = ' '.join(row.get('class', []))
        is_sticky = 'sticky' in row_classes.lower() or row.select_one('.icon.fa-sticky')
        is_locked = 'locked' in row_classes.lower() or row.select_one('.icon.fa-lock')
        is_announcement = 'announcement' in row_classes.lower() or row.select_one('.icon.fa-announce')

        topics.append({
            'topic_id': topic_id,
            'title': title,
            'forum_id': forum_id,
            'replies': replies,
            'views': views,
            'starter': starter,
            'last_post_time': last_post_time,
            'has_attachments': has_attachments,
            'pages': pages,
            'is_sticky': is_sticky,
            'is_locked': is_locked,
            'is_announcement': is_announcement,
        })

    return topics


def parse_topic_page(html: str, topic_id: int, forum_id: int, page_num: int) -> list[dict]:
    """Parse a topic view page and extract posts."""
    soup = BeautifulSoup(html, 'html.parser')
    posts = []

    # Extract topic title from h2
    topic_title = ""
    title_tag = soup.select_one('h2.topic-title a')
    if title_tag:
        topic_title = title_tag.get_text(strip=True)
    elif soup.select_one('h2.topic-title'):
        topic_title = soup.select_one('h2.topic-title').get_text(strip=True)

    # Extract forum name from breadcrumbs
    forum_name = ""
    forum_id_from_breadcrumb = None
    breadcrumbs = soup.select('.nav-breadcrumbs .crumb')
    for crumb in breadcrumbs:
        crumb_text = crumb.get_text(strip=True)
        if crumb_text not in ('Board index', 'Forum'):
            forum_name = crumb_text
            # Extract forum_id from data attribute
            fid = crumb.get('data-forum-id', '')
            if fid:
                try:
                    forum_id_from_breadcrumb = int(fid)
                except ValueError:
                    pass
            # Also try to extract from href
            if not forum_id_from_breadcrumb:
                a = crumb.select_one('a')
                if a:
                    href = a.get('href', '')
                    m = re.search(r'f=(\d+)', href)
                    if m:
                        forum_id_from_breadcrumb = int(m.group(1))

    # Use breadcrumb forum_id if available, otherwise use the passed-in forum_id
    effective_forum_id = forum_id_from_breadcrumb if forum_id_from_breadcrumb else forum_id

    # Find all post containers
    for post_div in soup.select('div.post'):
        try:
            post = _parse_single_post(post_div, topic_id, topic_title, effective_forum_id, forum_name)
            if post:
                posts.append(post)
        except Exception as e:
            print(f"    [Warning] Error parsing post: {e}")
            continue

    return posts, effective_forum_id, forum_name


def _parse_single_post(post_div: Tag, topic_id: int, topic_title: str,
                       forum_id: int, forum_name: str) -> dict | None:
    """Parse a single post div into a structured dict."""
    # Post ID from div id="pXXXXX"
    post_id_str = post_div.get('id', '')
    post_id = None
    m = re.match(r'p(\d+)', post_id_str)
    if m:
        post_id = int(m.group(1))

    # Author from postprofile
    author = ""
    author_id = None
    profile_dl = post_div.select_one('dl.postprofile')
    if profile_dl:
        author_link = profile_dl.select_one('dt a.username')
        if author_link:
            author = author_link.get_text(strip=True)
            href = author_link.get('href', '')
            uid_match = re.search(r'u=(\d+)', href)
            if uid_match:
                author_id = int(uid_match.group(1))
        else:
            # Sometimes username is just text in dt
            dt = profile_dl.select_one('dt')
            if dt:
                author = dt.get_text(strip=True)

    # Post date/time from <time> element
    post_date = ""
    post_datetime = ""
    time_tag = post_div.select_one('p.author time')
    if time_tag:
        post_datetime = time_tag.get('datetime', '')
        post_date = time_tag.get_text(strip=True)

    # Post subject/title
    post_subject = ""
    h3 = post_div.select_one('h3 a')
    if h3:
        post_subject = h3.get_text(strip=True)
        # Remove "Re: " prefix for replies
        if post_subject.startswith('Re: '):
            post_subject = post_subject[4:]

    # Post content
    content_div = post_div.select_one('div.content')
    content_md = ""
    if content_div:
        content_md = html_to_markdown(content_div)

    # Signature (separate from content)
    signature = ""
    sig_div = post_div.select_one('div.signature')
    if sig_div:
        signature = html_to_markdown(sig_div).strip()

    # Inline attachments (within content)
    inline_attachments = []
    for attach_dl in post_div.select('dl.file'):
        img = attach_dl.select_one('img.postimage')
        if img:
            src = img.get('src', '')
            alt = img.get('alt', '')
            if src.startswith('./'):
                src = BASE_URL + src[2:]
            src = clean_url(src)
            # Get file size info
            dd = attach_dl.select_one('dd')
            size_info = dd.get_text(strip=True) if dd else ''
            inline_attachments.append({
                'type': 'image',
                'url': src,
                'filename': alt,
                'info': size_info,
            })
        else:
            # Non-image attachment (file download)
            a = attach_dl.select_one('dt a')
            if a:
                href = a.get('href', '')
                text = a.get_text(strip=True)
                if href.startswith('./'):
                    href = BASE_URL + href[2:]
                href = clean_url(href)
                dd = attach_dl.select_one('dd')
                size_info = dd.get_text(strip=True) if dd else ''
                inline_attachments.append({
                    'type': 'file',
                    'url': href,
                    'filename': text,
                    'info': size_info,
                })

    # Attachment box (separate from content)
    # NOTE: We skip the attachbox because inline-attachment divs inside
    # the content already render the images. The attachbox just duplicates them.
    # We only extract non-image file attachments from it.
    attachbox = post_div.select_one('dl.attachbox')
    if attachbox:
        for file_dl in attachbox.select('dd dl.file'):
            img = file_dl.select_one('img.postimage')
            if not img:
                # Non-image file download
                a = file_dl.select_one('dt a')
                if a:
                    href = a.get('href', '')
                    text = a.get_text(strip=True)
                    if href.startswith('./'):
                        href = BASE_URL + href[2:]
                    href = clean_url(href)
                    dd = file_dl.select_one('dd')
                    size_info = dd.get_text(strip=True) if dd else ''
                    inline_attachments.append({
                        'type': 'file',
                        'url': href,
                        'filename': text,
                        'info': size_info,
                    })

    # Quote chains: find all blockquotes and extract who's quoting whom
    quotes = []
    for bq in post_div.select('blockquote'):
        cite = bq.find('cite')
        if cite:
            quoted_author = cite.get_text(strip=True)
            quoted_author = re.sub(r'\s*wrote:\s*$', '', quoted_author)
            # Remove cite from blockquote text
            cite.decompose()
            quoted_text = bq.get_text(strip=True)[:200]  # Truncate for metadata
            quotes.append({
                'author': quoted_author,
                'excerpt': quoted_text,
            })

    # Check if this is the first post (has class "first" or h3 has class "first")
    is_first_post = bool(post_div.select_one('h3.first'))

    return {
        'post_id': post_id,
        'topic_id': topic_id,
        'topic_title': topic_title,
        'forum_id': forum_id,
        'forum_name': forum_name,
        'author': author,
        'author_id': author_id,
        'post_date': post_date,
        'post_datetime': post_datetime,
        'post_subject': post_subject,
        'content_md': content_md,
        'signature': signature,
        'attachments': inline_attachments,
        'quotes': quotes,
        'is_first_post': is_first_post,
        'url': make_post_url(post_id) if post_id else '',
    }


def get_total_pages_forum(html: str) -> int:
    """Extract total pages from forum listing pagination."""
    soup = BeautifulSoup(html, 'html.parser')

    # Check for pagination div
    pagination = soup.select_one('.action-bar .pagination')
    if not pagination:
        return 1

    # Find the last page number
    page_links = pagination.select('a.button')
    if not page_links:
        return 1

    max_page = 1
    for link in page_links:
        text = link.get_text(strip=True)
        try:
            page_num = int(text)
            max_page = max(max_page, page_num)
        except ValueError:
            pass

    # Also check the "X topics" text
    topic_count_text = pagination.get_text()
    m = re.search(r'(\d+)\s+topics', topic_count_text)
    if m:
        total_topics = int(m.group(1))
        total_pages = (total_topics + TOPICS_PER_PAGE - 1) // TOPICS_PER_PAGE
        max_page = max(max_page, total_pages)

    return max_page


def get_total_pages_topic(html: str) -> int:
    """Extract total pages from topic pagination."""
    soup = BeautifulSoup(html, 'html.parser')

    # Check pagination
    pagination = soup.select_one('.action-bar .pagination')
    if not pagination:
        # Check title for post count
        return 1

    # Look for "X posts • Page Y of Z"
    text = pagination.get_text()
    m = re.search(r'Page\s+\d+\s+of\s+(\d+)', text)
    if m:
        return int(m.group(1))

    # Look for page links
    page_links = pagination.select('a.button')
    max_page = 1
    for link in page_links:
        try:
            max_page = max(max_page, int(link.get_text(strip=True)))
        except ValueError:
            pass

    return max_page


# ── Progress Tracking ─────────────────────────────────────────────────────

def load_progress() -> dict:
    """Load progress from file."""
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text())
        except (json.JSONDecodeError, IOError):
            pass
    return {
        'forums': {},  # forum_id → {last_topic_id, topics_scraped, posts_scraped}
        'started': datetime.now(timezone.utc).isoformat(),
        'last_run': None,
    }


def save_progress(progress: dict):
    """Save progress to file."""
    progress['last_run'] = datetime.now(timezone.utc).isoformat()
    FORUM_DIR.mkdir(parents=True, exist_ok=True)
    PROGRESS_FILE.write_text(json.dumps(progress, indent=2))


def load_stats() -> dict:
    """Load stats from file."""
    if STATS_FILE.exists():
        try:
            return json.loads(STATS_FILE.read_text())
        except (json.JSONDecodeError, IOError):
            pass
    return {
        'total_topics': 0,
        'total_posts': 0,
        'total_requests': 0,
        'total_errors': 0,
        'forums': {},
        'started': datetime.now(timezone.utc).isoformat(),
        'last_run': None,
    }


def save_stats(stats: dict):
    """Save stats to file."""
    stats['last_run'] = datetime.now(timezone.utc).isoformat()
    FORUM_DIR.mkdir(parents=True, exist_ok=True)
    STATS_FILE.write_text(json.dumps(stats, indent=2))


# ── Main Scraper ───────────────────────────────────────────────────────────

def scrape_forum(session: ForumSession, forum_id: int, forum_name: str,
                 limit: int = 0, dry_run: bool = False) -> list[dict]:
    """Scrape all topics from a forum. Returns list of topic metadata."""
    print(f"\n{'='*60}")
    print(f"Scraping forum: {forum_name} (f={forum_id})")
    print(f"{'='*60}")

    topics_found = []

    # Fetch first page to get pagination
    url = make_forum_url(forum_id, 0)
    html = session.fetch(url)
    if not html:
        print(f"  [Error] Could not fetch forum {forum_id}")
        return topics_found

    # Save raw HTML
    if not dry_run:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        (RAW_DIR / f"forum_{forum_id}_page_0.html").write_text(html, encoding='utf-8')

    total_pages = get_total_pages_forum(html)
    print(f"  Total pages: {total_pages}")

    # Parse first page for topics
    page_topics = parse_forum_page(html, forum_id)
    topics_found.extend(page_topics)

    # Fetch remaining pages
    for page in range(1, total_pages):
        start = page * TOPICS_PER_PAGE
        url = make_forum_url(forum_id, start)

        if not dry_run:
            time.sleep(0.5)  # Brief pause between listing pages
            html = session.fetch(url)
            if html:
                (RAW_DIR / f"forum_{forum_id}_page_{page}.html").write_text(html, encoding='utf-8')
                page_topics = parse_forum_page(html, forum_id)
                topics_found.extend(page_topics)
            else:
                print(f"  [Warning] Could not fetch page {page+1} of forum {forum_id}")
        else:
            # In dry run, we just list what we found on the first page
            pass

    print(f"  Found {len(topics_found)} topics")

    # Apply limit
    if limit > 0 and len(topics_found) > limit:
        print(f"  Limiting to {limit} topics (of {len(topics_found)})")
        topics_found = topics_found[:limit]

    return topics_found


def scrape_topic(session: ForumSession, topic_meta: dict, dry_run: bool = False) -> dict | None:
    """Scrape all posts from a topic. Returns topic dict with all posts."""
    topic_id = topic_meta['topic_id']
    title = topic_meta['title']
    forum_id = topic_meta['forum_id']

    print(f"\n  Topic: {title} (t={topic_id})")

    if dry_run:
        print(f"    [Dry run] Would scrape {topic_meta.get('pages', 1)} pages, "
              f"{topic_meta.get('replies', 0) + 1} posts")
        return None

    all_posts = []
    topic_title = ""
    forum_name = ""

    # Fetch first page
    url = make_topic_url(topic_id, 0)
    html = session.fetch(url)
    if not html:
        print(f"    [Error] Could not fetch topic {topic_id}")
        return None

    # Save raw HTML
    (RAW_DIR / f"topic_{topic_id}_page_0.html").write_text(html, encoding='utf-8')

    # Get total pages
    total_pages = get_total_pages_topic(html)
    # Also estimate from replies
    estimated_pages = max(1, (topic_meta.get('replies', 0) + 1 + POSTS_PER_PAGE - 1) // POSTS_PER_PAGE)
    total_pages = max(total_pages, estimated_pages)

    # Parse first page
    posts, actual_forum_id, actual_forum_name = parse_topic_page(html, topic_id, forum_id, 0)
    all_posts.extend(posts)

    if posts:
        topic_title = posts[0].get('topic_title', title)
        forum_name = actual_forum_name if actual_forum_name else forum_name
        # Update forum_id if we got a better one from breadcrumbs
        if actual_forum_id and actual_forum_id != forum_id:
            forum_id = actual_forum_id

    # Fetch remaining pages
    for page in range(1, total_pages):
        start = page * POSTS_PER_PAGE
        url = make_topic_url(topic_id, start)

        html = session.fetch(url)
        if not html:
            print(f"    [Warning] Could not fetch page {page+1} of topic {topic_id}")
            continue

        (RAW_DIR / f"topic_{topic_id}_page_{page}.html").write_text(html, encoding='utf-8')

        posts, _, _ = parse_topic_page(html, topic_id, forum_id, page)
        if not posts:
            # No more posts found — we've reached the end
            break
        all_posts.extend(posts)

    # Build topic data
    topic_data = {
        'topic_id': topic_id,
        'title': topic_title or title,
        'forum_id': forum_id,
        'forum_name': forum_name,
        'url': clean_url(make_topic_url(topic_id)),
        'replies': topic_meta.get('replies', 0),
        'views': topic_meta.get('views', 0),
        'starter': topic_meta.get('starter', ''),
        'is_sticky': topic_meta.get('is_sticky', False),
        'is_locked': topic_meta.get('is_locked', False),
        'is_announcement': topic_meta.get('is_announcement', False),
        'has_attachments': topic_meta.get('has_attachments', False),
        'scraped_at': datetime.now(timezone.utc).isoformat(),
        'post_count': len(all_posts),
        'posts': all_posts,
    }

    # Save topic JSON
    TOPICS_DIR.mkdir(parents=True, exist_ok=True)
    topic_file = TOPICS_DIR / f"topic_{topic_id}.json"
    topic_file.write_text(json.dumps(topic_data, indent=2, ensure_ascii=False), encoding='utf-8')

    print(f"    Saved {len(all_posts)} posts to {topic_file.name}")

    return topic_data


def main():
    parser = argparse.ArgumentParser(
        description="Scrape the Holography Forum (holographyforum.org)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--forum', type=str, default=None,
                        help='Forum ID(s) to scrape, comma-separated (e.g., "7,5,30")')
    parser.add_argument('--all-forums', action='store_true',
                        help='Scrape all forums including low-priority ones')
    parser.add_argument('--dry-run', action='store_true',
                        help='List what would be scraped without fetching')
    parser.add_argument('--limit', type=int, default=0,
                        help='Limit number of topics per forum (for testing)')
    parser.add_argument('--resume', action='store_true',
                        help='Resume from last checkpoint')
    parser.add_argument('--delay', type=float, default=REQUEST_DELAY,
                        help=f'Delay between requests in seconds (default: {REQUEST_DELAY})')
    parser.add_argument('--topic', type=int, default=None,
                        help='Scrape a single topic by ID')

    args = parser.parse_args()

    # Determine which forums to scrape
    if args.forum:
        forum_ids = [int(x.strip()) for x in args.forum.split(',')]
    elif args.all_forums:
        forum_ids = sorted(FORUMS.keys())
    else:
        # Default: high-value forums only
        forum_ids = [fid for fid, (_, _, pri) in FORUMS.items() if pri == 1]

    # Single topic mode
    if args.topic:
        session = ForumSession(delay=args.delay)
        topic_meta = {
            'topic_id': args.topic,
            'title': f'Topic {args.topic}',
            'forum_id': 0,
            'replies': 0,
            'views': 0,
            'starter': '',
            'pages': 1,
        }
        result = scrape_topic(session, topic_meta, dry_run=args.dry_run)
        if result:
            print(f"\nDone! Scraped {result['post_count']} posts from topic {args.topic}")
        return

    # Load progress and stats
    progress = load_progress() if args.resume else load_progress()
    stats = load_stats()

    session = ForumSession(delay=args.delay)

    # ── Dry Run Mode ──
    if args.dry_run:
        print("=" * 60)
        print("DRY RUN — Listing topics that would be scraped")
        print("=" * 60)

        total_topics = 0
        for fid in forum_ids:
            if fid not in FORUMS:
                print(f"\n  [Warning] Forum {fid} not in known forums list")
                continue
            fname, fshort, fpri = FORUMS[fid]
            topics = scrape_forum(session, fid, fname, limit=args.limit, dry_run=True)
            total_topics += len(topics)
            for t in topics:
                print(f"    t={t['topic_id']:5d}  {t['replies']:4d} replies  "
                      f"{t['views']:7d} views  {t['title'][:60]}")

        print(f"\n{'='*60}")
        print(f"Total topics to scrape: {total_topics}")
        print(f"Forums: {forum_ids}")
        return

    # ── Full Scrape Mode ──
    print("=" * 60)
    print("Holography Forum Scraper")
    print("=" * 60)
    print(f"Forums: {forum_ids}")
    print(f"Delay: {args.delay}s between requests")
    print(f"Resume: {args.resume}")
    print(f"Limit: {args.limit or 'none'}")

    total_topics_scraped = 0
    total_posts_scraped = 0

    for fid in forum_ids:
        if fid not in FORUMS:
            print(f"\n  [Warning] Forum {fid} not in known forums list, skipping")
            continue

        fname, fshort, fpri = FORUMS[fid]

        # Check progress for resume
        forum_progress = progress['forums'].get(str(fid), {})
        last_topic_id = forum_progress.get('last_topic_id', 0)

        # Get topic listing
        topics = scrape_forum(session, fid, fname, limit=args.limit)

        # Filter already-scraped topics if resuming
        if args.resume and last_topic_id > 0:
            topics = [t for t in topics if t['topic_id'] > last_topic_id]
            print(f"  Resuming after topic {last_topic_id}, {len(topics)} remaining")

        # Scrape each topic
        for i, topic_meta in enumerate(topics):
            topic_id = topic_meta['topic_id']

            # Skip if already scraped
            topic_file = TOPICS_DIR / f"topic_{topic_id}.json"
            if topic_file.exists() and not args.resume:
                print(f"  [{i+1}/{len(topics)}] Already scraped: {topic_meta['title'][:50]}")
                continue

            result = scrape_topic(session, topic_meta)

            if result:
                total_topics_scraped += 1
                total_posts_scraped += result['post_count']

                # Update progress
                progress['forums'][str(fid)] = {
                    'last_topic_id': topic_id,
                    'topics_scraped': progress['forums'].get(str(fid), {}).get('topics_scraped', 0) + 1,
                    'posts_scraped': progress['forums'].get(str(fid), {}).get('posts_scraped', 0) + result['post_count'],
                }
                save_progress(progress)

                # Update stats
                stats['total_topics'] += 1
                stats['total_posts'] += result['post_count']
                stats['forums'][str(fid)] = {
                    'name': fname,
                    'topics_scraped': stats['forums'].get(str(fid), {}).get('topics_scraped', 0) + 1,
                    'posts_scraped': stats['forums'].get(str(fid), {}).get('posts_scraped', 0) + result['post_count'],
                }
                stats['total_requests'] = session.request_count
                stats['total_errors'] = session.error_count
                save_stats(stats)

            # Rate limiting between topics
            if i < len(topics) - 1:
                time.sleep(args.delay)

    # Final stats
    stats['total_requests'] = session.request_count
    stats['total_errors'] = session.error_count
    save_stats(stats)

    print(f"\n{'='*60}")
    print(f"Scraping Complete!")
    print(f"  Topics scraped: {total_topics_scraped}")
    print(f"  Posts scraped:  {total_posts_scraped}")
    print(f"  HTTP requests:   {session.request_count}")
    print(f"  Errors:          {session.error_count}")
    print(f"  Output dir:      {TOPICS_DIR}")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()