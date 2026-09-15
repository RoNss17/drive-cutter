# Drive Cutter

Cut segments from Google Drive videos without downloading the full file.

Uses FFmpeg's HTTP Range request support to fetch only the bytes for your selected time range — so pulling 2 minutes from a 4-hour timeline downloads ~2% of the file, not 100%.

---

## Prerequisites

- **Python 3.9+**
- **FFmpeg** installed and on your PATH
  - macOS: `brew install ffmpeg`
  - Ubuntu/Debian: `sudo apt install ffmpeg`
  - Windows: download from [ffmpeg.org](https://ffmpeg.org/download.html) and add to PATH
- A **Google Cloud project** with the Drive API enabled

---

## Setup (one-time, ~5 minutes)

### 1. Google Cloud credentials

You need an OAuth 2.0 Client ID so the app can read your Drive files.

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or pick an existing one)
3. **Enable the Google Drive API:**
   - Go to APIs & Services → Library
   - Search "Google Drive API" → Enable
4. **Configure the OAuth consent screen:**
   - APIs & Services → OAuth consent screen
   - User type: External (or Internal if using Workspace)
   - Fill in the app name (anything — "Drive Cutter" works)
   - Add your email as a test user
   - Scopes: add `drive.readonly`
5. **Create credentials:**
   - APIs & Services → Credentials → Create Credentials → OAuth Client ID
   - Application type: **Web application**
   - Authorized redirect URI: `http://localhost:8000/oauth/callback`
   - Download the JSON file
6. **Rename** the downloaded file to `client_secret.json` and put it in the `drive-cutter/` folder (same directory as `app.py`)

### 2. Install dependencies

```bash
cd drive-cutter
pip install -r requirements.txt
```

### 3. Run

```bash
python app.py
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

Click **Connect Drive**, sign in with Google, and you're in.

---

## Usage

1. **Search** for a video file by name (or hit Enter with an empty search to list recent videos)
2. **Select** a file from the list
3. **Set the time range** — start and end times in `HH:MM:SS` format
4. **Cut & download** — the server runs FFmpeg, which Range-requests only the needed bytes from Drive, stream-copies them into a new MP4, and hands you the file

---

## How it works under the hood

The core FFmpeg command looks like this:

```
ffmpeg \
  -headers "Authorization: Bearer TOKEN\r\n" \
  -ss 00:45:00 \
  -i "https://www.googleapis.com/drive/v3/files/FILE_ID?alt=media" \
  -t 120 \
  -c copy \
  -movflags +faststart \
  output.mp4
```

Key details:

- **`-ss` before `-i`** tells FFmpeg to do input-level seeking. It estimates the byte offset for your timestamp and sends an HTTP Range request for that position — it does not download from the beginning.
- **`-c copy`** stream-copies the video and audio without re-encoding. Fast and lossless, but cuts are aligned to the nearest keyframe (typically within 0.5–2 seconds of your requested time).
- **`-movflags +faststart`** moves the moov atom to the front of the output file so the clip plays instantly without buffering.
- The `-headers` flag passes your OAuth token so Google Drive accepts the partial download request.

### What about the moov atom?

If the source file on Drive has its moov atom at the end (common with files not optimized for streaming), FFmpeg will first fetch the tail of the file to read the index, then jump to your segment. This is two Range requests instead of one — still far less data than a full download.

For fastest cuts, make sure footage is uploaded with `faststart` (moov atom at the beginning). You can fix existing files before upload:

```
ffmpeg -i input.mp4 -c copy -movflags +faststart input_fixed.mp4
```

### Keyframe alignment

With `-c copy`, cuts snap to the nearest keyframe boundary. For most H.264/H.265 footage, keyframes are every 0.5–2 seconds, so your clip might be slightly longer than the exact range you entered.

If you need frame-accurate cuts, you'd swap `-c copy` for re-encoding (e.g., `-c:v libx264 -c:a aac`), which is slower but precise. The app currently uses stream copy for speed.

---

## Configuration

Environment variables (all optional):

| Variable | Default | Description |
|---|---|---|
| `GOOGLE_CLIENT_SECRETS` | `client_secret.json` | Path to your OAuth credentials file |
| `HOST` | `127.0.0.1` | Server bind address |
| `PORT` | `8000` | Server port |
| `REDIRECT_URI` | `http://localhost:8000/oauth/callback` | Must match your Google Cloud credential config |

---

## Limitations

- **Single-user local tool.** Session state is stored in memory, not in a database. This is designed to run on your machine, not as a multi-user web service.
- **Token expiration.** Google OAuth tokens expire after about an hour. If a cut fails with a 401, click Disconnect and reconnect.
- **File size limits.** Google Drive API has bandwidth quotas. For very large files or frequent use, watch your Drive API quota in the Cloud Console.
- **Codec support.** Stream copy works with any codec FFmpeg supports. If the source uses an unusual container format, the output might need a different extension.
