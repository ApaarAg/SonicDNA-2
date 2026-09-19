"""
response_models.py — User-facing API response schemas.

Rules
-----
* Every field here MUST be safe to send to an untrusted client.
* No raw scores, embeddings, or graph adjacency data.
* Transient ranking artifacts (pre_embedding_score, graph_flow_bonus, …)
  are explicitly excluded at serialization time via `from_track()` / `from_playlist()`.
* Human-readable explanation fields are allowed here.
* Backward-compatible with existing dict-based API routes (use `.to_dict()`).

Design note
-----------
Dataclasses are used (not Pydantic) to keep the layer dependency-free and
import-safe even when Pydantic is unavailable.  For routes that need Pydantic
validation, adapt at the route boundary using `PlaylistResponse.to_dict()`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Field-allowlist: only these keys are forwarded to the user from a raw track
# dict produced by the recommendation pipeline.
# ---------------------------------------------------------------------------

_TRACK_PUBLIC_FIELDS: frozenset[str] = frozenset({
    # Core identity
    "id",
    "name",
    "artist",
    "album",
    "album_art",
    "image_url",
    "preview_url",
    "external_url",
    "spotify_url",
    "spotify_uri",
    "duration_ms",
    # Classification
    "source",          # "library" | "discovery" | "exploration"
    "is_new",
    "exploration",     # bool flag (not the full exploration_meta blob)
    "region",
    "region_key",
    "language",
    "mood",
    "community",
    "community_id",
    # Popularity signal (user-visible, scalar only)
    "popularity",
    "quality_score",
    # Audio features for display
    "energy",
    "valence",
    "danceability",
    "acousticness",
    "instrumentalness",
    "speechiness",
    "tempo",
    # Genre
    "genres",
    "artist_genres",
    # Explanation fields (human-readable)
    "explanation",
    "explanation_summary",
    "recommendation_reason",
})


def _safe_track(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Return only user-safe fields from a raw track dict."""
    return {k: v for k, v in raw.items() if k in _TRACK_PUBLIC_FIELDS}


# ---------------------------------------------------------------------------
# Per-track explanation (subset of explanation_engine output)
# ---------------------------------------------------------------------------

@dataclass
class TrackExplanationResponse:
    """A single per-track recommendation explanation shown to the user."""

    track_id: Optional[str] = None
    track_name: Optional[str] = None
    artist: Optional[str] = None
    primary_reason: Optional[str] = None       # e.g. "Matches your energy genome"
    reasons: List[str] = field(default_factory=list)
    source_label: Optional[str] = None         # "library" | "discovery" | "exploration"
    mood_match: Optional[str] = None
    semantic_contribution: Optional[str] = None  # "high" | "moderate" | "low"

    @classmethod
    def from_raw(cls, raw: Dict[str, Any]) -> "TrackExplanationResponse":
        """Build from the raw explanation dict produced by explanation_engine."""
        signals = raw.get("signals") or {}
        exploration_sig = signals.get("exploration") or {}
        return cls(
            track_id=raw.get("track_id"),
            track_name=raw.get("track_name"),
            artist=raw.get("artist"),
            primary_reason=raw.get("primary_reason"),
            reasons=list(raw.get("reasons") or []),
            source_label=raw.get("source"),
            mood_match=signals.get("mood"),
            semantic_contribution=signals.get("semantic_contribution"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


# ---------------------------------------------------------------------------
# Single track response (user-safe projection of a pipeline track dict)
# ---------------------------------------------------------------------------

@dataclass
class TrackResponse:
    """
    User-facing projection of a single track dict.

    Only stable, safe fields are included.  All ranking scores, embeddings,
    graph data, and debug metadata are stripped at construction time.
    """

    id: Optional[str] = None
    name: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    album_art: Optional[str] = None
    image_url: Optional[str] = None
    preview_url: Optional[str] = None
    external_url: Optional[str] = None
    spotify_url: Optional[str] = None
    spotify_uri: Optional[str] = None
    duration_ms: Optional[int] = None
    source: Optional[str] = None
    is_new: Optional[bool] = None
    exploration: Optional[bool] = None
    region: Optional[str] = None
    region_key: Optional[str] = None
    language: Optional[str] = None
    mood: Optional[str] = None
    community: Optional[str] = None
    community_id: Optional[str] = None
    popularity: Optional[float] = None
    quality_score: Optional[float] = None
    energy: Optional[float] = None
    valence: Optional[float] = None
    danceability: Optional[float] = None
    acousticness: Optional[float] = None
    instrumentalness: Optional[float] = None
    speechiness: Optional[float] = None
    tempo: Optional[float] = None
    genres: Optional[List[str]] = None
    artist_genres: Optional[List[str]] = None
    explanation: Optional[str] = None
    explanation_summary: Optional[str] = None
    recommendation_reason: Optional[str] = None

    @classmethod
    def from_track(cls, raw: Dict[str, Any]) -> "TrackResponse":
        """
        Construct from a raw pipeline track dict.
        Strips all non-public fields automatically.
        """
        safe = _safe_track(raw)
        return cls(**{k: safe.get(k) for k in cls.__dataclass_fields__})

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


# ---------------------------------------------------------------------------
# Playlist response
# ---------------------------------------------------------------------------

@dataclass
class PlaylistResponse:
    """
    User-facing playlist response envelope.

    Maps 1-to-1 with the dict currently returned by
    PlaylistGenerator.generate_regional_genome_playlist() at the serialization
    boundary — but without flow_report, recommendation_trace, graph internals,
    or any other debug/transient keys.
    """

    name: Optional[str] = None
    size: Optional[int] = None
    type: Optional[str] = None          # "regional_genome" | "pure_discovery"
    region: Optional[str] = None
    cluster_id: Optional[int] = None
    mood: Optional[str] = None
    session_type: Optional[str] = None
    discovery_ratio: Optional[float] = None
    exploration_ratio: Optional[float] = None
    target_minutes: Optional[int] = None
    actual_minutes: Optional[float] = None
    duration_target_met: Optional[bool] = None
    familiar_count: Optional[int] = None
    discovery_count: Optional[int] = None
    exploration_count: Optional[int] = None
    description: Optional[str] = None

    # Track list (sanitized)
    tracks: List[TrackResponse] = field(default_factory=list)

    # Lightweight summary characteristics — only scalar metrics
    avg_energy: Optional[float] = None
    avg_valence: Optional[float] = None
    avg_tempo: Optional[float] = None
    avg_popularity: Optional[float] = None
    total_duration_ms: Optional[int] = None
    genre_count: Optional[int] = None

    # Per-track explanations (optional, user-readable)
    recommendation_explanations: Optional[List[TrackExplanationResponse]] = None

    @classmethod
    def from_playlist(
        cls,
        raw: Dict[str, Any],
        *,
        include_explanations: bool = False,
    ) -> "PlaylistResponse":
        """
        Build a safe response from a raw playlist dict.

        Parameters
        ----------
        raw : dict
            The dict returned by PlaylistGenerator (may contain debug keys).
        include_explanations : bool
            Whether to include per-track explanation objects.
        """
        chars = raw.get("characteristics") or {}

        # Build safe track list
        tracks_raw: List[Dict[str, Any]] = raw.get("tracks") or []
        tracks = [TrackResponse.from_track(t) for t in tracks_raw]

        # Explanations — user-readable only
        explanations: Optional[List[TrackExplanationResponse]] = None
        if include_explanations:
            raw_exps = raw.get("recommendation_explanations") or []
            explanations = [TrackExplanationResponse.from_raw(e) for e in raw_exps]

        return cls(
            name=raw.get("name"),
            size=raw.get("size") or len(tracks),
            type=raw.get("type"),
            region=raw.get("region"),
            cluster_id=raw.get("cluster_id"),
            mood=raw.get("mood"),
            session_type=raw.get("session_type"),
            discovery_ratio=raw.get("discovery_ratio"),
            exploration_ratio=raw.get("exploration_ratio"),
            target_minutes=raw.get("target_minutes"),
            actual_minutes=raw.get("actual_minutes"),
            duration_target_met=raw.get("duration_target_met"),
            familiar_count=raw.get("familiar_count") or chars.get("library_count"),
            discovery_count=raw.get("discovery_count") or chars.get("discovery_count"),
            exploration_count=raw.get("exploration_count") or chars.get("exploration_count"),
            description=raw.get("description"),
            tracks=tracks,
            avg_energy=chars.get("avg_energy"),
            avg_valence=chars.get("avg_valence"),
            avg_tempo=chars.get("avg_tempo"),
            avg_popularity=chars.get("avg_popularity"),
            total_duration_ms=chars.get("total_duration_ms"),
            genre_count=chars.get("genre_count"),
            recommendation_explanations=explanations,
        )

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Tracks list is already safe dicts; keep non-None only
        d["tracks"] = [t for t in d.get("tracks", [])]
        if self.recommendation_explanations is None:
            d.pop("recommendation_explanations", None)
        return {k: v for k, v in d.items() if v is not None}


# ---------------------------------------------------------------------------
# Outer recommendation response (wraps playlist + metadata)
# ---------------------------------------------------------------------------

@dataclass
class PlaylistRecommendationResponse:
    """
    Top-level API response for a playlist recommendation endpoint.

    Wraps PlaylistResponse with request metadata and optional user-facing
    session context.  Never includes flow_report, calibration data, or debug
    payloads.
    """

    status: str = "ok"
    playlist: Optional[PlaylistResponse] = None
    user_id: Optional[str] = None
    session_type: Optional[str] = None
    generated_at: Optional[str] = None    # ISO timestamp string

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"status": self.status}
        if self.playlist is not None:
            d["playlist"] = self.playlist.to_dict()
        if self.user_id:
            d["user_id"] = self.user_id
        if self.session_type:
            d["session_type"] = self.session_type
        if self.generated_at:
            d["generated_at"] = self.generated_at
        return d
