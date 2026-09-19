"""
Append-only feedback storage adapters.

Stores are deliberately separate from canonical user tables. The JSONL store is
for lightweight offline use; callers can provide their own adapter by
implementing FeedbackStore.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Iterator, List, Mapping, Protocol


class FeedbackStore(Protocol):
    def record(self, event) -> dict:
        ...

    def iter_events(self, *, feedback_subject_id: str | None = None, session_id: str | None = None) -> Iterable[dict]:
        ...


def _event_to_dict(event) -> dict:
    if hasattr(event, "to_dict"):
        return dict(event.to_dict())
    return dict(event)


def _matches(event: Mapping, *, feedback_subject_id: str | None, session_id: str | None) -> bool:
    if feedback_subject_id is not None and event.get("feedback_subject_id") != feedback_subject_id:
        return False
    if session_id is not None and event.get("session_id") != session_id:
        return False
    return True


class InMemoryFeedbackStore:
    """Small test/dev store. Does not touch production persistence."""

    def __init__(self) -> None:
        self._events: List[dict] = []

    def record(self, event) -> dict:
        payload = _event_to_dict(event)
        self._events.append(payload)
        return payload

    def record_many(self, events: Iterable) -> List[dict]:
        return [self.record(event) for event in events]

    def iter_events(self, *, feedback_subject_id: str | None = None, session_id: str | None = None) -> Iterator[dict]:
        for event in self._events:
            if _matches(event, feedback_subject_id=feedback_subject_id, session_id=session_id):
                yield dict(event)


class JsonlFeedbackStore:
    """Append-only JSONL feedback store for offline analysis jobs."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def record(self, event) -> dict:
        payload = _event_to_dict(event)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
        return payload

    def record_many(self, events: Iterable) -> List[dict]:
        return [self.record(event) for event in events]

    def iter_events(self, *, feedback_subject_id: str | None = None, session_id: str | None = None) -> Iterator[dict]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                event = json.loads(line)
                if _matches(event, feedback_subject_id=feedback_subject_id, session_id=session_id):
                    yield event
