"""
Diagnostic correlation engine.

The engine normalizes existing observability outputs and runs explainable,
rule-based correlations. It is intentionally read-only and optional.
"""

from __future__ import annotations

import os
from copy import deepcopy
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .correlation_rules import CorrelationRule, DiagnosticHypothesis, evaluate_rules
from .evaluation_hierarchy import build_evaluation_hierarchy_report


def is_diagnostics_enabled() -> bool:
    """Return True only when diagnostics are explicitly enabled or in dev-like envs."""

    for key in ("SONICDNA_DIAGNOSTICS", "DEBUG_DIAGNOSTICS"):
        if os.getenv(key, "").lower() in {"1", "true", "yes"}:
            return True
    env = (os.getenv("SONICDNA_ENV") or os.getenv("APP_ENV") or "").lower()
    return env in {"development", "dev", "local", "debug"}


def _as_dict(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        return dict(value.to_dict())
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _as_list(value: Any) -> List[Dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        items = value
    else:
        items = [value]
    normalized = []
    for item in items:
        if hasattr(item, "to_dict"):
            normalized.append(dict(item.to_dict()))
        elif isinstance(item, Mapping):
            normalized.append(dict(item))
    return normalized


def _extract_monitoring(
    monitoring_anomalies: Any = None,
    monitoring_report: Any = None,
) -> Dict[str, Any]:
    report = _as_dict(monitoring_report)
    anomalies = _as_list(monitoring_anomalies) or _as_list(report.get("anomalies"))
    quality: Dict[str, float] = {}
    for item in report.get("quality", []) or []:
        if isinstance(item, Mapping) and isinstance(item.get("mean"), (int, float)):
            quality[str(item.get("metric"))] = float(item["mean"])
    for metric, stats in (report.get("quality_metrics") or {}).items():
        if isinstance(stats, Mapping) and isinstance(stats.get("mean"), (int, float)):
            quality[str(metric)] = float(stats["mean"])
    return {"monitoring_anomalies": anomalies, "monitoring_quality": quality}


def _extract_runtime_trace(runtime_trace: Any = None) -> Dict[str, Any]:
    trace = deepcopy(_as_dict(runtime_trace))
    flow_adjustments = _as_list(trace.get("flow_adjustments"))
    ranking_path = _as_list(trace.get("ranking_path"))
    trace["flow_adjustments"] = flow_adjustments
    trace["cache_events"] = _as_list(trace.get("cache_events"))
    trace["exploration_events"] = _as_list(trace.get("exploration_events"))
    trace["ranking_path"] = ranking_path
    trace["flow_position_change_count"] = sum(
        1 for item in flow_adjustments
        if item.get("original_position") != item.get("new_position") or item.get("dominant_signal")
    )
    trace["ranking_delta_count"] = sum(
        1 for item in ranking_path
        if isinstance(item.get("delta"), (int, float)) and abs(item["delta"]) >= 2
    )
    return trace


def _extract_calibration(calibration_report: Any = None) -> Dict[str, Any]:
    report = _as_dict(calibration_report)
    regression = _as_dict(report.get("regression_detection"))
    findings = _as_list(regression.get("findings"))
    diversity_values = [
        finding.get("value")
        for finding in findings
        if str(finding.get("metric", "")).startswith("diversity.")
        and isinstance(finding.get("value"), (int, float))
    ]

    scenario_reports = _as_list(report.get("scenario_reports"))
    same_order_values = []
    overlap_values = []
    for scenario in scenario_reports:
        stability = _as_dict(scenario.get("recommendation_stability"))
        if isinstance(stability.get("same_order_ratio"), (int, float)):
            same_order_values.append(float(stability["same_order_ratio"]))
        if isinstance(stability.get("overlap"), (int, float)):
            overlap_values.append(float(stability["overlap"]))
        if isinstance(scenario.get("playlist_overlap"), (int, float)):
            overlap_values.append(float(scenario["playlist_overlap"]))

    aggregate = _as_dict(report.get("aggregate"))
    average_overlap = aggregate.get("average_playlist_overlap")
    if average_overlap is None and overlap_values:
        average_overlap = round(sum(overlap_values) / len(overlap_values), 3)

    return {
        "diversity_regression": min(diversity_values) if diversity_values else None,
        "average_playlist_overlap": average_overlap,
        "minimum_playlist_overlap": min(overlap_values) if overlap_values else None,
        "same_order_ratio": (
            round(sum(same_order_values) / len(same_order_values), 3)
            if same_order_values else None
        ),
        "regression_count": regression.get("regression_count"),
    }


def _extract_flow(flow_report: Any = None) -> Dict[str, Any]:
    report = _as_dict(flow_report)
    quality = _as_dict(report.get("flow_quality"))
    components = _as_dict(quality.get("component_scores"))
    repetition = _as_dict(report.get("repetition_metrics"))
    exploration = _as_dict(report.get("exploration_metrics"))
    arc = _as_dict(report.get("arc_metrics"))

    return {
        "overall_flow_score": quality.get("overall_flow_score"),
        "flow_entropy": quality.get("flow_entropy"),
        "transition_smoothness": components.get("transition_smoothness"),
        "artist_repeat_pressure": repetition.get("artist_repeat_pressure"),
        "community_repeat_pressure": repetition.get("community_repeat_pressure"),
        "max_artist_run": repetition.get("max_artist_run"),
        "max_cluster_run": repetition.get("max_cluster_run"),
        "top_repeated_artists": repetition.get("top_repeated_artists", []),
        "exploration_ratio": exploration.get("exploration_ratio"),
        "exploration_count": exploration.get("exploration_count"),
        "arc_direction_changes": arc.get("arc_direction_changes"),
        "anti_patterns": _as_list(report.get("anti_patterns")),
    }


def _extract_feedback(feedback_report: Any = None) -> Dict[str, Any]:
    report = _as_dict(feedback_report)
    artist_fatigue = _as_dict(report.get("artist_fatigue"))
    repetitive = _as_dict(report.get("repetitive_playlist_detection"))
    flow = _as_dict(report.get("flow_dissatisfaction"))

    return {
        "fatigued_artists": _as_list(artist_fatigue.get("fatigued_artists")),
        "repetitiveness_complaint_rate": repetitive.get("complaint_rate"),
        "repetitiveness_complaint_count": repetitive.get("complaint_count"),
        "flow_dissatisfaction_score": flow.get("indicator_score"),
        "low_flow_rating_count": flow.get("low_rating_count"),
        "chaos_complaint_count": flow.get("chaos_complaint_count"),
    }


class DiagnosticEngine:
    """Run rule-based correlations over existing operational reports."""

    def __init__(self, rules: Optional[Sequence[CorrelationRule]] = None) -> None:
        self.rules = rules

    def collect_signals(
        self,
        *,
        runtime_trace: Any = None,
        monitoring_anomalies: Any = None,
        monitoring_report: Any = None,
        calibration_report: Any = None,
        flow_report: Any = None,
        feedback_report: Any = None,
    ) -> Dict[str, Any]:
        """Normalize inputs into a compact signal map for correlation rules."""

        monitoring = _extract_monitoring(monitoring_anomalies, monitoring_report)
        return {
            "runtime_trace": _extract_runtime_trace(runtime_trace),
            "calibration": _extract_calibration(calibration_report),
            "flow": _extract_flow(flow_report),
            "feedback": _extract_feedback(feedback_report),
            **monitoring,
        }

    def generate_hypotheses(
        self,
        *,
        runtime_trace: Any = None,
        monitoring_anomalies: Any = None,
        monitoring_report: Any = None,
        calibration_report: Any = None,
        flow_report: Any = None,
        feedback_report: Any = None,
    ) -> List[DiagnosticHypothesis]:
        """Generate hypotheses without mutating inputs or recommendation config."""

        signals = self.collect_signals(
            runtime_trace=runtime_trace,
            monitoring_anomalies=monitoring_anomalies,
            monitoring_report=monitoring_report,
            calibration_report=calibration_report,
            flow_report=flow_report,
            feedback_report=feedback_report,
        )
        return evaluate_rules(signals, self.rules)

    def generate_report(self, **kwargs: Any) -> Dict[str, Any]:
        """Convenience wrapper returning the full structured diagnostics report."""

        from .diagnostics_report import build_diagnostics_report

        signals = self.collect_signals(**kwargs)
        hypotheses = evaluate_rules(signals, self.rules)
        return build_diagnostics_report(
            hypotheses=hypotheses,
            context={
                "signals": signals,
                "evaluation_hierarchy": build_evaluation_hierarchy_report(signals),
            },
        )
