# SonicDNA Calibration Harness

This package is an offline evaluation layer for controlled recommendation tuning. It wraps the existing semantic ranking, graph reranking, exploration injection, playlist flow sequencing, `evaluation.py`, `flow_evaluation.py`, centralized `scoring_config`, and explanation traces.

It does not redesign recommendation logic, persist benchmark artifacts into canonical DB state, train models, or auto-tune weights.

## Package Contents

- `scenario_runner.py`: controlled persona/session scenarios such as focus, workout, emotional, discovery, conservative listener, adventurous listener, mainstream-heavy listener, and niche listener.
- `playlist_diff.py`: playlist overlap, diversity delta, semantic consistency, semantic balance diagnostics, flow quality, explanation trace, and stability comparisons.
- `benchmark_runner.py`: config A/B orchestration, temporary scoring config overrides, aggregate reports, stability checks, and regression detection.
- `human_perception.py`: offline human-review schema, metric-vs-human comparison, disagreement diagnostics, and perceptual stress-test scenario names.
- `calibration_docs.md`: workflow notes, examples, and regression strategy.

## Calibration Workflow

1. Choose one or more scenarios from `SCENARIOS`.
2. Define config A and config B. Each config can provide a label, a stub or real generator, optional Spotify service, scenario overrides, and temporary `scoring_config` overrides.
3. Run `run_ab_benchmark`.
4. Inspect `scenario_reports` for playlist overlap, flow deltas, diversity deltas, semantic consistency, and explanation trace changes.
5. Treat regression findings as review gates. The harness reports possible regressions; it never changes weights automatically.

Semantic balance diagnostics are offline-only observations. They report
embedding neighborhood diversity, identity-neighbor dominance, texture
utilization, semantic basin collapse risk, cross-region discovery connectivity,
and cross-genre texture-coherent retrieval. They do not change ranking,
exploration injection, flow sequencing, or embedding generation.

Long-horizon exploration diagnostics are also offline-only. They are attached
to repeated-run stability reports and summarize cross-session exploration
diversity, repeated semantic corridors, recurring exploration archetypes,
novelty decay, repeated bridge-region reuse, and long-term semantic attractor
risk. Use `long_horizon_drift_probe` and `novelty_sustainability_probe` with
`run_stability_benchmark` when checking discovery behavior across many runs.

Topology behavior diagnostics are offline-only repeated-run observations. They
summarize cross-family exploration diversity, macro-family over-concentration,
bridge-genre over-reliance, regional permeability balance, semantic shortcut
collapse risk, and culturally meaningful crossover quality. Use
`topology_permeability_probe` and `macro_family_shortcut_probe` when checking
whether discovery remains permeable without collapsing into one macro-family or
creating unrealistic shortcuts across distinct neighborhoods.

Human-perception calibration is offline-only and advisory. Use
`analyze_human_perception(playlist, human_reviews, session_type=...)` after a
review session to compare objective metrics against structured ratings for
overall quality, discovery magic, emotional realism, memorability, subjective
coherence, and perceived novelty. The report flags metric-human disagreement,
technically healthy but emotionally weak playlists, fake novelty, over-smoothed
emotional arcs, and artificial-feeling exploration. The utility only reads
playlist data and existing `evaluation.py` / `flow_evaluation.py` reports; it
does not train models, persist feedback, change thresholds, or affect runtime
recommendations.

Perceptual stress-test scenarios are available for offline review planning:
`perceived_discovery_quality_probe`, `emotional_realism_probe`,
`memorability_probe`, and `subjective_coherence_probe`.

## Example Benchmark

```python
from calibration.benchmark_runner import run_ab_benchmark

report = run_ab_benchmark(
    config_a={
        "label": "baseline",
    },
    config_b={
        "label": "candidate_exploration",
        "scoring_overrides": {
            "EXPLORATION.DEFAULT_RATIO": 0.18,
        },
    },
    scenario_names=[
        "focus",
        "workout",
        "emotional",
        "discovery",
        "conservative_listener",
        "adventurous_listener",
        "mainstream_heavy_listener",
        "niche_listener",
    ],
)
```

## Example Structured Report

```json
{
  "config_a": {"label": "baseline"},
  "config_b": {"label": "candidate_exploration"},
  "metric_deltas": {
    "flow.overall_flow_score": 0.018,
    "diversity.unique_artists_ratio": 0.041,
    "semantic.avg_trace_semantic_similarity": -0.012
  },
  "playlist_overlap": 0.62,
  "flow_quality_delta": 0.018,
  "diversity_delta": {
    "unique_artists_ratio": 0.041,
    "novelty.mainstream_niche_balance": 0.027
  }
}
```

## Regression Detection Strategy

Regression detection compares candidate deltas against explicit thresholds:

- Flow quality should not drop materially for any persona.
- Diversity should not collapse, especially unique artist ratio and mainstream/niche balance.
- Semantic consistency should not drop beyond the configured tolerance.
- Playlist overlap should not be too low unless the experiment intentionally targets major exploration behavior.
- Recommendation stability can be measured with repeated runs for the same scenario and config.

Default thresholds live in `DEFAULT_REGRESSION_THRESHOLDS` and can be overridden per benchmark run.

## Notes

- Config overrides are applied by temporarily patching centralized `scoring_config` class attributes and restoring them after each scenario run.
- Reports are returned in memory. Persist them only to an explicit experiment folder if a caller chooses to do so outside this package.
- Use stub generators for deterministic unit tests and real `PlaylistGenerator` instances for offline integration runs.
