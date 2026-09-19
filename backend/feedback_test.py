import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from feedback.feedback_analysis import analyze_feedback
from feedback.feedback_models import (
    FeedbackEventType,
    PlaylistFeedback,
    TrackFeedback,
    make_feedback_subject_id,
)
from feedback.feedback_store import InMemoryFeedbackStore, JsonlFeedbackStore


def test_track_feedback_redacts_canonical_identity_and_serializes_schema():
    event = TrackFeedback(
        feedback_subject_id=make_feedback_subject_id("canonical-user-123"),
        session_id="session-1",
        playlist_id="playlist-1",
        track_id="track-1",
        event_type=FeedbackEventType.EXPLORATION_ACCEPTED,
        artist="Artist A",
        is_exploration=True,
    )
    payload = event.to_dict()

    assert payload["event_type"] == "exploration_accepted"
    assert payload["feedback_subject_id"] != "canonical-user-123"
    assert "canonical_user_id" not in payload
    assert payload["privacy"]["canonical_identity_stored"] is False


def test_feedback_store_records_events_without_database_coupling():
    scratch = Path(__file__).parent / "__pycache__" / "feedback_test_events.jsonl"
    if scratch.exists():
        scratch.unlink()
    store = JsonlFeedbackStore(scratch)
    event = PlaylistFeedback(
        feedback_subject_id="anon-subject",
        session_id="session-1",
        playlist_id="playlist-1",
        satisfaction_rating=4,
        flow_smoothness_rating=2,
        emotional_coherence_rating=3,
        session_intent_alignment_rating=2,
        repetitiveness_complaint=True,
    )

    store.record(event)
    loaded = list(store.iter_events())

    assert len(loaded) == 1
    assert loaded[0]["event_type"] == "playlist_feedback"
    assert loaded[0]["repetitiveness_complaint"] is True
    scratch.unlink()


def test_feedback_analysis_reports_acceptance_fatigue_flow_and_session_signals():
    store = InMemoryFeedbackStore()
    subject = "anon-subject"
    for event in [
        TrackFeedback(
            feedback_subject_id=subject,
            session_id="s1",
            playlist_id="p1",
            track_id="a1",
            event_type=FeedbackEventType.EXPLORATION_ACCEPTED,
            artist="Repeat Artist",
            is_exploration=True,
        ),
        TrackFeedback(
            feedback_subject_id=subject,
            session_id="s1",
            playlist_id="p1",
            track_id="a2",
            event_type=FeedbackEventType.DISLIKE,
            artist="Repeat Artist",
        ),
        TrackFeedback(
            feedback_subject_id=subject,
            session_id="s1",
            playlist_id="p1",
            track_id="a3",
            event_type=FeedbackEventType.SKIP,
            artist="Repeat Artist",
        ),
        TrackFeedback(
            feedback_subject_id=subject,
            session_id="s1",
            playlist_id="p1",
            track_id="b1",
            event_type=FeedbackEventType.SAVE,
            artist="Discovery Artist",
            source="discovery",
        ),
        PlaylistFeedback(
            feedback_subject_id=subject,
            session_id="s1",
            playlist_id="p1",
            satisfaction_rating=2,
            flow_smoothness_rating=1,
            emotional_coherence_rating=2,
            session_intent_alignment_rating=1,
            chaos_complaint=True,
        ),
    ]:
        store.record(event)

    report = analyze_feedback(store.iter_events())

    assert report["exploration_acceptance_rate"] == 1.0
    assert report["discovery_success_rate"] == 1.0
    assert report["flow_dissatisfaction"]["low_rating_count"] == 1
    assert report["session_mismatch"]["low_alignment_count"] == 1
    assert report["artist_fatigue"]["fatigued_artists"][0]["artist"] == "repeat artist"
    assert report["emotional_coherence"]["average_rating"] == 2.0
