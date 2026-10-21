import pytest

from gmail_cleaner.imap import ImapError, ImapGmail

LIST = [
    b'(\\HasNoChildren) "/" "INBOX"',
    b'(\\All \\HasNoChildren) "/" "[Gmail]/All Mail"',
    b'(\\HasNoChildren \\Trash) "/" "[Gmail]/Papelera"',
]


class FakeConn:
    def __init__(self, listing=LIST, found=b"3 1 2"):
        self.listing, self.found = listing, found
        self.calls = []

    def sizes(self, uids):
        out = []
        for u in uids:  # size before the header literal
            out += [(f"{u} (UID {u} RFC822.SIZE {int(u) * 100} BODY[HEADER.FIELDS (FROM)] {{20}}".encode(),
                     f"From: a{u}@x.com\r\n\r\n".encode()), b")"]
        return out

    def list(self):
        return "OK", self.listing

    def select(self, folder, readonly=False):
        self.calls.append(("select", folder, readonly))
        return "OK", [b"3"]

    def uid(self, cmd, *args):
        self.calls.append((cmd, *args))
        if cmd == "SEARCH":
            return "OK", [self.found]
        if cmd == "FETCH" and "RFC822.SIZE" in args[1]:
            return "OK", self.sizes(args[0].split(","))
        if cmd == "FETCH":
            hdr = b"Subject: =?utf-8?q?Caf=C3=A9_deals?=\r\n\r\n"
            return "OK", [(b"1 (UID 1 BODY[HEADER.FIELDS (SUBJECT)] {40}", hdr), b")"]
        return "OK", [b"done"]


def test_finds_folders_by_special_use_flag_not_name():
    g = ImapGmail(FakeConn())
    assert (g._all, g._trash) == ("[Gmail]/All Mail", "[Gmail]/Papelera")


def test_missing_folders_gives_helpful_error():
    with pytest.raises(ImapError, match="IMAP"):
        ImapGmail(FakeConn(listing=[b'(\\HasNoChildren) "/" "INBOX"']))


def test_list_ids_newest_first_and_limited():
    conn = FakeConn()
    g = ImapGmail(conn)
    assert g.list_ids("from:a@b.com -is:starred", limit=2) == ["2", "1"]
    assert ("SEARCH", "X-GM-RAW", '"from:a@b.com -is:starred"') in conn.calls
    assert ("select", '"[Gmail]/All Mail"', True) in conn.calls  # read-only


def test_empty_search():
    assert ImapGmail(FakeConn(found=b"")).list_ids("from:x") == []


def test_non_ascii_query_rejected():
    with pytest.raises(ValueError):
        ImapGmail(FakeConn()).list_ids("from:café@x.com")


def test_get_decodes_subject():
    assert ImapGmail(FakeConn()).get("1").subject == "Café deals"


def test_trash_copies_to_trash_in_batches():
    conn = FakeConn()
    ImapGmail(conn).trash([str(i) for i in range(1200)])
    copies = [c for c in conn.calls if c[0] == "COPY"]
    assert [len(c[1].split(",")) for c in copies] == [500, 500, 200]
    assert all(c[2] == '"[Gmail]/Papelera"' for c in copies)
    assert not any(c[0] in ("STORE", "EXPUNGE") for c in conn.calls)


def test_sample_reads_sizes_and_senders():
    conn = FakeConn(found=b"1 2 3")
    total, rows = ImapGmail(conn).sample(10)
    assert total == 3
    assert sorted(rows) == [("a1@x.com", 100), ("a2@x.com", 200), ("a3@x.com", 300)]
    assert any(c[0] == "FETCH" and "BODY.PEEK" in c[2] for c in conn.calls)  # never marks read


def test_sample_is_random_subset_when_smaller_than_mailbox():
    conn = FakeConn(found=b" ".join(str(i).encode() for i in range(1, 101)))
    total, rows = ImapGmail(conn).sample(10)
    assert total == 100 and len(rows) == 10 and len({r[0] for r in rows}) == 10


def test_sample_batches_fetches():
    conn = FakeConn(found=b" ".join(str(i).encode() for i in range(1, 1201)))
    ImapGmail(conn).sample(5000)
    fetches = [c for c in conn.calls if c[0] == "FETCH"]
    assert [len(c[1].split(",")) for c in fetches] == [500, 500, 200]


def test_parse_handles_size_after_the_literal():
    from gmail_cleaner.imap import _parse_sizes

    data = [(b"1 (UID 7 BODY[HEADER.FIELDS (FROM)] {20}", b"From: z@y.com\r\n\r\n"), b" RFC822.SIZE 4242)"]
    assert _parse_sizes(data) == [("z@y.com", 4242)]
