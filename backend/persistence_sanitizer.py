"""
Sanitizers for crossing persistence boundaries.

Recommendation objects are intentionally rich while they are in memory: they may
carry traces, graph bonuses, embeddings, candidate pools, and debug metadata.
This module strips that ephemeral state before data is persisted or queued.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


TRANSIENT_FIELD_NAMES = {
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
}

TRANSIENT_KEY_PARTS = (
    "raw_embedding",
    "query_embedding",
    "candidate_embedding",
    "temporary_ranking",
    "ranking_diagnostic",
    "request_only",
)


def _is_transient_key(key: Any) -> bool:
    if not isinstance(key, str):
        return False

    normalized = key.strip().lower()
    if not normalized:
        return False
    if normalized in TRANSIENT_FIELD_NAMES:
        return True
    if normalized.startswith("_"):
        return True
    if normalized.endswith("_cache") or normalized.endswith("_diagnostics"):
        return True
    if normalized.endswith("_adjacency"):
        return True
    if normalized.startswith("pre_") and normalized.endswith("_score"):
        return True
    if normalized.startswith("post_") and normalized.endswith("_score"):
        return True
    return any(part in normalized for part in TRANSIENT_KEY_PARTS)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item)
            for key, item in value.items()
        }
    if hasattr(value, "tolist"):
        return _json_safe(value.tolist())
    return str(value)


def _strip_transient(value: Any) -> Any:
    if isinstance(value, Mapping):
        clean = {}
        for key, item in value.items():
            if _is_transient_key(key):
                continue
            clean[key] = _strip_transient(item)
        return clean

    if isinstance(value, list):
        return [_strip_transient(item) for item in value]

    if isinstance(value, tuple):
        return [_strip_transient(item) for item in value]

    return _json_safe(value)


def sanitize_track_for_response(track: Any) -> dict:
    """
    Return a copy of a track without raw/internal runtime state.

    This is intentionally not wired into live playlist responses yet; response
    behavior remains controlled by existing routes. It is available for future
    response envelopes that need an explicit public boundary.
    """
    if not isinstance(track, Mapping):
        return {}
    return _strip_transient(track)


def sanitize_track_for_persistence(track: Any) -> dict:
    """
    Return a track safe for durable playlist/history storage.

    Stable user-visible metadata is preserved, including names, artists, images,
    Spotify URLs, durations, genre labels, and explicit explanation summaries.
    Runtime scoring, graph, embedding, cache, and request-only fields are removed.
    """
    if not isinstance(track, Mapping):
        return {}
    return _strip_transient(track)


def sanitize_playlist_for_persistence(playlist: Any) -> Any:
    """
    Strip transient state from a playlist before persistence.

    Accepts either a playlist dict with a `tracks` list or a bare list of track
    dicts, matching the current legacy `generated_playlists` save helper.
    """
    if isinstance(playlist, list):
        return [sanitize_track_for_persistence(track) for track in playlist]

    if not isinstance(playlist, Mapping):
        return playlist

    clean = _strip_transient(playlist)
    tracks = clean.get("tracks")
    if isinstance(tracks, list):
        clean["tracks"] = [sanitize_track_for_persistence(track) for track in tracks]
    return clean


def sanitize_snapshot_payload(snapshot: Any) -> dict:
    """
    Strip request/debug state from a profile payload before snapshot persistence.
    """
    if not isinstance(snapshot, Mapping):
        return {}
    return _strip_transient(snapshot)


def sanitize_email_payload(payload: Any) -> Any:
    """
    Strip transient state from data that will be queued for email delivery.
    """
    return _strip_transient(payload)


def sanitize_share_payload(payload: Any) -> Any:
    """
    Strip transient state from share-link payloads before they leave the owner.
    """
    return _strip_transient(payload)

