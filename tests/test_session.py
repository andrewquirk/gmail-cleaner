from gmail_cleaner.gmail import MessageInfo
from gmail_cleaner.session import Session


def msg(id, sender="news@shop.com", labels=("INBOX",)):
    return MessageInfo(id, sender, "Sale!", "Mon", "", list(labels), True)


class FakeGmail:
    def __init__(self, messages):
        self.messages = messages
        self.calls = []

    def search(self, query, max_results=50):
        return self.messages

    def archive(self, ids):
        self.calls.append(("archive", ids))

    def trash(self, ids):
        self.calls.append(("trash", ids))

    def label(self, ids, name):
        self.calls.append(("label", ids, name))


def make(apply=False, **kw):
    g = FakeGmail([msg("1"), msg("2", labels=("INBOX", "STARRED")), msg("3", "boss@work.com")])
    s = Session(gmail=g, apply=apply, protected_senders=["boss@work.com"], **kw)
    s.search("in:inbox", 50)
    return s, g


def test_dry_run_changes_nothing():
    s, g = make(apply=False)
    r = s.act("archive", ["1"], "promo")
    assert r["count"] == 1 and g.calls == []


def test_apply_calls_gmail():
    s, g = make(apply=True)
    s.act("archive", ["1"], "promo")
    assert g.calls == [("archive", ["1"])]


def test_skips_starred_protected_and_unknown():
    s, g = make(apply=True)
    r = s.act("trash", ["1", "2", "3", "999"], "junk")
    assert g.calls == [("trash", ["1"])]
    assert set(r["skipped"]) == {"2", "3", "999"}


def test_max_actions_cap():
    s, _ = make(apply=True, max_actions=1)
    s.seen["4"] = msg("4")
    r = s.act("archive", ["1", "4"], "promo")
    assert r["count"] == 1 and "4" in r["skipped"]


def test_label_passes_name():
    s, g = make(apply=True)
    s.act("label", ["1"], "receipt", label="Cleaner/Receipts")
    assert g.calls == [("label", ["1"], "Cleaner/Receipts")]
