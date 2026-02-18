#!/bin/bash
# OpenMemory install/update script
# Clones vendor repo at pinned version, builds Docker images, starts services
set -e

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENDOR_DIR="$PLUGIN_DIR/vendor"
VENDOR_NAME="OpenMemory"
VENDOR_URL="https://github.com/CaviraOSS/OpenMemory.git"
# Pinned to v1.2.3: later versions removed dashboard source
VENDOR_REF="v1.2.3"
EMBEDDING_MODEL="mxbai-embed-large"

echo "=== OpenMemory Install ==="

# ─── 1. Check Ollama is installed ───────────────────────────────────────────
if ! command -v ollama &>/dev/null; then
    echo ""
    echo "  ❌ Ollama is not installed."
    echo ""
    echo "  OpenMemory requires Ollama for local embeddings."
    echo "  Install Ollama first, then re-run this install."
    echo ""
    echo "  macOS (Homebrew):  brew install ollama"
    echo "  macOS / Linux:     curl -fsSL https://ollama.com/install.sh | sh"
    echo "  All platforms:     https://ollama.com/download"
    echo ""
    exit 1
fi
echo "  ✓ Ollama found: $(command -v ollama)"

# ─── 2. Check Ollama is running ─────────────────────────────────────────────
if ! ollama list &>/dev/null; then
    echo ""
    echo "  ❌ Ollama is installed but not running."
    echo ""
    echo "  Start Ollama first, then re-run this install."
    echo ""
    echo "  macOS (app):   Open the Ollama application"
    echo "  CLI:           ollama serve &"
    echo ""
    exit 1
fi
echo "  ✓ Ollama is running"

# ─── 3. Ensure embedding model is available ─────────────────────────────────
if ollama list | grep -q "$EMBEDDING_MODEL"; then
    echo "  ✓ Model '$EMBEDDING_MODEL' already available — skipping download"
else
    echo ""
    echo "  OpenMemory needs the '$EMBEDDING_MODEL' embedding model (~669 MB)."
    echo "  This is a one-time download."
    echo ""
    echo "  Pulling '$EMBEDDING_MODEL'..."
    if ! ollama pull "$EMBEDDING_MODEL"; then
        echo ""
        echo "  ❌ Failed to pull '$EMBEDDING_MODEL'."
        echo "  Check your internet connection and that Ollama is running, then retry."
        echo ""
        exit 1
    fi
    echo "  ✓ Model '$EMBEDDING_MODEL' ready"
fi

# ─── 4. Clone vendor repo (idempotent — always fresh) ───────────────────────
echo "  Cloning $VENDOR_NAME at $VENDOR_REF..."
rm -rf "$VENDOR_DIR"
mkdir -p "$VENDOR_DIR"
git clone --depth 1 --branch "$VENDOR_REF" "$VENDOR_URL" "$VENDOR_DIR/$VENDOR_NAME"

# ─── 5. Build Docker images ─────────────────────────────────────────────────
echo "  Building Docker images..."
cd "$PLUGIN_DIR"
docker compose build

# ─── 6. Start services ──────────────────────────────────────────────────────
echo "  Starting services..."
docker compose up -d

# ─── 7. Health checks with retries ──────────────────────────────────────────
echo "  Waiting for services to become healthy..."

API_OK=false
for i in $(seq 1 15); do
    if curl -sf http://localhost:8787/health > /dev/null 2>&1; then
        API_OK=true
        break
    fi
    sleep 2
done

DASH_OK=false
for i in $(seq 1 15); do
    if curl -sf http://localhost:3737 > /dev/null 2>&1; then
        DASH_OK=true
        break
    fi
    sleep 2
done

if $API_OK; then
    echo "  ✅ API: http://localhost:8787"
else
    echo "  ⚠️  API not responding after 30s — check: docker compose logs openmemory"
fi

if $DASH_OK; then
    echo "  ✅ Dashboard: http://localhost:3737"
else
    echo "  ⚠️  Dashboard not responding after 30s — check: docker compose logs dashboard"
fi

echo "  ✅ OpenMemory installed"
