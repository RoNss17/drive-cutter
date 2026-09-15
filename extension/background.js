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

async function ensureServer() {
  if (await checkServer()) return true;

  return new Promise((resolve) => {
    let port;
    try {
      port = chrome.runtime.connectNative(NATIVE_HOST);
    } catch {
      resolve(false);
      return;
    }

    let settled = false;
    const timeout = setTimeout(() => {
      if (!settled) { settled = true; resolve(false); }
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
        resolve(false);
      }
    });
  });
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
    chrome.cookies.getAll({ domain: ".google.com" }, (cookies) => {
      const relevant = cookies
        .filter((c) => c.name.startsWith("SID") || c.name.startsWith("HSID") ||
                       c.name.startsWith("SSID") || c.name === "NID" ||
                       c.name.startsWith("SAPISID") || c.name.startsWith("APISID") ||
                       c.name === "__Secure-1PSID" || c.name === "__Secure-3PSID" ||
                       c.name === "__Secure-1PAPISID" || c.name === "__Secure-3PAPISID")
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
    ensureServer().then((ok) => sendResponse({ ok }));
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
