const SERVER = "http://127.0.0.1:8000";

const dot = document.getElementById("dot");
const statusText = document.getElementById("status-text");
const main = document.getElementById("main");
const offline = document.getElementById("offline");
const startBtn = document.getElementById("start-btn");
const urlInput = document.getElementById("url");
const badgeRow = document.getElementById("badge-row");
const actionRow = document.getElementById("action-row");
const progressRow = document.getElementById("progress-row");

const PLATFORMS = [
  { name: "drive",      re: /^https?:\/\/drive\.google\.com\/file\/d\//,                          flow: "cut-page" },
  { name: "wetransfer", re: /^https?:\/\/(.+\.)?wetransfer\.com\/(previews|downloads)\//,          flow: "cut-page" },
  { name: "pinterest",  re: /^https?:\/\/([a-z]+\.)?pinterest\.[a-z.]+\/pin\//,                    flow: "download" },
  { name: "x",          re: /^https?:\/\/(x|twitter)\.com\/[^/]+\/status\//,                       flow: "download" },
  { name: "youtube",    re: /^https?:\/\/((www\.|m\.)?youtube\.com\/(watch|shorts\/|live\/)|youtu\.be\/)/, flow: "download" },
];

function detectPlatform(url) {
  if (!url) return null;
  const trimmed = url.trim();
  for (const p of PLATFORMS) if (p.re.test(trimmed)) return p;
  return null;
}

let currentPoll = null;
let currentTick = null;
let currentDlId = null;

function clearIntervals() {
  if (currentPoll) { clearInterval(currentPoll); currentPoll = null; }
  if (currentTick) { clearInterval(currentTick); currentTick = null; }
}

function fmtSecs(s) {
  s = Math.max(0, Math.round(s));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60), r = s % 60;
  return r ? `${m}m ${r}s` : `${m}m`;
}

function setStatus(on) {
  dot.className = "dot " + (on ? "on" : "off");
  statusText.textContent = on ? "Server running" : "Server not running";
  main.style.display    = on ? "block" : "none";
  offline.style.display = on ? "none"  : "block";
}

function renderPlatform() {
  const p = detectPlatform(urlInput.value);
  badgeRow.innerHTML = "";
  actionRow.innerHTML = "";
  progressRow.innerHTML = "";

  if (!urlInput.value.trim()) return;

  if (!p) {
    badgeRow.innerHTML = `<span class="platform-badge unsupported">unsupported</span>`;
    return;
  }
  badgeRow.innerHTML = `<span class="platform-badge">${p.name}</span>`;

  if (p.flow === "cut-page") {
    actionRow.innerHTML = `
      <button class="btn" id="open-tab">Open on page to cut →</button>
      <div class="hint" style="margin-top:6px;">
        ${p.name === "drive" ? "Drive" : "WeTransfer"} cutting uses the on-page panel so you can capture playhead times.
      </div>`;
    document.getElementById("open-tab").addEventListener("click", () => {
      chrome.tabs.create({ url: urlInput.value.trim() });
      window.close();
    });
  } else {
    actionRow.innerHTML = `<button class="btn" id="go">Download Video</button>`;
    document.getElementById("go").addEventListener("click", () => startDownload(p.name));
  }
}

async function startDownload(platform) {
  const url = urlInput.value.trim();
  clearIntervals();
  actionRow.innerHTML = `<button class="btn stop" id="stop">Stop</button>`;
  progressRow.innerHTML = `
    <div class="progress-bar"><div class="progress-fill"></div></div>
    <div class="progress-note" id="note">starting…</div>`;
  document.getElementById("stop").addEventListener("click", stopDownload);

  const note = document.getElementById("note");
  const startedAt = Date.now();

  let res;
  try {
    res = await fetch(`${SERVER}/dl/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, platform }),
    }).then((r) => r.json());
  } catch (e) {
    showError("Could not reach the Clipr server.");
    return;
  }
  if (!res.dl_id) {
    showError(res.detail || res.error || "Could not start download.");
    return;
  }
  currentDlId = res.dl_id;

  currentTick = setInterval(() => {
    note.textContent = `${note.dataset.size || "0.0 B"} · ${fmtSecs((Date.now() - startedAt) / 1000)}`;
  }, 500);

  currentPoll = setInterval(async () => {
    let p;
    try {
      p = await fetch(`${SERVER}/dl/progress/${currentDlId}`).then((r) => r.json());
    } catch { return; }
    note.dataset.size = p.currentFormatted || "0.0 B";
    if (p.done) {
      clearIntervals();
      if (p.error) {
        showError(p.error);
      } else if (p.download_url) {
        progressRow.innerHTML = "";
        actionRow.innerHTML = `
          <a class="btn done" href="${SERVER}${p.download_url}" download>
            Download (${p.sizeFormatted || ""})
          </a>
          <button class="btn secondary" id="new-dl" style="margin-top:6px;">New download</button>`;
        document.getElementById("new-dl").addEventListener("click", renderPlatform);
      } else {
        showError("Download finished but no file was produced.");
      }
    }
  }, 1000);
}

async function stopDownload() {
  if (currentDlId) {
    try { await fetch(`${SERVER}/dl/cancel?dl_id=${encodeURIComponent(currentDlId)}`, { method: "POST" }); }
    catch {}
  }
  clearIntervals();
  showError("Cancelled.");
}

function showError(msg) {
  clearIntervals();
  progressRow.innerHTML = `<div class="error">${msg}</div>`;
  actionRow.innerHTML = `<button class="btn secondary" id="retry">Try again</button>`;
  document.getElementById("retry").addEventListener("click", renderPlatform);
}

// ----- init -----
async function checkServerAndInit() {
  let ok = false;
  try {
    const r = await fetch(`${SERVER}/health`, { signal: AbortSignal.timeout(2000) });
    ok = r.ok;
  } catch {}
  setStatus(ok);
  if (!ok) return;

  // Pre-fill with the active tab's URL if it looks like a supported one
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab?.url && detectPlatform(tab.url)) {
      urlInput.value = tab.url;
    }
  } catch {}
  renderPlatform();
  urlInput.focus();
  urlInput.select();
}

urlInput.addEventListener("input", renderPlatform);
urlInput.addEventListener("keydown", (e) => {
  if (e.key !== "Enter") return;
  const p = detectPlatform(urlInput.value);
  if (p?.flow === "download") startDownload(p.name);
  if (p?.flow === "cut-page") document.getElementById("open-tab")?.click();
});

startBtn.addEventListener("click", () => {
  startBtn.disabled = true;
  startBtn.textContent = "Starting…";
  chrome.runtime.sendMessage({ type: "ensure-server" }, (res) => {
    if (res?.ok) checkServerAndInit();
    else {
      startBtn.disabled = false;
      startBtn.textContent = "Start Server";
      statusText.textContent = "Failed — run install.sh first";
    }
  });
});

checkServerAndInit();
