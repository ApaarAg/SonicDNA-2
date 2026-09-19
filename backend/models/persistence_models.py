"""
persistence_models.py — Durable storage schemas.

Rules
-----
* Persistence models MUST exclude all transient/debug state.
* No raw embeddings, ranking scores, graph artifacts, or request-only fields.
* Fields here map directly to what ``persistence_sanitizer`` already strips —
  this layer makes that contract explicit and typed.
* Backward-compatible: `from_raw()` classmethod accepts the existing dict
  shapes without requiring callers to change routing or storage logic.
* `to_dict()` returns a JSON-serializable dict ready for DB insertion.

Covered entities
----------------
  PersistedTrack           — single track for playlist history storage
  PersistedPlaylist        — full playlist snapshot for history storage
  GenomeSnapshot           — genome/archetype snapshot for user timeline
  FeedbackSummary          — aggregated feedback analytics report
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Fields that are FORBIDDEN in persisted data (aligned with persistence_sanitizer)
_PERSISTENCE_BLOCKED_FIELDS: frozenset[str] = frozenset({
    "recommendation_trace",
    "graph_flow_bonus",
    "graph_weight",
    "graph_weights",
    "exploration_meta",
    "exploration_score",
    "exploration_scores",
    "temporary_exploration_score",
    "temporary_exploration_scores",
    "primary_score",
    "rank_score",
    "ranking_score",
    "final_rank_score",
    "pre_exploration_rank",
    "pre_embedding_score",
    "post_embedding_score",
    "pre_graph_score",
    "post_graph_score",
    "pre_rerank_score",
    "post_rerank_score",
    "rerank_score",
    "reranked_score",
    "user_embedding_similarity",
    "semantic_similarity",
    "embed_similarity",
    "embedding_similarity",
    "raw_embedding",
    "embedding",
    "embeddings",
    "query_embedding",
    "query_embeddings",
    "embedding_query",
    "candidate_embedding",
    "candidate_embeddings",
    "track_embedding",
    "track_embeddings",
    "user_embedding",
    "user_embeddings",
    "embedding_vector",
    "embedding_vectors",
    "candidate_pool",
    "candidate_pools",
    "candidate_tracks",
    "candidate_scores",
    "graph_adjacency",
    "adjacency",
    "neighbors",
    "neighbor_scores",
    "graph_neighbors",
    "graph_nodes",
    "graph_edges",
    "graph_distances",
    "graph_distance_scores",
    "ranking_diagnostics",
    "temporary_ranking_diagnostics",
    "diagnostics",
    "debug",
    "debug_info",
    "debug_metadata",
    "internal_cache",
    "cache",
    "cache_key",
    "cache_hit",
    "request_metadata",
    "request_meta",
    "request_only_metadata",
    # Flow report is debug-only
    "flow_report",
})

_PERSIST_TRACK_ALLOWED: frozenset[str] = frozenset({
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
    "source",
    "is_new",
    "exploration",
    "region",
    "region_key",
    "language",
    "mood",
    "community",
    "community_id",
    "popularity",
    "quality_score",
    "energy",
    "valence",
    "danceability",
    "acousticness",
    "instrumentalness",
    "speechiness",
    "tempo",
    "genres",
    "artist_genres",
    # Human-readable explanation summary is acceptable for persistence
    "explanation_summary",
    "recommendation_reason",
})


def _safe_track_for_persistence(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in raw.items() if k in _PERSIST_TRACK_ALLOWED}


# ---------------------------------------------------------------------------
# PersistedTrack
# ---------------------------------------------------------------------------

@dataclass
class PersistedTrack:
    """
    Minimal, stable track record for durable playlist history storage.

    All runtime scoring, embedding, graph, and debug fields are excluded.
    """

    id: Optional[str] = None
    name: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    image_url: Optional[str] = None
    spotify_url: Optional[str] = None
    spotify_uri: Optional[str] = None
    duration_ms: Optional[int] = None
    source: Optional[str] = None          # "library" | "discovery" | "exploration"
    is_new: Optional[bool] = None
    exploration: Optional[bool] = None
    region: Optional[str] = None
    region_key: Optional[str] = None
    community: Optional[str] = None
    community_id: Optional[str] = None
    popularity: Optional[float] = None
    energy: Optional[float] = None
    valence: Optional[float] = None
    danceability: Optional[float] = None
    tempo: Optional[float] = None
    genres: Optional[List[str]] = None
    # Human-readable reason safe for storage
    explanation_summary: Optional[str] = None
    recommendation_reason: Optional[str] = None

    @classmethod
    def from_track(cls, raw: Dict[str, Any]) -> "PersistedTrack":
        safe = _safe_track_for_persistence(raw)
        return cls(**{k: safe.get(k) for k in cls.__dataclass_fields__})

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


# ---------------------------------------------------------------------------
# PersistedPlaylist
# ---------------------------------------------------------------------------

@dataclass
class PersistedPlaylist:
    """
    Durable playlist snapshot for user history or recommendation archival.

    * Tracks are stored as PersistedTrack (no debug/runtime state).
    * flow_report, ranking diagnostics, embeddings excluded.
    * Characteristics are scalar-only (no series/arc data — those are debug).
    """

    name: Optional[str] = None
    size: Optional[int] = None
    type: Optional[str] = None
    region: Optional[str] = None
    cluster_id: Optional[int] = None
    mood: Optional[str] = None
    session_type: Optional[str] = None
    discovery_ratio: Optional[float] = None
    exploration_ratio: Optional[float] = None
    target_minutes: Optional[int] = None
    actual_minutes: Optional[float] = None
    familiar_count: Optional[int] = None
    discovery_count: Optional[int] = None
    exploration_count: Optional[int] = None
    description: Optional[str] = None

    # Summarized scalar characteristics only (no energy_series, valence_series, etc.)
    avg_energy: Optional[float] = None
    avg_valence: Optional[float] = None
    avg_tempo: Optional[float] = None
    avg_popularity: Optional[float] = None
    total_duration_ms: Optional[int] = None
    genre_count: Optional[int] = None

    tracks: List[PersistedTrack] = field(default_factory=list)

    @classmethod
    def from_playlist(cls, raw: Dict[str, Any]) -> "PersistedPlaylist":
        """
        Build a persistence-safe snapshot from a raw pipeline playlist dict.

        Safe to call immediately after PlaylistGenerator output; strips all
        debug/transient keys that persistence_sanitizer would otherwise need
        to clean at a later boundary.
        """
        chars: Dict[str, Any] = {}
        raw_chars = raw.get("characteristics")
        if isinstance(raw_chars, dict):
            # Include only scalar numeric characteristics
            chars = {
                k: v for k, v in raw_chars.items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)
                and k not in {"energy_series", "valence_series"}
            }

        tracks_raw: List[Dict[str, Any]] = raw.get("tracks") or []
        tracks = [PersistedTrack.from_track(t) for t in tracks_raw]

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
            familiar_count=raw.get("familiar_count") or chars.get("library_count"),
            discovery_count=raw.get("discovery_count") or chars.get("discovery_count"),
            exploration_count=raw.get("exploration_count") or chars.get("exploration_count"),
            description=raw.get("description"),
            avg_energy=chars.get("avg_energy"),
            avg_valence=chars.get("avg_valence"),
            avg_tempo=chars.get("avg_tempo"),
            avg_popularity=chars.get("avg_popularity"),
            total_duration_ms=chars.get("total_duration_ms"),
            genre_count=chars.get("genre_count"),
            tracks=tracks,
        )

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["tracks"] = [t for t in d.get("tracks", [])]
        return {k: v for k, v in d.items() if v is not None}

    def content_hash(self) -> str:
        """Stable content hash of track IDs — useful for deduplication."""
        ids = "|".join(
            str(t.id or t.name or "")
            for t in self.tracks
        )
        return hashlib.sha256(ids.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# GenomeSnapshot  (user timeline / profile persistence)
# ---------------------------------------------------------------------------

@dataclass
class GenomeSnapshot:
    """
    Persisted genome + archetype snapshot for a user at a point in time.

    Mirrors the fields saved by `save_genome_snapshot()` in database.py without
    carrying request-only state, embedding queries, or analysis debug info.
    """

    user_id: Optional[str] = None
    taken_at: Optional[str] = None          # ISO timestamp
    region: Optional[str] = None
    archetype_id: Optional[int] = None
    archetype_name: Optional[str] = None
    primary_pct: Optional[float] = None
    secondary_name: Optional[str] = None
    secondary_pct: Optional[float] = None
    genome: Dict[str, float] = field(default_factory=dict)    # feature → score
    cluster_id: Optional[int] = None
    source: Optional[str] = None           # "quiz" | "clips" | "adaptive" | "spotify"
    spotify_influenced: Optional[bool] = None

    @classmethod
    def from_raw(cls, raw: Dict[str, Any]) -> "GenomeSnapshot":
        """Build from the dict produced by analyze_quiz / analyze_adaptive / etc."""
        genome = {}
        for k, v in (raw.get("genome_features") or raw.get("genome") or {}).items():
            try:
                genome[k] = round(float(v), 4)
            except (TypeError, ValueError):
                pass

        return cls(
            user_id=raw.get("user_id"),
            taken_at=raw.get("taken_at"),
            region=raw.get("region"),
            archetype_id=raw.get("archetype_id") or raw.get("cluster_id"),
            archetype_name=raw.get("archetype_name") or raw.get("archetype"),
            primary_pct=raw.get("primary_pct"),
            secondary_name=raw.get("secondary_name"),
            secondary_pct=raw.get("secondary_pct"),
            genome=genome,
            cluster_id=raw.get("cluster_id"),
            source=raw.get("source"),
            spotify_influenced=bool(raw.get("spotify_taste_influence", {}).get("applied")) if raw.get("spotify_taste_influence") else None,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


# ---------------------------------------------------------------------------
# FeedbackSummary  (aggregated feedback analytics)
# ---------------------------------------------------------------------------

@dataclass
class ExplorationAcceptance:
    accepted_count: int = 0
    rejected_count: int = 0
    rated_count: int = 0
    acceptance_rate: Optional[float] = None


@dataclass
class DiscoverySuccess:
    positive_count: int = 0
    negative_count: int = 0
    rated_count: int = 0
    success_rate: Optional[float] = None


@dataclass
class PlaylistSatisfaction:
    average_rating: Optional[float] = None
    low_rating_count: int = 0
    rating_count: int = 0


@dataclass
class FeedbackSummary:
    """
    Aggregated, anonymized feedback analytics report for storage or review.

    Does NOT carry raw event arrays, canonical user identities, or individual
    feedback records — only aggregate statistics.
    """

    session_id: Optional[str] = None
    playlist_id: Optional[str] = None
    event_count: int = 0
    track_event_count: int = 0
    playlist_event_count: int = 0
    exploration_acceptance_rate: Optional[float] = None
    discovery_success_rate: Optional[float] = None
    playlist_satisfaction: Optional[PlaylistSatisfaction] = None
    exploration: Optional[ExplorationAcceptance] = None
    discovery: Optional[DiscoverySuccess] = None
    privacy_note: str = "Aggregated — no canonical identity stored"

    @classmethod
    def from_analysis(cls, report: Dict[str, Any], *, session_id: Optional[str] = None, playlist_id: Optional[str] = None) -> "FeedbackSummary":
        """
        Build from the dict returned by ``feedback_analysis.analyze_feedback()``.
        """
        raw_sat = report.get("playlist_satisfaction") or {}
        raw_exp = report.get("exploration") or {}
        raw_disc = report.get("discovery_success") or {}

        return cls(
            session_id=session_id,
            playlist_id=playlist_id,
            event_count=int(report.get("event_count") or 0),
            track_event_count=int(report.get("track_event_count") or 0),
            playlist_event_count=int(report.get("playlist_event_count") or 0),
            exploration_acceptance_rate=report.get("exploration_acceptance_rate"),
            discovery_success_rate=report.get("discovery_success_rate"),
            playlist_satisfaction=PlaylistSatisfaction(
                average_rating=raw_sat.get("average_rating"),
                low_rating_count=int(raw_sat.get("low_rating_count") or 0),
                rating_count=int(raw_sat.get("rating_count") or 0),
            ),
            exploration=ExplorationAcceptance(
                accepted_count=int(raw_exp.get("accepted_count") or 0),
                rejected_count=int(raw_exp.get("rejected_count") or 0),
                rated_count=int(raw_exp.get("rated_count") or 0),
                acceptance_rate=raw_exp.get("acceptance_rate"),
            ),
            discovery=DiscoverySuccess(
                positive_count=int(raw_disc.get("positive_count") or 0),
                negative_count=int(raw_disc.get("negative_count") or 0),
                rated_count=int(raw_disc.get("rated_count") or 0),
                success_rate=raw_disc.get("success_rate"),
            ),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}
