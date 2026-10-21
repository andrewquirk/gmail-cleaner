"""Local web UI: connect Gmail with an app password, then trash mail by sender.

Runs only on 127.0.0.1. The app password is kept in memory and never written to disk.
"""

from __future__ import annotations

import json
import re
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .cleanup import trash_senders
from .imap import ImapError, connect
from .usage import summarize

_PAGE = Path(__file__).with_name("ui.html")
_MAX_BODY = 1_000_000
_MAX_SAMPLE = 20_000


class App:
    """State shared by all requests: CSRF token and the in-memory Gmail login."""

    def __init__(self, log: Path, connector=connect):
        self.log = log
        self._connector = connector
        self.csrf = secrets.token_urlsafe(32)
        self.port = 0
        self._lock = threading.Lock()  # one Gmail action at a time
        self._email = ""
        self._password = ""

    def status(self) -> dict:
        return {"connected": bool(self._password), "email": self._email}

    def connect(self, email: str, password: str) -> None:
        email = email.strip()
        password = "".join(password.split())  # Google shows app passwords in groups of four
        if "@" not in email or not password:
            raise ValueError("Enter your Gmail address and app password.")
        with self._lock:
            with self._connector(email, password):
                pass  # logging in is the check
            self._email, self._password = email, password

    def disconnect(self) -> None:
        with self._lock:
            self._email = self._password = ""

    def usage(self, sample: int) -> dict:
        if not 1 <= sample <= _MAX_SAMPLE:
            raise ValueError(f"Sample size must be between 1 and {_MAX_SAMPLE:,}.")
        with self._lock:
            if not self._password:
                raise PermissionError("Not connected.")
            with self._connector(self._email, self._password) as mailbox:
                total, rows = mailbox.sample(sample)
        return summarize(rows, total)

    def trash(self, senders: list[str], apply: bool) -> list[dict]:
        with self._lock:
            if not self._password:
                raise PermissionError("Not connected.")
            with self._connector(self._email, self._password) as mailbox:
                results = trash_senders(mailbox, senders, apply=apply, log_path=self.log)
        return [{"sender": r.sender, "count": r.count, "samples": r.samples} for r in results]


def parse_senders(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for s in re.split(r"[\s,;]+", text):
        if s:
            seen[s] = None
    return list(seen)


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep the terminal quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self' 'unsafe-inline'")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj: dict) -> None:
            self._send(code, json.dumps(obj).encode())

        def _host_ok(self) -> bool:
            # Rejects DNS-rebinding: only our own origin may talk to us.
            return self.headers.get("Host") in (f"127.0.0.1:{app.port}", f"localhost:{app.port}")

        def do_GET(self):
            if not self._host_ok():
                return self._json(403, {"error": "forbidden"})
            if self.path == "/":
                html = _PAGE.read_text().replace("__CSRF__", app.csrf)
                return self._send(200, html.encode(), "text/html; charset=utf-8")
            self._json(404, {"error": "not found"})

        def do_POST(self):
            if not self._host_ok() or not secrets.compare_digest(
                self.headers.get("X-CSRF-Token", ""), app.csrf
            ):
                return self._json(403, {"error": "forbidden"})
            try:
                n = int(self.headers.get("Content-Length", 0))
                if n > _MAX_BODY:
                    return self._json(413, {"error": "too large"})
                body = json.loads(self.rfile.read(n) or b"{}")
                self._json(200, self._route(self.path, body))
            except PermissionError as e:
                self._json(401, {"error": str(e)})
            except (ImapError, ValueError, KeyError, TypeError) as e:
                self._json(400, {"error": str(e)})
            except Exception as e:  # noqa: BLE001 - surface Gmail failures to the page
                self._json(500, {"error": f"{type(e).__name__}: {e}"})

        def _route(self, path: str, body: dict) -> dict:
            if path == "/api/status":
                return app.status()
            if path == "/api/connect":
                app.connect(body["email"], body["password"])
                return app.status()
            if path == "/api/disconnect":
                app.disconnect()
                return app.status()
            if path == "/api/usage":
                return app.usage(int(body.get("sample", 1000)))
            if path in ("/api/preview", "/api/apply"):
                senders = parse_senders(body.get("senders", ""))
                if not senders:
                    raise ValueError("Enter at least one sender.")
                return {"results": app.trash(senders, apply=path == "/api/apply")}
            raise KeyError(f"unknown endpoint {path}")

    return Handler


def serve(log: Path, open_browser: bool = True) -> None:
    app = App(log)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    app.port = server.server_address[1]
    url = f"http://127.0.0.1:{app.port}/"
    print(f"gmail-cleaner UI running at {url}  (Ctrl+C to stop)", flush=True)
    if open_browser:
        threading.Timer(0.3, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
