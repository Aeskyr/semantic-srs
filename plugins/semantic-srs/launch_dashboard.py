from __future__ import annotations

import os
import secrets
import socket
import threading
import webbrowser

import uvicorn


def available_port(start: int = 8765) -> int:
    for port in range(start, start + 100):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("No available localhost port found")


def main() -> None:
    port = available_port()
    token = secrets.token_urlsafe(32)
    os.environ["SEMANTIC_SRS_DASHBOARD_PORT"] = str(port)
    os.environ["SEMANTIC_SRS_DASHBOARD_TOKEN"] = token
    url = f"http://127.0.0.1:{port}/?token={token}"
    print(f"Semantic SRS dashboard: {url}")
    print("Press Ctrl+C to stop.")
    threading.Timer(0.8, webbrowser.open, args=(url,)).start()
    uvicorn.run("dashboard:app", host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()

