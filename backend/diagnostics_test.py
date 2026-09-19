import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from diagnostics.diagnostic_engine import DiagnosticEngine, is_diagnostics_enabled
from diagnostics.diagnostics_report import build_diagnostics_report, example_diagnostic_reports
from diagnostics.evaluation_hierarchy import build_evaluation_hierarchy_report


def test_diversity_collapse_correlates_artist_repetition_feedback_and_calibration():
    engine = DiagnosticEngine()
    hypotheses = engine.generate_hypotheses(
        runtime_trace={
            "exploration_events": [],
            "flow_adjustments": [
                {"dominant_signal": "cluster_penalty", "flow_score": 0.21},
            ],
        },
        monitoring_anomalies=[
            {"type": "diversity_collapse", "metric": "playlist_diversity", "current_value": 0.12},
        ],
        calibration_report={
            "regression_detection": {
                "findings": [
                    {"metric": "diversity.unique_artists_ratio", "value": -0.14},
                ]
            }
        },
        flow_report={
            "repetition_metrics": {
                "artist_repeat_pressure": 0.62,
                "max_artist_run": 4,
                "top_repeated_artists": ["repeat artist"],
            },
            "exploration_metrics": {"exploration_ratio": 0.0},
            "anti_patterns": [{"pattern": "repetitive_artist_run"}],
        },
        feedback_report={
            "artist_fatigue": {
                "fatigued_artists": [{"artist": "repeat artist", "fatigue_score": 0.83}],
            },
            "repetitive_playlist_detection": {"complaint_rate": 0.4, "complaint_count": 3},
        },
    )

    diversity = hypotheses[0].to_dict()
    assert diversity["issue"] == "diversity_collapse"
    assert diversity["confidence"] >= 0.8
    assert "artist_repetition_pressure" in diversity["probable_causes"]
    assert "exploration_ratio_too_low" in diversity["probable_causes"]
    assert "playlist_diversity" in diversity["affected_metrics"]
    assert diversity["supporting_signals"]
    assert diversity["recommended_investigation"]


def test_cache_degradation_correlates_cache_misses_and_latency_spikes():
    engine = DiagnosticEngine()
    hypotheses = engine.generate_hypotheses(
        runtime_trace={
            "timing": {
                "candidate_retrieval": {"duration_ms": 1900},
                "recommendation_total": {"duration_ms": 2500},
            },
            "cache_events": [
                {"cache_name": "regional", "hit": False},
                {"cache_name": "regional", "hit": False},
                {"cache_name": "search", "hit": False},
                {"cache_name": "search", "hit": True},
            ],
        },
        monitoring_anomalies=[
            {"type": "cache_collapse", "metric": "cache_regional", "current_value": 0.05},
            {"type": "latency_spike", "metric": "candidate_retrieval", "current_value": 1900},
        ],
    )

    cache = hypotheses[0].to_dict()
    assert cache["issue"] == "cache_degradation_latency_spike"
    assert cache["confidence"] >= 0.75
    assert "cache_hit_rate_collapse" in cache["probable_causes"]
    assert "candidate_retrieval" in cache["affected_metrics"]


def test_exploration_disappearance_correlates_with_stability_spikes_without_mutation():
    engine = DiagnosticEngine()
    calibration_report = {
        "aggregate": {"average_playlist_overlap": 0.94},
        "scenario_reports": [{"recommendation_stability": {"same_order_ratio": 0.96}}],
    }
    flow_report = {"exploration_metrics": {"exploration_ratio": 0.0, "exploration_count": 0}}

    hypotheses = engine.generate_hypotheses(
        monitoring_anomalies=[
            {"type": "exploration_gone", "metric": "exploration_injection_rate", "current_value": 0.0},
        ],
        calibration_report=calibration_report,
        flow_report=flow_report,
    )

    exploration = hypotheses[0].to_dict()
    assert exploration["issue"] == "exploration_disappearance"
    assert "stability_overconstraint" in exploration["probable_causes"]
    assert calibration_report["aggregate"]["average_playlist_overlap"] == 0.94
    assert flow_report["exploration_metrics"]["exploration_ratio"] == 0.0


def test_report_builder_returns_examples_strategy_and_workflow():
    report = build_diagnostics_report(
        hypotheses=[
            {
                "issue": "sequencing_instability",
                "confidence": 0.71,
                "probable_causes": ["flow_penalty_oscillation"],
                "supporting_signals": [{"source": "flow_evaluation", "metric": "arc_direction_changes"}],
                "affected_metrics": ["recommendation_stability"],
                "recommended_investigation": ["Compare ranking diffs before and after flow sequencing."],
            }
        ],
        context={"window": 50},
    )

    assert report["diagnostics"]["hypothesis_count"] == 1
    assert report["correlation_reasoning_strategy"]
    assert report["operational_debugging_workflow"]
    assert example_diagnostic_reports()[0]["issue"]


def test_evaluation_hierarchy_classifies_metric_roles_and_reasons():
    engine = DiagnosticEngine()
    signals = engine.collect_signals(
        monitoring_report={
            "quality_metrics": {
                "playlist_diversity": {"mean": 0.31},
                "flow_quality": {"mean": 0.86},
                "recommendation_stability": {"mean": 0.93},
                "cache_regional": {"mean": 0.72},
            }
        },
        calibration_report={
            "regression_detection": {
                "regression_count": 1,
                "findings": [{"metric": "diversity.unique_artists_ratio", "value": -0.11}],
            },
            "aggregate": {"average_playlist_overlap": 0.91},
            "scenario_reports": [{"recommendation_stability": {"same_order_ratio": 0.94}}],
        },
        flow_report={
            "flow_quality": {
                "overall_flow_score": 0.88,
                "flow_entropy": 0.18,
                "component_scores": {"transition_smoothness": 0.91},
            },
            "repetition_metrics": {
                "artist_repeat_pressure": 0.49,
                "community_repeat_pressure": 0.42,
                "max_artist_run": 3,
            },
            "exploration_metrics": {"exploration_ratio": 0.04, "exploration_count": 1},
        },
        feedback_report={
            "artist_fatigue": {"fatigued_artists": [{"artist": "repeat artist"}]},
            "repetitive_playlist_detection": {"complaint_rate": 0.25, "complaint_count": 2},
        },
        runtime_trace={"cache_events": [{"cache_name": "regional", "hit": True}]},
    )

    report = build_evaluation_hierarchy_report(signals)
    classification = report["classification"]

    assert any(item["metric"] == "playlist_diversity" for item in classification["primary_metrics"])
    assert any(item["metric"] == "overall_flow_score" for item in classification["primary_metrics"])
    assert any(item["metric"] == "transition_smoothness" for item in classification["derived_metrics"])
    assert any(item["metric"] == "fatigued_artists" for item in classification["correlated_metrics"])
    assert all(item["reason"] for items in classification.values() for item in items)


def test_evaluation_hierarchy_detects_overlap_entropy_and_conflicts():
    engine = DiagnosticEngine()
    signals = engine.collect_signals(
        monitoring_anomalies=[
            {"type": "exploration_gone", "metric": "exploration_injection_rate", "current_value": 0.0},
            {"type": "diversity_collapse", "metric": "playlist_diversity", "current_value": 0.19},
        ],
        monitoring_report={
            "quality_metrics": {
                "playlist_diversity": {"mean": 0.19},
                "recommendation_stability": {"mean": 0.96},
                "flow_quality": {"mean": 0.91},
            }
        },
        calibration_report={
            "aggregate": {"average_playlist_overlap": 0.95},
            "scenario_reports": [{"recommendation_stability": {"same_order_ratio": 0.97}}],
        },
        flow_report={
            "flow_quality": {
                "overall_flow_score": 0.9,
                "component_scores": {"transition_smoothness": 0.93},
            },
            "repetition_metrics": {"artist_repeat_pressure": 0.57, "max_artist_run": 4},
            "exploration_metrics": {"exploration_ratio": 0.0, "exploration_count": 0},
        },
    )

    report = build_evaluation_hierarchy_report(signals)
    overlap_families = {item["family"] for item in report["overlapping_metric_families"]}
    conflicts = {item["pressure"] for item in report["conflicting_optimization_pressures"]}

    assert {"diversity", "exploration", "stability"}.issubset(overlap_families)
    assert report["observability_entropy"]["level"] in {"moderate", "high"}
    assert "stability_vs_exploration" in conflicts
    assert "flow_smoothness_vs_discovery" in conflicts


def test_diagnostic_report_embeds_evaluation_hierarchy_without_mutation():
    engine = DiagnosticEngine()
    calibration_report = {
        "aggregate": {"average_playlist_overlap": 0.94},
        "scenario_reports": [{"recommendation_stability": {"same_order_ratio": 0.96}}],
    }

    report = engine.generate_report(
        monitoring_anomalies=[
            {"type": "exploration_gone", "metric": "exploration_injection_rate", "current_value": 0.0}
        ],
        calibration_report=calibration_report,
        flow_report={"exploration_metrics": {"exploration_ratio": 0.0, "exploration_count": 0}},
    )

    diagnostics = report["diagnostics"]
    assert diagnostics["context"]["evaluation_hierarchy"]["metric_count"] >= 1
    assert diagnostics["safety"]["changes_recommendation_behavior"] is False
    assert calibration_report["aggregate"]["average_playlist_overlap"] == 0.94


def test_diagnostics_enablement_is_dev_or_explicit_only(monkeypatch):
    for key in ["SONICDNA_DIAGNOSTICS", "DEBUG_DIAGNOSTICS", "SONICDNA_ENV", "APP_ENV"]:
        monkeypatch.delenv(key, raising=False)
    assert is_diagnostics_enabled() is False

    monkeypatch.setenv("SONICDNA_DIAGNOSTICS", "1")
    assert is_diagnostics_enabled() is True
