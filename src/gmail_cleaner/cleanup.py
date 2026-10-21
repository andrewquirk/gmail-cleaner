"""Deterministic sender-based cleanup: find everything from a sender, move it to Trash."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol


class Mailbox(Protocol):
    def list_ids(self, query: str, limit: int | None = ...) -> list[str]: ...
    def get(self, message_id: str): ...
    def trash(self, ids: list[str]) -> None: ...


@dataclass
class SenderResult:
    sender: str
    count: int
    samples: list[str] = field(default_factory=list)  # subjects, for the preview


def build_query(sender: str) -> str:
    """Gmail query for one sender. Accepts an address or a domain (e.g. "@shop.com")."""
    sender = sender.strip()
    if not sender or any(c in sender for c in ' "(){}'):
        raise ValueError(f"invalid sender: {sender!r}")
    # Starred mail is always kept; mail already in Trash is ignored.
    return f"from:{sender} -is:starred -in:trash"


def trash_senders(
    mailbox: Mailbox,
    senders: list[str],
    apply: bool = False,
    limit: int | None = None,
    log_path: Path | None = None,
) -> list[SenderResult]:
    results = []
    for sender in senders:
        ids = mailbox.list_ids(build_query(sender), limit)
        samples = [mailbox.get(i).subject for i in ids[:3]]
        if ids and apply:
            mailbox.trash(ids)
        if ids and log_path:
            entry = {
                "time": datetime.now(timezone.utc).isoformat(),
                "applied": apply,
                "action": "trash",
                "sender": sender,
                "ids": ids,
            }
            with log_path.open("a") as f:
                f.write(json.dumps(entry) + "\n")
        results.append(SenderResult(sender, len(ids), samples))
    return results
