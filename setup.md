# Drive Cutter

Cut segments from Google Drive and WeTransfer videos without downloading the full file.

FFmpeg reads the source over HTTP Range requests, so pulling 2 minutes from a 4-hour video downloads roughly 2% of the file. No login, no API keys — for private Drive files the Chrome extension reuses your existing browser session.

---

## Install (macOS / Linux, ~2 minutes)

```bash
cd drive-cutter
chmod +x install.sh
./install.sh
```

The script:
1. Finds Python 3.9+ (or installs a private copy with [uv](https://docs.astral.sh/uv/) — no Homebrew or Xcode needed)
2. Downloads a static FFmpeg into `bin/` (falls back to Homebrew/apt only if that fails)
3. Registers the native messaging host and opens Chrome so you can **Load unpacked** → select the `extension` folder

Then quit Chrome fully (Cmd+Q) and reopen it.

**Windows:** run `install.bat`. The Windows path is untested — please report what breaks.

> Keep the folder somewhere permanent like `~/drive-cutter`. Do **not** leave it in `~/Downloads` — macOS revokes Chrome's access to Downloads across restarts and the extension silently unloads.

---

## Usage

1. Open a Google Drive video page (`drive.google.com/file/d/…/view`) or a WeTransfer preview page
2. The **Drive Cutter** panel appears bottom-right
3. Use the ⏱ buttons to capture the playhead, or type times as `HH:MM:SS`
4. Click **Cut** — the local server starts on demand
5. Click **Download** when it finishes; the temp file is deleted a few seconds after download

Multiple segments cut in parallel.

---

## How it works

- Chrome extension → native messaging → local FastAPI server (`app.py`) → FFmpeg
- `-ss` before `-i` makes FFmpeg seek with HTTP Range requests instead of reading from the start
- `-c copy` stream-copies (no re-encode; cuts snap to the nearest keyframe)
- A local proxy sits between FFmpeg and Google Drive. Drive returns an HTML "quota exceeded" page instead of bytes when a single Range is too large or requests arrive too fast, so the proxy requests small chunks, retries those pages with backoff, and stitches the chunks into one continuous stream with read-ahead
- Server auto-stops after 10 minutes idle; output files are cleaned up on start and after download

Logs: `logs/server.log`, rotated daily, kept 7 days. Look there first when something fails.

---

## Configuration (environment variables)

| Variable | Default | Description |
|---|---|---|
| `PORT` | `8000` | Server port |
| `IDLE_TIMEOUT` | `600` | Auto-shutdown after N seconds idle (0 = never) |
| `DRIVE_CHUNK_MB` | `50` | Size of each upstream request to Drive. Peak throughput on a real cut. 10–200 MB all work; past ~100 MB the seek-probe overhead outweighs the extra throughput |
| `DRIVE_PREFETCH` | `1` | Extra chunks fetched ahead while streaming. Higher = faster, but more likely to trip Drive's rate limit |

Set before starting: `DRIVE_CHUNK_MB=25 ./venv/bin/python app.py`

---

## Sharing

```bash
./build-release.sh     # → dist/Drive-Cutter-Mac-vX.Y.zip, dist/Drive-Cutter-Windows-vX.Y.zip
```

---

## Project layout

```
drive-cutter/
├── app.py                 FastAPI server: Drive/WeTransfer info, proxy, cut, download
├── requirements.txt       fastapi + uvicorn
├── install.sh / .bat      One-time setup
├── build-release.sh       Produces the zips in dist/
├── setup.md               This file
├── MISTAKES.md            Mistakes & learnings log — read before changing the proxy
├── extension/             Chrome MV3 extension (manifest, background, content, popup)
├── native-host/host.py    Starts the server on demand via native messaging
├── bin/ffmpeg             Static FFmpeg (created by install.sh, gitignored)
├── venv/                  Python env (created by install.sh, gitignored)
└── logs/                  Server logs (gitignored)
```
