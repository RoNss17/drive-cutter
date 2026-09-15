"""
Drive Cutter — Cut segments from Google Drive / WeTransfer videos.
Uses FFmpeg HTTP Range requests — only downloads the bytes you need.
"""

import asyncio
import os
import re
import uuid
import tempfile
import time
import json as _json
import signal
import threading
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))
IDLE_TIMEOUT = int(os.getenv("IDLE_TIMEOUT", "600"))  # seconds, 0 = disabled

OUTPUT_DIR = Path(tempfile.gettempdir()) / "drive-cutter-output"
OUTPUT_DIR.mkdir(exist_ok=True)

DRIVE_PUBLIC_URL = (
    "https://drive.usercontent.google.com/download?id={}&export=download&confirm=t"
)

app = FastAPI(title="Drive Cutter")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "chrome-extension://*",
        "http://localhost:*",
        "http://127.0.0.1:*",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

static_dir = Path(__file__).parent / "static"
if static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# ---------------------------------------------------------------------------
# Idle shutdown
# ---------------------------------------------------------------------------
_last_activity = time.time()
_idle_timer: threading.Timer | None = None


def _touch():
    global _last_activity
    _last_activity = time.time()


def _check_idle():
    if IDLE_TIMEOUT <= 0:
        return
    idle = time.time() - _last_activity
    if idle >= IDLE_TIMEOUT:
        print(f"\n  Idle for {IDLE_TIMEOUT}s — shutting down.\n")
        os.kill(os.getpid(), signal.SIGTERM)
    else:
        remaining = IDLE_TIMEOUT - idle
        global _idle_timer
        _idle_timer = threading.Timer(remaining + 1, _check_idle)
        _idle_timer.daemon = True
        _idle_timer.start()


@app.middleware("http")
async def activity_tracker(request: Request, call_next):
    _touch()
    return await call_next(request)


@app.on_event("startup")
async def _start_idle_watcher():
    if IDLE_TIMEOUT > 0:
        _check_idle()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _time_to_seconds(t: str) -> float:
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
# Routes — Health
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok", "version": "2.0"}


@app.get("/", response_class=HTMLResponse)
async def index():
    html = Path(__file__).parent / "static" / "index.html"
    if html.exists():
        return html.read_text()
    return "<h1>Drive Cutter</h1><p>Server running. Use the browser extension.</p>"


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
# Routes — Drive (cookie-authenticated, via extension)
# ---------------------------------------------------------------------------
DRIVE_COOKIE_URL = DRIVE_PUBLIC_URL


@app.post("/drive/cookie-info/{file_id}")
async def drive_cookie_info(file_id: str, request: Request):
    body = await request.json()
    cookies = body.get("cookies", "")
    url = DRIVE_COOKIE_URL.format(file_id)
    req = urllib.request.Request(url)
    req.add_header("Range", "bytes=0-0")
    req.add_header("Cookie", cookies)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            cd = resp.headers.get("Content-Disposition", "")
            name = "video.mp4"
            if 'filename="' in cd:
                name = cd.split('filename="')[1].split('"')[0]
            elif "filename*=" in cd:
                name = cd.split("filename*=")[1].split("''")[-1].strip()
                name = urllib.parse.unquote(name)
            cr = resp.headers.get("Content-Range", "")
            size = int(cr.split("/")[-1]) if "/" in cr else 0
            if size == 0:
                size = int(resp.headers.get("Content-Length", 0))
            mime = resp.headers.get("Content-Type", "video/mp4").split(";")[0]
    except (urllib.error.HTTPError, urllib.error.URLError) as e:
        raise HTTPException(403, f"Cookie auth failed: {e}")
    if size == 0:
        raise HTTPException(403, "Could not determine file size — cookies may be invalid")
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
# Routes — Drive proxy (FFmpeg can't follow Google's redirects)
# ---------------------------------------------------------------------------
_proxy_registry: dict[str, dict] = {}


@app.post("/proxy/register")
async def proxy_register(request: Request):
    body = await request.json()
    token = uuid.uuid4().hex
    _proxy_registry[token] = {
        "url": body["url"],
        "cookies": body.get("cookies", ""),
        "created": time.time(),
    }
    return {"token": token, "proxy_url": f"http://127.0.0.1:{PORT}/proxy/stream/{token}"}


@app.get("/proxy/stream/{token}")
async def proxy_stream(token: str, request: Request):
    entry = _proxy_registry.get(token)
    if not entry:
        raise HTTPException(404, "Unknown proxy token")

    url = entry["url"]
    cookies = entry["cookies"]
    total_size = entry.get("size", 0)

    req = urllib.request.Request(url)
    if cookies:
        req.add_header("Cookie", cookies)

    range_header = request.headers.get("range")
    if range_header:
        # Google Drive rejects open-ended Range (bytes=0-) with an HTML page.
        # Rewrite to a concrete end byte so Drive returns actual video bytes.
        m = re.match(r"bytes=(\d+)-$", range_header)
        if m:
            start = int(m.group(1))
            end = start + 10 * 1024 * 1024 - 1  # 10 MB chunk
            if total_size > 0:
                end = min(end, total_size - 1)
            range_header = f"bytes={start}-{end}"
        req.add_header("Range", range_header)
    else:
        # No Range at all — also gets HTML from Drive. Send a concrete range.
        end = 10 * 1024 * 1024 - 1
        if total_size > 0:
            end = min(end, total_size - 1)
        req.add_header("Range", f"bytes=0-{end}")

    req.add_header("User-Agent", "Mozilla/5.0")

    try:
        resp = urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as e:
        raise HTTPException(e.code, f"Upstream error: {e.reason}")

    content_type = resp.headers.get("Content-Type", "video/mp4")
    content_length = resp.headers.get("Content-Length")
    content_range = resp.headers.get("Content-Range")
    status = 206 if content_range else 200

    headers = {}
    if content_length:
        headers["Content-Length"] = content_length
    if content_range:
        headers["Content-Range"] = content_range
    headers["Accept-Ranges"] = "bytes"

    def stream():
        try:
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            resp.close()

    return StreamingResponse(stream(), status_code=status, media_type=content_type, headers=headers)


# ---------------------------------------------------------------------------
# Routes — Cut
# ---------------------------------------------------------------------------
@app.post("/cut")
async def cut_video(request: Request):
    body = await request.json()
    source = body.get("source", "drive_public")

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

    proxy_token = None
    file_size = body.get("file_size", 0)
    if source == "drive_public":
        upstream_url = DRIVE_PUBLIC_URL.format(file_id)
        token = uuid.uuid4().hex
        _proxy_registry[token] = {
            "url": upstream_url,
            "cookies": "",
            "size": file_size,
            "created": time.time(),
        }
        video_url = f"http://127.0.0.1:{PORT}/proxy/stream/{token}"
        proxy_token = token
    elif source == "drive_cookie":
        upstream_url = DRIVE_COOKIE_URL.format(file_id)
        cookies = body.get("cookies", "")
        token = uuid.uuid4().hex
        _proxy_registry[token] = {
            "url": upstream_url,
            "cookies": cookies,
            "size": file_size,
            "created": time.time(),
        }
        video_url = f"http://127.0.0.1:{PORT}/proxy/stream/{token}"
        proxy_token = token
    elif source == "wetransfer":
        video_url = body.get("direct_url")
        if not video_url:
            raise HTTPException(400, "direct_url required for wetransfer source")
    else:
        raise HTTPException(400, f"Unknown source: {source}")

    slug = body.get("filename", "cut").replace(" ", "_").replace("/", "_").replace("\\", "_")
    out_name = f"{slug}_{uuid.uuid4().hex[:6]}.mp4"
    out_path = OUTPUT_DIR / out_name

    cmd = ["ffmpeg", "-hide_banner"]
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
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)
        except asyncio.TimeoutError:
            proc.kill()
            raise HTTPException(504, "FFmpeg timed out (10 min limit)")
        returncode = proc.returncode
        stderr_text = stderr.decode(errors="replace")
    except FileNotFoundError:
        raise HTTPException(500, "FFmpeg not found. Install it: https://ffmpeg.org")
    finally:
        if proxy_token:
            _proxy_registry.pop(proxy_token, None)

    elapsed = round(time.time() - t0, 1)

    if returncode != 0:
        err_tail = "\n".join(stderr_text.strip().splitlines()[-8:])
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
    print(f"\n  Drive Cutter → http://localhost:{PORT}")
    if IDLE_TIMEOUT > 0:
        print(f"  Auto-shutdown after {IDLE_TIMEOUT}s idle\n")
    else:
        print()
    uvicorn.run(app, host=HOST, port=PORT)
