"""
scoring_config.py  —  Unified scoring configuration for SonicDNA backend.

All numeric weights, thresholds, penalties, profile curves, and evaluation
tolerances that govern recommendation quality live here.

STRUCTURE
---------
RANKING          Genome / primary-score blend weights + similarity weights
SIMILARITY       Transition-space feature weights (shared by flow & evaluation)
EXPLORATION      Ratio caps, min-relatedness, graph thresholds
GRAPH            Track-graph edge weights and flow-reranking bonus
FLOW             Per-position sequencer scoring weights
EVALUATION       Anti-pattern thresholds, quality grade cutoffs
SESSION_PROFILES Per-context audio-curve targets used by the flow engine
SESSION_TARGETS  Per-context targets + spike/variance tolerances for evaluation

USAGE
-----
    from config.scoring_config import RANKING, FLOW, SESSION_PROFILES

INTEGRATION RULES
-----------------
* Import these constants; never duplicate them.
* Adding a new session profile: extend SESSION_PROFILES and SESSION_TARGETS
  simultaneously — the evaluation engine mirrors the flow engine.
* All weights in a single blend (e.g. FLOW.GREEDY_WEIGHTS) must sum to 1.0
  where documented — adjust in one place only.

DO NOT rewrite engine logic. DO NOT change recommendation architecture.
"""

from __future__ import annotations

from typing import Dict, List


# ===========================================================================
# 1. RANKING  —  primary genome/embedding scoring blend
# ===========================================================================

class RANKING:
    """
    Weights for _score_tracks_by_genome() in playlist_generator.py.

    genome_weight + popularity_weight + mood_weight + region_weight
    + quality_weight must sum to 1.0.
    """

    # Primary blend (playlist_generator._score_tracks_by_genome)
    GENOME_WEIGHT:      float = 0.38
    POPULARITY_WEIGHT:  float = 0.25
    MOOD_WEIGHT:        float = 0.17
    REGION_WEIGHT:      float = 0.12
    QUALITY_WEIGHT:     float = 0.08

    # Post-embedding re-blend  (playlist_generator._apply_user_embedding_similarity)
    # final_score = pre_embedding_score * PRE_EMBED_RETAIN + semantic_score * EMBED_WEIGHT
    PRE_EMBED_RETAIN:   float = 0.78
    EMBED_WEIGHT:       float = 0.22

    # Mood scoring base and per-hit increment  (_lexical_mood_score)
    MOOD_BASE:          float = 0.35
    MOOD_HIT_INCREMENT: float = 0.22

    # Novelty scoring proxy  (_novelty_score)
    NOVELTY_ARTIST_UNFAMILIARITY_FLOOR:   float = 0.35
    NOVELTY_ARTIST_UNFAMILIARITY_RANGE:   float = 0.45   # * artist_unfamiliarity
    NOVELTY_REGION_CONFIDENCE_RANGE:      float = 0.20   # * region_confidence
    NOVELTY_PREFERRED_ARTIST_PARTIAL:     float = 0.15   # score when artist in library but preferred

    # Popularity dampening cap  (1 - min(cap, popularity * cap))
    POPULARITY_DAMPENING_CAP:             float = 0.65

    # Novelty relabeling threshold — discovery tracks below this are relabeled "library"
    NOVELTY_LIBRARY_THRESHOLD:            float = 0.42

    # Playlist characteristic tag thresholds  (_analyze_playlist)
    TAG_DANCEABLE_FLOOR:     float = 0.66
    TAG_HIGH_ENERGY_FLOOR:   float = 0.66
    TAG_POSITIVE_FLOOR:      float = 0.66
    TAG_MELANCHOLIC_CEILING: float = 0.36
    TAG_ACOUSTIC_FLOOR:      float = 0.58

    # Mood filter thresholds  (_filter_by_mood)
    MOOD_HAPPY_VALENCE_FLOOR:      float = 0.58
    MOOD_SAD_VALENCE_CEILING:      float = 0.46
    MOOD_ENERGETIC_ENERGY_FLOOR:   float = 0.58
    MOOD_FOCUSED_INSTRUMENT_FLOOR: float = 0.25
    MOOD_FOCUSED_ENERGY_CEILING:   float = 0.62
    MOOD_FILTER_LEXICAL_FLOOR:     float = 0.35   # lexical score that overrides feature gate

    # Calm mood compliance gates  (_is_mood_compliant)
    CALM_ENERGY_CEILING:  float = 0.55
    CALM_VALENCE_FLOOR:   float = 0.25
    CALM_VALENCE_CEILING: float = 0.72
    CALM_TEMPO_CEILING:   float = 132.0

    # Default fallback values used when seeding curated tracks
    SEED_REGION_CONFIDENCE: float = 0.95
    SEED_QUALITY_SCORE:     float = 0.85
    SEED_NOVELTY_DISCOVERY: float = 0.85
    SEED_NOVELTY_LIBRARY:   float = 0.00

    # Calm cap values applied to curated seed tracks
    CALM_SEED_DANCE_CAP:   float = 0.52
    CALM_SEED_ENERGY_CAP:  float = 0.48
    CALM_SEED_VALENCE_FLOOR: float = 0.35
    CALM_SEED_VALENCE_CAP:   float = 0.68
    CALM_SEED_TEMPO_CAP:     float = 126.0

    # Default region confidence when no region key is present
    DEFAULT_REGION_CONFIDENCE_WITH_REGION:    float = 0.65
    DEFAULT_REGION_CONFIDENCE_WITHOUT_REGION: float = 0.50


# ===========================================================================
# 2. SIMILARITY  —  weighted L1 in audio-feature space
#    Shared by playlist_flow_engine._transition_distance and
#    flow_evaluation._transition_dist
# ===========================================================================

class SIMILARITY:
    """
    Feature blend weights for transition-distance computation.

    ENERGY_WEIGHT + VALENCE_WEIGHT + DANCE_WEIGHT + TEMPO_WEIGHT = 1.0
    """

    ENERGY_WEIGHT:    float = 0.38
    VALENCE_WEIGHT:   float = 0.28
    DANCE_WEIGHT:     float = 0.20
    TEMPO_WEIGHT:     float = 0.14

    # Tempo normalisation range: raw BPM → [0, 1]
    TEMPO_MIN_BPM:    float = 60.0
    TEMPO_RANGE_BPM:  float = 140.0   # (raw - MIN) / RANGE → [0, 1]

    # Default values when a feature is missing from a track
    DEFAULT_ENERGY:         float = 0.5
    DEFAULT_VALENCE:        float = 0.5
    DEFAULT_DANCEABILITY:   float = 0.5
    DEFAULT_ACOUSTICNESS:   float = 0.3
    DEFAULT_TEMPO:          float = 120.0

    # Zone alignment: weighted error in (energy, valence) space
    ZONE_ENERGY_WEIGHT:  float = 0.55
    ZONE_VALENCE_WEIGHT: float = 0.45
    ZONE_SCALE_FACTOR:   float = 2.0    # reward = max(0, 1 - dist * SCALE_FACTOR)

    # Smooth transition reward: distance ceiling below which reward is given
    SMOOTH_DIST_CEILING: float = 0.45

    # Abrupt transition penalty: lower distance floor
    ABRUPT_DIST_FLOOR:   float = 0.35
    ABRUPT_DIST_RANGE:   float = 0.65   # (dist - FLOOR) / RANGE = raw penalty


# ===========================================================================
# 3. EXPLORATION  —  controlled discovery injection
# ===========================================================================

class EXPLORATION:
    """
    Parameters for ExplorationEngine in exploration_engine.py.
    """

    # Default and maximum exploration ratios
    DEFAULT_RATIO:         float = 0.15
    MAX_RATIO:             float = 0.20

    # Hard cap on the total number of exploration tracks in any playlist
    MAX_TRACKS:            int   = 8

    # Minimum semantic relatedness for a candidate to qualify
    MIN_RELATEDNESS:       float = 0.52

    # Edge-weight floor for "strong" local edges in density computation
    LOCAL_EDGE_THRESHOLD:  float = 0.68

    # Fallback semantic score when user embedding is absent
    FALLBACK_SEMANTIC:     float = 0.58

    # Exploration-score weights (ExplorationEngine.score_candidates)
    # semantic * W_SEMANTIC + graph_reward * W_GRAPH + bridge * W_BRIDGE
    # + artist_diversity * W_ARTIST + peripheral_coherence * W_PERIPHERAL
    # + rank_signal * W_RANK
    # - repeated_artist * W_REPEAT_ARTIST - local_density * W_LOCAL_DENSITY
    # - community_penalty * W_COMMUNITY
    W_SEMANTIC:         float = 0.28
    W_GRAPH:            float = 0.20
    W_BRIDGE:           float = 0.18
    W_ARTIST:           float = 0.14
    W_PERIPHERAL:       float = 0.10
    W_RANK:             float = 0.10
    W_REPEAT_ARTIST:    float = 0.16   # penalty
    W_LOCAL_DENSITY:    float = 0.12   # penalty
    W_COMMUNITY:        float = 0.10   # penalty

    # Artist diversity signals
    ARTIST_DIVERSITY_NEW:       float = 1.0    # artist not yet in selected
    ARTIST_DIVERSITY_ONCE:      float = 0.25   # artist appears once
    ARTIST_DIVERSITY_REPEAT:    float = 0.0    # artist appears 2+ times

    # Bridge score signals
    BRIDGE_CROSS_COMMUNITY_CONNECTED: float = 1.0
    BRIDGE_CROSS_COMMUNITY_ONLY:      float = 0.65
    BRIDGE_SAME_COMMUNITY_CONNECTED:  float = 0.35
    BRIDGE_NONE:                      float = 0.0
    BRIDGE_CONNECTED_WEIGHT_FLOOR:    float = 0.35   # edge weight to count as "connected"

    # Graph distance rewards (hops from candidate to any selected track)
    GRAPH_REWARD_DIST_1:    float = 0.25
    GRAPH_REWARD_DIST_2:    float = 1.00
    GRAPH_REWARD_DIST_3:    float = 0.75
    GRAPH_REWARD_DIST_NONE: float = 0.45   # disconnected fallback

    # Max BFS depth for graph distance computation
    GRAPH_MAX_DEPTH:        int   = 3

    # Artist repeat gate in inject_exploration_tracks
    ARTIST_REPEAT_GATE:     int   = 1    # skip candidate if artist already appears ≥ this many times


# ===========================================================================
# 4. GRAPH  —  TrackGraph edge weights and flow-reranking
# ===========================================================================

class GRAPH:
    """
    Constants for track_graph.py.
    """

    # Edge quality floor — neighbor pairs below this weight are not stored
    EDGE_THRESHOLD: float = 0.20

    # Default top-K neighbors stored per node
    DEFAULT_K:      int   = 10

    # Signal blend weights for edge_weight() — must sum to 1.0
    W_EMBED:   float = 0.55
    W_ARTIST:  float = 0.20
    W_GENRE:   float = 0.15
    W_REGION:  float = 0.10

    # Artist affinity partial-match score (first-word match)
    ARTIST_PARTIAL_MATCH: float = 0.5
    ARTIST_EXACT_MATCH:   float = 1.0

    # Flow-reranking bonus ceiling (rerank_for_flow)
    FLOW_ALPHA: float = 0.08


# ===========================================================================
# 5. FLOW  —  PlaylistFlowEngine greedy sequencer scoring
# ===========================================================================

class FLOW:
    """
    Greedy sequencer scoring blend in playlist_flow_engine._greedy_sequence.
    """

    # Weights applied to each signal in the greedy scoring formula
    # zone_reward * W_ZONE + smooth * W_SMOOTH + explore * W_EXPLORE
    # - abrupt_pen * W_ABRUPT - spike_pen * W_SPIKE
    # - cluster_pen * W_CLUSTER - artist_pen * W_ARTIST_PEN
    # + TIE_CONSTANT
    W_ZONE:       float = 0.30
    W_SMOOTH:     float = 0.25
    W_EXPLORE:    float = 0.10
    W_ABRUPT:     float = 0.20
    W_SPIKE:      float = 0.08
    W_CLUSTER:    float = 0.08
    W_ARTIST_PEN: float = 0.08
    TIE_CONSTANT: float = 0.05   # small bias to break ties deterministically

    # Artist repeat penalty (per occurrence in recent window)
    ARTIST_PEN_PER_OCCURRENCE: float = 0.12
    ARTIST_PEN_CAP:            float = 0.25
    ARTIST_WINDOW:             int   = 5    # how many recent tracks to scan

    # Cluster repeat penalty (per occurrence in pacing window)
    CLUSTER_PEN_PER_OCCURRENCE: float = 0.15
    CLUSTER_PEN_CAP:            float = 0.35

    # Repeated energy-spike penalty cap
    SPIKE_PEN_CAP:         float = 0.30
    SPIKE_PEN_SCALE:       float = 0.12    # weight * (run - 1) * SCALE
    SPIKE_ENERGY_FLOOR:    float = 0.72    # energy ≥ this = "high energy" track
    SPIKE_MIN_RUN:         int   = 2       # must see ≥ this many high-energy tracks before penalising

    # Exploration placement rewards / penalties (module-level constants)
    EXPLORE_ABRUPT_REWARD:      float = 0.10
    EXPLORE_ZONE_MATCH_REWARD:  float = 0.12   # track in preferred zone
    EXPLORE_ZONE_MISMATCH_PEN:  float = -0.06  # track in wrong zone ("middle" or "tail")
    EXPLORE_TAIL_MISMATCH_PEN:  float = -0.04
    EXPLORE_DISTRIBUTED_REWARD: float = 0.06

    # Zone boundaries as fractions of total length
    INTRO_FRACTION:  float = 1.0 / 5.0    # first ~20 %
    OUTRO_FRACTION:  float = 1.0 / 6.0    # last  ~17 %

    # Smoothness threshold: transition distances below this earn smooth reward
    SMOOTH_REWARD_CEILING: float = 0.45

    # Abrupt penalty: distance above this triggers spike weight
    ABRUPT_PENALTY_FLOOR: float = 0.35

    # Diagnostic thresholds for log output (non-scoring)
    LOG_ABRUPT_THRESHOLD: float = 0.10
    LOG_SMOOTH_THRESHOLD: float = 0.08


# ===========================================================================
# 6. EVALUATION  —  FlowEvaluator thresholds and quality grading
# ===========================================================================

class EVALUATION:
    """
    Observation-only thresholds for flow_evaluation.py.
    """

    # Transition distance above which a step is "abrupt"
    ABRUPT_THRESHOLD:       float = 0.40

    # Energy level considered "high" for spike detection
    SPIKE_ENERGY_FLOOR:     float = 0.72

    # Standard deviation below which arc is "flat"
    FLAT_VARIANCE_CEILING:  float = 0.04

    # Consecutive reversals window for oscillation detection
    OSCILLATION_WINDOW:     int   = 4

    # Consecutive same-cluster tracks that trigger a "collapse" anti-pattern
    CLUSTER_RUN_THRESHOLD:  int   = 3

    # Valence level below which a track is "low valence"
    LOW_VALENCE_CEILING:    float = 0.32

    # Fraction of playlist with low valence that triggers valence_collapse
    VALENCE_COLLAPSE_RATIO: float = 0.40

    # Minimum playlist size thresholds before patterns are checked
    MIN_TRACKS_FOR_OSCILLATION:  int = 6
    MIN_TRACKS_FOR_FLAT_ARC:     int = 5
    MIN_TRACKS_FOR_COLLAPSE:     int = 4

    # Exploration clustering score below which "exploration_clustering" fires
    EXPLORE_CLUSTER_SCORE_FLOOR: float = 0.40

    # Ending resolution: score below which "unresolved_ending" fires
    ENDING_RESOLUTION_FLOOR:     float = 0.50

    # Overall quality composite weights
    # smoothness * W_SMOOTH + arc_score * W_ARC + explore_zone * W_EZ
    # + cluster_sc * W_EC + repeat_sc * W_REPEAT + anchor_sc * W_ANCHOR
    # + session_sc * W_SESSION
    W_SMOOTH:  float = 0.22
    W_ARC:     float = 0.18
    W_EZ:      float = 0.08    # exploration zone
    W_EC:      float = 0.06    # exploration clustering
    W_REPEAT:  float = 0.16
    W_ANCHOR:  float = 0.14
    W_SESSION: float = 0.16

    # Smoothness formula: max(0, 1 - avg_transition * SMOOTHNESS_SCALE)
    SMOOTHNESS_SCALE: float = 1.5

    # Adherence formula: max(0, 1 - mean(zone_errors) * ADHERENCE_SCALE)
    ADHERENCE_SCALE:  float = 2.0

    # Start anchor formula: max(0, 1 - start_dist / ABRUPT_THRESHOLD)
    # (uses ABRUPT_THRESHOLD above)

    # Ending resolution: body_energy overshoot penalised at this scale
    RESOLUTION_OVERSHOOT_SCALE: float = 2.0

    # Zone error weighting matches SIMILARITY.ZONE_*
    ZONE_ENERGY_WEIGHT:  float = 0.55
    ZONE_VALENCE_WEIGHT: float = 0.45

    # Grade cutoffs  (overall_flow_score)
    GRADE_EXCELLENT: float = 0.82
    GRADE_GOOD:      float = 0.65
    GRADE_FAIR:      float = 0.48
    # below GRADE_FAIR → "poor"

    # Exploration zone score for non-intro placement
    EXPLORE_INTRO_ZONE_SCORE:     float = 0.3
    EXPLORE_NON_INTRO_ZONE_SCORE: float = 1.0

    # Band thresholds for explanation_engine._band()
    BAND_HIGH_FLOOR: float = 0.68
    BAND_LOW_CEIL:   float = 0.42

    # Mood continuity deltas for explanation_engine._mood_continuity()
    MOOD_SMOOTH_DELTA:   float = 0.22
    MOOD_CONTRAST_DELTA: float = 0.70


# ===========================================================================
# 7. SESSION_PROFILES  —  per-context audio curves for PlaylistFlowEngine
# ===========================================================================
# Each profile drives the greedy sequencer in playlist_flow_engine.py.
#
# Keys
# ----
# description       : human-readable label
# energy_curve      : [intro_target, body_target, outro_target]
# valence_curve     : same structure
# allow_abrupt_at   : positions (0-indexed) where contrast is acceptable
# exploration_zone  : "middle" | "tail" | "distributed"
# cluster_penalty   : per-profile weight override for cluster-run penalty
# energy_spike_penalty : per-profile weight for abrupt energy spike
# smooth_reward     : per-profile weight for smooth transition reward
# pacing_window     : how many recent tracks to consider for pacing logic

SESSION_PROFILES: Dict[str, Dict] = {
    "default": {
        "description":          "Balanced, gentle arc from moderate to peak then taper",
        "energy_curve":         [0.50, 0.70, 0.55],
        "valence_curve":        [0.55, 0.65, 0.55],
        "allow_abrupt_at":      [],
        "exploration_zone":     "middle",
        "cluster_penalty":      0.18,
        "energy_spike_penalty": 0.22,
        "smooth_reward":        0.12,
        "pacing_window":        4,
    },
    "workout": {
        "description":          "Fast ramp-up, sustained high energy, minimal descent",
        "energy_curve":         [0.72, 0.90, 0.82],
        "valence_curve":        [0.65, 0.75, 0.70],
        "allow_abrupt_at":      [2],               # big drop allowed at track 3
        "exploration_zone":     "tail",
        "cluster_penalty":      0.08,              # cluster variety less important
        "energy_spike_penalty": 0.05,              # spikes are fine for workout
        "smooth_reward":        0.04,
        "pacing_window":        3,
    },
    "focus": {
        "description":          "Flat, calm, low-variance energy; minimal mood disruptions",
        "energy_curve":         [0.38, 0.42, 0.36],
        "valence_curve":        [0.50, 0.52, 0.48],
        "allow_abrupt_at":      [],
        "exploration_zone":     "tail",
        "cluster_penalty":      0.20,
        "energy_spike_penalty": 0.30,              # spikes badly disrupt focus
        "smooth_reward":        0.16,
        "pacing_window":        5,
    },
    "night_drive": {
        "description":          "Moody arc: starts low, builds to atmospheric peak, fades",
        "energy_curve":         [0.45, 0.65, 0.52],
        "valence_curve":        [0.40, 0.50, 0.38],
        "allow_abrupt_at":      [],
        "exploration_zone":     "middle",
        "cluster_penalty":      0.15,
        "energy_spike_penalty": 0.20,
        "smooth_reward":        0.14,
        "pacing_window":        4,
    },
    "emotional": {
        "description":          "Gradual emotional descent then cathartic resolution",
        "energy_curve":         [0.45, 0.35, 0.50],
        "valence_curve":        [0.55, 0.30, 0.55],
        "allow_abrupt_at":      [],
        "exploration_zone":     "middle",
        "cluster_penalty":      0.10,
        "energy_spike_penalty": 0.18,
        "smooth_reward":        0.18,              # extra reward for emotional continuity
        "pacing_window":        4,
    },
    "discovery": {
        "description":          "Variety-first; strategic exploration placement, energetic open",
        "energy_curve":         [0.60, 0.62, 0.55],
        "valence_curve":        [0.60, 0.58, 0.52],
        "allow_abrupt_at":      [3, 6, 9],         # exploration contrast moments
        "exploration_zone":     "distributed",
        "cluster_penalty":      0.25,              # punish same-cluster clustering hard
        "energy_spike_penalty": 0.12,
        "smooth_reward":        0.08,
        "pacing_window":        3,
    },
}

# ---------------------------------------------------------------------------
# Derived helpers — used internally by playlist_flow_engine.py
# ---------------------------------------------------------------------------

_DEFAULT_PROFILE:     str       = "default"
_VALID_SESSION_TYPES: frozenset = frozenset(SESSION_PROFILES.keys())


# ===========================================================================
# 8. SESSION_TARGETS  —  evaluation mirrors of SESSION_PROFILES
#    Used by flow_evaluation.py (_session_adherence, _detect_anti_patterns)
# ===========================================================================
# Each entry mirrors the matching SESSION_PROFILE energy/valence curves and
# adds spike_tolerance and variance_tolerance for the evaluator.

SESSION_TARGETS: Dict[str, Dict] = {
    "default": {
        "energy":             [0.50, 0.70, 0.55],
        "valence":            [0.55, 0.65, 0.55],
        "spike_tolerance":    0.22,
        "variance_tolerance": 0.18,
        "desc":               "Balanced arc",
    },
    "workout": {
        "energy":             [0.72, 0.90, 0.82],
        "valence":            [0.65, 0.75, 0.70],
        "spike_tolerance":    0.90,
        "variance_tolerance": 0.30,
        "desc":               "Sustained high energy",
    },
    "focus": {
        "energy":             [0.38, 0.42, 0.36],
        "valence":            [0.50, 0.52, 0.48],
        "spike_tolerance":    0.08,
        "variance_tolerance": 0.08,
        "desc":               "Flat, low-variance",
    },
    "night_drive": {
        "energy":             [0.45, 0.65, 0.52],
        "valence":            [0.40, 0.50, 0.38],
        "spike_tolerance":    0.20,
        "variance_tolerance": 0.16,
        "desc":               "Moody atmospheric arc",
    },
    "emotional": {
        "energy":             [0.45, 0.35, 0.50],
        "valence":            [0.55, 0.30, 0.55],
        "spike_tolerance":    0.18,
        "variance_tolerance": 0.25,
        "desc":               "Controlled emotional descent",
    },
    "discovery": {
        "energy":             [0.60, 0.62, 0.55],
        "valence":            [0.60, 0.58, 0.52],
        "spike_tolerance":    0.30,
        "variance_tolerance": 0.20,
        "desc":               "Variety-first",
    },
}

_DEFAULT_SESSION: str = "default"
