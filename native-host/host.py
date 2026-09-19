#!/usr/bin/env python3
"""
Native Messaging host for Drive Cutter Chrome extension.
Starts the server on demand and reports status back via stdout.
"""
import os
import sys
import traceback


def _run():
    import json
    import struct
    import subprocess
    import time
    import urllib.request
    import urllib.error

    SERVER_URL = "http://127.0.0.1:8000"
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
    if sys.platform == "win32":
        VENV_PYTHON = os.path.join(PROJECT_DIR, "venv", "Scripts", "python.exe")
    else:
        VENV_PYTHON = os.path.join(PROJECT_DIR, "venv", "bin", "python")
    APP_PY = os.path.join(PROJECT_DIR, "app.py")

    def send_message(obj):
        data = json.dumps(obj).encode("utf-8")
        sys.stdout.buffer.write(struct.pack("I", len(data)))
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()

    def read_message():
        raw = sys.stdin.buffer.read(4)
        if len(raw) != 4:
            return None
        length = struct.unpack("I", raw)[0]
        data = sys.stdin.buffer.read(length)
        return json.loads(data)

    def server_running():
        try:
            req = urllib.request.Request(f"{SERVER_URL}/health")
            with urllib.request.urlopen(req, timeout=2) as resp:
                return resp.status == 200
        except Exception:
            return False

    def start_server():
        if server_running():
            send_message({"status": "started", "message": "Already running"})
            return

        python = VENV_PYTHON if os.path.exists(VENV_PYTHON) else sys.executable
        kwargs = dict(cwd=PROJECT_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen([python, APP_PY], **kwargs)

        for _ in range(30):
            time.sleep(0.5)
            if server_running():
                send_message({"status": "started", "message": "Server started"})
                return

        send_message({"status": "error", "message": "Server failed to start in 15s"})

    start_server()
    while True:
        msg = read_message()
        if msg is None:
            break
        if msg.get("action") == "ping":
            send_message({"status": "pong", "running": server_running()})


if __name__ == "__main__":
    try:
        _run()
    except Exception:
        _log = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crash.log")
        with open(_log, "w") as f:
            traceback.print_exc(file=f)
        sys.exit(1)
