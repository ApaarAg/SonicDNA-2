"""
Offline evaluation hierarchy and signal consolidation diagnostics.

This module interprets the normalized signals produced by DiagnosticEngine. It
does not create runtime metrics, alter thresholds, or feed back into ranking.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional


MetricRecord = Dict[str, Any]


FAMILY_OWNERS = {
    "diversity": "evaluation.py for list diversity; flow_evaluation.py for ordered repetition.",
    "flow_quality": "flow_evaluation.py owns ordered playlist flow shape.",
    "stability": "calibration reports interpret repeated-run overlap and order stability.",
    "exploration": "exploration_engine.py owns injection behavior; diagnostics interprets disappearance.",
    "cache_health": "monitoring owns cache health and latency anomaly surfaces.",
    "artist_repetition": "flow_evaluation.py owns objective repetition; feedback analytics owns perception.",
    "community_repetition": "flow_evaluation.py owns community and cluster repetition.",
    "recommendation_failure": "monitoring owns failure anomalies; diagnostics correlates causes.",
    "semantic_similarity": "evaluation.py owns semantic similarity; calibration interprets drift.",
    "regional_permeability": "calibration topology diagnostics own offline regional permeability.",
    "operational_trace": "runtime traces are supporting evidence, not primary evaluation goals.",
}


PRIMARY_METRICS = {
    "playlist_diversity": (
        "diversity",
        "Canonical list-level diversity health signal from monitoring/evaluation.",
    ),
    "flow_quality": (
        "flow_quality",
        "Canonical monitoring surface for ordered playlist flow health.",
    ),
    "overall_flow_score": (
        "flow_quality",
        "Primary flow evaluation score summarizing ordered playlist continuity.",
    ),
    "recommendation_stability": (
        "stability",
        "Primary monitoring surface for repeated recommendation stability.",
    ),
    "average_playlist_overlap": (
        "stability",
        "Primary calibration signal for repeated-run inventory overlap.",
    ),
    "same_order_ratio": (
        "stability",
        "Primary calibration signal for repeated-run ordering stability.",
    ),
    "exploration_ratio": (
        "exploration",
        "Primary final-playlist signal for exploration presence.",
    ),
    "exploration_count": (
        "exploration",
        "Primary count of final-playlist exploration placements.",
    ),
    "artist_repeat_pressure": (
        "artist_repetition",
        "Primary ordered-playlist signal for same-artist repetition pressure.",
    ),
    "community_repeat_pressure": (
        "community_repetition",
        "Primary ordered-playlist signal for neighborhood repetition pressure.",
    ),
}


DERIVED_METRICS = {
    "transition_smoothness": (
        "flow_quality",
        "Derived component of the overall flow score.",
    ),
    "flow_entropy": (
        "flow_quality",
        "Derived component describing local variation within flow evaluation.",
    ),
    "max_artist_run": (
        "artist_repetition",
        "Derived run-length symptom behind artist repetition pressure.",
    ),
    "max_cluster_run": (
        "community_repetition",
        "Derived run-length symptom behind community repetition pressure.",
    ),
    "minimum_playlist_overlap": (
        "stability",
        "Derived worst-case overlap view for calibration stability.",
    ),
    "diversity_regression": (
        "diversity",
        "Derived calibration delta rather than a separate optimization target.",
    ),
    "regression_count": (
        "operational_trace",
        "Derived count of calibration regressions, useful only with named findings.",
    ),
    "flow_position_change_count": (
        "flow_quality",
        "Derived trace count showing how often flow altered positions.",
    ),
    "ranking_delta_count": (
        "operational_trace",
        "Derived trace count that supports ranking-path investigation.",
    ),
}


CORRELATED_METRICS = {
    "fatigued_artists": (
        "artist_repetition",
        "Feedback perception signal correlated with objective artist repetition.",
    ),
    "repetitiveness_complaint_rate": (
        "diversity",
        "Feedback perception signal correlated with diversity and repetition.",
    ),
    "repetitiveness_complaint_count": (
        "diversity",
        "Feedback volume signal for repetitive playlist complaints.",
    ),
    "flow_dissatisfaction_score": (
        "flow_quality",
        "Feedback perception signal correlated with flow quality.",
    ),
    "low_flow_rating_count": (
        "flow_quality",
        "Feedback volume signal for low-flow ratings.",
    ),
    "chaos_complaint_count": (
        "flow_quality",
        "Feedback volume signal for chaotic sequencing complaints.",
    ),
    "top_repeated_artists": (
        "artist_repetition",
        "Supporting identity list for explaining repetition pressure.",
    ),
    "anti_patterns": (
        "flow_quality",
        "Named flow symptoms correlated with primary flow scores.",
    ),
    "cache_events": (
        "cache_health",
        "Runtime cache evidence correlated with monitoring cache health.",
    ),
    "exploration_events": (
        "exploration",
        "Runtime exploration evidence correlated with final exploration placement.",
    ),
}


ANOMALY_FAMILIES = {
    "diversity_collapse": "diversity",
    "exploration_gone": "exploration",
    "cache_collapse": "cache_health",
    "latency_spike": "cache_health",
    "playlist_failed": "recommendation_failure",
    "empty_candidates": "recommendation_failure",
}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _has_signal(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _family_for_metric(metric: str, source: str, value: Any = None) -> str:
    key = metric.lower()
    for mapping in (PRIMARY_METRICS, DERIVED_METRICS, CORRELATED_METRICS):
        if metric in mapping:
            return mapping[metric][0]
    if key.startswith("cache_") or "cache" in key or key == "candidate_retrieval":
        return "cache_health"
    if "diversity" in key:
        return "diversity"
    if "exploration" in key:
        return "exploration"
    if "stability" in key or "overlap" in key or "same_order" in key:
        return "stability"
    if "artist" in key:
        return "artist_repetition"
    if "community" in key or "cluster" in key:
        return "community_repetition"
    if "semantic" in key:
        return "semantic_similarity"
    if "regional" in key or "permeability" in key:
        return "regional_permeability"
    if source == "monitoring_anomalies" and isinstance(value, Mapping):
        return ANOMALY_FAMILIES.get(str(value.get("type")), "recommendation_failure")
    return "operational_trace"


def _role_reason(metric: str, source: str, value: Any) -> tuple[str, str, str]:
    if source == "monitoring_anomalies":
        anomaly_type = str(value.get("type", metric)) if isinstance(value, Mapping) else metric
        family = ANOMALY_FAMILIES.get(anomaly_type, _family_for_metric(metric, source, value))
        return (
            "correlated_metrics",
            family,
            "Named monitoring anomaly derived from lower-level metrics; keep it as correlation evidence.",
        )

    for role, mapping in (
        ("primary_metrics", PRIMARY_METRICS),
        ("derived_metrics", DERIVED_METRICS),
        ("correlated_metrics", CORRELATED_METRICS),
    ):
        if metric in mapping:
            family, reason = mapping[metric]
            return role, family, reason

    family = _family_for_metric(metric, source, value)
    if source == "monitoring_quality":
        return (
            "primary_metrics",
            family,
            "Monitoring quality metric is treated as a primary observable unless a narrower owner exists.",
        )
    if source == "runtime_trace":
        return (
            "correlated_metrics",
            family,
            "Runtime trace event supports diagnosis but is not itself an optimization target.",
        )
    return (
        "derived_metrics",
        family,
        "Derived diagnostic surface retained for interpretation, not independent optimization.",
    )


def _record(source: str, metric: str, value: Any) -> MetricRecord:
    role, family, reason = _role_reason(metric, source, value)
    if not _has_signal(value):
        role = "low_signal_metrics"
        reason = "Signal is absent or empty in this diagnostic window."
    return {
        "source": source,
        "metric": metric,
        "family": family,
        "role": role,
        "value": value,
        "owner": FAMILY_OWNERS.get(family, "Diagnostics keeps this signal advisory."),
        "reason": reason,
    }


def _iter_metrics(signals: Mapping[str, Any]) -> Iterable[MetricRecord]:
    for metric, value in (signals.get("monitoring_quality") or {}).items():
        yield _record("monitoring_quality", str(metric), value)

    for anomaly in signals.get("monitoring_anomalies") or []:
        if isinstance(anomaly, Mapping):
            metric = str(anomaly.get("metric") or anomaly.get("type") or "monitoring_anomaly")
            yield _record("monitoring_anomalies", metric, dict(anomaly))

    for source in ("calibration", "flow", "feedback"):
        for metric, value in (signals.get(source) or {}).items():
            if metric == "anti_patterns":
                yield _record(source, metric, value)
            elif metric == "top_repeated_artists":
                yield _record(source, metric, value)
            elif _is_number(value) or isinstance(value, (list, tuple, dict)) or value is None:
                yield _record(source, str(metric), value)

    runtime = signals.get("runtime_trace") or {}
    for metric in (
        "cache_events",
        "exploration_events",
        "flow_position_change_count",
        "ranking_delta_count",
    ):
        if metric in runtime:
            yield _record("runtime_trace", metric, runtime.get(metric))


def _sort_records(records: Iterable[MetricRecord]) -> List[MetricRecord]:
    return sorted(records, key=lambda item: (item["family"], item["source"], item["metric"]))


def _group_overlaps(records: List[MetricRecord]) -> List[Dict[str, Any]]:
    by_family: Dict[str, List[MetricRecord]] = defaultdict(list)
    for record in records:
        if record["role"] != "low_signal_metrics":
            by_family[record["family"]].append(record)

    overlaps = []
    for family, items in by_family.items():
        sources = sorted({item["source"] for item in items})
        metric_names = sorted({item["metric"] for item in items})
        if len(metric_names) < 2 and len(sources) < 2:
            continue
        overlaps.append(
            {
                "family": family,
                "metric_count": len(metric_names),
                "sources": sources,
                "metrics": metric_names,
                "preferred_owner": FAMILY_OWNERS.get(family, "Diagnostics keeps this signal advisory."),
                "interpretation": (
                    "Multiple signals describe the same evaluation family; read the primary metric first, "
                    "then use derived and correlated metrics only to explain movement."
                ),
            }
        )
    return sorted(overlaps, key=lambda item: (item["family"], item["metric_count"]))


def _redundant_groups(overlaps: List[Dict[str, Any]], records: List[MetricRecord]) -> List[Dict[str, Any]]:
    by_metric = {(item["source"], item["metric"]): item for item in records}
    groups = []
    for overlap in overlaps:
        family = overlap["family"]
        metrics = [
            item for item in records
            if item["family"] == family and item["role"] in {"derived_metrics", "correlated_metrics"}
        ]
        if len(metrics) < 2:
            continue
        groups.append(
            {
                "family": family,
                "signals": [
                    {"source": item["source"], "metric": item["metric"], "role": item["role"]}
                    for item in _sort_records(metrics)
                    if (item["source"], item["metric"]) in by_metric
                ],
                "reason": (
                    "These signals are useful as explanations but become redundant if interpreted as "
                    "separate success criteria."
                ),
            }
        )
    return groups


def _metric_value(records: List[MetricRecord], metric: str) -> Optional[Any]:
    for record in records:
        if record["metric"] == metric and record["role"] != "low_signal_metrics":
            return record["value"]
    return None


def _observability_entropy(
    records: List[MetricRecord],
    overlaps: List[Dict[str, Any]],
    redundant_groups: List[Dict[str, Any]],
) -> Dict[str, Any]:
    source_count = len({record["source"] for record in records})
    low_signal_count = sum(1 for record in records if record["role"] == "low_signal_metrics")
    metric_count = len(records)
    score = min(
        1.0,
        len(overlaps) * 0.14
        + len(redundant_groups) * 0.08
        + max(0, source_count - 2) * 0.06
        + max(0, metric_count - 12) * 0.018
        + low_signal_count * 0.02,
    )
    level = "high" if score >= 0.7 else "moderate" if score >= 0.38 else "low"
    drivers = []
    if overlaps:
        drivers.append(f"{len(overlaps)} overlapping evaluation families")
    if redundant_groups:
        drivers.append(f"{len(redundant_groups)} redundant derived/correlated signal groups")
    if source_count > 2:
        drivers.append(f"{source_count} observability sources represented")
    if low_signal_count:
        drivers.append(f"{low_signal_count} absent or empty signals")
    return {
        "score": round(score, 3),
        "level": level,
        "drivers": drivers,
        "interpretation": (
            "Higher entropy means developers must reconcile more overlapping signals before deciding "
            "which metric actually changed."
        ),
    }


def _conflicting_pressures(records: List[MetricRecord]) -> List[Dict[str, Any]]:
    pressures: List[Dict[str, Any]] = []
    average_overlap = _metric_value(records, "average_playlist_overlap")
    same_order_ratio = _metric_value(records, "same_order_ratio")
    recommendation_stability = _metric_value(records, "recommendation_stability")
    exploration_ratio = _metric_value(records, "exploration_ratio")
    exploration_count = _metric_value(records, "exploration_count")
    playlist_diversity = _metric_value(records, "playlist_diversity")
    artist_repeat_pressure = _metric_value(records, "artist_repeat_pressure")
    transition_smoothness = _metric_value(records, "transition_smoothness")

    stable = any(
        _is_number(value) and value >= threshold
        for value, threshold in (
            (average_overlap, 0.9),
            (same_order_ratio, 0.9),
            (recommendation_stability, 0.9),
        )
    )
    exploration_low = (
        (_is_number(exploration_ratio) and exploration_ratio <= 0.05)
        or (_is_number(exploration_count) and exploration_count <= 1)
    )
    diversity_low = _is_number(playlist_diversity) and playlist_diversity <= 0.35
    repetition_high = _is_number(artist_repeat_pressure) and artist_repeat_pressure >= 0.45
    smooth_high = _is_number(transition_smoothness) and transition_smoothness >= 0.85

    if stable and exploration_low:
        pressures.append(
            {
                "pressure": "stability_vs_exploration",
                "families": ["stability", "exploration"],
                "evidence": {
                    "average_playlist_overlap": average_overlap,
                    "same_order_ratio": same_order_ratio,
                    "recommendation_stability": recommendation_stability,
                    "exploration_ratio": exploration_ratio,
                    "exploration_count": exploration_count,
                },
                "interpretation": (
                    "Very stable repeated runs can be desirable, but paired with weak exploration "
                    "they may indicate over-constrained discovery."
                ),
            }
        )

    if diversity_low and repetition_high:
        pressures.append(
            {
                "pressure": "diversity_vs_repetition",
                "families": ["diversity", "artist_repetition"],
                "evidence": {
                    "playlist_diversity": playlist_diversity,
                    "artist_repeat_pressure": artist_repeat_pressure,
                },
                "interpretation": (
                    "Low diversity and high artist repetition are not independent failures; "
                    "treat repetition as a likely driver of the diversity movement."
                ),
            }
        )

    if smooth_high and (exploration_low or diversity_low or stable):
        pressures.append(
            {
                "pressure": "flow_smoothness_vs_discovery",
                "families": ["flow_quality", "exploration", "diversity"],
                "evidence": {
                    "transition_smoothness": transition_smoothness,
                    "exploration_ratio": exploration_ratio,
                    "playlist_diversity": playlist_diversity,
                    "average_playlist_overlap": average_overlap,
                },
                "interpretation": (
                    "Smooth transitions may be crowding out discovery variety when exploration or "
                    "diversity is simultaneously weak."
                ),
            }
        )

    return sorted(pressures, key=lambda item: item["pressure"])


def _classification(records: List[MetricRecord]) -> Dict[str, List[MetricRecord]]:
    grouped = {
        "primary_metrics": [],
        "derived_metrics": [],
        "correlated_metrics": [],
        "low_signal_metrics": [],
    }
    for record in records:
        item = dict(record)
        role = item.pop("role")
        grouped[role].append(item)
    return {role: _sort_records(items) for role, items in grouped.items()}


def build_evaluation_hierarchy_report(signals: Mapping[str, Any]) -> Dict[str, Any]:
    """Build an offline, deterministic hierarchy report from normalized signals."""

    records = _sort_records(_iter_metrics(signals or {}))
    overlaps = _group_overlaps(records)
    redundant_groups = _redundant_groups(overlaps, records)
    classification = _classification(records)
    return {
        "mode": "offline_signal_consolidation_only",
        "metric_count": len(records),
        "source_count": len({record["source"] for record in records}),
        "classification_counts": {
            role: len(items)
            for role, items in classification.items()
        },
        "classification": classification,
        "overlapping_metric_families": overlaps,
        "redundant_signal_groups": redundant_groups,
        "observability_entropy": _observability_entropy(records, overlaps, redundant_groups),
        "conflicting_optimization_pressures": _conflicting_pressures(records),
        "interpretation_guide": [
            "Read primary metrics as the canonical health surface for each family.",
            "Use derived metrics to explain movement in primary metrics, not as new objectives.",
            "Use correlated metrics as perception, trace, or anomaly evidence requiring corroboration.",
            "Treat low-signal metrics as missing context rather than healthy or unhealthy outcomes.",
        ],
        "safety": {
            "changes_recommendation_behavior": False,
            "changes_calibration_thresholds": False,
            "offline_only": True,
        },
    }
