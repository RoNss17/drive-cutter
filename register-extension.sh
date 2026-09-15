#!/bin/bash
set -e

# --------------------------------------------------
# Registers the Chrome extension ID in the native
# messaging host manifest so Chrome allows the
# connection.
#
# Usage: ./register-extension.sh <extension-id>
# --------------------------------------------------

if [ -z "$1" ]; then
  echo "Usage: ./register-extension.sh <extension-id>"
  echo ""
  echo "  Find your extension ID at chrome://extensions"
  echo "  after loading the unpacked extension."
  exit 1
fi

EXT_ID="$1"
HOST_NAME="com.drivecutter.host"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HOST_PY="$SCRIPT_DIR/native-host/host.py"

if [ "$(uname)" = "Darwin" ]; then
  NM_DIR="$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts"
elif [ "$(uname)" = "Linux" ]; then
  NM_DIR="$HOME/.config/google-chrome/NativeMessagingHosts"
else
  echo "Unsupported OS"
  exit 1
fi

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
echo "  ✓ Manifest: $NM_DIR/$HOST_NAME.json"
echo ""
echo "  Restart Chrome for the change to take effect."
