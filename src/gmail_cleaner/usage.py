"""Which senders take up the most space? Summarizes a random sample of the mailbox."""

from __future__ import annotations

from collections import defaultdict
from email.utils import parseaddr

UNKNOWN = "(unknown)"
_TOP_SENDERS = 3


def _split(from_header: str) -> tuple[str, str]:
    addr = parseaddr(from_header)[1].strip().lower()
    if "@" not in addr:
        return UNKNOWN, UNKNOWN
    return addr, addr.rsplit("@", 1)[1]


def summarize(rows: list[tuple[str, int]], total_messages: int, top: int = 25) -> dict:
    """Group (From header, size) rows by sender domain, biggest first.

    Sizes from a sample are scaled up to estimate the whole mailbox. When the sample
    covers every message, the numbers are exact.
    """
    sampled = len(rows)
    sample_bytes = sum(size for _, size in rows)
    scale = total_messages / sampled if sampled else 0
    domains: dict[str, dict] = defaultdict(lambda: {"count": 0, "bytes": 0, "senders": defaultdict(int)})
    for header, size in rows:
        addr, domain = _split(header)
        d = domains[domain]
        d["count"] += 1
        d["bytes"] += size
        d["senders"][addr] += 1
    ranked = sorted(domains.items(), key=lambda kv: kv[1]["bytes"], reverse=True)
    return {
        "total_messages": total_messages,
        "sampled": sampled,
        "exact": sampled == total_messages,
        "sample_bytes": sample_bytes,
        "est_total_bytes": round(sample_bytes * scale),
        "other_domains": max(len(ranked) - top, 0),
        "domains": [
            {
                "domain": name,
                "count": d["count"],
                "bytes": d["bytes"],
                "share": d["bytes"] / sample_bytes if sample_bytes else 0,
                "est_bytes": round(d["bytes"] * scale),
                "top_senders": [
                    {"sender": a, "count": c}
                    for a, c in sorted(d["senders"].items(), key=lambda kv: -kv[1])[:_TOP_SENDERS]
                    if a != UNKNOWN
                ],
            }
            for name, d in ranked[:top]
        ],
    }
