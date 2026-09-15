"""
Drive Cutter — Download only the segment you need from Google Drive videos.
Uses FFmpeg's HTTP Range request support to avoid downloading full files.
"""

import os
import re
import subprocess
import uuid
import tempfile
import time
import json as _json
import urllib.request
import urllib.error
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CLIENT_SECRETS_FILE = os.getenv("GOOGLE_CLIENT_SECRETS", "client_secret.json")
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))
REDIRECT_URI = os.getenv("REDIRECT_URI", f"http://localhost:{PORT}/oauth/callback")

OUTPUT_DIR = Path(tempfile.gettempdir()) / "drive-cutter-output"
OUTPUT_DIR.mkdir(exist_ok=True)

# Single-user session (local tool — not for production multi-user use)
session: dict = {}

app = FastAPI(title="Drive Cutter")
app.mount("/static", StaticFiles(directory="static"), name="static")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_creds() -> Credentials:
    if "credentials" not in session:
        raise HTTPException(401, "Not authenticated")
    return Credentials(**session["credentials"])


def _time_to_seconds(t: str) -> float:
    """Parse HH:MM:SS, MM:SS, or plain seconds into a float."""
    parts = str(t).strip().split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


def _seconds_to_hms(s: float) -> str:
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = s % 60
    return f"{h:02d}:{m:02d}:{sec:06.3f}"


def _format_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


DRIVE_PUBLIC_URL = (
    "https://drive.usercontent.google.com/download?id={}&export=download&confirm=t"
)


def _fetch_json(url, data=None):
    body = _json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return _json.loads(resp.read())


def _parse_wetransfer_url(url):
    m = re.match(
        r"https?://(?:([a-zA-Z0-9_-]+)\.)?wetransfer\.com/"
        r"(?:previews|downloads)/([a-f0-9]+)/([a-f0-9]+)",
        url,
    )
    if m:
        return m.group(2), m.group(3), m.group(1)
    return None, None, None


# ---------------------------------------------------------------------------
# Routes — Auth
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index():
    return Path("static/index.html").read_text()


@app.get("/auth/status")
async def auth_status():
    return {"authenticated": "credentials" in session}


@app.get("/auth/start")
async def auth_start():
    if not Path(CLIENT_SECRETS_FILE).exists():
        raise HTTPException(
            500,
            f"Missing {CLIENT_SECRETS_FILE}. Download it from Google Cloud Console → "
            "APIs & Services → Credentials → OAuth 2.0 Client IDs.",
        )
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, scopes=SCOPES, redirect_uri=REDIRECT_URI
    )
    auth_url, state = flow.authorization_url(
        access_type="offline", include_granted_scopes="true", prompt="consent"
    )
    session["oauth_state"] = state
    session["code_verifier"] = flow.code_verifier
    return {"auth_url": auth_url}


@app.get("/oauth/callback")
async def oauth_callback(request: Request):
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if not code:
        raise HTTPException(400, "Missing authorization code")

    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
        state=state,
        code_verifier=session.get("code_verifier"),
    )
    flow.fetch_token(code=code)
    creds = flow.credentials

    session["credentials"] = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or []),
    }
    return RedirectResponse("/?auth=success")


@app.post("/auth/logout")
async def logout():
    session.clear()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Routes — Drive
# ---------------------------------------------------------------------------
@app.get("/drive/search")
async def search_files(q: str = ""):
    creds = _get_creds()
    service = build("drive", "v3", credentials=creds, cache_discovery=False)

    query_parts = [
        "(mimeType contains 'video/' or mimeType = 'application/octet-stream')"
    ]
    if q.strip():
        safe_q = q.replace("'", "\\'")
        query_parts.append(f"name contains '{safe_q}'")
    query_parts.append("trashed = false")

    results = (
        service.files()
        .list(
            q=" and ".join(query_parts),
            spaces="drive",
            fields="files(id,name,size,mimeType,videoMediaMetadata,modifiedTime)",
            pageSize=30,
            orderBy="modifiedTime desc",
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
        )
        .execute()
    )
    files = results.get("files", [])

    # Attach human-readable sizes
    for f in files:
        if "size" in f:
            f["sizeFormatted"] = _format_bytes(int(f["size"]))
    return {"files": files}


@app.get("/drive/file/{file_id}")
async def file_detail(file_id: str):
    creds = _get_creds()
    service = build("drive", "v3", credentials=creds, cache_discovery=False)
    f = (
        service.files()
        .get(
            fileId=file_id,
            fields="id,name,size,mimeType,videoMediaMetadata,modifiedTime",
            supportsAllDrives=True,
        )
        .execute()
    )
    if "size" in f:
        f["sizeFormatted"] = _format_bytes(int(f["size"]))
    return f


# ---------------------------------------------------------------------------
# Routes — Drive (public, no auth)
# ---------------------------------------------------------------------------
@app.get("/drive/public-info/{file_id}")
async def drive_public_info(file_id: str):
    url = DRIVE_PUBLIC_URL.format(file_id)
    req = urllib.request.Request(url)
    req.add_header("Range", "bytes=0-0")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            cd = resp.headers.get("Content-Disposition", "")
            name = "video.mp4"
            if 'filename="' in cd:
                name = cd.split('filename="')[1].split('"')[0]
            cr = resp.headers.get("Content-Range", "")
            size = int(cr.split("/")[-1]) if "/" in cr else 0
            if size == 0:
                size = int(resp.headers.get("Content-Length", 0))
            mime = resp.headers.get("Content-Type", "video/mp4").split(";")[0]
    except (urllib.error.HTTPError, urllib.error.URLError):
        raise HTTPException(403, "File is not publicly accessible")
    return {
        "id": file_id,
        "name": name,
        "size": size,
        "sizeFormatted": _format_bytes(size),
        "mimeType": mime,
        "source": "drive_public",
    }


# ---------------------------------------------------------------------------
# Routes — WeTransfer
# ---------------------------------------------------------------------------
@app.post("/wetransfer/resolve")
async def wetransfer_resolve(request: Request):
    body = await request.json()
    wt_url = body.get("url", "")
    transfer_id, security_hash, subdomain = _parse_wetransfer_url(wt_url)
    if not transfer_id:
        raise HTTPException(400, "Could not parse WeTransfer URL")
    api_base = (
        f"https://{subdomain}.wetransfer.com" if subdomain else "https://wetransfer.com"
    )
    try:
        data = _fetch_json(
            f"{api_base}/api/v4/transfers/{transfer_id}/prepare-download",
            data={"security_hash": security_hash},
        )
    except Exception as e:
        raise HTTPException(502, f"WeTransfer API error: {e}")
    files = []
    for item in data.get("items", []):
        if item.get("item_type") == "file":
            files.append({
                "id": item["id"],
                "name": item["name"],
                "size": item["size"],
                "sizeFormatted": _format_bytes(item["size"]),
            })
    return {
        "transfer_id": transfer_id,
        "security_hash": security_hash,
        "api_base": api_base,
        "display_name": data.get("display_name", ""),
        "files": files,
    }


@app.post("/wetransfer/download-url")
async def wetransfer_download_url(request: Request):
    body = await request.json()
    api_base = body.get("api_base", "https://wetransfer.com")
    try:
        data = _fetch_json(
            f"{api_base}/api/v4/transfers/{body['transfer_id']}/download",
            data={
                "security_hash": body["security_hash"],
                "intent": "single_file",
                "file_ids": [body["file_id"]],
            },
        )
    except Exception as e:
        raise HTTPException(502, f"WeTransfer API error: {e}")
    return {"direct_link": data["direct_link"]}


# ---------------------------------------------------------------------------
# Routes — Cut
# ---------------------------------------------------------------------------
@app.post("/cut")
async def cut_video(request: Request):
    body = await request.json()
    source = body.get("source", "drive")

    file_id = body.get("file_id")
    start_time = body.get("start_time", "0")
    end_time = body.get("end_time")
    if not end_time:
        raise HTTPException(400, "end_time is required")

    start_sec = _time_to_seconds(start_time)
    end_sec = _time_to_seconds(end_time)
    duration = end_sec - start_sec
    if duration <= 0:
        raise HTTPException(400, "End time must be after start time")

    if source == "drive":
        creds = _get_creds()
        video_url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
        extra_headers = f"Authorization: Bearer {creds.token}\r\n"
    elif source == "drive_public":
        video_url = DRIVE_PUBLIC_URL.format(file_id)
        extra_headers = None
    elif source == "wetransfer":
        video_url = body.get("direct_url")
        if not video_url:
            raise HTTPException(400, "direct_url required for wetransfer source")
        extra_headers = None
    else:
        raise HTTPException(400, f"Unknown source: {source}")

    slug = body.get("filename", "cut").replace(" ", "_")
    out_name = f"{slug}_{uuid.uuid4().hex[:6]}.mp4"
    out_path = OUTPUT_DIR / out_name

    cmd = ["ffmpeg", "-hide_banner"]
    if extra_headers:
        cmd += ["-headers", extra_headers]
    cmd += [
        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "5",
        "-ss", _seconds_to_hms(start_sec),
        "-i", video_url,
        "-t", str(duration),
        "-c", "copy",
        "-movflags", "+faststart",
        "-avoid_negative_ts", "make_zero",
        "-y",
        str(out_path),
    ]

    t0 = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "FFmpeg timed out (10 min limit)")
    except FileNotFoundError:
        raise HTTPException(500, "FFmpeg not found. Install it: https://ffmpeg.org")

    elapsed = round(time.time() - t0, 1)

    if result.returncode != 0:
        err_tail = "\n".join(result.stderr.strip().splitlines()[-8:])
        return JSONResponse({"error": "FFmpeg failed", "details": err_tail}, status_code=500)

    if not out_path.exists() or out_path.stat().st_size == 0:
        return JSONResponse({"error": "Output file is empty"}, status_code=500)

    out_size = out_path.stat().st_size
    return {
        "success": True,
        "filename": out_name,
        "size": out_size,
        "sizeFormatted": _format_bytes(out_size),
        "elapsed": elapsed,
        "download_url": f"/download/{out_name}",
    }


@app.get("/download/{filename}")
async def download(filename: str):
    path = OUTPUT_DIR / filename
    if not path.exists():
        raise HTTPException(404, "File not found")
    return FileResponse(path, filename=filename, media_type="video/mp4")


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")  # allow http for local dev
    print(f"\n  Drive Cutter → http://localhost:{PORT}\n")
    uvicorn.run(app, host=HOST, port=PORT)
