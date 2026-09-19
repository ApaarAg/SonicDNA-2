"""
Canonical metric contracts and naming drift checks.

This module turns the semantic contract documentation into a tiny runtime
registry. It does not create metrics and does not record telemetry.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

from .invariant_checks import ContractViolation


_SNAKE_CASE = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class MetricContract:
    """Static metadata for a known metric name."""

    name: str
    owner: str
    namespace: str = "semantic"
    valid_range: Optional[Tuple[float, float]] = None
    sequence_sensitive: bool = False
    forbidden_synonyms: Tuple[str, ...] = field(default_factory=tuple)


CANONICAL_METRICS: Dict[str, MetricContract] = {
    "flow_trace": MetricContract("flow_trace", "playlist_flow_engine", sequence_sensitive=True),
    "flow_position": MetricContract("flow_position", "playlist_flow_engine", sequence_sensitive=True),
    "flow_sequencing": MetricContract("flow_sequencing", "playlist_flow_engine", namespace="latency"),
    "overall_flow_score": MetricContract("overall_flow_score", "flow_evaluation", valid_range=(0.0, 1.0), sequence_sensitive=True),
    "flow_quality": MetricContract("flow_quality", "flow_evaluation", valid_range=(0.0, 1.0), sequence_sensitive=True),
    "semantic_similarity": MetricContract("semantic_similarity", "ranking", valid_range=(0.0, 1.0)),
    "user_embedding_similarity": MetricContract("user_embedding_similarity", "ranking", valid_range=(0.0, 1.0)),
    "semantic_match": MetricContract("semantic_match", "evaluation", valid_range=(0.0, 1.0)),
    "unique_artists_ratio": MetricContract("unique_artists_ratio", "evaluation", valid_range=(0.0, 1.0)),
    "unique_genres_ratio": MetricContract("unique_genres_ratio", "evaluation", valid_range=(0.0, 1.0)),
    "playlist_diversity": MetricContract("playlist_diversity", "evaluation", valid_range=(0.0, 1.0)),
    "playlist_overlap": MetricContract("playlist_overlap", "evaluation", valid_range=(0.0, 1.0)),
    "same_order_ratio": MetricContract("same_order_ratio", "evaluation", valid_range=(0.0, 1.0), sequence_sensitive=True),
    "recommendation_stability": MetricContract("recommendation_stability", "monitoring", valid_range=(0.0, 1.0), namespace="monitoring"),
    "exploration_ratio": MetricContract("exploration_ratio", "exploration_engine", valid_range=(0.0, 1.0)),
    "exploration_count": MetricContract("exploration_count", "exploration_engine"),
    "exploration_injection_rate": MetricContract("exploration_injection_rate", "monitoring", valid_range=(0.0, 1.0), namespace="monitoring"),
    "inverse_popularity": MetricContract("inverse_popularity", "evaluation", valid_range=(0.0, 1.0)),
    "mainstream_ratio": MetricContract("mainstream_ratio", "evaluation", valid_range=(0.0, 1.0)),
    "niche_ratio": MetricContract("niche_ratio", "evaluation", valid_range=(0.0, 1.0)),
    "mainstream_niche_balance": MetricContract("mainstream_niche_balance", "evaluation", valid_range=(0.0, 1.0)),
    "quality_score": MetricContract("quality_score", "ranking", valid_range=(0.0, 1.0)),
    "primary_score": MetricContract("primary_score", "ranking", valid_range=(0.0, 1.0)),
    "final_rank_score": MetricContract("final_rank_score", "ranking", valid_range=(0.0, 1.0)),
    "cache_hit_rate": MetricContract("cache_hit_rate", "monitoring", valid_range=(0.0, 1.0), namespace="monitoring"),
    "cache_collapse": MetricContract("cache_collapse", "monitoring", namespace="monitoring"),
    "graph_weight": MetricContract("graph_weight", "track_graph", valid_range=(0.0, 1.0)),
    "graph_flow_bonus": MetricContract("graph_flow_bonus", "track_graph"),
    "graph_neighborhood": MetricContract("graph_neighborhood", "track_graph"),
    "artist_repeat_pressure": MetricContract("artist_repeat_pressure", "flow_evaluation", valid_range=(0.0, 1.0), sequence_sensitive=True),
    "max_artist_run": MetricContract("max_artist_run", "flow_evaluation", sequence_sensitive=True),
    "artist_fatigue": MetricContract("artist_fatigue", "feedback", namespace="feedback"),
    "community_repeat_pressure": MetricContract("community_repeat_pressure", "flow_evaluation", valid_range=(0.0, 1.0), sequence_sensitive=True),
    "max_cluster_run": MetricContract("max_cluster_run", "flow_evaluation", sequence_sensitive=True),
    "adherence_score": MetricContract("adherence_score", "flow_evaluation", valid_range=(0.0, 1.0), sequence_sensitive=True),
    "spike_violations": MetricContract("spike_violations", "flow_evaluation", sequence_sensitive=True),
    "energy_variance_ok": MetricContract("energy_variance_ok", "flow_evaluation", sequence_sensitive=True),
    "playlist_failed": MetricContract("playlist_failed", "monitoring", namespace="monitoring"),
    "empty_candidates": MetricContract("empty_candidates", "monitoring", namespace="monitoring"),
    "candidate_nonempty_rate": MetricContract("candidate_nonempty_rate", "monitoring", valid_range=(0.0, 1.0), namespace="monitoring"),
    "elevated_failures": MetricContract("elevated_failures", "monitoring", namespace="monitoring"),
}


FORBIDDEN_SYNONYMS: Dict[str, str] = {
    "flow health": "overall_flow_score",
    "smoothness score": "overall_flow_score",
    "vibe score": "overall_flow_score",
    "vibe flow": "flow_trace",
    "graph flow": "graph_weight",
    "semantic flow": "semantic_similarity",
    "relevance": "semantic_similarity",
    "affinity": "semantic_similarity",
    "discovery": "exploration_ratio",
    "discovery quality": "novelty",
    "determinism": "recommendation_stability",
    "consistency": "recommendation_stability",
    "flow score": "overall_flow_score",
}

AMBIGUOUS_SINGLE_WORDS = frozenset({"quality", "fit", "health", "coherence", "stability", "smoothness"})


class MetricRegistry:
    """Small in-memory registry used by tests, diagnostics, and dev boot checks."""

    def __init__(self, initial: Optional[Mapping[str, MetricContract]] = None) -> None:
        self._contracts: Dict[str, MetricContract] = dict(initial or {})

    def register(self, contract: MetricContract) -> List[ContractViolation]:
        normalized = contract.name.strip().lower()
        if normalized in self._contracts:
            return [
                ContractViolation(
                    code="duplicate_metric_registration",
                    message=f"Metric {contract.name!r} is already registered.",
                    path=contract.name,
                    value={"existing_owner": self._contracts[normalized].owner, "new_owner": contract.owner},
                    hint="Use the existing canonical metric contract or rename the new metric deliberately.",
                )
            ]
        self._contracts[normalized] = contract
        return []

    def get(self, name: str) -> Optional[MetricContract]:
        return self._contracts.get(str(name).strip().lower())

    def names(self) -> List[str]:
        return sorted(self._contracts)


def _phrase(term: str) -> str:
    return str(term or "").strip().lower().replace("_", " ")


def validate_metric_terms(metric_terms: Iterable[str]) -> List[ContractViolation]:
    """Detect invalid names, vague names, and forbidden synonym drift."""

    violations: List[ContractViolation] = []
    for raw in metric_terms:
        term = str(raw or "").strip()
        normalized = term.lower()
        phrase = _phrase(term)
        if not term:
            continue
        if not _SNAKE_CASE.match(normalized):
            violations.append(
                ContractViolation(
                    code="invalid_metric_name",
                    message=f"Metric name {term!r} is not canonical snake_case.",
                    path=term,
                    value=term,
                    hint="Use canonical metric names from semantic_contracts.md.",
                )
            )
        if phrase in FORBIDDEN_SYNONYMS:
            violations.append(
                ContractViolation(
                    code="forbidden_synonym_drift",
                    message=f"{term!r} drifts from canonical metric {FORBIDDEN_SYNONYMS[phrase]!r}.",
                    path=term,
                    value=term,
                    hint="Preserve the canonical metric name and put explanatory language in surrounding text.",
                )
            )
        if normalized in AMBIGUOUS_SINGLE_WORDS:
            violations.append(
                ContractViolation(
                    code="invalid_metric_name",
                    message=f"Metric name {term!r} is too ambiguous for runtime reporting.",
                    path=term,
                    value=term,
                    hint="Qualify the scope, for example overall_flow_score or semantic_similarity.",
                )
            )
    return violations
