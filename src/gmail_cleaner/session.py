"""Safety layer between the agent and Gmail.

Every mutation goes through Session.act(), which enforces the rules in code
(not in the prompt): dry-run, protected senders, starred mail, an action cap,
and "only message IDs the agent actually saw in a search".
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from .gmail import MessageInfo


class MailClient(Protocol):
    def search(self, query: str, max_results: int = ...) -> list[MessageInfo]: ...
    def archive(self, ids: list[str]) -> None: ...
    def trash(self, ids: list[str]) -> None: ...
    def label(self, ids: list[str], label_name: str) -> None: ...


@dataclass
class Session:
    gmail: MailClient
    apply: bool = False
    max_actions: int = 200
    protected_senders: list[str] = field(default_factory=list)
    log_path: Path | None = None
    seen: dict[str, MessageInfo] = field(default_factory=dict)
    actions_taken: int = 0

    def search(self, query: str, max_results: int) -> list[MessageInfo]:
        results = self.gmail.search(query, max_results)
        for m in results:
            self.seen[m.id] = m
        return results

    def act(self, action: str, ids: list[str], reason: str, label: str | None = None) -> dict:
        allowed: list[str] = []
        skipped: dict[str, str] = {}
        for i in dict.fromkeys(ids):
            msg = self.seen.get(i)
            if msg is None:
                skipped[i] = "unknown id (not returned by a search this run)"
            elif "STARRED" in msg.labels:
                skipped[i] = "starred"
            elif self._is_protected(msg):
                skipped[i] = "protected sender"
            elif self.actions_taken + len(allowed) >= self.max_actions:
                skipped[i] = "max_actions reached"
            else:
                allowed.append(i)

        if allowed and self.apply:
            if action == "label":
                self.gmail.label(allowed, label or "")
            else:
                getattr(self.gmail, action)(allowed)
        self.actions_taken += len(allowed)
        self._log(action, allowed, reason, label)
        return {
            "status": "applied" if self.apply else "dry-run (nothing changed)",
            "action": action,
            "count": len(allowed),
            "skipped": skipped,
        }

    def _is_protected(self, msg: MessageInfo) -> bool:
        sender = msg.sender.lower()
        return any(p.lower() in sender for p in self.protected_senders)

    def _log(self, action: str, ids: list[str], reason: str, label: str | None) -> None:
        if not ids:
            return
        entry = {
            "time": datetime.now(timezone.utc).isoformat(),
            "applied": self.apply,
            "action": action,
            "label": label,
            "reason": reason,
            "messages": [
                {"id": i, "from": self.seen[i].sender, "subject": self.seen[i].subject}
                for i in ids
            ],
        }
        if self.log_path:
            with self.log_path.open("a") as f:
                f.write(json.dumps(entry) + "\n")
