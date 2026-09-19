"""
Controlled semantic exploration for playlist generation.

The engine is deliberately lightweight and additive. It chooses a small number
of semantically coherent discovery tracks from an already-ranked candidate pool,
then replaces only the playlist tail so the primary recommender remains in
charge of the listening experience.
"""

from collections import Counter, deque
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    from spotify_service_fixed import canonicalize_genres, normalize_artist_name, track_fingerprint
except Exception:  # pragma: no cover
    def canonicalize_genres(genres):  # type: ignore[misc]
        raw = [genres] if isinstance(genres, str) else list(genres or [])
        return [str(g).strip().lower() for g in raw if str(g).strip()]

    def normalize_artist_name(name: str) -> str:  # type: ignore[misc]
        return str(name or "").split(",")[0].strip().lower()

    def track_fingerprint(name: str, artist: str) -> str:  # type: ignore[misc]
        return f"{str(name or '').strip().lower()}|{normalize_artist_name(artist)}"

try:
    from config.scoring_config import EXPLORATION as _ECFG
    _CONFIG_AVAILABLE = True
except ImportError:
    _CONFIG_AVAILABLE = False

# Module-level constants — sourced from config when available
DEFAULT_EXPLORATION_RATIO = _ECFG.DEFAULT_RATIO   if _CONFIG_AVAILABLE else 0.15
MAX_EXPLORATION_RATIO     = _ECFG.MAX_RATIO        if _CONFIG_AVAILABLE else 0.20
MAX_EXPLORATION_TRACKS    = _ECFG.MAX_TRACKS       if _CONFIG_AVAILABLE else 8
MIN_RELATEDNESS           = _ECFG.MIN_RELATEDNESS  if _CONFIG_AVAILABLE else 0.52
LOCAL_EDGE_THRESHOLD      = _ECFG.LOCAL_EDGE_THRESHOLD if _CONFIG_AVAILABLE else 0.68


def _clean(value) -> str:
    return str(value or "").strip().lower()


def _track_key(track: dict) -> str:
    return _clean(track.get("track_fingerprint") or track.get("id") or track_fingerprint(track.get("name", ""), track.get("artist", "")))


def _primary_artist(track: dict) -> str:
    return _clean(track.get("primary_artist_normalized") or normalize_artist_name(track.get("artist", "")))


def _genres(track: dict) -> List[str]:
    raw = track.get("canonical_genres") or track.get("artist_genres") or track.get("genres") or []
    return canonicalize_genres(raw)


def _community(track: dict) -> str:
    explicit = (
        track.get("community")
        or track.get("community_id")
        or track.get("semantic_community")
        or track.get("graph_community")
    )
    if explicit is not None:
        return _clean(explicit)
    genres = _genres(track)
    region = _clean(track.get("region") or track.get("region_key"))
    if genres and region:
        return f"{region}:{genres[0]}"
    if genres:
        return genres[0]
    return region or "unknown"


def _norm(embedding) -> Optional[Any]:
    if embedding is None:
        return None
    import numpy as np
    vec = np.asarray(embedding, dtype=np.float32)
    if vec.ndim != 1 or vec.size == 0:
        return None
    norm = float(np.linalg.norm(vec))
    if not np.isfinite(norm) or norm <= 0:
        return None
    return vec / norm


def _cosine(left, right) -> Optional[float]:
    left_vec = _norm(left)
    right_vec = _norm(right)
    if left_vec is None or right_vec is None or left_vec.shape != right_vec.shape:
        return None
    import numpy as np
    return float(np.clip(np.dot(left_vec, right_vec), -1.0, 1.0))


def _relatedness(user_embedding, candidate_embedding) -> Optional[float]:
    similarity = _cosine(user_embedding, candidate_embedding)
    if similarity is None:
        return None
    return (similarity + 1.0) / 2.0


def _adjacency_from_graph(track_graph) -> Dict[str, List[Tuple[str, float]]]:
    if track_graph is None:
        return {}
    adjacency = getattr(track_graph, "_adjacency", None)
    return adjacency if isinstance(adjacency, dict) else {}


def _graph_distance(
    candidate_id: str,
    selected_ids: set,
    adjacency: Dict[str, List[Tuple[str, float]]],
    max_depth: int = 3,
) -> Optional[int]:
    if not candidate_id or not selected_ids or not adjacency:
        return None
    queue = deque([(candidate_id, 0)])
    seen = {candidate_id}
    while queue:
        node, depth = queue.popleft()
        if depth > 0 and node in selected_ids:
            return depth
        if depth >= max_depth:
            continue
        for neighbor, _weight in adjacency.get(node, []):
            if neighbor not in seen:
                seen.add(neighbor)
                queue.append((neighbor, depth + 1))
    return None


def _local_density(
    candidate_id: str,
    selected_ids: set,
    adjacency: Dict[str, List[Tuple[str, float]]],
) -> float:
    neighbors = adjacency.get(candidate_id) or []
    strong = [node for node, weight in neighbors if weight >= LOCAL_EDGE_THRESHOLD]
    if not strong:
        return 0.0
    return sum(1 for node in strong if node in selected_ids) / len(strong)


def _graph_distance_reward(distance: Optional[int]) -> float:
    if distance == 1:
        return 0.25
    if distance == 2:
        return 1.0
    if distance == 3:
        return 0.75
    if distance is None:
        return 0.45
    return 0.0


def _bridge_score(candidate: dict, selected_communities: set, adjacency, selected_ids: set) -> float:
    candidate_community = _community(candidate)
    if not selected_communities:
        return 0.0
    community_cross = candidate_community not in selected_communities
    _cw = _ECFG.BRIDGE_CONNECTED_WEIGHT_FLOOR if _CONFIG_AVAILABLE else 0.35
    connected_selected = {
        node for node, weight in adjacency.get(_track_key(candidate), [])
        if node in selected_ids and weight >= _cw
    }
    _bcc = _ECFG.BRIDGE_CROSS_COMMUNITY_CONNECTED if _CONFIG_AVAILABLE else 1.0
    _bc  = _ECFG.BRIDGE_CROSS_COMMUNITY_ONLY      if _CONFIG_AVAILABLE else 0.65
    _bsc = _ECFG.BRIDGE_SAME_COMMUNITY_CONNECTED   if _CONFIG_AVAILABLE else 0.35
    if community_cross and connected_selected:
        return _bcc
    if community_cross:
        return _bc
    if connected_selected:
        return _bsc
    return 0.0


def _artist_diversity(candidate: dict, selected_artist_counts: Counter) -> float:
    artist = _primary_artist(candidate)
    if not artist:
        return 0.5
    count = selected_artist_counts.get(artist, 0)
    _new  = _ECFG.ARTIST_DIVERSITY_NEW  if _CONFIG_AVAILABLE else 1.0
    _once = _ECFG.ARTIST_DIVERSITY_ONCE if _CONFIG_AVAILABLE else 0.25
    _rep  = _ECFG.ARTIST_DIVERSITY_REPEAT if _CONFIG_AVAILABLE else 0.0
    if count == 0:
        return _new
    if count == 1:
        return _once
    return _rep


def _community_penalty(candidate: dict, selected_community_counts: Counter, selected_count: int) -> float:
    if selected_count <= 0:
        return 0.0
    count = selected_community_counts.get(_community(candidate), 0)
    return min(1.0, count / max(1, selected_count))


def _score_rank_signal(track: dict, max_primary_score: float) -> float:
    score = track.get("primary_score", track.get("score", track.get("quality_score", 0.0)))
    try:
        score = float(score)
    except (TypeError, ValueError):
        return 0.0
    if max_primary_score > 0:
        return max(0.0, min(1.0, score / max_primary_score))
    return max(0.0, min(1.0, score))


def _safe_primary_score(track: dict) -> float:
    try:
        return float(track.get("primary_score", track.get("score", track.get("quality_score", 0.0))) or 0.0)
    except (TypeError, ValueError):
        return 0.0


class ExplorationEngine:
    def __init__(
        self,
        exploration_ratio: float = DEFAULT_EXPLORATION_RATIO,
        min_relatedness: float = MIN_RELATEDNESS,
    ):
        self.exploration_ratio = max(0.0, min(MAX_EXPLORATION_RATIO, float(exploration_ratio)))
        self.min_relatedness = max(0.0, min(1.0, float(min_relatedness)))

    def score_candidates(
        self,
        candidates: List[dict],
        selected_tracks: List[dict],
        user_embedding=None,
        *,
        candidate_embeddings: Optional[Iterable] = None,
        track_graph=None,
    ) -> List[dict]:
        if not candidates:
            return []

        embeddings = list(candidate_embeddings) if candidate_embeddings is not None else []
        if embeddings and len(embeddings) != len(candidates):
            embeddings = embeddings[: len(candidates)]
        if not embeddings:
            embeddings = [None] * len(candidates)

        adjacency = _adjacency_from_graph(track_graph)
        selected_ids = {_track_key(track) for track in selected_tracks}
        selected_artist_counts = Counter(_primary_artist(track) for track in selected_tracks if _primary_artist(track))
        selected_community_counts = Counter(_community(track) for track in selected_tracks if _community(track))
        selected_communities = set(selected_community_counts)
        max_primary_score = max((_safe_primary_score(track) for track in candidates), default=0.0)

        scored = []
        for candidate, embedding in zip(candidates, embeddings):
            candidate_id = _track_key(candidate)
            if not candidate_id or candidate_id in selected_ids:
                continue

            relatedness = _relatedness(user_embedding, embedding)
            if user_embedding is not None and relatedness is None:
                continue
            if relatedness is not None and relatedness < self.min_relatedness:
                continue
            semantic = relatedness if relatedness is not None else (
                _ECFG.FALLBACK_SEMANTIC if _CONFIG_AVAILABLE else 0.58
            )

            graph_distance = _graph_distance(candidate_id, selected_ids, adjacency)
            graph_reward = _graph_distance_reward(graph_distance)
            bridge = _bridge_score(candidate, selected_communities, adjacency, selected_ids)
            artist_diversity = _artist_diversity(candidate, selected_artist_counts)
            local_density = _local_density(candidate_id, selected_ids, adjacency)
            community_penalty = _community_penalty(candidate, selected_community_counts, len(selected_tracks))
            repeated_artist_penalty = 1.0 - artist_diversity
            rank_signal = _score_rank_signal(candidate, max_primary_score)

            peripheral_coherence = semantic * (1.0 - min(0.75, local_density))

            if _CONFIG_AVAILABLE:
                score = (
                    semantic          * _ECFG.W_SEMANTIC
                    + graph_reward   * _ECFG.W_GRAPH
                    + bridge         * _ECFG.W_BRIDGE
                    + artist_diversity * _ECFG.W_ARTIST
                    + peripheral_coherence * _ECFG.W_PERIPHERAL
                    + rank_signal    * _ECFG.W_RANK
                    - repeated_artist_penalty * _ECFG.W_REPEAT_ARTIST
                    - local_density  * _ECFG.W_LOCAL_DENSITY
                    - community_penalty * _ECFG.W_COMMUNITY
                )
            else:
                score = (
                    semantic * 0.28
                    + graph_reward * 0.20
                    + bridge * 0.18
                    + artist_diversity * 0.14
                    + peripheral_coherence * 0.10
                    + rank_signal * 0.10
                    - repeated_artist_penalty * 0.16
                    - local_density * 0.12
                    - community_penalty * 0.10
                )

            enriched = dict(candidate)
            enriched["exploration_score"] = round(max(0.0, min(1.0, score)), 4)
            enriched["exploration_meta"] = {
                "semantic_relatedness": round(semantic, 3),
                "graph_distance": graph_distance,
                "bridge_score": round(bridge, 3),
                "artist_diversity": round(artist_diversity, 3),
                "local_density": round(local_density, 3),
                "community_penalty": round(community_penalty, 3),
                "rank_signal": round(rank_signal, 3),
            }
            scored.append(enriched)

        scored.sort(
            key=lambda track: (
                track.get("exploration_score", 0.0),
                track.get("primary_score", 0.0),
                _track_key(track),
            ),
            reverse=True,
        )
        return scored

    def inject_exploration_tracks(
        self,
        playlist_tracks: List[dict],
        candidate_pool: List[dict],
        playlist_size: Optional[int] = None,
        user_embedding=None,
        *,
        candidate_embeddings: Optional[Iterable] = None,
        track_graph=None,
        exploration_ratio: Optional[float] = None,
    ) -> List[dict]:
        target_size = int(playlist_size or len(playlist_tracks))
        if target_size < 2 or not playlist_tracks or not candidate_pool:
            return playlist_tracks

        ratio = self.exploration_ratio if exploration_ratio is None else float(exploration_ratio)
        ratio = max(0.0, min(MAX_EXPLORATION_RATIO, ratio))
        if ratio <= 0.0:
            return playlist_tracks[:target_size]

        explore_count = max(1, int(round(target_size * ratio)))
        explore_count = min(MAX_EXPLORATION_TRACKS, explore_count, target_size - 1)
        protected_count = max(1, target_size - explore_count)
        protected_tracks = playlist_tracks[:protected_count]
        original_tail = playlist_tracks[protected_count:target_size]

        scored = self.score_candidates(
            candidate_pool,
            protected_tracks,
            user_embedding=user_embedding,
            candidate_embeddings=candidate_embeddings,
            track_graph=track_graph,
        )
        if not scored:
            return playlist_tracks[:target_size]

        existing_ids = {_track_key(track) for track in protected_tracks}
        artist_counts = Counter(_primary_artist(track) for track in protected_tracks if _primary_artist(track))
        picks = []
        for candidate in scored:
            if len(picks) >= explore_count:
                break
            candidate_id = _track_key(candidate)
            artist = _primary_artist(candidate)
            if not candidate_id or candidate_id in existing_ids:
                continue
            if artist and artist_counts.get(artist, 0) >= 1:
                continue
            candidate = dict(candidate)
            candidate["source"] = candidate.get("source") or "discovery"
            candidate["exploration"] = True
            picks.append(candidate)
            existing_ids.add(candidate_id)
            if artist:
                artist_counts[artist] += 1

        if not picks:
            return playlist_tracks[:target_size]

        fallback_tail = [track for track in original_tail if _track_key(track) not in existing_ids]
        result = (protected_tracks + picks + fallback_tail)[:target_size]
        print(
            f"[exploration] injected={len(picks)} ratio={ratio:.2f} "
            f"protected={len(protected_tracks)}"
        )
        return result


def inject_exploration_tracks(
    playlist_tracks: List[dict],
    candidate_pool: List[dict],
    playlist_size: Optional[int] = None,
    user_embedding=None,
    *,
    candidate_embeddings: Optional[Iterable] = None,
    track_graph=None,
    exploration_ratio: float = DEFAULT_EXPLORATION_RATIO,
) -> List[dict]:
    return ExplorationEngine(exploration_ratio=exploration_ratio).inject_exploration_tracks(
        playlist_tracks=playlist_tracks,
        candidate_pool=candidate_pool,
        playlist_size=playlist_size,
        user_embedding=user_embedding,
        candidate_embeddings=candidate_embeddings,
        track_graph=track_graph,
        exploration_ratio=exploration_ratio,
    )
