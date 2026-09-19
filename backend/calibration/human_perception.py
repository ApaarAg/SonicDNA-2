"""
Offline human-perception calibration utilities.

This module compares structured human review forms against existing objective
playlist metrics. It is advisory only: it does not mutate playlists, tune
weights, persist feedback, or feed recommendation behavior.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from evaluation import evaluate_playlist
from flow_evaluation import evaluate_flow

from .playlist_diff import _tracks


PERCEPTION_DIMENSIONS = (
    "overall_quality",
    "discovery_magic",
    "emotional_realism",
    "memorability",
    "subjective_coherence",
    "perceived_novelty",
)

PERCEPTUAL_STRESS_TEST_SCENARIOS = (
    "perceived_discovery_quality_probe",
    "emotional_realism_probe",
    "memorability_probe",
    "subjective_coherence_probe",
)

LOW_HUMAN_SCORE = 0.45
HIGH_METRIC_SCORE = 0.70
DISAGREEMENT_GAP = 0.28


def _clamp01(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return round(max(0.0, min(1.0, number)), 3)


def _rating01(value: Any, scale: float) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    if scale > 1.0:
        return _clamp01(number / scale)
    return _clamp01(number)


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return number


def _average(values: Iterable[Optional[float]]) -> Optional[float]:
    numeric = [float(value) for value in values if isinstance(value, (int, float))]
    if not numeric:
        return None
    return round(sum(numeric) / len(numeric), 3)


def _weighted(items: Sequence[tuple[Optional[float], float]]) -> Optional[float]:
    usable = [(value, weight) for value, weight in items if value is not None and weight > 0]
    if not usable:
        return None
    total_weight = sum(weight for _value, weight in usable)
    return round(sum(float(value) * weight for value, weight in usable) / total_weight, 3)


def _primary_artist(track: Mapping[str, Any]) -> str:
    return str(track.get("artist", "")).split(",")[0].strip().lower()


def _is_discovery(track: Mapping[str, Any]) -> bool:
    source = str(track.get("source") or "").strip().lower()
    return bool(track.get("exploration")) or source in {"discovery", "exploration"}


def _discovery_tracks(tracks: Sequence[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    return [track for track in tracks if _is_discovery(track)]


def _trace_semantic_score(tracks: Sequence[Mapping[str, Any]], evaluation_report: Mapping[str, Any]) -> Optional[float]:
    trace_scores = []
    for track in tracks:
        trace = track.get("recommendation_trace") or {}
        score = _safe_float(track.get("user_embedding_similarity"))
        if score is None:
            score = _safe_float(trace.get("semantic_similarity"))
        if score is not None:
            trace_scores.append(_clamp01(score, 0.0))
    if trace_scores:
        return _average(trace_scores)
    semantic = evaluation_report.get("semantic") or {}
    return _clamp01(semantic.get("semantic_match"))


def _arc_variation_score(arc: Mapping[str, Any]) -> float:
    energy_var = _safe_float(arc.get("energy_variance"), 0.0) or 0.0
    valence_var = _safe_float(arc.get("valence_variance"), 0.0) or 0.0
    # Human-feeling emotional arcs usually need some contour but not chaos.
    return round(max(0.0, min(1.0, (energy_var + valence_var) / 0.12)), 3)


def _discovery_profile(tracks: Sequence[Mapping[str, Any]], flow_report: Mapping[str, Any]) -> Dict[str, Any]:
    discoveries = _discovery_tracks(tracks)
    bridge_scores = []
    relatedness_scores = []
    novelty_scores = []
    artists = []
    for track in discoveries:
        meta = track.get("exploration_meta") or {}
        bridge_scores.append(_clamp01(meta.get("bridge_score"), 0.0))
        relatedness_scores.append(_clamp01(meta.get("semantic_relatedness"), 0.0))
        popularity = _safe_float(track.get("popularity"))
        if popularity is not None:
            novelty_scores.append(max(0.0, min(1.0, 1.0 - max(0.0, min(100.0, popularity)) / 100.0)))
        artist = _primary_artist(track)
        if artist:
            artists.append(artist)

    exploration_metrics = flow_report.get("exploration_metrics") or {}
    count = len(discoveries)
    artist_diversity = round(len(set(artists)) / max(1, len(artists)), 3) if artists else None
    bridge_mean = _average(bridge_scores)
    relatedness_mean = _average(relatedness_scores)
    meaningful_bridge = _weighted(((bridge_mean, 0.5), (relatedness_mean, 0.5)))
    return {
        "discovery_count": count,
        "discovery_ratio": round(count / max(1, len(tracks)), 3),
        "flow_exploration_ratio": exploration_metrics.get("exploration_ratio"),
        "exploration_spread": exploration_metrics.get("exploration_clustering_score"),
        "avg_discovery_novelty": _average(novelty_scores),
        "avg_bridge_score": bridge_mean,
        "avg_semantic_relatedness": relatedness_mean,
        "meaningful_discovery_score": meaningful_bridge,
        "discovery_artist_diversity": artist_diversity,
    }


def human_review_schema() -> Dict[str, Any]:
    """Return the offline review schema expected by this module."""

    return {
        "required_ratings": list(PERCEPTION_DIMENSIONS),
        "rating_scale": "0..1 by default, or provide rating_scale=5 for 1..5 forms",
        "optional_fields": ["playlist_id", "reviewer_id", "scenario", "notes", "flags"],
        "offline_only": True,
        "used_for_training": False,
    }


def normalize_human_review(review: Mapping[str, Any]) -> Dict[str, Any]:
    """Normalize one human review into a stable 0..1 rating schema."""

    scale = _safe_float(review.get("rating_scale"), None)
    if scale is None:
        scale = 5.0 if any(_safe_float(review.get(key), 0.0) > 1.0 for key in PERCEPTION_DIMENSIONS) else 1.0
    ratings = {
        dimension: _rating01(review.get(dimension), scale)
        for dimension in PERCEPTION_DIMENSIONS
    }
    ratings = {key: value for key, value in ratings.items() if value is not None}
    flags = review.get("flags") or []
    if isinstance(flags, str):
        flags = [flags]
    return {
        "playlist_id": str(review.get("playlist_id") or "").strip() or None,
        "reviewer_id": str(review.get("reviewer_id") or "").strip() or None,
        "scenario": str(review.get("scenario") or "").strip() or None,
        "ratings": ratings,
        "rating_scale": scale,
        "notes": str(review.get("notes") or "").strip(),
        "flags": [str(flag).strip() for flag in flags if str(flag).strip()],
    }


def summarize_human_reviews(reviews: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Aggregate normalized or raw human review dictionaries."""

    normalized = [
        review if "ratings" in review else normalize_human_review(review)
        for review in reviews
    ]
    averages = {
        dimension: _average((review.get("ratings") or {}).get(dimension) for review in normalized)
        for dimension in PERCEPTION_DIMENSIONS
    }
    averages = {key: value for key, value in averages.items() if value is not None}
    flag_counts = Counter(flag for review in normalized for flag in review.get("flags", []))
    low_dimensions = sorted(
        dimension for dimension, value in averages.items()
        if value <= LOW_HUMAN_SCORE
    )
    return {
        "review_count": len(normalized),
        "average_ratings": averages,
        "low_dimensions": low_dimensions,
        "flag_counts": dict(flag_counts),
        "notes_count": sum(1 for review in normalized if review.get("notes")),
    }


def _objective_metrics(
    tracks: Sequence[Mapping[str, Any]],
    evaluation_report: Mapping[str, Any],
    flow_report: Mapping[str, Any],
) -> Dict[str, Any]:
    quality = flow_report.get("flow_quality") or {}
    components = quality.get("component_scores") or {}
    arc = flow_report.get("arc_metrics") or {}
    repetition = flow_report.get("repetition_metrics") or {}
    diversity = evaluation_report.get("diversity") or {}
    novelty = evaluation_report.get("novelty") or {}
    discovery = _discovery_profile(tracks, flow_report)
    semantic = _trace_semantic_score(tracks, evaluation_report)

    technical_health = _weighted(
        (
            (_clamp01(quality.get("overall_flow_score")), 0.35),
            (_clamp01(diversity.get("unique_artists_ratio")), 0.20),
            (_clamp01(novelty.get("mainstream_niche_balance")), 0.10),
            (semantic, 0.15),
            (_clamp01(components.get("repetition_control")), 0.20),
        )
    )
    return {
        "technical_health_score": technical_health,
        "overall_flow_score": quality.get("overall_flow_score"),
        "transition_smoothness": components.get("transition_smoothness"),
        "arc_coherence": components.get("arc_coherence"),
        "session_adherence": components.get("session_adherence"),
        "flow_entropy": quality.get("flow_entropy"),
        "energy_variance": arc.get("energy_variance"),
        "valence_variance": arc.get("valence_variance"),
        "arc_variation_score": _arc_variation_score(arc),
        "unique_artists_ratio": diversity.get("unique_artists_ratio"),
        "unique_genres_ratio": diversity.get("unique_genres_ratio"),
        "inverse_popularity": novelty.get("inverse_popularity"),
        "mainstream_niche_balance": novelty.get("mainstream_niche_balance"),
        "semantic_fit_score": semantic,
        "artist_repeat_pressure": repetition.get("artist_repeat_pressure"),
        **discovery,
    }


def _proxy_scores(metrics: Mapping[str, Any]) -> Dict[str, Optional[float]]:
    discovery_presence = min(1.0, (metrics.get("discovery_ratio") or 0.0) / 0.25)
    emotional_realism = _weighted(
        (
            (_clamp01(metrics.get("overall_flow_score")), 0.30),
            (_clamp01(metrics.get("arc_coherence")), 0.20),
            (_clamp01(metrics.get("session_adherence")), 0.20),
            (_clamp01(metrics.get("arc_variation_score")), 0.30),
        )
    )
    discovery_quality = _weighted(
        (
            (_clamp01(metrics.get("avg_discovery_novelty")), 0.25),
            (_clamp01(metrics.get("meaningful_discovery_score")), 0.35),
            (_clamp01(metrics.get("exploration_spread")), 0.15),
            (_clamp01(discovery_presence), 0.10),
            (_clamp01(metrics.get("discovery_artist_diversity")), 0.15),
        )
    )
    memorability = _weighted(
        (
            (_clamp01(metrics.get("inverse_popularity")), 0.25),
            (_clamp01(metrics.get("unique_artists_ratio")), 0.25),
            (_clamp01(metrics.get("unique_genres_ratio")), 0.15),
            (_clamp01(metrics.get("arc_variation_score")), 0.25),
            (_clamp01(metrics.get("meaningful_discovery_score")), 0.10),
        )
    )
    coherence = _weighted(
        (
            (_clamp01(metrics.get("overall_flow_score")), 0.35),
            (_clamp01(metrics.get("semantic_fit_score")), 0.25),
            (_clamp01(metrics.get("meaningful_discovery_score")), 0.20),
            (_clamp01(metrics.get("transition_smoothness")), 0.20),
        )
    )
    perceived_novelty = _weighted(
        (
            (_clamp01(metrics.get("avg_discovery_novelty")), 0.50),
            (_clamp01(metrics.get("discovery_artist_diversity")), 0.20),
            (_clamp01(metrics.get("meaningful_discovery_score")), 0.30),
        )
    )
    return {
        "overall_quality": metrics.get("technical_health_score"),
        "discovery_magic": discovery_quality,
        "emotional_realism": emotional_realism,
        "memorability": memorability,
        "subjective_coherence": coherence,
        "perceived_novelty": perceived_novelty,
    }


def _metric_reasoning() -> Dict[str, List[Dict[str, str]]]:
    return {
        "overall_quality": [
            {"metric": "overall_flow_score", "reason": "Objective order health is useful, but can overrate lifeless smoothness."},
            {"metric": "unique_artists_ratio", "reason": "Artist variety supports perceived quality by reducing fatigue."},
            {"metric": "semantic_fit_score", "reason": "Semantic fit explains whether the set still belongs to the listener."},
            {"metric": "repetition_control", "reason": "Low adjacent repetition keeps healthy metrics from hiding fatigue."},
        ],
        "perceived_discovery_quality": [
            {"metric": "avg_discovery_novelty", "reason": "Low popularity can indicate novelty but is not meaningful discovery by itself."},
            {"metric": "meaningful_discovery_score", "reason": "Bridge and relatedness scores estimate whether a discovery has a believable path from the source taste."},
            {"metric": "exploration_spread", "reason": "Spread-out discoveries usually feel less dumped-in than clustered exploration."},
            {"metric": "discovery_artist_diversity", "reason": "Distinct discovery artists reduce the feeling of recycled novelty."},
        ],
        "emotional_realism": [
            {"metric": "arc_coherence", "reason": "Coherent arcs support story-like listening."},
            {"metric": "arc_variation_score", "reason": "Some contour is required; a perfectly flat arc can feel emotionally synthetic."},
            {"metric": "flow_entropy", "reason": "Mood-space entropy helps separate calm realism from over-smoothed sameness."},
        ],
        "memorability": [
            {"metric": "inverse_popularity", "reason": "Less obvious tracks can be memorable when they are still coherent."},
            {"metric": "unique_artists_ratio", "reason": "Identity variety gives listeners more moments to remember."},
            {"metric": "arc_variation_score", "reason": "Emotional contour creates anchors in memory."},
        ],
        "subjective_coherence": [
            {"metric": "overall_flow_score", "reason": "Flow continuity supports subjective coherence."},
            {"metric": "semantic_fit_score", "reason": "Semantic fit keeps varied tracks from feeling random."},
            {"metric": "meaningful_discovery_score", "reason": "Discovery bridges must feel earned, not merely injected."},
        ],
    }


def _dimension_disagreements(
    human_summary: Mapping[str, Any],
    proxies: Mapping[str, Optional[float]],
) -> List[Dict[str, Any]]:
    human = human_summary.get("average_ratings") or {}
    disagreements = []
    for dimension, metric_score in proxies.items():
        human_score = human.get(dimension)
        if metric_score is None or human_score is None:
            continue
        gap = round(float(metric_score) - float(human_score), 3)
        if abs(gap) < DISAGREEMENT_GAP:
            continue
        disagreements.append(
            {
                "dimension": dimension,
                "metric_score": round(float(metric_score), 3),
                "human_score": round(float(human_score), 3),
                "gap": gap,
                "direction": "metrics_overestimate" if gap > 0 else "humans_rate_higher",
                "severity": "high" if abs(gap) >= 0.45 else "medium",
            }
        )
    return disagreements


def _diagnostics(
    human_summary: Mapping[str, Any],
    metrics: Mapping[str, Any],
    proxies: Mapping[str, Optional[float]],
) -> Dict[str, Any]:
    human = human_summary.get("average_ratings") or {}
    disagreements = _dimension_disagreements(human_summary, proxies)
    flags = []
    patterns = []

    if disagreements:
        flags.append("metric_human_disagreement")

    technical = metrics.get("technical_health_score") or 0.0
    weak_emotion = min(
        human.get("emotional_realism", 1.0),
        human.get("memorability", 1.0),
        human.get("overall_quality", 1.0),
    )
    if technical >= HIGH_METRIC_SCORE and weak_emotion <= LOW_HUMAN_SCORE:
        flags.append("technically_healthy_but_emotionally_weak")
        patterns.append(
            {
                "pattern": "technically_healthy_but_emotionally_weak",
                "evidence": {"technical_health_score": technical, "weakest_human_signal": weak_emotion},
                "interpretation": "Objective health is strong while perception says the playlist lacks feeling or staying power.",
            }
        )

    novelty = metrics.get("avg_discovery_novelty") or metrics.get("inverse_popularity") or 0.0
    meaningful = metrics.get("meaningful_discovery_score") or 0.0
    discovery_human = min(human.get("discovery_magic", 1.0), human.get("perceived_novelty", 1.0))
    if novelty >= 0.55 and meaningful <= LOW_HUMAN_SCORE and discovery_human <= LOW_HUMAN_SCORE:
        flags.append("fake_novelty")
        patterns.append(
            {
                "pattern": "fake_novelty",
                "evidence": {
                    "avg_discovery_novelty": novelty,
                    "meaningful_discovery_score": meaningful,
                    "human_discovery_floor": discovery_human,
                },
                "interpretation": "Tracks look novel by popularity but humans do not experience them as meaningful discovery.",
            }
        )

    smooth = metrics.get("transition_smoothness") or 0.0
    entropy = metrics.get("flow_entropy") or 0.0
    energy_var = metrics.get("energy_variance") or 0.0
    valence_var = metrics.get("valence_variance") or 0.0
    if smooth >= 0.85 and (entropy <= 0.38 or (energy_var <= 0.04 and valence_var <= 0.04)) and human.get("emotional_realism", 1.0) <= 0.50:
        flags.append("over_smoothed_emotional_arc")
        patterns.append(
            {
                "pattern": "over_smoothed_emotional_arc",
                "evidence": {
                    "transition_smoothness": smooth,
                    "flow_entropy": entropy,
                    "energy_variance": energy_var,
                    "valence_variance": valence_var,
                    "human_emotional_realism": human.get("emotional_realism"),
                },
                "interpretation": "The playlist is smooth enough to score well but too flat to feel emotionally real.",
            }
        )

    exploration_ratio = metrics.get("discovery_ratio") or metrics.get("flow_exploration_ratio") or 0.0
    coherence_human = human.get("subjective_coherence", 1.0)
    if exploration_ratio >= 0.18 and meaningful <= 0.50 and min(coherence_human, human.get("discovery_magic", 1.0)) <= 0.50:
        flags.append("artificial_feeling_exploration")
        patterns.append(
            {
                "pattern": "artificial_feeling_exploration",
                "evidence": {
                    "discovery_ratio": exploration_ratio,
                    "meaningful_discovery_score": meaningful,
                    "human_subjective_coherence": coherence_human,
                    "human_discovery_magic": human.get("discovery_magic"),
                },
                "interpretation": "Exploration is present, but reviewers perceive it as inserted rather than earned.",
            }
        )

    return {
        "flags": sorted(set(flags)),
        "dimension_disagreements": sorted(disagreements, key=lambda item: (-abs(item["gap"]), item["dimension"])),
        "patterns": patterns,
        "advisory_only": True,
    }


def analyze_human_perception(
    playlist: Any,
    human_reviews: Sequence[Mapping[str, Any]],
    *,
    session_type: Optional[str] = None,
    user_embedding: Any = None,
    track_embedding_fn: Any = None,
) -> Dict[str, Any]:
    """Compare objective metrics with offline human perception reviews."""

    tracks = _tracks(playlist)
    normalized_reviews = [normalize_human_review(review) for review in human_reviews]
    human_summary = summarize_human_reviews(normalized_reviews)
    evaluation_report = evaluate_playlist(tracks, user_embedding=user_embedding, track_embedding_fn=track_embedding_fn)
    flow_report = evaluate_flow(tracks, session_type=session_type)
    metrics = _objective_metrics(tracks, evaluation_report, flow_report)
    proxies = _proxy_scores(metrics)
    return {
        "mode": "offline_human_perception_calibration_only",
        "human_review_schema": human_review_schema(),
        "human_review_summary": human_summary,
        "objective_metrics": metrics,
        "perception_proxy_scores": proxies,
        "disagreement_diagnostics": _diagnostics(human_summary, metrics, proxies),
        "metric_reasoning": _metric_reasoning(),
        "stress_test_scenarios": list(PERCEPTUAL_STRESS_TEST_SCENARIOS),
        "safety": {
            "changes_recommendation_behavior": False,
            "trains_or_updates_models": False,
            "uses_live_feedback_loop": False,
            "persists_feedback": False,
            "offline_only": True,
        },
    }


compare_human_reviews_to_metrics = analyze_human_perception
