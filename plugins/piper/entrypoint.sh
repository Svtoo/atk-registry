#!/bin/bash
set -e

VOICE="${PIPER_VOICE:-en_GB-cori-high}"
DATA_DIR="${PIPER_DATA_DIR:-/app/models}"

echo "Piper TTS starting with voice: $VOICE"

# Check if voice model exists, download if not
MODEL_PATH="$DATA_DIR/$VOICE.onnx"
if [ ! -f "$MODEL_PATH" ]; then
    echo "Downloading voice model: $VOICE..."
    python3 -m piper.download_voices --data-dir "$DATA_DIR" "$VOICE"
fi

echo "Starting Piper HTTP server..."
exec python3 -m piper.http_server --data-dir "$DATA_DIR" -m "$VOICE"

