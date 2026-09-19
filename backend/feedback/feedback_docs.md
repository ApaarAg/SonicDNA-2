# SonicDNA Feedback Infrastructure

This package captures structured human feedback and computes lightweight offline analytics. It is separate from semantic ranking, graph reranking, exploration, playlist sequencing, scoring config, and calibration logic.

It does not implement reinforcement learning, online learning, automatic weight changes, or production ranking mutation.

## Package Contents

- `feedback_models.py`: dataclass schemas for track-level and playlist-level feedback.
- `feedback_store.py`: append-only in-memory and JSONL stores.
- `feedback_analysis.py`: pure analytics functions for exploration, fatigue, flow, session mismatch, repetition, discovery, and emotional coherence.
- `feedback_docs.md`: schema, storage, analytics, and calibration usage notes.

## Example Feedback Schema

Track-level event:

```json
{
  "feedback_subject_id": "fb_6e233f8d9d1d48f0b9d5db1e5e0a8012",
  "session_id": "session-2026-05-09-a",
  "playlist_id": "playlist-abc",
  "event_type": "exploration_accepted",
  "track_id": "spotify:track:123",
  "track_name": "Example Track",
  "artist": "Example Artist",
  "source": "discovery",
  "is_exploration": true,
  "position": 18,
  "timestamp": "2026-05-09T05:20:00+00:00",
  "privacy": {
    "canonical_identity_stored": false,
    "stores_raw_profile": false,
    "intended_use": "offline_analysis_only"
  }
}
```

Playlist-level event:

```json
{
  "feedback_subject_id": "fb_6e233f8d9d1d48f0b9d5db1e5e0a8012",
  "session_id": "session-2026-05-09-a",
  "playlist_id": "playlist-abc",
  "event_type": "playlist_feedback",
  "satisfaction_rating": 4,
  "flow_smoothness_rating": 3,
  "emotional_coherence_rating": 5,
  "session_intent_alignment_rating": 4,
  "repetitiveness_complaint": false,
  "chaos_complaint": false
}
```

Supported signals include likes, dislikes, skips, saves, replays, exploration acceptance/rejection, playlist satisfaction, flow smoothness, emotional coherence, session intent alignment, repetitiveness complaints, and chaos/disruption complaints.

## Example Analytics Report

```json
{
  "event_count": 42,
  "exploration_acceptance_rate": 0.625,
  "discovery_success_rate": 0.714,
  "artist_fatigue": {
    "fatigued_artists": [
      {
        "artist": "example artist",
        "event_count": 5,
        "negative_count": 3,
        "skip_count": 2,
        "fatigue_score": 0.8
      }
    ]
  },
  "flow_dissatisfaction": {
    "average_rating": 2.4,
    "low_rating_count": 3,
    "chaos_complaint_count": 1
  },
  "session_mismatch": {
    "average_alignment": 3.1,
    "low_alignment_count": 2
  },
  "emotional_coherence": {
    "average_rating": 4.2,
    "low_rating_count": 0
  }
}
```

## Feedback Storage Strategy

Feedback is append-only and separate from canonical user identity. Use `make_feedback_subject_id(canonical_user_id)` at the boundary if a stable pseudonymous id is needed, then store only the derived feedback id.

Recommended storage modes:

- `InMemoryFeedbackStore` for tests, local demos, and endpoint hook smoke checks.
- `JsonlFeedbackStore` for offline evaluation runs and private analyst review.
- A future production adapter may implement the same `record` and `iter_events` interface, but should write to a feedback-specific table or stream rather than canonical user records.

Do not store raw Spotify profiles, raw embeddings, auth tokens, or canonical user ids in this package.

## Optional Integration Hooks

Minimal endpoint hooks can translate frontend events into `TrackFeedback` or `PlaylistFeedback` and call `store.record(event)`. These hooks should be optional and must not be required by playlist generation.

Examples:

```python
from feedback.feedback_models import FeedbackEventType, TrackFeedback
from feedback.feedback_store import JsonlFeedbackStore

store = JsonlFeedbackStore("outputs/feedback/events.jsonl")
store.record(TrackFeedback(
    feedback_subject_id="fb_session_only",
    session_id="session-1",
    playlist_id="playlist-1",
    track_id="track-1",
    event_type=FeedbackEventType.SKIP,
    artist="Example Artist",
))
```

## Future Calibration Usage

Feedback analytics can inform offline calibration reviews:

- Compare exploration acceptance with calibration exploration-ratio experiments.
- Use artist fatigue indicators to evaluate diversity and repetition thresholds.
- Compare flow dissatisfaction with `flow_evaluation` reports.
- Use session mismatch indicators when reviewing session profile behavior.
- Use emotional coherence statistics for emotional and focus scenario benchmark reviews.

These signals should become benchmark inputs or review dashboards only. They should not auto-tune scoring config or mutate production recommendation behavior.
