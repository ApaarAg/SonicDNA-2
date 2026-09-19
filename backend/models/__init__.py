"""
models/ — Explicit schema separation for SonicDNA backend.

Three distinct schema layers:
  response_models     — user-facing API payloads (safe, stable)
  persistence_models  — durable storage snapshots (no ephemeral state)
  debug_models        — internal diagnostics and trace payloads (never user-facing)

Import from the specific sub-module for clarity.  This __init__ re-exports
only the most frequently referenced types for ergonomic in-package use.
"""

from .response_models import (
    TrackResponse,
    PlaylistResponse,
    TrackExplanationResponse,
    PlaylistRecommendationResponse,
)
from .persistence_models import (
    PersistedTrack,
    PersistedPlaylist,
    GenomeSnapshot,
    FeedbackSummary,
)
from .debug_models import (
    RecommendationTrace,
    FlowEvaluationReport,
    CalibrationReport,
    DebugPlayloadEnvelope,
)

__all__ = [
    # Response
    "TrackResponse",
    "PlaylistResponse",
    "TrackExplanationResponse",
    "PlaylistRecommendationResponse",
    # Persistence
    "PersistedTrack",
    "PersistedPlaylist",
    "GenomeSnapshot",
    "FeedbackSummary",
    # Debug
    "RecommendationTrace",
    "FlowEvaluationReport",
    "CalibrationReport",
    "DebugPlayloadEnvelope",
]
