"""
Lightweight feedback analytics.

Reports summarize captured human feedback for calibration review. They do not
modify recommendation weights, profiles, ranking, or graph behavior.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable, Mapping, Optional


POSITIVE_DISCOVERY_EVENTS = {"save", "like", "replay", "exploration_accepted"}
NEGATIVE_TRACK_EVENTS = {"dislike", "skip", "exploration_rejected"}


def _events(events: Iterable[Mapping]) -> list[dict]:
    return [dict(event) for event in events]


def _is_exploration(event: Mapping) -> bool:
    return bool(event.get("is_exploration")) or event.get("event_type") in {
        "exploration_accepted",
        "exploration_rejected",
    }


def _rating_values(events: list[dict], key: str) -> list[float]:
    values = []
    for event in events:
        value = event.get(key)
        if isinstance(value, (int, float)):
            values.append(float(value))
    return values


def _avg(values: list[float]) -> Optional[float]:
    if not values:
        return None
    return round(sum(values) / len(values), 3)


def _rate(numerator: int, denominator: int) -> Optional[float]:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 3)


def exploration_acceptance(events: list[dict]) -> dict:
    exploration_events = [event for event in events if _is_exploration(event)]
    accepted = [event for event in exploration_events if event.get("event_type") == "exploration_accepted"]
    rejected = [event for event in exploration_events if event.get("event_type") == "exploration_rejected"]
    explicit_total = len(accepted) + len(rejected)
    return {
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "rated_count": explicit_total,
        "acceptance_rate": _rate(len(accepted), explicit_total),
    }


def discovery_success(events: list[dict]) -> dict:
    discovery = [
        event
        for event in events
        if event.get("source") == "discovery" or _is_exploration(event)
    ]
    positive = [event for event in discovery if event.get("event_type") in POSITIVE_DISCOVERY_EVENTS]
    negative = [event for event in discovery if event.get("event_type") in NEGATIVE_TRACK_EVENTS]
    total = len(positive) + len(negative)
    return {
        "positive_count": len(positive),
        "negative_count": len(negative),
        "rated_count": total,
        "success_rate": _rate(len(positive), total),
    }


def artist_fatigue(events: list[dict], *, repeat_threshold: int = 3) -> dict:
    artist_events: dict[str, list[dict]] = defaultdict(list)
    for event in events:
        artist = str(event.get("artist") or "").strip().lower()
        if artist:
            artist_events[artist].append(event)

    fatigued = []
    for artist, artist_items in artist_events.items():
        negative = sum(1 for event in artist_items if event.get("event_type") in NEGATIVE_TRACK_EVENTS)
        skips = sum(1 for event in artist_items if event.get("event_type") == "skip")
        if len(artist_items) >= repeat_threshold or negative >= 2:
            fatigued.append(
                {
                    "artist": artist,
                    "event_count": len(artist_items),
                    "negative_count": negative,
                    "skip_count": skips,
                    "fatigue_score": round((negative + skips * 0.5) / max(1, len(artist_items)), 3),
                }
            )
    fatigued.sort(key=lambda item: (item["fatigue_score"], item["event_count"]), reverse=True)
    return {
        "fatigued_artists": fatigued,
        "artist_event_counts": dict(Counter(str(event.get("artist") or "").strip().lower() for event in events if event.get("artist"))),
    }


def flow_dissatisfaction(events: list[dict]) -> dict:
    ratings = _rating_values(events, "flow_smoothness_rating")
    low = [rating for rating in ratings if rating <= 2]
    chaos_count = sum(1 for event in events if event.get("chaos_complaint") or event.get("event_type") == "chaos_complaint")
    return {
        "average_rating": _avg(ratings),
        "low_rating_count": len(low),
        "chaos_complaint_count": chaos_count,
        "indicator_score": round((len(low) + chaos_count) / max(1, len(events)), 3),
    }


def session_mismatch(events: list[dict]) -> dict:
    ratings = _rating_values(events, "session_intent_alignment_rating")
    low = [rating for rating in ratings if rating <= 2]
    return {
        "average_alignment": _avg(ratings),
        "low_alignment_count": len(low),
        "mismatch_rate": _rate(len(low), len(ratings)),
    }


def repetitive_playlist_detection(events: list[dict]) -> dict:
    playlist_counts = Counter(event.get("playlist_id") for event in events if event.get("playlist_id"))
    complaint_count = sum(
        1
        for event in events
        if event.get("repetitiveness_complaint") or event.get("event_type") == "repetitiveness_complaint"
    )
    repeated_playlists = [
        {"playlist_id": playlist_id, "feedback_event_count": count}
        for playlist_id, count in playlist_counts.items()
        if count >= 5
    ]
    return {
        "complaint_count": complaint_count,
        "repeated_feedback_playlists": repeated_playlists,
        "complaint_rate": _rate(complaint_count, len(events)),
    }


def emotional_coherence(events: list[dict]) -> dict:
    ratings = _rating_values(events, "emotional_coherence_rating")
    low = [rating for rating in ratings if rating <= 2]
    return {
        "average_rating": _avg(ratings),
        "low_rating_count": len(low),
        "rating_count": len(ratings),
    }


def analyze_feedback(events: Iterable[Mapping]) -> dict:
    """Return a structured offline analytics report."""
    items = _events(events)
    exploration = exploration_acceptance(items)
    discovery = discovery_success(items)
    satisfaction = _rating_values(items, "satisfaction_rating")
    report = {
        "event_count": len(items),
        "track_event_count": sum(1 for event in items if event.get("track_id") or event.get("track_name")),
        "playlist_event_count": sum(1 for event in items if event.get("event_type") == "playlist_feedback"),
        "exploration_acceptance_rate": exploration["acceptance_rate"],
        "discovery_success_rate": discovery["success_rate"],
        "exploration": exploration,
        "artist_fatigue": artist_fatigue(items),
        "flow_dissatisfaction": flow_dissatisfaction(items),
        "session_mismatch": session_mismatch(items),
        "repetitive_playlist_detection": repetitive_playlist_detection(items),
        "discovery_success": discovery,
        "emotional_coherence": emotional_coherence(items),
        "playlist_satisfaction": {
            "average_rating": _avg(satisfaction),
            "low_rating_count": sum(1 for value in satisfaction if value <= 2),
            "rating_count": len(satisfaction),
        },
        "privacy": {
            "canonical_identity_required": False,
            "raw_profile_required": False,
            "analysis_writes_to_ranking": False,
        },
    }
    return report
