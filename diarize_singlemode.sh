#!/bin/bash
# Diarize all transcribed singlemode (HoloTalk) videos
# Step 1: Download audio for videos that need diarization
# Step 2: Run diarization with --num-speakers 2
# Step 3: Clean up audio after

set -e
cd "$(dirname "$0")"

DIARIZE_VENV="/Users/mark/.openclaw/workspace/foster/darante-transcript-pilot/diarize-env"
PYTHON="$DIARIZE_VENV/bin/python3"
AUDIO_DIR="./audio"
TRANSCRIPTS_DIR="./transcripts"

# Get list of singlemode videos that are transcribed but not yet diarized
python3 -c "
import json, os
c = json.load(open('catalog.json'))
transcripts = set(os.listdir('transcripts'))
sm = [v for v in c if v.get('creator_id') == 'singlemode']
need = [v['id'] for v in sm 
        if (f'{v[\"id\"]}-parakeet.srt' in transcripts or f'{v[\"id\"]}-whisper-largev3.txt' in transcripts)
        and f'{v[\"id\"]}-diarization.json' not in transcripts]
for vid in need:
    print(vid)
" > /tmp/diarize_videos.txt

TOTAL=$(wc -l < /tmp/diarize_videos.txt | tr -d ' ')
echo "=== Diarizing $TOTAL singlemode videos ==="
echo ""

COUNT=0
while IFS= read -r VID; do
    COUNT=$((COUNT + 1))
    AUDIO_FILE="$AUDIO_DIR/${VID}.wav"
    DIAR_FILE="$TRANSCRIPTS_DIR/${VID}-diarization.json"
    
    # Skip if already diarized
    if [ -f "$DIAR_FILE" ]; then
        echo "[$COUNT/$TOTAL] Already diarized: $VID"
        continue
    fi
    
    # Download audio if not present
    if [ ! -f "$AUDIO_FILE" ]; then
        echo "[$COUNT/$TOTAL] Downloading audio: $VID"
        yt-dlp -x --audio-format wav -o "$AUDIO_DIR/${VID}.%(ext)s" "https://www.youtube.com/watch?v=${VID}" 2>/dev/null
        if [ ! -f "$AUDIO_FILE" ]; then
            echo "  FAILED to download audio for $VID, skipping"
            continue
        fi
    fi
    
    echo "[$COUNT/$TOTAL] Diarizing: $VID"
    "$PYTHON" 06_diarize.py --video "$VID" --num-speakers 2 --device cpu
    
    # Clean up audio after successful diarization to save disk
    if [ -f "$DIAR_FILE" ]; then
        rm -f "$AUDIO_FILE"
        echo "  Cleaned up audio for $VID"
    fi
    
done < /tmp/diarize_videos.txt

echo ""
echo "=== Diarization complete ==="