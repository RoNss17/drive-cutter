const SERVER = "http://127.0.0.1:8000";
const NATIVE_HOST = "com.drivecutter.host";

let serverReady = null; // null = unknown, true/false

async function checkServer() {
  try {
    const res = await fetch(`${SERVER}/health`, { signal: AbortSignal.timeout(2000) });
    if (res.ok) { serverReady = true; return true; }
  } catch {}
  serverReady = false;
  return false;
}

let lastNativeError = "";

function tryNativeHost() {
  return new Promise((resolve) => {
    let port;
    try {
      port = chrome.runtime.connectNative(NATIVE_HOST);
    } catch (e) {
      lastNativeError = e.message || "connectNative threw";
      resolve(false);
      return;
    }

    let settled = false;
    const timeout = setTimeout(() => {
      if (!settled) { settled = true; lastNativeError = "Timeout (15s)"; resolve(false); }
    }, 15000);

    port.onMessage.addListener((msg) => {
      if (msg.status === "started" && !settled) {
        settled = true;
        clearTimeout(timeout);
        serverReady = true;
        resolve(true);
      }
    });

    port.onDisconnect.addListener(() => {
      if (!settled) {
        settled = true;
        clearTimeout(timeout);
        lastNativeError = chrome.runtime.lastError?.message || "Native host disconnected";
        resolve(false);
      }
    });
  });
}

async function ensureServer() {
  if (await checkServer()) return true;

  for (let attempt = 0; attempt < 2; attempt++) {
    const ok = await tryNativeHost();
    if (ok) return true;
    if (attempt === 0) await new Promise((r) => setTimeout(r, 1000));
  }
  return false;
}

async function proxyRequest(path, options = {}) {
  const url = `${SERVER}${path}`;
  const res = await fetch(url, options);
  const data = await res.json();
  return { ok: res.ok, status: res.status, data };
}

// Listen for messages from content scripts and popup
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "get-drive-cookies") {
    // Exactly what the browser itself would send to drive.usercontent.google.com —
    // no name filter, so newer session cookies (__Secure-*PSIDTS, *PSIDCC) are included.
    const hosts = new Set([
      "google.com", ".google.com",
      "usercontent.google.com", ".usercontent.google.com",
      "drive.usercontent.google.com", ".drive.usercontent.google.com",
    ]);
    chrome.cookies.getAll({ domain: ".google.com" }, (cookies) => {
      const relevant = cookies
        .filter((c) => hosts.has(c.domain))
        .map((c) => `${c.name}=${c.value}`)
        .join("; ");
      sendResponse({ cookies: relevant });
    });
    return true;
  }

  if (msg.type === "get-video-time") {
    const tabId = sender.tab?.id;
    if (!tabId) { sendResponse({ time: null }); return true; }
    chrome.scripting.executeScript({
      target: { tabId, allFrames: true },
      func: () => {
        // Check normal DOM
        let v = document.querySelector("video");
        if (v) return v.currentTime;
        // Traverse shadow DOMs recursively
        function findVideo(root) {
          const video = root.querySelector("video");
          if (video) return video;
          const els = root.querySelectorAll("*");
          for (const el of els) {
            if (el.shadowRoot) {
              const found = findVideo(el.shadowRoot);
              if (found) return found;
            }
          }
          return null;
        }
        v = findVideo(document);
        return v ? v.currentTime : null;
      },
    }).then((results) => {
      const found = results?.find((r) => r.result !== null && r.result !== undefined);
      sendResponse({ time: found ? found.result : null });
    }).catch(() => {
      sendResponse({ time: null });
    });
    return true;
  }
  if (msg.type === "check-server") {
    checkServer().then((ok) => sendResponse({ ok }));
    return true;
  }

  if (msg.type === "ensure-server") {
    ensureServer().then((ok) => sendResponse({ ok, error: ok ? null : lastNativeError }));
    return true;
  }

  if (msg.type === "api") {
    (async () => {
      try {
        if (!serverReady) {
          const ok = await ensureServer();
          if (!ok) {
            sendResponse({ ok: false, data: { error: "Could not start server" } });
            return;
          }
        }
        const result = await proxyRequest(msg.path, msg.options || {});
        sendResponse(result);
      } catch (e) {
        sendResponse({ ok: false, data: { error: e.message } });
      }
    })();
    return true;
  }
});
