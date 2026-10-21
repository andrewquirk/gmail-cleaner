from gmail_cleaner.usage import summarize

ROWS = [
    ("Shop <news@shop.com>", 3000),
    ('"Shop Deals" <deals@SHOP.com>', 1000),
    ("friend@gmail.com", 500),
    ("", 500),
    ("not an address", 100),
]


def test_groups_by_domain_biggest_first_with_shares():
    out = summarize(ROWS, total_messages=5)
    names = [d["domain"] for d in out["domains"]]
    assert names == ["shop.com", "(unknown)", "gmail.com"]  # 4000, 600, 500 bytes
    shop = out["domains"][0]
    assert (shop["count"], shop["bytes"]) == (2, 4000)
    assert round(shop["share"], 3) == round(4000 / 5100, 3)
    assert {s["sender"] for s in shop["top_senders"]} == {"news@shop.com", "deals@shop.com"}


def test_exact_when_sample_is_whole_mailbox():
    out = summarize(ROWS, total_messages=5)
    assert out["exact"] and out["est_total_bytes"] == out["sample_bytes"] == 5100


def test_scales_estimates_when_sampled():
    out = summarize(ROWS, total_messages=50)
    assert not out["exact"]
    assert out["est_total_bytes"] == 51000
    assert out["domains"][0]["est_bytes"] == 40000


def test_unknown_senders_have_no_addable_chips():
    out = summarize([("", 10), ("???", 10)], total_messages=2)
    assert out["domains"][0]["domain"] == "(unknown)"
    assert out["domains"][0]["top_senders"] == []


def test_empty_sample():
    out = summarize([], total_messages=0)
    assert out["domains"] == [] and out["est_total_bytes"] == 0


def test_limits_to_top_n():
    rows = [(f"a@d{i}.com", 100 - i) for i in range(30)]
    out = summarize(rows, total_messages=30, top=25)
    assert len(out["domains"]) == 25 and out["other_domains"] == 5
