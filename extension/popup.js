const dot = document.getElementById("dot");
const statusText = document.getElementById("status-text");
const startBtn = document.getElementById("start-btn");
const openLink = document.getElementById("open-link");

function setStatus(on) {
  dot.className = "dot " + (on ? "on" : "off");
  statusText.textContent = on ? "Server running" : "Server not running";
  startBtn.disabled = on;
  startBtn.textContent = on ? "Running" : "Start Server";
  openLink.style.display = on ? "block" : "none";
}

chrome.runtime.sendMessage({ type: "check-server" }, (res) => {
  setStatus(res?.ok === true);
  if (!res?.ok) startBtn.disabled = false;
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
