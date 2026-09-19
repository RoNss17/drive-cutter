// Detect page type and extract file info
(function () {
  if (document.getElementById("drive-cutter-panel")) return;

  const pageUrl = window.location.href;
  let pageType = null;
  let fileId = null;

  // Google Drive: /file/d/{id}/view
  const driveMatch = pageUrl.match(/drive\.google\.com\/file\/d\/([a-zA-Z0-9_-]+)/);
  if (driveMatch) {
    pageType = "drive";
    fileId = driveMatch[1];
  }

  // WeTransfer: /previews/{id}/{hash} or /downloads/{id}/{hash}
  const wtMatch = pageUrl.match(
    /wetransfer\.com\/(previews|downloads)\/([a-f0-9]+)\/([a-f0-9]+)/
  );
  if (wtMatch) {
    pageType = "wetransfer";
  }

  if (!pageType) return;

  // API helper that goes through background service worker
  function api(path, options) {
    return new Promise((resolve, reject) => {
      chrome.runtime.sendMessage(
        { type: "api", path, options },
        (response) => {
          if (chrome.runtime.lastError) {
            reject(new Error(chrome.runtime.lastError.message));
            return;
          }
          resolve(response);
        }
      );
    });
  }

  // Build and inject the floating panel
  const panel = document.createElement("div");
  panel.id = "drive-cutter-panel";
  panel.innerHTML = `
    <div class="dc-header">
      <span class="dc-logo">Drive Cutter</span>
      <button class="dc-close" id="dc-close">×</button>
    </div>
    <div class="dc-body" id="dc-body">
      <div class="dc-status" id="dc-status">Connecting…</div>
    </div>
  `;
  document.body.appendChild(panel);

  // Make panel draggable
  let isDragging = false, dragX, dragY;
  const header = panel.querySelector(".dc-header");
  header.addEventListener("mousedown", (e) => {
    if (e.target.closest(".dc-close")) return;
    isDragging = true;
    dragX = e.clientX - panel.offsetLeft;
    dragY = e.clientY - panel.offsetTop;
    document.addEventListener("mousemove", onDrag);
    document.addEventListener("mouseup", () => {
      isDragging = false;
      document.removeEventListener("mousemove", onDrag);
    }, { once: true });
  });
  function onDrag(e) {
    if (!isDragging) return;
    panel.style.left = (e.clientX - dragX) + "px";
    panel.style.top = (e.clientY - dragY) + "px";
    panel.style.right = "auto";
    panel.style.bottom = "auto";
  }

  document.getElementById("dc-close").addEventListener("click", () => {
    panel.style.display = "none";
  });

  // State
  let state = {
    serverOk: false,
    file: null,
    wtContext: null,
    wtFiles: [],
    segments: [{ id: 1, start: "00:00:00", end: "", cutting: false, result: null, error: null }],
    segmentCounter: 1,
  };

  function esc(s) {
    const el = document.createElement("span");
    el.textContent = s || "";
    return el.innerHTML;
  }

  function findVideoInShadow(root) {
    const v = root.querySelector("video");
    if (v) return v;
    for (const el of root.querySelectorAll("*")) {
      if (el.shadowRoot) {
        const found = findVideoInShadow(el.shadowRoot);
        if (found) return found;
      }
    }
    return null;
  }

  function parseDriveTimeUI() {
    // Drive shows current time in player controls as text like "1:23:45 / 2:00:00"
    // Try to find and parse it as a last resort
    const allEls = document.querySelectorAll("*");
    for (const el of allEls) {
      const text = el.textContent?.trim();
      if (!text) continue;
      const m = text.match(/^(\d{1,2}:)?\d{1,2}:\d{2}\s*\/\s*(\d{1,2}:)?\d{1,2}:\d{2}$/);
      if (m) {
        const current = text.split("/")[0].trim();
        const parts = current.split(":").map(Number);
        if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
        if (parts.length === 2) return parts[0] * 60 + parts[1];
      }
    }
    return null;
  }

  function getVideoTimeAsync() {
    return new Promise((resolve) => {
      // Try direct access (including shadow DOM)
      const video = findVideoInShadow(document);
      if (video) { resolve(video.currentTime); return; }
      // Try Drive's time display UI
      const uiTime = parseDriveTimeUI();
      if (uiTime !== null) { resolve(uiTime); return; }
      // Ask background to check all frames via chrome.scripting
      chrome.runtime.sendMessage({ type: "get-video-time" }, (res) => {
        if (res?.time !== null && res?.time !== undefined) {
          resolve(res.time);
        } else {
          // Final fallback: try UI again after a tick
          setTimeout(() => resolve(parseDriveTimeUI()), 100);
        }
      });
    });
  }

  function formatTime(sec) {
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = Math.floor(sec % 60);
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }

  async function captureTime(segId, field) {
    const t = await getVideoTimeAsync();
    if (t !== null) {
      const seg = state.segments.find((s) => s.id == segId);
      if (seg) {
        seg[field] = formatTime(t);
        renderCutUI();
      }
    } else {
      const btn = document.querySelector(`.dc-capture[data-seg="${segId}"][data-field="${field}"]`);
      if (btn) {
        btn.style.borderColor = "#f06060";
        btn.title = "Play the video first";
        setTimeout(() => { btn.style.borderColor = ""; btn.title = "Capture playhead time"; }, 1500);
      }
    }
  }

  // Start server and load file info
  async function init() {
    const body = document.getElementById("dc-body");
    body.innerHTML = `<div class="dc-status">Starting server…</div>`;

    const serverResult = await new Promise((resolve) => {
      chrome.runtime.sendMessage({ type: "ensure-server" }, resolve);
    });

    if (!serverResult?.ok) {
      const errDetail = serverResult?.error ? `<div class="dc-status" style="font-size:10px;color:#888;word-break:break-word;">${esc(serverResult.error)}</div>` : "";
      body.innerHTML = `<div class="dc-status dc-error">Could not start server.</div>
        ${errDetail}
        <div class="dc-actions dc-actions-center">
          <button class="dc-btn dc-btn-retry" id="dc-retry">Retry</button>
        </div>`;
      document.getElementById("dc-retry").addEventListener("click", () => init());
      return;
    }
    state.serverOk = true;

    if (pageType === "drive") {
      await loadDriveFile();
    } else if (pageType === "wetransfer") {
      await loadWeTransfer();
    }
  }

  async function getDriveCookies() {
    return new Promise((resolve) => {
      chrome.runtime.sendMessage({ type: "get-drive-cookies" }, (res) => {
        resolve(res?.cookies || "");
      });
    });
  }

  async function loadDriveFile() {
    const body = document.getElementById("dc-body");
    body.innerHTML = `<div class="dc-status">Loading file info…</div>`;

    // Always use cookie auth from extension — user is signed in
    const cookies = await getDriveCookies();
    if (cookies) {
      const authRes = await api(`/drive/cookie-info/${fileId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cookies, ua: navigator.userAgent }),
      });
      if (authRes.ok) {
        state.file = authRes.data;
        state.file.accessMode = "cookie";
        state.file.cookies = cookies;
        renderCutUI();
        return;
      }
    }

    // Fallback: try public access (for shared files when no cookies)
    const res = await api(`/drive/public-info/${fileId}`);
    if (res.ok && res.data.size > 0) {
      state.file = res.data;
      state.file.accessMode = "public";
      renderCutUI();
      return;
    }

    body.innerHTML = `<div class="dc-status dc-error">Could not access file</div>`;
  }

  async function loadWeTransfer() {
    const body = document.getElementById("dc-body");
    body.innerHTML = `<div class="dc-status">Resolving transfer…</div>`;

    const res = await api("/wetransfer/resolve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: pageUrl }),
    });

    if (!res.ok) {
      body.innerHTML = `<div class="dc-status dc-error">Could not resolve WeTransfer link</div>`;
      return;
    }

    state.wtContext = {
      transfer_id: res.data.transfer_id,
      security_hash: res.data.security_hash,
      api_base: res.data.api_base,
      display_name: res.data.display_name,
    };
    state.wtFiles = res.data.files.map((f) => ({ ...f, source: "wetransfer" }));

    if (state.wtFiles.length === 1) {
      state.file = state.wtFiles[0];
      renderCutUI();
    } else {
      renderFileList();
    }
  }

  function renderFileList() {
    const body = document.getElementById("dc-body");
    const items = state.wtFiles
      .map(
        (f) =>
          `<div class="dc-file" data-id="${f.id}">
            <span class="dc-fname">${esc(f.name)}</span>
            <span class="dc-fsize">${esc(f.sizeFormatted)}</span>
          </div>`
      )
      .join("");
    body.innerHTML = `
      <div class="dc-label">${state.wtFiles.length} files in transfer</div>
      <div class="dc-files">${items}</div>
    `;
    body.querySelectorAll(".dc-file").forEach((el) => {
      el.addEventListener("click", () => {
        const id = el.dataset.id;
        state.file = state.wtFiles.find((f) => f.id === id);
        state.segments = [{ id: 1, start: "00:00:00", end: "", cutting: false, result: null, error: null }];
        state.segmentCounter = 1;
        renderCutUI();
      });
    });
  }

  function renderCutUI() {
    const body = document.getElementById("dc-body");
    const f = state.file;
    const segsHtml = state.segments
      .map((seg, i) => {
        if (seg.result) {
          return `<div class="dc-seg">
            <div class="dc-seg-head">Segment ${i + 1} · ${esc(seg.start)} → ${esc(seg.end)}</div>
            <a href="${seg.result.download_url}" target="_blank" class="dc-btn dc-btn-done">Download (${seg.result.sizeFormatted})</a>
          </div>`;
        }
        if (seg.cutting) {
          const pct = seg.progress?.percent;
          const eta = seg.progress?.etaFormatted;
          const fetched = seg.progress?.bytesFetched;
          const elapsed = seg.progress?.elapsedFormatted || "0s";
          const barClass = pct != null ? "dc-progress-fill dc-progress-real" : "dc-progress-fill";
          const barStyle = pct != null ? `style="width:${pct}%"` : "";
          const rightLine = fetched
            ? `${esc(fetched)} · ${esc(elapsed)}`
            : `${esc(elapsed)}`;
          return `<div class="dc-seg">
            <div class="dc-seg-head">Segment ${i + 1} · ${esc(seg.start)} → ${esc(seg.end)}</div>
            <div class="dc-cutting" data-seg-status="${seg.id}">Cutting…${eta ? " " + esc(eta) : ""}</div>
            <div class="dc-progress-bar"><div class="${barClass}" data-seg-fill="${seg.id}" ${barStyle}></div></div>
            <div class="dc-progress-size" data-seg="${seg.id}">${rightLine}</div>
            <button class="dc-btn dc-btn-stop" data-stop="${seg.id}">Stop</button>
          </div>`;
        }
        return `<div class="dc-seg">
          <div class="dc-seg-head">
            <span>${state.segments.length > 1 ? `Segment ${i + 1}` : "Time range"}</span>
            ${state.segments.length > 1 ? `<button class="dc-remove" data-seg="${seg.id}">×</button>` : ""}
          </div>
          <div class="dc-time-row">
            <div class="dc-time-field">
              <label>Start</label>
              <div class="dc-input-group">
                <input class="dc-input" data-seg="${seg.id}" data-field="start" placeholder="00:00:00" value="${esc(seg.start)}" />
                <button class="dc-capture" data-seg="${seg.id}" data-field="start" title="Capture playhead time">⏱</button>
              </div>
            </div>
            <div class="dc-time-field">
              <label>End</label>
              <div class="dc-input-group">
                <input class="dc-input" data-seg="${seg.id}" data-field="end" placeholder="00:01:00" value="${esc(seg.end)}" />
                <button class="dc-capture" data-seg="${seg.id}" data-field="end" title="Capture playhead time">⏱</button>
              </div>
            </div>
          </div>
          ${seg.error ? `<div class="dc-error">${esc(seg.error.message || seg.error)}</div>` : ""}
        </div>`;
      })
      .join("");

    const anyCutting = state.segments.some((s) => s.cutting);
    const uncutCount = state.segments.filter((s) => !s.result && !s.cutting).length;

    body.innerHTML = `
      <div class="dc-file-info">
        <div class="dc-fname">${esc(f.name)}</div>
        <div class="dc-fsize">${f.sizeFormatted || ""}</div>
        ${state.wtFiles.length > 1 ? `<button class="dc-btn dc-btn-sm dc-btn-back" id="dc-back">← Files</button>` : ""}
      </div>
      ${segsHtml}
      <div class="dc-actions">
        ${
          !anyCutting && uncutCount > 0
            ? `<button class="dc-btn dc-btn-cut" id="dc-cut">Cut${uncutCount > 1 ? ` ${uncutCount} segments` : ""}</button>`
            : ""
        }
        ${!anyCutting ? `<button class="dc-btn dc-btn-sm" id="dc-add">+ Segment</button>` : ""}
      </div>
    `;

    // Wire events
    body.querySelectorAll(".dc-input").forEach((input) => {
      input.addEventListener("input", (e) => {
        const seg = state.segments.find((s) => s.id == e.target.dataset.seg);
        if (seg) seg[e.target.dataset.field] = e.target.value;
      });
    });
    body.querySelectorAll(".dc-capture").forEach((btn) => {
      btn.addEventListener("click", () => {
        captureTime(btn.dataset.seg, btn.dataset.field);
      });
    });
    body.querySelectorAll(".dc-remove").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.segments = state.segments.filter((s) => s.id != btn.dataset.seg);
        renderCutUI();
      });
    });
    const cutBtn = document.getElementById("dc-cut");
    if (cutBtn) cutBtn.addEventListener("click", cutAll);
    body.querySelectorAll(".dc-btn-stop").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const segId = btn.dataset.stop;
        const seg = state.segments.find((s) => s.id == segId);
        if (!seg || !seg.progress?.cutId) return;
        btn.disabled = true;
        btn.textContent = "Stopping…";
        try {
          await api(`/cut/cancel?cut_id=${encodeURIComponent(seg.progress.cutId)}`, { method: "POST" });
        } catch {}
        seg.cutting = false;
        seg.progress = null;
        seg.error = { message: "Cancelled" };
        renderCutUI();
      });
    });
    const addBtn = document.getElementById("dc-add");
    if (addBtn)
      addBtn.addEventListener("click", () => {
        state.segmentCounter++;
        state.segments.push({ id: state.segmentCounter, start: "00:00:00", end: "", cutting: false, result: null, error: null });
        renderCutUI();
      });
    const backBtn = document.getElementById("dc-back");
    if (backBtn) backBtn.addEventListener("click", () => renderFileList());
  }

  async function cutOne(seg) {
    const f = state.file;
    const source = f.source || "drive_public";
    seg.cutting = true;
    seg.error = null;
    seg.progress = { startedAt: Date.now() };
    renderCutUI();

    try {
      let cutBody = {
        file_id: f.id,
        start_time: seg.start || "00:00:00",
        end_time: seg.end,
        filename: f.name.replace(/\.[^.]+$/, ""),
        file_size: f.size || 0,
        source,
        ua: navigator.userAgent,
      };

      if (source === "drive_public" && f.accessMode === "cookie" && f.cookies) {
        cutBody.source = "drive_cookie";
        cutBody.cookies = f.cookies;
      }

      if (source === "wetransfer" && state.wtContext) {
        const urlRes = await api("/wetransfer/download-url", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            transfer_id: state.wtContext.transfer_id,
            security_hash: state.wtContext.security_hash,
            api_base: state.wtContext.api_base,
            file_id: f.id,
          }),
        });
        if (!urlRes.ok) throw new Error("Failed to get download URL");
        cutBody.direct_url = urlRes.data.direct_link;
      }

      const cutId = Math.random().toString(36).slice(2, 10);
      cutBody.cut_id = cutId;
      // Expose the id so the Stop button can address this specific cut.
      seg.progress.cutId = cutId;

      // Fire the cut request (don't await yet — start polling progress)
      const cutPromise = api("/cut", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(cutBody),
      });

      // Two loops: a fast client-side tick for the elapsed timer, and a slower
      // server poll for the real percent + ETA + bytes-fetched. Both patch the
      // DOM in place so typing in another segment isn't interrupted.
      const fmtSecs = (s) => {
        s = Math.max(0, Math.round(s));
        if (s < 60) return `${s}s`;
        const m = Math.floor(s / 60);
        const r = s % 60;
        return r ? `${m}m ${r}s` : `${m}m`;
      };
      const paintDom = () => {
        const p = seg.progress;
        if (!p) return;
        const status = document.querySelector(`.dc-cutting[data-seg-status="${seg.id}"]`);
        const fill = document.querySelector(`.dc-progress-fill[data-seg-fill="${seg.id}"]`);
        const right = document.querySelector(`.dc-progress-size[data-seg="${seg.id}"]`);
        if (status) status.textContent = `Cutting…${p.etaFormatted ? " " + p.etaFormatted : ""}`;
        if (fill) {
          if (p.percent != null) {
            fill.classList.add("dc-progress-real");
            fill.style.width = p.percent + "%";
          }
        }
        if (right) {
          right.textContent = p.bytesFetched
            ? `${p.bytesFetched} · ${p.elapsedFormatted}`
            : p.elapsedFormatted;
        }
      };

      const tickInterval = setInterval(() => {
        if (!seg.progress) return;
        seg.progress.elapsedFormatted = fmtSecs((Date.now() - seg.progress.startedAt) / 1000);
        paintDom();
      }, 500);

      const pollInterval = setInterval(async () => {
        try {
          const prog = await api(`/cut/progress/${cutId}`);
          if (prog.ok && prog.data && seg.progress) {
            const d = prog.data;
            seg.progress.percent = d.percent;
            seg.progress.bytesFetched = d.bytes_fetched_formatted || "";
            seg.progress.etaFormatted = d.eta_seconds != null ? `~${fmtSecs(d.eta_seconds)}` : "";
            paintDom();
          }
        } catch {}
      }, 1000);

      const res = await cutPromise;
      clearInterval(pollInterval);
      clearInterval(tickInterval);

      if (res.ok && res.data.success) {
        seg.result = {
          ...res.data,
          download_url: `http://127.0.0.1:8000${res.data.download_url}`,
        };
      } else {
        const d = res.data || {};
        const msg = d.error || d.detail || d.message || JSON.stringify(d);
        const details = d.details || "";
        seg.error = { message: msg + (details ? "\n" + details : "") };
      }
    } catch (e) {
      seg.error = { message: e.message };
    }
    seg.cutting = false;
    seg.progress = null;
    renderCutUI();
  }

  async function cutAll() {
    const toCut = state.segments.filter((s) => !s.result && !s.cutting && s.end);
    if (toCut.length === 0) return;
    await Promise.all(toCut.map((seg) => cutOne(seg)));
  }

  init();
})();
