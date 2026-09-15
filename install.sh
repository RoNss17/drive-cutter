#!/bin/bash
set -e

# --------------------------------------------------
# Drive Cutter — one-time setup
# --------------------------------------------------
# Sets up everything needed to run the Chrome extension:
#   1. Checks prerequisites (Python 3, FFmpeg)
#   2. Creates virtual environment + installs deps
#   3. Loads extension into Chrome (manual step)
#   4. Registers native messaging host with your extension ID
# --------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"
HOST_NAME="com.drivecutter.host"
HOST_PY="$SCRIPT_DIR/native-host/host.py"

echo ""
echo "  ╔══════════════════════════════════╗"
echo "  ║     Drive Cutter — Setup         ║"
echo "  ╚══════════════════════════════════╝"
echo ""

# ---- Step 1: Prerequisites ----
echo "  [1/4] Checking prerequisites…"
echo ""

if ! command -v python3 &>/dev/null; then
  echo "  ✗ python3 not found. Install Python 3.9+ first."
  echo "    macOS:  brew install python3"
  echo "    Ubuntu: sudo apt install python3 python3-venv"
  exit 1
fi
echo "  ✓ python3 — $(python3 --version)"

if ! command -v ffmpeg &>/dev/null; then
  echo ""
  echo "  ✗ ffmpeg not found."
  echo "    macOS:   brew install ffmpeg"
  echo "    Ubuntu:  sudo apt install ffmpeg"
  echo "    Windows: https://ffmpeg.org/download.html"
  exit 1
fi
echo "  ✓ ffmpeg  — $(ffmpeg -version 2>&1 | head -1 | cut -d' ' -f1-3)"

# ---- Step 2: Python environment ----
echo ""
echo "  [2/4] Setting up Python environment…"

if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/pip" install -q -r "$SCRIPT_DIR/requirements.txt"
chmod +x "$HOST_PY"
echo "  ✓ Virtual environment ready"

# ---- Step 3: Load extension in Chrome ----
echo ""
echo "  [3/4] Load the Chrome extension"
echo ""
echo "  Open Chrome and do the following:"
echo ""
echo "    1. Go to  chrome://extensions"
echo "    2. Turn on  Developer mode  (toggle, top-right)"
echo "    3. Click  Load unpacked"
echo "    4. Select this folder:"
echo "       $SCRIPT_DIR/extension"
echo "    5. Copy the extension ID shown on the card"
echo "       (looks like: akhgmgilifoafjipkfgjbmbhcpfaahpl)"
echo ""
read -rp "  Paste your extension ID here: " EXT_ID

if [ -z "$EXT_ID" ]; then
  echo ""
  echo "  ✗ No extension ID entered."
  echo "    Re-run this script when you have it, or run:"
  echo "    ./register-extension.sh <extension-id>"
  exit 1
fi

# ---- Step 4: Register native messaging host ----
echo ""
echo "  [4/4] Registering native messaging host…"

if [ "$(uname)" = "Darwin" ]; then
  NM_DIR="$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts"
elif [ "$(uname)" = "Linux" ]; then
  NM_DIR="$HOME/.config/google-chrome/NativeMessagingHosts"
else
  echo "  ✗ Unsupported OS. See setup.md for manual registration."
  exit 1
fi

mkdir -p "$NM_DIR"

cat > "$NM_DIR/$HOST_NAME.json" <<MANIFEST
{
  "name": "$HOST_NAME",
  "description": "Drive Cutter — starts the local server on demand",
  "path": "$HOST_PY",
  "type": "stdio",
  "allowed_origins": [
    "chrome-extension://$EXT_ID/"
  ]
}
MANIFEST

echo "  ✓ Registered extension $EXT_ID"

# ---- Done ----
echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║  ✓ Setup complete!                       ║"
echo "  ║                                          ║"
echo "  ║  Restart Chrome, then go to any          ║"
echo "  ║  Google Drive or WeTransfer video page.  ║"
echo "  ║  The Drive Cutter panel appears           ║"
echo "  ║  automatically in the bottom-right.       ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""
