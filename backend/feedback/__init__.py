"""
Privacy-preserving human feedback capture and analysis for SonicDNA.

This package is intentionally separate from recommendation ranking. It records
structured feedback and computes offline summaries only.
"""

from .feedback_analysis import analyze_feedback
from .feedback_models import (
    FeedbackEventType,
    PlaylistFeedback,
    TrackFeedback,
    make_feedback_subject_id,
)
from .feedback_store import FeedbackStore, InMemoryFeedbackStore, JsonlFeedbackStore

__all__ = [
    "FeedbackEventType",
    "FeedbackStore",
    "InMemoryFeedbackStore",
    "JsonlFeedbackStore",
    "PlaylistFeedback",
    "TrackFeedback",
    "analyze_feedback",
    "make_feedback_subject_id",
]
