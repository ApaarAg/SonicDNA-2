"""
Playlist comparison metrics for offline calibration.

All functions are read-only. They operate on playlist dictionaries or raw track
lists and delegate diversity, novelty, semantic, and flow checks to existing
backend evaluators where possible.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from evaluation import cosine_similarity, evaluate_playlist, playlist_overlap, ranking_consistency
from flow_evaluation import evaluate_flow

try:
    from spotify_service_fixed import canonicalize_genres, genre_families_for_genres, region_family_for_region
except Exception:  # pragma: no cover
    def canonicalize_genres(genres):  # type: ignore[misc]
        raw = [genres] if isinstance(genres, str) else list(genres or [])
        return [str(genre).strip().lower() for genre in raw if str(genre).strip()]

    def genre_families_for_genres(genres):  # type: ignore[misc]
        return []

    def region_family_for_region(region_key: str):  # type: ignore[misc]
        return str(region_key or "").strip().lower()

try:
    from track_profile_builder import build_track_profile
except Exception:  # pragma: no cover
    build_track_profile = None

Track = Mapping[str, Any]
EmbeddingFn = Callable[[Track], object]


def _tracks(value: Any) -> List[dict]:
    if isinstance(value, Mapping):
        return [dict(track) for track in value.get("tracks", [])]
    return [dict(track) for track in (value or [])]


def _track_id(track: Track) -> str:
    return str(track.get("id") or f"{track.get('name', '')}:{track.get('artist', '')}").strip().lower()


def _primary_artist(track: Track) -> str:
    return str(track.get("artist", "")).split(",")[0].strip().lower()


def _genres(track: Track) -> List[str]:
    raw = track.get("canonical_genres") or track.get("artist_genres") or track.get("genres") or []
    if isinstance(raw, str):
        raw = raw.replace("[", "").replace("]", "").replace('"', "").split(",")
    return canonicalize_genres(raw)


def _region(track: Track) -> str:
    region = str(track.get("region") or track.get("region_key") or "").strip().lower()
    if region:
        return region
    text = " ".join(_genres(track)).lower()
    for marker in ("india", "tamil", "hindi", "punjabi", "brazil", "japan", "korea", "latin", "arab"):
        if marker in text:
            return marker
    return ""


def _genre_families(track: Track) -> List[str]:
    raw = track.get("genre_families") or []
    if isinstance(raw, str):
        raw = raw.replace("[", "").replace("]", "").replace('"', "").split(",")
    families = [str(family).strip().lower() for family in raw if str(family).strip()]
    return families or genre_families_for_genres(_genres(track))


def _primary_genre_family(track: Track) -> str:
    families = _genre_families(track)
    if families:
        return families[0]
    genres = _genres(track)
    return genres[0] if genres else "unknown"


def _region_family(track: Track) -> str:
    return str(track.get("region_family") or region_family_for_region(_region(track))).strip().lower()


def _genre_tokens(track: Track) -> set:
    tokens = set()
    for genre in _genres(track):
        tokens.update(part for part in genre.replace("-", " ").split() if part)
        if genre:
            tokens.add(genre)
    return tokens


def _profile_sections(track: Track) -> Dict[str, set]:
    if build_track_profile is None:
        return {}
    text = build_track_profile(dict(track))
    sections: Dict[str, set] = {"identity": set(), "secondary": set(), "context": set()}
    current = None
    for token in text.split():
        if token in sections:
            current = token
            continue
        if current:
            sections[current].add(token)
    return sections


def _texture_terms(track: Track) -> set:
    secondary = _profile_sections(track).get("secondary", set())
    terms = {
        term for term in secondary
        if (
            "texture" in term
            or "atmosphere" in term
            or "density" in term
            or "scale" in term
            or term.startswith("ambient-")
        )
    }
    if terms:
        return terms

    # Fallback for diagnostics when the profile builder is unavailable.
    acoustic = _safe_track_float(track, "acousticness", 0.35)
    instrumental = _safe_track_float(track, "instrumentalness", 0.0)
    return {
        "organic-texture" if acoustic >= 0.55 else "synthetic-texture",
        "ambient-heavy" if instrumental >= 0.45 else "ambient-light",
    }


def _safe_track_float(track: Track, key: str, default: float = 0.0) -> float:
    try:
        value = float(track.get(key, default))
        return value if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default


def _identity_related(left: Track, right: Track) -> bool:
    left_region = _region(left)
    right_region = _region(right)
    if left_region and right_region and left_region == right_region:
        return True
    return bool(_genre_tokens(left) & _genre_tokens(right))


def _texture_related(left: Track, right: Track) -> bool:
    return bool(_texture_terms(left) & _texture_terms(right))


def _cross_region(left: Track, right: Track) -> bool:
    left_region = _region(left)
    right_region = _region(right)
    return bool(left_region and right_region and left_region != right_region)


def _cross_genre(left: Track, right: Track) -> bool:
    left_genres = _genre_tokens(left)
    right_genres = _genre_tokens(right)
    return bool(left_genres and right_genres and not (left_genres & right_genres))


def _avg_numeric(tracks: Sequence[Track], key: str) -> Optional[float]:
    values = []
    for track in tracks:
        try:
            value = float(track.get(key))
            if math.isfinite(value):
                values.append(value)
        except (TypeError, ValueError):
            continue
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _delta(left: Optional[float], right: Optional[float]) -> Optional[float]:
    if left is None or right is None:
        return None
    return round(right - left, 4)


def _flatten_numbers(data: Mapping[str, Any], prefix: str = "") -> Dict[str, float]:
    flat: Dict[str, float] = {}
    for key, value in data.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, Mapping):
            flat.update(_flatten_numbers(value, name))
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            flat[name] = float(value)
    return flat


def _metric_deltas(left: Mapping[str, Any], right: Mapping[str, Any]) -> Dict[str, float]:
    left_flat = _flatten_numbers(left)
    right_flat = _flatten_numbers(right)
    return {
        key: round(right_flat[key] - left_flat[key], 4)
        for key in sorted(left_flat.keys() & right_flat.keys())
    }


def _explanation_trace_summary(playlist: Mapping[str, Any]) -> dict:
    explanations = playlist.get("recommendation_explanations") or []
    reason_counts: Counter[str] = Counter()
    semantic_levels: Counter[str] = Counter()
    exploration_count = 0
    for item in explanations:
        for reason in item.get("reasons", []):
            reason_counts[str(reason)] += 1
        signals = item.get("signals") or {}
        level = signals.get("semantic_contribution")
        if level:
            semantic_levels[str(level)] += 1
        if (signals.get("exploration") or {}).get("injected"):
            exploration_count += 1
    return {
        "explanation_count": len(explanations),
        "top_reasons": reason_counts.most_common(8),
        "semantic_contribution_counts": dict(semantic_levels),
        "explained_exploration_count": exploration_count,
    }


def _diversity_profile(tracks: Sequence[Track], evaluation_report: Mapping[str, Any]) -> dict:
    diversity = dict(evaluation_report.get("diversity") or {})
    novelty = dict(evaluation_report.get("novelty") or {})
    return {
        **diversity,
        **{f"novelty.{key}": value for key, value in novelty.items()},
        "unique_track_ratio": round(len({_track_id(t) for t in tracks if _track_id(t)}) / max(1, len(tracks)), 3),
        "artist_repeat_count": sum(max(0, count - 1) for count in Counter(_primary_artist(t) for t in tracks if _primary_artist(t)).values()),
        "genre_count": len({genre for track in tracks for genre in _genres(track)}),
        "avg_popularity": _avg_numeric(tracks, "popularity"),
    }


def _semantic_trace_profile(tracks: Sequence[Track], evaluation_report: Mapping[str, Any]) -> dict:
    trace_scores = [
        score
        for score in (_avg_numeric([track], "user_embedding_similarity") for track in tracks)
        if score is not None
    ]
    if not trace_scores:
        trace_scores = [
            float((track.get("recommendation_trace") or {}).get("semantic_similarity"))
            for track in tracks
            if isinstance((track.get("recommendation_trace") or {}).get("semantic_similarity"), (int, float))
        ]
    semantic = dict(evaluation_report.get("semantic") or {})
    return {
        **semantic,
        "avg_trace_semantic_similarity": round(sum(trace_scores) / len(trace_scores), 3) if trace_scores else None,
        "semantic_trace_coverage": round(len(trace_scores) / max(1, len(tracks)), 3),
    }


def _normalised_embedding(embedding) -> Optional[List[float]]:
    if embedding is None:
        return None
    try:
        values = embedding.tolist() if hasattr(embedding, "tolist") else list(embedding)
        vector = [float(value) for value in values]
    except Exception:
        return None
    if not vector or any(not math.isfinite(value) for value in vector):
        return None
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0.0:
        return None
    return [value / norm for value in vector]


def _collect_embeddings(
    tracks: Sequence[Track],
    track_embedding_fn: Optional[EmbeddingFn],
) -> List[Tuple[int, List[float]]]:
    if track_embedding_fn is None:
        return []
    vectors: List[Tuple[int, List[float]]] = []
    for index, track in enumerate(tracks):
        try:
            vector = _normalised_embedding(track_embedding_fn(track))
        except Exception:
            vector = None
        if vector is not None:
            vectors.append((index, vector))
    if not vectors:
        return []
    width = len(vectors[0][1])
    return [(index, vector) for index, vector in vectors if len(vector) == width]


def _similarity_01(left: List[float], right: List[float]) -> float:
    return (cosine_similarity(left, right) + 1.0) / 2.0


def _nearest_neighbor_pairs(vectors: Sequence[Tuple[int, List[float]]]) -> List[Tuple[int, int, float]]:
    pairs = []
    for index, vector in vectors:
        best: Optional[Tuple[int, float]] = None
        for other_index, other_vector in vectors:
            if other_index == index:
                continue
            score = _similarity_01(vector, other_vector)
            if best is None or score > best[1] or (score == best[1] and other_index < best[0]):
                best = (other_index, score)
        if best is not None:
            pairs.append((index, best[0], best[1]))
    return pairs


def _pairwise_embedding_diversity(vectors: Sequence[Tuple[int, List[float]]]) -> Optional[float]:
    distances = []
    for left_pos in range(len(vectors)):
        for right_pos in range(left_pos + 1, len(vectors)):
            distances.append(1.0 - _similarity_01(vectors[left_pos][1], vectors[right_pos][1]))
    if not distances:
        return None
    return round(sum(distances) / len(distances), 3)


def _ratio(count: int, total: int) -> Optional[float]:
    if total <= 0:
        return None
    return round(count / total, 3)


def _community_key(track: Track) -> str:
    region = _region(track) or "unknown"
    genres = _genres(track)
    primary_genre = genres[0] if genres else "unknown"
    return f"{region}:{primary_genre}"


def _dominant_community(tracks: Sequence[Track]) -> str:
    communities = [_community_key(track) for track in tracks if not _is_exploration_track(track)]
    if not communities:
        communities = [_community_key(track) for track in tracks]
    return Counter(communities).most_common(1)[0][0] if communities else "unknown"


def _is_exploration_track(track: Track) -> bool:
    if track.get("exploration"):
        return True
    source = str(track.get("source") or "").strip().lower()
    return source == "discovery" and bool(track.get("exploration_meta"))


def _exploration_tracks(tracks: Sequence[Track]) -> List[Track]:
    return [track for track in tracks if _is_exploration_track(track)]


def _exploration_archetype(track: Track) -> str:
    region = _region(track) or "unknown"
    genres = _genres(track)
    primary_genre = genres[0] if genres else "unknown"
    texture = sorted(_texture_terms(track))
    texture_key = "+".join(texture[:2]) if texture else "unknown-texture"
    return f"{region}:{primary_genre}:{texture_key}"


def _novelty_value(track: Track) -> Optional[float]:
    try:
        popularity = float(track.get("popularity"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(popularity):
        return None
    return max(0.0, min(1.0, 1.0 - max(0.0, min(100.0, popularity)) / 100.0))


def _counter_reuse_score(values: Sequence[str]) -> Optional[float]:
    values = [value for value in values if value]
    if not values:
        return None
    return round(Counter(values).most_common(1)[0][1] / len(values), 3)


def _counter_repeat_ratio(values: Sequence[str]) -> Optional[float]:
    values = [value for value in values if value]
    if not values:
        return None
    repeats = sum(max(0, count - 1) for count in Counter(values).values())
    return round(repeats / len(values), 3)


def _long_horizon_exploration_profile(track_sets: Sequence[Sequence[Track]]) -> dict:
    session_count = len(track_sets)
    per_session_exploration = [_exploration_tracks(tracks) for tracks in track_sets]
    exploration_sessions = sum(1 for tracks in per_session_exploration if tracks)
    all_exploration = [track for tracks in per_session_exploration for track in tracks]
    total_exploration = len(all_exploration)

    if session_count == 0:
        return {
            "session_count": 0,
            "exploration_track_count": 0,
            "exploration_session_coverage": 0.0,
            "cross_session_exploration_diversity": None,
            "semantic_corridor_reuse_score": None,
            "recurring_exploration_archetype_score": None,
            "novelty_decay": None,
            "bridge_region_reuse_score": None,
            "long_term_semantic_attractor_score": None,
            "flags": [],
        }

    if total_exploration == 0:
        return {
            "session_count": session_count,
            "exploration_track_count": 0,
            "exploration_session_coverage": 0.0,
            "cross_session_exploration_diversity": 0.0,
            "semantic_corridor_reuse_score": None,
            "recurring_exploration_archetype_score": None,
            "novelty_decay": None,
            "bridge_region_reuse_score": None,
            "long_term_semantic_attractor_score": None,
            "flags": ["no_long_horizon_exploration"],
        }

    corridors = []
    bridge_regions = []
    archetypes = []
    communities = []
    novelty_by_session = []
    for tracks, exploration_tracks in zip(track_sets, per_session_exploration):
        source_community = _dominant_community(tracks)
        session_novelty = []
        for track in exploration_tracks:
            target_community = _community_key(track)
            corridors.append(f"{source_community}->{target_community}")
            archetypes.append(_exploration_archetype(track))
            communities.append(target_community)
            region = _region(track)
            if region:
                bridge_regions.append(region)
            novelty = _novelty_value(track)
            if novelty is not None:
                session_novelty.append(novelty)
        if session_novelty:
            novelty_by_session.append(sum(session_novelty) / len(session_novelty))

    unique_exploration = len({_track_id(track) for track in all_exploration if _track_id(track)})
    exploration_diversity = round(unique_exploration / total_exploration, 3)
    corridor_reuse = _counter_reuse_score(corridors)
    archetype_recurrence = _counter_reuse_score(archetypes)
    bridge_region_reuse = _counter_reuse_score(bridge_regions)
    attractor_score = max(
        value for value in (
            _counter_reuse_score(communities),
            _counter_reuse_score(archetypes),
            corridor_reuse,
        )
        if value is not None
    )

    novelty_decay = None
    if len(novelty_by_session) >= 2:
        midpoint = max(1, len(novelty_by_session) // 2)
        early = novelty_by_session[:midpoint]
        late = novelty_by_session[midpoint:]
        if late:
            novelty_decay = round((sum(early) / len(early)) - (sum(late) / len(late)), 3)

    flags = []
    if corridor_reuse is not None and corridor_reuse >= 0.60 and len(set(corridors)) < len(corridors):
        flags.append("semantic_corridor_reuse")
    if archetype_recurrence is not None and archetype_recurrence >= 0.60:
        flags.append("recurring_exploration_archetype")
    if novelty_decay is not None and novelty_decay > 0.08:
        flags.append("novelty_decay")
    if bridge_region_reuse is not None and bridge_region_reuse >= 0.60 and len(set(bridge_regions)) < len(bridge_regions):
        flags.append("bridge_region_reuse")
    if attractor_score is not None and attractor_score >= 0.60:
        flags.append("long_term_semantic_attractor")

    return {
        "session_count": session_count,
        "exploration_track_count": total_exploration,
        "exploration_session_coverage": round(exploration_sessions / max(1, session_count), 3),
        "cross_session_exploration_diversity": exploration_diversity,
        "semantic_corridor_reuse_score": corridor_reuse,
        "recurring_exploration_archetype_score": archetype_recurrence,
        "novelty_decay": novelty_decay,
        "bridge_region_reuse_score": bridge_region_reuse,
        "long_term_semantic_attractor_score": attractor_score,
        "unique_corridor_count": len(set(corridors)),
        "unique_exploration_archetype_count": len(set(archetypes)),
        "flags": flags,
    }


def _topology_diagnostics_profile(track_sets: Sequence[Sequence[Track]]) -> dict:
    """Offline-only topology behavior summary for repeated discovery runs."""
    session_count = len(track_sets)
    per_session_exploration = [_exploration_tracks(tracks) for tracks in track_sets]
    all_exploration = [track for tracks in per_session_exploration for track in tracks]
    total_exploration = len(all_exploration)
    if total_exploration == 0:
        return {
            "session_count": session_count,
            "exploration_track_count": 0,
            "cross_family_exploration_diversity": 0.0,
            "macro_family_overconcentration_score": None,
            "bridge_genre_overreliance_score": None,
            "regional_permeability_balance": None,
            "semantic_shortcut_collapse_score": None,
            "culturally_meaningful_crossover_quality": None,
            "flags": ["no_topology_exploration"],
        }

    families = [_primary_genre_family(track) for track in all_exploration]
    family_counts = Counter(families)
    cross_family_diversity = round(len(set(families)) / total_exploration, 3)
    macro_overconcentration = round(family_counts.most_common(1)[0][1] / total_exploration, 3)

    bridge_tracks = []
    cultural_crossover_hits = 0
    cultural_crossover_total = 0
    permeability_events = 0
    permeable_events = 0
    strong_shortcut_events = 0
    for source_tracks, exploration_tracks in zip(track_sets, per_session_exploration):
        source_regions = [_region(track) for track in source_tracks if not _is_exploration_track(track) and _region(track)]
        source_region_families = [
            _region_family(track)
            for track in source_tracks
            if not _is_exploration_track(track) and _region_family(track)
        ]
        source_genre_families = [
            _primary_genre_family(track)
            for track in source_tracks
            if not _is_exploration_track(track)
        ]
        dominant_region = Counter(source_regions).most_common(1)[0][0] if source_regions else ""
        dominant_region_family = Counter(source_region_families).most_common(1)[0][0] if source_region_families else ""
        dominant_genre_family = Counter(source_genre_families).most_common(1)[0][0] if source_genre_families else ""
        for track in exploration_tracks:
            meta = track.get("exploration_meta") or {}
            try:
                bridge = float(meta.get("bridge_score", 0.0) or 0.0)
            except (TypeError, ValueError):
                bridge = 0.0
            try:
                relatedness = float(meta.get("semantic_relatedness", 0.0) or 0.0)
            except (TypeError, ValueError):
                relatedness = 0.0
            if bridge >= 0.65:
                bridge_tracks.append(track)

            region = _region(track)
            region_family = _region_family(track)
            family = _primary_genre_family(track)
            is_cross_region = bool(dominant_region and region and region != dominant_region)
            is_same_macro_region = bool(dominant_region_family and region_family and region_family == dominant_region_family)
            if is_cross_region:
                permeability_events += 1
                if bridge >= 0.35 or relatedness >= 0.52 or is_same_macro_region:
                    permeable_events += 1
                cultural_crossover_total += 1
                is_cross_family = family != dominant_genre_family
                if (is_cross_family or is_same_macro_region) and (bridge >= 0.35 or relatedness >= 0.52):
                    cultural_crossover_hits += 1
            if bridge >= 0.65 and relatedness >= 0.65 and (
                family == dominant_genre_family or is_same_macro_region
            ):
                strong_shortcut_events += 1

    if bridge_tracks:
        bridge_families = [_primary_genre_family(track) for track in bridge_tracks]
        bridge_overreliance = round(Counter(bridge_families).most_common(1)[0][1] / len(bridge_families), 3)
    else:
        bridge_overreliance = 0.0
    regional_permeability = _ratio(permeable_events, permeability_events)
    cultural_quality = _ratio(cultural_crossover_hits, cultural_crossover_total)
    shortcut_concentration = _ratio(strong_shortcut_events, total_exploration) or 0.0
    semantic_shortcut_collapse = round(
        max(shortcut_concentration, macro_overconcentration * bridge_overreliance),
        3,
    )

    flags = []
    if macro_overconcentration >= 0.70 and total_exploration >= 3:
        flags.append("macro_family_overconcentration")
    if bridge_overreliance >= 0.70 and len(bridge_tracks) >= 3:
        flags.append("bridge_genre_overreliance")
    if regional_permeability is not None and regional_permeability < 0.45:
        flags.append("low_regional_permeability")
    if semantic_shortcut_collapse >= 0.70 and total_exploration >= 3:
        flags.append("semantic_shortcut_collapse")
    if cultural_quality is not None and cultural_quality < 0.45:
        flags.append("weak_culturally_meaningful_crossover")

    return {
        "session_count": session_count,
        "exploration_track_count": total_exploration,
        "cross_family_exploration_diversity": cross_family_diversity,
        "macro_family_overconcentration_score": macro_overconcentration,
        "bridge_genre_overreliance_score": bridge_overreliance,
        "regional_permeability_balance": regional_permeability,
        "semantic_shortcut_collapse_score": semantic_shortcut_collapse,
        "culturally_meaningful_crossover_quality": cultural_quality,
        "unique_genre_family_count": len(set(families)),
        "bridge_track_count": len(bridge_tracks),
        "permeability_event_count": permeability_events,
        "flags": flags,
    }


def _semantic_balance_profile(
    tracks: Sequence[Track],
    *,
    track_embedding_fn: Optional[EmbeddingFn] = None,
) -> dict:
    vectors = _collect_embeddings(tracks, track_embedding_fn)
    coverage = round(len(vectors) / max(1, len(tracks)), 3)
    if len(vectors) < 2:
        return {
            "embedding_coverage": coverage,
            "embedding_neighborhood_diversity": None,
            "avg_nearest_neighbor_similarity": None,
            "identity_neighbor_share": None,
            "identity_overdominance_score": None,
            "texture_neighbor_share": None,
            "texture_underutilization_score": None,
            "semantic_basin_collapse_score": None,
            "cross_region_discovery_connectivity": _cross_region_discovery_connectivity(tracks, []),
            "cross_genre_texture_coherent_retrieval": None,
            "flags": ["missing_embeddings"] if tracks else [],
        }

    diversity = _pairwise_embedding_diversity(vectors)
    nearest = _nearest_neighbor_pairs(vectors)
    nearest_count = len(nearest)
    avg_nearest = round(sum(score for _left, _right, score in nearest) / nearest_count, 3) if nearest else None

    identity_neighbor_count = sum(1 for left, right, _score in nearest if _identity_related(tracks[left], tracks[right]))
    texture_neighbor_count = sum(1 for left, right, _score in nearest if _texture_related(tracks[left], tracks[right]))
    cross_genre_texture_count = sum(
        1 for left, right, _score in nearest
        if _cross_genre(tracks[left], tracks[right]) and _texture_related(tracks[left], tracks[right])
    )
    identity_share = _ratio(identity_neighbor_count, nearest_count)
    texture_share = _ratio(texture_neighbor_count, nearest_count)
    cross_genre_texture = _ratio(cross_genre_texture_count, nearest_count)

    texture_candidate_total = 0
    texture_candidate_hits = 0
    for left_pos in range(len(tracks)):
        for right_pos in range(left_pos + 1, len(tracks)):
            if _cross_genre(tracks[left_pos], tracks[right_pos]):
                texture_candidate_total += 1
                if _texture_related(tracks[left_pos], tracks[right_pos]):
                    texture_candidate_hits += 1
    texture_candidate_share = _ratio(texture_candidate_hits, texture_candidate_total) or 0.0

    diversity_value = diversity if diversity is not None else 0.0
    nearest_value = avg_nearest if avg_nearest is not None else 0.0
    identity_value = identity_share if identity_share is not None else 0.0
    texture_value = texture_share if texture_share is not None else 0.0
    identity_overdominance = round(identity_value * max(0.0, 1.0 - diversity_value), 3)
    texture_underuse = round(max(0.0, texture_candidate_share - texture_value), 3)
    basin_collapse = round(nearest_value * max(0.0, 1.0 - diversity_value), 3)
    flags = []
    if identity_overdominance >= 0.40:
        flags.append("identity_overdominance")
    if texture_underuse >= 0.20:
        flags.append("texture_underutilization")
    if basin_collapse >= 0.75 and diversity_value <= 0.20:
        flags.append("semantic_basin_collapse")

    return {
        "embedding_coverage": coverage,
        "embedding_neighborhood_diversity": diversity,
        "avg_nearest_neighbor_similarity": avg_nearest,
        "identity_neighbor_share": identity_share,
        "identity_overdominance_score": identity_overdominance,
        "texture_neighbor_share": texture_share,
        "texture_underutilization_score": texture_underuse,
        "semantic_basin_collapse_score": basin_collapse,
        "cross_region_discovery_connectivity": _cross_region_discovery_connectivity(tracks, nearest),
        "cross_genre_texture_coherent_retrieval": cross_genre_texture,
        "flags": flags,
    }


def _cross_region_discovery_connectivity(
    tracks: Sequence[Track],
    nearest: Sequence[Tuple[int, int, float]],
) -> Optional[float]:
    exploration_indexes = [index for index, track in enumerate(tracks) if track.get("exploration")]
    if not exploration_indexes:
        return None
    base_regions = [
        _region(track) for track in tracks
        if not track.get("exploration") and _region(track)
    ]
    dominant_region = Counter(base_regions).most_common(1)[0][0] if base_regions else ""
    nearest_by_index = {left: score for left, _right, score in nearest}
    connected = 0
    eligible = 0
    for index in exploration_indexes:
        track = tracks[index]
        region = _region(track)
        if dominant_region and region and region == dominant_region:
            continue
        eligible += 1
        meta = track.get("exploration_meta") or {}
        relatedness = meta.get("semantic_relatedness")
        try:
            relatedness_value = float(relatedness)
        except (TypeError, ValueError):
            relatedness_value = nearest_by_index.get(index, 0.0)
        bridge = meta.get("bridge_score")
        try:
            bridge_value = float(bridge)
        except (TypeError, ValueError):
            bridge_value = 0.0
        if relatedness_value >= 0.52 or bridge_value >= 0.35 or nearest_by_index.get(index, 0.0) >= 0.52:
            connected += 1
    return _ratio(connected, eligible)


def compare_playlists(
    playlist_a: Any,
    playlist_b: Any,
    *,
    session_type: Optional[str] = None,
    user_embedding_a=None,
    user_embedding_b=None,
    track_embedding_fn: Optional[EmbeddingFn] = None,
) -> dict:
    """Return an offline structured comparison report for two playlists."""
    tracks_a = _tracks(playlist_a)
    tracks_b = _tracks(playlist_b)

    eval_a = evaluate_playlist(tracks_a, user_embedding=user_embedding_a, track_embedding_fn=track_embedding_fn)
    eval_b = evaluate_playlist(tracks_b, user_embedding=user_embedding_b, track_embedding_fn=track_embedding_fn)
    flow_a = evaluate_flow(tracks_a, session_type=session_type)
    flow_b = evaluate_flow(tracks_b, session_type=session_type)
    diversity_a = _diversity_profile(tracks_a, eval_a)
    diversity_b = _diversity_profile(tracks_b, eval_b)
    semantic_a = _semantic_trace_profile(tracks_a, eval_a)
    semantic_b = _semantic_trace_profile(tracks_b, eval_b)
    semantic_balance_a = _semantic_balance_profile(tracks_a, track_embedding_fn=track_embedding_fn)
    semantic_balance_b = _semantic_balance_profile(tracks_b, track_embedding_fn=track_embedding_fn)

    overlap = playlist_overlap(tracks_a, tracks_b)
    flow_score_a = flow_a.get("flow_quality", {}).get("overall_flow_score")
    flow_score_b = flow_b.get("flow_quality", {}).get("overall_flow_score")

    return {
        "playlist_a": {
            "track_count": len(tracks_a),
            "flow_quality": flow_a.get("flow_quality", {}),
            "diversity": diversity_a,
            "semantic": semantic_a,
            "semantic_balance": semantic_balance_a,
            "explanations": _explanation_trace_summary(playlist_a) if isinstance(playlist_a, Mapping) else {},
        },
        "playlist_b": {
            "track_count": len(tracks_b),
            "flow_quality": flow_b.get("flow_quality", {}),
            "diversity": diversity_b,
            "semantic": semantic_b,
            "semantic_balance": semantic_balance_b,
            "explanations": _explanation_trace_summary(playlist_b) if isinstance(playlist_b, Mapping) else {},
        },
        "metric_deltas": {
            **{f"diversity.{k}": v for k, v in _metric_deltas(diversity_a, diversity_b).items()},
            **{f"semantic.{k}": v for k, v in _metric_deltas(semantic_a, semantic_b).items()},
            **{f"semantic_balance.{k}": v for k, v in _metric_deltas(semantic_balance_a, semantic_balance_b).items()},
            **{f"flow.{k}": v for k, v in _metric_deltas(flow_a.get("flow_quality", {}), flow_b.get("flow_quality", {})).items()},
        },
        "playlist_overlap": overlap,
        "flow_quality_delta": _delta(flow_score_a, flow_score_b),
        "diversity_delta": _metric_deltas(diversity_a, diversity_b),
        "semantic_consistency": {
            "config_a": semantic_a,
            "config_b": semantic_b,
            "delta": _metric_deltas(semantic_a, semantic_b),
        },
        "semantic_balance": {
            "config_a": semantic_balance_a,
            "config_b": semantic_balance_b,
            "delta": _metric_deltas(semantic_balance_a, semantic_balance_b),
        },
        "recommendation_stability": {
            "same_order_ratio": ranking_consistency(tracks_a, tracks_b).get("same_order_ratio"),
            "deterministic": ranking_consistency(tracks_a, tracks_b).get("deterministic"),
            "overlap": overlap,
        },
        "flow_reports": {
            "config_a": flow_a,
            "config_b": flow_b,
        },
    }


def compare_repeated_runs(playlists: Sequence[Any], *, session_type: Optional[str] = None) -> dict:
    """Summarize recommendation stability across repeated offline runs."""
    track_sets = [_tracks(playlist) for playlist in playlists]
    long_horizon = _long_horizon_exploration_profile(track_sets)
    topology = _topology_diagnostics_profile(track_sets)
    if len(track_sets) < 2:
        return {
            "run_count": len(track_sets),
            "average_overlap": 1.0,
            "average_same_order_ratio": 1.0,
            "long_horizon_exploration": long_horizon,
            "topology_diagnostics": topology,
        }
    overlaps = []
    order_ratios = []
    for index in range(1, len(track_sets)):
        comparison = compare_playlists(track_sets[0], track_sets[index], session_type=session_type)
        overlaps.append(comparison["playlist_overlap"])
        order_ratios.append(comparison["recommendation_stability"]["same_order_ratio"])
    return {
        "run_count": len(track_sets),
        "average_overlap": round(sum(overlaps) / len(overlaps), 3),
        "minimum_overlap": round(min(overlaps), 3),
        "average_same_order_ratio": round(sum(order_ratios) / len(order_ratios), 3),
        "deterministic": all(ratio == 1.0 for ratio in order_ratios),
        "long_horizon_exploration": long_horizon,
        "topology_diagnostics": topology,
    }
