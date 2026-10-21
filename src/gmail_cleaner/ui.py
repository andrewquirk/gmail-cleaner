"""Local web UI: sign in with Google, then trash mail by sender. Runs only on 127.0.0.1."""

from __future__ import annotations

import json
import re
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .auth import build_service, load_cached, sign_in
from .cleanup import trash_senders
from .gmail import Gmail

_PAGE = Path(__file__).with_name("ui.html")
_MAX_BODY = 1_000_000


class App:
    """State shared by all requests: file locations, CSRF token, and the Gmail session."""

    def __init__(self, credentials: Path, token: Path, log: Path):
        self.credentials = credentials
        self.token = token
        self.log = log
        self.csrf = secrets.token_urlsafe(32)
        self.port = 0
        self._lock = threading.Lock()  # one Gmail action or sign-in at a time
        self._gmail: Gmail | None = None
        self._email = ""

    def _connect(self) -> Gmail | None:
        if self._gmail is None:
            creds = load_cached(self.token)
            if creds is None:
                return None
            svc = build_service(creds)
            self._email = svc.users().getProfile(userId="me").execute()["emailAddress"]
            self._gmail = Gmail(svc)
        return self._gmail

    def status(self) -> dict:
        with self._lock:
            signed_in = self._connect() is not None
            return {
                "signed_in": signed_in,
                "email": self._email if signed_in else "",
                "has_credentials": self.credentials.exists(),
            }

    def save_credentials(self, raw: str) -> None:
        data = json.loads(raw)
        if not isinstance(data, dict) or "installed" not in data:
            raise ValueError(
                "That isn't a Desktop-app OAuth client file. In Google Cloud Console, "
                "create an OAuth client ID of type 'Desktop app' and download its JSON."
            )
        self.credentials.write_text(raw)
        self.credentials.chmod(0o600)

    def sign_in(self) -> None:
        with self._lock:
            sign_in(self.credentials, self.token)
            self._gmail = None

    def sign_out(self) -> None:
        with self._lock:
            self.token.unlink(missing_ok=True)
            self._gmail = None
            self._email = ""

    def trash(self, senders: list[str], apply: bool) -> list[dict]:
        with self._lock:
            gmail = self._connect()
            if gmail is None:
                raise PermissionError("Not signed in.")
            results = trash_senders(gmail, senders, apply=apply, log_path=self.log)
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
            except FileNotFoundError as e:
                self._json(400, {"error": str(e)})
            except (ValueError, KeyError, TypeError) as e:
                self._json(400, {"error": str(e)})
            except Exception as e:  # noqa: BLE001 - surface Google/API failures to the page
                self._json(500, {"error": f"{type(e).__name__}: {e}"})

        def _route(self, path: str, body: dict) -> dict:
            if path == "/api/status":
                return app.status()
            if path == "/api/credentials":
                app.save_credentials(body["content"])
                return app.status()
            if path == "/api/signin":
                app.sign_in()
                return app.status()
            if path == "/api/signout":
                app.sign_out()
                return app.status()
            if path in ("/api/preview", "/api/apply"):
                senders = parse_senders(body.get("senders", ""))
                if not senders:
                    raise ValueError("Enter at least one sender.")
                return {"results": app.trash(senders, apply=path == "/api/apply")}
            raise KeyError(f"unknown endpoint {path}")

    return Handler


def serve(credentials: Path, token: Path, log: Path, open_browser: bool = True) -> None:
    app = App(credentials, token, log)
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
