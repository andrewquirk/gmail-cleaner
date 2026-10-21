"""Gmail over IMAP with an app password.

Only three things are ever done: search, read subject lines, and copy mail into Trash.
Nothing is expunged or permanently deleted.
"""

from __future__ import annotations

import imaplib
import random
import re
import ssl
from contextlib import contextmanager
from dataclasses import dataclass
from email import message_from_bytes, policy

HOST = "imap.gmail.com"
_BATCH = 500  # UIDs per COPY command, to keep command lines short
_FETCH_BATCH = 500  # messages per FETCH when sampling
_UID = re.compile(rb"UID (\d+)")
_SIZE = re.compile(rb"RFC822\.SIZE (\d+)")
_LIST_LINE = re.compile(rb'\((?P<flags>[^)]*)\) (?:"[^"]*"|NIL) (?P<name>.+)')


class ImapError(Exception):
    """A problem with the Gmail connection, phrased for the person using the UI."""


@dataclass
class Header:
    subject: str


def _quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


class ImapGmail:
    """Same shape as cleanup.Mailbox: list_ids / get / trash."""

    def __init__(self, conn: imaplib.IMAP4):
        self._c = conn
        self._all, self._trash = self._find_folders()
        self._selected = False

    def _find_folders(self) -> tuple[str, str]:
        # Folder names are localized, so find them by their special-use flags.
        typ, lines = self._c.list()
        found: dict[str, str] = {}
        for line in lines if typ == "OK" else []:
            m = _LIST_LINE.match(line or b"")
            if not m:
                continue
            name = m["name"].decode("ascii", "replace").strip()
            if name.startswith('"') and name.endswith('"'):
                name = name[1:-1].replace('\\"', '"').replace("\\\\", "\\")
            for flag in m["flags"].decode().split():
                if flag in ("\\All", "\\Trash"):
                    found[flag] = name
        if len(found) != 2:
            raise ImapError(
                "Couldn't find Gmail's 'All Mail' and 'Trash' folders. "
                "In Gmail settings, check that IMAP access is turned on."
            )
        return found["\\All"], found["\\Trash"]

    def _select_all(self) -> None:
        if not self._selected:
            typ, _ = self._c.select(_quote(self._all), readonly=True)
            if typ != "OK":
                raise ImapError("Couldn't open 'All Mail'.")
            self._selected = True

    def list_ids(self, query: str, limit: int | None = None) -> list[str]:
        """UIDs matching a Gmail search (e.g. "from:a@b.com -is:starred"), newest first."""
        if not query.isascii():
            raise ValueError("Sender addresses must use plain ASCII characters.")
        self._select_all()
        typ, data = self._c.uid("SEARCH", "X-GM-RAW", _quote(query))
        if typ != "OK":
            raise ImapError("Gmail rejected that search.")
        ids = (data[0] or b"").decode().split()
        ids.reverse()
        return ids[:limit] if limit else ids

    def get(self, message_id: str) -> Header:
        self._select_all()
        typ, data = self._c.uid("FETCH", message_id, "(BODY.PEEK[HEADER.FIELDS (SUBJECT)])")
        if typ != "OK":
            return Header("(unknown)")
        raw = next((p[1] for p in data if isinstance(p, tuple)), b"")
        msg = message_from_bytes(raw, policy=policy.default)
        return Header(str(msg["Subject"] or "(no subject)"))

    def sample(self, n: int) -> tuple[int, list[tuple[str, int]]]:
        """(total messages in All Mail, [(From header, size in bytes)] for a random sample).

        Reads only sizes and the From header, never bodies. If n covers the whole mailbox,
        every message is included.
        """
        self._select_all()
        typ, data = self._c.uid("SEARCH", "ALL")
        if typ != "OK":
            raise ImapError("Gmail rejected the search.")
        uids = (data[0] or b"").decode().split()
        chosen = uids if n >= len(uids) else random.sample(uids, n)
        rows: list[tuple[str, int]] = []
        for i in range(0, len(chosen), _FETCH_BATCH):
            batch = ",".join(chosen[i : i + _FETCH_BATCH])
            typ, data = self._c.uid("FETCH", batch, "(RFC822.SIZE BODY.PEEK[HEADER.FIELDS (FROM)])")
            if typ != "OK":
                raise ImapError("Gmail refused to list message sizes.")
            rows += _parse_sizes(data)
        return len(uids), rows

    def trash(self, ids: list[str]) -> None:
        # COPY into Trash gives the message the Trash label, which is how Gmail files
        # trashed mail. Gmail deletes it for good after 30 days; until then it's recoverable.
        self._select_all()
        for i in range(0, len(ids), _BATCH):
            typ, _ = self._c.uid("COPY", ",".join(ids[i : i + _BATCH]), _quote(self._trash))
            if typ != "OK":
                raise ImapError("Gmail refused to move some messages to Trash.")


def _parse_sizes(data) -> list[tuple[str, int]]:
    """Pull (From header, size) out of a FETCH response, whichever order the server used."""
    records: list[dict] = []
    for part in data:
        if isinstance(part, tuple):  # item line + the header literal
            records.append({"text": part[0], "from": part[1]})
        elif isinstance(part, bytes) and records:  # items that came after the literal
            records[-1]["text"] += part
    rows = []
    for r in records:
        m = _SIZE.search(r["text"])
        if not m:
            continue
        msg = message_from_bytes(r["from"], policy=policy.default)
        rows.append((str(msg["From"] or ""), int(m[1])))
    return rows


@contextmanager
def connect(email: str, app_password: str):
    """Log in, yield an ImapGmail, and always log out."""
    try:
        conn = imaplib.IMAP4_SSL(HOST, ssl_context=ssl.create_default_context(), timeout=30)
    except OSError as e:
        raise ImapError(f"Couldn't reach Gmail ({e}). Check your internet connection.") from e
    try:
        try:
            conn.login(email, app_password)
        except imaplib.IMAP4.error as e:
            raise ImapError(
                "Gmail rejected that email or app password. Use a 16-character app "
                "password, not your normal Google password."
            ) from e
        yield ImapGmail(conn)
    finally:
        try:
            conn.logout()
        except (imaplib.IMAP4.error, OSError):
            pass
