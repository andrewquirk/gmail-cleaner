"""Thin wrapper over the Gmail API. Only the operations the agent needs."""

from __future__ import annotations

from dataclasses import asdict, dataclass

_HEADERS = ["From", "Subject", "Date", "List-Unsubscribe"]
_BATCH = 1000  # batchModify limit


@dataclass
class MessageInfo:
    id: str
    sender: str
    subject: str
    date: str
    snippet: str
    labels: list[str]
    has_unsubscribe: bool

    def to_dict(self) -> dict:
        return asdict(self)


class Gmail:
    def __init__(self, service):
        self._svc = service.users().messages()
        self._labels = service.users().labels()
        self._label_ids: dict[str, str] | None = None

    def search(self, query: str, max_results: int = 50) -> list[MessageInfo]:
        resp = self._svc.list(userId="me", q=query, maxResults=min(max_results, 100)).execute()
        return [self.get(m["id"]) for m in resp.get("messages", [])]

    def get(self, message_id: str) -> MessageInfo:
        # Metadata only: the agent never sees message bodies.
        m = self._svc.get(
            userId="me", id=message_id, format="metadata", metadataHeaders=_HEADERS
        ).execute()
        h = {x["name"].lower(): x["value"] for x in m["payload"].get("headers", [])}
        return MessageInfo(
            id=m["id"],
            sender=h.get("from", ""),
            subject=h.get("subject", ""),
            date=h.get("date", ""),
            snippet=m.get("snippet", ""),
            labels=m.get("labelIds", []),
            has_unsubscribe="list-unsubscribe" in h,
        )

    def archive(self, ids: list[str]) -> None:
        self._modify(ids, add=[], remove=["INBOX"])

    def list_ids(self, query: str, limit: int | None = None) -> list[str]:
        """All message IDs matching a query, following pagination."""
        ids: list[str] = []
        token = None
        while True:
            resp = self._svc.list(
                userId="me", q=query, maxResults=500, pageToken=token
            ).execute()
            ids += [m["id"] for m in resp.get("messages", [])]
            token = resp.get("nextPageToken")
            if not token or (limit and len(ids) >= limit):
                return ids[:limit] if limit else ids

    def trash(self, ids: list[str]) -> None:
        # Moves to Trash (recoverable for 30 days). Never calls messages.delete.
        self._modify(ids, add=["TRASH"], remove=["INBOX"])

    def label(self, ids: list[str], label_name: str) -> None:
        self._modify(ids, add=[self._ensure_label(label_name)], remove=[])

    def _modify(self, ids: list[str], add: list[str], remove: list[str]) -> None:
        for i in range(0, len(ids), _BATCH):
            self._svc.batchModify(
                userId="me",
                body={"ids": ids[i : i + _BATCH], "addLabelIds": add, "removeLabelIds": remove},
            ).execute()

    def _ensure_label(self, name: str) -> str:
        if self._label_ids is None:
            resp = self._labels.list(userId="me").execute()
            self._label_ids = {x["name"]: x["id"] for x in resp.get("labels", [])}
        if name not in self._label_ids:
            created = self._labels.create(userId="me", body={"name": name}).execute()
            self._label_ids[name] = created["id"]
        return self._label_ids[name]
