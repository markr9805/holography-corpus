# Holography Transcript Pipeline

Multi-creator transcript pipeline for holography content across YouTube, Vimeo, and the web.

## Overview

This pipeline downloads, transcribes, merges, and publishes transcripts from holography content creators. It's adapted from the Darante LaMar single-creator pipeline to support **multiple creators** across **multiple platforms**.

### Key Features

- **Multi-creator catalog** — `creators.json` defines all creators with channel URLs, platforms, tiers, and metadata
- **Multi-platform download** — YouTube and Vimeo support via yt-dlp, with website URL extraction
- **Dual Whisper models** — Turbo + Large-V3 for cross-checking transcription accuracy
- **Smart flag classification** — Auto-resolves profanity censors, LV3 hallucinations, function word swaps, and holography-specific term mismatches
- **Speaker diarization** — pyannote 3.1 for identifying who speaks when
- **Obsidian vault** — Full corpus as navigable Obsidian notes with wikilinks
- **Static website** — Dark-themed responsive site with video embeds, transcripts, and client-side search
- **Incremental processing** — Scan for new videos, download only new ones, transcribe only new ones

## Quick Start

```bash
# 1. Scan channels for new videos
python3 scan_channels.py

# 2. Download captions and audio
python3 01_download.py --all

# 3. Run Whisper transcription (requires whisper-env)
python3 02_whisper.py --all --resume

# 4. Merge transcripts and flag disagreements
python3 03_merge.py --all

# 5. Label and classify flags
python3 04_label.py --all

# 6. Apply corrections
python3 05_correct.py --all

# 7. Speaker diarization (requires diarize-env)
python3 06_diarize.py --all

# Or run the full pipeline at once:
python3 pipeline.py
```

## Build Outputs

```bash
# Build Obsidian vault
python3 build_obsidian_vault.py

# Build search index
python3 build_search_index.py

# Build static website
python3 build_website.py

# Serve website locally
cd website && python3 -m http.server 8000
```

## Directory Structure

```
holography-transcript-pipeline/
├── README.md                    # This file
├── catalog.json                 # Multi-creator video catalog (auto-generated)
├── creators.json                # Creator definitions (manually maintained)
├── corrections.json             # Growing corrections dictionary
├── .env                         # API keys (HF_TOKEN, etc.)
├── .gitignore
├── 01_download.py               # Download captions + audio from YouTube/Vimeo
├── 02_whisper.py                # Whisper transcription (turbo + large-v3)
├── 03_merge.py                  # Merge captions + Whisper outputs
├── 04_label.py                  # Classify flagged disagreements
├── 05_correct.py                # Apply correction dictionary
├── 06_diarize.py                # Speaker diarization (pyannote)
├── pipeline.py                  # Full pipeline orchestration
├── scan_channels.py             # Scan ALL channels for new videos
├── build_obsidian_vault.py      # Generate Obsidian vault
├── build_search_index.py        # Build search-index.json
├── build_website.py             # Generate static website
├── scrape_forum.py              # Scrape Holography Forum (phpBB)
├── forum_to_markdown.py        # Convert forum JSON to Markdown
├�── forum_to_search_index.py   # Build forum search index
├── captions/                    # Downloaded captions (.srt)
├── audio/                       # Downloaded audio (.wav) — cleaned up after processing
├── chunks/                      # Chunked audio for Whisper — cleaned up after processing
├── transcripts/                 # Final transcripts and flags
│   └── forum/                  # Forum thread markdown transcripts
├── forum/                       # Forum scraping data
│   ├── raw/                     # Raw HTML pages
│   ├── topics/                  # Parsed topic JSON
│   ├── forum_progress.json      # Resume state
│   └── forum_stats.json         # Scraping statistics
├── analysis/                    # Corpus analysis, visualizations
│   ├── search-index.json
│   ├── forum-search-index.json
│   └── transcripts/
└── website/                     # Generated static website
    ├── index.html
    ├── creators/
    ├── videos/
    ├── search/
    └── static/
```

## Creators

The `creators.json` file defines all holography content creators organized by tier:

| Tier | Description | Examples |
|------|-------------|---------|
| 1 | Primary — Active, prolific holography creators | LaserboyHolo, HoloJay, Eric Leiser, Martin Richardson |
| 2 | Secondary — Important but smaller or less active | TheDrlaser, XAR3D, Josh Dellay, HoloCenter, HoloTalk, LitiHolo |
| 3 | Tertiary — Occasional or indirect holography content | Applied Science, Getty Museum, Rob Hocking |
| 4 | Supplementary — Minimal or archival content | Rayvel, Virtual Museum, BYU, Jacques Holograms |

### Adding a New Creator

Add an entry to `creators.json`:

```json
{
  "id": "newcreator",
  "name": "New Creator Name",
  "platform": "youtube",
  "channel_url": "https://www.youtube.com/@newcreator",
  "tier": 2,
  "description": "Description of the creator's content.",
  "status": "active",
  "subscribers": 1000,
  "video_count": 50,
  "website": "https://example.com"
}
```

Then run `python3 scan_channels.py --creator newcreator` to scan for videos.

## Platforms

### YouTube
Full support via yt-dlp. Auto-captions and audio download work reliably.

### Vimeo
Full support via yt-dlp. Caption availability varies. Audio download works well.

### Websites
The `scan_channels.py` script can extract YouTube/Vimeo embed URLs from personal websites. These are added to the catalog with their original platform (youtube/vimeo) for download.

## Pipeline Steps

### Step 1: Download (`01_download.py`)
- Scans YouTube/Vimeo channels for all videos
- Downloads English auto-captions (SRT format)
- Downloads audio (WAV format) for Whisper processing
- Supports `--creator` flag to process specific creators
- Supports `--resume` to skip already-downloaded videos

### Step 2: Whisper (`02_whisper.py`)
- Runs both Whisper Turbo and Large-V3 on chunked audio
- 5-minute chunks with 10-second overlap for accuracy
- Uses MLX-accelerated models on Apple Silicon
- Produces per-video per-model transcripts

### Step 3: Merge (`03_merge.py`)
- Aligns YouTube captions with both Whisper outputs
- Flags disagreements between sources with timestamps
- Generates review notes for human verification
- Supports multi-platform video URLs (YouTube timestamps, Vimeo links)

### Step 4: Label (`04_label.py`)
- Auto-classifies flags into categories:
  - **Holography terms** — Known holography terminology that Whisper mishears
  - **Profanity** — YouTube censorship vs. Whisper accuracy
  - **Cascades** — LV3 hallucination patterns
  - **Morphology** — Same root word, different form
  - **Function words** — Stopword swaps
  - **Minor** — Phonetic variants
  - **Content** — Genuine disagreements needing human review

### Step 5: Correct (`05_correct.py`)
- Applies the growing `corrections.json` dictionary
- Supports both word-level and regex pattern corrections
- Holography-specific terms can be added to the corrections dictionary

### Step 6: Diarize (`06_diarize.py`)
- Uses pyannote speaker-diarization-3.1
- Auto-detects number of speakers (or specify with `--num-speakers`)
- Produces per-video diarization JSON with speaker turns
- Supports MPS acceleration on Apple Silicon

## Environment Setup

### Whisper Environment
```bash
python3 -m venv whisper-env
source whisper-env/bin/activate
pip install mlx-whisper
```

### Diarization Environment
```bash
python3 -m venv diarize-env
source diarize-env/bin/activate
pip install pyannote.audio torch
```

### HuggingFace Token
You need a HuggingFace token with access to `pyannote/speaker-diarization-3.1`:
1. Create account at https://huggingface.co
2. Get token at https://huggingface.co/settings/tokens
3. Accept model terms at https://huggingface.co/pyannote/speaker-diarization-3.1
4. Add token to `.env` file: `HF_TOKEN=your_token_here`

## Obsidian Vault

The Obsidian vault is built at `~/Obsidian/Holography-Corpus/` with:
- One note per video with full transcript and metadata
- Creator notes with bios, stats, and video lists
- Platform index pages (YouTube, Vimeo)
- Wikilinks connecting everything
- YAML frontmatter for Dataview queries

## Website

The static website is built at `website/` with:
- **Home page** — Corpus stats, active creators, recent videos
- **Creator pages** — Bio, stats, video list for each creator
- **Video pages** — Embedded player, transcript, metadata
- **Search page** — Client-side Lunr.js search across all transcripts
- **Dark theme** — Consistent, responsive design

## Corrections Dictionary

The `corrections.json` file grows over time. Add holography-specific corrections:

```json
{
  "entries": [
    {
      "wrong": "holograph",
      "right": "hologram",
      "context": "made a",
      "source_video": "abc123",
      "label": "holography_term",
      "note": "Whisper often mishears 'hologram' as 'holograph'"
    }
  ]
}
```

## Differences from Darante Pipeline

| Feature | Darante | Holography |
|---------|---------|-------------|
| Creators | Single (Darante' LaMar) | Multiple (40+) |
| Platforms | YouTube only | YouTube + Vimeo + websites |
| Catalog | Flat video list | Multi-creator with creator_id |
| Download | Single channel | Multi-channel with per-creator tracking |
| Transcripts | Single-creator frontmatter | Multi-creator with tier metadata |
| Labels | Generic profanity/morphology | + Holography-specific term detection |
| Website | Visualization dashboard | Full static site with search |
| Obsidian | Single-creator vault | Multi-creator with cross-references |

## Forum Scraping

The Holography Forum at [holographyforum.org](https://holographyforum.org/forum/) is a phpBB forum with ~51,000 posts across ~6,500 topics. It's a critical knowledge base covering DCG techniques, silver halide chemistry, optics, equipment, and ISDH symposium discussions. The forum scraper module downloads all topics and posts as structured data.

### Forum Sections

| Priority | Forum | ID | Topics | Posts |
|----------|-------|-----|--------|-------|
| 1 | General Holography (old) | 30 | 1,921 | 18,624 |
| 1 | DCG (Dichromated Gelatin) | 7 | 155 | 1,582 |
| 1 | Techniques | 5 | 428 | 4,241 |
| 1 | Beginning Holography | 45 | 234 | 2,462 |
| 1 | Gallery | 32 | 299 | 2,243 |
| 1 | AgX (Silver Halide) | 9 | 65 | 575 |
| 1 | Optics | 23 | 36 | 288 |
| 1 | Equipment | 6 | 235 | 1,261 |
| 1 | ISDH/Symposia | 3 | 28 | 101 |
| 1 | Announcements | 4 | 71 | 313 |
| 1 | General Holography (new) | 8 | 138 | 922 |
| 2 | Network54 Archive | 41 | 1,371 | 11,598 |
| 2 | Links | 33 | 231 | 638 |
| 2 | For Sale or Trade | 39 | 371 | 1,576 |
| 2 | Off Topic | 12/34 | 632 | 2,563 |
| 2 | Jobs/Admin/Dump | 52/31/54 | 242 | 1,150 |

### Scraping Commands

```bash
# Scrape all high-value forums (default)
python3 scrape_forum.py

# Scrape a specific forum (DCG)
python3 scrape_forum.py --forum 7

# Scrape multiple forums
python3 scrape_forum.py --forum 7,5,30

# Scrape ALL forums including low-priority
python3 scrape_forum.py --all-forums

# Dry run — list what would be scraped
python3 scrape_forum.py --dry-run

# Limit topics per forum (for testing)
python3 scrape_forum.py --limit 5

# Scrape a single topic by ID
python3 scrape_forum.py --topic 11416

# Resume from last checkpoint
python3 scrape_forum.py --resume

# Custom delay between requests (default: 1.5s)
python3 scrape_forum.py --delay 3
```

### Convert to Markdown

```bash
# Convert all scraped topics to Markdown
python3 forum_to_markdown.py

# Convert only DCG topics
python3 forum_to_markdown.py --forum 7

# Convert a specific topic
python3 forum_to_markdown.py --topic 11416

# Force overwrite existing files
python3 forum_to_markdown.py --force
```

### Build Search Index

```bash
# Build forum-only search index
python3 forum_to_search_index.py

# Include full post content (larger file)
python3 forum_to_search_index.py --content

# Merge with video search index
python3 forum_to_search_index.py --merge

# Index only specific forums
python3 forum_to_search_index.py --forum 7,5
```

### Output Structure

```
holography-transcript-pipeline/
├── forum/
│   ├── raw/                        # Raw HTML pages (for re-parsing)
│   │   ├── forum_7_page_0.html      # Forum listing page
│   │   ├── topic_11416_page_0.html  # Topic view page
│   │   └── ...
│   ├── topics/                      # Parsed topic JSON (one per topic)
│   │   ├── topic_11416.json         # Full topic with all posts
│   │   └── ...
│   ├── forum_progress.json          # Resume state
│   └── forum_stats.json             # Scraping statistics
├── transcripts/
│   ├── forum/                       # Markdown transcripts
│   │   ├── DCG - Dichromated Gelatin - 2025 International Symposium.md
│   │   └── ...
│   └── ...
├── analysis/
│   ├── forum-search-index.json      # Forum-only search index
│   ├── search-index.json            # Merged video + forum index
│   └── ...
└── ...
```

### Resume Behavior

The scraper saves progress after each topic in `forum/forum_progress.json`. If interrupted:

- **Resume from checkpoint**: `python3 scrape_forum.py --resume` picks up where it left off
- **Re-parse existing HTML**: If raw HTML is saved in `forum/raw/`, you can re-parse without re-fetching
- **Skip existing topics**: Topics already in `forum/topics/` are skipped unless `--resume` is used

### Rate Limiting

- 1.5 second delay between requests (configurable with `--delay`)
- Exponential backoff on errors (5s, 15s, 45s)
- Progress saved after each topic (not each post)
- Raw HTML cached for re-parsing without re-fetching

### Data Format

Each topic JSON file contains:

```json
{
  "topic_id": 11416,
  "title": "2025 International Symposium on Display Holography",
  "forum_id": 7,
  "forum_name": "DCG",
  "url": "https://holographyforum.org/forum/viewtopic.php?t=11416",
  "replies": 8,
  "views": 1983856,
  "starter": "Ed Wesly",
  "post_count": 9,
  "posts": [
    {
      "post_id": 73462,
      "author": "Ed Wesly",
      "author_id": 2186,
      "post_date": "Wed Feb 12, 2025 1:04 pm",
      "post_datetime": "2025-02-12T18:04:11+00:00",
      "content_md": "Here is something of interest...",
      "attachments": [{"type": "image", "url": "...", "filename": "..."}],
      "quotes": [],
      "signature": "\"We're the flowers in the dustbin\"  Sex Pistols"
    }
  ]
}
```

## License

This pipeline is for research and archival purposes. Respect the copyright of the original video creators.