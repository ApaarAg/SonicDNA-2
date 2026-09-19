"""
Schema and boundary guards for response, persistence, trace, and observability.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Sequence, Set

from .invariant_checks import ContractViolation


DEBUG_FIELD_NAMES: Set[str] = {
    "debug",
    "debug_info",
    "debug_metadata",
    "diagnostics",
    "flow_report",
    "recommendation_trace",
    "ranking_diagnostics",
    "runtime_trace",
    "calibration_report",
}

INTERNAL_FIELD_NAMES: Set[str] = {
    "graph_flow_bonus",
    "graph_weight",
    "graph_weights",
    "exploration_meta",
    "exploration_score",
    "temporary_exploration_score",
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
    "user_embedding_similarity",
    "semantic_similarity",
    "raw_embedding",
    "embedding",
    "embeddings",
    "query_embedding",
    "candidate_embedding",
    "track_embedding",
    "user_embedding",
    "embedding_vector",
    "candidate_pool",
    "candidate_tracks",
    "candidate_scores",
    "graph_adjacency",
    "neighbors",
    "neighbor_scores",
    "cache_key",
    "cache_hit",
    "request_metadata",
    "request_meta",
    "request_only_metadata",
}

PERSISTENCE_FORBIDDEN_FIELDS = DEBUG_FIELD_NAMES | INTERNAL_FIELD_NAMES | {
    "cache",
    "internal_cache",
    "graph_nodes",
    "graph_edges",
    "graph_distances",
}

TRACE_TOP_LEVEL_FIELDS = {
    "request_id",
    "total_duration_ms",
    "timing",
    "ranking_path",
    "promotion_events",
    "exploration_events",
    "flow_adjustments",
    "cache_events",
    "failure_warnings",
}

TRACE_EVENT_FIELDS: Dict[str, Set[str]] = {
    "timing": {"stage", "duration_ms", "metadata"},
    "ranking_path": {"track_id", "track_name", "stage", "rank_before", "rank_after", "score_before", "score_after", "delta"},
    "promotion_events": {"track_id", "track_name", "from_stage", "to_stage", "rank_change", "reason"},
    "exploration_events": {"track_id", "track_name", "artist", "action", "exploration_score", "semantic_relatedness", "position", "reason"},
    "flow_adjustments": {"track_id", "track_name", "original_position", "new_position", "flow_score", "zone", "dominant_signal"},
    "cache_events": {"cache_name", "hit", "key_hint", "entry_count"},
    "failure_warnings": {"stage", "error_type", "message", "recoverable"},
}

MONITORING_ONLY_KEYS = {"anomalies", "active_anomalies", "health", "status", "latencies", "caches", "quality", "counters"}
DIAGNOSTIC_ONLY_KEYS = {"hypotheses", "probable_causes", "supporting_signals", "recommended_investigation", "diagnostics"}


def _walk(value: Any, path: str = ""):
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_path = f"{path}.{key}" if path else str(key)
            yield key_path, str(key), item
            yield from _walk(item, key_path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            item_path = f"{path}[{index}]" if path else f"[{index}]"
            yield item_path, str(index), item
            yield from _walk(item, item_path)


def validate_response_boundary(payload: Mapping[str, Any]) -> List[ContractViolation]:
    """Detect debug/internal fields crossing into user-facing responses."""

    violations: List[ContractViolation] = []
    for path, key, value in _walk(payload):
        normalized = key.strip().lower()
        if normalized in DEBUG_FIELD_NAMES:
            violations.append(
                ContractViolation(
                    code="response_debug_boundary_leakage",
                    message=f"Debug field {key!r} appears in a response payload.",
                    path=path,
                    value=value,
                    hint="Return debug artifacts only through explicit internal/debug envelopes.",
                )
            )
        elif normalized in INTERNAL_FIELD_NAMES or normalized.startswith("_"):
            violations.append(
                ContractViolation(
                    code="response_internal_field_leakage",
                    message=f"Internal field {key!r} appears in a response payload.",
                    path=path,
                    value=value,
                    hint="Project responses through models.response_models before returning to clients.",
                )
            )
    return violations


def validate_persistence_boundary(payload: Mapping[str, Any]) -> List[ContractViolation]:
    """Detect debug/runtime contamination before durable persistence."""

    violations: List[ContractViolation] = []
    for path, key, value in _walk(payload):
        normalized = key.strip().lower()
        if (
            normalized in PERSISTENCE_FORBIDDEN_FIELDS
            or normalized.startswith("_")
            or normalized.endswith("_diagnostics")
            or normalized.endswith("_adjacency")
        ):
            violations.append(
                ContractViolation(
                    code="persistence_debug_contamination",
                    message=f"Runtime/debug field {key!r} appears in a persistence payload.",
                    path=path,
                    value=value,
                    hint="Use persistence_sanitizer or models.persistence_models at storage boundaries.",
                )
            )
    return violations


def _event_items(section_name: str, section: Any) -> Iterable[Mapping[str, Any]]:
    if section_name == "timing" and isinstance(section, Mapping):
        return [item for item in section.values() if isinstance(item, Mapping)]
    if isinstance(section, Sequence) and not isinstance(section, (str, bytes, bytearray)):
        return [item for item in section if isinstance(item, Mapping)]
    return []


def validate_trace_schema(trace_payload: Mapping[str, Any]) -> List[ContractViolation]:
    """Validate runtime trace top-level and event fields."""

    violations: List[ContractViolation] = []
    for key in trace_payload:
        if key not in TRACE_TOP_LEVEL_FIELDS:
            violations.append(
                ContractViolation(
                    code="invalid_trace_schema_field",
                    message=f"Unexpected runtime trace field {key!r}.",
                    path=str(key),
                    value=trace_payload.get(key),
                    hint="Keep trace output within debug.runtime_trace.PipelineTrace.to_dict schema.",
                )
            )

    for section_name, allowed in TRACE_EVENT_FIELDS.items():
        section = trace_payload.get(section_name)
        for item in _event_items(section_name, section):
            for key, value in item.items():
                if key not in allowed:
                    violations.append(
                        ContractViolation(
                            code="invalid_trace_schema_field",
                            message=f"Unexpected {section_name} trace field {key!r}.",
                            path=f"{section_name}.{key}",
                            value=value,
                            hint="Add schema fields deliberately in debug.runtime_trace and contracts together.",
                        )
                    )
    return violations


def validate_monitoring_diagnostic_namespaces(
    *,
    monitoring_payload: Mapping[str, Any] | None = None,
    diagnostics_payload: Mapping[str, Any] | None = None,
) -> List[ContractViolation]:
    """Detect monitoring anomaly fields in diagnostics and hypothesis fields in monitoring."""

    violations: List[ContractViolation] = []
    monitoring_payload = monitoring_payload or {}
    diagnostics_payload = diagnostics_payload or {}

    for path, key, value in _walk(monitoring_payload):
        if key in DIAGNOSTIC_ONLY_KEYS:
            violations.append(
                ContractViolation(
                    code="monitoring_diagnostic_namespace_mixing",
                    message=f"Diagnostic field {key!r} appears in monitoring payload.",
                    path=path,
                    value=value,
                    hint="Monitoring should emit operational thresholds; diagnostics should emit hypotheses.",
                )
            )

    for path, key, value in _walk(diagnostics_payload):
        if key in MONITORING_ONLY_KEYS:
            violations.append(
                ContractViolation(
                    code="monitoring_diagnostic_namespace_mixing",
                    message=f"Monitoring field {key!r} appears in diagnostics payload.",
                    path=path,
                    value=value,
                    hint="Keep anomaly labels in monitoring and root-cause hypotheses in diagnostics.",
                )
            )
    return violations
