"""
session_intents.py — Intent-conditioned recommendation profiles.

Each session intent defines a complete behavioural contract that influences:

  1. RETRIEVAL   — audio feature filters gate which candidates enter the pool
  2. RANKING     — score weight adjustments change what rises to the top
  3. EXPLORATION — novelty tolerance controls how many unfamiliar tracks appear
  4. SEQUENCING  — arc type, pacing, smoothness drive flow engine behaviour

This is NOT additive mood bonuses. Each intent creates a structurally
different recommendation path:

  * workout  → filters out low-energy tracks, escalates momentum
  * focus    → rejects high-valence variance, minimal exploration
  * rage     → high energy floor, fast pacing, low smoothness demand

Architecture
------------
Intent profiles are consumed by:
  - playlist_generator._score_tracks_by_genome()  (weight modulation)
  - playlist_generator._intent_audio_gate()        (pre-scoring filter)
  - playlist_flow_engine.SESSION_PROFILES           (flow profile override)
  - exploration_engine.inject_exploration_tracks()  (ratio override)

The intent system sits ON TOP of existing session_type logic. If a matching
intent is found, its flow_profile overrides the session_type for sequencing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Intent profile schema
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AudioGate:
    """Hard pre-scoring filter on audio features. Tracks outside these
    bounds are removed from the candidate pool BEFORE genome scoring.
    None = no constraint on that axis."""
    energy_min: Optional[float] = None
    energy_max: Optional[float] = None
    valence_min: Optional[float] = None
    valence_max: Optional[float] = None
    danceability_min: Optional[float] = None
    danceability_max: Optional[float] = None
    acousticness_min: Optional[float] = None
    acousticness_max: Optional[float] = None
    tempo_min_bpm: Optional[float] = None
    tempo_max_bpm: Optional[float] = None

    def passes(self, track: dict) -> bool:
        """Return True if track passes all gate constraints."""
        checks = [
            (self.energy_min, self.energy_max, _feat(track, "energy")),
            (self.valence_min, self.valence_max, _feat(track, "valence")),
            (self.danceability_min, self.danceability_max, _feat(track, "danceability")),
            (self.acousticness_min, self.acousticness_max, _feat(track, "acousticness")),
        ]
        for lo, hi, val in checks:
            if val is None:
                continue
            if lo is not None and val < lo:
                return False
            if hi is not None and val > hi:
                return False
        # Tempo is in BPM, not 0-1
        tempo = track.get("tempo")
        if tempo is not None:
            try:
                tempo = float(tempo)
                if self.tempo_min_bpm is not None and tempo < self.tempo_min_bpm:
                    return False
                if self.tempo_max_bpm is not None and tempo > self.tempo_max_bpm:
                    return False
            except (TypeError, ValueError):
                pass
        return True


@dataclass(frozen=True)
class ScoreWeights:
    """Per-intent weight modulation for _score_tracks_by_genome.
    These REPLACE the default weights when an intent is active."""
    genome_weight: float = 0.38
    popularity_weight: float = 0.25
    mood_weight: float = 0.17
    region_weight: float = 0.12
    quality_weight: float = 0.08


@dataclass(frozen=True)
class FlowProfile:
    """Per-intent flow sequencing profile. Overrides SESSION_PROFILES
    when an intent is active."""
    description: str = ""
    energy_curve: Tuple[float, float, float] = (0.50, 0.70, 0.55)
    valence_curve: Tuple[float, float, float] = (0.55, 0.65, 0.55)
    allow_abrupt_at: Tuple[int, ...] = ()
    exploration_zone: str = "middle"
    cluster_penalty: float = 0.18
    energy_spike_penalty: float = 0.22
    smooth_reward: float = 0.12
    pacing_window: int = 4

    def to_session_profile(self) -> Dict[str, Any]:
        """Convert to the dict format expected by PlaylistFlowEngine."""
        return {
            "description": self.description,
            "energy_curve": list(self.energy_curve),
            "valence_curve": list(self.valence_curve),
            "allow_abrupt_at": list(self.allow_abrupt_at),
            "exploration_zone": self.exploration_zone,
            "cluster_penalty": self.cluster_penalty,
            "energy_spike_penalty": self.energy_spike_penalty,
            "smooth_reward": self.smooth_reward,
            "pacing_window": self.pacing_window,
        }


@dataclass(frozen=True)
class IntentProfile:
    """Complete intent profile controlling the full recommendation pipeline."""
    name: str
    description: str

    # Audio gate — hard pre-scoring filter
    audio_gate: AudioGate = field(default_factory=AudioGate)

    # Score weight modulation
    score_weights: ScoreWeights = field(default_factory=ScoreWeights)

    # Exploration control
    exploration_ratio: float = 0.10
    novelty_tolerance: float = 0.5          # 0=very conservative, 1=adventurous
    min_semantic_relatedness: float = 0.52   # exploration relatedness floor

    # Mood consistency strength — how heavily mood match is enforced
    # 0 = mood is decorative, 1 = mood is mandatory
    mood_consistency: float = 0.5

    # Artist repetition tolerance — how many times same artist may appear
    artist_repeat_limit: int = 2

    # Flow profile override
    flow_profile: FlowProfile = field(default_factory=FlowProfile)

    # Lyrical density tolerance — higher = prefer vocal, lower = prefer instrumental
    lyrical_density: float = 0.5            # 0=instrumental, 1=vocal-heavy

    # Emotional variance tolerance — how much valence swing is acceptable
    emotional_variance: float = 0.3         # stddev allowed in valence

    # Mood keywords — terms that boost relevance for this intent
    mood_keywords: Tuple[str, ...] = ()
    anti_keywords: Tuple[str, ...] = ()

    # Phase-based session evolution — optional, None = use flat flow_profile
    phases: Optional[Tuple["SessionPhase", ...]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SessionPhase:
    """
    A single phase within a session journey.

    Phases divide the playlist into N named segments, each with its own
    energy/valence targets, exploration allowance, and sequencing character.
    The flow engine interpolates smoothly between phases at boundaries.

    Attributes
    ----------
    name : str
        Human-readable label (e.g. 'warmup', 'peak', 'cooldown').
    weight : float
        Relative proportion of the playlist this phase occupies.
        Weights are normalised — they don't need to sum to 1.0.
    energy_target : float
        Target energy level (0–1) for tracks in this phase.
    valence_target : float
        Target valence level (0–1) for tracks in this phase.
    energy_spike_penalty : float
        How hard to penalise abrupt energy jumps within this phase.
        Higher = smoother (0.03 = rage phase allows spikes freely).
    smooth_reward : float
        How much to reward gradual transitions in this phase.
    exploration_boost : float
        Additive exploration ratio boost for this phase (+ve) or
        reduction (-ve).
    cluster_penalty : float
        How hard to penalise same-cluster clustering in this phase.
    allow_abrupt : bool
        If True, the phase boundary itself is treated as an abrupt
        contrast point — good for dramatic transitions.
    """
    name: str
    weight: float
    energy_target: float
    valence_target: float
    energy_spike_penalty: float = 0.20
    smooth_reward: float = 0.12
    exploration_boost: float = 0.0
    cluster_penalty: float = 0.18
    allow_abrupt: bool = False


# ---------------------------------------------------------------------------
# Intent resolution result
# ---------------------------------------------------------------------------

@dataclass
class IntentResolution:
    """Result of semantic intent resolution.

    Carries the resolved IntentProfile plus metadata about *how* it was
    resolved — confidence, whether blending occurred, and the pre-softening
    tier that should be applied to gates before adaptive relaxation.

    Attributes
    ----------
    profile : IntentProfile
        The resolved (possibly blended) intent profile.
    confidence : float
        Resolution confidence in [0, 1].  1.0 = exact name match.
    method : str
        How the intent was resolved: 'exact', 'semantic', 'blend', or 'none'.
    primary_name : str
        Name of the primary matched intent.
    secondary_name : str
        Name of the secondary intent when blending, else empty.
    blend_ratio : float
        Weight of the primary intent in a blend (1.0 = no blend).
    pre_soften_tier : int
        Gate softening tier to apply BEFORE adaptive relaxation.
        0 for high-confidence, 1-2 for moderate/weak confidence.
    """
    profile: IntentProfile
    confidence: float = 1.0
    method: str = "exact"
    primary_name: str = ""
    secondary_name: str = ""
    blend_ratio: float = 1.0
    pre_soften_tier: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "confidence": round(self.confidence, 3),
            "method": self.method,
            "primary_name": self.primary_name,
            "secondary_name": self.secondary_name,
            "blend_ratio": round(self.blend_ratio, 3),
            "pre_soften_tier": self.pre_soften_tier,
        }


# ---------------------------------------------------------------------------
# Confidence thresholds
# ---------------------------------------------------------------------------

# Cosine similarity is mapped to [0, 1] via (raw + 1) / 2.
# Calibrated for all-MiniLM-L6-v2:
#   - unrelated text produces raw cosine ~0.10-0.16 → confidence ~0.55-0.58
#   - weakly related text: raw ~0.18-0.28 → confidence ~0.59-0.64
#   - related text: raw ~0.30-0.50 → confidence ~0.65-0.75
#   - strongly related: raw 0.50+ → confidence 0.75+
_CONFIDENCE_COMMITTED  = 0.68   # full intent, no softening
_CONFIDENCE_MODERATE   = 0.62   # use intent, pre-soften gates by 1 tier
_CONFIDENCE_WEAK       = 0.58   # blend if possible, else soften by 2 tiers
# Below _CONFIDENCE_WEAK → return None (no intent match)

# Maximum similarity gap between top-2 intents that triggers blending
_BLEND_MARGIN = 0.08


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _feat(track: dict, key: str) -> Optional[float]:
    val = track.get(key)
    if val is None:
        return None
    try:
        f = float(val)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Intent profiles
# ---------------------------------------------------------------------------

INTENT_PROFILES: Dict[str, IntentProfile] = {

    "workout": IntentProfile(
        name="workout",
        description="High-energy escalating momentum. Fast BPM, sustained drive, minimal calm.",
        audio_gate=AudioGate(
            energy_min=0.55,
            valence_min=0.30,
            danceability_min=0.45,
            tempo_min_bpm=100,
        ),
        score_weights=ScoreWeights(
            genome_weight=0.30,
            popularity_weight=0.28,
            mood_weight=0.22,
            region_weight=0.10,
            quality_weight=0.10,
        ),
        exploration_ratio=0.08,
        novelty_tolerance=0.35,
        min_semantic_relatedness=0.55,
        mood_consistency=0.7,
        artist_repeat_limit=2,
        lyrical_density=0.6,
        emotional_variance=0.20,
        mood_keywords=("energetic", "dance", "party", "banger", "pump", "power",
                       "run", "fast", "workout", "anthem"),
        anti_keywords=("slow", "sad", "calm", "acoustic", "sleep", "lullaby"),
        flow_profile=FlowProfile(
            description="Escalating momentum — ramps hard, sustains peak, minimal taper",
            energy_curve=(0.72, 0.90, 0.82),
            valence_curve=(0.65, 0.75, 0.70),
            allow_abrupt_at=(2,),
            exploration_zone="tail",
            cluster_penalty=0.08,
            energy_spike_penalty=0.05,
            smooth_reward=0.04,
            pacing_window=3,
        ),
    ),

    "focus": IntentProfile(
        name="focus",
        description="Low volatility, minimal disruption. Calm, steady, instrumental-leaning.",
        audio_gate=AudioGate(
            energy_max=0.60,
            valence_min=0.25,
            valence_max=0.72,
            danceability_max=0.65,
        ),
        score_weights=ScoreWeights(
            genome_weight=0.40,
            popularity_weight=0.15,
            mood_weight=0.25,
            region_weight=0.10,
            quality_weight=0.10,
        ),
        exploration_ratio=0.05,
        novelty_tolerance=0.20,
        min_semantic_relatedness=0.60,
        mood_consistency=0.8,
        artist_repeat_limit=3,
        lyrical_density=0.3,
        emotional_variance=0.12,
        mood_keywords=("smooth", "chill", "lofi", "study", "deep", "ambient",
                       "calm", "focus", "instrumental"),
        anti_keywords=("party", "banger", "club", "dance", "anthem", "rage"),
        flow_profile=FlowProfile(
            description="Flat calm — minimal variance, no mood disruptions",
            energy_curve=(0.38, 0.42, 0.36),
            valence_curve=(0.50, 0.52, 0.48),
            allow_abrupt_at=(),
            exploration_zone="tail",
            cluster_penalty=0.20,
            energy_spike_penalty=0.30,
            smooth_reward=0.16,
            pacing_window=5,
        ),
    ),

    "heartbreak": IntentProfile(
        name="heartbreak",
        description="Emotional continuity. Low energy, high mood consistency, cathartic arc.",
        audio_gate=AudioGate(
            energy_max=0.65,
            valence_max=0.60,
        ),
        score_weights=ScoreWeights(
            genome_weight=0.35,
            popularity_weight=0.20,
            mood_weight=0.30,
            region_weight=0.08,
            quality_weight=0.07,
        ),
        exploration_ratio=0.08,
        novelty_tolerance=0.30,
        min_semantic_relatedness=0.58,
        mood_consistency=0.85,
        artist_repeat_limit=2,
        lyrical_density=0.8,
        emotional_variance=0.15,
        mood_keywords=("sad", "heartbreak", "lonely", "broken", "tears", "pain",
                       "missing", "love", "slow", "emotional"),
        anti_keywords=("party", "dance", "happy", "banger", "upbeat", "club"),
        flow_profile=FlowProfile(
            description="Emotional descent then cathartic resolution",
            energy_curve=(0.45, 0.35, 0.50),
            valence_curve=(0.50, 0.28, 0.48),
            allow_abrupt_at=(),
            exploration_zone="middle",
            cluster_penalty=0.10,
            energy_spike_penalty=0.25,
            smooth_reward=0.18,
            pacing_window=5,
        ),
    ),

    "night_drive": IntentProfile(
        name="night_drive",
        description="Atmospheric immersion. Moody build, sustained atmosphere, hypnotic pacing.",
        audio_gate=AudioGate(
            energy_min=0.25,
            energy_max=0.75,
            valence_max=0.65,
        ),
        score_weights=ScoreWeights(
            genome_weight=0.38,
            popularity_weight=0.18,
            mood_weight=0.24,
            region_weight=0.12,
            quality_weight=0.08,
        ),
        exploration_ratio=0.12,
        novelty_tolerance=0.50,
        min_semantic_relatedness=0.50,
        mood_consistency=0.65,
        artist_repeat_limit=2,
        lyrical_density=0.5,
        emotional_variance=0.22,
        mood_keywords=("night", "drive", "dark", "moody", "atmospheric", "synth",
                       "dream", "vibe", "cruising", "midnight"),
        anti_keywords=("acoustic", "folk", "classical", "devotional"),
        flow_profile=FlowProfile(
            description="Moody arc — low start, atmospheric peak, slow fade",
            energy_curve=(0.45, 0.65, 0.52),
            valence_curve=(0.40, 0.50, 0.38),
            allow_abrupt_at=(),
            exploration_zone="middle",
            cluster_penalty=0.15,
            energy_spike_penalty=0.20,
            smooth_reward=0.14,
            pacing_window=4,
        ),
    ),

    "party": IntentProfile(
        name="party",
        description="High energy, high variance allowed. Bangers, dance, crowd energy.",
        audio_gate=AudioGate(
            energy_min=0.50,
            valence_min=0.35,
            danceability_min=0.50,
        ),
        score_weights=ScoreWeights(
            genome_weight=0.28,
            popularity_weight=0.32,
            mood_weight=0.18,
            region_weight=0.12,
            quality_weight=0.10,
        ),
        exploration_ratio=0.12,
        novelty_tolerance=0.55,
        min_semantic_relatedness=0.48,
        mood_consistency=0.5,
        artist_repeat_limit=2,
        lyrical_density=0.7,
        emotional_variance=0.35,
        mood_keywords=("party", "dance", "club", "banger", "anthem", "hit",
                       "upbeat", "celebration", "fun", "groove"),
        anti_keywords=("sad", "slow", "acoustic", "calm", "sleep", "ambient"),
        flow_profile=FlowProfile(
            description="High energy with strategic variety — peaks and valleys for crowd energy",
            energy_curve=(0.68, 0.85, 0.72),
            valence_curve=(0.70, 0.78, 0.65),
            allow_abrupt_at=(3, 7),
            exploration_zone="distributed",
            cluster_penalty=0.12,
            energy_spike_penalty=0.06,
            smooth_reward=0.06,
            pacing_window=3,
        ),
    ),

    "healing": IntentProfile(
        name="healing",
        description="Gentle uplift from low to moderate. Soothing, gradual, positive resolution.",
        audio_gate=AudioGate(
            energy_max=0.65,
            valence_min=0.30,
        ),
        score_weights=ScoreWeights(
            genome_weight=0.36,
            popularity_weight=0.18,
            mood_weight=0.28,
            region_weight=0.10,
            quality_weight=0.08,
        ),
        exploration_ratio=0.10,
        novelty_tolerance=0.40,
        min_semantic_relatedness=0.55,
        mood_consistency=0.75,
        artist_repeat_limit=2,
        lyrical_density=0.6,
        emotional_variance=0.18,
        mood_keywords=("healing", "hope", "gentle", "soft", "peaceful", "calm",
                       "breathe", "light", "morning", "warmth"),
        anti_keywords=("rage", "banger", "club", "dark", "angry"),
        flow_profile=FlowProfile(
            description="Gentle ascending arc — starts soft, gradually warms",
            energy_curve=(0.32, 0.48, 0.55),
            valence_curve=(0.40, 0.55, 0.62),
            allow_abrupt_at=(),
            exploration_zone="tail",
            cluster_penalty=0.16,
            energy_spike_penalty=0.28,
            smooth_reward=0.18,
            pacing_window=5,
        ),
    ),

    "romantic": IntentProfile(
        name="romantic",
        description="Warm emotional continuity. Medium energy, high valence consistency.",
        audio_gate=AudioGate(
            energy_max=0.72,
            valence_min=0.35,
        ),
        score_weights=ScoreWeights(
            genome_weight=0.35,
            popularity_weight=0.22,
            mood_weight=0.25,
            region_weight=0.10,
            quality_weight=0.08,
        ),
        exploration_ratio=0.08,
        novelty_tolerance=0.35,
        min_semantic_relatedness=0.56,
        mood_consistency=0.80,
        artist_repeat_limit=2,
        lyrical_density=0.8,
        emotional_variance=0.15,
        mood_keywords=("love", "romantic", "heart", "dream", "beautiful",
                       "kiss", "together", "forever", "darling"),
        anti_keywords=("rage", "angry", "dark", "broken", "death", "war"),
        flow_profile=FlowProfile(
            description="Warm sustained arc — builds gently, holds warmth",
            energy_curve=(0.42, 0.58, 0.50),
            valence_curve=(0.60, 0.68, 0.62),
            allow_abrupt_at=(),
            exploration_zone="middle",
            cluster_penalty=0.14,
            energy_spike_penalty=0.22,
            smooth_reward=0.16,
            pacing_window=4,
        ),
    ),

    "rage": IntentProfile(
        name="rage",
        description="Maximum intensity. High energy floor, fast pacing, aggressive momentum.",
        audio_gate=AudioGate(
            energy_min=0.60,
            danceability_min=0.40,
            tempo_min_bpm=110,
        ),
        score_weights=ScoreWeights(
            genome_weight=0.30,
            popularity_weight=0.25,
            mood_weight=0.25,
            region_weight=0.10,
            quality_weight=0.10,
        ),
        exploration_ratio=0.06,
        novelty_tolerance=0.25,
        min_semantic_relatedness=0.58,
        mood_consistency=0.8,
        artist_repeat_limit=2,
        lyrical_density=0.7,
        emotional_variance=0.25,
        mood_keywords=("rage", "angry", "fire", "power", "fight", "intense",
                       "scream", "heavy", "dark", "aggressive"),
        anti_keywords=("calm", "soft", "gentle", "acoustic", "sleep", "lullaby"),
        flow_profile=FlowProfile(
            description="Relentless assault — high floor, no mercy, brutal pacing",
            energy_curve=(0.78, 0.92, 0.85),
            valence_curve=(0.40, 0.50, 0.45),
            allow_abrupt_at=(2, 5),
            exploration_zone="tail",
            cluster_penalty=0.06,
            energy_spike_penalty=0.03,
            smooth_reward=0.03,
            pacing_window=2,
        ),
    ),

    "calm": IntentProfile(
        name="calm",
        description="Pure tranquility. Minimal energy, very smooth, heavily acoustic.",
        audio_gate=AudioGate(
            energy_max=0.50,
            danceability_max=0.55,
            acousticness_min=0.20,
        ),
        score_weights=ScoreWeights(
            genome_weight=0.40,
            popularity_weight=0.15,
            mood_weight=0.28,
            region_weight=0.09,
            quality_weight=0.08,
        ),
        exploration_ratio=0.06,
        novelty_tolerance=0.25,
        min_semantic_relatedness=0.60,
        mood_consistency=0.85,
        artist_repeat_limit=3,
        lyrical_density=0.35,
        emotional_variance=0.10,
        mood_keywords=("calm", "peaceful", "soft", "quiet", "gentle", "zen",
                       "breathe", "relax", "sleep", "meditate"),
        anti_keywords=("party", "dance", "club", "banger", "rage", "scream"),
        flow_profile=FlowProfile(
            description="Pure calm — flat, warm, zero disruption",
            energy_curve=(0.30, 0.35, 0.28),
            valence_curve=(0.52, 0.55, 0.50),
            allow_abrupt_at=(),
            exploration_zone="tail",
            cluster_penalty=0.22,
            energy_spike_penalty=0.35,
            smooth_reward=0.20,
            pacing_window=6,
        ),
    ),

    "confidence": IntentProfile(
        name="confidence",
        description="Empowerment arc. Builds from moderate to strong, swagger-heavy.",
        audio_gate=AudioGate(
            energy_min=0.40,
            valence_min=0.35,
        ),
        score_weights=ScoreWeights(
            genome_weight=0.32,
            popularity_weight=0.28,
            mood_weight=0.22,
            region_weight=0.10,
            quality_weight=0.08,
        ),
        exploration_ratio=0.10,
        novelty_tolerance=0.45,
        min_semantic_relatedness=0.52,
        mood_consistency=0.65,
        artist_repeat_limit=2,
        lyrical_density=0.75,
        emotional_variance=0.22,
        mood_keywords=("confident", "boss", "power", "king", "queen", "swagger",
                       "unstoppable", "champion", "strong", "anthem"),
        anti_keywords=("sad", "broken", "lonely", "weak", "sleep"),
        flow_profile=FlowProfile(
            description="Empowerment ramp — starts moderate, builds to swagger peak",
            energy_curve=(0.50, 0.75, 0.70),
            valence_curve=(0.58, 0.72, 0.68),
            allow_abrupt_at=(3,),
            exploration_zone="middle",
            cluster_penalty=0.14,
            energy_spike_penalty=0.10,
            smooth_reward=0.10,
            pacing_window=4,
        ),
    ),

    "celebration": IntentProfile(
        name="celebration",
        description="Pure joy. High valence, high energy, maximum positivity.",
        audio_gate=AudioGate(
            energy_min=0.45,
            valence_min=0.45,
            danceability_min=0.40,
        ),
        score_weights=ScoreWeights(
            genome_weight=0.30,
            popularity_weight=0.30,
            mood_weight=0.22,
            region_weight=0.10,
            quality_weight=0.08,
        ),
        exploration_ratio=0.12,
        novelty_tolerance=0.50,
        min_semantic_relatedness=0.50,
        mood_consistency=0.65,
        artist_repeat_limit=2,
        lyrical_density=0.7,
        emotional_variance=0.28,
        mood_keywords=("celebration", "party", "happy", "joy", "cheer", "festival",
                       "dance", "fun", "victory", "winning"),
        anti_keywords=("sad", "dark", "broken", "lonely", "anger"),
        flow_profile=FlowProfile(
            description="Joyful wave — high valence with celebratory peaks",
            energy_curve=(0.60, 0.82, 0.70),
            valence_curve=(0.68, 0.80, 0.72),
            allow_abrupt_at=(4, 8),
            exploration_zone="distributed",
            cluster_penalty=0.12,
            energy_spike_penalty=0.08,
            smooth_reward=0.08,
            pacing_window=3,
        ),
    ),
}


# ---------------------------------------------------------------------------
# Lookup API
# ---------------------------------------------------------------------------

def get_intent(name: Optional[str]) -> Optional[IntentProfile]:
    """Look up an intent profile by name. Returns None for unknown intents."""
    if not name:
        return None
    return INTENT_PROFILES.get(name.strip().lower())


def list_intents() -> List[str]:
    """Return all available intent names."""
    return sorted(INTENT_PROFILES.keys())


# ---------------------------------------------------------------------------
# Semantic intent embedding (lazy-initialised, uses existing infrastructure)
# ---------------------------------------------------------------------------

_intent_embeddings: Optional[Dict[str, Any]] = None
_embedding_ranker_ref = None  # cached reference to avoid repeated lookups


def _build_intent_text(profile: IntentProfile) -> str:
    """Build a natural-language text summarising an intent for embedding."""
    parts = [profile.description]
    if profile.mood_keywords:
        parts.append("mood: " + " ".join(profile.mood_keywords))
    if profile.anti_keywords:
        parts.append("not: " + " ".join(profile.anti_keywords[:5]))
    return " ".join(parts)[:500]


def _get_ranker():
    """Obtain a reference to the existing EmbeddingRanker singleton.

    Tries the process-global UserProfileEncoder first (already loaded by
    the recommendation pipeline), then falls back to a direct import.
    Returns None when embeddings are genuinely unavailable.
    """
    global _embedding_ranker_ref
    if _embedding_ranker_ref is not None:
        return _embedding_ranker_ref

    # Path 1: reuse the singleton that user_profile_encoder already created
    try:
        from user_profile_encoder import _get_default_encoder
        encoder = _get_default_encoder()
        if encoder and getattr(encoder, "embedding_ranker", None):
            _embedding_ranker_ref = encoder.embedding_ranker
            return _embedding_ranker_ref
    except Exception:
        pass

    # Path 2: direct construction (same model, same cache)
    try:
        from embedding_ranker import EmbeddingRanker
        _embedding_ranker_ref = EmbeddingRanker()
        return _embedding_ranker_ref
    except Exception:
        pass

    return None


def _get_intent_embeddings() -> Optional[Dict[str, Any]]:
    """Lazily compute and cache semantic embeddings for all intent profiles.

    Uses the same ``all-MiniLM-L6-v2`` model already loaded by
    EmbeddingRanker — no new models, no new dependencies.
    """
    global _intent_embeddings
    if _intent_embeddings is not None:
        return _intent_embeddings

    ranker = _get_ranker()
    if ranker is None:
        return None

    texts = {}
    for name, profile in INTENT_PROFILES.items():
        texts[name] = _build_intent_text(profile)

    try:
        import numpy as np
        names = list(texts.keys())
        text_list = [texts[n] for n in names]
        vecs = ranker.embed_texts_cached(text_list)
        _intent_embeddings = {}
        for name, vec in zip(names, vecs):
            norm = np.linalg.norm(vec)
            if norm > 0:
                _intent_embeddings[name] = vec / norm
            else:
                _intent_embeddings[name] = vec
        print(f"[intent.embeddings] cached={len(_intent_embeddings)} intents")
        return _intent_embeddings
    except Exception as exc:
        print(f"[intent.embeddings.error] {exc}")
        return None


def _semantic_match(
    query: str,
) -> List[Tuple[str, float]]:
    """Return all intents ranked by cosine similarity to *query*.

    Each entry is ``(intent_name, confidence)`` where confidence is in
    ``[0, 1]`` (mapped from raw cosine via ``(cos + 1) / 2``).
    """
    embeddings = _get_intent_embeddings()
    if embeddings is None:
        return []

    ranker = _get_ranker()
    if ranker is None:
        return []

    try:
        import numpy as np
        query_vec = ranker.embed_cached(query.strip()[:500])
        query_norm = np.linalg.norm(query_vec)
        if query_norm > 0:
            query_vec = query_vec / query_norm
    except Exception:
        return []

    scores = []
    for name, intent_vec in embeddings.items():
        raw_cos = float(np.clip(np.dot(query_vec, intent_vec), -1.0, 1.0))
        confidence = (raw_cos + 1.0) / 2.0
        scores.append((name, confidence))

    scores.sort(key=lambda x: x[1], reverse=True)
    return scores


# ---------------------------------------------------------------------------
# Intent blending
# ---------------------------------------------------------------------------

def _lerp(a: Optional[float], b: Optional[float], t: float) -> Optional[float]:
    """Linear interpolation.  Returns None only if both inputs are None."""
    if a is None and b is None:
        return None
    va = a if a is not None else b
    vb = b if b is not None else a
    return va * t + vb * (1.0 - t)


def blend_profiles(
    primary: IntentProfile,
    secondary: IntentProfile,
    ratio: float,
) -> IntentProfile:
    """Blend two IntentProfiles by *ratio* (1.0 = 100 % primary).

    Rules
    -----
    - AudioGate bounds are linearly interpolated.
    - ScoreWeights are weighted-averaged then renormalised.
    - Exploration/mood/variance scalars are weighted-averaged.
    - FlowProfile uses the PRIMARY intent — flow arc is identity-defining
      and must not be averaged (per semantic_contracts.md).
    - mood_keywords/anti_keywords are unioned.
    - Name becomes "primary+secondary".
    """
    t = max(0.0, min(1.0, ratio))
    s = 1.0 - t

    # --- AudioGate ---
    pg, sg = primary.audio_gate, secondary.audio_gate
    blended_gate = AudioGate(
        energy_min=_lerp(pg.energy_min, sg.energy_min, t),
        energy_max=_lerp(pg.energy_max, sg.energy_max, t),
        valence_min=_lerp(pg.valence_min, sg.valence_min, t),
        valence_max=_lerp(pg.valence_max, sg.valence_max, t),
        danceability_min=_lerp(pg.danceability_min, sg.danceability_min, t),
        danceability_max=_lerp(pg.danceability_max, sg.danceability_max, t),
        acousticness_min=_lerp(pg.acousticness_min, sg.acousticness_min, t),
        acousticness_max=_lerp(pg.acousticness_max, sg.acousticness_max, t),
        tempo_min_bpm=_lerp(pg.tempo_min_bpm, sg.tempo_min_bpm, t),
        tempo_max_bpm=_lerp(pg.tempo_max_bpm, sg.tempo_max_bpm, t),
    )

    # --- ScoreWeights (renormalise) ---
    pw, sw = primary.score_weights, secondary.score_weights
    raw = [
        pw.genome_weight * t + sw.genome_weight * s,
        pw.popularity_weight * t + sw.popularity_weight * s,
        pw.mood_weight * t + sw.mood_weight * s,
        pw.region_weight * t + sw.region_weight * s,
        pw.quality_weight * t + sw.quality_weight * s,
    ]
    total = sum(raw) or 1.0
    blended_weights = ScoreWeights(
        genome_weight=raw[0] / total,
        popularity_weight=raw[1] / total,
        mood_weight=raw[2] / total,
        region_weight=raw[3] / total,
        quality_weight=raw[4] / total,
    )

    # --- Union keywords ---
    mood_kw = tuple(sorted(set(primary.mood_keywords) | set(secondary.mood_keywords)))
    anti_kw = tuple(sorted(set(primary.anti_keywords) | set(secondary.anti_keywords)))

    return IntentProfile(
        name=f"{primary.name}+{secondary.name}",
        description=f"Blend of {primary.name} ({t:.0%}) and {secondary.name} ({s:.0%})",
        audio_gate=blended_gate,
        score_weights=blended_weights,
        exploration_ratio=primary.exploration_ratio * t + secondary.exploration_ratio * s,
        novelty_tolerance=primary.novelty_tolerance * t + secondary.novelty_tolerance * s,
        min_semantic_relatedness=primary.min_semantic_relatedness * t + secondary.min_semantic_relatedness * s,
        mood_consistency=primary.mood_consistency * t + secondary.mood_consistency * s,
        artist_repeat_limit=round(primary.artist_repeat_limit * t + secondary.artist_repeat_limit * s),
        flow_profile=primary.flow_profile,       # NEVER blended — arc is identity
        lyrical_density=primary.lyrical_density * t + secondary.lyrical_density * s,
        emotional_variance=primary.emotional_variance * t + secondary.emotional_variance * s,
        mood_keywords=mood_kw,
        anti_keywords=anti_kw,
        phases=primary.phases,                    # phases from primary only
    )


# ---------------------------------------------------------------------------
# Public resolution API
# ---------------------------------------------------------------------------

def resolve_intent_with_confidence(
    session_type: Optional[str] = None,
    mood: Optional[str] = None,
) -> Optional[IntentResolution]:
    """
    Resolve an IntentProfile from session_type or mood with confidence
    scoring, semantic matching, and optional emotional blending.

    Three-layer resolution
    ----------------------
    1. **Exact match**: ``get_intent(session_type)`` or ``get_intent(mood)``.
       Confidence = 1.0, no blending.
    2. **Semantic match**: embed the mood string and compare against all
       intent embeddings.  If top-2 are within ``_BLEND_MARGIN``, blend
       proportionally.  Confidence from cosine similarity.
    3. **Fallback**: if confidence < ``_CONFIDENCE_WEAK``, return None.

    Returns ``IntentResolution`` or None.
    """
    # --- Layer 1: exact name match ---
    if session_type:
        profile = get_intent(session_type)
        if profile is not None:
            return IntentResolution(
                profile=profile,
                confidence=1.0,
                method="exact",
                primary_name=profile.name,
                blend_ratio=1.0,
                pre_soften_tier=0,
            )

    if mood:
        mood_lower = mood.strip().lower()
        profile = get_intent(mood_lower)
        if profile is not None:
            return IntentResolution(
                profile=profile,
                confidence=1.0,
                method="exact",
                primary_name=profile.name,
                blend_ratio=1.0,
                pre_soften_tier=0,
            )

        # --- Layer 2: semantic matching ---
        rankings = _semantic_match(mood_lower)
        if rankings:
            top_name, top_conf = rankings[0]

            if top_conf < _CONFIDENCE_WEAK:
                # No intent is close enough
                return None

            top_profile = INTENT_PROFILES[top_name]

            # Check for blend opportunity
            if len(rankings) >= 2:
                sec_name, sec_conf = rankings[1]
                gap = top_conf - sec_conf

                if gap <= _BLEND_MARGIN and sec_conf >= _CONFIDENCE_WEAK:
                    # Blend the top two
                    sec_profile = INTENT_PROFILES[sec_name]
                    total_sim = top_conf + sec_conf
                    ratio = top_conf / total_sim if total_sim > 0 else 0.5
                    blended = blend_profiles(top_profile, sec_profile, ratio)
                    # Confidence is the average of the two
                    blend_conf = (top_conf + sec_conf) / 2.0

                    # Determine pre-softening
                    if blend_conf >= _CONFIDENCE_COMMITTED:
                        soften = 0
                    elif blend_conf >= _CONFIDENCE_MODERATE:
                        soften = 1
                    else:
                        soften = 2

                    return IntentResolution(
                        profile=blended,
                        confidence=blend_conf,
                        method="blend",
                        primary_name=top_name,
                        secondary_name=sec_name,
                        blend_ratio=ratio,
                        pre_soften_tier=soften,
                    )

            # Single intent match — determine pre-softening from confidence
            if top_conf >= _CONFIDENCE_COMMITTED:
                soften = 0
            elif top_conf >= _CONFIDENCE_MODERATE:
                soften = 1
            else:
                soften = 2

            return IntentResolution(
                profile=top_profile,
                confidence=top_conf,
                method="semantic",
                primary_name=top_name,
                blend_ratio=1.0,
                pre_soften_tier=soften,
            )

        # --- Semantic matching unavailable: fall back to keyword scan ---
        # (preserves behavior when embedding infrastructure is absent)
        best_match = None
        best_score = 0
        for profile in INTENT_PROFILES.values():
            hits = sum(1 for kw in profile.mood_keywords if kw in mood_lower)
            if hits > best_score:
                best_score = hits
                best_match = profile
        if best_match is not None and best_score >= 1:
            # Keyword matches get confidence scaled to the new threshold range
            kw_conf = min(0.85, 0.63 + best_score * 0.07)
            soften = 0 if kw_conf >= _CONFIDENCE_COMMITTED else 1
            return IntentResolution(
                profile=best_match,
                confidence=kw_conf,
                method="keyword_fallback",
                primary_name=best_match.name,
                blend_ratio=1.0,
                pre_soften_tier=soften,
            )

    return None


def resolve_intent(
    session_type: Optional[str] = None,
    mood: Optional[str] = None,
) -> Optional[IntentProfile]:
    """
    Resolve an IntentProfile from session_type or mood.

    This is the backward-compatible wrapper.  It returns just the
    IntentProfile (or None), discarding confidence metadata.

    For full resolution metadata, use ``resolve_intent_with_confidence()``.
    """
    resolution = resolve_intent_with_confidence(
        session_type=session_type, mood=mood,
    )
    if resolution is None:
        return None
    return resolution.profile


# ---------------------------------------------------------------------------
# Adaptive constraint relaxation
# ---------------------------------------------------------------------------

# Relaxation widens AudioGate bounds progressively to prevent candidate
# starvation while preserving intent identity.  Three tiers:
#
#   Tier 0 — original gate (no relaxation)
#   Tier 1 — mild: ±0.08 on 0-1 features, ±10 BPM on tempo
#   Tier 2 — moderate: ±0.15 on features, ±20 BPM, +0.03 exploration
#   Tier 3 — strong: ±0.22 on features, ±30 BPM, +0.06 exploration,
#            drop acousticness/danceability constraints entirely
#
# Flow profile is NEVER relaxed — intent arc is identity-defining.
# Score weights are NEVER relaxed — ranking character is preserved.

MAX_RELAXATION_TIER = 3

_TIER_DELTAS = {
    #          feature_delta  tempo_delta  exploration_bonus  drop_secondary
    1: (0.08, 10.0, 0.03, False),
    2: (0.15, 20.0, 0.05, False),
    3: (0.22, 30.0, 0.08, True),
}


@dataclass
class PoolHealth:
    """Diagnostic snapshot of candidate pool after gating."""
    pool_name: str = ""
    pre_gate_count: int = 0
    post_gate_count: int = 0
    unique_artists: int = 0
    unique_communities: int = 0
    relaxation_tier: int = 0
    target_size: int = 0

    @property
    def survival_rate(self) -> float:
        return self.post_gate_count / max(1, self.pre_gate_count)

    @property
    def is_starved(self) -> bool:
        return self.post_gate_count < self.target_size

    @property
    def diversity_ratio(self) -> float:
        return self.unique_artists / max(1, self.post_gate_count)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pool_name": self.pool_name,
            "pre_gate": self.pre_gate_count,
            "post_gate": self.post_gate_count,
            "survival_rate": round(self.survival_rate, 3),
            "unique_artists": self.unique_artists,
            "diversity_ratio": round(self.diversity_ratio, 3),
            "relaxation_tier": self.relaxation_tier,
            "is_starved": self.is_starved,
        }


def _clamp(val: Optional[float], lo: float = 0.0, hi: float = 1.0) -> Optional[float]:
    if val is None:
        return None
    return max(lo, min(hi, val))


def relax_gate(gate: AudioGate, tier: int) -> AudioGate:
    """
    Return a new AudioGate with bounds widened by the given relaxation tier.

    Tier 0 returns the original gate unchanged.
    Higher tiers progressively widen bounds while keeping the gate directional
    (a min-energy gate stays a min-energy gate, just lower).
    """
    if tier <= 0:
        return gate
    tier = min(tier, MAX_RELAXATION_TIER)
    feat_delta, tempo_delta, _, drop_secondary = _TIER_DELTAS[tier]

    # Widen energy
    e_min = _clamp(gate.energy_min - feat_delta if gate.energy_min is not None else None)
    e_max = _clamp(gate.energy_max + feat_delta if gate.energy_max is not None else None)
    # Widen valence
    v_min = _clamp(gate.valence_min - feat_delta if gate.valence_min is not None else None)
    v_max = _clamp(gate.valence_max + feat_delta if gate.valence_max is not None else None)

    # Secondary features: drop entirely at tier 3
    if drop_secondary:
        d_min = d_max = a_min = a_max = None
    else:
        d_min = _clamp(gate.danceability_min - feat_delta if gate.danceability_min is not None else None)
        d_max = _clamp(gate.danceability_max + feat_delta if gate.danceability_max is not None else None)
        a_min = _clamp(gate.acousticness_min - feat_delta if gate.acousticness_min is not None else None)
        a_max = _clamp(gate.acousticness_max + feat_delta if gate.acousticness_max is not None else None)

    # Tempo
    t_min = max(40.0, gate.tempo_min_bpm - tempo_delta) if gate.tempo_min_bpm is not None else None
    t_max = min(250.0, gate.tempo_max_bpm + tempo_delta) if gate.tempo_max_bpm is not None else None

    return AudioGate(
        energy_min=e_min, energy_max=e_max,
        valence_min=v_min, valence_max=v_max,
        danceability_min=d_min, danceability_max=d_max,
        acousticness_min=a_min, acousticness_max=a_max,
        tempo_min_bpm=t_min, tempo_max_bpm=t_max,
    )


def adaptive_gate_filter(
    tracks: List[dict],
    intent: IntentProfile,
    *,
    min_pool_size: int = 15,
    min_artist_diversity: int = 5,
    pool_name: str = "unknown",
) -> tuple:
    """
    Apply the intent's AudioGate with progressive relaxation.

    Returns (filtered_tracks, PoolHealth) where the gate has been widened
    just enough to maintain playlist viability.

    Strategy
    --------
    1. Apply original gate (tier 0).
    2. If pool < min_pool_size OR unique artists < min_artist_diversity,
       try tier 1, then tier 2, then tier 3.
    3. Stop at the first tier that meets BOTH thresholds.
    4. If tier 3 still fails, return whatever we have (never empty —
       that's handled by existing fallback logic).

    The flow profile and score weights are NEVER modified.
    """
    pre_count = len(tracks)

    for tier in range(MAX_RELAXATION_TIER + 1):
        gate = relax_gate(intent.audio_gate, tier)
        filtered = [t for t in tracks if gate.passes(t)]
        artists = _count_unique_artists(filtered)

        if len(filtered) >= min_pool_size and artists >= min_artist_diversity:
            health = PoolHealth(
                pool_name=pool_name,
                pre_gate_count=pre_count,
                post_gate_count=len(filtered),
                unique_artists=artists,
                relaxation_tier=tier,
                target_size=min_pool_size,
            )
            if tier > 0:
                print(
                    f"[intent.relax] pool={pool_name} tier={tier} "
                    f"pre={pre_count} post={len(filtered)} artists={artists}"
                )
            return filtered, health

    # Tier 3 still insufficient — return what we have
    gate = relax_gate(intent.audio_gate, MAX_RELAXATION_TIER)
    filtered = [t for t in tracks if gate.passes(t)]
    artists = _count_unique_artists(filtered)
    health = PoolHealth(
        pool_name=pool_name,
        pre_gate_count=pre_count,
        post_gate_count=len(filtered),
        unique_artists=artists,
        relaxation_tier=MAX_RELAXATION_TIER,
        target_size=min_pool_size,
    )
    print(
        f"[intent.relax.exhausted] pool={pool_name} tier={MAX_RELAXATION_TIER} "
        f"pre={pre_count} post={len(filtered)} artists={artists} "
        f"STARVED={health.is_starved}"
    )
    return filtered, health


def relaxed_exploration_ratio(
    intent: IntentProfile,
    pool_health: PoolHealth,
) -> float:
    """
    Adjust exploration ratio based on pool health.

    If the pool is starved or diversity is low, increase exploration to
    compensate — but never exceed MAX_EXPLORATION_RATIO.
    """
    base = intent.exploration_ratio
    if pool_health.relaxation_tier <= 0:
        return base

    _, _, exploration_bonus, _ = _TIER_DELTAS[pool_health.relaxation_tier]
    adjusted = base + exploration_bonus

    # Further boost if diversity is critically low
    if pool_health.diversity_ratio < 0.4:
        adjusted += 0.02

    return min(0.20, adjusted)


def _count_unique_artists(tracks: List[dict]) -> int:
    """Count unique primary artists in a track list."""
    seen = set()
    for t in tracks:
        artist = str(t.get("artist", "") or "").split(",")[0].strip().lower()
        if artist:
            seen.add(artist)
    return len(seen)

