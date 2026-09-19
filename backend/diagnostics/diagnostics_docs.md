# SonicDNA Diagnostics

This package adds a lightweight diagnostic correlation layer for operational
reasoning and root-cause hypothesis generation. It does not add a new
recommendation system and does not alter ranking, sequencing, scoring config,
feedback state, or playlist output.

## Files

- `diagnostic_engine.py`: normalizes existing observability inputs and runs the rule set.
- `correlation_rules.py`: explainable rules that create structured hypotheses.
- `evaluation_hierarchy.py`: offline hierarchy and overlap analysis for existing metrics.
- `diagnostics_report.py`: report envelope, examples, and Markdown formatting.
- `diagnostics_docs.md`: operator-facing strategy and workflow.

## Optional Operation

Diagnostics are intended for development or operator workflows. Enablement is
explicit via `SONICDNA_DIAGNOSTICS=1` or `DEBUG_DIAGNOSTICS=1`, and also returns
enabled in dev-like environments such as `SONICDNA_ENV=development`.

The engine can also be called directly in tests or offline scripts without
touching production request flow.

## Correlation Reasoning Strategy

1. Normalize runtime traces, monitoring anomalies, calibration reports, flow
   evaluation, and feedback analytics into a compact signal map.
2. Apply named deterministic rules. Each rule records the exact source and
   metric that supported the conclusion.
3. Emit hypotheses with `issue`, `confidence`, `probable_causes`,
   `supporting_signals`, `affected_metrics`, and `recommended_investigation`.
4. Treat confidence as a rule-evidence score, not a learned probability.
5. Keep the output advisory. Diagnostics never auto-tune configs or auto-fix
   behavior.

## Root-Cause Hypothesis Explanation

The diagnostic layer answers: "What issue best explains several systems moving
together?" For example, a diversity anomaly plus repeated artists in flow
evaluation plus artist fatigue in feedback analytics becomes a
`diversity_collapse` hypothesis.

A hypothesis is not a verdict. It is a structured investigation lead with
auditable evidence:

```json
{
  "issue": "diversity_collapse",
  "confidence": 0.82,
  "probable_causes": [
    "artist_repetition_pressure",
    "exploration_ratio_too_low",
    "flow_penalty_overweight"
  ],
  "supporting_signals": [
    {
      "source": "monitoring",
      "metric": "playlist_diversity",
      "value": 0.12,
      "interpretation": "Monitoring flagged low diversity."
    }
  ],
  "affected_metrics": [
    "playlist_diversity",
    "artist_repeat_pressure",
    "exploration_ratio"
  ],
  "recommended_investigation": [
    "Inspect repeated artists and communities in the final ordered playlist.",
    "Compare exploration injection events against final playlist positions."
  ]
}
```

## Correlation Targets

- Diversity collapse vs artist repetition:
  combines monitoring `diversity_collapse`, flow repetition metrics, calibration
  diversity regressions, missing exploration, and artist fatigue feedback.

- Flow smoothness vs boredom indicators:
  combines flow score, entropy, smoothness component scores, and feedback
  dissatisfaction.

- Exploration disappearance vs stability spikes:
  combines `exploration_gone`, zero exploration in flow reports, missing runtime
  exploration events, and high calibration overlap/order stability.

- Cache degradation vs latency spikes:
  combines `cache_collapse`, `latency_spike`, runtime cache miss bursts, and
  slow trace stages.

- Sequencing instability vs recommendation instability:
  combines ranking deltas, flow position changes, calibration overlap/order
  drift, flow oscillation, and monitoring instability.

## Evaluation Hierarchy

`DiagnosticEngine.generate_report()` includes
`diagnostics.context.evaluation_hierarchy`, an offline consolidation report over
the same normalized signals used by correlation rules.

The hierarchy separates:

- Primary metrics: canonical health surfaces for a metric family.
- Derived metrics: component, delta, count, or worst-case views that explain
  primary movement.
- Correlated metrics: feedback, trace, or anomaly evidence that needs
  corroboration.
- Low-signal metrics: absent or empty signals that should be treated as missing
  context, not as healthy outcomes.

The report also lists overlapping metric families, redundant derived/correlated
signal groups, observability entropy drivers, and conflicting optimization
pressures such as stability crowding out exploration or smooth sequencing
coinciding with weak discovery. These are interpretation aids only; they do not
alter thresholds, recommendations, calibration scenarios, or monitoring state.

## Operational Debugging Workflow

1. Start with the highest-confidence hypothesis.
2. Read its `supporting_signals` before acting.
3. Confirm whether monitoring anomalies line up with runtime trace timings or
   event counts.
4. Use calibration reports to decide whether the issue is recent,
   scenario-specific, or stable across runs.
5. Use flow evaluation and feedback analytics to separate playlist shape from
   user perception.
6. Investigate the probable causes manually.
7. Only make recommendation or config changes through the existing calibration
   process, not from diagnostics directly.

## Example Usage

```python
from diagnostics.diagnostic_engine import DiagnosticEngine
from diagnostics.diagnostics_report import build_diagnostics_report

engine = DiagnosticEngine()
hypotheses = engine.generate_hypotheses(
    runtime_trace=trace_dict,
    monitoring_anomalies=anomalies,
    calibration_report=benchmark_report,
    flow_report=flow_report,
    feedback_report=feedback_report,
)
report = build_diagnostics_report(hypotheses=hypotheses)
```

## Safety Guarantees

- No config writes.
- No recommendation behavior changes.
- No ML or RL model.
- No persistence requirement.
- No user-facing output requirement.
- Rule-based and explainable by construction.
