"""Launch LumenSpace on loopback; open the browser only once the server is ready."""

import socket
import threading
import time
import urllib.request
import webbrowser

import uvicorn

URL = "http://127.0.0.1:8765"


def open_when_ready():
    for _ in range(200):
        try:
            with urllib.request.urlopen(URL, timeout=0.5) as response:
                if response.status == 200:
                    webbrowser.open(URL)
                    return
        except OSError:
            time.sleep(0.1)


if __name__ == "__main__":
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", 8765))
        except OSError:
            raise SystemExit(
                "LumenSpace cannot start: port 8765 is already in use. "
                "Close the previous terminal/server window and start LumenSpace again."
            ) from None
    threading.Thread(target=open_when_ready, daemon=True).start()
    uvicorn.run("terminal.app:app", host="127.0.0.1", port=8765, log_level="info")
