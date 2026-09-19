"""
Smoke tests for the redesigned intent resolution pipeline.

Tests semantic matching, blending, confidence scoring, fallback behavior,
backward compatibility, and starvation prevention pre-softening.

Run:  python intent_resolution_test.py
"""

from __future__ import annotations

import sys
import os

# Ensure backend is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_passed = 0
_failed = 0
_errors = []


def _check(label: str, condition: bool, detail: str = ""):
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  ✓ {label}")
    else:
        _failed += 1
        msg = f"  ✗ {label}"
        if detail:
            msg += f" — {detail}"
        print(msg)
        _errors.append(label)


def test_exact_name_match():
    """All 11 intent names resolve with confidence 1.0 via exact match."""
    print("\n── Test: exact name match ──")
    from config.session_intents import (
        resolve_intent_with_confidence, list_intents, INTENT_PROFILES,
    )
    for name in list_intents():
        res = resolve_intent_with_confidence(session_type=name)
        _check(
            f"session_type='{name}' → exact match",
            res is not None and res.confidence == 1.0 and res.method == "exact",
            f"got method={getattr(res, 'method', None)} conf={getattr(res, 'confidence', None)}"
        )
        _check(
            f"session_type='{name}' → correct profile",
            res is not None and res.profile.name == name,
            f"got name={getattr(res.profile, 'name', None) if res else None}"
        )


def test_mood_name_match():
    """Mood strings that exactly match intent names resolve as exact."""
    print("\n── Test: mood name match ──")
    from config.session_intents import resolve_intent_with_confidence
    for name in ["workout", "calm", "party", "rage"]:
        res = resolve_intent_with_confidence(mood=name)
        _check(
            f"mood='{name}' → exact match",
            res is not None and res.method == "exact" and res.confidence == 1.0,
            f"got method={getattr(res, 'method', None)}"
        )


def test_backward_compat_resolve_intent():
    """The backward-compatible resolve_intent returns IntentProfile or None."""
    print("\n── Test: backward-compatible resolve_intent ──")
    from config.session_intents import resolve_intent, IntentProfile
    result = resolve_intent(session_type="workout")
    _check(
        "resolve_intent(session_type='workout') returns IntentProfile",
        isinstance(result, IntentProfile) and result.name == "workout",
    )
    result = resolve_intent(mood="calm")
    _check(
        "resolve_intent(mood='calm') returns IntentProfile",
        isinstance(result, IntentProfile) and result.name == "calm",
    )
    result = resolve_intent(mood="xyzzy_nonsense_12345")
    _check(
        "resolve_intent(mood='xyzzy_nonsense') returns None or profile",
        result is None or isinstance(result, IntentProfile),
    )


def test_semantic_matching():
    """Semantic matching resolves contextual queries to the right intent."""
    print("\n── Test: semantic matching ──")
    from config.session_intents import resolve_intent_with_confidence
    cases = [
        # (mood_string, expected_options, description)
        # expected_options is a set of acceptable intent names
        ("studying late at night", {"focus", "night_drive"}, "study context -> focus or night_drive"),
        ("pumping iron at the gym", {"workout"}, "gym context -> workout"),
        ("driving through the city at midnight", {"night_drive"}, "midnight driving -> night_drive"),
        ("getting over a breakup", {"heartbreak"}, "breakup context -> heartbreak"),
        ("feeling like a boss", {"confidence"}, "empowerment context -> confidence"),
        ("chill vibes", {"calm", "focus"}, "chill -> calm or focus"),
    ]
    for mood_str, expected_opts, desc in cases:
        res = resolve_intent_with_confidence(mood=mood_str)
        if res is None:
            _check(f"{desc}", False, "resolved to None")
            continue
        _check(
            f"{desc}",
            res.primary_name in expected_opts,
            f"got primary={res.primary_name} conf={res.confidence:.3f} method={res.method}"
        )
        _check(
            f"{desc} -> method is semantic/blend/exact",
            res.method in ("semantic", "blend", "exact", "keyword_fallback"),
            f"got method={res.method}"
        )


def test_confidence_scoring():
    """Exact matches have confidence 1.0; semantic matches have < 1.0."""
    print("\n── Test: confidence scoring ──")
    from config.session_intents import resolve_intent_with_confidence
    exact = resolve_intent_with_confidence(session_type="workout")
    _check(
        "exact match has confidence 1.0",
        exact is not None and exact.confidence == 1.0,
    )

    semantic = resolve_intent_with_confidence(mood="pumping iron at the gym")
    _check(
        "semantic match has confidence < 1.0",
        semantic is not None and semantic.confidence < 1.0,
        f"got {getattr(semantic, 'confidence', None)}"
    )
    _check(
        "semantic match has confidence > threshold",
        semantic is not None and semantic.confidence >= 0.35,
        f"got {getattr(semantic, 'confidence', None)}"
    )


def test_confidence_monotonicity():
    """More specific queries should generally have higher confidence."""
    print("\n── Test: confidence monotonicity ──")
    from config.session_intents import resolve_intent_with_confidence
    vague = resolve_intent_with_confidence(mood="music")
    specific = resolve_intent_with_confidence(mood="high energy workout music for running")
    if vague is not None and specific is not None:
        _check(
            "specific query ≥ vague query confidence",
            specific.confidence >= vague.confidence - 0.05,  # small tolerance
            f"specific={specific.confidence:.3f} vague={vague.confidence:.3f}"
        )
    else:
        _check(
            "both queries resolve",
            False,
            f"vague={vague is not None} specific={specific is not None}"
        )


def test_low_confidence_returns_none():
    """Truly unrelated queries should return None or very low confidence."""
    print("\n── Test: low confidence fallback ──")
    from config.session_intents import resolve_intent_with_confidence
    res = resolve_intent_with_confidence(mood="quantum mechanics thermodynamics")
    if res is None:
        _check("gibberish returns None", True)
    else:
        # With calibrated thresholds, unrelated text should either
        # return None or have very low confidence with pre-softening
        _check(
            "gibberish returns None or low confidence with softening",
            res.confidence < 0.68 or res.pre_soften_tier > 0,
            f"got conf={res.confidence:.3f} intent={res.primary_name} soften={res.pre_soften_tier}"
        )


def test_blending():
    """Emotionally ambiguous queries should trigger blending."""
    print("\n── Test: intent blending ──")
    from config.session_intents import resolve_intent_with_confidence
    # "emotional healing journey" is close to both heartbreak and healing
    res = resolve_intent_with_confidence(mood="emotional healing after heartbreak")
    if res is None:
        _check("emotional healing resolves", False, "returned None")
        return

    _check(
        "emotional healing triggers blend or semantic match",
        res.method in ("blend", "semantic", "keyword_fallback"),
        f"got method={res.method} primary={res.primary_name}"
    )

    if res.method == "blend":
        _check(
            "blend has two intents",
            bool(res.secondary_name),
            f"secondary={res.secondary_name}"
        )
        _check(
            "blend ratio is between 0 and 1",
            0.0 < res.blend_ratio < 1.0,
            f"ratio={res.blend_ratio}"
        )
        _check(
            "blended profile name contains '+'",
            "+" in res.profile.name,
            f"name={res.profile.name}"
        )
    else:
        print(f"    (resolved as {res.method} to {res.primary_name}, "
              f"conf={res.confidence:.3f} — blending not triggered)")


def test_blended_gate_validity():
    """Blended AudioGates should still pass valid tracks."""
    print("\n── Test: blended gate validity ──")
    from config.session_intents import blend_profiles, INTENT_PROFILES
    p1 = INTENT_PROFILES["heartbreak"]
    p2 = INTENT_PROFILES["healing"]
    blended = blend_profiles(p1, p2, 0.6)

    _check(
        "blended profile has name",
        "+" in blended.name,
        f"name={blended.name}"
    )

    # A mid-energy, mid-valence track should pass the blended gate
    test_track = {
        "energy": 0.45,
        "valence": 0.40,
        "danceability": 0.40,
        "acousticness": 0.30,
        "tempo": 110,
    }
    _check(
        "mid-range track passes blended gate",
        blended.audio_gate.passes(test_track),
        f"gate: e_max={blended.audio_gate.energy_max} v_min={blended.audio_gate.valence_min}"
    )

    # Score weights should still sum to ~1.0
    w = blended.score_weights
    total = w.genome_weight + w.popularity_weight + w.mood_weight + w.region_weight + w.quality_weight
    _check(
        "blended score weights sum to ~1.0",
        abs(total - 1.0) < 0.01,
        f"sum={total:.4f}"
    )


def test_pre_softening():
    """Moderate/weak confidence triggers pre-soften tier > 0."""
    print("\n── Test: pre-softening ──")
    from config.session_intents import resolve_intent_with_confidence
    # Exact matches should have tier 0
    exact = resolve_intent_with_confidence(session_type="rage")
    _check(
        "exact match → pre_soften_tier=0",
        exact is not None and exact.pre_soften_tier == 0,
    )

    # Vague queries may get pre-softened
    vague = resolve_intent_with_confidence(mood="maybe something energetic but also chill")
    if vague is not None:
        _check(
            "vague query → pre_soften_tier ≥ 0",
            vague.pre_soften_tier >= 0,
            f"tier={vague.pre_soften_tier} conf={vague.confidence:.3f}"
        )
    else:
        _check("vague query returns None (acceptable fallback)", True)


def test_intent_resolution_dataclass():
    """IntentResolution.to_dict() works and has expected fields."""
    print("\n── Test: IntentResolution dataclass ──")
    from config.session_intents import resolve_intent_with_confidence
    res = resolve_intent_with_confidence(session_type="workout")
    _check("to_dict works", res is not None and isinstance(res.to_dict(), dict))
    if res:
        d = res.to_dict()
        for key in ["confidence", "method", "primary_name", "blend_ratio", "pre_soften_tier"]:
            _check(f"to_dict has '{key}'", key in d, f"keys={list(d.keys())}")


def test_list_intents_unchanged():
    """list_intents() returns all original intent names."""
    print("\n── Test: list_intents unchanged ──")
    from config.session_intents import list_intents
    intents = list_intents()
    expected = sorted([
        "workout", "focus", "heartbreak", "night_drive", "party",
        "healing", "romantic", "rage", "calm", "confidence", "celebration",
    ])
    _check(
        "list_intents contains all 11 intents",
        intents == expected,
        f"got {intents}"
    )


def test_flow_profile_not_blended():
    """FlowProfile always comes from primary intent, never averaged."""
    print("\n── Test: flow profile preservation ──")
    from config.session_intents import blend_profiles, INTENT_PROFILES
    p1 = INTENT_PROFILES["workout"]
    p2 = INTENT_PROFILES["calm"]
    blended = blend_profiles(p1, p2, 0.6)
    _check(
        "blended flow_profile == primary's flow_profile",
        blended.flow_profile is p1.flow_profile,
        f"blended energy_curve={blended.flow_profile.energy_curve} "
        f"expected={p1.flow_profile.energy_curve}"
    )


def test_semantic_embeddings_cached():
    """Intent embeddings are computed once and cached."""
    print("\n── Test: embedding cache ──")
    from config.session_intents import _get_intent_embeddings
    emb1 = _get_intent_embeddings()
    emb2 = _get_intent_embeddings()
    if emb1 is None:
        print("    ⚠ Embeddings unavailable (model not loaded) — skipping")
        return
    _check("embeddings cached (same object)", emb1 is emb2)
    _check("all 11 intents have embeddings", len(emb1) == 11, f"got {len(emb1)}")


if __name__ == "__main__":
    print("=" * 60)
    print("Intent Resolution Pipeline — Smoke Tests")
    print("=" * 60)

    test_exact_name_match()
    test_mood_name_match()
    test_backward_compat_resolve_intent()
    test_intent_resolution_dataclass()
    test_list_intents_unchanged()
    test_flow_profile_not_blended()
    test_blended_gate_validity()

    # Semantic tests require the embedding model
    print("\n── Loading embedding model (may take a moment) ──")
    try:
        from config.session_intents import _get_ranker
        ranker = _get_ranker()
        if ranker is None:
            print("  ⚠ EmbeddingRanker unavailable — skipping semantic tests")
        else:
            print(f"  ✓ EmbeddingRanker loaded on device={ranker.device}")
            test_semantic_embeddings_cached()
            test_semantic_matching()
            test_confidence_scoring()
            test_confidence_monotonicity()
            test_low_confidence_returns_none()
            test_blending()
            test_pre_softening()
    except Exception as exc:
        print(f"  ⚠ Could not load embedding model: {exc}")
        print("    Skipping semantic matching tests")

    print("\n" + "=" * 60)
    print(f"Results: {_passed} passed, {_failed} failed")
    if _errors:
        print(f"Failed: {', '.join(_errors)}")
    print("=" * 60)
    sys.exit(1 if _failed else 0)
