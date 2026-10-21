from types import SimpleNamespace

import pytest

from gmail_cleaner.cleanup import build_query, trash_senders


class FakeMailbox:
    def __init__(self, by_query):
        self.by_query = by_query
        self.trashed = []

    def list_ids(self, query, limit=None):
        ids = self.by_query.get(query, [])
        return ids[:limit] if limit else ids

    def get(self, message_id):
        return SimpleNamespace(subject=f"subject {message_id}")

    def trash(self, ids):
        self.trashed += ids


def test_query_excludes_starred_and_trash():
    assert build_query("a@b.com") == "from:a@b.com -is:starred -in:trash"


@pytest.mark.parametrize("bad", ["", "  ", "a b", 'x"y', "a@b.com OR c@d.com"])
def test_query_rejects_injection(bad):
    with pytest.raises(ValueError):
        build_query(bad)


def test_dry_run_counts_but_does_not_trash():
    mb = FakeMailbox({build_query("a@b.com"): ["1", "2"]})
    [r] = trash_senders(mb, ["a@b.com"], apply=False)
    assert r.count == 2 and r.samples == ["subject 1", "subject 2"] and mb.trashed == []


def test_apply_trashes_every_match_and_logs(tmp_path):
    mb = FakeMailbox({build_query("a@b.com"): ["1", "2"], build_query("c.com"): ["3"]})
    log = tmp_path / "log.jsonl"
    trash_senders(mb, ["a@b.com", "c.com"], apply=True, log_path=log)
    assert mb.trashed == ["1", "2", "3"]
    assert len(log.read_text().splitlines()) == 2


def test_limit_applies_per_sender():
    mb = FakeMailbox({build_query("a@b.com"): ["1", "2", "3"]})
    trash_senders(mb, ["a@b.com"], apply=True, limit=2)
    assert mb.trashed == ["1", "2"]
