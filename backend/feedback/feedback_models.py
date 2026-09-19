"""
Structured feedback models.

The models keep feedback separate from canonical user identity. Callers should
pass a stable anonymous feedback_subject_id, or derive one with
make_feedback_subject_id before recording events.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Mapping, Optional


class FeedbackEventType(str, Enum):
    LIKE = "like"
    DISLIKE = "dislike"
    SKIP = "skip"
    SAVE = "save"
    REPLAY = "replay"
    EXPLORATION_ACCEPTED = "exploration_accepted"
    EXPLORATION_REJECTED = "exploration_rejected"
    PLAYLIST_FEEDBACK = "playlist_feedback"
    REPETITIVENESS_COMPLAINT = "repetitiveness_complaint"
    CHAOS_COMPLAINT = "chaos_complaint"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def make_feedback_subject_id(canonical_user_id: str, *, salt: str = "sonicdna-feedback-v1") -> str:
    """Return a one-way pseudonymous id for feedback storage."""
    raw = f"{salt}:{canonical_user_id}".encode("utf-8")
    return "fb_" + hashlib.sha256(raw).hexdigest()[:32]


def new_feedback_subject_id() -> str:
    """Return an anonymous feedback subject id for session-only use."""
    return "fb_" + uuid.uuid4().hex


def _clean_optional(value: Optional[Any]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _rating(value: Optional[int], field_name: str) -> Optional[int]:
    if value is None:
        return None
    try:
        rating = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer from 1 to 5") from exc
    if rating < 1 or rating > 5:
        raise ValueError(f"{field_name} must be from 1 to 5")
    return rating


@dataclass(frozen=True)
class FeedbackPrivacy:
    canonical_identity_stored: bool = False
    stores_raw_profile: bool = False
    intended_use: str = "offline_analysis_only"


@dataclass(frozen=True)
class FeedbackBase:
    feedback_subject_id: str
    session_id: str
    playlist_id: Optional[str] = None
    event_type: FeedbackEventType = FeedbackEventType.PLAYLIST_FEEDBACK
    timestamp: str = field(default_factory=utc_now_iso)
    client_context: Mapping[str, Any] = field(default_factory=dict)
    privacy: FeedbackPrivacy = field(default_factory=FeedbackPrivacy)

    def __post_init__(self) -> None:
        if not _clean_optional(self.feedback_subject_id):
            raise ValueError("feedback_subject_id is required")
        if not _clean_optional(self.session_id):
            raise ValueError("session_id is required")

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["event_type"] = self.event_type.value
        return {key: value for key, value in payload.items() if value is not None}


@dataclass(frozen=True)
class TrackFeedback(FeedbackBase):
    track_id: Optional[str] = None
    track_name: Optional[str] = None
    artist: Optional[str] = None
    source: Optional[str] = None
    is_exploration: bool = False
    position: Optional[int] = None
    skip_after_ms: Optional[int] = None
    replay_count: Optional[int] = None
    reason: Optional[str] = None
    event_type: FeedbackEventType = FeedbackEventType.LIKE

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.event_type == FeedbackEventType.PLAYLIST_FEEDBACK:
            raise ValueError("TrackFeedback requires a track-level event_type")
        if not _clean_optional(self.track_id) and not _clean_optional(self.track_name):
            raise ValueError("TrackFeedback requires track_id or track_name")


@dataclass(frozen=True)
class PlaylistFeedback(FeedbackBase):
    satisfaction_rating: Optional[int] = None
    flow_smoothness_rating: Optional[int] = None
    emotional_coherence_rating: Optional[int] = None
    session_intent_alignment_rating: Optional[int] = None
    repetitiveness_complaint: bool = False
    chaos_complaint: bool = False
    comment_tag: Optional[str] = None
    event_type: FeedbackEventType = FeedbackEventType.PLAYLIST_FEEDBACK

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "satisfaction_rating", _rating(self.satisfaction_rating, "satisfaction_rating"))
        object.__setattr__(self, "flow_smoothness_rating", _rating(self.flow_smoothness_rating, "flow_smoothness_rating"))
        object.__setattr__(
            self,
            "emotional_coherence_rating",
            _rating(self.emotional_coherence_rating, "emotional_coherence_rating"),
        )
        object.__setattr__(
            self,
            "session_intent_alignment_rating",
            _rating(self.session_intent_alignment_rating, "session_intent_alignment_rating"),
        )
