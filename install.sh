#!/bin/bash
set -e

# --------------------------------------------------
# Drive Cutter — one-time setup (macOS & Linux)
# --------------------------------------------------
# Installs ALL dependencies from scratch:
#   - Xcode Command Line Tools (macOS)
#   - Homebrew (macOS)
#   - Python 3 + FFmpeg
#   - Python virtual environment + pip deps
#   - Opens Chrome + extension folder for easy loading
#   - Registers native messaging host (auto, no ID needed)
# --------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"
HOST_NAME="com.drivecutter.host"
HOST_PY="$SCRIPT_DIR/native-host/host.py"
OS="$(uname)"

# Fixed extension ID — pinned via manifest.json "key" field
# Same for everyone, no need to copy/paste
EXT_ID="cmddahdpalfapiiiepdfmelnmpcihgie"

echo ""
echo "  ╔══════════════════════════════════╗"
echo "  ║     Drive Cutter — Setup         ║"
echo "  ╚══════════════════════════════════╝"
echo ""

# ---- Helper ----
ask_install() {
  local name="$1"
  read -rp "  Install $name now? [Y/n] " answer
  case "$answer" in
    [nN]*) return 1 ;;
    *) return 0 ;;
  esac
}

# ==========================================================
#  STEP 1: Xcode Command Line Tools (macOS only)
# ==========================================================
echo "  [1/5] Xcode Command Line Tools"

if [ "$OS" = "Darwin" ]; then
  if xcode-select -p &>/dev/null; then
    echo "  ✓ Already installed"
  else
    echo "  ✗ Not installed (needed for git, python3, build tools)"
    if ask_install "Xcode Command Line Tools"; then
      echo "  Installing… (a system dialog may appear — click Install)"
      xcode-select --install 2>/dev/null || true
      echo ""
      echo "  Waiting for installation to finish…"
      echo "  (Click 'Install' in the dialog if it appeared)"
      until xcode-select -p &>/dev/null; do
        sleep 5
      done
      echo "  ✓ Installed"
    else
      echo "  ⚠ Skipped — some dependencies may fail."
    fi
  fi
else
  echo "  ✓ Not needed (Linux)"
fi

# ==========================================================
#  STEP 2: Homebrew (macOS) / apt check (Linux)
# ==========================================================
echo ""
echo "  [2/5] Package manager"

if [ "$OS" = "Darwin" ]; then
  BREW_BIN=""
  if [ -x "/opt/homebrew/bin/brew" ]; then
    BREW_BIN="/opt/homebrew/bin/brew"
  elif [ -x "/usr/local/bin/brew" ]; then
    BREW_BIN="/usr/local/bin/brew"
  elif command -v brew &>/dev/null; then
    BREW_BIN="$(command -v brew)"
  fi

  if [ -n "$BREW_BIN" ]; then
    echo "  ✓ Homebrew found"
    eval "$("$BREW_BIN" shellenv 2>/dev/null)" 2>/dev/null || true
  else
    echo "  ✗ Homebrew not installed (needed for Python & FFmpeg)"
    if ask_install "Homebrew"; then
      echo "  Installing Homebrew…"
      /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
      if [ -x "/opt/homebrew/bin/brew" ]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
      elif [ -x "/usr/local/bin/brew" ]; then
        eval "$(/usr/local/bin/brew shellenv)"
      fi
      echo "  ✓ Homebrew installed"
    else
      echo "  ✗ Skipped. Install Python 3 and FFmpeg manually."
    fi
  fi
elif [ "$OS" = "Linux" ]; then
  if command -v apt &>/dev/null; then
    echo "  ✓ apt available"
  else
    echo "  ⚠ apt not found — you may need to install dependencies manually"
  fi
fi

# ==========================================================
#  STEP 3: Python 3 + FFmpeg
# ==========================================================
echo ""
echo "  [3/5] Python 3 & FFmpeg"

# ---- Python 3 ----
if command -v python3 &>/dev/null; then
  PY_MINOR="$(python3 -c 'import sys; print(sys.version_info.minor)' 2>/dev/null || echo 0)"
  if [ "$PY_MINOR" -ge 9 ]; then
    echo "  ✓ $(python3 --version)"
  else
    echo "  ⚠ $(python3 --version) found but 3.9+ required"
    if [ "$OS" = "Darwin" ] && command -v brew &>/dev/null; then
      ask_install "Python 3 (via Homebrew)" && brew install python3
    elif [ "$OS" = "Linux" ] && command -v apt &>/dev/null; then
      ask_install "Python 3 (via apt)" && sudo apt update -qq && sudo apt install -y python3 python3-venv python3-pip
    fi
    echo "  ✓ $(python3 --version)"
  fi
else
  echo "  ✗ Python 3 not installed"
  if [ "$OS" = "Darwin" ] && command -v brew &>/dev/null; then
    if ask_install "Python 3 (via Homebrew)"; then
      brew install python3
      echo "  ✓ $(python3 --version)"
    else
      echo "  ✗ Cannot continue without Python 3."; exit 1
    fi
  elif [ "$OS" = "Linux" ] && command -v apt &>/dev/null; then
    if ask_install "Python 3 (via apt)"; then
      sudo apt update -qq && sudo apt install -y python3 python3-venv python3-pip
      echo "  ✓ $(python3 --version)"
    else
      echo "  ✗ Cannot continue without Python 3."; exit 1
    fi
  else
    echo "  ✗ Install Python 3.9+ manually: https://python.org"; exit 1
  fi
fi

# Verify venv module
if ! python3 -m venv --help &>/dev/null; then
  if [ "$OS" = "Linux" ] && command -v apt &>/dev/null; then
    echo "  Installing python3-venv…"
    sudo apt install -y python3-venv
  else
    echo "  ✗ Python venv module missing. Reinstall Python 3."; exit 1
  fi
fi

# ---- FFmpeg ----
if command -v ffmpeg &>/dev/null; then
  echo "  ✓ $(ffmpeg -version 2>&1 | head -1 | cut -d' ' -f1-3)"
else
  echo "  ✗ FFmpeg not installed"
  if [ "$OS" = "Darwin" ] && command -v brew &>/dev/null; then
    if ask_install "FFmpeg (via Homebrew — may take a few minutes)"; then
      brew install ffmpeg
      echo "  ✓ $(ffmpeg -version 2>&1 | head -1 | cut -d' ' -f1-3)"
    else
      echo "  ✗ Cannot cut videos without FFmpeg."; exit 1
    fi
  elif [ "$OS" = "Linux" ] && command -v apt &>/dev/null; then
    if ask_install "FFmpeg (via apt)"; then
      sudo apt update -qq && sudo apt install -y ffmpeg
      echo "  ✓ $(ffmpeg -version 2>&1 | head -1 | cut -d' ' -f1-3)"
    else
      echo "  ✗ Cannot cut videos without FFmpeg."; exit 1
    fi
  else
    echo "  ✗ Install FFmpeg manually: https://ffmpeg.org"; exit 1
  fi
fi

# ==========================================================
#  STEP 4: Python virtual environment
# ==========================================================
echo ""
echo "  [4/5] Python environment"

if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/pip" install -q -r "$SCRIPT_DIR/requirements.txt"
chmod +x "$HOST_PY"
echo "  ✓ Dependencies installed"

# ==========================================================
#  STEP 5: Chrome extension + native messaging
# ==========================================================
echo ""
echo "  [5/5] Chrome extension"

# ---- Register native messaging host (auto — ID is fixed) ----
if [ "$OS" = "Darwin" ]; then
  NM_DIR="$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts"
elif [ "$OS" = "Linux" ]; then
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

# ---- Check if Chrome is installed ----
CHROME_OK=false
if [ "$OS" = "Darwin" ] && [ -d "/Applications/Google Chrome.app" ]; then
  CHROME_OK=true
elif [ "$OS" = "Linux" ] && command -v google-chrome &>/dev/null; then
  CHROME_OK=true
fi

if [ "$CHROME_OK" = false ]; then
  echo ""
  echo "  ⚠ Google Chrome not found."
  echo "    Install it from https://google.com/chrome"
  echo "    Then re-run this script."
  exit 1
fi

# ---- Open Chrome extensions page + Finder for easy loading ----
echo ""
echo "  ┌──────────────────────────────────────────────┐"
echo "  │                                              │"
echo "  │  Almost done! Load the extension in Chrome:  │"
echo "  │                                              │"
echo "  │  1. Turn on Developer mode (top-right)       │"
echo "  │  2. Click 'Load unpacked'                    │"
echo "  │  3. Select the extension folder              │"
echo "  │     (opening it for you now…)                │"
echo "  │                                              │"
echo "  └──────────────────────────────────────────────┘"
echo ""

if [ "$OS" = "Darwin" ]; then
  # Open the extensions page in Chrome
  open -a "Google Chrome" "chrome://extensions" 2>/dev/null || true
  sleep 1
  # Open Finder to the extension folder so they can select it
  open "$SCRIPT_DIR/extension" 2>/dev/null || true
elif [ "$OS" = "Linux" ]; then
  google-chrome "chrome://extensions" 2>/dev/null &
  sleep 1
  xdg-open "$SCRIPT_DIR/extension" 2>/dev/null || true
fi

read -rp "  Press Enter once you've loaded the extension… "

# ---- Done ----
echo ""
echo "  ╔══════════════════════════════════════════════╗"
echo "  ║                                              ║"
echo "  ║  ✓ Setup complete!                           ║"
echo "  ║                                              ║"
echo "  ║  Quit Chrome (Cmd+Q) and reopen it.         ║"
echo "  ║  Then go to any Google Drive or WeTransfer   ║"
echo "  ║  video page — the panel appears              ║"
echo "  ║  automatically in the bottom-right.          ║"
echo "  ║                                              ║"
echo "  ╚══════════════════════════════════════════════╝"
echo ""
