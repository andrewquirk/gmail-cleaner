import json
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from gmail_cleaner.imap import ImapError
from gmail_cleaner.ui import App, make_handler, parse_senders


class FakeMailbox:
    def __init__(self):
        self.trashed = []

    def list_ids(self, query, limit=None):
        return ["1", "2"] if "shop.com" in query else []

    def get(self, message_id):
        return SimpleNamespace(subject=f"subject {message_id}")

    def trash(self, ids):
        self.trashed += ids

    def sample(self, n):
        self.sampled = n
        return 100, [("A <a@shop.com>", 2000), ("b@gmail.com", 500)]


@pytest.fixture
def server(tmp_path):
    mailbox = FakeMailbox()
    logins = []

    @contextmanager
    def connector(email, password):
        logins.append((email, password))
        if password != "abcdefghijklmnop":
            raise ImapError("Gmail rejected that email or app password.")
        yield mailbox

    app = App(tmp_path / "log.jsonl", connector=connector)
    app.mailbox, app.logins = mailbox, logins
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


def connect(app, password="abcd efgh ijkl mnop"):
    return post(app, "/api/connect", {"email": "me@gmail.com", "password": password})


def test_parse_senders_splits_and_dedupes():
    assert parse_senders("a@b.com, @c.com\nA\n a@b.com ;") == ["a@b.com", "@c.com", "A"]


def test_page_embeds_csrf_token(server):
    with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/") as r:
        assert server.csrf in r.read().decode()


def test_post_without_token_is_forbidden(server):
    assert post(server, "/api/status", token=False)[0] == 403


def test_wrong_host_is_forbidden(server):
    assert post(server, "/api/status", host="evil.example")[0] == 403


def test_starts_disconnected(server):
    assert post(server, "/api/status") == (200, {"connected": False, "email": ""})


def test_connect_strips_spaces_from_app_password(server):
    code, body = connect(server)
    assert (code, body) == (200, {"connected": True, "email": "me@gmail.com"})
    assert server.logins[-1] == ("me@gmail.com", "abcdefghijklmnop")


def test_bad_password_is_rejected_and_not_kept(server):
    code, body = connect(server, "wrong")
    assert code == 400 and "rejected" in body["error"]
    assert post(server, "/api/status")[1]["connected"] is False


def test_connect_requires_both_fields(server):
    assert post(server, "/api/connect", {"email": "nope", "password": ""})[0] == 400


def test_password_is_never_returned(server):
    connect(server)
    assert "abcdefgh" not in json.dumps(post(server, "/api/status")[1])


def test_preview_requires_connection(server):
    assert post(server, "/api/preview", {"senders": "a@b.com"})[0] == 401


def test_preview_changes_nothing_and_apply_trashes(server):
    connect(server)
    code, body = post(server, "/api/preview", {"senders": "news@shop.com"})
    assert code == 200 and body["results"][0]["count"] == 2
    assert server.mailbox.trashed == []
    post(server, "/api/apply", {"senders": "news@shop.com"})
    assert server.mailbox.trashed == ["1", "2"]


def test_preview_requires_senders(server):
    connect(server)
    assert post(server, "/api/preview", {"senders": "  "})[0] == 400


def test_disconnect_forgets_password(server):
    connect(server)
    assert post(server, "/api/disconnect")[1]["connected"] is False
    assert post(server, "/api/preview", {"senders": "a@b.com"})[0] == 401


def test_usage_requires_connection(server):
    assert post(server, "/api/usage", {"sample": 1000})[0] == 401


def test_usage_returns_domains_and_changes_nothing(server):
    connect(server)
    code, body = post(server, "/api/usage", {"sample": 1000})
    assert code == 200 and server.mailbox.sampled == 1000
    assert [d["domain"] for d in body["domains"]] == ["shop.com", "gmail.com"]
    assert body["total_messages"] == 100 and server.mailbox.trashed == []


@pytest.mark.parametrize("n", [0, -5, 20_001])
def test_usage_rejects_bad_sample_sizes(server, n):
    connect(server)
    assert post(server, "/api/usage", {"sample": n})[0] == 400
