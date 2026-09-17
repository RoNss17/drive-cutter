#!/bin/bash
# Builds shareable zips into dist/ from the current source tree.
# Never hand-edit dist/ — re-run this after every change you want to ship.
set -e
cd "$(dirname "$0")"

VERSION="$(sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' extension/manifest.json)"
STAGE="dist/stage/Drive-Cutter"

rm -rf dist
mkdir -p "$STAGE/extension" "$STAGE/native-host"

cp app.py requirements.txt setup.md install.sh install.bat "$STAGE/"
cp extension/manifest.json extension/background.js extension/content.js extension/content.css \
   extension/popup.html extension/popup.js extension/icon48.png extension/icon128.png "$STAGE/extension/"
cp native-host/host.py native-host/host.bat "$STAGE/native-host/"

(cd dist/stage && zip -qr "../Drive-Cutter-Mac-v$VERSION.zip" Drive-Cutter \
    -x 'Drive-Cutter/install.bat' 'Drive-Cutter/native-host/host.bat' '*.DS_Store')
(cd dist/stage && zip -qr "../Drive-Cutter-Windows-v$VERSION.zip" Drive-Cutter \
    -x 'Drive-Cutter/install.sh' '*.DS_Store')

rm -rf dist/stage
echo "Built:"
ls -la dist/*.zip
