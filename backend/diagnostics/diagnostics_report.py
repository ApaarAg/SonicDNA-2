"""
Diagnostic report rendering helpers.

Reports are JSON-serializable and intended for developer dashboards, logs, or
manual operational review.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping

from .correlation_rules import DiagnosticHypothesis


CORRELATION_REASONING_STRATEGY = [
    "Normalize existing traces, anomalies, calibration outputs, flow reports, and feedback analytics into comparable signals.",
    "Apply named rule-based correlations that require at least two supporting signals for high confidence.",
    "Return hypotheses with causes, supporting evidence, affected metrics, and investigation prompts.",
    "Keep the result advisory: diagnostics never mutate configs, weights, rankings, playlists, or feedback state.",
]


ROOT_CAUSE_HYPOTHESIS_EXPLANATION = [
    "A hypothesis is not a verdict; it is a ranked explanation for why multiple independent systems are moving together.",
    "Confidence is a deterministic score from matched rule evidence, not a learned probability.",
    "Probable causes are phrased as investigation targets so operators can inspect the responsible subsystem manually.",
    "Supporting signals preserve source and metric names to make each conclusion auditable.",
]


OPERATIONAL_DEBUGGING_WORKFLOW = [
    "Start with the highest-confidence issue and inspect its supporting_signals.",
    "Confirm whether monitoring anomalies line up with runtime trace timings or event counts.",
    "Use calibration reports to decide whether the issue is recent, scenario-specific, or stable across runs.",
    "Use flow evaluation and feedback analytics to separate objective playlist shape from user perception.",
    "Investigate the named probable causes manually; do not auto-apply config changes from diagnostic output.",
]


def _hypothesis_dict(item: Any) -> Dict[str, Any]:
    if isinstance(item, DiagnosticHypothesis):
        return item.to_dict()
    if hasattr(item, "to_dict"):
        return dict(item.to_dict())
    if isinstance(item, Mapping):
        return dict(item)
    return {}


def build_diagnostics_report(
    *,
    hypotheses: Iterable[Any],
    context: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build a complete diagnostic report envelope."""

    items = [_hypothesis_dict(item) for item in hypotheses]
    items = [item for item in items if item]
    items.sort(key=lambda item: item.get("confidence", 0), reverse=True)
    return {
        "diagnostics": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": "rule_based_observation_only",
            "hypothesis_count": len(items),
            "hypotheses": items,
            "context": dict(context or {}),
            "safety": {
                "auto_modifies_configs": False,
                "changes_recommendation_behavior": False,
                "uses_ml_or_rl": False,
                "intended_operation": "optional_dev_or_operator_review",
            },
        },
        "correlation_reasoning_strategy": list(CORRELATION_REASONING_STRATEGY),
        "root_cause_hypothesis_explanation": list(ROOT_CAUSE_HYPOTHESIS_EXPLANATION),
        "operational_debugging_workflow": list(OPERATIONAL_DEBUGGING_WORKFLOW),
    }


def example_diagnostic_reports() -> List[Dict[str, Any]]:
    """Representative outputs for docs, tests, and developer dashboards."""

    return [
        {
            "issue": "diversity_collapse",
            "confidence": 0.82,
            "probable_causes": [
                "artist_repetition_pressure",
                "exploration_ratio_too_low",
                "flow_penalty_overweight",
            ],
            "supporting_signals": [
                {
                    "source": "monitoring",
                    "metric": "playlist_diversity",
                    "value": 0.12,
                    "interpretation": "Monitoring flagged low diversity.",
                },
                {
                    "source": "flow_evaluation",
                    "metric": "max_artist_run",
                    "value": 4,
                    "interpretation": "The same artist appears in a long consecutive run.",
                },
                {
                    "source": "feedback_analytics",
                    "metric": "artist_fatigue_score",
                    "value": 0.83,
                    "interpretation": "Feedback suggests repeated-artist fatigue.",
                },
            ],
            "affected_metrics": ["playlist_diversity", "artist_repeat_pressure", "exploration_ratio"],
            "recommended_investigation": [
                "Inspect repeated artists and communities in the final ordered playlist.",
                "Compare exploration injection events against final playlist positions.",
            ],
        },
        {
            "issue": "cache_degradation_latency_spike",
            "confidence": 0.77,
            "probable_causes": ["cache_hit_rate_collapse", "runtime_cache_miss_burst"],
            "supporting_signals": [
                {
                    "source": "monitoring",
                    "metric": "cache_regional",
                    "value": 0.05,
                    "interpretation": "Regional cache hit rate collapsed.",
                },
                {
                    "source": "monitoring",
                    "metric": "candidate_retrieval",
                    "value": 1900,
                    "interpretation": "Candidate retrieval latency spiked.",
                },
            ],
            "affected_metrics": ["cache_regional", "candidate_retrieval"],
            "recommended_investigation": [
                "Check whether latency spikes align with cache miss bursts by cache name.",
                "Inspect upstream API latency separately from local ranking stages.",
            ],
        },
        {
            "issue": "exploration_disappearance",
            "confidence": 0.8,
            "probable_causes": ["exploration_ratio_too_low", "stability_overconstraint"],
            "supporting_signals": [
                {
                    "source": "monitoring",
                    "metric": "exploration_injection_rate",
                    "value": 0.0,
                    "interpretation": "Exploration injection disappeared.",
                },
                {
                    "source": "calibration",
                    "metric": "average_playlist_overlap",
                    "value": 0.94,
                    "interpretation": "Runs are almost identical while exploration is absent.",
                },
            ],
            "affected_metrics": ["exploration_injection_rate", "recommendation_stability"],
            "recommended_investigation": [
                "Trace exploration candidate eligibility before injection.",
                "Compare stability and overlap metrics against exploration counts.",
            ],
        },
    ]


def format_markdown_report(report: Mapping[str, Any]) -> str:
    """Render a concise Markdown version for operator notes."""

    diagnostics = report.get("diagnostics", {})
    lines = [
        "# SonicDNA Diagnostic Report",
        "",
        f"Mode: {diagnostics.get('mode', 'rule_based_observation_only')}",
        f"Hypotheses: {diagnostics.get('hypothesis_count', 0)}",
        "",
    ]
    for item in diagnostics.get("hypotheses", []):
        lines.extend(
            [
                f"## {item.get('issue', 'unknown_issue')}",
                f"- Confidence: {item.get('confidence')}",
                f"- Probable causes: {', '.join(item.get('probable_causes', []))}",
                f"- Affected metrics: {', '.join(item.get('affected_metrics', []))}",
                "- Recommended investigation:",
            ]
        )
        for step in item.get("recommended_investigation", []):
            lines.append(f"  - {step}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
