#!/bin/bash
set -e

# --------------------------------------------------
# Drive Cutter — one-time setup (macOS & Linux)
# --------------------------------------------------
#   1. Python 3.9+  — uses what you have; otherwise installs a private
#                     copy with uv (seconds, no admin, no Homebrew/Xcode)
#   2. FFmpeg       — downloads a static binary into ./bin (no Homebrew)
#   3. Chrome       — registers the native messaging host and walks you
#                     through loading the extension
# --------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"
BIN_DIR="$SCRIPT_DIR/bin"
HOST_NAME="com.drivecutter.host"
HOST_PY="$SCRIPT_DIR/native-host/host.py"
OS="$(uname)"
ARCH="$(uname -m)"

# Fixed extension ID — pinned via manifest.json "key", same for everyone
EXT_ID="cmddahdpalfapiiiepdfmelnmpcihgie"

FFMPEG_RELEASE="https://github.com/eugeneware/ffmpeg-static/releases/download/b6.0"

echo ""
echo "  ╔══════════════════════════════════╗"
echo "  ║     Drive Cutter — Setup         ║"
echo "  ╚══════════════════════════════════╝"
echo ""

# ==========================================================
#  STEP 1: Python
# ==========================================================
echo "  [1/3] Python"

py_ok() {
  # macOS ships a /usr/bin/python3 stub that only works once Xcode CLT is
  # installed; running it pops a dialog. Skip it unless CLT is present.
  if [ "$OS" = "Darwin" ] && [ "$1" = "/usr/bin/python3" ] && ! xcode-select -p &>/dev/null; then
    return 1
  fi
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null
}

PYTHON=""
UV=""
for cand in python3 python3.13 python3.12 python3.11 python3.10 python3.9; do
  p="$(command -v "$cand" 2>/dev/null || true)"
  if [ -n "$p" ] && py_ok "$p"; then PYTHON="$p"; break; fi
done

if [ -n "$PYTHON" ]; then
  echo "  ✓ $("$PYTHON" --version) — $PYTHON"
else
  echo "  ✗ No Python 3.9+ found — installing a private copy with uv"
  if command -v uv &>/dev/null; then
    UV="$(command -v uv)"
  elif [ -x "$HOME/.local/bin/uv" ]; then
    UV="$HOME/.local/bin/uv"
  else
    curl -LsSf https://astral.sh/uv/install.sh | sh
    UV="$HOME/.local/bin/uv"
  fi
  "$UV" python install 3.12
  PYTHON="$("$UV" python find 3.12)"
  echo "  ✓ $("$PYTHON" --version) — $PYTHON"
fi

# ---- Virtual environment + deps ----
if [ ! -x "$VENV_DIR/bin/python" ]; then
  if [ -n "$UV" ]; then
    "$UV" venv --quiet --python "$PYTHON" "$VENV_DIR"
  else
    "$PYTHON" -m venv "$VENV_DIR"
  fi
fi
if [ -n "$UV" ]; then
  "$UV" pip install --quiet --python "$VENV_DIR/bin/python" -r "$SCRIPT_DIR/requirements.txt"
else
  "$VENV_DIR/bin/python" -m pip install -q -r "$SCRIPT_DIR/requirements.txt"
fi
echo "  ✓ Python environment ready"

# ==========================================================
#  STEP 2: FFmpeg
# ==========================================================
echo ""
echo "  [2/3] FFmpeg"

FFMPEG_BIN=""
if [ -x "$BIN_DIR/ffmpeg" ] && "$BIN_DIR/ffmpeg" -version &>/dev/null; then
  FFMPEG_BIN="$BIN_DIR/ffmpeg"
  echo "  ✓ Bundled FFmpeg present — bin/ffmpeg"
elif command -v ffmpeg &>/dev/null; then
  FFMPEG_BIN="$(command -v ffmpeg)"
  echo "  ✓ $(ffmpeg -version 2>&1 | head -1 | cut -d' ' -f1-3) — $FFMPEG_BIN"
else
  case "$OS/$ARCH" in
    Darwin/arm64)  ASSET="ffmpeg-darwin-arm64" ;;
    Darwin/x86_64) ASSET="ffmpeg-darwin-x64" ;;
    Linux/x86_64)  ASSET="ffmpeg-linux-x64" ;;
    *)             ASSET="" ;;
  esac

  if [ -n "$ASSET" ]; then
    echo "  ↓ Downloading FFmpeg static build (~80 MB)…"
    mkdir -p "$BIN_DIR"
    if curl -fL --progress-bar -o "$BIN_DIR/ffmpeg" "$FFMPEG_RELEASE/$ASSET"; then
      chmod +x "$BIN_DIR/ffmpeg"
      xattr -d com.apple.quarantine "$BIN_DIR/ffmpeg" 2>/dev/null || true
      if "$BIN_DIR/ffmpeg" -version &>/dev/null; then
        FFMPEG_BIN="$BIN_DIR/ffmpeg"
        echo "  ✓ FFmpeg installed — bin/ffmpeg"
      else
        rm -f "$BIN_DIR/ffmpeg"
        echo "  ✗ Downloaded binary would not run"
      fi
    else
      rm -f "$BIN_DIR/ffmpeg"
      echo "  ✗ Download failed"
    fi
  fi

  if [ -z "$FFMPEG_BIN" ]; then
    echo "  → Falling back to your package manager…"
    if [ "$OS" = "Darwin" ] && command -v brew &>/dev/null; then
      brew install ffmpeg && FFMPEG_BIN="$(command -v ffmpeg)"
    elif [ "$OS" = "Linux" ] && command -v apt-get &>/dev/null; then
      sudo apt-get update -qq && sudo apt-get install -y ffmpeg && FFMPEG_BIN="$(command -v ffmpeg)"
    fi
  fi

  if [ -z "$FFMPEG_BIN" ]; then
    echo "  ✗ Could not install FFmpeg. Install it manually (https://ffmpeg.org) and re-run."
    exit 1
  fi
fi

# ==========================================================
#  STEP 3: Chrome extension + native messaging
# ==========================================================
echo ""
echo "  [3/3] Chrome"

chmod +x "$HOST_PY"
# macOS marks downloaded folders as quarantined; Chrome refuses to launch the host then.
xattr -r -d com.apple.quarantine "$SCRIPT_DIR" 2>/dev/null || true

if [ "$OS" = "Darwin" ]; then
  NM_DIR="$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts"
else
  NM_DIR="$HOME/.config/google-chrome/NativeMessagingHosts"
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
echo "  ✓ Native messaging host registered"

CHROME_OK=false
if [ "$OS" = "Darwin" ] && [ -d "/Applications/Google Chrome.app" ]; then
  CHROME_OK=true
elif [ "$OS" = "Linux" ] && command -v google-chrome &>/dev/null; then
  CHROME_OK=true
fi
if [ "$CHROME_OK" = false ]; then
  echo ""
  echo "  ⚠ Google Chrome not found. Install it from https://google.com/chrome and re-run."
  exit 1
fi

echo ""
echo "  ┌──────────────────────────────────────────────┐"
echo "  │  Load the extension in Chrome:               │"
echo "  │                                              │"
echo "  │  1. Turn on Developer mode (top-right)       │"
echo "  │  2. Click 'Load unpacked'                    │"
echo "  │  3. Select the 'extension' folder            │"
echo "  │     (opening both for you now…)              │"
echo "  └──────────────────────────────────────────────┘"
echo ""

if [ "$OS" = "Darwin" ]; then
  open -a "Google Chrome" "chrome://extensions" 2>/dev/null || true
  sleep 1
  open "$SCRIPT_DIR/extension" 2>/dev/null || true
else
  google-chrome "chrome://extensions" 2>/dev/null &
  sleep 1
  xdg-open "$SCRIPT_DIR/extension" 2>/dev/null || true
fi

read -rp "  Press Enter once you've loaded the extension… "

echo ""
echo "  ╔══════════════════════════════════════════════╗"
echo "  ║  ✓ Setup complete!                           ║"
echo "  ║                                              ║"
echo "  ║  Quit Chrome fully (Cmd+Q) and reopen it.    ║"
echo "  ║  Open any Google Drive or WeTransfer video   ║"
echo "  ║  page — the panel appears bottom-right.      ║"
echo "  ╚══════════════════════════════════════════════╝"
echo ""
