# SonicDNA Runtime Contracts

Date: 2026-05-09

## Purpose

`backend/contracts` converts the existing semantic and architecture
documentation into runtime safeguards. It does not add a recommendation system,
change scoring, reorder tracks, persist data, or redesign the backend. The
package only inspects payloads and returns advisory violations.

## Enforcement Strategy

- Validators are plain functions over dictionaries/lists and are safe to call
  at boundaries.
- `validate_architectural_contracts()` aggregates all checks into a
  `ContractReport`.
- `enforce_contracts()` emits `RuntimeWarning` only when `SONICDNA_CONTRACTS=1`,
  `DEBUG_CONTRACTS=1`, or a dev-like environment is active.
- Production callers can ignore the report, log it, or sample it without
  changing recommendation behavior.
- Tests may assert on violation codes for stricter drift prevention.

## Runtime Safeguards

1. Invalid metric naming: `validate_metric_terms()` warns for non-snake-case
   names and ambiguous single-word metrics such as `quality` or `health`.
2. Forbidden synonym drift: known forbidden phrases such as `flow health` and
   `vibe score` are mapped back to canonical metric names.
3. Response/debug boundary leakage: `validate_response_boundary()` flags debug
   and internal fields before user-facing responses.
4. Persistence/debug contamination: `validate_persistence_boundary()` flags
   ranking traces, graph scores, embeddings, caches, and request-only fields.
5. Invalid trace schema fields: `validate_trace_schema()` checks
   `PipelineTrace.to_dict()` top-level keys and nested event keys.
6. Duplicate metric registration: `MetricRegistry.register()` reports a
   duplicate instead of overwriting the existing contract.
7. Invalid score ranges: `check_score_ranges()` verifies `_score`, `_ratio`,
   `_rate`, `_similarity`, and known scalar metrics.
8. Sequence-sensitive misuse: `check_sequence_sensitive_usage()` catches flow,
   repetition, adherence, and order metrics used before final sequencing.
9. Monitoring/diagnostic namespace mixing:
   `validate_monitoring_diagnostic_namespaces()` keeps anomaly fields in
   monitoring and root-cause hypotheses in diagnostics.
10. Config duplication detection: `check_config_duplication()` flags constants
    duplicated outside `config.scoring_config`.

## Pipeline-Stage Runtime Integrity

`pipeline_integrity.py` adds advisory checks inside the recommendation
pipeline, before final response/debug/persistence validation:

- candidate retrieval: catches empty pools, candidate starvation, corrupted
  tracks, duplicate keys, score range violations, and early diversity collapse.
- post-intent gating: checks survival rate, target pool size, artist diversity,
  and impossible gate health metrics.
- adaptive relaxation: flags exhausted relaxation and repeated fallback
  reasons.
- exploration injection: checks requested exploration that disappears despite
  available candidates, size drift, duplicate keys, and score ranges.
- flow sequencing preconditions: validates stable track identity and finite
  audio features before ordering.
- final ordered playlist: checks size sanity, duplicate keys, low final
  diversity, impossible flow positions, and score ranges.

These checks reuse `ContractViolation` and `enforce_contracts()` so they do not
create a second monitoring system. They only warn when contract enforcement is
enabled and never auto-correct intermediate state.

## Example Invariant Violations

```python
validate_metric_terms(["flow health", "vibe_score"])
# -> forbidden_synonym_drift for "flow health"
# -> forbidden_synonym_drift for "vibe_score"

validate_response_boundary({"flow_report": {"overall_flow_score": 0.4}})
# -> response_debug_boundary_leakage

validate_persistence_boundary({"tracks": [{"embedding_vector": [0.1, 0.2]}]})
# -> persistence_debug_contamination

check_sequence_sensitive_usage(
    "overall_flow_score",
    {"tracks_are_ordered": False, "source_stage": "candidate_pool"},
)
# -> sequence_sensitive_misuse

check_config_duplication({
    "config.scoring_config.FLOW.W_ZONE": 0.30,
    "playlist_flow_engine.W_ZONE": 0.30,
})
# -> config_duplication_detected
```

## Architectural Drift Prevention Workflow

1. Add or rename a metric only after checking `backend/docs/semantic_contracts.md`.
2. Register canonical names in `metric_contracts.py`; do not create aliases for
   comfort.
3. Validate response, debug, trace, persistence, monitoring, and diagnostics
   payloads at their boundary in development.
4. Keep warning mode enabled locally while changing observability code.
5. Add a focused contract test whenever a new boundary field is introduced.
6. Treat violations as architectural review prompts, not automatic behavior
   changes.
