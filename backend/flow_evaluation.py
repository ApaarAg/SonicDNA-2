"""
flow_evaluation.py  —  Observation-only playlist flow quality evaluator.

Measures quality of an already-ordered playlist.
NEVER reorders, reranks, or mutates track objects.
NO side-effects on recommendation logic.

Public surface
--------------
evaluate_flow(tracks, session_type, **kwargs)  -> dict
    Module-level entry point. Returns full structured report.

FlowEvaluator
    Class driving all metric computation.

ANTI_PATTERNS
    Dict of detected pathological playlist shapes.

Integration guard
-----------------
Enabled when:
  DEBUG_FLOW=true | 1 | yes     (env var)
  OR
  SONICDNA_ENV / APP_ENV / ENV  in {development, dev, local, debug}

is_flow_debug_enabled()  -> bool   (call before evaluate_flow in hot paths)
"""

from __future__ import annotations

import math
import os
import statistics
from collections import Counter
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Session profile targets  (now loaded from central config when available)
# ---------------------------------------------------------------------------
try:
    from config.scoring_config import (
        SESSION_TARGETS as _CFG_TARGETS,
        EVALUATION,
        SIMILARITY,
    )
    _CONFIG_AVAILABLE = True
except ImportError:
    _CONFIG_AVAILABLE = False

if _CONFIG_AVAILABLE:
    _SESSION_TARGETS = _CFG_TARGETS
else:
    # Inline fallback — identical values, preserved for standalone operation
    _SESSION_TARGETS: Dict[str, Dict] = {
        "default":    {"energy": [0.50, 0.70, 0.55], "valence": [0.55, 0.65, 0.55],
                       "spike_tolerance": 0.22, "variance_tolerance": 0.18, "desc": "Balanced arc"},
        "workout":    {"energy": [0.72, 0.90, 0.82], "valence": [0.65, 0.75, 0.70],
                       "spike_tolerance": 0.90, "variance_tolerance": 0.30, "desc": "Sustained high energy"},
        "focus":      {"energy": [0.38, 0.42, 0.36], "valence": [0.50, 0.52, 0.48],
                       "spike_tolerance": 0.08, "variance_tolerance": 0.08, "desc": "Flat, low-variance"},
        "night_drive":{"energy": [0.45, 0.65, 0.52], "valence": [0.40, 0.50, 0.38],
                       "spike_tolerance": 0.20, "variance_tolerance": 0.16, "desc": "Moody atmospheric arc"},
        "emotional":  {"energy": [0.45, 0.35, 0.50], "valence": [0.55, 0.30, 0.55],
                       "spike_tolerance": 0.18, "variance_tolerance": 0.25, "desc": "Controlled emotional descent"},
        "discovery":  {"energy": [0.60, 0.62, 0.55], "valence": [0.60, 0.58, 0.52],
                       "spike_tolerance": 0.30, "variance_tolerance": 0.20, "desc": "Variety-first"},
    }
_DEFAULT_SESSION = "default"

# Thresholds — sourced from EVALUATION config when available
_ABRUPT_THRESHOLD      = EVALUATION.ABRUPT_THRESHOLD      if _CONFIG_AVAILABLE else 0.40
_SPIKE_ENERGY_FLOOR    = EVALUATION.SPIKE_ENERGY_FLOOR    if _CONFIG_AVAILABLE else 0.72
_FLAT_VARIANCE_CEILING = EVALUATION.FLAT_VARIANCE_CEILING if _CONFIG_AVAILABLE else 0.04
_OSCILLATION_WINDOW    = EVALUATION.OSCILLATION_WINDOW    if _CONFIG_AVAILABLE else 4
_CLUSTER_RUN_THRESHOLD = EVALUATION.CLUSTER_RUN_THRESHOLD if _CONFIG_AVAILABLE else 3


# ---------------------------------------------------------------------------
# Environment guard
# ---------------------------------------------------------------------------

def is_flow_debug_enabled() -> bool:
    """Return True when flow evaluation logging is active."""
    flag = os.getenv("DEBUG_FLOW", "").lower()
    if flag in {"1", "true", "yes"}:
        return True
    env = (
        os.getenv("SONICDNA_ENV") or os.getenv("APP_ENV") or os.getenv("ENV") or ""
    ).lower()
    return env in {"development", "dev", "local", "debug"}


# ---------------------------------------------------------------------------
# Feature accessors (read-only, never mutate)
# ---------------------------------------------------------------------------

def _f(track: dict, key: str, default: float = 0.5) -> float:
    try:
        v = float(track.get(key, default))
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def _energy(t: dict) -> float:   return _f(t, "energy", 0.5)
def _valence(t: dict) -> float:  return _f(t, "valence", 0.5)
def _dance(t: dict) -> float:    return _f(t, "danceability", 0.5)
def _tempo_norm(t: dict) -> float:
    raw = _f(t, "tempo", 120.0)
    return max(0.0, min(1.0, (raw - 60.0) / 140.0))


def _artist(t: dict) -> str:
    return str(t.get("artist", "")).split(",")[0].strip().lower()


def _cluster(t: dict) -> str:
    explicit = t.get("community") or t.get("community_id") or ""
    return str(explicit).strip().lower() if explicit else _artist(t)


def _is_explore(t: dict) -> bool:
    return bool(t.get("exploration"))


def _transition_dist(a: dict, b: dict) -> float:
    """Weighted L1 distance in (energy, valence, dance, tempo) space."""
    _we = SIMILARITY.ENERGY_WEIGHT  if _CONFIG_AVAILABLE else 0.38
    _wv = SIMILARITY.VALENCE_WEIGHT if _CONFIG_AVAILABLE else 0.28
    _wd = SIMILARITY.DANCE_WEIGHT   if _CONFIG_AVAILABLE else 0.20
    _wt = SIMILARITY.TEMPO_WEIGHT   if _CONFIG_AVAILABLE else 0.14
    raw = (
        _we * abs(_energy(a) - _energy(b))
        + _wv * abs(_valence(a) - _valence(b))
        + _wd * abs(_dance(a)  - _dance(b))
        + _wt * abs(_tempo_norm(a) - _tempo_norm(b))
    )
    return max(0.0, min(1.0, raw))


# ---------------------------------------------------------------------------
# Zone helpers
# ---------------------------------------------------------------------------

def _zone(pos: int, total: int) -> int:
    """0=intro, 1=body, 2=outro."""
    if total <= 2:
        return 1
    intro_end    = max(1, total // 5)
    outro_start  = total - max(1, total // 6)
    if pos < intro_end:   return 0
    if pos >= outro_start: return 2
    return 1


# ---------------------------------------------------------------------------
# Individual metrics
# ---------------------------------------------------------------------------

def _transition_metrics(tracks: List[dict]) -> dict:
    if len(tracks) < 2:
        return {"avg_transition_distance": 0.0, "max_transition_distance": 0.0,
                "abrupt_transition_count": 0, "abrupt_transition_positions": []}
    dists = [_transition_dist(tracks[i], tracks[i + 1]) for i in range(len(tracks) - 1)]
    abrupt_pos = [i + 2 for i, d in enumerate(dists) if d >= _ABRUPT_THRESHOLD]
    return {
        "avg_transition_distance": round(statistics.mean(dists), 3),
        "max_transition_distance": round(max(dists), 3),
        "abrupt_transition_count": len(abrupt_pos),
        "abrupt_transition_positions": abrupt_pos,
    }


def _arc_metrics(tracks: List[dict]) -> dict:
    if len(tracks) < 3:
        return {"arc_direction_changes": 0, "energy_curve_consistency": 1.0,
                "valence_curve_consistency": 1.0, "energy_variance": 0.0,
                "valence_variance": 0.0, "energy_slope": 0.0}

    energies = [_energy(t) for t in tracks]
    valences  = [_valence(t) for t in tracks]

    def _direction_changes(series: List[float]) -> int:
        changes = 0
        for i in range(1, len(series) - 1):
            prev_dir = series[i] - series[i - 1]
            next_dir = series[i + 1] - series[i]
            if (prev_dir > 0 and next_dir < 0) or (prev_dir < 0 and next_dir > 0):
                changes += 1
        return changes

    def _curve_consistency(series: List[float]) -> float:
        """1.0 = perfectly monotone, lower = more oscillation."""
        n = len(series)
        if n < 2:
            return 1.0
        changes = _direction_changes(series)
        return round(max(0.0, 1.0 - changes / max(1, n - 2)), 3)

    e_var = round(statistics.variance(energies), 4) if len(energies) > 1 else 0.0
    v_var = round(statistics.variance(valences),  4) if len(valences)  > 1 else 0.0
    n     = len(energies)
    slope = round((energies[-1] - energies[0]) / max(1, n - 1), 4)

    return {
        "arc_direction_changes":      _direction_changes(energies),
        "energy_curve_consistency":   _curve_consistency(energies),
        "valence_curve_consistency":  _curve_consistency(valences),
        "energy_variance":            e_var,
        "valence_variance":           v_var,
        "energy_slope":               slope,
        "energy_series":              [round(e, 3) for e in energies],
        "valence_series":             [round(v, 3) for v in valences],
    }


def _exploration_metrics(tracks: List[dict]) -> dict:
    total = len(tracks)
    explore_positions = [i for i, t in enumerate(tracks) if _is_explore(t)]
    count = len(explore_positions)
    if total == 0 or count == 0:
        return {"exploration_count": 0, "exploration_ratio": 0.0,
                "exploration_zone_score": 1.0, "exploration_positions": [],
                "exploration_clustering_score": 1.0}

    # Zone score: penalise intro placement, reward body/tail
    zone_scores = []
    for pos in explore_positions:
        z = _zone(pos, total)
        _non_intro = EVALUATION.EXPLORE_NON_INTRO_ZONE_SCORE if _CONFIG_AVAILABLE else 1.0
        _intro_sc  = EVALUATION.EXPLORE_INTRO_ZONE_SCORE     if _CONFIG_AVAILABLE else 0.3
        zone_scores.append(_non_intro if z in {1, 2} else _intro_sc)

    # Clustering score: are exploration tracks spread out?
    if count == 1:
        clustering_score = 1.0
    else:
        gaps = [explore_positions[i + 1] - explore_positions[i]
                for i in range(len(explore_positions) - 1)]
        ideal_gap = max(1, total // (count + 1))
        clustering_score = round(
            sum(min(1.0, g / ideal_gap) for g in gaps) / len(gaps), 3
        )

    return {
        "exploration_count":           count,
        "exploration_ratio":           round(count / total, 3),
        "exploration_zone_score":      round(statistics.mean(zone_scores), 3),
        "exploration_positions":       [p + 1 for p in explore_positions],
        "exploration_clustering_score": clustering_score,
    }


def _repetition_metrics(tracks: List[dict]) -> dict:
    if not tracks:
        return {"artist_repeat_pressure": 0.0, "community_repeat_pressure": 0.0,
                "max_artist_run": 0, "max_cluster_run": 0}

    # Artist consecutive run
    def _max_run(items: List[str]) -> int:
        if not items:
            return 0
        max_r = cur_r = 1
        for i in range(1, len(items)):
            if items[i] == items[i - 1]:
                cur_r += 1
                max_r = max(max_r, cur_r)
            else:
                cur_r = 1
        return max_r

    artists  = [_artist(t)  for t in tracks]
    clusters = [_cluster(t) for t in tracks]

    artist_counts  = Counter(artists)
    cluster_counts = Counter(clusters)

    # Pressure = fraction of window-2 pairs that repeat
    def _repeat_pressure(items: List[str]) -> float:
        if len(items) < 2:
            return 0.0
        repeats = sum(1 for i in range(len(items) - 1) if items[i] == items[i + 1])
        return round(repeats / (len(items) - 1), 3)

    return {
        "artist_repeat_pressure":    _repeat_pressure(artists),
        "community_repeat_pressure": _repeat_pressure(clusters),
        "max_artist_run":            _max_run(artists),
        "max_cluster_run":           _max_run(clusters),
        "top_repeated_artists":      [a for a, c in artist_counts.most_common(3) if c > 1],
        "top_repeated_clusters":     [c for c, n in cluster_counts.most_common(3) if n > 1],
    }


def _flow_entropy(tracks: List[dict]) -> float:
    """Shannon entropy over binned (energy, valence) cells → diversity of mood space."""
    if len(tracks) < 2:
        return 0.0
    bins: Counter = Counter()
    for t in tracks:
        e_bin = int(_energy(t) * 5)  # 0-5
        v_bin = int(_valence(t) * 5)
        bins[(e_bin, v_bin)] += 1
    total = len(tracks)
    entropy = -sum((c / total) * math.log2(c / total) for c in bins.values())
    max_entropy = math.log2(min(total, 36))  # 6×6 grid max
    return round(entropy / max_entropy, 3) if max_entropy > 0 else 0.0


def _start_end_metrics(tracks: List[dict]) -> dict:
    if len(tracks) < 2:
        return {"start_anchor_strength": 1.0, "ending_resolution_score": 1.0,
                "start_transition_dist": 0.0, "end_transition_dist": 0.0}

    start_dist = _transition_dist(tracks[0], tracks[1])
    end_dist   = _transition_dist(tracks[-2], tracks[-1])

    # Anchor: low energy variance in first 2 tracks is a smooth open
    start_anchor = round(max(0.0, 1.0 - start_dist / _ABRUPT_THRESHOLD), 3)

    # Resolution: ending energy should be ≤ body energy (no unresolved spike)
    body_energy  = statistics.mean(_energy(t) for t in tracks[1:-1]) if len(tracks) > 2 else 0.5
    end_energy   = _energy(tracks[-1])
    resolution   = round(max(0.0, 1.0 - max(0.0, end_energy - body_energy) * 2.0), 3)

    return {
        "start_anchor_strength":  start_anchor,
        "ending_resolution_score": resolution,
        "start_transition_dist":  round(start_dist, 3),
        "end_transition_dist":    round(end_dist, 3),
    }


def _session_adherence(tracks: List[dict], session_type: str) -> dict:
    """Measure how closely the playlist follows the session profile."""
    profile = _SESSION_TARGETS.get(session_type, _SESSION_TARGETS[_DEFAULT_SESSION])
    total   = len(tracks)
    if total == 0:
        return {"session_type": session_type, "adherence_score": 0.0,
                "zone_scores": [], "spike_violations": 0}

    zone_errors: List[float] = []
    spike_violations = 0
    tolerance = profile["spike_tolerance"]

    _ze = EVALUATION.ZONE_ENERGY_WEIGHT  if _CONFIG_AVAILABLE else 0.55
    _zv = EVALUATION.ZONE_VALENCE_WEIGHT if _CONFIG_AVAILABLE else 0.45
    _adh_scale = EVALUATION.ADHERENCE_SCALE if _CONFIG_AVAILABLE else 2.0

    for i, t in enumerate(tracks):
        z  = _zone(i, total)
        e_target = profile["energy"][z]
        v_target = profile["valence"][z]
        e_err = abs(_energy(t) - e_target)
        v_err = abs(_valence(t) - v_target)
        zone_errors.append(_ze * e_err + _zv * v_err)

        # Spike: energy exceeds target + tolerance
        if _energy(t) > e_target + tolerance:
            spike_violations += 1

    adherence = round(max(0.0, 1.0 - statistics.mean(zone_errors) * _adh_scale), 3)

    # Variance check
    energies  = [_energy(t) for t in tracks]
    e_stdev   = statistics.stdev(energies) if len(energies) > 1 else 0.0
    var_ok = e_stdev <= profile["variance_tolerance"]

    return {
        "session_type":       session_type,
        "profile_desc":       profile["desc"],
        "adherence_score":    adherence,
        "spike_violations":   spike_violations,
        "energy_variance_ok": var_ok,
        "energy_stdev":       round(e_stdev, 3),
        "variance_tolerance": profile["variance_tolerance"],
    }


def _overall_flow_quality(
    transition: dict,
    arc: dict,
    exploration: dict,
    repetition: dict,
    start_end: dict,
    session: dict,
) -> dict:
    """Single composite score [0, 1]."""
    # Component scores (all in [0, 1])
    _sm_scale = EVALUATION.SMOOTHNESS_SCALE if _CONFIG_AVAILABLE else 1.5
    smoothness   = max(0.0, 1.0 - transition["avg_transition_distance"] * _sm_scale)
    arc_score    = (arc["energy_curve_consistency"] + arc["valence_curve_consistency"]) / 2
    explore_sc   = exploration.get("exploration_zone_score", 1.0)
    cluster_sc   = exploration.get("exploration_clustering_score", 1.0)
    repeat_sc    = max(0.0, 1.0 - (repetition["artist_repeat_pressure"] +
                                    repetition["community_repeat_pressure"]) / 2)
    anchor_sc    = (start_end["start_anchor_strength"] + start_end["ending_resolution_score"]) / 2
    session_sc   = session["adherence_score"]

    if _CONFIG_AVAILABLE:
        overall = round(
            smoothness   * EVALUATION.W_SMOOTH
            + arc_score  * EVALUATION.W_ARC
            + explore_sc * EVALUATION.W_EZ
            + cluster_sc * EVALUATION.W_EC
            + repeat_sc  * EVALUATION.W_REPEAT
            + anchor_sc  * EVALUATION.W_ANCHOR
            + session_sc * EVALUATION.W_SESSION,
            3,
        )
    else:
        overall = round(
            smoothness  * 0.22
            + arc_score * 0.18
            + explore_sc * 0.08
            + cluster_sc * 0.06
            + repeat_sc  * 0.16
            + anchor_sc  * 0.14
            + session_sc * 0.16,
            3,
        )

    _exc = EVALUATION.GRADE_EXCELLENT if _CONFIG_AVAILABLE else 0.82
    _gd  = EVALUATION.GRADE_GOOD      if _CONFIG_AVAILABLE else 0.65
    _fr  = EVALUATION.GRADE_FAIR      if _CONFIG_AVAILABLE else 0.48
    grade = (
        "excellent" if overall >= _exc else
        "good"      if overall >= _gd  else
        "fair"      if overall >= _fr  else
        "poor"
    )

    return {
        "overall_flow_score": overall,
        "grade":              grade,
        "component_scores": {
            "transition_smoothness":    round(smoothness, 3),
            "arc_coherence":           round(arc_score,  3),
            "exploration_zone":        round(explore_sc, 3),
            "exploration_spread":      round(cluster_sc, 3),
            "repetition_control":      round(repeat_sc,  3),
            "start_end_quality":       round(anchor_sc,  3),
            "session_adherence":       round(session_sc, 3),
        },
    }


# ---------------------------------------------------------------------------
# Anti-pattern detection
# ---------------------------------------------------------------------------

ANTI_PATTERN_DESCRIPTIONS: Dict[str, str] = {
    "excessive_oscillation":   "Energy direction reverses too frequently (zigzag effect)",
    "flat_emotional_arc":      "Emotional variance is too low — playlist feels monotonous",
    "abrupt_start":            "First transition is too jarring — opener needs a smoother lead-in",
    "unresolved_ending":       "Ending energy is higher than the playlist body — no cool-down",
    "exploration_clustering":  "Exploration tracks are bunched together instead of spread out",
    "repetitive_artist_run":   "Same primary artist appears in 3+ consecutive tracks",
    "local_community_collapse":"Same community/cluster dominates 3+ consecutive tracks",
    "energy_spike_run":        "Three or more consecutive high-energy tracks in a non-workout context",
    "valence_collapse":        "Sustained low valence without recovery — emotionally draining",
    "exploration_in_intro":    "Exploration track placed in the first 20% of the playlist",
}


def _detect_anti_patterns(
    tracks: List[dict],
    arc: dict,
    transition: dict,
    exploration: dict,
    repetition: dict,
    start_end: dict,
    session_type: str,
) -> List[dict]:
    """Return list of detected anti-pattern dicts {name, description, severity}."""
    found: List[dict] = []
    n = len(tracks)

    def _add(name: str, severity: str, detail: str = "") -> None:
        found.append({
            "pattern":     name,
            "description": ANTI_PATTERN_DESCRIPTIONS.get(name, name),
            "severity":    severity,
            "detail":      detail,
        })

    # Excessive oscillation
    changes = arc.get("arc_direction_changes", 0)
    if n >= 6 and changes > max(2, n // 3):
        _add("excessive_oscillation", "medium",
             f"direction_changes={changes} for {n} tracks")

    # Flat emotional arc
    e_var = arc.get("energy_variance", 0.0)
    v_var = arc.get("valence_variance", 0.0)
    if n >= 5 and e_var < _FLAT_VARIANCE_CEILING and v_var < _FLAT_VARIANCE_CEILING:
        _add("flat_emotional_arc", "low",
             f"energy_var={e_var} valence_var={v_var}")

    # Abrupt start
    if start_end["start_transition_dist"] >= _ABRUPT_THRESHOLD:
        _add("abrupt_start", "medium",
             f"start_dist={start_end['start_transition_dist']}")

    # Unresolved ending
    if start_end["ending_resolution_score"] < 0.50:
        _add("unresolved_ending", "low",
             f"resolution={start_end['ending_resolution_score']}")

    # Exploration clustering
    if exploration["exploration_count"] >= 2 and \
            exploration.get("exploration_clustering_score", 1.0) < 0.40:
        _add("exploration_clustering", "medium",
             f"clustering_score={exploration['exploration_clustering_score']}")

    # Exploration in intro
    if exploration["exploration_count"] > 0:
        intro_end = max(1, n // 5)
        early = [p for p in exploration["exploration_positions"] if p <= intro_end]
        if early:
            _add("exploration_in_intro", "low",
                 f"positions={early}")

    # Repetitive artist run
    max_ar = repetition.get("max_artist_run", 0)
    if max_ar >= _CLUSTER_RUN_THRESHOLD:
        _add("repetitive_artist_run", "high",
             f"max_run={max_ar}")

    # Local community collapse
    max_cr = repetition.get("max_cluster_run", 0)
    if max_cr >= _CLUSTER_RUN_THRESHOLD:
        _add("local_community_collapse", "medium",
             f"max_run={max_cr}")

    # Energy spike run (non-workout context)
    if session_type not in {"workout"}:
        energies = [_energy(t) for t in tracks]
        max_spike_run = 0
        cur_run = 0
        for e in energies:
            if e >= _SPIKE_ENERGY_FLOOR:
                cur_run += 1
                max_spike_run = max(max_spike_run, cur_run)
            else:
                cur_run = 0
        if max_spike_run >= 3:
            _add("energy_spike_run", "medium" if session_type == "focus" else "low",
                 f"max_spike_run={max_spike_run}")

    # Valence collapse — sustained low valence > 40% of playlist
    if session_type not in {"emotional", "night_drive"}:
        low_val = sum(1 for t in tracks if _valence(t) < 0.32)
        if n >= 4 and low_val / n > 0.40:
            _add("valence_collapse", "low",
                 f"low_valence_fraction={round(low_val/n, 2)}")

    return found


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------

class FlowEvaluator:
    """
    Observation-only playlist flow quality evaluator.

    Usage
    -----
    report = FlowEvaluator().evaluate(tracks, session_type="focus")
    # or
    report = evaluate_flow(tracks, session_type="focus")
    """

    def evaluate(
        self,
        tracks: List[dict],
        session_type: Optional[str] = None,
    ) -> dict:
        """
        Evaluate a playlist and return a structured quality report.

        Parameters
        ----------
        tracks : list of track dicts
            Must already be in final display order.
            Must have audio features (energy, valence, danceability, tempo).
        session_type : str or None
            One of: default, workout, focus, night_drive, emotional, discovery.

        Returns
        -------
        Structured report dict — see module docstring for schema.
        Track objects are NEVER mutated.
        """
        stype = (session_type or _DEFAULT_SESSION).lower().strip()
        if stype not in _SESSION_TARGETS:
            stype = _DEFAULT_SESSION

        if not tracks:
            return self._empty_report(stype)

        # --- Read-only copies for all internal operations ---
        snap = [dict(t) for t in tracks]  # shallow copy to guarantee no mutation path

        transition   = _transition_metrics(snap)
        arc          = _arc_metrics(snap)
        exploration  = _exploration_metrics(snap)
        repetition   = _repetition_metrics(snap)
        start_end    = _start_end_metrics(snap)
        session      = _session_adherence(snap, stype)
        entropy      = _flow_entropy(snap)
        quality      = _overall_flow_quality(
            transition, arc, exploration, repetition, start_end, session
        )
        anti_patterns = _detect_anti_patterns(
            snap, arc, transition, exploration, repetition, start_end, stype
        )

        report = {
            "flow_quality": {
                **quality,
                "flow_entropy":  entropy,
                "track_count":   len(tracks),
                "session_type":  stype,
            },
            "transition_metrics":  transition,
            "arc_metrics":         arc,
            "exploration_metrics": exploration,
            "repetition_metrics":  repetition,
            "start_end_metrics":   start_end,
            "session_adherence":   session,
            "anti_patterns":       anti_patterns,
            "anti_pattern_count":  len(anti_patterns),
        }

        return report

    @staticmethod
    def _empty_report(stype: str) -> dict:
        return {
            "flow_quality": {
                "overall_flow_score": 0.0, "grade": "poor",
                "flow_entropy": 0.0, "track_count": 0, "session_type": stype,
                "component_scores": {},
            },
            "transition_metrics":  {},
            "arc_metrics":         {},
            "exploration_metrics": {},
            "repetition_metrics":  {},
            "start_end_metrics":   {},
            "session_adherence":   {"session_type": stype, "adherence_score": 0.0},
            "anti_patterns":       [],
            "anti_pattern_count":  0,
        }

    def log_summary(self, report: dict) -> None:
        """Print a concise single-line summary to stdout."""
        fq   = report.get("flow_quality", {})
        sess = report.get("session_adherence", {})
        ap   = report.get("anti_pattern_count", 0)
        print(
            f"[flow_eval] session={fq.get('session_type','?')} "
            f"score={fq.get('overall_flow_score','?')} "
            f"grade={fq.get('grade','?')} "
            f"entropy={fq.get('flow_entropy','?')} "
            f"adherence={sess.get('adherence_score','?')} "
            f"anti_patterns={ap}"
        )


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

def evaluate_flow(
    tracks: List[dict],
    session_type: Optional[str] = None,
) -> dict:
    """
    Evaluate playlist flow quality. Observation-only.

    Returns the full structured report. Tracks are never mutated.
    """
    return FlowEvaluator().evaluate(tracks, session_type=session_type)
