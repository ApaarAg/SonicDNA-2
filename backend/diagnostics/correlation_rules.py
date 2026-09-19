"""
Explainable correlation rules for operational diagnostics.

Rules here only inspect structured observability reports. They do not tune,
rerank, persist state, or call recommendation systems.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence


@dataclass
class SupportingSignal:
    """One concrete signal that supports a diagnostic hypothesis."""

    source: str
    metric: str
    value: Any = None
    interpretation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value not in (None, "")}


@dataclass
class DiagnosticHypothesis:
    """Structured, JSON-serializable diagnostic hypothesis."""

    issue: str
    confidence: float
    probable_causes: List[str] = field(default_factory=list)
    supporting_signals: List[SupportingSignal] = field(default_factory=list)
    affected_metrics: List[str] = field(default_factory=list)
    recommended_investigation: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "issue": self.issue,
            "confidence": round(max(0.0, min(1.0, self.confidence)), 2),
            "probable_causes": sorted(set(self.probable_causes)),
            "supporting_signals": [signal.to_dict() for signal in self.supporting_signals],
            "affected_metrics": sorted(set(self.affected_metrics)),
            "recommended_investigation": self.recommended_investigation,
        }


@dataclass(frozen=True)
class CorrelationRule:
    """Named rule wrapper so the engine can expose explainable rule metadata."""

    name: str
    description: str
    evaluator: Callable[[Mapping[str, Any]], Optional[DiagnosticHypothesis]]

    def evaluate(self, signals: Mapping[str, Any]) -> Optional[DiagnosticHypothesis]:
        return self.evaluator(signals)


def _signals(*items: SupportingSignal) -> List[SupportingSignal]:
    return [item for item in items if item.value is not None or item.interpretation]


def _unique(values: Iterable[str]) -> List[str]:
    return sorted({value for value in values if value})


def _has_anomaly(signals: Mapping[str, Any], anomaly_type: str) -> Optional[Mapping[str, Any]]:
    for anomaly in signals.get("monitoring_anomalies", []):
        if anomaly.get("type") == anomaly_type:
            return anomaly
    return None


def _quality_value(signals: Mapping[str, Any], metric: str) -> Optional[float]:
    quality = signals.get("monitoring_quality", {})
    value = quality.get(metric)
    return float(value) if isinstance(value, (int, float)) else None


def _max_numeric(values: Sequence[Any]) -> Optional[float]:
    numeric = [float(value) for value in values if isinstance(value, (int, float))]
    return max(numeric) if numeric else None


def _rule_diversity_collapse(signals: Mapping[str, Any]) -> Optional[DiagnosticHypothesis]:
    flow = signals.get("flow", {})
    feedback = signals.get("feedback", {})
    calibration = signals.get("calibration", {})
    trace = signals.get("runtime_trace", {})
    anomaly = _has_anomaly(signals, "diversity_collapse")

    repeat_pressure = flow.get("artist_repeat_pressure")
    max_artist_run = flow.get("max_artist_run")
    exploration_ratio = flow.get("exploration_ratio")
    complaint_rate = feedback.get("repetitiveness_complaint_rate")
    fatigue_score = _max_numeric([item.get("fatigue_score") for item in feedback.get("fatigued_artists", [])])
    diversity_regression = calibration.get("diversity_regression")
    flow_adjustment_count = len(trace.get("flow_adjustments", []))

    score = 0.0
    causes: List[str] = []
    affected = ["playlist_diversity"]
    evidence: List[SupportingSignal] = []

    if anomaly:
        score += 0.28
        evidence.append(SupportingSignal("monitoring", anomaly.get("metric", "playlist_diversity"), anomaly.get("current_value"), "Monitoring flagged playlist diversity collapse."))
    if isinstance(repeat_pressure, (int, float)) and repeat_pressure >= 0.35:
        score += 0.2
        causes.append("artist_repetition_pressure")
        affected.append("artist_repeat_pressure")
        evidence.append(SupportingSignal("flow_evaluation", "artist_repeat_pressure", repeat_pressure, "Artist repetition pressure is elevated."))
    if isinstance(max_artist_run, (int, float)) and max_artist_run >= 3:
        score += 0.16
        causes.append("artist_repetition_pressure")
        evidence.append(SupportingSignal("flow_evaluation", "max_artist_run", max_artist_run, "Consecutive artist run crosses the repetition threshold."))
    if isinstance(exploration_ratio, (int, float)) and exploration_ratio <= 0.02:
        score += 0.14
        causes.append("exploration_ratio_too_low")
        affected.append("exploration_ratio")
        evidence.append(SupportingSignal("flow_evaluation", "exploration_ratio", exploration_ratio, "Exploration is absent or near absent in the evaluated playlist."))
    if isinstance(complaint_rate, (int, float)) and complaint_rate >= 0.2:
        score += 0.11
        affected.append("repetitiveness_complaint_rate")
        evidence.append(SupportingSignal("feedback_analytics", "repetitiveness_complaint_rate", complaint_rate, "Users are reporting repetitiveness."))
    if isinstance(fatigue_score, (int, float)) and fatigue_score >= 0.5:
        score += 0.08
        causes.append("artist_fatigue")
        affected.append("artist_fatigue")
        evidence.append(SupportingSignal("feedback_analytics", "artist_fatigue_score", fatigue_score, "Feedback indicates repeated-artist fatigue."))
    if isinstance(diversity_regression, (int, float)) and diversity_regression < -0.05:
        score += 0.13
        causes.append("recent_diversity_regression")
        evidence.append(SupportingSignal("calibration", "diversity_regression", diversity_regression, "Calibration comparison shows diversity moving backward."))
    if flow_adjustment_count:
        causes.append("flow_penalty_overweight")

    if score < 0.45:
        return None
    return DiagnosticHypothesis(
        issue="diversity_collapse",
        confidence=score,
        probable_causes=_unique(causes),
        supporting_signals=evidence,
        affected_metrics=_unique(affected),
        recommended_investigation=[
            "Inspect repeated artists and communities in the final ordered playlist.",
            "Compare exploration injection events against final playlist positions.",
            "Review recent calibration regressions for diversity-related deltas.",
            "Check whether flow penalties are indirectly concentrating similar artists.",
        ],
    )


def _rule_flow_boredom(signals: Mapping[str, Any]) -> Optional[DiagnosticHypothesis]:
    flow = signals.get("flow", {})
    feedback = signals.get("feedback", {})
    anomaly = _has_anomaly(signals, "flow_degradation")

    score_value = flow.get("overall_flow_score")
    entropy = flow.get("flow_entropy")
    smoothness = flow.get("transition_smoothness")
    boredom = feedback.get("flow_dissatisfaction_score")
    low_flow_ratings = feedback.get("low_flow_rating_count")

    score = 0.0
    causes: List[str] = []
    evidence: List[SupportingSignal] = []
    affected = ["flow_quality"]

    if anomaly:
        score += 0.25
        evidence.append(SupportingSignal("monitoring", anomaly.get("metric", "flow_quality"), anomaly.get("current_value"), "Monitoring flagged flow degradation."))
    if isinstance(score_value, (int, float)) and score_value < 0.45:
        score += 0.18
        evidence.append(SupportingSignal("flow_evaluation", "overall_flow_score", score_value, "Flow evaluator rates the playlist as weak."))
    if isinstance(entropy, (int, float)) and entropy < 0.35:
        score += 0.18
        causes.append("low_mood_space_entropy")
        affected.append("flow_entropy")
        evidence.append(SupportingSignal("flow_evaluation", "flow_entropy", entropy, "Mood-space entropy is low, which can feel static."))
    if isinstance(smoothness, (int, float)) and smoothness > 0.85:
        score += 0.12
        causes.append("over_smoothing")
        affected.append("transition_smoothness")
        evidence.append(SupportingSignal("flow_evaluation", "transition_smoothness", smoothness, "Transitions may be too smooth to create enough contrast."))
    if isinstance(boredom, (int, float)) and boredom >= 0.25:
        score += 0.18
        causes.append("boredom_indicators")
        affected.append("flow_dissatisfaction")
        evidence.append(SupportingSignal("feedback_analytics", "flow_dissatisfaction_score", boredom, "Feedback indicates flow dissatisfaction or boredom."))
    if isinstance(low_flow_ratings, (int, float)) and low_flow_ratings > 0:
        score += 0.09
        evidence.append(SupportingSignal("feedback_analytics", "low_flow_rating_count", low_flow_ratings, "Low flow ratings are present."))

    if score < 0.45:
        return None
    return DiagnosticHypothesis(
        issue="flow_smoothness_boredom",
        confidence=score,
        probable_causes=_unique(causes or ["flow_contrast_too_low"]),
        supporting_signals=evidence,
        affected_metrics=_unique(affected),
        recommended_investigation=[
            "Inspect energy and valence series for overly flat arcs.",
            "Compare transition smoothness with user boredom or low satisfaction feedback.",
            "Review flow anti-patterns before changing any scoring weights.",
        ],
    )


def _rule_exploration_disappearance(signals: Mapping[str, Any]) -> Optional[DiagnosticHypothesis]:
    flow = signals.get("flow", {})
    calibration = signals.get("calibration", {})
    trace = signals.get("runtime_trace", {})
    anomaly = _has_anomaly(signals, "exploration_gone")

    exploration_ratio = flow.get("exploration_ratio")
    exploration_events = trace.get("exploration_events", [])
    overlap = calibration.get("average_playlist_overlap")
    order_ratio = calibration.get("same_order_ratio")
    stability = _quality_value(signals, "recommendation_stability")

    score = 0.0
    causes: List[str] = []
    evidence: List[SupportingSignal] = []
    affected = ["exploration_injection_rate", "recommendation_stability"]

    if anomaly:
        score += 0.3
        evidence.append(SupportingSignal("monitoring", anomaly.get("metric", "exploration_injection_rate"), anomaly.get("current_value"), "Monitoring flagged exploration disappearance."))
    if isinstance(exploration_ratio, (int, float)) and exploration_ratio <= 0.02:
        score += 0.18
        causes.append("exploration_ratio_too_low")
        evidence.append(SupportingSignal("flow_evaluation", "exploration_ratio", exploration_ratio, "Playlist-level exploration is absent."))
    if not exploration_events:
        score += 0.1
        evidence.append(SupportingSignal("runtime_trace", "exploration_events", 0, "Runtime trace contains no exploration injection events."))
    if isinstance(overlap, (int, float)) and overlap >= 0.9:
        score += 0.18
        causes.append("stability_overconstraint")
        evidence.append(SupportingSignal("calibration", "average_playlist_overlap", overlap, "Repeated or candidate runs are almost identical."))
    if isinstance(order_ratio, (int, float)) and order_ratio >= 0.9:
        score += 0.14
        causes.append("stability_overconstraint")
        evidence.append(SupportingSignal("calibration", "same_order_ratio", order_ratio, "Ordering is highly stable across repeated runs."))
    if isinstance(stability, (int, float)) and stability >= 0.9:
        score += 0.1
        causes.append("stability_overconstraint")
        evidence.append(SupportingSignal("monitoring", "recommendation_stability", stability, "Operational stability is very high while exploration is absent."))

    if score < 0.45:
        return None
    return DiagnosticHypothesis(
        issue="exploration_disappearance",
        confidence=score,
        probable_causes=_unique(causes),
        supporting_signals=evidence,
        affected_metrics=_unique(affected),
        recommended_investigation=[
            "Trace exploration candidate eligibility before injection.",
            "Compare stability and overlap metrics against exploration counts.",
            "Inspect rejection reasons for exploration candidates; do not change ratios from diagnostics.",
        ],
    )


def _rule_cache_latency(signals: Mapping[str, Any]) -> Optional[DiagnosticHypothesis]:
    trace = signals.get("runtime_trace", {})
    cache_anomaly = _has_anomaly(signals, "cache_collapse")
    latency_anomaly = _has_anomaly(signals, "latency_spike")
    cache_events = trace.get("cache_events", [])
    timings = trace.get("timing", {})

    miss_count = sum(1 for item in cache_events if item.get("hit") is False)
    lookup_count = len(cache_events)
    miss_rate = miss_count / lookup_count if lookup_count else None
    slow_stages = [
        stage for stage, entry in timings.items()
        if isinstance(entry, Mapping) and isinstance(entry.get("duration_ms"), (int, float)) and entry["duration_ms"] >= 1000
    ]

    score = 0.0
    evidence: List[SupportingSignal] = []
    affected = []
    causes: List[str] = []

    if cache_anomaly:
        score += 0.32
        causes.append("cache_hit_rate_collapse")
        affected.append(cache_anomaly.get("metric", "cache"))
        evidence.append(SupportingSignal("monitoring", cache_anomaly.get("metric", "cache"), cache_anomaly.get("current_value"), "Monitoring flagged cache collapse."))
    if latency_anomaly:
        score += 0.28
        affected.append(latency_anomaly.get("metric", "latency"))
        evidence.append(SupportingSignal("monitoring", latency_anomaly.get("metric", "latency"), latency_anomaly.get("current_value"), "Monitoring flagged a latency spike."))
    if isinstance(miss_rate, float) and miss_rate >= 0.6:
        score += 0.15
        causes.append("runtime_cache_miss_burst")
        evidence.append(SupportingSignal("runtime_trace", "cache_miss_rate", round(miss_rate, 3), "Runtime trace shows many cache misses."))
    if slow_stages:
        score += 0.12
        affected.extend(slow_stages)
        evidence.append(SupportingSignal("runtime_trace", "slow_stages", slow_stages, "Trace timing points to slow pipeline stages."))

    if score < 0.5:
        return None
    return DiagnosticHypothesis(
        issue="cache_degradation_latency_spike",
        confidence=score,
        probable_causes=_unique(causes),
        supporting_signals=evidence,
        affected_metrics=_unique(affected),
        recommended_investigation=[
            "Check whether latency spikes align with cache miss bursts by cache name.",
            "Inspect upstream API latency separately from local ranking stages.",
            "Review cache invalidation or cold-start timing before changing recommendation logic.",
        ],
    )


def _rule_sequencing_instability(signals: Mapping[str, Any]) -> Optional[DiagnosticHypothesis]:
    trace = signals.get("runtime_trace", {})
    calibration = signals.get("calibration", {})
    flow = signals.get("flow", {})
    anomaly = _has_anomaly(signals, "instability")

    flow_moves = trace.get("flow_position_change_count")
    ranking_moves = trace.get("ranking_delta_count")
    overlap = calibration.get("minimum_playlist_overlap") or calibration.get("average_playlist_overlap")
    order_ratio = calibration.get("same_order_ratio")
    oscillation = flow.get("arc_direction_changes")

    score = 0.0
    causes: List[str] = []
    affected = ["recommendation_stability"]
    evidence: List[SupportingSignal] = []

    if anomaly:
        score += 0.24
        evidence.append(SupportingSignal("monitoring", anomaly.get("metric", "recommendation_stability"), anomaly.get("current_value"), "Monitoring flagged recommendation instability."))
    if isinstance(flow_moves, (int, float)) and flow_moves >= 5:
        score += 0.18
        causes.append("large_flow_reordering")
        affected.append("flow_position_changes")
        evidence.append(SupportingSignal("runtime_trace", "flow_position_change_count", flow_moves, "Flow sequencing moved many tracks."))
    if isinstance(ranking_moves, (int, float)) and ranking_moves >= 5:
        score += 0.14
        causes.append("ranking_stage_volatility")
        evidence.append(SupportingSignal("runtime_trace", "ranking_delta_count", ranking_moves, "Ranking stages show many position changes."))
    if isinstance(overlap, (int, float)) and overlap < 0.55:
        score += 0.18
        causes.append("candidate_set_volatility")
        evidence.append(SupportingSignal("calibration", "playlist_overlap", overlap, "Repeated or candidate runs have low overlap."))
    if isinstance(order_ratio, (int, float)) and order_ratio < 0.55:
        score += 0.14
        causes.append("ordering_volatility")
        evidence.append(SupportingSignal("calibration", "same_order_ratio", order_ratio, "Ordering changes substantially across runs."))
    if isinstance(oscillation, (int, float)) and oscillation >= 4:
        score += 0.12
        causes.append("flow_penalty_oscillation")
        affected.append("arc_direction_changes")
        evidence.append(SupportingSignal("flow_evaluation", "arc_direction_changes", oscillation, "Flow arc oscillates frequently."))

    if score < 0.45:
        return None
    return DiagnosticHypothesis(
        issue="sequencing_instability",
        confidence=score,
        probable_causes=_unique(causes),
        supporting_signals=evidence,
        affected_metrics=_unique(affected),
        recommended_investigation=[
            "Compare ranking snapshots before and after flow sequencing.",
            "Inspect whether instability begins in candidate retrieval, reranking, or sequencing.",
            "Run repeated calibration scenarios with fixed inputs to isolate nondeterminism.",
        ],
    )


DEFAULT_CORRELATION_RULES: List[CorrelationRule] = [
    CorrelationRule(
        name="diversity_collapse_vs_artist_repetition",
        description="Links low diversity with repeated artists, absent exploration, calibration regression, and fatigue feedback.",
        evaluator=_rule_diversity_collapse,
    ),
    CorrelationRule(
        name="flow_smoothness_vs_boredom",
        description="Links low/over-smooth flow characteristics with boredom or flow dissatisfaction indicators.",
        evaluator=_rule_flow_boredom,
    ),
    CorrelationRule(
        name="exploration_disappearance_vs_stability",
        description="Links absent exploration with unusually high overlap or stability.",
        evaluator=_rule_exploration_disappearance,
    ),
    CorrelationRule(
        name="cache_degradation_vs_latency",
        description="Links cache collapse or miss bursts with latency spikes.",
        evaluator=_rule_cache_latency,
    ),
    CorrelationRule(
        name="sequencing_instability_vs_recommendation_instability",
        description="Links flow/ranking movement with unstable recommendation outputs.",
        evaluator=_rule_sequencing_instability,
    ),
]


def evaluate_rules(
    signals: Mapping[str, Any],
    rules: Optional[Sequence[CorrelationRule]] = None,
) -> List[DiagnosticHypothesis]:
    """Evaluate rules and return hypotheses sorted by confidence descending."""

    hypotheses = [
        hypothesis
        for rule in (rules or DEFAULT_CORRELATION_RULES)
        for hypothesis in [rule.evaluate(signals)]
        if hypothesis is not None
    ]
    hypotheses.sort(key=lambda item: item.confidence, reverse=True)
    return hypotheses
