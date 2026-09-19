const dot = document.getElementById("dot");
const statusText = document.getElementById("status-text");
const startBtn = document.getElementById("start-btn");
const stopBtn = document.getElementById("stop-btn");
const note = document.getElementById("cancel-note");

function setStatus(on) {
  dot.className = "dot " + (on ? "on" : "off");
  statusText.textContent = on ? "Server running" : "Server not running";
  startBtn.disabled = on;
  startBtn.textContent = on ? "Running" : "Start Server";
  startBtn.style.display = on ? "none" : "block";
  stopBtn.style.display = on ? "block" : "none";
  stopBtn.disabled = false;
  stopBtn.textContent = "Stop Cut";
}

chrome.runtime.sendMessage({ type: "check-server" }, (res) => {
  setStatus(res?.ok === true);
});

startBtn.addEventListener("click", () => {
  startBtn.disabled = true;
  startBtn.textContent = "Starting…";
  chrome.runtime.sendMessage({ type: "ensure-server" }, (res) => {
    setStatus(res?.ok === true);
    if (!res?.ok) {
      startBtn.disabled = false;
      startBtn.textContent = "Start Server";
      statusText.textContent = "Failed — run install.sh first";
    }
  });
});

stopBtn.addEventListener("click", async () => {
  stopBtn.disabled = true;
  stopBtn.textContent = "Stopping…";
  note.style.display = "none";
  try {
    const r = await fetch("http://127.0.0.1:8000/cut/cancel", { method: "POST" });
    const data = await r.json();
    const n = data.cancelled ?? 0;
    note.textContent = n ? `Cancelled ${n} cut${n === 1 ? "" : "s"} and cleaned up temp files.`
                         : "No active cut to stop.";
    note.style.color = n ? "#4ade80" : "#999";
    note.style.display = "block";
  } catch (e) {
    note.textContent = "Failed to reach the server.";
    note.style.color = "#f06060";
    note.style.display = "block";
  }
  stopBtn.disabled = false;
  stopBtn.textContent = "Stop Cut";
});
