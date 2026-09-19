# Semantic Contracts

Date: 2026-05-09

Scope: this document defines canonical semantic meanings for the existing
recommendation backend. It standardizes names and interpretation boundaries
only. It does not change recommendation behavior, redesign architecture, add a
backend system, or introduce new metrics.

## Purpose

The backend now has multiple observation layers: ranking traces, graph
reranking, exploration, flow sequencing, evaluation, calibration, monitoring,
diagnostics, feedback analytics, and schema-separated models. These layers may
talk about the same concept with different names. This document is the contract
for what each term means, who owns it, and how other subsystems may consume it.

## Canonical Terminology Map

| Canonical term | Canonical metric names | Owner | Do not rename as |
| --- | --- | --- | --- |
| Flow | `flow_trace`, `flow_position`, `flow_sequencing` | `playlist_flow_engine.py` | graph flow, semantic flow, vibe order |
| Flow quality | `overall_flow_score`, `flow_quality`, `component_scores` | `flow_evaluation.py` | flow health, smoothness score, vibe score |
| Semantic similarity | `semantic_similarity`, `user_embedding_similarity`, `semantic_match` | ranking/evaluation contexts | relevance, affinity, quality |
| Diversity | `unique_artists_ratio`, `unique_genres_ratio`, `playlist_diversity` | `evaluation.py` | novelty, exploration, repetition control |
| Stability | `playlist_overlap`, `same_order_ratio`, `recommendation_stability` | `evaluation.py`, `calibration/*` | determinism, consistency, confidence |
| Exploration | `exploration_ratio`, `exploration_count`, `exploration_injection_rate` | `exploration_engine.py` | discovery, novelty, diversity |
| Novelty | `inverse_popularity`, `mainstream_ratio`, `niche_ratio`, `mainstream_niche_balance` | `evaluation.py` | exploration, discovery quality |
| Recommendation quality | `quality_score`, `primary_score`, `final_rank_score`, evaluator metrics | stage-specific | flow quality, popularity, correctness |
| Cache health | `cache_<name>`, `cache_hit_rate`, `cache_collapse` | `monitoring/*` | latency, retrieval quality |
| Semantic adjacency | `graph_weight`, `graph_flow_bonus`, `graph_neighborhood` | `track_graph.py` | flow, semantic similarity |
| Texture continuity | `transition_semantic.texture_coherence`, `transition_semantic.texture_delta`, embedding texture descriptors | `playlist_flow_engine.py`, `track_profile_builder.py` | mood similarity, semantic similarity, flow quality |
| Artist repetition | `artist_repeat_pressure`, `max_artist_run`, `artist_fatigue` | `flow_evaluation.py`, feedback for fatigue | diversity collapse, community collapse |
| Community repetition | `community_repeat_pressure`, `max_cluster_run` | `flow_evaluation.py` | artist repetition, graph density |
| Playlist coherence | composite interpretation from flow, semantic, diversity, session metrics | evaluation/calibration consumers | flow quality, semantic similarity alone |
| Session adherence | `adherence_score`, `spike_violations`, `energy_variance_ok` | `flow_evaluation.py` | mood match, personalization |
| Recommendation failure | `playlist_failed`, `empty_candidates`, `candidate_nonempty_rate`, `elevated_failures` | `monitoring/*` | low quality, poor flow |

## Metric Interpretation Guide

Use this guide when reading reports:

- Scores in `[0, 1]` are not interchangeable. A `0.8` semantic similarity is
  not equivalent to a `0.8` flow quality or cache hit rate.
- Objective metrics describe playlist structure or system behavior. Perceptual
  metrics describe user response. Diagnostics may correlate them, but should
  not merge their names.
- Local metrics describe a track, transition, cache lookup, or request. Global
  metrics describe a playlist, scenario, rolling window, or benchmark.
- Sequence-sensitive metrics depend on final order. They must not be computed
  from unordered candidate pools.
- Monitoring owns anomaly labels. Diagnostics owns cross-system hypotheses.
- Calibration owns comparison and regression interpretation. It should not
  redefine base metric meaning.

## Term Contracts

### 1. Flow

- Canonical meaning: the post-selection ordering behavior that arranges an
  already-selected track list into a temporal and emotional sequence.
- Valid range: not a scalar by itself. Related scalar outputs include
  `flow_position` as zero-based position and per-track `flow_trace.flow_score`
  as a local sequencer score.
- Objective or perceptual: objective.
- Local or global: local for per-track `flow_trace`; global when discussing the
  complete ordered playlist.
- Sequence-sensitive: yes.
- Owning subsystem: `backend/playlist_flow_engine.py`.
- Consuming subsystems: `playlist_generator.py`, runtime tracing, debug models,
  flow evaluation.
- Operational interpretation: flow explains why selected tracks were placed in
  a particular order. It does not explain why a track was selected.
- Common misuse risks: using "flow" to describe graph reranking, semantic
  similarity, or any pleasant-sounding playlist property.
- Related metrics: `flow_position`, `flow_trace`, `flow_sequencing` latency,
  `overall_flow_score`.
- Forbidden synonym drift: do not use "graph flow", "semantic flow", "vibe
  flow", or "playlist quality" when the intended meaning is ordering behavior.

### 2. Flow Quality

- Canonical meaning: an observation-only assessment of an already-ordered
  playlist's pacing, arc, repetition control, exploration placement,
  start/end quality, and session fit.
- Valid range: `overall_flow_score` in `[0, 1]`; grade is one of `excellent`,
  `good`, `fair`, `poor`.
- Objective or perceptual: objective structural metric. It may correlate with
  perception but is not user satisfaction.
- Local or global: global playlist-level metric with component scores.
- Sequence-sensitive: yes.
- Owning subsystem: `backend/flow_evaluation.py`.
- Consuming subsystems: playlist generator debug output, calibration,
  monitoring, diagnostics, debug models.
- Operational interpretation: low flow quality means the final order has
  structural pacing issues. It does not imply bad semantic relevance.
- Common misuse risks: treating `transition_smoothness` as the full flow
  quality score; treating low flow quality as a recommendation failure.
- Related metrics: `avg_transition_distance`, `arc_direction_changes`,
  `flow_entropy`, `artist_repeat_pressure`, `session_adherence`.
- Forbidden synonym drift: do not call this "flow health", "boredom score",
  "smoothness", or "recommendation quality".

### 3. Semantic Similarity

- Canonical meaning: embedding-based closeness between a user/query/profile and
  a track or playlist centroid, normalized according to the producing stage.
- Valid range: raw cosine similarity may be `[-1, 1]`; reported
  `semantic_similarity`, `user_embedding_similarity`, and `semantic_match`
  should be interpreted as `[0, 1]` unless explicitly labelled raw cosine.
- Objective or perceptual: objective model-derived signal.
- Local or global: local for track-to-user or track-to-track; global when
  computed against a playlist centroid.
- Sequence-sensitive: no, except when reported alongside sequence diagnostics.
- Owning subsystem: stage-specific. Track ranking owns per-track semantic
  similarity; `evaluation.py` owns playlist-level `semantic_match`.
- Consuming subsystems: playlist generator, graph, exploration, explanation,
  calibration, diagnostics.
- Operational interpretation: higher semantic similarity means closer embedding
  alignment. It does not guarantee diversity, novelty, flow, or satisfaction.
  Track profile text may use `identity`, `secondary`, and `context` section
  markers to prioritize descriptors for embeddings; these markers are not
  metrics and must not appear as calibration fields.
- Common misuse risks: calling semantic similarity "quality"; comparing raw
  cosine and normalized `[0, 1]` scores as if they share a scale.
- Related metrics: `embedding_distance`, `avg_trace_semantic_similarity`,
  `semantic_trace_coverage`, `graph_weight`.
- Forbidden synonym drift: do not use "relevance", "fit", "affinity", or
  "quality" without naming the semantic similarity metric.

### 4. Diversity

- Canonical meaning: variety across the unordered final track list, primarily
  unique artists and unique genres.
- Valid range: ratios in `[0, 1]`; monitoring `playlist_diversity` follows the
  recorded quality score scale `[0, 1]`.
- Objective or perceptual: objective.
- Local or global: global playlist-level metric.
- Sequence-sensitive: no. Sequence-sensitive repetition belongs to artist or
  community repetition metrics.
- Owning subsystem: `backend/evaluation.py`.
- Consuming subsystems: calibration, monitoring, diagnostics.
- Operational interpretation: low diversity means the playlist set is narrow.
  It does not identify whether the narrowness is due to artist repetition,
  community repetition, low exploration, or candidate retrieval.
- Common misuse risks: using diversity to mean novelty, exploration, or
  anti-repetition in local sequence windows.
- Related metrics: `unique_artists_ratio`, `unique_genres_ratio`,
  `artist_repeat_pressure`, `community_repeat_pressure`,
  `diversity_collapse`.
- Forbidden synonym drift: do not call diversity "discovery", "novelty",
  "variety score" unless mapped to the canonical metric.

### 5. Stability

- Canonical meaning: similarity of recommendation outputs across repeated runs
  or compared configurations, measured by track overlap and ordering
  consistency.
- Valid range: `playlist_overlap`, `same_order_ratio`, and monitoring
  `recommendation_stability` are in `[0, 1]`.
- Objective or perceptual: objective.
- Local or global: global across playlists, benchmark runs, or rolling
  operation windows.
- Sequence-sensitive: partly. `playlist_overlap` is not sequence-sensitive;
  `same_order_ratio` is sequence-sensitive.
- Owning subsystem: `backend/evaluation.py` for primitives;
  `backend/calibration/*` for benchmark interpretation.
- Consuming subsystems: calibration, monitoring, diagnostics.
- Operational interpretation: high stability means repeated outputs are
  similar; low stability means candidate selection or ordering is volatile.
- Common misuse risks: treating high stability as always good. Excessive
  stability can indicate exploration disappearance.
- Related metrics: `playlist_overlap`, `same_order_ratio`, `deterministic`,
  `average_playlist_overlap`, `minimum_overlap`.
- Forbidden synonym drift: do not use "determinism", "confidence", or
  "consistency" unless the exact stability metric is named.

### 6. Exploration

- Canonical meaning: controlled injection of semantically related discovery
  tracks into an already-ranked playlist tail.
- Valid range: requested `exploration_ratio` in `[0, MAX_RATIO]`; observed
  `exploration_count` is integer `0..playlist_size`; observed
  `exploration_injection_rate` is `[0, 1]`.
- Objective or perceptual: objective for injection and placement; perceptual
  only when using feedback metrics such as acceptance.
- Local or global: local for candidate `exploration_score`; global for playlist
  count/ratio and rolling monitoring rate.
- Sequence-sensitive: injection itself is not sequence-sensitive; final
  placement metrics are sequence-sensitive.
- Owning subsystem: `backend/exploration_engine.py`.
- Consuming subsystems: playlist generator, flow evaluation, runtime tracing,
  monitoring, feedback analytics, diagnostics.
- Operational interpretation: exploration means controlled discovery. It is
  not the same as all discovery tracks and not the same as novelty.
- Common misuse risks: using "discovery" and "exploration" interchangeably;
  interpreting zero exploration as failure without checking requested ratio.
- Related metrics: `exploration_score`, `exploration_meta`,
  `exploration_ratio`, `exploration_count`, `exploration_positions`,
  `exploration_acceptance_rate`, `exploration_gone`.
- Forbidden synonym drift: do not call exploration "novelty", "discovery", or
  "diversity" without preserving the explicit exploration metric name.

### 7. Novelty

- Canonical meaning: how non-mainstream or less popularity-dominated a playlist
  is, based on popularity distribution proxies.
- Valid range: `inverse_popularity`, `mainstream_ratio`, `niche_ratio`, and
  `mainstream_niche_balance` are in `[0, 1]`.
- Objective or perceptual: objective proxy.
- Local or global: global playlist-level metric in evaluation; local
  `novelty_score` may appear on tracks from generator logic.
- Sequence-sensitive: no.
- Owning subsystem: `backend/evaluation.py` for playlist novelty;
  `playlist_generator.py` for local track novelty labelling.
- Consuming subsystems: calibration, diagnostics where available.
- Operational interpretation: high novelty means lower mainstream dominance or
  better mainstream/niche balance. It does not necessarily mean exploration was
  used.
- Common misuse risks: using novelty as a synonym for discovery, exploration,
  or user surprise.
- Related metrics: `inverse_popularity`, `mainstream_ratio`, `niche_ratio`,
  `mainstream_niche_balance`, local `novelty_score`.
- Forbidden synonym drift: do not call novelty "exploration", "discovery
  quality", or "diversity".

### 8. Recommendation Quality

- Canonical meaning: stage-specific estimate of how suitable a candidate or
  final ranked item is for recommendation, before or after ranking passes.
- Valid range: scalar scoring outputs should be interpreted as `[0, 1]` when
  named `quality_score`, `primary_score`, or `final_rank_score`, unless a
  stage explicitly documents another scale.
- Objective or perceptual: objective heuristic/model signal, not user
  satisfaction.
- Local or global: local track-level signal; aggregate quality must be named
  by its owning metric, such as flow quality or diversity.
- Sequence-sensitive: no, except post-sequencing debug traces may include final
  rank context.
- Owning subsystem: stage-specific. Candidate retrieval quality belongs to
  `spotify_service_fixed.py`; recommendation ranking quality belongs to
  `playlist_generator.py`.
- Consuming subsystems: explanation, response projection, debug models,
  calibration.
- Operational interpretation: quality score supports ranking decisions. It is
  not a contract that the final playlist is coherent, diverse, or stable.
- Common misuse risks: treating `quality_score` as an end-to-end playlist
  quality metric.
- Related metrics: `quality_score`, `primary_score`, `pre_embedding_score`,
  `post_embedding_score`, `final_rank_score`, `overall_flow_score`.
- Forbidden synonym drift: do not use "quality" alone in reports. Always name
  the stage: candidate quality, ranking quality, flow quality, or playlist
  quality hypothesis.

### 9. Cache Health

- Canonical meaning: operational effectiveness of in-memory or service-level
  caches, measured by hit rates and related latency anomalies.
- Valid range: cache hit rates in `[0, 1]`; cache event `hit` is boolean.
- Objective or perceptual: objective operational metric.
- Local or global: local for runtime `cache_events`; global for monitoring
  rolling cache rates.
- Sequence-sensitive: no.
- Owning subsystem: `backend/monitoring/metrics_store.py` and
  `backend/monitoring/anomaly_detection.py`.
- Consuming subsystems: health report, diagnostics, runtime tracing.
- Operational interpretation: poor cache health can explain latency spikes. It
  does not imply poor recommendation quality.
- Common misuse risks: interpreting cache miss bursts as retrieval failure or
  semantic degradation.
- Related metrics: `cache_search`, `cache_regional`, `cache_embedding`,
  `cache_collapse`, `latency_spike`.
- Forbidden synonym drift: do not call cache health "retrieval quality",
  "candidate quality", or "service health" without the cache metric.

### 10. Semantic Adjacency

- Canonical meaning: graph-neighborhood relationship between tracks based on
  embedding similarity, artist affinity, genre overlap, and regional overlap.
- Valid range: `graph_weight` in `[0, 1]`; `graph_flow_bonus` is an additive
  local bonus bounded by graph configuration.
- Objective or perceptual: objective graph-derived signal.
- Local or global: local track-to-track or node-neighborhood signal.
- Sequence-sensitive: adjacency itself is not sequence-sensitive; graph
  reranking may apply it relative to previous placed tracks.
- Owning subsystem: `backend/track_graph.py`.
- Consuming subsystems: playlist generator, exploration, explanation,
  diagnostics.
- Operational interpretation: semantic adjacency means two tracks are nearby in
  the graph. It is not the same as playlist flow.
- Common misuse risks: calling graph reranking "flow" and confusing semantic
  neighborhood continuity with audio transition smoothness.
- Related metrics: `graph_weight`, `graph_flow_bonus`, `graph_neighborhood`,
  `graph_distance`, `bridge_score`.
- Forbidden synonym drift: do not rename semantic adjacency to "flow",
  "semantic similarity", or "coherence" without naming the graph signal.

### 11. Artist Repetition

- Canonical meaning: repeated occurrence of the same primary artist in the
  playlist, especially consecutive or locally clustered repeats.
- Valid range: `artist_repeat_pressure` in `[0, 1]`; `max_artist_run` is
  integer `0..track_count`; `artist_fatigue` is feedback-derived and
  report-specific.
- Objective or perceptual: objective for repeat pressure and max run;
  perceptual for feedback fatigue.
- Local or global: local when measuring consecutive runs or recent windows;
  global when reporting playlist summary.
- Sequence-sensitive: yes for pressure and max run; no for unordered artist
  counts.
- Owning subsystem: `backend/flow_evaluation.py` for final sequence metrics;
  `backend/feedback/feedback_analysis.py` for fatigue.
- Consuming subsystems: monitoring through diversity quality, diagnostics,
  calibration reports.
- Operational interpretation: high artist repetition can explain diversity
  collapse or user fatigue, but is not identical to either.
- Common misuse risks: treating artist repetition as community repetition or as
  all diversity.
- Related metrics: `artist_repeat_pressure`, `max_artist_run`,
  `top_repeated_artists`, `artist_fatigue`.
- Forbidden synonym drift: do not call it "diversity collapse", "artist
  fatigue", or "community collapse" unless those separate metrics are present.

### 12. Community Repetition

- Canonical meaning: repeated occurrence of the same explicit community or
  fallback cluster proxy in the final ordered playlist.
- Valid range: `community_repeat_pressure` in `[0, 1]`; `max_cluster_run` is
  integer `0..track_count`.
- Objective or perceptual: objective.
- Local or global: local when measuring consecutive runs; global when reported
  as playlist summary.
- Sequence-sensitive: yes.
- Owning subsystem: `backend/flow_evaluation.py`.
- Consuming subsystems: diagnostics, calibration, debug models.
- Operational interpretation: high community repetition suggests local
  semantic or stylistic collapse even if artists differ.
- Common misuse risks: treating community repetition as graph density, artist
  repetition, or diversity.
- Related metrics: `community_repeat_pressure`, `max_cluster_run`,
  `top_repeated_clusters`, `local_community_collapse`.
- Forbidden synonym drift: do not call it "graph collapse", "artist
  repetition", or "local density" without the exact metric.

### 13. Playlist Coherence

- Canonical meaning: an operator-level interpretation that a playlist holds
  together across semantic relevance, sequence flow, session adherence,
  repetition control, and diversity.
- Valid range: no direct scalar. Use named component metrics instead.
- Objective or perceptual: mixed interpretation. Component metrics are
  objective; user feedback may add perceptual evidence.
- Local or global: global playlist-level interpretation.
- Sequence-sensitive: partly, because flow and repetition components are
  sequence-sensitive.
- Owning subsystem: no single scoring owner. Calibration and diagnostics may
  discuss coherence by citing component metrics.
- Consuming subsystems: diagnostics, calibration docs, operator reports.
- Operational interpretation: coherence is a summary claim, not a metric. A
  report must cite the component metrics that justify it.
- Common misuse risks: inventing a new "coherence score" or using coherence as
  a synonym for flow quality.
- Related metrics: `semantic_match`, `overall_flow_score`,
  `adherence_score`, `unique_artists_ratio`, `artist_repeat_pressure`,
  local `transition_semantic.texture_coherence` diagnostics.
- Forbidden synonym drift: do not use "coherence" as a field name unless it is
  clearly a report label and not a new metric.

### 14. Texture Continuity

- Canonical meaning: local transition compatibility of production texture and
  sonic-world feel, estimated from existing metadata such as acousticness,
  instrumentalness, speechiness, liveness, tempo, danceability, genre text, and
  title/query context.
- Valid range: `transition_semantic.texture_coherence` is a local trace value
  in `[0, 1]`; `transition_semantic.texture_delta` is a local distance-like
  diagnostic. Embedding texture descriptors are plain text tokens, not scalar
  metrics.
- Objective or perceptual: objective heuristic proxy for perceptual texture.
- Local or global: local transition diagnostic only.
- Sequence-sensitive: yes.
- Owning subsystem: `backend/playlist_flow_engine.py` for transition traces;
  `backend/track_profile_builder.py` for embedding text descriptors.
- Consuming subsystems: flow trace inspection, embedding ranking text, and
  diagnostics that cite these exact local fields.
- Operational interpretation: texture continuity helps explain why emotional
  contrast can still feel coherent when synthetic/organic balance, atmosphere,
  vocal density, production feel, rhythmic aggression, and ambient weight stay
  compatible.
- Common misuse risks: treating texture continuity as semantic similarity,
  ranking quality, or a playlist-level score.
- Related metrics: `transition_semantic_reward`, `transition_identity`,
  `semantic_similarity`, `overall_flow_score`.
- Forbidden synonym drift: do not call this "mood similarity", "sonic quality",
  "vibe score", or "flow quality".

### 15. Session Adherence

- Canonical meaning: how closely an ordered playlist follows the target energy
  and valence profile for a requested session type.
- Valid range: `adherence_score` in `[0, 1]`; `spike_violations` integer
  `0..track_count`; `energy_variance_ok` boolean.
- Objective or perceptual: objective structural metric.
- Local or global: global playlist-level metric with per-zone calculation.
- Sequence-sensitive: yes.
- Owning subsystem: `backend/flow_evaluation.py`.
- Consuming subsystems: calibration, diagnostics, debug models.
- Operational interpretation: low session adherence means the playlist shape
  does not match the requested session profile. It does not necessarily mean
  bad mood matching or low semantic similarity.
- Common misuse risks: using session adherence as a synonym for mood fit,
  satisfaction, or personalization.
- Related metrics: `adherence_score`, `spike_violations`,
  `energy_variance_ok`, `energy_stdev`, `variance_tolerance`.
- Forbidden synonym drift: do not call this "mood match", "intent match", or
  "personalization" unless the session adherence metric is explicitly named.

### 16. Recommendation Failure

- Canonical meaning: operational inability to produce a successful
  recommendation response or candidate set, not a low-quality playlist.
- Valid range: counters are integers; operational rates are `[0, 1]`; failure
  rate is failures per minute.
- Objective or perceptual: objective operational metric.
- Local or global: local for request exceptions and trace warnings; global for
  monitoring counters and rates.
- Sequence-sensitive: no.
- Owning subsystem: `backend/monitoring/metrics_store.py` and
  `backend/monitoring/anomaly_detection.py`.
- Consuming subsystems: health report, diagnostics, runtime tracing.
- Operational interpretation: recommendation failure means generation failed,
  candidates were empty, or failure rate is elevated. It is not the same as low
  diversity, low flow quality, or bad feedback.
- Common misuse risks: labelling any poor metric as a failure; mixing
  recoverable trace warnings with endpoint failures.
- Related metrics: `playlist_failed`, `empty_candidates`,
  `candidate_nonempty_rate`, `playlist_success`, `elevated_failures`,
  `failure_warnings`.
- Forbidden synonym drift: do not call low quality, instability, cache
  degradation, or user dissatisfaction a recommendation failure unless the
  operational failure metric is present.

## Naming Consistency Recommendations

Use these names consistently:

| Use | Avoid |
| --- | --- |
| `exploration_ratio` for requested target | `exploration_factor`, `discovery ratio` when referring to exploration |
| `exploration_injection_rate` for monitoring | `exploration rate` without context |
| `semantic_adjacency` for graph neighborhood | graph flow, semantic flow |
| `overall_flow_score` for flow quality scalar | flow score, smoothness score |
| `semantic_similarity` for normalized embedding alignment | quality, relevance |
| `playlist_overlap` for set overlap | stability, determinism |
| `same_order_ratio` for sequence stability | overlap, consistency |
| `artist_repeat_pressure` for consecutive repeat pressure | diversity collapse |
| `community_repeat_pressure` for cluster/community repeats | graph collapse |
| `recommendation_failure` only for operational failures | poor recommendation, bad playlist |

## Interpretation Boundaries

### Monitoring vs Diagnostics

Monitoring says what crossed an operational threshold. Diagnostics explains
which cross-system signals may be related. Diagnostics must not invent a new
meaning for monitoring metrics.

### Evaluation vs Feedback

Evaluation describes objective playlist shape. Feedback describes user
perception. A playlist can be objectively smooth and still disliked; it can be
objectively diverse and still feel incoherent.

### Ranking vs Sequencing

Ranking selects and scores tracks. Sequencing orders already-selected tracks.
Semantic contracts must not explain ordering behavior as ranking quality or
selection behavior as flow.

### Graph Adjacency vs Semantic Similarity

Semantic similarity is embedding alignment. Semantic adjacency is a graph edge
or neighborhood relation that may include artist, genre, and region signals.
They may correlate but are not equivalent.

### Exploration vs Novelty

Exploration is a controlled injection mechanism. Novelty is a popularity-based
evaluation proxy. A track can be exploratory but not novel, or novel without
being injected by the exploration engine.

## Semantic Drift Prevention Strategy

1. New reports must use canonical metric names from this document.
2. If a subsystem needs a new derived label, it must cite the canonical source
   metric it derives from.
3. Do not introduce synonyms in logs, diagnostics, health reports, or docs when
   a canonical term already exists.
4. Keep anomaly labels in monitoring and root-cause issue labels in
   diagnostics. Do not mix the two namespaces.
5. Use suffixes to clarify scope:
   - `_ratio` for static playlist proportions.
   - `_rate` for rolling operational rates.
   - `_score` for scalar quality or fit values.
   - `_count` for integer event or item counts.
   - `_pressure` for sequence-local repetition pressure.
   - `_delta` for calibration comparison values.
6. Every metric should state whether it is sequence-sensitive before being used
   in calibration or diagnostics.
7. Avoid single-word "quality", "fit", "health", "coherence", and "stability"
   in code or reports. Use the full canonical metric name.
8. Keep public response fields distinct from debug, monitoring, and diagnostic
   fields.

## Contract Change Rules

This document may be updated when existing behavior is clarified, but contract
changes should follow these rules:

- Do not change recommendation behavior as part of semantic contract updates.
- Do not add a metric just to resolve naming discomfort.
- Prefer deleting or mapping ambiguous terms over creating flexible aliases.
- If a term changes ownership, update its consumers and docs in the same
  change.
- When a metric has both objective and perceptual forms, keep them as separate
  names and correlate only in diagnostics.
