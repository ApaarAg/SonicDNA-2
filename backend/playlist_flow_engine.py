"""
playlist_flow_engine.py  —  Lightweight post-ranking playlist sequencer.

Operates AFTER final track selection and BEFORE response serialization.
It REORDERS an already-ranked track list; it does NOT change which tracks
are in the playlist, does NOT replace genome/embedding/graph ranking, and
does NOT modify discovery or exploration ratios.

Design philosophy
-----------------
* Pure soft-scoring via additive penalties and rewards.
* No ML, no RL, no graph neural networks.
* O(n²) worst-case, acceptable for playlist sizes ≤ 100.
* Fully optional — a single flag or a missing module disables it cleanly.
* Annotates each track with a ``flow_trace`` dict for transparent debugging.

Public surface
--------------
reorder_for_flow(tracks, session_type, **kwargs)  → List[dict]
    Module-level convenience function.  The main integration point.

PlaylistFlowEngine
    The class driving all sequencing logic.

SESSION_PROFILES
    Dict of per-session audio-feature target curves.
"""

from __future__ import annotations

import math
import sys
import os
from collections import Counter
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Central scoring configuration
# ---------------------------------------------------------------------------
try:
    from config.scoring_config import (
        SESSION_PROFILES as _CFG_SESSION_PROFILES,
        SIMILARITY,
        FLOW,
    )
    _CONFIG_AVAILABLE = True
except ImportError:
    _CONFIG_AVAILABLE = False

try:
    from config.session_intents import get_intent as _get_intent
    _INTENTS_AVAILABLE = True
except ImportError:
    _INTENTS_AVAILABLE = False

# ---------------------------------------------------------------------------
# Session profiles  —  loaded from central config when available
# ---------------------------------------------------------------------------

# Each profile maps to an "ideal" sequence shape.
# Values are (energy_target, valence_target) for three playlist zones:
#   [intro_zone, body_zone, outro_zone]
# Used to nudge pacing; never enforced as hard constraints.

if _CONFIG_AVAILABLE:
    # Authoritative source: config/scoring_config.py
    SESSION_PROFILES: Dict[str, Dict] = _CFG_SESSION_PROFILES
else:
    # Inline fallback — preserved verbatim so the engine works standalone
    SESSION_PROFILES = {
        "default": {
            "description": "Balanced, gentle arc from moderate to peak then taper",
            "energy_curve": [0.50, 0.70, 0.55],
            "valence_curve": [0.55, 0.65, 0.55],
            "allow_abrupt_at": [],
            "exploration_zone": "middle",
            "cluster_penalty": 0.18,
            "energy_spike_penalty": 0.22,
            "smooth_reward": 0.12,
            "pacing_window": 4,
        },
        "workout": {
            "description": "Fast ramp-up, sustained high energy, minimal descent",
            "energy_curve": [0.72, 0.90, 0.82],
            "valence_curve": [0.65, 0.75, 0.70],
            "allow_abrupt_at": [2],
            "exploration_zone": "tail",
            "cluster_penalty": 0.08,
            "energy_spike_penalty": 0.05,
            "smooth_reward": 0.04,
            "pacing_window": 3,
        },
        "focus": {
            "description": "Flat, calm, low-variance energy; minimal mood disruptions",
            "energy_curve": [0.38, 0.42, 0.36],
            "valence_curve": [0.50, 0.52, 0.48],
            "allow_abrupt_at": [],
            "exploration_zone": "tail",
            "cluster_penalty": 0.20,
            "energy_spike_penalty": 0.30,
            "smooth_reward": 0.16,
            "pacing_window": 5,
        },
        "night_drive": {
            "description": "Moody arc: starts low, builds to atmospheric peak, fades",
            "energy_curve": [0.45, 0.65, 0.52],
            "valence_curve": [0.40, 0.50, 0.38],
            "allow_abrupt_at": [],
            "exploration_zone": "middle",
            "cluster_penalty": 0.15,
            "energy_spike_penalty": 0.20,
            "smooth_reward": 0.14,
            "pacing_window": 4,
        },
        "emotional": {
            "description": "Gradual emotional descent then cathartic resolution",
            "energy_curve": [0.45, 0.35, 0.50],
            "valence_curve": [0.55, 0.30, 0.55],
            "allow_abrupt_at": [],
            "exploration_zone": "middle",
            "cluster_penalty": 0.10,
            "energy_spike_penalty": 0.18,
            "smooth_reward": 0.18,
            "pacing_window": 4,
        },
        "discovery": {
            "description": "Variety-first; strategic exploration placement, energetic open",
            "energy_curve": [0.60, 0.62, 0.55],
            "valence_curve": [0.60, 0.58, 0.52],
            "allow_abrupt_at": [3, 6, 9],
            "exploration_zone": "distributed",
            "cluster_penalty": 0.25,
            "energy_spike_penalty": 0.12,
            "smooth_reward": 0.08,
            "pacing_window": 3,
        },
    }

_DEFAULT_PROFILE = "default"
_VALID_SESSION_TYPES = set(SESSION_PROFILES.keys())

# ---------------------------------------------------------------------------
# Feature extraction helpers
# ---------------------------------------------------------------------------

def _safe_float(value, default: float = 0.5) -> float:
    """Coerce value to float, returning default on failure."""
    try:
        f = float(value)
        return f if math.isfinite(f) else default
    except (TypeError, ValueError):
        return default


def _energy(track: dict) -> float:
    return _safe_float(track.get("energy"), 0.5)


def _valence(track: dict) -> float:
    return _safe_float(track.get("valence"), 0.5)


def _danceability(track: dict) -> float:
    return _safe_float(track.get("danceability"), 0.5)


def _acousticness(track: dict) -> float:
    return _safe_float(track.get("acousticness"), 0.3)


def _tempo(track: dict) -> float:
    """Return tempo normalised to [0, 1] over a [60, 200] BPM span."""
    _tmin = SIMILARITY.TEMPO_MIN_BPM  if _CONFIG_AVAILABLE else 60.0
    _trng = SIMILARITY.TEMPO_RANGE_BPM if _CONFIG_AVAILABLE else 140.0
    raw = _safe_float(track.get("tempo"), _tmin + _trng * 0.5)
    return max(0.0, min(1.0, (raw - _tmin) / _trng))


def _instrumentalness(track: dict) -> float:
    return _safe_float(track.get("instrumentalness"), 0.0)


def _speechiness(track: dict) -> float:
    return _safe_float(track.get("speechiness"), 0.05)


def _liveness(track: dict) -> float:
    return _safe_float(track.get("liveness"), 0.18)


def _text_metadata(track: dict) -> str:
    values = [
        track.get("name", ""),
        track.get("artist", ""),
        track.get("search_query", ""),
        track.get("region", ""),
        track.get("region_key", ""),
    ]
    for key in ("genres", "artist_genres"):
        raw = track.get(key)
        if isinstance(raw, list):
            values.extend(str(item) for item in raw)
        elif raw:
            values.append(str(raw))
    return " ".join(values).lower()


def _has_text_marker(text: str, terms: List[str]) -> bool:
    padded = f" {text.lower()} "
    return any(term in padded for term in terms)


def _texture_vector(track: dict) -> Dict[str, float]:
    """
    Coarse sonic-world vector from existing metadata only.

    Values are trace/support signals, not new recommendation metrics. They let
    the sequencer distinguish mood-similar tracks that live in different
    production textures.
    """
    energy = _energy(track)
    dance = _danceability(track)
    acoustic = _acousticness(track)
    instrumental = _instrumentalness(track)
    speech = _speechiness(track)
    live = _liveness(track)
    tempo = _tempo(track)
    text = _text_metadata(track)

    electronic_context = _has_text_marker(
        text,
        ["ambient", "synth", "electronic", "edm", "techno", "house", "score", "soundtrack"],
    )
    organic_context = _has_text_marker(
        text,
        ["acoustic", "folk", "country", "singer-songwriter", "blues", "orchestral", "live"],
    )
    raw_context = _has_text_marker(text, ["live", "demo", "garage", "punk", "raw", "session"])

    synthetic = max(0.0, min(1.0, (1.0 - acoustic) * 0.65 + (0.25 if electronic_context else 0.0)))
    organic = max(0.0, min(1.0, acoustic * 0.72 + (0.22 if organic_context else 0.0)))
    atmosphere = max(
        0.0,
        min(
            1.0,
            instrumental * 0.38
            + (1.0 - acoustic) * 0.28
            + (0.24 if electronic_context else 0.0)
            + (1.0 - min(1.0, speech * 4.0)) * 0.10,
        ),
    )
    vocal_density = max(0.0, min(1.0, (1.0 - instrumental) * 0.72 + min(1.0, speech * 4.0) * 0.28))
    rhythmic_aggression = max(0.0, min(1.0, energy * 0.42 + dance * 0.34 + tempo * 0.24))
    ambient_weight = max(0.0, min(1.0, atmosphere * 0.72 + instrumental * 0.18 + (0.10 if "ambient" in text else 0.0)))
    cinematic = max(0.0, min(1.0, atmosphere * 0.48 + instrumental * 0.32 + synthetic * 0.20))
    intimate = max(0.0, min(1.0, organic * 0.36 + vocal_density * 0.34 + (1.0 - energy) * 0.20 + live * 0.10))
    polished = max(0.0, min(1.0, synthetic * 0.45 + (1.0 - live) * 0.25 + (1.0 - speech) * 0.15 + energy * 0.15))
    raw = max(0.0, min(1.0, organic * 0.36 + live * 0.30 + (0.22 if raw_context else 0.0) + (1.0 - polished) * 0.12))

    return {
        "synthetic_organic": synthetic - organic,
        "atmospheric_density": atmosphere,
        "vocal_density": vocal_density,
        "cinematic_intimate": cinematic - intimate,
        "polished_raw": polished - raw,
        "rhythmic_aggression": rhythmic_aggression,
        "ambient_weight": ambient_weight,
    }


def _texture_delta(a: dict, b: dict) -> float:
    a_vec = _texture_vector(a)
    b_vec = _texture_vector(b)
    weights = {
        "synthetic_organic": 0.20,
        "atmospheric_density": 0.16,
        "vocal_density": 0.17,
        "cinematic_intimate": 0.13,
        "polished_raw": 0.11,
        "rhythmic_aggression": 0.13,
        "ambient_weight": 0.10,
    }
    return sum(abs(a_vec[key] - b_vec[key]) * weight for key, weight in weights.items())


def _track_key(track: dict) -> str:
    raw = track.get("id") or f"{track.get('name', '')}::{track.get('artist', '')}"
    return str(raw).strip().lower()


def _primary_artist(track: dict) -> str:
    return str(track.get("artist", "")).split(",")[0].strip().lower()


def _is_exploration(track: dict) -> bool:
    return bool(track.get("exploration"))


# ---------------------------------------------------------------------------
# Transition distance between consecutive tracks
# ---------------------------------------------------------------------------

def _transition_distance(a: dict, b: dict) -> float:
    """
    Measure how abruptly track *b* follows track *a*.

    Combines energy, valence, danceability, and tempo deltas into a
    single distance in [0, 1] where 0 = identical feel, 1 = maximum contrast.
    """
    e_delta = abs(_energy(a) - _energy(b))
    v_delta = abs(_valence(a) - _valence(b))
    d_delta = abs(_danceability(a) - _danceability(b))
    t_delta = abs(_tempo(a) - _tempo(b))

    # Weighted L1 in audio-feature space — weights from SIMILARITY config
    _we = SIMILARITY.ENERGY_WEIGHT  if _CONFIG_AVAILABLE else 0.38
    _wv = SIMILARITY.VALENCE_WEIGHT if _CONFIG_AVAILABLE else 0.28
    _wd = SIMILARITY.DANCE_WEIGHT   if _CONFIG_AVAILABLE else 0.20
    _wt = SIMILARITY.TEMPO_WEIGHT   if _CONFIG_AVAILABLE else 0.14
    raw = _we * e_delta + _wv * v_delta + _wd * d_delta + _wt * t_delta
    return max(0.0, min(1.0, raw))


def _mood_vector(track: dict) -> Tuple[float, float]:
    """Return (energy, valence) as a 2-D mood coordinate."""
    return (_energy(track), _valence(track))


# ---------------------------------------------------------------------------
# Zone helpers — split playlist into intro / body / outro
# ---------------------------------------------------------------------------

def _zone_index(position: int, total: int) -> int:
    """Return 0 (intro), 1 (body), or 2 (outro)."""
    if total <= 2:
        return 1
    intro_end = max(1, total // 5)         # first ~20 %
    outro_start = total - max(1, total // 6)  # last ~17 %
    if position < intro_end:
        return 0
    if position >= outro_start:
        return 2
    return 1


def _zone_target(profile: dict, zone: int) -> Tuple[float, float]:
    """Return (energy_target, valence_target) for the given zone."""
    e = profile["energy_curve"][zone]
    v = profile["valence_curve"][zone]
    return e, v


def _phase_target(profile: dict, position: int, total: int) -> Tuple[float, float]:
    """
    Return smoothly interpolated energy/valence targets for a position.

    The profile still owns the session identity through its intro/body/outro
    curve. Interpolation only removes hard zone edges so phase transitions feel
    less mechanical on longer playlists.
    """
    if total <= 1:
        return _zone_target(profile, 1)

    frac = max(0.0, min(1.0, position / max(1, total - 1)))
    energies = profile["energy_curve"]
    valences = profile["valence_curve"]
    if frac <= 0.5:
        t = frac / 0.5
        return (
            energies[0] + (energies[1] - energies[0]) * t,
            valences[0] + (valences[1] - valences[0]) * t,
        )
    t = (frac - 0.5) / 0.5
    return (
        energies[1] + (energies[2] - energies[1]) * t,
        valences[1] + (valences[2] - valences[1]) * t,
    )


def _arc_dynamic_strength(profile: dict) -> float:
    """How much controlled emotional movement this profile should allow."""
    e_span = max(profile["energy_curve"]) - min(profile["energy_curve"])
    v_span = max(profile["valence_curve"]) - min(profile["valence_curve"])
    smooth = float(profile.get("smooth_reward", 0.12))
    spike_penalty = float(profile.get("energy_spike_penalty", 0.20))

    # Flat/utility sessions should remain steady. This preserves focus/calm
    # identity while allowing emotional, night-drive, party, rage, etc. to move.
    if e_span < 0.10 and v_span < 0.10:
        return 0.0
    if smooth >= 0.16 and spike_penalty >= 0.28 and (e_span + v_span) < 0.30:
        return 0.0

    abrupt_bonus = 0.10 if profile.get("allow_abrupt_at") else 0.0
    return max(0.0, min(1.0, 0.25 + (e_span + v_span) * 1.55 + abrupt_bonus))


def _arc_dynamics_reward(
    prev_track: Optional[dict],
    candidate: dict,
    recent_tracks: List[dict],
    position: int,
    total: int,
    profile: dict,
) -> Tuple[float, str]:
    """
    Small deterministic bonus for realistic emotional movement.

    This rewards controlled contrast, escalation, and recovery only when the
    transition is still below the existing abrupt-protection floor.
    """
    strength = _arc_dynamic_strength(profile)
    if strength <= 0.0 or prev_track is None or total < 6:
        return 0.0, ""

    dist = _transition_distance(prev_track, candidate)
    abrupt_floor = FLOW.ABRUPT_PENALTY_FLOOR if _CONFIG_AVAILABLE else 0.35
    if dist >= abrupt_floor:
        return 0.0, ""

    prev_energy = _energy(prev_track)
    cand_energy = _energy(candidate)
    prev_valence = _valence(prev_track)
    cand_valence = _valence(candidate)
    energy_delta = cand_energy - prev_energy
    valence_delta = cand_valence - prev_valence
    motion = abs(energy_delta) + 0.7 * abs(valence_delta)
    target_now = _phase_target(profile, position, total)
    target_next = _phase_target(profile, min(total - 1, position + 1), total)
    target_energy_delta = target_next[0] - target_now[0]
    frac = position / max(1, total - 1)

    recent = recent_tracks[-4:]
    recent_energies = [_energy(t) for t in recent]
    recent_valences = [_valence(t) for t in recent]
    recent_range = (
        max(recent_energies) - min(recent_energies)
        + 0.7 * (max(recent_valences) - min(recent_valences))
        if len(recent) >= 2 else 1.0
    )

    # Break long same-feel runs with a moderate, non-abrupt contrast in the
    # body of the playlist.
    if 0.16 <= frac <= 0.78 and len(recent) >= 2 and recent_range < 0.11:
        if 0.08 <= motion <= 0.28:
            smooth_gate = max(0.35, 1.0 - dist / abrupt_floor)
            return 0.085 * strength * smooth_gate, "contrast"

    # After intensity, reward a lower-energy recovery step near the current
    # phase target. This gives tension/release without inserting new tracks.
    recent_peak = max(recent_energies) if recent_energies else prev_energy
    if recent_peak >= target_now[0] + 0.10 and energy_delta <= -0.06:
        target_fit = 1.0 - min(1.0, abs(cand_energy - target_now[0]) + abs(cand_valence - target_now[1]))
        return 0.070 * strength * max(0.25, target_fit), "recovery"

    # Follow the profile's larger directional arc with modest rises/dips.
    if target_energy_delta > 0.025 and 0.025 <= energy_delta <= 0.18:
        return 0.045 * strength, "escalation"
    if target_energy_delta < -0.025 and -0.18 <= energy_delta <= -0.025:
        return 0.045 * strength, "release"

    return 0.0, ""


# ---------------------------------------------------------------------------
# Scoring helpers for the greedy sequencer
# ---------------------------------------------------------------------------

def _zone_alignment_reward(track: dict, position: int, total: int, profile: dict) -> float:
    """
    Soft reward [0, 1] for a track whose energy/valence sits close to
    the session-profile target for this zone.
    """
    e_tgt, v_tgt = _phase_target(profile, position, total)
    e_dist = abs(_energy(track) - e_tgt)
    v_dist = abs(_valence(track) - v_tgt)
    _ze = SIMILARITY.ZONE_ENERGY_WEIGHT if _CONFIG_AVAILABLE else 0.55
    _zv = SIMILARITY.ZONE_VALENCE_WEIGHT if _CONFIG_AVAILABLE else 0.45
    _zs = SIMILARITY.ZONE_SCALE_FACTOR   if _CONFIG_AVAILABLE else 2.0
    raw_dist = _ze * e_dist + _zv * v_dist
    return max(0.0, 1.0 - raw_dist * _zs)


def _abrupt_mood_penalty(prev_track: Optional[dict], candidate: dict, profile: dict) -> float:
    """
    Soft penalty [0, 1] for an abrupt mood jump.
    Scaled by the session profile's energy-spike weight.
    """
    if prev_track is None:
        return 0.0
    dist = _transition_distance(prev_track, candidate)
    # Apply spike penalty only when distance exceeds a moderate threshold
    _floor = FLOW.ABRUPT_PENALTY_FLOOR if _CONFIG_AVAILABLE else 0.35
    _range = SIMILARITY.ABRUPT_DIST_RANGE if _CONFIG_AVAILABLE else 0.65
    if dist <= _floor:
        return 0.0
    spike_weight = profile.get("energy_spike_penalty", 0.20)
    return min(1.0, (dist - _floor) / _range) * spike_weight


def _repeated_energy_spike_penalty(
    candidate: dict,
    recent_tracks: List[dict],
    profile: dict,
) -> float:
    """
    Penalise a third consecutive energy spike in the pacing window.
    Prevents workout-style bursts where they don't belong.
    """
    window = profile.get("pacing_window", 4)
    if len(recent_tracks) < 2:
        return 0.0
    # Count high-energy tracks in the window
    _ef = FLOW.SPIKE_ENERGY_FLOOR if _CONFIG_AVAILABLE else 0.72
    high_energy_count = sum(
        1 for t in recent_tracks[-window:]
        if _energy(t) >= _ef
    )
    _min_run = FLOW.SPIKE_MIN_RUN if _CONFIG_AVAILABLE else 2
    if high_energy_count < _min_run:
        return 0.0
    candidate_high = _energy(candidate) >= _ef
    if not candidate_high:
        return 0.0
    # Exponential penalty for long runs of high energy
    weight = profile.get("energy_spike_penalty", 0.20)
    _cap   = FLOW.SPIKE_PEN_CAP   if _CONFIG_AVAILABLE else 0.30
    _scale = FLOW.SPIKE_PEN_SCALE if _CONFIG_AVAILABLE else 0.12
    return min(_cap, weight * (high_energy_count - 1) * _scale)


def _repetitive_cluster_penalty(
    candidate: dict,
    recent_tracks: List[dict],
    profile: dict,
) -> float:
    """
    Penalise local same-cluster runs to preserve diversity.
    Uses the track's artist as a lightweight cluster proxy when
    no explicit community/cluster field is available.
    """
    window = profile.get("pacing_window", 4)
    if not recent_tracks:
        return 0.0

    # Prefer explicit community field, fall back to primary artist
    def _cluster(t: dict) -> str:
        return (
            str(t.get("community") or t.get("community_id") or "")
            or _primary_artist(t)
        )

    candidate_cluster = _cluster(candidate)
    if not candidate_cluster:
        return 0.0

    cluster_run = sum(
        1 for t in recent_tracks[-window:]
        if _cluster(t) == candidate_cluster
    )
    if cluster_run == 0:
        return 0.0

    weight = profile.get("cluster_penalty", 0.18)
    _cap   = FLOW.CLUSTER_PEN_CAP           if _CONFIG_AVAILABLE else 0.35
    _scale = FLOW.CLUSTER_PEN_PER_OCCURRENCE if _CONFIG_AVAILABLE else 0.15
    return min(_cap, weight * cluster_run * _scale)


def _smooth_transition_reward(prev_track: Optional[dict], candidate: dict, profile: dict) -> float:
    """
    Soft reward for a gradual, coherent transition from the previous track.
    """
    if prev_track is None:
        return 0.0
    dist = _transition_distance(prev_track, candidate)
    _ceil = FLOW.SMOOTH_REWARD_CEILING if _CONFIG_AVAILABLE else 0.45
    if dist >= _ceil:
        return 0.0
    reward_weight = profile.get("smooth_reward", 0.12)
    return (1.0 - dist / _ceil) * reward_weight


def _exploration_placement_reward(
    candidate: dict,
    position: int,
    total: int,
    exploration_zone: str,
    allow_abrupt_at: List[int],
) -> float:
    """
    Soft reward for placing exploration tracks at strategically beneficial
    positions, or a penalty for bad placement.

    Zone modes
    ----------
    "middle"       → best in body zone
    "tail"         → best in outro zone
    "distributed"  → anywhere except intro
    """
    if not _is_exploration(candidate):
        return 0.0

    # Abrupt-contrast positions are always fine for exploration
    if position in allow_abrupt_at:
        return FLOW.EXPLORE_ABRUPT_REWARD if _CONFIG_AVAILABLE else 0.10

    zone = _zone_index(position, total)

    _match  = FLOW.EXPLORE_ZONE_MATCH_REWARD  if _CONFIG_AVAILABLE else 0.12
    _mmis   = FLOW.EXPLORE_ZONE_MISMATCH_PEN  if _CONFIG_AVAILABLE else -0.06
    _tmis   = FLOW.EXPLORE_TAIL_MISMATCH_PEN  if _CONFIG_AVAILABLE else -0.04
    _dist   = FLOW.EXPLORE_DISTRIBUTED_REWARD if _CONFIG_AVAILABLE else 0.06

    if exploration_zone == "middle":
        return _match if zone == 1 else _mmis
    if exploration_zone == "tail":
        return _match if zone == 2 else _tmis
    if exploration_zone == "distributed":
        return 0.0 if zone == 0 else _dist
    return 0.0


def _artist_repeat_penalty(candidate: dict, recent_tracks: List[dict]) -> float:
    """Soft penalty for placing the same artist too close together."""
    artist = _primary_artist(candidate)
    if not artist:
        return 0.0
    _win = FLOW.ARTIST_WINDOW if _CONFIG_AVAILABLE else 5
    window = recent_tracks[-_win:]
    recent_artists = [_primary_artist(t) for t in window]
    count = recent_artists.count(artist)
    if count == 0:
        return 0.0
    _cap   = FLOW.ARTIST_PEN_CAP           if _CONFIG_AVAILABLE else 0.25
    _scale = FLOW.ARTIST_PEN_PER_OCCURRENCE if _CONFIG_AVAILABLE else 0.12
    return min(_cap, count * _scale)


def _closeness(value: float, center: float, radius: float) -> float:
    """Triangular closeness score around a fractional playlist position."""
    if radius <= 0:
        return 0.0
    return max(0.0, 1.0 - abs(value - center) / radius)


def _normalised_signal(value, default: float = 0.5) -> float:
    """Return metadata signals on a conservative [0, 1] scale."""
    raw = _safe_float(value, default)
    if raw > 1.0:
        raw = raw / 100.0
    return max(0.0, min(1.0, raw))


def _anchor_salience(track: dict) -> float:
    """
    Estimate whether a track can become a memorable emotional landmark.

    Uses only existing metadata: audio features, popularity/quality-like score
    fields, and exploration status. The blend is intentionally small and
    deterministic; it never changes the selected track set.
    """
    energy = _energy(track)
    valence = _valence(track)
    dance = _danceability(track)
    tempo = _tempo(track)
    acousticness = _acousticness(track)

    emotional_extreme = abs(valence - 0.5) * 2.0
    kinetic_presence = (energy + dance + tempo) / 3.0
    texture_contrast = min(
        1.0,
        abs(energy - 0.5) * 1.4
        + abs(valence - 0.5) * 1.2
        + abs(acousticness - 0.35) * 0.35,
    )
    quality = max(
        _normalised_signal(track.get("quality_score"), 0.5),
        _normalised_signal(track.get("score"), 0.5),
        _normalised_signal(track.get("final_score"), 0.5),
    )
    popularity = _normalised_signal(track.get("popularity"), 0.55)
    exploration = 1.0 if _is_exploration(track) else 0.0

    score = (
        emotional_extreme * 0.24
        + kinetic_presence * 0.22
        + texture_contrast * 0.18
        + quality * 0.16
        + popularity * 0.12
        + exploration * 0.08
    )
    return max(0.0, min(1.0, score))


def _anchor_reward(
    prev_track: Optional[dict],
    candidate: dict,
    recent_tracks: List[dict],
    position: int,
    total: int,
    profile: dict,
) -> Tuple[float, str, float]:
    """
    Sparse landmark reward for ignition/escalation/climax/recovery/release.

    This is not a fixed structure: every role is a soft positional fit plus a
    mood-shape fit. Rewards are gated by salience, spacing, and the same
    abrupt-transition floor used elsewhere in the flow engine.
    """
    strength = _arc_dynamic_strength(profile)
    if strength <= 0.0 or total < 8:
        return 0.0, "", 0.0

    abrupt_floor = FLOW.ABRUPT_PENALTY_FLOOR if _CONFIG_AVAILABLE else 0.35
    if prev_track is not None and _transition_distance(prev_track, candidate) >= abrupt_floor:
        return 0.0, "", 0.0

    anchors_so_far = sum(
        1 for track in recent_tracks
        if (track.get("flow_trace") or {}).get("anchor_role")
    )
    max_anchors = max(1, min(5, total // 6))
    if anchors_so_far >= max_anchors:
        return 0.0, "", 0.0
    if any((track.get("flow_trace") or {}).get("anchor_role") for track in recent_tracks[-3:]):
        return 0.0, "", 0.0

    salience = _anchor_salience(candidate)
    if salience < 0.50:
        return 0.0, "", salience

    frac = position / max(1, total - 1)
    energy = _energy(candidate)
    valence = _valence(candidate)
    prev_energy = _energy(prev_track) if prev_track is not None else energy
    body_energy = profile["energy_curve"][1]
    outro_energy = profile["energy_curve"][2]
    body_valence = profile["valence_curve"][1]
    outro_valence = profile["valence_curve"][2]

    role_fits = {
        "ignition": _closeness(frac, 0.18, 0.14) * (
            0.55 + 0.45 * max(0.0, min(1.0, (energy - prev_energy + 0.08) / 0.22))
        ),
        "escalation": _closeness(frac, 0.40, 0.18) * (
            0.45 + 0.55 * max(0.0, min(1.0, (energy - prev_energy + 0.04) / 0.20))
        ),
        "climax": _closeness(frac, 0.58, 0.18) * (
            0.40 + 0.60 * max(0.0, min(1.0, (energy - body_energy + 0.12) / 0.24))
        ),
        "recovery": _closeness(frac, 0.74, 0.18) * (
            0.45 + 0.55 * max(0.0, min(1.0, (prev_energy - energy + 0.05) / 0.24))
        ),
        "release": _closeness(frac, 0.88, 0.16) * (
            0.50
            + 0.25 * max(0.0, min(1.0, (outro_energy - energy + 0.14) / 0.28))
            + 0.25 * max(0.0, min(1.0, (valence - min(body_valence, outro_valence) + 0.08) / 0.30))
        ),
    }
    role, fit = max(role_fits.items(), key=lambda item: item[1])
    if (
        role == "escalation"
        and frac >= 0.30
        and energy >= body_energy + 0.04
        and salience >= 0.60
    ):
        role = "climax"
    if fit < 0.38:
        return 0.0, "", salience

    reward = 0.115 * strength * salience * fit
    return reward, role, salience


def _emotional_monotony_penalty(
    prev_track: Optional[dict],
    candidate: dict,
    recent_tracks: List[dict],
    profile: dict,
) -> float:
    """
    Discourage long same-feel stretches when a coherent pivot is available.

    Flat identities such as focus opt out via _arc_dynamic_strength().
    Abrupt candidates are already handled by abrupt penalties, so this only
    distinguishes near-identical continuations from moderate movement.
    """
    strength = _arc_dynamic_strength(profile)
    if strength <= 0.0 or prev_track is None or len(recent_tracks) < 3:
        return 0.0

    near_same_count = sum(
        1 for track in recent_tracks[-3:]
        if abs(_energy(candidate) - _energy(track)) < 0.025
        and abs(_valence(candidate) - _valence(track)) < 0.025
    )
    if near_same_count >= 2:
        return 0.130 * strength

    recent = recent_tracks[-4:]
    energies = [_energy(t) for t in recent]
    valences = [_valence(t) for t in recent]
    local_range = (
        max(energies) - min(energies)
        + 0.7 * (max(valences) - min(valences))
    )
    if local_range >= 0.10:
        return 0.0

    motion = abs(_energy(candidate) - _energy(prev_track)) + 0.7 * abs(_valence(candidate) - _valence(prev_track))
    if motion >= 0.07:
        return 0.0

    return 0.055 * strength * (1.0 - min(1.0, motion / 0.07))


def _transition_semantics_reward(
    prev_track: Optional[dict],
    candidate: dict,
    recent_tracks: List[dict],
    position: int,
    total: int,
    profile: dict,
) -> Tuple[float, str, Dict[str, float]]:
    """
    Give a tiny reward to emotionally legible neighboring-track transitions.

    The identity labels are trace-only explanations of local ordering behavior.
    They use audio metadata already present on tracks and stay below the
    existing abrupt-transition floor, so they cannot excuse jarring jumps.
    """
    if prev_track is None or total < 3:
        return 0.0, "", {}

    dist = _transition_distance(prev_track, candidate)
    abrupt_floor = FLOW.ABRUPT_PENALTY_FLOOR if _CONFIG_AVAILABLE else 0.35
    if dist >= abrupt_floor:
        return 0.0, "", {}

    prev_energy = _energy(prev_track)
    cand_energy = _energy(candidate)
    prev_valence = _valence(prev_track)
    cand_valence = _valence(candidate)
    energy_delta = cand_energy - prev_energy
    valence_delta = cand_valence - prev_valence
    mood_motion = abs(energy_delta) + 0.8 * abs(valence_delta)

    acoustic_delta = abs(_acousticness(prev_track) - _acousticness(candidate))
    dance_delta = abs(_danceability(prev_track) - _danceability(candidate))
    tempo_delta = abs(_tempo(prev_track) - _tempo(candidate))
    metadata_texture_delta = _texture_delta(prev_track, candidate)
    texture_delta = (
        acoustic_delta * 0.34
        + dance_delta * 0.16
        + tempo_delta * 0.12
        + metadata_texture_delta * 0.74
    )
    texture_coherence = max(0.0, 1.0 - texture_delta / 0.62)

    atmosphere = max(
        0.0,
        1.0 - (metadata_texture_delta * 0.90 + acoustic_delta * 0.55 + abs(valence_delta) * 0.45 + tempo_delta * 0.25),
    )
    rhythm = max(
        0.0,
        1.0 - (metadata_texture_delta * 0.60 + dance_delta * 0.85 + tempo_delta * 0.80 + abs(energy_delta) * 0.35),
    )
    continuation = max(0.0, 1.0 - mood_motion / 0.14) * max(atmosphere, rhythm)
    contrast_bridge = max(atmosphere, rhythm * 0.95)
    contrast = (
        max(0.0, 1.0 - abs(mood_motion - 0.22) / 0.18)
        * contrast_bridge
        * texture_coherence
    )

    recent_peak = max((_energy(t) for t in recent_tracks[-4:]), default=prev_energy)
    release_motion = max(0.0, -energy_delta) + max(0.0, valence_delta) * 0.75
    target_energy, target_valence = _phase_target(profile, position, total)
    release_target_fit = max(
        0.0,
        1.0 - (abs(cand_energy - target_energy) + abs(cand_valence - target_valence)),
    )
    release = (
        max(0.0, 1.0 - abs(release_motion - 0.16) / 0.16)
        * max(0.35, release_target_fit)
        * (1.0 if recent_peak >= target_energy + 0.06 else 0.55)
    )

    semantic_fits = {
        "emotional_continuation": continuation,
        "emotional_contrast": contrast,
        "atmospheric_continuity": atmosphere * max(0.0, 1.0 - mood_motion / 0.22),
        "rhythmic_continuity": rhythm * max(0.0, 1.0 - abs(energy_delta) / 0.20),
        "release_transition": release,
    }

    identity, fit = max(semantic_fits.items(), key=lambda item: item[1])
    if (
        energy_delta <= -0.06
        and 0.08 <= release_motion <= 0.30
        and recent_peak >= target_energy - 0.02
    ):
        identity, fit = "release_transition", max(fit, release, 0.55)
    elif (
        0.10 <= mood_motion <= 0.34
        and contrast >= 0.42
        and contrast_bridge >= 0.55
    ):
        identity, fit = "emotional_contrast", max(fit, contrast)
    elif (
        atmosphere >= 0.84
        and _acousticness(prev_track) >= 0.55
        and _acousticness(candidate) >= 0.55
        and mood_motion <= 0.12
    ):
        identity, fit = "atmospheric_continuity", max(fit, semantic_fits["atmospheric_continuity"])
    elif (
        rhythm >= 0.78
        and _danceability(prev_track) >= 0.70
        and _danceability(candidate) >= 0.70
        and tempo_delta <= 0.08
    ):
        identity, fit = "rhythmic_continuity", max(fit, semantic_fits["rhythmic_continuity"])
    elif mood_motion <= 0.06:
        identity, fit = "emotional_continuation", max(fit, continuation)

    if identity == "emotional_continuation" and len(recent_tracks) >= 3:
        recent = recent_tracks[-4:]
        recent_energies = [_energy(t) for t in recent]
        recent_valences = [_valence(t) for t in recent]
        recent_range = (
            max(recent_energies) - min(recent_energies)
            + 0.7 * (max(recent_valences) - min(recent_valences))
        )
        if recent_range < 0.10:
            return 0.0, "", {
                "mood_motion": round(mood_motion, 3),
                "texture_delta": round(texture_delta, 3),
                "texture_coherence": round(texture_coherence, 3),
            }

    if fit < 0.50:
        return 0.0, "", {
            "mood_motion": round(mood_motion, 3),
            "texture_delta": round(texture_delta, 3),
            "texture_coherence": round(texture_coherence, 3),
        }

    # Dynamic sessions may use contrast/release a bit more; flat sessions still
    # get continuation identity without being pushed toward dramatic pivots.
    dynamic_strength = _arc_dynamic_strength(profile)
    if identity in {"emotional_contrast", "release_transition"} and dynamic_strength <= 0.0:
        return 0.0, "", {
            "mood_motion": round(mood_motion, 3),
            "texture_delta": round(texture_delta, 3),
            "texture_coherence": round(texture_coherence, 3),
        }

    session_factor = 0.65 + 0.35 * dynamic_strength
    smooth_gate = max(0.25, 1.0 - dist / abrupt_floor)
    reward = 0.052 * fit * smooth_gate * session_factor

    return reward, identity, {
        "mood_motion": round(mood_motion, 3),
        "texture_delta": round(texture_delta, 3),
        "texture_coherence": round(texture_coherence, 3),
        "atmosphere": round(atmosphere, 3),
        "rhythm": round(rhythm, 3),
        "fit": round(fit, 3),
    }


# ---------------------------------------------------------------------------
# Greedy sequencer
# ---------------------------------------------------------------------------

def _greedy_sequence(
    tracks: List[dict],
    profile: dict,
    already_fixed: int = 0,
) -> List[dict]:
    """
    Greedy one-pass sequencer.

    For each position, score all remaining tracks and pick the best
    one.  The score balances:
      + zone alignment reward
      + smooth transition reward
      + exploration placement reward
      + sparse anchor salience reward
      − abrupt mood penalty
      − emotional monotony penalty
      − repeated energy spike penalty
      − repetitive cluster penalty
      − artist repeat penalty

    Parameters
    ----------
    tracks : list of track dicts (already contain audio features)
    profile : session profile dict (from SESSION_PROFILES)
    already_fixed : number of tracks at the head to keep in place
                    (used to preserve the top-ranked recommended track)
    """
    if len(tracks) <= 1:
        return tracks

    total = len(tracks)
    fixed = list(tracks[:already_fixed])
    pool = list(tracks[already_fixed:])
    placed = list(fixed)

    allow_abrupt_at: List[int] = profile.get("allow_abrupt_at", [])
    exploration_zone: str = profile.get("exploration_zone", "middle")

    while pool:
        position = len(placed)
        prev_track = placed[-1] if placed else None
        recent_tracks = placed[-profile.get("pacing_window", 4):]

        best_idx = 0
        best_adj = float("-inf")

        for idx, candidate in enumerate(pool):
            # Base: zone alignment
            zone_reward = _zone_alignment_reward(candidate, position, total, profile)

            # Transition smoothness
            smooth = _smooth_transition_reward(prev_track, candidate, profile)

            # Exploration placement
            explore_reward = _exploration_placement_reward(
                candidate, position, total, exploration_zone, allow_abrupt_at
            )

            # Emotional arc realism: controlled movement without abrupt jumps.
            arc_reward, arc_role = _arc_dynamics_reward(
                prev_track, candidate, recent_tracks, position, total, profile
            )

            # Sparse memorable landmarks: only soft rewards, never hard slots.
            anchor, anchor_role, anchor_salience = _anchor_reward(
                prev_track, candidate, placed, position, total, profile
            )

            # Local transition identity: meaningful neighbor compatibility.
            transition_semantic, transition_identity, transition_details = (
                _transition_semantics_reward(
                    prev_track, candidate, recent_tracks, position, total, profile
                )
            )

            # Penalties
            abrupt_pen = _abrupt_mood_penalty(prev_track, candidate, profile)
            monotony_pen = _emotional_monotony_penalty(
                prev_track, candidate, recent_tracks, profile
            )
            spike_pen = _repeated_energy_spike_penalty(candidate, recent_tracks, profile)
            cluster_pen = _repetitive_cluster_penalty(candidate, recent_tracks, profile)
            artist_pen = _artist_repeat_penalty(candidate, recent_tracks)

            if _CONFIG_AVAILABLE:
                adj = (
                    zone_reward  * FLOW.W_ZONE
                    + smooth     * FLOW.W_SMOOTH
                    + explore_reward * FLOW.W_EXPLORE
                    + arc_reward
                    + anchor
                    + transition_semantic
                    - abrupt_pen * FLOW.W_ABRUPT
                    - monotony_pen
                    - spike_pen  * FLOW.W_SPIKE
                    - cluster_pen * FLOW.W_CLUSTER
                    - artist_pen * FLOW.W_ARTIST_PEN
                    + FLOW.TIE_CONSTANT
                )
            else:
                adj = (
                    zone_reward * 0.30
                    + smooth * 0.25
                    + explore_reward * 0.10
                    + arc_reward
                    + anchor
                    + transition_semantic
                    - abrupt_pen * 0.20
                    - monotony_pen
                    - spike_pen * 0.08
                    - cluster_pen * 0.08
                    - artist_pen * 0.08
                    + 0.05
                )

            # Annotate for trace (only on tentative winner update)
            if adj > best_adj:
                best_adj = adj
                best_idx = idx
                best_trace = {
                    "zone_reward": round(zone_reward, 3),
                    "smooth_reward": round(smooth, 3),
                    "explore_reward": round(explore_reward, 3),
                    "arc_reward": round(arc_reward, 3),
                    "arc_role": arc_role,
                    "anchor_reward": round(anchor, 3),
                    "anchor_role": anchor_role,
                    "anchor_salience": round(anchor_salience, 3),
                    "transition_semantic_reward": round(transition_semantic, 3),
                    "transition_identity": transition_identity,
                    "transition_semantic": transition_details,
                    "abrupt_penalty": round(abrupt_pen, 3),
                    "monotony_penalty": round(monotony_pen, 3),
                    "spike_penalty": round(spike_pen, 3),
                    "cluster_penalty": round(cluster_pen, 3),
                    "artist_penalty": round(artist_pen, 3),
                    "flow_score": round(adj, 4),
                }

        chosen = pool.pop(best_idx)

        # Annotate track with flow trace (non-destructive merge)
        chosen = dict(chosen)
        chosen["flow_trace"] = best_trace
        chosen["flow_position"] = position
        placed.append(chosen)

    return placed


# ---------------------------------------------------------------------------
# Diversity preservation checks
# ---------------------------------------------------------------------------

def _count_exploration(tracks: List[dict]) -> int:
    return sum(1 for t in tracks if _is_exploration(t))


def _count_by_source(tracks: List[dict]) -> Counter:
    return Counter(t.get("source", "unknown") for t in tracks)


def _verify_ratios_preserved(
    original: List[dict],
    reordered: List[dict],
) -> bool:
    """
    Verify that reordering did not accidentally change the set of tracks.
    Returns True when the multisets match, False otherwise.
    """
    orig_keys = sorted(_track_key(t) for t in original)
    new_keys = sorted(_track_key(t) for t in reordered)
    return orig_keys == new_keys


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------

class PlaylistFlowEngine:
    """
    Lightweight post-ranking playlist sequencer.

    Usage
    -----
    engine = PlaylistFlowEngine()
    reordered = engine.reorder(tracks, session_type="night_drive")

    Or use the module-level convenience function::

        reordered = reorder_for_flow(tracks, session_type="focus")
    """

    def __init__(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def reorder(
        self,
        tracks: List[dict],
        session_type: Optional[str] = None,
        *,
        protect_top: int = 1,
        verbose: bool = False,
    ) -> List[dict]:
        """
        Reorder *tracks* for temporal and emotional coherence.

        Parameters
        ----------
        tracks : list of track dicts
            The final selected tracks from PlaylistGenerator.  Must
            already have audio features (energy, valence, danceability,
            acousticness, tempo).
        session_type : str or None
            One of: default, workout, focus, night_drive, emotional,
            discovery.  Falls back to "default" if unknown or None.
        protect_top : int
            How many top-ranked tracks to keep in position (avoids
            displacing the #1 recommendation).  Default = 1.
        verbose : bool
            If True, print a flow summary to stdout.

        Returns
        -------
        Reordered list of track dicts.  Each track gets a ``flow_trace``
        key injected with sequencing diagnostics.  The original track
        contents are NOT modified.
        """
        if not tracks:
            return tracks

        # Resolve profile — intent flow profiles override session profiles
        stype = (session_type or _DEFAULT_PROFILE).lower().strip()
        profile = None
        if _INTENTS_AVAILABLE:
            _intent = _get_intent(stype)
            if _intent is not None:
                profile = _intent.flow_profile.to_session_profile()
                print(f"[flow_engine] intent_profile={stype}")
        if profile is None:
            if stype not in _VALID_SESSION_TYPES:
                print(
                    f"[flow_engine] unknown session_type={stype!r} "
                    f"falling back to 'default'"
                )
                stype = _DEFAULT_PROFILE
            profile = SESSION_PROFILES[stype]

        # Safety: protect_top must not exceed list length
        protect_top = max(0, min(protect_top, len(tracks) - 1))

        # Run greedy sequencer
        reordered = _greedy_sequence(tracks, profile, already_fixed=protect_top)

        # Integrity check: guarantee same tracks, no additions or removals
        if not _verify_ratios_preserved(tracks, reordered):
            print(
                "[flow_engine] WARNING: ratio mismatch after reordering — "
                "returning original order"
            )
            return tracks

        if verbose:
            self._log_summary(tracks, reordered, stype)

        print(
            f"[flow_engine] session={stype} tracks={len(reordered)} "
            f"exploration={_count_exploration(reordered)} "
            f"protect_top={protect_top}"
        )

        return reordered

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def _log_summary(
        self,
        original: List[dict],
        reordered: List[dict],
        session_type: str,
    ) -> None:
        """Print a before/after comparison to stdout."""
        profile = SESSION_PROFILES.get(session_type, SESSION_PROFILES[_DEFAULT_PROFILE])
        print(f"\n[flow_engine.summary] session={session_type}")
        print(f"  Profile: {profile['description']}")
        print(f"  Tracks : {len(reordered)}")
        print()
        print(f"  {'#':>3}  {'Name':<34}  {'E':>5}  {'V':>5}  {'FlowScore':>9}  Notes")
        print("  " + "-" * 72)
        for i, track in enumerate(reordered, 1):
            name = (track.get("name") or "?")[:32]
            e = _energy(track)
            v = _valence(track)
            ft = track.get("flow_trace") or {}
            fs = ft.get("flow_score", 0.0)
            notes = []
            if _is_exploration(track):
                notes.append("explore")
            if ft.get("abrupt_penalty", 0) > 0.10:
                notes.append("⚡abrupt")
            if ft.get("smooth_reward", 0) > 0.08:
                notes.append("✓smooth")
            print(
                f"  {i:>3}. {name:<34}  {e:>5.2f}  {v:>5.2f}  {fs:>9.4f}  "
                f"{', '.join(notes)}"
            )
        print()

    def flow_report(self, reordered: List[dict]) -> dict:
        """
        Return a compact summary dict suitable for API responses or logging.

        Keys
        ----
        energy_curve      : list of per-track energy values
        valence_curve     : list of per-track valence values
        avg_transition    : mean transition distance between consecutive tracks
        max_transition    : largest single-step mood jump
        exploration_positions : positions of exploration tracks (1-indexed)
        """
        energies = [round(_energy(t), 3) for t in reordered]
        valences = [round(_valence(t), 3) for t in reordered]

        transitions = []
        for a, b in zip(reordered, reordered[1:]):
            transitions.append(_transition_distance(a, b))

        explore_positions = [
            i + 1 for i, t in enumerate(reordered) if _is_exploration(t)
        ]

        return {
            "energy_curve": energies,
            "valence_curve": valences,
            "avg_transition_distance": round(sum(transitions) / len(transitions), 3) if transitions else 0.0,
            "max_transition_distance": round(max(transitions), 3) if transitions else 0.0,
            "exploration_positions": explore_positions,
            "total_tracks": len(reordered),
        }


# ---------------------------------------------------------------------------
# Module-level convenience function  (primary integration surface)
# ---------------------------------------------------------------------------

def reorder_for_flow(
    tracks: List[dict],
    session_type: Optional[str] = None,
    *,
    protect_top: int = 1,
    verbose: bool = False,
) -> List[dict]:
    """
    Convenience wrapper around ``PlaylistFlowEngine.reorder``.

    This is the function to call from ``playlist_generator.py`` or
    ``main.py`` after final track selection and before serialization.

    Parameters
    ----------
    tracks       : list of track dicts with audio features
    session_type : optional session profile name (see SESSION_PROFILES)
    protect_top  : how many top-scored tracks to anchor at position 0+
    verbose      : print detailed sequencing trace

    Returns
    -------
    Reordered list (same tracks, different order, each with a flow_trace).
    """
    return PlaylistFlowEngine().reorder(
        tracks,
        session_type=session_type,
        protect_top=protect_top,
        verbose=verbose,
    )


# ---------------------------------------------------------------------------
# Smoke-test  (run as __main__)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import random

    print("=== PlaylistFlowEngine smoke-test ===\n")

    rng = random.Random(42)

    def _rand_track(name: str, artist: str, energy: float, valence: float, source: str = "library") -> dict:
        return {
            "id": f"{name}::{artist}".lower(),
            "name": name,
            "artist": artist,
            "energy": energy,
            "valence": valence,
            "danceability": energy * 0.9 + rng.uniform(-0.05, 0.05),
            "acousticness": 1.0 - energy * 0.7,
            "tempo": 80 + energy * 100,
            "source": source,
            "popularity": rng.randint(55, 90),
        }

    SAMPLE = [
        _rand_track("Track A", "Artist 1", 0.90, 0.80),
        _rand_track("Track B", "Artist 2", 0.30, 0.25),
        _rand_track("Track C", "Artist 3", 0.75, 0.65),
        _rand_track("Track D", "Artist 4", 0.50, 0.55),
        _rand_track("Track E", "Artist 1", 0.85, 0.70),
        _rand_track("Track F", "Artist 5", 0.40, 0.35, source="discovery"),
        _rand_track("Track G", "Artist 6", 0.60, 0.60),
        _rand_track("Track H", "Artist 7", 0.70, 0.72),
        _rand_track("Track I", "Artist 2", 0.20, 0.22, source="discovery"),
        _rand_track("Track J", "Artist 8", 0.55, 0.50),
    ]
    # Mark one exploration track
    SAMPLE[5]["exploration"] = True

    engine = PlaylistFlowEngine()

    for stype in ["default", "workout", "focus", "night_drive", "emotional", "discovery"]:
        print(f"\n{'='*60}")
        print(f"Session: {stype}")
        reordered = engine.reorder(SAMPLE, session_type=stype, verbose=True)
        report = engine.flow_report(reordered)
        print(f"  avg_transition={report['avg_transition_distance']}")
        print(f"  max_transition={report['max_transition_distance']}")
        print(f"  exploration_positions={report['exploration_positions']}")
