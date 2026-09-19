# Backend Consolidation Audit

Date: 2026-05-09

Scope: semantic recommendation backend only. This audit reviews the existing
ranking, graph reranking, exploration, flow sequencing, evaluation,
calibration, feedback analytics, runtime tracing, monitoring, diagnostics,
schema separation, and persistence sanitization layers. It proposes
consolidation and simplification opportunities only. It does not recommend new
recommendation systems.

## Executive Summary

The backend has strong separation between recommendation behavior and
observability, but the same concepts are now expressed in too many places:
artist repetition, community repetition, semantic similarity, exploration,
flow quality, stability, cache health, and user-safe serialization all have
multiple representations.

The highest-value simplification is to reduce duplicated measurement surfaces,
not to change recommendation behavior. In practice, this means choosing one
canonical owner for each metric family, then letting calibration, monitoring,
diagnostics, debug models, and docs consume that owner instead of recomputing
near-equivalent values.

## Major Subsystem Map

| Subsystem | Location | Current role | Consolidation pressure |
| --- | --- | --- | --- |
| Primary semantic ranking | `backend/playlist_generator.py`, `backend/embedding_ranker.py`, `backend/user_profile_encoder.py` | Builds genome, mood, popularity, region, quality, and embedding signals. | Several scoring constants exist in `scoring_config.py` but are still duplicated as literals in generator code. |
| Graph reranking | `backend/track_graph.py` | Builds semantic neighbor graph and applies small flow bonus. | Overlaps with flow sequencing through a separate "flow" adjustment concept. |
| Exploration | `backend/exploration_engine.py` | Injects controlled discovery tracks after primary selection. | Recomputes artist, community, semantic, graph, rank, and density signals also used elsewhere. |
| Flow sequencing | `backend/playlist_flow_engine.py` | Reorders selected tracks for pacing and annotates `flow_trace`. | Shares transition distance and session profile concepts with `flow_evaluation.py`; also overlaps with graph flow reranking. |
| Offline evaluation | `backend/evaluation.py`, `backend/flow_evaluation.py` | Computes diversity, novelty, semantic consistency, flow quality, and anti-patterns. | Duplicates helper functions and metric concepts used by calibration, monitoring, and diagnostics. |
| Calibration | `backend/calibration/*.py` | Runs controlled scenarios and regression checks. | Recomputes diversity, semantic, stability, and flow deltas already available from evaluation layers. |
| Feedback analytics | `backend/feedback/feedback_analysis.py` | Aggregates human feedback into exploration, discovery, flow, session, and repetition signals. | Produces parallel names for signals also used by monitoring and diagnostics. |
| Runtime tracing | `backend/debug/runtime_trace.py` | Per-request timing and event-level trace. | Some trace outputs overlap with monitoring counters and debug models. |
| Monitoring | `backend/monitoring/*.py` | Rolling metrics, health report, anomaly detection. | Thresholds are local and partly duplicate evaluation, diagnostics, and calibration thresholds. |
| Diagnostics | `backend/diagnostics/*.py` | Rule-based cross-system hypothesis generation. | Duplicates some anomaly thresholds and issue labels from monitoring, by design, but could consume normalized anomaly types only. |
| Schema separation | `backend/models/*.py` | User, debug, and persistence projections. | Response models and persistence models duplicate large allow/block lists from `persistence_sanitizer.py`. |
| Persistence sanitization | `backend/persistence_sanitizer.py` | Removes transient fields before storage or external boundaries. | Field lists duplicate persistence model blocked fields. |

## Top Architectural Simplification Opportunities

1. Consolidate flow measurement into one owner.
   - Preferred owner: `flow_evaluation.py`.
   - Consumers: calibration, monitoring, diagnostics, debug models.
   - Keep `playlist_flow_engine.py` focused on sequencing and per-track
     `flow_trace`; remove or de-emphasize its separate compact `flow_report`.
   - Estimated complexity reduction: high, about 20-30% less flow-related
     cognitive load.

2. Consolidate track identity and metadata helpers.
   - Duplicate helpers exist for `_primary_artist`, `_track_key` or
     `_track_id`, `_genres`, `_community` or `_cluster`, `_norm`, and cosine
     similarity.
   - Recommendation: move only the already-common, behavior-neutral helpers
     into one existing utility home or pick `evaluation.py` as the read-only
     metric helper source. Do not create new scoring behavior.
   - Estimated complexity reduction: medium, about 10-15% less repeated code.

3. Collapse monitoring and diagnostics threshold ownership.
   - Monitoring should decide what is anomalous.
   - Diagnostics should correlate named anomalies and observed values, not
     maintain independent hidden anomaly thresholds.
   - Estimated complexity reduction: medium, about 15-20% less observability
     ambiguity.

4. Reduce duplicate schema boundary lists.
   - `persistence_sanitizer.py`, `models/persistence_models.py`, and
     `models/response_models.py` each define their own safe/transient field
     vocabulary.
   - Recommendation: choose one blocklist/allowlist owner, then have the
     typed models reference it or explicitly document deviations.
   - Estimated complexity reduction: medium, about 10-15% less boundary risk.

5. Retire dead or literal-shadowed config knobs.
   - `scoring_config.py` is valuable, but many constants are not referenced
     by runtime modules or are shadowed by hard-coded literals.
   - Recommendation: do not add more flexibility. Either wire existing knobs
     into current behavior or delete/comment them as historical candidates.
   - Estimated complexity reduction: high for maintainers, about 20% less
     config scanning burden.

## Duplicate Metric Map

| Metric or signal family | Current locations | Duplication pattern | Preferred owner |
| --- | --- | --- | --- |
| Track identity | `evaluation.py`, `calibration/playlist_diff.py`, `explanation_engine.py`, `exploration_engine.py`, `playlist_flow_engine.py`, `track_graph.py`, `playlist_generator.py` | Each module normalizes IDs or name/artist fallback independently. | One shared read-only helper. |
| Primary artist | `evaluation.py`, `calibration/playlist_diff.py`, `explanation_engine.py`, `exploration_engine.py`, `playlist_flow_engine.py`, `track_graph.py`, `playlist_generator.py`, `spotify_service_fixed.py` | Same first-artist split repeated, sometimes with different fallback behavior. | One shared read-only helper. |
| Genre normalization | `evaluation.py`, `calibration/playlist_diff.py`, `explanation_engine.py`, `exploration_engine.py`, `track_graph.py`, `main.py` | String/list parsing differs slightly by module. | One shared read-only helper. |
| Community or cluster proxy | `exploration_engine.py`, `flow_evaluation.py`, `playlist_flow_engine.py` | Uses explicit community when present, otherwise falls back to artist or genre/region. | `flow_evaluation.py` for measurement, `exploration_engine.py` for behavior. |
| Transition distance | `playlist_flow_engine.py`, `flow_evaluation.py` | Same weighted L1 audio distance with separate functions and partially separate thresholds. | `flow_evaluation.py` for measurement; sequencer may keep local private scoring helper. |
| Flow quality | `flow_evaluation.py`, `playlist_flow_engine.py`, `monitoring/metrics_store.py`, `monitoring/anomaly_detection.py`, `diagnostics/correlation_rules.py`, `calibration/playlist_diff.py` | Score, compact report, quality metric, anomaly, hypothesis, and calibration delta are all separate surfaces. | `flow_evaluation.py` emits metric; monitoring records it; others consume. |
| Diversity | `evaluation.py`, `calibration/playlist_diff.py`, `flow_evaluation.py`, `monitoring/anomaly_detection.py`, `diagnostics/correlation_rules.py`, `feedback/feedback_analysis.py` | Unique artist ratio, artist repeat pressure, artist fatigue, and diversity collapse are related but named separately. | `evaluation.py` for list diversity; `flow_evaluation.py` for ordered repetition. |
| Exploration | `exploration_engine.py`, `flow_evaluation.py`, `runtime_trace.py`, `monitoring/metrics_store.py`, `monitoring/anomaly_detection.py`, `diagnostics/correlation_rules.py`, `feedback/feedback_analysis.py` | Injection count, ratio, position, acceptance, disappearance, and traces are measured separately. | `exploration_engine.py` for behavior; `flow_evaluation.py` for final playlist placement; monitoring only records rates. |
| Semantic similarity | `embedding_ranker.py`, `user_profile_encoder.py`, `evaluation.py`, `track_graph.py`, `exploration_engine.py`, `playlist_generator.py`, `explanation_engine.py`, `calibration/playlist_diff.py` | Cosine normalization and semantic score naming differ by stage. | Keep stage-specific scoring; unify debug/report names. |
| Stability | `evaluation.py`, `calibration/playlist_diff.py`, `calibration/benchmark_runner.py`, `monitoring/metrics_store.py`, `diagnostics/correlation_rules.py` | Same-order ratio, overlap, deterministic flag, stability floor, and instability hypothesis overlap. | `evaluation.py` for primitive; calibration for benchmark interpretation. |
| Cache health | `embedding_ranker.py`, `spotify_service_fixed.py`, `runtime_trace.py`, `monitoring/metrics_store.py`, `monitoring/anomaly_detection.py`, `diagnostics/correlation_rules.py` | Caches exist in multiple modules, but only monitoring has formal cache rates. | Monitoring owns cache health; traces provide event detail only. |

## Issue Inventory

### 1. Flow sequencing and flow evaluation both define transition logic

- Subsystem location: `backend/playlist_flow_engine.py`,
  `backend/flow_evaluation.py`, `backend/config/scoring_config.py`.
- Why duplication exists: sequencing needs a local scoring function while
  evaluation needs observation-only metrics; both evolved around the same
  weighted audio-feature distance.
- Operational risk: a playlist can be optimized under one threshold and judged
  under another. Example: sequencer abrupt floor is `FLOW.ABRUPT_PENALTY_FLOOR`
  while evaluator uses `EVALUATION.ABRUPT_THRESHOLD`.
- Simplification recommendation: keep private scoring helpers in the sequencer
  but make `flow_evaluation.py` the only owner of final reported flow metrics.
  Any health, calibration, diagnostics, or debug payload should consume the
  evaluator report, not the sequencer compact report.
- Estimated complexity reduction: high.

### 2. Graph flow reranking overlaps conceptually with flow sequencing

- Subsystem location: `backend/track_graph.py`,
  `backend/playlist_flow_engine.py`, `backend/playlist_generator.py`.
- Why duplication exists: graph reranking softly boosts semantically adjacent
  tracks before the dedicated flow sequencer reorders by audio pacing.
- Operational risk: two stages both claim to improve "flow", but they operate
  on different notions: semantic neighborhood continuity versus audio arc
  continuity. Debugging a flow regression requires knowing which pass caused it.
- Simplification recommendation: rename/report graph contribution as
  "semantic adjacency bonus" in docs and debug payloads. Reserve "flow" for the
  post-selection sequencer and evaluator.
- Estimated complexity reduction: medium.

### 3. Artist repetition is handled by at least five surfaces

- Subsystem location: `exploration_engine.py`, `playlist_flow_engine.py`,
  `flow_evaluation.py`, `feedback/feedback_analysis.py`,
  `diagnostics/correlation_rules.py`.
- Why duplication exists: artist repetition affects exploration eligibility,
  local sequencing, objective evaluation, user fatigue, and root-cause
  hypotheses.
- Operational risk: an artist can be blocked by exploration, penalized by flow,
  flagged by evaluation, and diagnosed via feedback under different thresholds.
- Simplification recommendation: define a metric vocabulary:
  `artist_repeat_gate` for behavior, `artist_repeat_pressure` for final
  playlist measurement, and `artist_fatigue` for feedback. Avoid adding more
  synonyms such as repetition collapse, repeated artist pressure, or diversity
  pressure unless they map to those three.
- Estimated complexity reduction: medium.

### 4. Exploration has too many derived health names

- Subsystem location: `exploration_engine.py`, `flow_evaluation.py`,
  `runtime_trace.py`, `monitoring/anomaly_detection.py`,
  `feedback/feedback_analysis.py`, `diagnostics/correlation_rules.py`.
- Why duplication exists: exploration started as behavior, then gained
  placement evaluation, monitoring, feedback, and diagnostics.
- Operational risk: "exploration_gone", `exploration_ratio`,
  `exploration_count`, `exploration_positions`, `exploration_acceptance_rate`,
  and `discovery_success_rate` can tell different stories with no hierarchy.
- Simplification recommendation: use a three-layer model:
  injection (`exploration_engine`), final placement (`flow_evaluation`), human
  response (`feedback_analysis`). Monitoring should record only injection rate;
  diagnostics should correlate the three without introducing new metric names.
- Estimated complexity reduction: medium.

### 5. Calibration recomputes evaluation-derived sections

- Subsystem location: `calibration/playlist_diff.py`,
  `calibration/scenario_runner.py`, `evaluation.py`, `flow_evaluation.py`.
- Why duplication exists: calibration needs deltas, so it flattens evaluation
  and flow reports into comparison structures.
- Operational risk: calibration has its own profiles such as
  `_diversity_profile` and `_semantic_trace_profile`, making it unclear whether
  a regression threshold applies to a raw evaluator metric or a calibration
  augmentation.
- Simplification recommendation: keep calibration-specific deltas, but mark
  raw evaluator fields and calibration-only derived fields separately in the
  report. Prefer fewer regression thresholds over more metric deltas.
- Estimated complexity reduction: medium.

### 6. Monitoring anomaly thresholds are isolated from central scoring config

- Subsystem location: `monitoring/anomaly_detection.py`,
  `config/scoring_config.py`.
- Why duplication exists: operational thresholds were added after the scoring
  config and kept local for monitoring.
- Operational risk: maintainers may expect "all thresholds" to be central, but
  latency, cache, quality, and rate anomaly floors live in monitoring only.
- Simplification recommendation: either document monitoring thresholds as
  operational-only and intentionally local, or move only stable quality floors
  into central config. Do not centralize every latency knob unless it is
  actually tuned.
- Estimated complexity reduction: low to medium.

### 7. Diagnostics has secondary thresholds on top of anomalies

- Subsystem location: `diagnostics/correlation_rules.py`,
  `monitoring/anomaly_detection.py`, `flow_evaluation.py`.
- Why duplication exists: diagnostics needs confidence scoring and therefore
  checks raw values in addition to named anomalies.
- Operational risk: diagnostics can imply severity even when monitoring did not
  flag an anomaly, or can use a nearby but different threshold.
- Simplification recommendation: diagnostics should prefer named anomalies and
  explicit evaluator metrics; keep value thresholds only as confidence
  refinements. Document each threshold as correlation-only.
- Estimated complexity reduction: medium.

### 8. Schema separation duplicates sanitization rules

- Subsystem location: `persistence_sanitizer.py`,
  `models/persistence_models.py`, `models/response_models.py`.
- Why duplication exists: sanitization came first as a generic strip pass;
  schema-separated models later made the public and durable contracts explicit.
- Operational risk: a transient field may be added to one list but not the
  other, causing drift between response, persistence, and sanitizer behavior.
- Simplification recommendation: choose one canonical transient blocklist and
  one canonical public allowlist. The typed models should reference or mirror
  that source with tests.
- Estimated complexity reduction: medium.

### 9. Debug models wrap data still embedded in mutable playlist dicts

- Subsystem location: `models/debug_models.py`, `playlist_generator.py`,
  `flow_evaluation.py`, `debug/runtime_trace.py`.
- Why duplication exists: debug models were added as a schema boundary after
  the pipeline already embedded `recommendation_trace`, `flow_report`, and
  scoring fields into track/playlist dicts.
- Operational risk: operators must know whether to inspect raw playlist
  fields, debug envelope models, runtime traces, or flow reports.
- Simplification recommendation: keep existing behavior, but make debug models
  the documented preferred debug envelope. Treat inline fields as legacy
  transport until later cleanup.
- Estimated complexity reduction: medium.

### 10. Runtime trace and monitoring both represent timing and cache health

- Subsystem location: `debug/runtime_trace.py`, `monitoring/metrics_store.py`,
  `monitoring/health_report.py`, `diagnostics/correlation_rules.py`.
- Why duplication exists: trace is per-request, monitoring is rolling aggregate.
- Operational risk: cache hit events and latency stages can be counted in trace
  and monitoring separately; a missing integration can make one layer look
  healthy and the other empty.
- Simplification recommendation: document ownership: runtime trace is event
  detail, monitoring is aggregate health. Diagnostics should never treat a
  missing trace event as equivalent to a monitoring failure unless a trace was
  supplied.
- Estimated complexity reduction: low to medium.

### 11. Evaluation and feedback both describe user dissatisfaction indirectly

- Subsystem location: `flow_evaluation.py`, `feedback/feedback_analysis.py`,
  `diagnostics/correlation_rules.py`.
- Why duplication exists: evaluation describes playlist shape; feedback
  describes perceived quality. Diagnostics bridges the two.
- Operational risk: "flow_degradation", "flow_dissatisfaction",
  "boredom_indicators", "chaos_complaint", and "low flow rating" can look like
  separate issues when they are signals in the same causal chain.
- Simplification recommendation: use evaluator terms for objective structure
  and feedback terms for perception. Diagnostics should be the only layer that
  combines them into hypotheses.
- Estimated complexity reduction: medium.

### 12. Playlist characteristics duplicate evaluation metrics

- Subsystem location: `playlist_generator._analyze_playlist`,
  `evaluation.py`, `flow_evaluation.py`, `models/response_models.py`.
- Why duplication exists: playlist responses need quick scalar summaries while
  evaluation provides deeper offline metrics.
- Operational risk: user-facing `avg_energy`, `avg_valence`, tags, diversity,
  and flow reports can drift or be interpreted as the same metric.
- Simplification recommendation: keep response characteristics minimal and
  user-facing. Avoid exposing evaluator internals in response characteristics.
  Prefer `evaluation.py` for offline quality metrics.
- Estimated complexity reduction: low.

### 13. Spotify metadata scoring is a parallel quality system

- Subsystem location: `spotify_service_fixed.py`,
  `playlist_generator.py`, `config/scoring_config.py`.
- Why duplication exists: Spotify tracks need heuristic audio proxies and
  quality scores before the playlist generator can rank them.
- Operational risk: `quality_score`, metadata `proxy_features`, genre/region
  affinity, preferred artist score, and playlist generator quality weighting
  make the source of "quality" hard to reason about.
- Simplification recommendation: document Spotify metadata scoring as
  candidate retrieval quality only. Keep playlist generator quality weighting
  as recommendation quality. Do not add more quality score names.
- Estimated complexity reduction: medium.

### 14. Fallback constants in modules shadow central config

- Subsystem location: `playlist_generator.py`, `playlist_flow_engine.py`,
  `flow_evaluation.py`, `track_graph.py`, `exploration_engine.py`,
  `config/scoring_config.py`.
- Why duplication exists: modules preserve standalone fallback behavior when
  config import fails.
- Operational risk: config can look authoritative while fallback literals or
  hard-coded literals remain the actual source in some paths.
- Simplification recommendation: keep import fallback only where module
  standalone operation is genuinely required. For integrated backend operation,
  prefer failing fast or documenting fallback as test/demo-only.
- Estimated complexity reduction: medium.

## Repeated Thresholds and Conflicting Heuristics

| Theme | Locations | Conflict or repetition | Recommendation |
| --- | --- | --- | --- |
| Abrupt transition | `FLOW.ABRUPT_PENALTY_FLOOR = 0.35`, `EVALUATION.ABRUPT_THRESHOLD = 0.40`, diagnostics checks flow score separately | Sequencer starts penalizing before evaluator calls a transition abrupt. | Keep both if intentional, but rename as "sequencer penalty floor" vs "evaluation abrupt label". |
| Smoothness | `FLOW.SMOOTH_REWARD_CEILING = 0.45`, `EVALUATION.SMOOTHNESS_SCALE = 1.5`, diagnostics over-smooth threshold `0.85` | Smooth reward, composite score, and boredom hypothesis each have separate math. | Make diagnostics consume component score only; avoid new smoothness thresholds. |
| High energy spike | `FLOW.SPIKE_ENERGY_FLOOR = 0.72`, `EVALUATION.SPIKE_ENERGY_FLOOR = 0.72` | Same number in two classes. | One owner or explicit mirror comment with a test. |
| Artist repeat | exploration gate skips artist repeats, flow adds local penalty, evaluation flags max artist run, feedback flags fatigue at 3 events | Behavior, evaluation, and feedback thresholds differ. | Keep separate, but document as behavior/shape/perception layers. |
| Exploration ratio | generator payload uses `exploration_factor`, engine uses `exploration_ratio`, monitoring uses `exploration_injection_rate`, flow uses `exploration_ratio` | Same concept appears under factor, ratio, rate, and count. | Standardize public/internal naming to ratio for requested target and rate for observed operations. |
| Session profiles | `SESSION_PROFILES` and `SESSION_TARGETS` duplicate energy and valence curves | Evaluation mirrors flow profiles with extra tolerances. | Generate targets from profiles or document mirroring as a required invariant. |
| Semantic similarity | cosine functions and normalization repeated across modules | Some return [-1,1], some convert to [0,1], some return 0 on invalid. | Standardize report labels: `cosine_similarity_raw` vs `semantic_similarity_01`. |
| Cache degradation | runtime trace events, metrics store cache rates, anomaly thresholds, diagnostics confidence thresholds | Multiple layers infer cache health. | Monitoring owns cache health; diagnostics only correlates monitoring anomaly with trace details. |

## Dead Config Candidate List

The following `backend/config/scoring_config.py` values appear not to be
referenced outside the config file, or are currently shadowed by hard-coded
literals. This does not prove they are useless; it marks them as candidates for
either wiring, deleting, or explicitly documenting as reserved.

### Ranking and mood candidates

- `TAG_DANCEABLE_FLOOR`
- `TAG_HIGH_ENERGY_FLOOR`
- `TAG_POSITIVE_FLOOR`
- `TAG_MELANCHOLIC_CEILING`
- `TAG_ACOUSTIC_FLOOR`
- `MOOD_HAPPY_VALENCE_FLOOR`
- `MOOD_SAD_VALENCE_CEILING`
- `MOOD_ENERGETIC_ENERGY_FLOOR`
- `MOOD_FOCUSED_INSTRUMENT_FLOOR`
- `MOOD_FOCUSED_ENERGY_CEILING`
- `MOOD_FILTER_LEXICAL_FLOOR`
- `CALM_ENERGY_CEILING`
- `CALM_VALENCE_FLOOR`
- `CALM_VALENCE_CEILING`
- `CALM_TEMPO_CEILING`
- `NOVELTY_ARTIST_UNFAMILIARITY_FLOOR`
- `NOVELTY_ARTIST_UNFAMILIARITY_RANGE`
- `NOVELTY_REGION_CONFIDENCE_RANGE`
- `NOVELTY_PREFERRED_ARTIST_PARTIAL`
- `POPULARITY_DAMPENING_CAP`
- `NOVELTY_LIBRARY_THRESHOLD`
- `SEED_REGION_CONFIDENCE`
- `SEED_QUALITY_SCORE`
- `SEED_NOVELTY_DISCOVERY`
- `SEED_NOVELTY_LIBRARY`
- `CALM_SEED_DANCE_CAP`
- `CALM_SEED_ENERGY_CAP`
- `CALM_SEED_VALENCE_FLOOR`
- `CALM_SEED_VALENCE_CAP`
- `CALM_SEED_TEMPO_CAP`
- `DEFAULT_REGION_CONFIDENCE_WITH_REGION`
- `DEFAULT_REGION_CONFIDENCE_WITHOUT_REGION`

### Similarity and graph candidates

- `DEFAULT_ENERGY`
- `DEFAULT_VALENCE`
- `DEFAULT_DANCEABILITY`
- `DEFAULT_ACOUSTICNESS`
- `DEFAULT_TEMPO`
- `SMOOTH_DIST_CEILING`
- `ABRUPT_DIST_FLOOR`
- `ARTIST_PARTIAL_MATCH`
- `ARTIST_EXACT_MATCH`

### Exploration candidates

- `BRIDGE_NONE`
- `GRAPH_REWARD_DIST_1`
- `GRAPH_REWARD_DIST_2`
- `GRAPH_REWARD_DIST_3`
- `GRAPH_REWARD_DIST_NONE`
- `GRAPH_MAX_DEPTH`
- `ARTIST_REPEAT_GATE`

### Flow and evaluation candidates

- `INTRO_FRACTION`
- `OUTRO_FRACTION`
- `LOG_ABRUPT_THRESHOLD`
- `LOG_SMOOTH_THRESHOLD`
- `OSCILLATION_WINDOW`
- `LOW_VALENCE_CEILING`
- `VALENCE_COLLAPSE_RATIO`
- `MIN_TRACKS_FOR_OSCILLATION`
- `MIN_TRACKS_FOR_FLAT_ARC`
- `MIN_TRACKS_FOR_COLLAPSE`
- `EXPLORE_CLUSTER_SCORE_FLOOR`
- `ENDING_RESOLUTION_FLOOR`
- `RESOLUTION_OVERSHOOT_SCALE`
- `BAND_HIGH_FLOOR`
- `BAND_LOW_CEIL`
- `MOOD_SMOOTH_DELTA`
- `MOOD_CONTRAST_DELTA`

## Dead Observability Output Candidates

| Output | Location | Why it may be dead or low value | Recommendation |
| --- | --- | --- | --- |
| `PlaylistFlowEngine.flow_report()` compact report | `playlist_flow_engine.py` | `flow_evaluation.evaluate_flow()` provides the richer operational report used by generator, calibration, debug models, and diagnostics. | Keep only if a route consumes it; otherwise document as legacy/demo output. |
| `DebugPlayloadEnvelope` typo in class name | `models/debug_models.py`, `main.py` | Typo creates friction in imports and docs, although behavior works. | Rename only in a compatibility-preserving cleanup later; for now document as internal. |
| `cache_flush` counter | `monitoring/metrics_store.py` | No clear call site in current backend search results. | Remove or wire only if cache flushing exists operationally. |
| `api_errors` counter | `monitoring/metrics_store.py` | No clear call site in current backend search results. | Remove or record at API boundary, not both. |
| Runtime `promotion_events` | `debug/runtime_trace.py` | Promotion is derived from ranking diff and may duplicate `ranking_path`. | Keep either raw ranking diff or promotion summary, not both, unless both are actively used. |
| `failure_warnings` plus monitoring failure counters | `debug/runtime_trace.py`, `monitoring/metrics_store.py` | Per-request and aggregate failure views overlap but are not clearly linked. | Define trace as detailed sample and monitoring as aggregate owner. |

## Redundant Trace Events

| Trace event | Overlaps with | Risk | Simplification |
| --- | --- | --- | --- |
| `ranking_path` | `promotion_events`, debug `ScoringTrace`, calibration ranking consistency | Same movement may appear as position delta, promotion, or stability drift. | Keep `ranking_path` as raw source; derive promotions in display/reporting. |
| `exploration_events` | flow exploration metrics, monitoring injection rate, feedback exploration acceptance | Count can diverge from final playlist placement and user response. | Use trace only for injection decisions; final placement belongs to flow evaluation. |
| `flow_adjustments` | final `flow_report`, `flow_trace` per track, flow evaluation anti-patterns | Flow state is recorded in three places. | Keep per-track `flow_trace` for sequencer debug and evaluator report for quality; avoid another summary. |
| `cache_events` | monitoring cache rates | Per-request cache miss bursts and rolling cache collapse can be confused. | Diagnostics should treat cache events as supporting detail only. |

## Overlapping Anomaly Logic

| Issue label | Monitoring source | Diagnostics source | Consolidation recommendation |
| --- | --- | --- | --- |
| Diversity collapse | `monitoring/anomaly_detection.py` on `playlist_diversity` | `diagnostics/correlation_rules.py` combines anomaly, flow repetition, calibration, feedback | Monitoring owns anomaly; diagnostics owns probable causes. |
| Flow degradation / boredom | Monitoring flags low `flow_quality`; diagnostics flags `flow_smoothness_boredom` | Diagnostics adds entropy, smoothness, and feedback thresholds | Keep boredom only in diagnostics; monitoring should not learn perception labels. |
| Exploration gone | Monitoring flags low injection rate | Diagnostics combines zero final exploration, no trace events, high stability | Good split; avoid adding another exploration anomaly elsewhere. |
| Cache collapse | Monitoring flags cache rates | Diagnostics correlates with latency and trace miss burst | Good split; avoid diagnostics-only cache severity. |
| Instability | Monitoring flags low stability | Calibration measures overlap/order drift; diagnostics correlates sequencing/ranking movement | Calibration should own benchmark instability; monitoring should own operational instability. |

## Candidate Simplification Opportunities

1. Replace repeated helper implementations with one shared helper set for
   identity, primary artist, genres, normalized embeddings, and semantic score
   label conversion.
2. Treat `flow_evaluation.py` as the single final playlist quality metric
   source. Keep `playlist_flow_engine.py` behavior-focused.
3. Standardize names:
   - requested exploration target: `exploration_ratio`
   - observed operational metric: `exploration_injection_rate`
   - final playlist shape: `exploration_count` and `exploration_positions`
   - human outcome: `exploration_acceptance_rate`
4. Collapse debug boundary vocabulary by making sanitizer field lists the
   canonical source for blocked transient fields.
5. Reduce calibration regression thresholds to the few metrics operators
   actually act on: flow quality delta, unique artist diversity delta,
   semantic similarity delta, and playlist overlap.
6. Remove or wire literal-shadowed config values in one pass. Avoid adding new
   knobs until the current list is smaller.
7. In docs and logs, reserve "flow" for post-selection sequencing. Rename graph
   bonus language to "semantic adjacency" to reduce confusion.
8. Keep monitoring anomaly labels minimal and stable. Let diagnostics expand
   them into root-cause hypotheses.

## Recommended Consolidation Roadmap

### Phase 1: Documentation and naming cleanup

- Mark `flow_evaluation.py` as the owner of final flow quality.
- Mark monitoring as the owner of anomaly labels.
- Mark diagnostics as the owner of cross-system hypotheses.
- Update docs to distinguish semantic adjacency from flow sequencing.
- Complexity reduction: low risk, medium impact.

### Phase 2: Dead config pruning

- For each dead config candidate, choose one outcome:
  - wire it into existing code where a matching literal already exists,
  - delete it if behavior should remain literal/simple,
  - or comment it as reserved and remove it from tuning docs.
- Start with obvious literal-shadowed values in `playlist_generator.py`:
  mood filters, calm caps, novelty constants, seed constants, and playlist tag
  thresholds.
- Complexity reduction: high impact, low to medium risk if covered by existing
  calibration tests.

### Phase 3: Metric ownership consolidation

- Make calibration reports distinguish raw evaluator metrics from
  calibration-derived deltas.
- Make diagnostics consume anomaly names first and raw thresholds second.
- Keep only one final flow report shape for operational consumers.
- Complexity reduction: medium impact, medium risk.

### Phase 4: Shared helper extraction

- Extract only behavior-neutral helpers:
  track identity, primary artist, genre normalization, community label, vector
  normalization, cosine similarity conversion.
- Do not extract scoring formulas or ranking policy.
- Complexity reduction: medium impact, medium risk because helper semantics
  must match existing edge cases.

### Phase 5: Boundary model alignment

- Align `persistence_sanitizer.py`, `models/persistence_models.py`, and
  `models/response_models.py` around one canonical safe/transient vocabulary.
- Add narrow tests proving ranking/debug fields do not cross response or
  persistence boundaries.
- Complexity reduction: medium impact, low risk.

## Non-Goals

- Do not remove semantic ranking, graph reranking, exploration, flow sequencing,
  evaluation, calibration, feedback, monitoring, diagnostics, schema models, or
  sanitization.
- Do not auto-tune configuration.
- Do not add ML, RL, or a meta-recommender.
- Do not change recommendation quality targets without calibration.
- Do not replace working heuristics simply because they are heuristic.

