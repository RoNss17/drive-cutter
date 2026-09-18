"""
Drive Cutter — Cut segments from Google Drive / WeTransfer videos.
Uses FFmpeg HTTP Range requests — only downloads the bytes you need.
"""

import asyncio
import logging
import logging.handlers
import os
import re
import shutil
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

from collections import deque
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# ---------------------------------------------------------------------------
# Logging — daily rotation, 7-day retention
# ---------------------------------------------------------------------------
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

log = logging.getLogger("drivecutter")
log.setLevel(logging.DEBUG)

_file_handler = logging.handlers.TimedRotatingFileHandler(
    LOG_DIR / "server.log", when="midnight", backupCount=7, encoding="utf-8",
)
_file_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S",
))
_console_handler = logging.StreamHandler()
_console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
_console_handler.setLevel(logging.INFO)
log.addHandler(_file_handler)
log.addHandler(_console_handler)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))
IDLE_TIMEOUT = int(os.getenv("IDLE_TIMEOUT", "600"))  # seconds, 0 = disabled

OUTPUT_DIR = Path(tempfile.gettempdir()) / "drive-cutter-output"
OUTPUT_DIR.mkdir(exist_ok=True)

# Clean up old output files on startup
_cleaned = 0
for _old in OUTPUT_DIR.glob("*.mp4"):
    try:
        _old.unlink()
        _cleaned += 1
    except OSError:
        pass
if _cleaned:
    log.info("Startup cleanup: removed %d old output file(s)", _cleaned)

# Ensure Homebrew paths are available (Chrome launches with a minimal PATH)
for p in ["/opt/homebrew/bin", "/usr/local/bin"]:
    if p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = p + ":" + os.environ.get("PATH", "")

_BUNDLED_FFMPEG = Path(__file__).parent / "bin" / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
FFMPEG = str(_BUNDLED_FFMPEG) if _BUNDLED_FFMPEG.exists() else (shutil.which("ffmpeg") or "ffmpeg")
log.info("FFmpeg: %s", FFMPEG)
log.info("Output dir: %s", OUTPUT_DIR)

# Drive's download endpoint answers with an HTML "quota exceeded" page instead of
# bytes when a single Range is too large (500 MB fails cold) and sometimes when
# requests arrive too fast (seen at 10 MB). Keep upstream requests small and let
# the proxy stitch them into one continuous stream for FFmpeg.
DRIVE_CHUNK = int(os.getenv("DRIVE_CHUNK_MB", "10")) * 1024 * 1024
DRIVE_PREFETCH = max(0, int(os.getenv("DRIVE_PREFETCH", "1")))  # extra chunks in flight
DRIVE_HTML_RETRIES = 4

DRIVE_PUBLIC_URL = (
    "https://drive.usercontent.google.com/download?id={}&export=download&confirm=t"
)


@asynccontextmanager
async def _lifespan(_app):
    if IDLE_TIMEOUT > 0:
        _check_idle()
    yield


app = FastAPI(title="Drive Cutter", lifespan=_lifespan)

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
        log.info("Idle for %ds — shutting down", IDLE_TIMEOUT)
        os.kill(os.getpid(), signal.SIGTERM)
    else:
        remaining = IDLE_TIMEOUT - idle
        global _idle_timer
        _idle_timer = threading.Timer(remaining + 1, _check_idle)
        _idle_timer.daemon = True
        _idle_timer.start()


class _ActivityMiddleware:
    # Plain ASGI on purpose: @app.middleware("http") is BaseHTTPMiddleware, which
    # cancels the app on client disconnect and leaves streaming generators un-closed.
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            _touch()
        await self.app(scope, receive, send)


app.add_middleware(_ActivityMiddleware)


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
    return {"status": "ok", "version": "2.1"}


@app.get("/")
async def index():
    return {"app": "Drive Cutter", "status": "running",
            "hint": "Open a Google Drive or WeTransfer video page with the Chrome extension installed."}


@app.get("/debug/tasks")
async def debug_tasks():
    """Where is every coroutine parked right now? For diagnosing stuck streams."""
    out = []
    for task in asyncio.all_tasks():
        frames = task.get_stack(limit=6)
        out.append({
            "name": task.get_name(),
            "done": task.done(),
            "stack": [f"{f.f_code.co_name} ({Path(f.f_code.co_filename).name}:{f.f_lineno})" for f in frames],
        })
    return {"count": len(out), "tasks": out}


# ---------------------------------------------------------------------------
# Routes — Drive (public, no auth)
# ---------------------------------------------------------------------------
@app.get("/drive/public-info/{file_id}")
async def drive_public_info(file_id: str):
    log.info("Public info request: file_id=%s", file_id)
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
    except (urllib.error.HTTPError, urllib.error.URLError) as e:
        log.warning("Public info failed for %s: %s", file_id, e)
        raise HTTPException(403, "File is not publicly accessible")
    log.info("Public info OK: name=%s size=%s mime=%s", name, _format_bytes(size), mime)
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
    ua = body.get("ua", "")
    log.info("Cookie info request: file_id=%s cookies_len=%d ua=%s", file_id, len(cookies), ua[:40])
    url = DRIVE_COOKIE_URL.format(file_id)

    def probe(u: str):
        req = _drive_request(u, cookies, "bytes=0-0", ua)
        return urllib.request.urlopen(req, None, 30)

    try:
        resp = probe(url)
        # Drive's virus-scan warning: parse the form, retry against the bypass URL
        if "text/html" in resp.headers.get("Content-Type", ""):
            resp.close()
            resolved = _resolve_download_url(url, cookies, ua)
            if resolved == url:
                raise HTTPException(403, "Drive returned a warning page and no bypass form was found — file may be quota-limited")
            log.info("Cookie info: resolved via virus-scan bypass")
            url = resolved  # use resolved URL for the eventual proxy stream too
            resp = probe(resolved)
        with resp:
            log.debug("Cookie info response: url=%s ct=%s cr=%s", resp.url, resp.headers.get("Content-Type"), resp.headers.get("Content-Range"))
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
        log.error("Cookie auth failed for %s: %s", file_id, e)
        raise HTTPException(403, f"Cookie auth failed: {e}")
    if "text/html" in mime:
        log.warning("Cookie info still HTML after resolve for %s", file_id)
        raise HTTPException(403, "Drive returned a web page instead of video data — the bypass form has changed shape")
    if size == 0:
        log.warning("Cookie info returned size=0 for %s — cookies may be stale", file_id)
        raise HTTPException(403, "Could not determine file size — cookies may be invalid")
    log.info("Cookie info OK: name=%s size=%s mime=%s", name, _format_bytes(size), mime)
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
        log.warning("Could not parse WeTransfer URL: %s", wt_url[:100])
        raise HTTPException(400, "Could not parse WeTransfer URL")
    log.info("WeTransfer resolve: transfer_id=%s subdomain=%s", transfer_id, subdomain)
    api_base = (
        f"https://{subdomain}.wetransfer.com" if subdomain else "https://wetransfer.com"
    )
    try:
        data = _fetch_json(
            f"{api_base}/api/v4/transfers/{transfer_id}/prepare-download",
            data={"security_hash": security_hash},
        )
    except Exception as e:
        log.error("WeTransfer resolve failed: %s", e)
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
    log.info("WeTransfer resolved: %d file(s), display_name=%s", len(files), data.get("display_name"))
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
    log.info("WeTransfer download-url: transfer_id=%s file_id=%s", body.get("transfer_id"), body.get("file_id"))
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
        log.error("WeTransfer download-url failed: %s", e)
        raise HTTPException(502, f"WeTransfer API error: {e}")
    log.info("WeTransfer download-url OK")
    return {"direct_link": data["direct_link"]}


# ---------------------------------------------------------------------------
# Routes — Drive proxy (FFmpeg can't follow Google's redirects)
# ---------------------------------------------------------------------------
_proxy_registry: dict[str, dict] = {}
_cut_progress: dict[str, dict] = {}  # cut_id -> {path, estimated_size, done}


@app.post("/proxy/register")
async def proxy_register(request: Request):
    body = await request.json()
    token = uuid.uuid4().hex
    _proxy_registry[token] = {
        "url": body["url"],
        "cookies": body.get("cookies", ""),
        "created": time.time(),
    }
    log.info("Proxy registered: token=%s..%s url=%s", token[:8], token[-4:], body["url"][:80])
    return {"token": token, "proxy_url": f"http://127.0.0.1:{PORT}/proxy/stream/{token}"}


class _DriveHTMLError(Exception):
    def __init__(self, kind: str, body: str):
        super().__init__(kind)
        self.kind = kind
        self.body = body


DEFAULT_UA = "Mozilla/5.0"


def _drive_request(url: str, cookies: str, range_header: str, ua: str = "") -> urllib.request.Request:
    """A request shaped like the browser's own download request."""
    req = urllib.request.Request(url)
    if cookies:
        req.add_header("Cookie", cookies)
    req.add_header("Range", range_header)
    req.add_header("User-Agent", ua or DEFAULT_UA)
    req.add_header("Accept", "*/*")
    req.add_header("Accept-Language", "en-US,en;q=0.9")
    req.add_header("Referer", "https://drive.google.com/")
    return req


def _resolve_download_url(url: str, cookies: str, ua: str) -> str:
    """When Drive returns its "can't scan for viruses" warning page instead of
    bytes, the page contains a <form> whose action URL carries a fresh `confirm`
    token and a `uuid`. Post the form (or GET the action with its inputs) and
    Drive starts serving the file. `confirm=t` alone stopped working somewhere
    in 2024; this replaces it. Returns the URL that actually serves bytes.
    Cached per registry entry so subsequent chunks skip the round-trip.
    """
    req = _drive_request(url, cookies, "bytes=0-", ua)
    resp = urllib.request.urlopen(req, None, 30)
    ct = resp.headers.get("Content-Type", "")
    if "text/html" not in ct:
        resp.close()
        return url  # Drive is willing to serve directly — no bypass needed
    html = resp.read(65536).decode(errors="replace")
    resp.close()

    # The warning page's form looks like:
    #   <form action="https://drive.usercontent.google.com/download">
    #     <input name="id" value="…"><input name="export" value="download">
    #     <input name="confirm" value="…"><input name="uuid" value="…">
    action = re.search(r'<form[^>]+action="([^"]+)"', html)
    inputs = dict(re.findall(r'<input[^>]+name="([^"]+)"[^>]+value="([^"]+)"', html))
    if action and inputs.get("confirm"):
        base = action.group(1).replace("&amp;", "&")
        qs = urllib.parse.urlencode(inputs)
        return f"{base}?{qs}" if "?" not in base else f"{base}&{qs}"
    # Some variants (older page) put the whole retry URL in an <a href="/uc?…confirm=…">
    href = re.search(r'href="(/uc\?[^"]*confirm=[^"]*)"', html)
    if href:
        return "https://drive.google.com" + href.group(1).replace("&amp;", "&")
    return url  # unknown page shape — let the caller see the HTML


def _fetch_range(url: str, cookies: str, start: int, end: int, ua: str = "", entry: dict | None = None):
    """Fetch bytes [start, end] from upstream in one request.

    If Drive answers with its HTML warning page, resolve a new download URL
    (parses the page's confirm/uuid token) and retry once. The resolved URL is
    cached on `entry` so later chunks skip the parse. Anything still returning
    HTML after that is treated as a genuine rejection and retried with backoff.
    """
    delay = 1.0
    for attempt in range(1, DRIVE_HTML_RETRIES + 1):
        effective = (entry.get("resolved_url") if entry else None) or url
        req = _drive_request(effective, cookies, f"bytes={start}-{end}", ua)
        resp = urllib.request.urlopen(req, None, 30)
        ct = resp.headers.get("Content-Type", "")
        if "text/html" not in ct:
            # Never read more than asked, even if the server ignored Range and sent 200
            data = resp.read(end - start + 1)
            cr = resp.headers.get("Content-Range", "")
            resp.close()
            tail = cr.split("/")[-1] if "/" in cr else ""
            total = int(tail) if tail.isdigit() else 0
            return data, total, ct
        body = resp.read(8192).decode(errors="replace")
        resp.close()
        kind = ("rate-limit" if "Quota exceeded" in body or "Too many users" in body
                else "virus-scan" if "can't scan this file" in body or "too large for Google to scan" in body
                else "html")
        # Once per stream: on the first virus-scan page, resolve the real download URL
        # by parsing the form's confirm+uuid, then retry the same range against it.
        if kind == "virus-scan" and entry is not None and not entry.get("resolved_url"):
            resolved = _resolve_download_url(url, cookies, ua)
            if resolved != url:
                entry["resolved_url"] = resolved
                log.info("Resolved Drive download URL via virus-scan bypass (confirm+uuid)")
                continue  # retry same range immediately, no backoff
        if attempt == DRIVE_HTML_RETRIES:
            log.error("Drive %s page persisted after %d attempts for bytes=%d-%d:\n%s",
                      kind, attempt, start, end, body[:600])
            raise _DriveHTMLError(kind, body)
        log.warning("Drive returned %s page for bytes=%d-%d (attempt %d/%d) — retrying in %.0fs",
                    kind, start, end, attempt, DRIVE_HTML_RETRIES, delay)
        time.sleep(delay)
        delay *= 2


def _html_error_message(err: _DriveHTMLError) -> str:
    if err.kind == "rate-limit":
        return ("Google Drive is rate-limiting this file (it reports 'quota exceeded'). "
                "Wait a few minutes and try again. If it keeps happening, make a copy of "
                "the file in your Drive (right-click → Make a copy) and cut from the copy.")
    if err.kind == "virus-scan":
        return ("Google Drive's virus-scan warning page was returned and the bypass form "
                "could not be parsed — the page shape may have changed. Check server logs.")
    return f"Google Drive returned a web page instead of video data: {err.body[:200]!r}"


@app.get("/proxy/stream/{token}")
async def proxy_stream(token: str, request: Request):
    entry = _proxy_registry.get(token)
    if not entry:
        log.warning("Proxy stream: unknown token %s", token[:12])
        raise HTTPException(404, "Unknown proxy token")

    url = entry["url"]
    cookies = entry["cookies"]
    ua = entry.get("ua", "")
    total = entry.get("size", 0) or 0

    range_header = request.headers.get("range", "")
    m_full = re.match(r"bytes=(\d+)-(\d+)$", range_header)
    m_open = re.match(r"bytes=(\d+)-$", range_header)
    if m_full:
        start, stop = int(m_full.group(1)), int(m_full.group(2))
    elif m_open:
        start, stop = int(m_open.group(1)), None
    else:
        start, stop = 0, None

    if total and start >= total:
        raise HTTPException(416, "Range not satisfiable")

    first_end = start + DRIVE_CHUNK - 1
    if stop is not None:
        first_end = min(first_end, stop)
    if total:
        first_end = min(first_end, total - 1)

    t0 = time.time()
    log.debug("Proxy stream request: bytes=%d-%s (first chunk %d-%d)", start, stop if stop is not None else "", start, first_end)
    try:
        first, learned_total, content_type = await asyncio.to_thread(
            _fetch_range, url, cookies, start, first_end, ua, entry
        )
    except urllib.error.HTTPError as e:
        log.error("Proxy upstream HTTP error: %d %s url=%s", e.code, e.reason, url[:80])
        raise HTTPException(e.code if e.code in (403, 404, 416) else 502, f"Upstream error: {e.reason}")
    except urllib.error.URLError as e:
        log.error("Proxy upstream URL error: %s url=%s", e.reason, url[:80])
        raise HTTPException(502, f"Upstream error: {e.reason}")
    except _DriveHTMLError as e:
        raise HTTPException(502, _html_error_message(e))

    if not total and learned_total:
        total = learned_total
        entry["size"] = total
    if stop is None:
        stop = (total - 1) if total else (start + len(first) - 1)
    elif total:
        stop = min(stop, total - 1)
    length = stop - start + 1

    headers = {"Accept-Ranges": "bytes", "Content-Length": str(length)}
    if total:
        headers["Content-Range"] = f"bytes {start}-{stop}/{total}"
    status = 206 if total else 200
    log.info("Proxy stream open: bytes=%d-%d/%s (%s) chunk=%s prefetch=%d",
             start, stop, total or "?", _format_bytes(length), _format_bytes(DRIVE_CHUNK), DRIVE_PREFETCH)

    async def gen():
        sent = 0
        chunks = 1
        pending: deque = deque()
        next_start = first_end + 1
        gone = asyncio.Event()
        closed = False

        def close(note: str):
            nonlocal closed
            if closed:
                return
            closed = True
            gone.set()
            for f in pending:
                f.cancel()
            elapsed = time.time() - t0
            rate = (sent / 1048576 / elapsed) if elapsed > 0 else 0.0
            log.info("Proxy stream closed: %s in %d chunk(s), %.1fs, %.1f MB/s%s",
                     _format_bytes(sent), chunks, elapsed, rate, note)

        # uvicorn silently drops sends after a disconnect and Starlette no longer
        # cancels the stream, so nothing tells us the client left. Poll for it from
        # a side task: it notices even while we're parked on an upstream fetch, and
        # it runs the cleanup itself in case the consumer abandons this generator
        # without closing it (then our own `finally` only runs at GC time).
        # (is_disconnected() also resumes the socket's read side, which is what
        # lets the peer's close be observed at all.)
        async def watchdog():
            while not gone.is_set():
                if await request.is_disconnected():
                    log.debug("Proxy stream: client gone after %.1fs (watchdog)", time.time() - t0)
                    close(" (client stopped early)")
                    return
                await asyncio.sleep(0.5)

        watch = asyncio.ensure_future(watchdog())
        gone_wait = asyncio.ensure_future(gone.wait())

        def schedule():
            nonlocal next_start
            while len(pending) <= DRIVE_PREFETCH and next_start <= stop:
                s, e = next_start, min(next_start + DRIVE_CHUNK - 1, stop)
                pending.append(asyncio.ensure_future(asyncio.to_thread(_fetch_range, url, cookies, s, e, ua, entry)))
                next_start = e + 1

        buf = first
        try:
            while True:
                for i in range(0, len(buf), 256 * 1024):
                    if gone.is_set() or await request.is_disconnected():
                        return
                    piece = buf[i:i + 256 * 1024]
                    sent += len(piece)
                    yield piece
                if next_start > stop and not pending:
                    break
                # Read-ahead starts only after the client has taken a whole chunk:
                # FFmpeg's seek probes read a few KB and disconnect, and prefetching
                # for those would just burn requests against Drive's rate limit.
                schedule()
                fut = pending.popleft()
                schedule()
                done, _ = await asyncio.wait({fut, gone_wait}, return_when=asyncio.FIRST_COMPLETED)
                if fut not in done:
                    log.debug("Proxy stream: abandoning upstream wait, client gone")
                    return
                try:
                    buf, _, _ = fut.result()
                    chunks += 1
                except Exception as e:
                    # Drop the connection; FFmpeg's -reconnect resumes from its own offset.
                    log.error("Upstream chunk failed mid-stream at %s: %s", _format_bytes(start + sent), e)
                    return
        finally:
            close("" if sent >= length else " (client stopped early)")
            watch.cancel()
            gone_wait.cancel()

    return StreamingResponse(gen(), status_code=status, media_type=content_type or "video/mp4", headers=headers)


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

    log.info("Cut request: source=%s file_id=%s range=%s→%s (%.1fs) file_size=%s",
             source, file_id, start_time, end_time, duration, _format_bytes(body.get("file_size", 0)))

    proxy_token = None
    file_size = body.get("file_size", 0)
    if source == "drive_public":
        upstream_url = DRIVE_PUBLIC_URL.format(file_id)
        token = uuid.uuid4().hex
        _proxy_registry[token] = {
            "url": upstream_url,
            "cookies": "",
            "ua": body.get("ua", ""),
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
            "ua": body.get("ua", ""),
            "size": file_size,
            "created": time.time(),
        }
        video_url = f"http://127.0.0.1:{PORT}/proxy/stream/{token}"
        proxy_token = token
        log.debug("Cut using cookie auth, cookies_len=%d", len(cookies))
    elif source == "wetransfer":
        video_url = body.get("direct_url")
        if not video_url:
            raise HTTPException(400, "direct_url required for wetransfer source")
        log.debug("Cut using WeTransfer direct URL")
    else:
        raise HTTPException(400, f"Unknown source: {source}")

    slug = body.get("filename", "cut").replace(" ", "_").replace("/", "_").replace("\\", "_")
    cut_id = body.get("cut_id") or uuid.uuid4().hex[:8]
    out_name = f"{slug}_{cut_id}.mp4"
    out_path = OUTPUT_DIR / out_name

    _cut_progress[cut_id] = {"path": str(out_path), "estimated_size": 0, "done": False}

    cmd = [FFMPEG, "-hide_banner"]
    cmd += [
        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_on_http_error", "4xx,5xx",
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

    log.debug("FFmpeg cmd: %s", " ".join(cmd))
    t0 = time.time()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        log.info("FFmpeg started: pid=%d cut_id=%s", proc.pid, cut_id)
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)
        except asyncio.TimeoutError:
            log.error("FFmpeg timed out after 600s: cut_id=%s pid=%d", cut_id, proc.pid)
            proc.kill()
            raise HTTPException(504, "FFmpeg timed out (10 min limit)")
        returncode = proc.returncode
        stderr_text = stderr.decode(errors="replace")
    except FileNotFoundError:
        log.error("FFmpeg binary not found at: %s", FFMPEG)
        raise HTTPException(500, "FFmpeg not found. Install it: https://ffmpeg.org")
    finally:
        if proxy_token:
            _proxy_registry.pop(proxy_token, None)
        _cut_progress[cut_id]["done"] = True

    elapsed = round(time.time() - t0, 1)

    if returncode != 0:
        _cut_progress.pop(cut_id, None)
        err_tail = "\n".join(stderr_text.strip().splitlines()[-8:])
        log.error("FFmpeg failed (exit %d) cut_id=%s elapsed=%.1fs:\n%s", returncode, cut_id, elapsed, err_tail)
        return JSONResponse({"error": "FFmpeg failed", "details": err_tail}, status_code=500)

    if not out_path.exists() or out_path.stat().st_size == 0:
        _cut_progress.pop(cut_id, None)
        log.error("FFmpeg produced empty output: cut_id=%s path=%s", cut_id, out_path)
        return JSONResponse({"error": "Output file is empty"}, status_code=500)

    out_size = out_path.stat().st_size
    log.info("Cut complete: cut_id=%s size=%s elapsed=%.1fs output=%s", cut_id, _format_bytes(out_size), elapsed, out_name)
    return {
        "success": True,
        "filename": out_name,
        "size": out_size,
        "sizeFormatted": _format_bytes(out_size),
        "elapsed": elapsed,
        "download_url": f"/download/{out_name}",
        "cut_id": cut_id,
    }


@app.get("/cut/progress/{cut_id}")
async def cut_progress(cut_id: str):
    entry = _cut_progress.get(cut_id)
    if not entry:
        raise HTTPException(404, "Unknown cut")
    current_size = 0
    try:
        p = Path(entry["path"])
        if p.exists():
            current_size = p.stat().st_size
    except OSError:
        pass
    pct = 0
    if entry["estimated_size"] > 0:
        pct = min(99, int(100 * current_size / entry["estimated_size"]))
    if entry["done"]:
        pct = 100
    return {"cut_id": cut_id, "current_size": current_size, "estimated_size": entry["estimated_size"],
            "percent": pct, "done": entry["done"],
            "currentFormatted": _format_bytes(current_size)}


@app.get("/download/{filename}")
async def download(filename: str):
    path = OUTPUT_DIR / filename
    if not path.exists():
        log.warning("Download not found: %s", filename)
        raise HTTPException(404, "File not found")

    log.info("Download served: %s (%s)", filename, _format_bytes(path.stat().st_size))

    async def cleanup():
        await asyncio.sleep(5)
        try:
            path.unlink()
            log.debug("Auto-deleted: %s", filename)
        except OSError:
            pass
        for cid, entry in list(_cut_progress.items()):
            if entry["path"] == str(path):
                _cut_progress.pop(cid, None)

    response = FileResponse(path, filename=filename, media_type="video/mp4")
    asyncio.get_event_loop().create_task(cleanup())
    return response


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    log.info("Starting Drive Cutter on http://localhost:%d", PORT)
    print(f"\n  Drive Cutter → http://localhost:{PORT}")
    print(f"  Logs → {LOG_DIR / 'server.log'}")
    if IDLE_TIMEOUT > 0:
        print(f"  Auto-shutdown after {IDLE_TIMEOUT}s idle\n")
    else:
        print()
    uvicorn.run(app, host=HOST, port=PORT)
