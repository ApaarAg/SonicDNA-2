import os
import sys
import warnings

sys.path.insert(0, os.path.dirname(__file__))

from contracts.pipeline_integrity import (
    PipelineStage,
    validate_adaptive_relaxation_outcome,
    validate_candidate_pool_integrity,
    validate_exploration_injection_integrity,
    validate_final_ordered_playlist,
    validate_post_intent_gate_health,
    validate_sequencing_preconditions,
)


def _codes(violations):
    return {item.code for item in violations}


def _track(idx, artist=None, **extra):
    track = {
        "id": f"t{idx}",
        "name": f"Track {idx}",
        "artist": artist or f"Artist {idx}",
        "energy": 0.4 + idx * 0.03,
        "valence": 0.5,
        "danceability": 0.5,
        "tempo": 110,
        "quality_score": 0.8,
    }
    track.update(extra)
    return track


def test_candidate_pool_integrity_detects_empty_corrupted_starved_and_diversity_collapse():
    violations = validate_candidate_pool_integrity(
        "candidate_retrieval",
        [
            {"id": "broken", "artist": "Same Artist"},
            _track(1, artist="Same Artist", quality_score=1.4),
            _track(2, artist="Same Artist"),
        ],
        min_count=5,
    )

    assert {
        "candidate_starvation",
        "corrupted_candidate_pool",
        "diversity_collapse",
        "invalid_score_range",
    }.issubset(_codes(violations))


def test_intent_gate_and_relaxation_validators_detect_starvation_and_repeated_fallbacks():
    health = {
        "pool_name": "library",
        "pre_gate": 30,
        "post_gate": 3,
        "survival_rate": 0.1,
        "unique_artists": 1,
        "diversity_ratio": 0.333,
        "relaxation_tier": 3,
        "is_starved": True,
    }

    gate_violations = validate_post_intent_gate_health(health, target_size=15)
    relaxation_violations = validate_adaptive_relaxation_outcome(
        health,
        fallback_history=["spotify_empty_or_failed", "spotify_empty_or_failed"],
    )

    assert "candidate_starvation" in _codes(gate_violations)
    assert "diversity_collapse" in _codes(gate_violations)
    assert "adaptive_relaxation_exhausted" in _codes(relaxation_violations)
    assert "repeated_fallback_loop" in _codes(relaxation_violations)


def test_exploration_sequencing_and_final_playlist_validators_detect_stage_misuse():
    before = [_track(i) for i in range(6)]
    after = list(before)
    candidates = [_track(20), _track(21)]
    exploration_violations = validate_exploration_injection_integrity(
        before_tracks=before,
        after_tracks=after,
        candidate_pool=candidates,
        requested_ratio=0.2,
    )

    invalid_for_flow = [
        _track(1, id="same", energy="bad"),
        _track(2, id="same"),
        {"id": "nameless", "energy": 0.5, "valence": 0.5},
    ]
    sequencing_violations = validate_sequencing_preconditions(invalid_for_flow)

    final_violations = validate_final_ordered_playlist(
        [_track(1, flow_position=3), _track(2, exploration=True)],
        requested_size=5,
        requested_exploration_ratio=0.2,
    )

    assert "exploration_disappearance" in _codes(exploration_violations)
    assert "invalid_sequencing_input" in _codes(sequencing_violations)
    assert "unstable_ordering_conditions" in _codes(sequencing_violations)
    assert "final_playlist_structural_sanity" in _codes(final_violations)
    assert "impossible_metric_state" in _codes(final_violations)


def test_stage_validators_are_advisory_only_when_contracts_enabled(monkeypatch):
    monkeypatch.setenv("SONICDNA_CONTRACTS", "1")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        original = [_track(1)]
        violations = PipelineStage.CANDIDATE_RETRIEVAL.validate(
            tracks=original,
            min_count=3,
            emit_warnings=True,
        )

    assert original == [_track(1)]
    assert "candidate_starvation" in _codes(violations)
    assert any("candidate_starvation" in str(item.message) for item in caught)
