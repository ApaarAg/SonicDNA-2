"""
identity_narratives.py
======================
SonicDNA — Identity Narratives Module

Generates personalized identity insights from genome vectors, archetypes,
shadow archetypes, evolution history, and compatibility data.

Powers:
  - Identity cards
  - Reveal screens
  - Profile summaries
  - Evolution insights
  - Compatibility explanations

Assumptions about the existing SonicDNA codebase
-------------------------------------------------
* Shared SQLAlchemy `Base`, `SessionLocal`, `get_db` in `app.database`.
* `User` ORM model with:
    - id                : int
    - username          : str
    - archetype         : str | None
    - shadow_archetype  : str | None
    - genome_vector     : JSON list[float] | None
* `GenomeSnapshot` from genome_evolution.py exists with audio feature columns.
* `UserSimilarity` from social_constellation.py exists with similarity scores.
* ENV: DATABASE_URL already configured.
* ENV: OPENAI_API_KEY or ANTHROPIC_API_KEY — optional; used only when
       LLM_NARRATIVE_ENABLED=true. Falls back to deterministic engine
       if unset or if the LLM call fails.

New database objects
--------------------
* IdentityReading     — persisted narrative output per user + version
* CompatibilityReading — persisted compatibility narrative for a user pair
"""

from __future__ import annotations

import hashlib
import math
import os
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    desc,
    func,
)
from sqlalchemy.orm import Session, relationship

# ---------------------------------------------------------------------------
# Shared database objects
# ---------------------------------------------------------------------------
try:
    from app.database import Base, SessionLocal, get_db  # type: ignore
    from app.models import User  # type: ignore
except ImportError:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import declarative_base, sessionmaker

    _DB_URL = os.getenv("DATABASE_URL", "sqlite:///./sonic_dna_dev.db")
    _engine = create_engine(
        _DB_URL,
        connect_args={"check_same_thread": False} if "sqlite" in _DB_URL else {},
    )
    Base = declarative_base()
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)

    def get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    class User(Base):  # type: ignore[no-redef]
        __tablename__ = "users"
        id               = Column(Integer, primary_key=True, index=True)
        username         = Column(String(120), unique=True, nullable=False)
        archetype        = Column(String(80), nullable=True)
        shadow_archetype = Column(String(80), nullable=True)
        genome_vector    = Column(JSON, nullable=True)


USER_ID_TYPE = User.id.type

# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------

LLM_ENABLED: bool = os.getenv("LLM_NARRATIVE_ENABLED", "false").lower() == "true"
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "anthropic").lower()  # "anthropic" | "openai"


# ---------------------------------------------------------------------------
# Archetype Knowledge Base
# ---------------------------------------------------------------------------
# Each archetype entry encodes behavioural dimensions used by the narrative
# engine to produce non-generic, data-grounded text.

ARCHETYPE_KB: Dict[str, Dict[str, Any]] = {
    "explorer": {
        "core_drive":        "novelty and sonic frontier-pushing",
        "emotional_pattern": "cycles between restless curiosity and brief satiation after discovery",
        "strength":          "unmatched breadth of musical reference; connecting sounds others never would",
        "blind_spot":        "depth — the explorer moves on before fully inhabiting a sound world",
        "growth_direction":  "choose one genre per month and go deeper than feels comfortable",
        "music_relationship": "music is a map — you are always looking for the edge of the known territory",
        "shadow_trigger":    "repetition and familiarity; genres that feel 'done'",
        "feature_affinity":  {"energy": 0.7, "valence": 0.55, "acousticness": 0.3, "instrumentalness": 0.5},
    },
    "devotee": {
        "core_drive":        "deep loyalty and emotional communion with beloved artists",
        "emotional_pattern": "intense attachment phases followed by protective advocacy for overlooked work",
        "strength":          "extraordinary depth of knowledge; emotional literacy within a canon",
        "blind_spot":        "confirmation bias — returning to comfort rather than risk",
        "growth_direction":  "let an artist you love lead you to one artist you've never heard",
        "music_relationship": "music is a relationship — you don't consume it, you inhabit it",
        "shadow_trigger":    "hype cycles and bandwagon listeners who haven't 'earned' their fandom",
        "feature_affinity":  {"energy": 0.5, "valence": 0.6, "acousticness": 0.55, "danceability": 0.5},
    },
    "curator": {
        "core_drive":        "craft and editorial judgment in assembling the perfect listening context",
        "emotional_pattern": "satisfaction from precision; discomfort when the sequence is wrong",
        "strength":          "exceptional contextual intelligence — right song, right moment",
        "blind_spot":        "over-curation can suppress spontaneity and genuine surprise",
        "growth_direction":  "create one intentionally imperfect playlist with no editing allowed",
        "music_relationship": "music is architecture — every track is a structural decision",
        "shadow_trigger":    "shuffle mode and algorithmic playlists that disregard intention",
        "feature_affinity":  {"energy": 0.5, "valence": 0.5, "acousticness": 0.5, "speechiness": 0.35},
    },
    "rebel": {
        "core_drive":        "resistance to mainstream taste and institutional gatekeeping",
        "emotional_pattern": "fierce pride in obscurity; occasional loneliness of the unshared discovery",
        "strength":          "early-adopter instinct; finding signal in noise before consensus forms",
        "blind_spot":        "contrarianism for its own sake can crowd out genuine appreciation",
        "growth_direction":  "find one massively popular song and explore why it resonates with millions",
        "music_relationship": "music is a statement — what you listen to defines what you refuse to be",
        "shadow_trigger":    "commercial success of artists you championed before they broke",
        "feature_affinity":  {"energy": 0.75, "valence": 0.4, "acousticness": 0.35, "speechiness": 0.5},
    },
    "nostalgist": {
        "core_drive":        "emotional retrieval and preservation of formative sonic memories",
        "emotional_pattern": "triggered by familiar sounds into vivid episodic memory and warm melancholy",
        "strength":          "deep emotional intelligence; music as autobiography",
        "blind_spot":        "living in sonic amber — present-day discoveries feel like impostors",
        "growth_direction":  "find a contemporary artist whose work evokes the same feeling as a childhood record",
        "music_relationship": "music is memory — each song is a portal to a specific version of yourself",
        "shadow_trigger":    "remastered versions that alter the sound of beloved recordings",
        "feature_affinity":  {"energy": 0.45, "valence": 0.65, "acousticness": 0.65, "tempo": 0.4},
    },
    "futurist": {
        "core_drive":        "sonic innovation and the thrill of music that hasn't been named yet",
        "emotional_pattern": "impatience with the present; drawn to tension and unresolved sound",
        "strength":          "pattern recognition across emerging genres before they crystallise",
        "blind_spot":        "novelty fatigue — the cutting edge gets boring the moment it's named",
        "growth_direction":  "trace the lineage of one futuristic sound back to its folk or classical root",
        "music_relationship": "music is a prototype — every track is a proof of concept for what comes next",
        "shadow_trigger":    "nostalgia-bait and artists who rehash rather than advance",
        "feature_affinity":  {"energy": 0.65, "valence": 0.45, "instrumentalness": 0.6, "tempo": 0.65},
    },
    "empath": {
        "core_drive":        "emotional resonance and the feeling of being understood through sound",
        "emotional_pattern": "absorbs the emotional register of music completely; can be overwhelmed",
        "strength":          "uses music as precise emotional regulation; high sensitivity to lyrical nuance",
        "blind_spot":        "avoids sonically challenging music that might trigger discomfort",
        "growth_direction":  "spend a week with music that challenges rather than comforts you",
        "music_relationship": "music is a mirror — you are always looking for the song that knows you",
        "shadow_trigger":    "music used as background noise; treating songs as commodities",
        "feature_affinity":  {"energy": 0.45, "valence": 0.55, "acousticness": 0.65, "speechiness": 0.45},
    },
    "analyst": {
        "core_drive":        "structural understanding — music as system, not just feeling",
        "emotional_pattern": "aesthetic pleasure triggered by recognising patterns, motifs, and exceptions",
        "strength":          "cross-genre literacy; can decode what makes any music work",
        "blind_spot":        "intellectualising can suppress visceral emotional response",
        "growth_direction":  "listen to one album with no analysis — just let it move you",
        "music_relationship": "music is a language — you are always reading between the lines",
        "shadow_trigger":    "music praised for reasons you consider structurally incoherent",
        "feature_affinity":  {"energy": 0.5, "valence": 0.45, "instrumentalness": 0.55, "tempo": 0.55},
    },
    "unknown": {
        "core_drive":        "an evolving and still-forming relationship with sound",
        "emotional_pattern": "in flux — patterns are emerging but not yet stabilised",
        "strength":          "openness; your taste has not yet calcified into habit",
        "blind_spot":        "lack of self-knowledge about what you actually want from music",
        "growth_direction":  "track what you skip and what you replay — the data knows before you do",
        "music_relationship": "music is a question — you haven't settled on an answer yet",
        "shadow_trigger":    "being asked to explain your taste",
        "feature_affinity":  {"energy": 0.5, "valence": 0.5, "acousticness": 0.5, "danceability": 0.5},
    },
}

# Shadow archetype modifiers — applied on top of primary archetype readings
SHADOW_MODIFIERS: Dict[str, Dict[str, str]] = {
    "explorer": {
        "hidden_trait": "a secret longing for a sound world you could call home",
        "modifier":     "your shadow pulls toward depth even as your primary self resists it",
    },
    "devotee": {
        "hidden_trait": "an unexpressed hunger for music that would genuinely surprise you",
        "modifier":     "your shadow is more adventurous than you allow yourself to be publicly",
    },
    "curator": {
        "hidden_trait": "a repressed desire to abandon the list and just feel",
        "modifier":     "your shadow wants chaos; your primary self won't allow it",
    },
    "rebel": {
        "hidden_trait": "a private appreciation for something embarrassingly mainstream",
        "modifier":     "your shadow enjoys what your public taste would never admit to",
    },
    "nostalgist": {
        "hidden_trait": "a quiet excitement about a present-day artist you won't let yourself claim",
        "modifier":     "your shadow is more present-tense than you show",
    },
    "futurist": {
        "hidden_trait": "a sentimental attachment to a formative sound you've moved past publicly",
        "modifier":     "your shadow roots you when your primary self would rather keep moving",
    },
    "empath": {
        "hidden_trait": "an analytical streak that dissects music even as you claim to just feel it",
        "modifier":     "your shadow is cooler and more observational than your primary self",
    },
    "analyst": {
        "hidden_trait": "a deeply emotional response to certain music that your frameworks can't explain",
        "modifier":     "your shadow feels what your primary self insists on understanding",
    },
    "unknown": {
        "hidden_trait": "more pattern and preference than you've acknowledged yet",
        "modifier":     "your shadow knows your taste; your primary self is still catching up",
    },
}

# Archetype compatibility affinity matrix [0.0 – 1.0]
ARCHETYPE_COMPAT: Dict[Tuple[str, str], float] = {
    ("explorer",   "futurist"):  0.88,
    ("explorer",   "rebel"):     0.78,
    ("explorer",   "analyst"):   0.72,
    ("devotee",    "nostalgist"): 0.90,
    ("devotee",    "empath"):    0.85,
    ("devotee",    "curator"):   0.74,
    ("curator",    "analyst"):   0.86,
    ("curator",    "futurist"):  0.68,
    ("rebel",      "futurist"):  0.80,
    ("rebel",      "explorer"):  0.78,
    ("nostalgist", "empath"):    0.84,
    ("nostalgist", "devotee"):   0.90,
    ("futurist",   "analyst"):   0.76,
    ("empath",     "nostalgist"): 0.84,
    ("empath",     "devotee"):   0.85,
    ("analyst",    "curator"):   0.86,
    ("analyst",    "futurist"):  0.76,
}

def _archetype_affinity(a: str, b: str) -> float:
    if a == b:
        return 0.95
    key = tuple(sorted([a.lower(), b.lower()]))
    return ARCHETYPE_COMPAT.get(key, 0.40)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ORM Models
# ---------------------------------------------------------------------------

class IdentityReading(Base):
    """
    Persisted narrative identity reading for a user.
    Versioned — each recalculation appends a new row; the latest is served.
    """
    __tablename__ = "identity_readings"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    user_id             = Column(USER_ID_TYPE, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    version             = Column(Integer, nullable=False, default=1)
    input_hash          = Column(String(64), nullable=False)  # SHA-256 of inputs; skip regen if unchanged

    # Narrative fields
    identity_statement  = Column(Text, nullable=False)
    hidden_trait        = Column(Text, nullable=False)
    emotional_pattern   = Column(Text, nullable=False)
    strength            = Column(Text, nullable=False)
    blind_spot          = Column(Text, nullable=False)
    growth_direction    = Column(Text, nullable=False)
    music_relationship  = Column(Text, nullable=False)
    compatibility_summary = Column(Text, nullable=True)

    # Scoring
    openness_score      = Column(Float, nullable=False, default=0.0)   # 0–100
    depth_score         = Column(Float, nullable=False, default=0.0)
    energy_score        = Column(Float, nullable=False, default=0.0)
    valence_score       = Column(Float, nullable=False, default=0.0)
    complexity_score    = Column(Float, nullable=False, default=0.0)
    evolution_rate      = Column(Float, nullable=True)   # how fast genome is changing

    # Generation metadata
    generated_by        = Column(String(32), nullable=False, default="deterministic")  # "deterministic" | "llm"
    archetype_at_gen    = Column(String(80), nullable=True)
    shadow_at_gen       = Column(String(80), nullable=True)
    snapshot_count      = Column(Integer, nullable=False, default=0)

    created_at          = Column(DateTime(timezone=True), nullable=False,
                                 default=lambda: datetime.now(timezone.utc))

    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        Index("ix_ir_user_id",      "user_id"),
        Index("ix_ir_user_version", "user_id", "version"),
        Index("ix_ir_created_at",   "created_at"),
    )


class CompatibilityReading(Base):
    """
    Persisted compatibility narrative for a directed user pair.
    user_a_id < user_b_id for canonical ordering.
    """
    __tablename__ = "compatibility_readings"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    user_a_id       = Column(USER_ID_TYPE, ForeignKey("users.id"), nullable=False)
    user_b_id       = Column(USER_ID_TYPE, ForeignKey("users.id"), nullable=False)
    comparison_id   = Column(String(64), nullable=False, unique=True, index=True)

    overall_score       = Column(Float, nullable=False)   # 0–100
    genome_score        = Column(Float, nullable=False)
    archetype_score     = Column(Float, nullable=False)
    tension_score       = Column(Float, nullable=False)   # productive difference

    narrative           = Column(Text, nullable=False)
    shared_traits       = Column(JSON, nullable=False, default=list)
    tension_points      = Column(JSON, nullable=False, default=list)
    growth_together     = Column(Text, nullable=False)
    listening_chemistry = Column(Text, nullable=False)

    generated_by        = Column(String(32), nullable=False, default="deterministic")
    created_at          = Column(DateTime(timezone=True), nullable=False,
                                 default=lambda: datetime.now(timezone.utc))

    user_a = relationship("User", foreign_keys=[user_a_id])
    user_b = relationship("User", foreign_keys=[user_b_id])

    __table_args__ = (
        UniqueConstraint("user_a_id", "user_b_id", name="uq_compat_pair"),
        Index("ix_cr_user_a", "user_a_id"),
        Index("ix_cr_user_b", "user_b_id"),
    )


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------

class GenomeFeatures(BaseModel):
    danceability:     Optional[float] = Field(None, ge=0.0, le=1.0)
    energy:           Optional[float] = Field(None, ge=0.0, le=1.0)
    valence:          Optional[float] = Field(None, ge=0.0, le=1.0)
    acousticness:     Optional[float] = Field(None, ge=0.0, le=1.0)
    instrumentalness: Optional[float] = Field(None, ge=0.0, le=1.0)
    speechiness:      Optional[float] = Field(None, ge=0.0, le=1.0)
    tempo:            Optional[float] = Field(None, ge=0.0, le=300.0)
    genome_vector:    Optional[List[float]] = None


class EvolutionSummary(BaseModel):
    snapshot_count:  int = 0
    archetype_changes: int = 0
    dominant_archetype: Optional[str] = None
    energy_delta:    Optional[float] = None   # last - first
    valence_delta:   Optional[float] = None
    tempo_delta:     Optional[float] = None


class NarrativeScores(BaseModel):
    openness_score:    float = Field(..., ge=0.0, le=100.0)
    depth_score:       float = Field(..., ge=0.0, le=100.0)
    energy_score:      float = Field(..., ge=0.0, le=100.0)
    valence_score:     float = Field(..., ge=0.0, le=100.0)
    complexity_score:  float = Field(..., ge=0.0, le=100.0)
    evolution_rate:    Optional[float] = None


# --- Requests ---

class GenerateIdentityRequest(BaseModel):
    user_id:          int
    genome:           Optional[GenomeFeatures] = None
    archetype:        Optional[str] = None
    shadow_archetype: Optional[str] = None
    evolution:        Optional[EvolutionSummary] = None
    force_regenerate: bool = Field(False, description="Bypass input-hash cache check.")
    use_llm:          bool = Field(False, description="Attempt LLM generation (requires LLM_NARRATIVE_ENABLED=true).")


class GenerateCompatibilityRequest(BaseModel):
    user_a_id:       int
    user_b_id:       int
    genome_score:    Optional[float] = Field(None, ge=0.0, le=1.0)
    force_regenerate: bool = False
    use_llm:          bool = False


# --- Responses ---

class IdentityReadingOut(BaseModel):
    id:                   int
    user_id:              int
    version:              int
    identity_statement:   str
    hidden_trait:         str
    emotional_pattern:    str
    strength:             str
    blind_spot:           str
    growth_direction:     str
    music_relationship:   str
    compatibility_summary: Optional[str]
    scores:               NarrativeScores
    archetype:            Optional[str]
    shadow_archetype:     Optional[str]
    snapshot_count:       int
    generated_by:         str
    created_at:           datetime

    model_config = {"from_attributes": True}


class EvolutionNarrativeOut(BaseModel):
    user_id:              int
    snapshot_count:       int
    archetype_journey:    List[str]   # chronological archetype states
    evolution_statement:  str
    momentum:             str         # "accelerating" | "stable" | "shifting" | "dormant"
    energy_arc:           str         # human-readable description of energy trend
    valence_arc:          str
    pivot_moments:        List[Dict[str, Any]]   # notable archetype or feature transitions
    current_reading:      Optional[IdentityReadingOut]


class CompatibilityReadingOut(BaseModel):
    comparison_id:       str
    user_a_id:           int
    user_b_id:           int
    overall_score:       float
    genome_score:        float
    archetype_score:     float
    tension_score:       float
    narrative:           str
    shared_traits:       List[str]
    tension_points:      List[str]
    growth_together:     str
    listening_chemistry: str
    generated_by:        str
    created_at:          datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Narrative Engine — Deterministic
# ---------------------------------------------------------------------------

class NarrativeEngine:
    """
    Builds identity narratives from structured genome and archetype data
    without LLM dependency.

    All output is grounded in actual user data — feature values, archetype
    knowledge-base entries, and evolution deltas drive every sentence.
    The engine is designed so an LLM integration layer can use its output
    as a structured prompt context (see LLMNarrativeLayer below).
    """

    @staticmethod
    def _feat(genome: Optional[GenomeFeatures], key: str, default: float = 0.5) -> float:
        if genome is None:
            return default
        return getattr(genome, key, None) or default

    @staticmethod
    def _tempo_normalised(genome: Optional[GenomeFeatures]) -> float:
        """Returns tempo as 0–1 (max 300 BPM)."""
        if genome is None:
            return 0.5
        t = genome.tempo or 150.0
        return min(t / 300.0, 1.0)

    @classmethod
    def _score_openness(cls, genome: Optional[GenomeFeatures], archetype: str) -> float:
        """
        Openness = how varied and cross-genre the genome is.
        High instrumentalness + low speechiness + varied acousticness → open.
        Explorer / futurist archetypes add a bonus.
        """
        instr  = cls._feat(genome, "instrumentalness")
        speech = cls._feat(genome, "speechiness")
        acous  = cls._feat(genome, "acousticness")
        base   = (instr * 0.4 + (1 - speech) * 0.3 + (0.5 - abs(acous - 0.5)) * 0.3)
        bonus  = 0.15 if archetype in ("explorer", "futurist", "rebel") else 0.0
        return round(min((base + bonus) * 100, 100.0), 2)

    @classmethod
    def _score_depth(cls, genome: Optional[GenomeFeatures], snap_count: int, archetype: str) -> float:
        """
        Depth = richness of engagement over time.
        Snapshot count + instrumentalness + archetype devotion.
        """
        instr     = cls._feat(genome, "instrumentalness")
        snap_norm = min(snap_count / 100.0, 1.0)
        base      = (instr * 0.3 + snap_norm * 0.5 + 0.2)
        bonus     = 0.15 if archetype in ("devotee", "nostalgist", "analyst") else 0.0
        return round(min((base + bonus) * 100, 100.0), 2)

    @classmethod
    def _score_energy(cls, genome: Optional[GenomeFeatures]) -> float:
        energy  = cls._feat(genome, "energy")
        dance   = cls._feat(genome, "danceability")
        tempo_n = cls._tempo_normalised(genome)
        return round(((energy * 0.5 + dance * 0.3 + tempo_n * 0.2)) * 100, 2)

    @classmethod
    def _score_valence(cls, genome: Optional[GenomeFeatures]) -> float:
        return round(cls._feat(genome, "valence") * 100, 2)

    @classmethod
    def _score_complexity(cls, genome: Optional[GenomeFeatures], archetype: str) -> float:
        """
        Complexity = mix of speech, instrumentation, and non-mainstream energy balance.
        """
        speech = cls._feat(genome, "speechiness")
        instr  = cls._feat(genome, "instrumentalness")
        energy = cls._feat(genome, "energy")
        # Complex profiles balance these rather than maximising any one
        balance = 1.0 - abs(speech - instr) - abs(energy - 0.5) * 0.3
        bonus   = 0.1 if archetype in ("analyst", "curator", "futurist") else 0.0
        return round(min(max(balance + bonus, 0.0), 1.0) * 100, 2)

    @classmethod
    def _build_identity_statement(
        cls,
        archetype: str,
        shadow: str,
        genome: Optional[GenomeFeatures],
        scores: NarrativeScores,
        username: str,
    ) -> str:
        kb       = ARCHETYPE_KB.get(archetype, ARCHETYPE_KB["unknown"])
        shad_kb  = ARCHETYPE_KB.get(shadow, ARCHETYPE_KB["unknown"])
        energy   = cls._feat(genome, "energy")
        valence  = cls._feat(genome, "valence")
        acous    = cls._feat(genome, "acousticness")

        # Tone words derived from actual feature values
        energy_word  = "high-energy" if energy > 0.65 else ("low-key" if energy < 0.4 else "mid-intensity")
        mood_word    = "uplifting" if valence > 0.65 else ("melancholic" if valence < 0.4 else "emotionally balanced")
        texture_word = "acoustic-leaning" if acous > 0.6 else ("electronically-charged" if acous < 0.3 else "texturally varied")

        return (
            f"{username} listens with the instinct of a {archetype}, driven by {kb['core_drive']}. "
            f"Their genome is {energy_word}, {mood_word}, and {texture_word} — "
            f"a profile that reflects a listener who {kb['music_relationship'].lower()}. "
            f"Beneath the surface, the shadow of the {shadow} adds {shad_kb['core_drive']}, "
            f"creating a tension that makes their taste harder to predict than it first appears."
        )

    @classmethod
    def _build_hidden_trait(cls, shadow: str, archetype: str, genome: Optional[GenomeFeatures]) -> str:
        mod     = SHADOW_MODIFIERS.get(shadow, SHADOW_MODIFIERS["unknown"])
        instr   = cls._feat(genome, "instrumentalness")
        speech  = cls._feat(genome, "speechiness")

        lyric_note = (
            "Despite high instrumentalness in the genome, "
            if instr > 0.6
            else "Despite a leaning toward vocal-driven music, "
            if speech > 0.5
            else "Alongside a balanced feature profile, "
        )

        return (
            f"{lyric_note}{mod['hidden_trait']}. "
            f"{mod['modifier'].capitalize()}."
        )

    @classmethod
    def _build_emotional_pattern(
        cls,
        archetype: str,
        valence: float,
        energy: float,
    ) -> str:
        kb       = ARCHETYPE_KB.get(archetype, ARCHETYPE_KB["unknown"])
        base     = kb["emotional_pattern"]

        if valence > 0.7 and energy > 0.7:
            context = "The genome confirms this — high valence and energy together suggest emotional expression is outward and often celebratory."
        elif valence < 0.35 and energy > 0.6:
            context = "The genome shows high energy with low valence — this listener processes difficult emotions actively, not passively."
        elif valence < 0.35 and energy < 0.4:
            context = "Low energy and low valence in the genome point to introspective emotional processing — music as private space."
        elif valence > 0.6 and energy < 0.4:
            context = "High valence with low energy suggests quiet contentment — music chosen for warmth rather than stimulation."
        else:
            context = "The genome sits in a middle register emotionally — adaptable rather than extreme."

        return f"{base.capitalize()}. {context}"

    @classmethod
    def _build_evolution_rate(cls, evo: Optional[EvolutionSummary]) -> Optional[float]:
        if evo is None or evo.snapshot_count < 2:
            return None
        # Rate = archetype changes per 10 snapshots (normalised to 0–100)
        rate = (evo.archetype_changes / max(evo.snapshot_count, 1)) * 10
        return round(min(rate * 100, 100.0), 2)

    @classmethod
    def build(
        cls,
        username: str,
        archetype: str,
        shadow: str,
        genome: Optional[GenomeFeatures],
        evolution: Optional[EvolutionSummary],
        snap_count: int,
    ) -> Dict[str, Any]:
        arch  = archetype.lower() if archetype else "unknown"
        shad  = shadow.lower()    if shadow    else "unknown"
        kb    = ARCHETYPE_KB.get(arch, ARCHETYPE_KB["unknown"])

        energy  = cls._feat(genome, "energy")
        valence = cls._feat(genome, "valence")

        scores = NarrativeScores(
            openness_score   = cls._score_openness(genome, arch),
            depth_score      = cls._score_depth(genome, snap_count, arch),
            energy_score     = cls._score_energy(genome),
            valence_score    = cls._score_valence(genome),
            complexity_score = cls._score_complexity(genome, arch),
            evolution_rate   = cls._build_evolution_rate(evolution),
        )

        identity_statement  = cls._build_identity_statement(arch, shad, genome, scores, username)
        hidden_trait        = cls._build_hidden_trait(shad, arch, genome)
        emotional_pattern   = cls._build_emotional_pattern(arch, valence, energy)
        strength            = kb["strength"]
        blind_spot          = kb["blind_spot"]
        growth_direction    = kb["growth_direction"]
        music_relationship  = kb["music_relationship"]

        return {
            "identity_statement":  identity_statement,
            "hidden_trait":        hidden_trait,
            "emotional_pattern":   emotional_pattern,
            "strength":            strength,
            "blind_spot":          blind_spot,
            "growth_direction":    growth_direction,
            "music_relationship":  music_relationship,
            "scores":              scores,
        }


# ---------------------------------------------------------------------------
# LLM Integration Layer (optional)
# ---------------------------------------------------------------------------

class LLMNarrativeLayer:
    """
    Wraps the deterministic engine output in an LLM call to produce richer,
    more personalised prose.

    The deterministic reading is passed as structured context — the LLM
    refines the language, not the logic.  This ensures LLM output remains
    grounded in real user data.

    Falls back silently to deterministic output on any error.
    """

    SYSTEM_PROMPT = (
        "You are the identity narrative engine for SonicDNA, a music genome platform. "
        "You receive structured data about a listener's musical identity and rewrite "
        "each field in vivid, specific, second-person prose. "
        "You must not invent facts — only rephrase what the data says. "
        "Keep each field to 1–3 sentences. Return only valid JSON with the same keys."
    )

    @classmethod
    async def enhance(
        cls,
        deterministic: Dict[str, Any],
        archetype: str,
        shadow: str,
        username: str,
        genome: Optional[GenomeFeatures],
    ) -> Dict[str, Any]:
        if not LLM_ENABLED:
            return deterministic

        try:
            prompt = cls._build_prompt(deterministic, archetype, shadow, username, genome)
            raw    = await cls._call_llm(prompt)
            parsed = cls._parse_response(raw)
            # Merge — only replace narrative fields, never scores
            for field in [
                "identity_statement", "hidden_trait", "emotional_pattern",
                "strength", "blind_spot", "growth_direction",
                "music_relationship",
            ]:
                if field in parsed and isinstance(parsed[field], str) and len(parsed[field]) > 20:
                    deterministic[field] = parsed[field]
            deterministic["generated_by"] = f"llm_{LLM_PROVIDER}"
        except Exception:
            # Never raise — degrade to deterministic silently
            pass

        return deterministic

    @classmethod
    def _build_prompt(
        cls,
        data: Dict[str, Any],
        archetype: str,
        shadow: str,
        username: str,
        genome: Optional[GenomeFeatures],
    ) -> str:
        scores: NarrativeScores = data["scores"]
        genome_summary = ""
        if genome:
            genome_summary = (
                f"energy={genome.energy:.2f}, valence={genome.valence:.2f}, "
                f"acousticness={genome.acousticness:.2f}, "
                f"danceability={genome.danceability:.2f}, "
                f"instrumentalness={genome.instrumentalness:.2f}"
                if all(
                    v is not None
                    for v in [genome.energy, genome.valence, genome.acousticness,
                               genome.danceability, genome.instrumentalness]
                )
                else "genome features partially available"
            )

        return (
            f"Listener: {username}\n"
            f"Archetype: {archetype} | Shadow archetype: {shadow}\n"
            f"Genome: {genome_summary}\n"
            f"Scores: openness={scores.openness_score}, depth={scores.depth_score}, "
            f"energy={scores.energy_score}, valence={scores.valence_score}, "
            f"complexity={scores.complexity_score}\n\n"
            f"Current deterministic narrative:\n"
            + "\n".join(f"{k}: {v}" for k, v in data.items() if isinstance(v, str))
            + "\n\nRewrite each narrative field in vivid second-person prose. "
              "Return JSON with keys: identity_statement, hidden_trait, emotional_pattern, "
              "strength, blind_spot, growth_direction, music_relationship."
        )

    @classmethod
    async def _call_llm(cls, prompt: str) -> str:
        """
        Calls the configured LLM provider.
        Extend this method to add streaming, retries, or model selection.
        """
        import httpx

        if LLM_PROVIDER == "anthropic":
            api_key = os.getenv("ANTHROPIC_API_KEY", "")
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key":         api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type":      "application/json",
                    },
                    json={
                        "model":      "claude-sonnet-4-6",
                        "max_tokens": 1024,
                        "system":     cls.SYSTEM_PROMPT,
                        "messages":   [{"role": "user", "content": prompt}],
                    },
                )
                resp.raise_for_status()
                return resp.json()["content"][0]["text"]

        elif LLM_PROVIDER == "openai":
            api_key = os.getenv("OPENAI_API_KEY", "")
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type":  "application/json",
                    },
                    json={
                        "model":    "gpt-4o",
                        "messages": [
                            {"role": "system", "content": cls.SYSTEM_PROMPT},
                            {"role": "user",   "content": prompt},
                        ],
                    },
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]

        raise ValueError(f"Unknown LLM provider: {LLM_PROVIDER}")

    @staticmethod
    def _parse_response(raw: str) -> Dict[str, str]:
        import json, re
        cleaned = re.sub(r"^```json\s*|```$", "", raw.strip(), flags=re.MULTILINE)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {}


# ---------------------------------------------------------------------------
# Compatibility Narrative Engine
# ---------------------------------------------------------------------------

class CompatibilityNarrativeEngine:

    @staticmethod
    def _cosine(a: List[float], b: List[float]) -> float:
        if not a or not b:
            return 0.5
        min_len = min(len(a), len(b))
        a, b    = a[:min_len], b[:min_len]
        dot     = sum(x * y for x, y in zip(a, b))
        na      = math.sqrt(sum(x * x for x in a))
        nb      = math.sqrt(sum(y * y for y in b))
        if na == 0 or nb == 0:
            return 0.5
        return (dot / (na * nb) + 1.0) / 2.0

    @classmethod
    def build(
        cls,
        user_a: User,
        user_b: User,
        genome_a: Optional[GenomeFeatures],
        genome_b: Optional[GenomeFeatures],
        precomputed_genome_score: Optional[float],
    ) -> Dict[str, Any]:
        arch_a = (user_a.archetype        or "unknown").lower()
        arch_b = (user_b.archetype        or "unknown").lower()
        shad_a = (user_a.shadow_archetype or "unknown").lower()
        shad_b = (user_b.shadow_archetype or "unknown").lower()

        kb_a = ARCHETYPE_KB.get(arch_a, ARCHETYPE_KB["unknown"])
        kb_b = ARCHETYPE_KB.get(arch_b, ARCHETYPE_KB["unknown"])

        # --- Scores ---
        g_score = precomputed_genome_score
        if g_score is None and genome_a and genome_b and genome_a.genome_vector and genome_b.genome_vector:
            g_score = cls._cosine(genome_a.genome_vector, genome_b.genome_vector)
        g_score = g_score or 0.5

        a_score   = _archetype_affinity(arch_a, arch_b)
        # Tension: productive difference between shadow and primary
        t_score   = _archetype_affinity(shad_a, arch_b) * 0.5 + _archetype_affinity(shad_b, arch_a) * 0.5
        overall   = round((g_score * 0.50 + a_score * 0.35 + t_score * 0.15) * 100, 2)

        # --- Shared traits ---
        shared: List[str] = []
        if arch_a == arch_b:
            shared.append(f"You are both {arch_a}s — you'll recognise each other's obsessions instantly.")
        if abs((genome_a.energy or 0.5) - (genome_b.energy or 0.5)) < 0.15:
            shared.append("Your energy levels are closely matched — you'll agree on when to turn it up and when to scale back.")
        if abs((genome_a.valence or 0.5) - (genome_b.valence or 0.5)) < 0.15:
            shared.append("You share a similar emotional register — the same songs will likely hit you both.")
        if not shared:
            shared.append("Your differences are more prominent than your overlaps — which is where the interest lies.")

        # --- Tension points ---
        tensions: List[str] = []
        if abs((genome_a.energy or 0.5) - (genome_b.energy or 0.5)) > 0.35:
            tensions.append("One of you reaches for intensity while the other seeks restraint — a recurring negotiation in shared listening.")
        if arch_a != arch_b and a_score < 0.6:
            tensions.append(
                f"The {arch_a}'s {kb_a['core_drive']} can feel foreign to the {arch_b}, whose drive is {kb_b['core_drive']}."
            )
        if shad_a == arch_b or shad_b == arch_a:
            tensions.append(
                "One person's primary identity is the other's shadow — you'll push each other into uncomfortable territory."
            )
        if not tensions:
            tensions.append("Your compatibility is high enough that friction will be rare — which brings its own challenge.")

        # --- Narrative ---
        score_label = (
            "exceptionally high" if overall >= 82
            else "strong" if overall >= 65
            else "moderate" if overall >= 45
            else "challenging but interesting"
        )
        _genome_sim_label = "close enough that you'll often want the same song" if g_score > 0.65 else "different enough that you'll expand each other"
        narrative = (
            f"The compatibility between {user_a.username} ({arch_a}) and "
            f"{user_b.username} ({arch_b}) is {score_label} at {overall:.0f}/100. "
            f"Genome similarity runs at {g_score * 100:.0f}% \u2014 "
            f"{_genome_sim_label}. "
            f"Archetypally, {arch_a} and {arch_b} share an affinity of {a_score * 100:.0f}% \u2014 "
            f"{'a natural alignment of listening instincts' if a_score > 0.7 else 'a relationship that requires more active bridging'}."
        )


        growth_together = (
            f"Your shadows ({shad_a} and {shad_b}) represent what each of you suppresses. "
            f"In a shared listening context, leaning into those shadow qualities — rather than defaulting to primary instincts — "
            f"is where the most unexpected discoveries will come from."
        )

        chemistry_words = {
            (True, True):   "High energy, high mood — your shared sessions will feel like acceleration.",
            (True, False):  "Your energy aligns but your emotional tones diverge — expect productive argument.",
            (False, True):  "You agree on mood but not intensity — a tension that generates interesting middle ground.",
            (False, False): "Low energy, introspective mood — your shared listening will be slow-burning and deep.",
        }
        energy_aligned  = abs((genome_a.energy  or 0.5) - (genome_b.energy  or 0.5)) < 0.25
        valence_aligned = abs((genome_a.valence or 0.5) - (genome_b.valence or 0.5)) < 0.25
        listening_chemistry = chemistry_words.get((energy_aligned, valence_aligned), "Complex chemistry — hard to predict, worth discovering.")

        return {
            "overall_score":       overall,
            "genome_score":        round(g_score * 100, 2),
            "archetype_score":     round(a_score * 100, 2),
            "tension_score":       round(t_score * 100, 2),
            "narrative":           narrative,
            "shared_traits":       shared,
            "tension_points":      tensions,
            "growth_together":     growth_together,
            "listening_chemistry": listening_chemistry,
        }


# ---------------------------------------------------------------------------
# Service Layer
# ---------------------------------------------------------------------------

class IdentityNarrativeService:

    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_user_or_404(self, user_id: int) -> User:
        user = self.db.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail=f"User {user_id} not found.")
        return user

    @staticmethod
    def _input_hash(
        archetype: str,
        shadow: str,
        genome: Optional[GenomeFeatures],
        snap_count: int,
    ) -> str:
        parts = [archetype, shadow, str(snap_count)]
        if genome:
            parts += [
                str(round(genome.energy           or 0, 4)),
                str(round(genome.valence          or 0, 4)),
                str(round(genome.acousticness     or 0, 4)),
                str(round(genome.danceability     or 0, 4)),
                str(round(genome.instrumentalness or 0, 4)),
            ]
        raw = "|".join(parts)
        return hashlib.sha256(raw.encode()).hexdigest()

    def _latest_reading(self, user_id: int) -> Optional[IdentityReading]:
        return (
            self.db.query(IdentityReading)
            .filter(IdentityReading.user_id == user_id)
            .order_by(desc(IdentityReading.version))
            .first()
        )

    def _next_version(self, user_id: int) -> int:
        latest = self._latest_reading(user_id)
        return (latest.version + 1) if latest else 1

    def _reading_to_out(self, reading: IdentityReading) -> IdentityReadingOut:
        scores = NarrativeScores(
            openness_score   = reading.openness_score,
            depth_score      = reading.depth_score,
            energy_score     = reading.energy_score,
            valence_score    = reading.valence_score,
            complexity_score = reading.complexity_score,
            evolution_rate   = reading.evolution_rate,
        )
        out = IdentityReadingOut.model_validate(reading)
        out.scores = scores
        return out

    def _resolve_inputs(self, user: User, req: GenerateIdentityRequest):
        """Merge request overrides with user model defaults."""
        archetype = (req.archetype or user.archetype or "unknown").lower()
        shadow    = (req.shadow_archetype or user.shadow_archetype or "unknown").lower()
        genome    = req.genome

        # If no genome passed, try to read latest snapshot
        if genome is None:
            genome = self._genome_from_latest_snapshot(user.id)

        evolution  = req.evolution
        snap_count = evolution.snapshot_count if evolution else self._snapshot_count(user.id)
        return archetype, shadow, genome, evolution, snap_count

    def _genome_from_latest_snapshot(self, user_id: int) -> Optional[GenomeFeatures]:
        """Reads the most recent genome snapshot if the table exists."""
        try:
            from sqlalchemy import text
            row = self.db.execute(
                text(
                    "SELECT danceability, energy, valence, acousticness, "
                    "instrumentalness, speechiness, tempo "
                    "FROM genome_snapshots WHERE user_id = :uid "
                    "ORDER BY timestamp DESC LIMIT 1"
                ),
                {"uid": user_id},
            ).fetchone()
            if row:
                return GenomeFeatures(
                    danceability     = row[0],
                    energy           = row[1],
                    valence          = row[2],
                    acousticness     = row[3],
                    instrumentalness = row[4],
                    speechiness      = row[5],
                    tempo            = row[6],
                )
        except Exception:
            pass
        return None

    def _snapshot_count(self, user_id: int) -> int:
        try:
            from sqlalchemy import text
            result = self.db.execute(
                text("SELECT COUNT(*) FROM genome_snapshots WHERE user_id = :uid"),
                {"uid": user_id},
            ).scalar()
            return int(result or 0)
        except Exception:
            return 0

    def _evolution_from_db(self, user_id: int) -> Optional[EvolutionSummary]:
        try:
            from sqlalchemy import text
            rows = self.db.execute(
                text(
                    "SELECT archetype, energy, valence "
                    "FROM genome_snapshots WHERE user_id = :uid "
                    "ORDER BY timestamp ASC"
                ),
                {"uid": user_id},
            ).fetchall()
            if not rows:
                return None
            archetype_changes = sum(
                1 for i in range(1, len(rows)) if rows[i][0] != rows[i - 1][0]
            )
            energy_delta = (
                round((rows[-1][1] or 0) - (rows[0][1] or 0), 4)
                if rows[0][1] is not None and rows[-1][1] is not None
                else None
            )
            valence_delta = (
                round((rows[-1][2] or 0) - (rows[0][2] or 0), 4)
                if rows[0][2] is not None and rows[-1][2] is not None
                else None
            )
            return EvolutionSummary(
                snapshot_count     = len(rows),
                archetype_changes  = archetype_changes,
                dominant_archetype = rows[-1][0],
                energy_delta       = energy_delta,
                valence_delta      = valence_delta,
            )
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def generate(self, req: GenerateIdentityRequest) -> IdentityReadingOut:
        user = self._get_user_or_404(req.user_id)
        archetype, shadow, genome, evolution, snap_count = self._resolve_inputs(user, req)

        input_hash = self._input_hash(archetype, shadow, genome, snap_count)

        # Cache hit — return existing reading unless forced
        if not req.force_regenerate:
            latest = self._latest_reading(req.user_id)
            if latest and latest.input_hash == input_hash:
                return self._reading_to_out(latest)

        # Build deterministic narrative
        built = NarrativeEngine.build(
            username   = user.username,
            archetype  = archetype,
            shadow     = shadow,
            genome     = genome,
            evolution  = evolution,
            snap_count = snap_count,
        )
        generated_by = "deterministic"

        # LLM enhancement (async → sync wrapper; in production use background task)
        if req.use_llm and LLM_ENABLED:
            import asyncio
            try:
                loop   = asyncio.get_event_loop()
                built  = loop.run_until_complete(
                    LLMNarrativeLayer.enhance(built, archetype, shadow, user.username, genome)
                )
                generated_by = built.pop("generated_by", f"llm_{LLM_PROVIDER}")
            except Exception:
                pass

        scores: NarrativeScores = built.pop("scores")
        version = self._next_version(req.user_id)

        reading = IdentityReading(
            user_id              = req.user_id,
            version              = version,
            input_hash           = input_hash,
            identity_statement   = built["identity_statement"],
            hidden_trait         = built["hidden_trait"],
            emotional_pattern    = built["emotional_pattern"],
            strength             = built["strength"],
            blind_spot           = built["blind_spot"],
            growth_direction     = built["growth_direction"],
            music_relationship   = built["music_relationship"],
            openness_score       = scores.openness_score,
            depth_score          = scores.depth_score,
            energy_score         = scores.energy_score,
            valence_score        = scores.valence_score,
            complexity_score     = scores.complexity_score,
            evolution_rate       = scores.evolution_rate,
            generated_by         = generated_by,
            archetype_at_gen     = archetype,
            shadow_at_gen        = shadow,
            snapshot_count       = snap_count,
        )
        self.db.add(reading)
        self.db.commit()
        self.db.refresh(reading)
        return self._reading_to_out(reading)

    def get_latest(self, user_id: int) -> IdentityReadingOut:
        self._get_user_or_404(user_id)
        reading = self._latest_reading(user_id)
        if not reading:
            raise HTTPException(
                status_code=404,
                detail=f"No identity reading for user {user_id}. Call POST /identity/generate first.",
            )
        return self._reading_to_out(reading)

    def get_evolution_narrative(self, user_id: int) -> EvolutionNarrativeOut:
        user = self._get_user_or_404(user_id)
        evo  = self._evolution_from_db(user_id)

        if evo is None or evo.snapshot_count == 0:
            return EvolutionNarrativeOut(
                user_id             = user_id,
                snapshot_count      = 0,
                archetype_journey   = [],
                evolution_statement = "Not enough history yet. Your genome will tell a richer story over time.",
                momentum            = "dormant",
                energy_arc          = "no data",
                valence_arc         = "no data",
                pivot_moments       = [],
                current_reading     = None,
            )

        # Archetype journey
        try:
            from sqlalchemy import text
            arch_rows = self.db.execute(
                text(
                    "SELECT archetype, timestamp FROM genome_snapshots "
                    "WHERE user_id = :uid ORDER BY timestamp ASC"
                ),
                {"uid": user_id},
            ).fetchall()
            journey = []
            prev = None
            pivot_moments = []
            for row in arch_rows:
                if row[0] != prev:
                    journey.append(row[0] or "unknown")
                    if prev is not None:
                        pivot_moments.append({
                            "from":      prev,
                            "to":        row[0],
                            "timestamp": row[1].isoformat() if row[1] else None,
                            "type":      "archetype_shift",
                        })
                    prev = row[0]
        except Exception:
            journey       = [user.archetype or "unknown"]
            pivot_moments = []

        # Momentum
        if evo.archetype_changes == 0:
            momentum = "stable"
        elif evo.archetype_changes >= 3:
            momentum = "shifting"
        elif evo.snapshot_count > 20:
            momentum = "accelerating"
        else:
            momentum = "evolving"

        # Energy arc
        ed = evo.energy_delta
        if ed is None:
            energy_arc = "insufficient data"
        elif ed > 0.15:
            energy_arc = f"trending upward (+{ed:.2f}) — your listening has grown more intense over time"
        elif ed < -0.15:
            energy_arc = f"trending downward ({ed:.2f}) — your listening has become more restrained and inward"
        else:
            energy_arc = f"stable (Δ{ed:.2f}) — your energy profile has remained consistent"

        # Valence arc
        vd = evo.valence_delta
        if vd is None:
            valence_arc = "insufficient data"
        elif vd > 0.15:
            valence_arc = f"brightening (+{vd:.2f}) — emotionally, your listening has moved toward the light"
        elif vd < -0.15:
            valence_arc = f"darkening ({vd:.2f}) — your emotional palette has shifted toward shadow"
        else:
            valence_arc = f"level (Δ{vd:.2f}) — your emotional register has stayed consistent"

        arch_count = evo.archetype_changes
        _arch_stable_str = "remained stable" if arch_count == 0 else f"shifted {arch_count} time{'s' if arch_count != 1 else ''}"
        evolution_statement = (
            f"Across {evo.snapshot_count} genome snapshots, "
            f"{user.username}'s identity has {_arch_stable_str}. "
            f"The energy arc is {energy_arc.split(' \u2014 ')[0]}, and the emotional tone is {valence_arc.split(' \u2014 ')[0]}. "
            f"{'The genome is still settling \u2014 the most interesting chapters are ahead.' if evo.snapshot_count < 10 else 'The pattern is clear enough to read with confidence.'}"
        )


        current = self._latest_reading(user_id)

        return EvolutionNarrativeOut(
            user_id             = user_id,
            snapshot_count      = evo.snapshot_count,
            archetype_journey   = journey,
            evolution_statement = evolution_statement,
            momentum            = momentum,
            energy_arc          = energy_arc,
            valence_arc         = valence_arc,
            pivot_moments       = pivot_moments,
            current_reading     = self._reading_to_out(current) if current else None,
        )

    def get_compatibility(
        self,
        comparison_id: str,
        req: Optional[GenerateCompatibilityRequest] = None,
    ) -> CompatibilityReadingOut:
        # Try cached
        existing = (
            self.db.query(CompatibilityReading)
            .filter(CompatibilityReading.comparison_id == comparison_id)
            .first()
        )
        if existing and (req is None or not req.force_regenerate):
            return CompatibilityReadingOut.model_validate(existing)

        if req is None:
            raise HTTPException(status_code=404, detail="Compatibility reading not found.")

        # Build canonical pair ordering
        uid_lo, uid_hi = (
            (req.user_a_id, req.user_b_id)
            if req.user_a_id < req.user_b_id
            else (req.user_b_id, req.user_a_id)
        )
        user_a = self._get_user_or_404(uid_lo)
        user_b = self._get_user_or_404(uid_hi)

        genome_a = self._genome_from_latest_snapshot(user_a.id)
        genome_b = self._genome_from_latest_snapshot(user_b.id)

        built = CompatibilityNarrativeEngine.build(
            user_a                   = user_a,
            user_b                   = user_b,
            genome_a                 = genome_a,
            genome_b                 = genome_b,
            precomputed_genome_score = req.genome_score,
        )

        if existing:
            for k, v in built.items():
                setattr(existing, k, v)
            existing.generated_by = "deterministic"
            self.db.commit()
            self.db.refresh(existing)
            return CompatibilityReadingOut.model_validate(existing)

        record = CompatibilityReading(
            user_a_id       = uid_lo,
            user_b_id       = uid_hi,
            comparison_id   = comparison_id,
            generated_by    = "deterministic",
            **built,
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return CompatibilityReadingOut.model_validate(record)


# ---------------------------------------------------------------------------
# FastAPI Router
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/identity",
    tags=["Identity Narratives"],
    responses={
        404: {"description": "Resource not found"},
        422: {"description": "Validation error"},
        500: {"description": "Internal server error"},
    },
)


@router.post(
    "/generate",
    response_model=IdentityReadingOut,
    status_code=status.HTTP_200_OK,
    summary="Generate a personalized identity reading",
    description=(
        "Generates a full identity narrative from genome data and archetype. "
        "Returns cached reading if inputs haven't changed (bypass with force_regenerate=true). "
        "Optionally routes through LLM enhancement when use_llm=true and LLM_NARRATIVE_ENABLED=true."
    ),
)
def generate_identity(
    req: GenerateIdentityRequest,
    db: Session = Depends(get_db),
) -> IdentityReadingOut:
    return IdentityNarrativeService(db).generate(req)


@router.get(
    "/{user_id}",
    response_model=IdentityReadingOut,
    summary="Get the latest identity reading for a user",
    description="Returns the most recently generated identity reading. Call POST /identity/generate first.",
)
def get_identity(
    user_id: int,
    db: Session = Depends(get_db),
) -> IdentityReadingOut:
    return IdentityNarrativeService(db).get_latest(user_id)


@router.get(
    "/evolution/{user_id}",
    response_model=EvolutionNarrativeOut,
    summary="Get the evolution narrative for a user",
    description=(
        "Returns a chronological narrative of the user's musical identity evolution: "
        "archetype journey, energy and valence arcs, pivot moments, and momentum label."
    ),
)
def get_evolution_narrative(
    user_id: int,
    db: Session = Depends(get_db),
) -> EvolutionNarrativeOut:
    return IdentityNarrativeService(db).get_evolution_narrative(user_id)


@router.get(
    "/compatibility/{comparison_id}",
    response_model=CompatibilityReadingOut,
    summary="Get a cached compatibility reading",
    description="Retrieves a previously generated compatibility reading by comparison_id.",
)
def get_compatibility(
    comparison_id: str,
    db: Session = Depends(get_db),
) -> CompatibilityReadingOut:
    return IdentityNarrativeService(db).get_compatibility(comparison_id)


@router.post(
    "/compatibility/generate",
    response_model=CompatibilityReadingOut,
    status_code=status.HTTP_200_OK,
    summary="Generate a compatibility narrative for two users",
    description=(
        "Generates a full compatibility reading for a user pair — genome similarity, "
        "archetype affinity, tension score, shared traits, and narrative. "
        "comparison_id must be provided by the caller (e.g. 'user_3_vs_7')."
    ),
)
def generate_compatibility(
    comparison_id: str = Query(..., description="Stable identifier for this user pair."),
    req: GenerateCompatibilityRequest = ...,
    db: Session = Depends(get_db),
) -> CompatibilityReadingOut:
    return IdentityNarrativeService(db).get_compatibility(comparison_id, req)


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------

def include_router(app: Any) -> None:
    """
    from identity_narratives import include_router
    include_router(app)
    """
    app.include_router(router)
