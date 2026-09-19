#!/bin/bash
# Builds shareable zips into dist/ from the current source tree.
# Never hand-edit dist/ — re-run this after every change you want to ship.
set -e
cd "$(dirname "$0")"

VERSION="$(sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' extension/manifest.json)"

rm -rf dist
mkdir -p dist/stage

stage_folder() {
  local NAME="$1"
  local README="$2"
  local DIR="dist/stage/$NAME"
  mkdir -p "$DIR/extension" "$DIR/native-host"
  cp app.py requirements.txt setup.md install.sh install.bat "$DIR/"
  cp "$README" "$DIR/README First.txt"
  cp extension/manifest.json extension/background.js extension/content.js extension/content.css \
     extension/popup.html extension/popup.js extension/icon48.png extension/icon128.png "$DIR/extension/"
  cp native-host/host.py native-host/host.bat "$DIR/native-host/"
}

stage_folder "Drive Cutter Mac"     "README First (Mac).txt"
stage_folder "Drive Cutter Windows" "README First (Windows).txt"

(cd dist/stage && zip -qr "../Drive-Cutter-Mac-v$VERSION.zip" "Drive Cutter Mac" \
    -x '*/install.bat' '*/native-host/host.bat' '*.DS_Store')
(cd dist/stage && zip -qr "../Drive-Cutter-Windows-v$VERSION.zip" "Drive Cutter Windows" \
    -x '*/install.sh' '*.DS_Store')

rm -rf dist/stage
echo "Built:"
ls -la dist/*.zip
