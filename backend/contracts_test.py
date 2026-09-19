import os
import sys
import warnings

sys.path.insert(0, os.path.dirname(__file__))

from contracts.contract_validators import (
    enforce_contracts,
    validate_architectural_contracts,
)
from contracts.invariant_checks import (
    ContractViolation,
    check_config_duplication,
    check_score_ranges,
    check_sequence_sensitive_usage,
    is_contract_enforcement_enabled,
)
from contracts.metric_contracts import MetricContract, MetricRegistry, validate_metric_terms
from contracts.schema_guards import (
    validate_monitoring_diagnostic_namespaces,
    validate_persistence_boundary,
    validate_response_boundary,
    validate_trace_schema,
)


def _codes(violations):
    return {item.code for item in violations}


def test_metric_terms_detect_invalid_naming_synonym_drift_and_duplicate_registration():
    violations = validate_metric_terms(["flow health", "semantic_similarity", "vibe_score"])

    assert "invalid_metric_name" in _codes(violations)
    assert "forbidden_synonym_drift" in _codes(violations)

    registry = MetricRegistry()
    first = registry.register(MetricContract(name="semantic_similarity", owner="ranking"))
    second = registry.register(MetricContract(name="semantic_similarity", owner="diagnostics"))

    assert first == []
    assert second[0].code == "duplicate_metric_registration"


def test_response_and_persistence_boundary_leakage_is_reported_without_mutation():
    response_payload = {
        "tracks": [
            {
                "id": "track-1",
                "name": "Safe Track",
                "recommendation_trace": {"semantic_similarity": 0.8},
            }
        ],
        "debug": {"flow_report": {}},
    }
    persistence_payload = {
        "tracks": [
            {
                "id": "track-1",
                "graph_flow_bonus": 0.07,
                "embedding_vector": [0.1, 0.2],
            }
        ]
    }

    response_violations = validate_response_boundary(response_payload)
    persistence_violations = validate_persistence_boundary(persistence_payload)

    assert {"response_debug_boundary_leakage", "response_internal_field_leakage"}.issubset(
        _codes(response_violations)
    )
    assert "persistence_debug_contamination" in _codes(persistence_violations)
    assert response_payload["tracks"][0]["recommendation_trace"]["semantic_similarity"] == 0.8


def test_trace_schema_score_ranges_sequence_misuse_and_namespace_mixing_are_reported():
    trace_violations = validate_trace_schema(
        {
            "request_id": "req_1",
            "timing": {"ranking": {"duration_ms": 12, "unexpected": True}},
            "cache_events": [{"cache_name": "regional", "hit": True, "debug_blob": {}}],
            "unknown_top_level": True,
        }
    )
    range_violations = check_score_ranges(
        {
            "overall_flow_score": 1.2,
            "exploration_ratio": -0.1,
            "raw_cosine_similarity": -0.5,
        }
    )
    sequence_violations = check_sequence_sensitive_usage(
        metric_name="overall_flow_score",
        context={"tracks_are_ordered": False, "source_stage": "candidate_pool"},
    )
    namespace_violations = validate_monitoring_diagnostic_namespaces(
        monitoring_payload={"hypotheses": [{"issue": "diversity_collapse"}]},
        diagnostics_payload={"anomalies": [{"type": "cache_collapse"}]},
    )

    assert "invalid_trace_schema_field" in _codes(trace_violations)
    assert "invalid_score_range" in _codes(range_violations)
    assert "sequence_sensitive_misuse" in _codes(sequence_violations)
    assert "monitoring_diagnostic_namespace_mixing" in _codes(namespace_violations)


def test_config_duplication_and_aggregate_contract_validation_examples():
    config_violations = check_config_duplication(
        {
            "config.scoring_config.FLOW.W_ZONE": 0.30,
            "playlist_flow_engine.W_ZONE": 0.30,
        }
    )
    aggregate = validate_architectural_contracts(
        metric_names=["quality", "exploration_ratio"],
        response_payload={"flow_report": {"overall_flow_score": 0.4}},
        persistence_payload={"tracks": [{"id": "t1", "candidate_embedding": [0.1]}]},
        trace_payload={"timing": {"stage": {"duration_ms": 1, "extra": 2}}},
        score_payload={"quality_score": 1.5},
        sequence_checks=[
            {"metric_name": "artist_repeat_pressure", "context": {"tracks_are_ordered": False}},
        ],
        monitoring_payload={"hypotheses": []},
        diagnostics_payload={"anomalies": []},
        config_sources={
            "config.scoring_config.EXPLORATION.MAX_RATIO": 0.2,
            "exploration_engine.MAX_RATIO": 0.2,
        },
    )

    assert config_violations[0].code == "config_duplication_detected"
    assert aggregate.has_violations is True
    assert "config_duplication_detected" in aggregate.codes
    assert aggregate.examples


def test_enforcement_is_dev_only_and_warns_without_hard_failure(monkeypatch):
    for key in ["SONICDNA_CONTRACTS", "DEBUG_CONTRACTS", "SONICDNA_ENV", "APP_ENV"]:
        monkeypatch.delenv(key, raising=False)
    assert is_contract_enforcement_enabled() is False

    monkeypatch.setenv("SONICDNA_CONTRACTS", "1")
    assert is_contract_enforcement_enabled() is True

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        returned = enforce_contracts([ContractViolation(code="demo", message="example")])

    assert returned[0].code == "demo"
    assert len(caught) == 1
    assert "demo" in str(caught[0].message)
