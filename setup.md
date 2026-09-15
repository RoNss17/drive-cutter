# Drive Cutter

Cut segments from Google Drive and WeTransfer videos without downloading the full file.

Uses FFmpeg HTTP Range requests — pulling 2 minutes from a 4-hour video downloads ~2% of the file, not 100%.

**No login or API keys required.** Works with any publicly shared Drive link or WeTransfer transfer. For private Drive files, the Chrome extension uses your existing browser session.

---

## Quick Setup (macOS / Linux, ~2 minutes)

### Prerequisites

- **Python 3.9+** — `brew install python3` or `sudo apt install python3 python3-venv`
- **FFmpeg** — `brew install ffmpeg` or `sudo apt install ffmpeg`
- **Google Chrome**

### Install

```bash
cd drive-cutter
chmod +x install.sh
./install.sh
```

The script will:
1. Check prerequisites
2. Create a Python virtual environment and install dependencies
3. Walk you through loading the Chrome extension
4. Register the native messaging host with your extension ID

After it finishes, restart Chrome.

---

## Usage

1. Open a **Google Drive** video page (`drive.google.com/file/d/.../view`) or a **WeTransfer** preview page
2. The **Drive Cutter** panel appears in the bottom-right corner
3. Use the ⏱ buttons to capture the current playhead position, or type times manually
4. Click **Cut** — the server starts automatically if needed
5. Click **Download** when ready

You can add multiple segments and cut them all at once.

---

## Sharing with others

1. Share the `drive-cutter/` folder (zip, git clone, airdrop, etc.)
2. They run `./install.sh`
3. Done

---

## How it works

- **`-ss` before `-i`** — FFmpeg seeks via HTTP Range requests, not by downloading from the start
- **`-c copy`** — stream copy, no re-encoding (fast, lossless, snaps to nearest keyframe)
- **Local proxy** — the server proxies Google Drive downloads to handle redirect/range quirks that FFmpeg can't
- **Auto-start** — the Chrome extension uses Native Messaging to start the server on demand
- **Auto-shutdown** — server stops after 10 minutes of inactivity

### WeTransfer

The server calls WeTransfer's API to get a signed CloudFront URL (10-min expiry), which also supports Range requests.

---

## Project structure

```
drive-cutter/
├── app.py                  FastAPI server
├── requirements.txt        fastapi + uvicorn
├── install.sh              One-time setup (run this)
├── register-extension.sh   Re-register extension ID if needed
├── static/index.html       Standalone web UI (optional)
├── extension/
│   ├── manifest.json       Chrome MV3 manifest
│   ├── background.js       Service worker
│   ├── content.js          Injected panel on Drive/WeTransfer
│   ├── content.css         Panel styles
│   ├── popup.html/js       Extension popup
│   └── icon*.png           Icons
└── native-host/
    └── host.py             Starts server on demand via Native Messaging
```

## Configuration (optional)

| Variable | Default | Description |
|---|---|---|
| `HOST` | `127.0.0.1` | Server bind address |
| `PORT` | `8000` | Server port |
| `IDLE_TIMEOUT` | `600` | Auto-shutdown delay in seconds (0 = off) |

Set via environment variables: `PORT=9000 ./venv/bin/python app.py`
