import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from gmail_cleaner.ui import App, make_handler, parse_senders


@pytest.fixture
def server(tmp_path):
    app = App(tmp_path / "credentials.json", tmp_path / "token.json", tmp_path / "log.jsonl")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    app.port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield app
    srv.shutdown()
    srv.server_close()


def post(app, path, body=None, token=True, host=None):
    req = urllib.request.Request(
        f"http://127.0.0.1:{app.port}{path}",
        data=json.dumps(body or {}).encode(),
        headers={
            "Content-Type": "application/json",
            "Host": host or f"127.0.0.1:{app.port}",
            **({"X-CSRF-Token": app.csrf} if token else {}),
        },
    )
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def test_parse_senders_splits_and_dedupes():
    assert parse_senders("a@b.com, @c.com\nA\n a@b.com ;") == ["a@b.com", "@c.com", "A"]


def test_page_embeds_csrf_token(server):
    with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/") as r:
        assert server.csrf in r.read().decode()


def test_post_without_token_is_forbidden(server):
    assert post(server, "/api/status", token=False)[0] == 403


def test_wrong_host_is_forbidden(server):
    assert post(server, "/api/status", host="evil.example")[0] == 403


def test_status_when_signed_out(server):
    code, body = post(server, "/api/status")
    assert code == 200
    assert body == {"signed_in": False, "email": "", "has_credentials": False}


def test_rejects_non_desktop_credentials(server):
    code, body = post(server, "/api/credentials", {"content": json.dumps({"web": {}})})
    assert code == 400 and "Desktop app" in body["error"]
    assert not server.credentials.exists()


def test_saves_desktop_credentials(server):
    code, body = post(server, "/api/credentials", {"content": json.dumps({"installed": {}})})
    assert code == 200 and body["has_credentials"] is True
    assert oct(server.credentials.stat().st_mode & 0o777) == "0o600"


def test_preview_requires_sign_in(server):
    code, _ = post(server, "/api/preview", {"senders": "a@b.com"})
    assert code == 401


def test_preview_requires_senders(server):
    assert post(server, "/api/preview", {"senders": "  "})[0] == 400
