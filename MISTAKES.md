# Drive Cutter — Mistakes & Learnings Log

A running log of mistakes made while building/debugging, and what we learned. Read this before making changes to avoid repeating them.

---

## 2026-09-18 — "Drive is rate-limiting the account" was wrong for half a day

**What broke:** Every cut across a 12-hour span returned Drive's `<title>Google Drive - Quota exceeded</title>` HTML page instead of bytes. `bytes=0-0` probes worked at 05:12; the same probe at 05:26 failed. Cuts that had worked the previous morning stopped working entirely.

**What I told the user:** "This is Google throttling bytes-per-account. It'll clear in a few hours. Meanwhile, no size experiment can run — every attempt is measuring the throttle, not the cap." I even suggested making a copy of the file, waiting 24 h, or switching accounts. The user kept saying they'd cut 24 clips the previous day without issue, and asked if the problem could be on our side. I doubled down on the throttle theory instead of listening.

**What it actually was:** Google silently deprecated the `confirm=t` shortcut on `drive.usercontent.google.com/download`. That shortcut used to bypass the "Google Drive can't scan this file for viruses" warning for large files. It now returns an HTML page with a `<form>` whose action URL carries a fresh `confirm` token and a `uuid` parameter — only *that* URL serves bytes. Our proxy was still using `confirm=t`, so every cut fetched the HTML warning page and FFmpeg saw "Invalid data".

The page title also happens to say "Quota exceeded" for some sub-types of the warning, which is what made me lock onto the wrong theory. When the user tested the URL directly in the browser they saw the *other* variant of the same page — "can't scan this file for viruses" with a "Download anyway" button — which was the clue that finally cracked it. That form is exactly what we needed to submit.

**Fix:** When the proxy sees `text/html` from Drive, parse the page for the `<form action>` URL plus its `<input name="confirm">` and `<input name="uuid">` values, then re-request the same Range against the form's action URL with those values as query parameters. Cache the resolved URL per proxy-registry entry so later chunks skip the parse. Same bypass in the cookie-info endpoint, so the panel gets the real filename and size instead of "video.mp4 · 2.5 KB" (the size of the HTML page). This is essentially what `gdown` does.

**Learnings:**
- **Trust the user's history harder than my own theory.** They said "I did 24 clips yesterday" three times before I stopped. Every time I heard it, my first instinct was to explain it away ("maybe the account budget was fresh yesterday"). It wasn't — I was wrong.
- **Google's page titles lie.** The virus-scan warning and the real quota-exceeded page share DOM ancestors and one variant is titled "Quota exceeded". Match on *body content* (`can't scan this file`, `Too many users`), not `<title>`, when classifying rejection pages.
- **When a "workaround" is a magic query param, check whether it still works, occasionally.** `confirm=t` was a one-line hack that had worked for years. Nothing in our tests would have caught its silent deprecation until real users hit it. This class of dependency deserves a note in the code: "if Drive stops serving bytes here, the bypass token format has changed — see [[drive-endpoint-limits]]." Added.
- **A definitive user-side test beats hours of server-side theorizing.** "Open this URL in your signed-in browser and tell me what page you see" took 30 seconds and answered the question the logs couldn't. That should have been step one, not step ten.
- **Two-page interpretations of the same HTML.** I looked at the raw response body four times over the day and never noticed the class of page had changed. Log the response's `<title>` and the first 200 chars of `<body>` on every HTML error, not just the first 8 KB of raw markup — much easier to eyeball.

---

## 2026-09-17 — "10 MB is safe" was only half the story

**What we found:** After reverting to 10 MB chunks and getting a successful cut, the log showed Drive returned the *same* "Quota exceeded" HTML on the last chunk of that successful cut — at 10 MB. The cut only survived because FFmpeg already had enough bytes.

**So the endpoint has two limits, not one:** a per-request size cap (500 MB fails cold, 10 MB passes) **and** a request-rate limit that can fire at any size when requests come fast. Parallel cuts double the request rate.

**What we did:** The proxy now retries HTML responses with exponential backoff (4 attempts) instead of failing the cut, and stitches 10 MB upstream chunks into one continuous stream with read-ahead so FFmpeg never reconnects per chunk. Chunk size and read-ahead depth are env vars (`DRIVE_CHUNK_MB`, `DRIVE_PREFETCH`) so they can be tuned without a code change. FFmpeg also gets `-reconnect_on_http_error 4xx,5xx`.

**Learnings:**
- A "fix confirmed by one successful run" is not confirmed. Read the log of the *successful* run too — the failure mode was still there.
- When a third party has an undocumented limit, make the knob configurable and default it to the known-good value. Don't hardcode a guess.
- Read-ahead must be lazy: FFmpeg's seek probes open a stream, read a few KB, and disconnect. Prefetching for those burns requests against the rate limit for nothing. Only start reading ahead once the client has consumed a full chunk.

---

## 2026-09-17 — Streaming responses don't notice when FFmpeg hangs up

**What we found:** Testing the new stitched proxy against a fake Drive, the big streams never logged "closed". A client that read 5 MB and disconnected left the server coroutine stuck forever. With the old per-chunk design this was invisible (each request was capped at 10 MB, so the waste was bounded); with stitching it would have meant downloading the rest of a 10 GB file after every cut — and burning Drive's rate limit doing it.

**Cause (three layers, found one at a time):**
1. uvicorn's `send()` silently returns after a disconnect instead of raising, and Starlette ≥ 1.x on ASGI spec 2.4 no longer runs a disconnect listener alongside `StreamingResponse`. Nothing tells the generator the client left, and with the socket's read side paused the peer's close isn't even observed.
2. Polling `request.is_disconnected()` before each yield fixed that — except when the generator was parked waiting on an upstream fetch. A side watchdog task fixed that.
3. Still one straggler per parallel run, closing 2–195 s late. A task-stack dump (`/debug/tasks`) showed *no* coroutine parked in our code: the generator had been abandoned. `@app.middleware("http")` is `BaseHTTPMiddleware`, which wraps streaming responses in a task group and cancels the app on disconnect — the consumer dies at `await send()` while our generator sits at `yield`, so its `finally` only runs when the GC finalizes it.

**Fix:** Plain ASGI middleware instead of `BaseHTTPMiddleware`; `is_disconnected()` polled before each yield; a watchdog task that both notices the disconnect while we wait on upstream *and* runs the cleanup itself, so cleanup never depends on the consumer.

**Learnings:**
- "The output file is correct" is not the same as "the server is healthy." Check that every stream you open is logged as closed. A local fake upstream + a client that hangs up early is a 10-line test worth keeping.
- Framework guarantees drift between versions. Verify disconnect handling empirically whenever a long-lived response depends on it.

---

## 2026-09-17 — Two copies of the repo

**What we did:** Kept the git repo in `~/Downloads/drive-cutter` and a second copy in `~/drive-cutter` for Chrome (because Downloads is TCC-restricted), and manually `cp`'d files between them after every change.

**What it cost:** 2–4 extra commands per change all session, plus a standing risk that one copy drifts and we debug the wrong one. `dist/` and `Shareables/` were also hand-made snapshots and went stale the same day.

**Fix:** `~/drive-cutter` is the only checkout. Release zips come from `build-release.sh`, `dist/` is gitignored, `Shareables/` is gone.

**Learnings:**
- If a workaround makes you copy files by hand, the workaround is the bug. Move the source of truth instead.
- Anything a human has to regenerate by hand will be stale when it matters. Script it.

---

## 2026-09-17 — Chunk size "optimization" broke everything

**What we did:** Went from the original 10 MB proxy chunk size → single-request streaming (using `file_size` or 10 GB fallback as the end byte) → then 500 MB chunks. The goal was speed (4 MB/s → 28 MB/s).

**What broke:** Every cut on any Drive file failed with `Invalid data found when processing input`. Server logs revealed Drive was returning a 2009-byte HTML page (`<title>Google Drive - Quota exceeded</title>`) instead of video data.

**Wrong theory chased:** Assumed it was a real Google Drive daily download quota that would need 24 h to reset. Suggested the user "make a copy" or "wait 24 h." User pushed back: "I downloaded 24 clips previously non-stop and they didn't seem to give me an issue." That was the crucial data point — a real quota would not have let 24 clips through and then flipped mid-session.

**Actual cause:** Drive's `usercontent.google.com/download` endpoint returns the "Quota exceeded" HTML page as a generic rejection when the requested Range is too large. It has nothing to do with account/file quotas. The original 10 MB chunk size worked because it stayed under this threshold. 500 MB is over it.

**Fix:** Reverted to 10 MB chunks in the proxy.

**Learnings:**
- Google's error pages are misleading. "Quota exceeded" from Drive can mean "your request shape is wrong," not "you're rate-limited." Read the response body, but don't trust its natural-language message.
- Verify a hypothesis against the user's lived experience before recommending they wait 24 h or change their workflow. If they say "this used to work," trust that data point.
- **Always check `git log` and `git show <prev-commit>:file` for the last known-working version before assuming a new approach must be right.** The original had a specific 10 MB cap for a reason.
- Chunk-size "optimizations" against a third-party API need to be validated against that API's actual behavior, not just theorized. There is no free lunch — Drive imposes a per-request cap and we have to respect it.
- When benchmarking (4 MB/s → 28 MB/s), test with the actual target file sizes the user has, not just small test files.

---

## 2026-09-17 — ffprobe pre-probe broke cuts

**What we did:** Added an ffprobe pre-probe step in the cut endpoint to get the total video duration, so the progress bar could show accurate percentages.

**What broke:** ffprobe would connect to the proxy first, which opened a connection to Drive. Then FFmpeg would try to connect too, opening a second connection. This introduced timing and connection-lifecycle bugs.

**Fix:** Removed the pre-probe. Progress bar now shows current output file size but no percentage.

**Learnings:**
- Adding an extra network round-trip through a proxy that streams from a third party doubles the failure surface. If the third party has any rate limiting or session state, a "harmless" probe request will interact with it.
- Progress UX doesn't need a percentage. Showing the growing file size is enough feedback for most users.
- Don't add features that require the same fragile external endpoint to serve two independent clients concurrently.

---

## 2026-09-17 — HTML retry logic made errors worse, not better

**What we did:** Added a "retry with confirmation token" path in the proxy when Drive returned an HTML page. Tried to scrape `confirm=...` and `uuid=...` values out of the HTML.

**What broke:** The retry hit the same rejection, and now the error the user saw was `502 Bad Gateway` instead of the original (also-wrong) `Invalid data found`. We were papering over a symptom without knowing the root cause.

**Fix:** Reverted the retry logic. Kept the HTML detection so we can *log* what Drive sends, but don't try to work around it — the actual fix was elsewhere (chunk size).

**Learnings:**
- If you don't know why an upstream is returning HTML, adding scraping/retry logic is a guess, not a fix. First **capture and log the HTML body** so you can read what the server is actually saying.
- The debug logging that captured the HTML page contents (`<title>Google Drive - Quota exceeded</title>`) is what actually solved this. Diagnostics first, then fixes.
- A 502 that hides the real error is worse than the original error. Only convert an upstream error to a nicer one after you've verified the conversion doesn't lose information.

---

## 2026-09-17 — Synchronous urlopen inside async handler deadlocked the server

**What we did:** The original proxy used `urllib.request.urlopen()` directly inside an `async def` handler.

**What broke:** For long-running streaming requests (large video files), the sync call blocked FastAPI's event loop. FFmpeg's subsequent Range requests couldn't be served because the loop was stuck. Cutting hung at 0% CPU.

**Fix:** Wrapped the call in `await asyncio.to_thread(urllib.request.urlopen, req, None, 60)`.

**Learnings:**
- **Never call a blocking I/O function directly inside an `async def` handler.** Even if it "works" for small responses, it will deadlock for long ones.
- Standard library `urllib` is sync-only. In async code use `httpx` or wrap with `asyncio.to_thread`.
- Symptoms of an event-loop deadlock: everything hangs, CPU is idle, no timeout fires until a request-level timeout hits. Not "slow" — completely stuck.

---

## 2026-09-17 — Chrome native messaging: extension ID mismatches

**What we did:** Updated the manifest.json `key` field to pin the extension ID, but left the old extension ID in `com.drivecutter.host.json`'s `allowed_origins`.

**What broke:** On fresh Chrome start, "Could not start server" — Chrome refused to launch the native host because it didn't recognize the new extension ID.

**Fix:** Added both IDs to `allowed_origins`. Long-term: pick one ID via the pinned `key` and stop supporting the old one.

**Learnings:**
- The extension ID is derived from the public `key` in manifest.json. Pinning `key` gives a stable ID.
- Native messaging manifests must list every allowed extension ID; a mismatch fails silently as "Native host has exited."
- Keep `allowed_origins` in sync with the current manifest key whenever the key changes.

---

## 2026-09-17 — macOS quarantine attribute blocked native host launch

**What we did:** Installed the app by unzipping a downloaded archive into a project folder.

**What broke:** macOS applied `com.apple.quarantine` extended attribute to all files. Chrome refused to execute the native host script.

**Fix:** `xattr -r -d com.apple.quarantine <project>`. Added this to `install.sh`.

**Learnings:**
- Anything downloaded (including archives extracted from downloads) inherits quarantine on macOS. Installers must clear it explicitly.
- Debug clue: `xattr -l <file>` lists extended attributes.

---

## 2026-09-17 — Downloads folder is TCC-restricted; Chrome loses access on restart

**What we did:** Kept the unpacked extension inside `~/Downloads/drive-cutter/`.

**What broke:** Chrome's access to the folder got revoked on every restart, so the extension was silently unloaded on `Cmd+Q`.

**Fix:** Moved the project to `~/drive-cutter/`. Kept a synced git-tracked copy in `~/Downloads/drive-cutter/`.

**Learnings:**
- macOS TCC treats `~/Downloads`, `~/Desktop`, and `~/Documents` as protected. Long-lived apps that reference files there will lose permission across launches.
- Ship extensions/native hosts from `~/` or an app-specific dir like `~/Library/Application Support/`.

---

## 2026-09-17 — Chrome launches native hosts with a minimal PATH

**What we did:** Called `ffmpeg` by name in `subprocess.exec`, assuming Homebrew's `/opt/homebrew/bin` was in PATH.

**What broke:** When the server was launched by Chrome (via native messaging), PATH didn't include `/opt/homebrew/bin`, so `ffmpeg` wasn't found.

**Fix:** Prepend `/opt/homebrew/bin` and `/usr/local/bin` to `os.environ["PATH"]` at server startup. Also use `shutil.which("ffmpeg")` to resolve to an absolute path once.

**Learnings:**
- Any subprocess launched by Chrome (or a plist-launched daemon on macOS) starts with a stripped PATH.
- Resolve binary paths at startup with `shutil.which(...)`, don't rely on inherited PATH.

---

## General patterns / meta-lessons

- **Diagnostics before fixes.** When a bug shows up, add logging that captures the actual response body / error / state *before* changing behavior. Every "fix" we shipped without capturing the HTML body was wrong.
- **Trust the user's history.** When they say "this used to work," treat that as ground truth and look for what changed on our side, not for reasons their environment is different now.
- **Compare against last known good.** `git show <prev-commit>:<file>` is faster than re-reasoning about what the code should do.
- **Optimizations require validation against real inputs.** A 7× speed number from a synthetic test doesn't mean the same optimization works on the real workload.
- **Don't chain fixes to hide errors.** If a 500 becomes a 502 and the user still sees a wall of red, we made it worse. Only replace an error message when we're sure the replacement is *more* accurate.
- **Async/sync boundary.** Any I/O in an async handler must be actually async, or explicitly offloaded with `asyncio.to_thread`. This bug will always look like "hangs at random" and is worth checking first when a FastAPI server misbehaves.
