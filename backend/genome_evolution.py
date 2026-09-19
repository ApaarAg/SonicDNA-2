"""
genome_evolution.py
===================
SonicDNA — Genome Evolution Module

Powers the "Evolution" section of SonicDNA.
Stores versioned genome snapshots for every user and exposes endpoints
for history retrieval, timeline charting, and trend analysis.

Assumptions about the existing SonicDNA codebase
-------------------------------------------------
* A shared SQLAlchemy `Base`, `SessionLocal`, and `get_db` already exist
  (imported from `app.database`).
* A `User` ORM model already exists with at least:
    - id            : int (primary key)
    - username      : str
    - archetype     : str
    - shadow_archetype : str
* Environment variable DATABASE_URL is already configured.

New database objects introduced here
--------------------------------------
* GenomeSnapshot  — one row per point-in-time genome reading for a user
"""

from __future__ import annotations

import os
import statistics
import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator, model_validator
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
    func,
    asc,
    desc,
)
from sqlalchemy.orm import Session, relationship

# ---------------------------------------------------------------------------
# Shared database objects  (adjust import path to match your project layout)
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
        id = Column(Integer, primary_key=True, index=True)
        username = Column(String(120), unique=True, nullable=False)
        archetype = Column(String(80), nullable=True)
        shadow_archetype = Column(String(80), nullable=True)


USER_ID_TYPE = User.id.type


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Audio feature bounds (Spotify / SonicDNA scale)
FEATURE_BOUNDS: Dict[str, Tuple[float, float]] = {
    "danceability":      (0.0, 1.0),
    "energy":            (0.0, 1.0),
    "valence":           (0.0, 1.0),
    "acousticness":      (0.0, 1.0),
    "instrumentalness":  (0.0, 1.0),
    "speechiness":       (0.0, 1.0),
    "tempo":             (0.0, 300.0),
}

AUDIO_FEATURES = list(FEATURE_BOUNDS.keys())

# Minimum snapshots required before trend analysis is meaningful
MIN_SNAPSHOTS_FOR_TRENDS = 2

# Max snapshots returned without pagination (safety cap)
MAX_HISTORY_LIMIT = 10_000


# ---------------------------------------------------------------------------
# ORM Models
# ---------------------------------------------------------------------------

class GenomeSnapshot(Base):
    """
    Historical record of a user's genome at a point in time.

    One row is written every time SonicDNA recalculates the user's genome
    (e.g. after each listening session, daily batch job, or manual trigger).
    Rows are never updated — they are immutable historical records.
    """
    __tablename__ = "genome_snapshots"
    __table_args__ = {"extend_existing": True}

    id = Column(USER_ID_TYPE, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(
        USER_ID_TYPE,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    timestamp = Column(
        "taken_at",
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    # Archetype state at snapshot time
    archetype = Column("archetype_name", String(80), nullable=True)
    shadow_archetype = Column("secondary_name", String(80), nullable=True)

    # Store other features in the single 'genome' JSON string column
    genome_data = Column("genome", Text, nullable=True)

    user = relationship("User", foreign_keys=[user_id])

    # Transparently map audio features to the JSON string
    @property
    def genome_json(self):
        if not hasattr(self, "_parsed_genome"):
            if self.genome_data:
                try:
                    self._parsed_genome = json.loads(self.genome_data)
                except Exception:
                    self._parsed_genome = {}
            else:
                self._parsed_genome = {}
        return self._parsed_genome

    def _set_feature(self, key, value):
        js = self.genome_json
        js[key] = value
        self.genome_data = json.dumps(js)

    @property
    def danceability(self):
        return self.genome_json.get("danceability")
    
    @danceability.setter
    def danceability(self, value):
        self._set_feature("danceability", value)

    @property
    def energy(self):
        return self.genome_json.get("energy")
    
    @energy.setter
    def energy(self, value):
        self._set_feature("energy", value)

    @property
    def valence(self):
        return self.genome_json.get("valence")
    
    @valence.setter
    def valence(self, value):
        self._set_feature("valence", value)

    @property
    def acousticness(self):
        return self.genome_json.get("acousticness")
    
    @acousticness.setter
    def acousticness(self, value):
        self._set_feature("acousticness", value)

    @property
    def instrumentalness(self):
        return self.genome_json.get("instrumentalness")
    
    @instrumentalness.setter
    def instrumentalness(self, value):
        self._set_feature("instrumentalness", value)

    @property
    def speechiness(self):
        return self.genome_json.get("speechiness")
    
    @speechiness.setter
    def speechiness(self, value):
        self._set_feature("speechiness", value)

    @property
    def tempo(self):
        return self.genome_json.get("tempo")
    
    @tempo.setter
    def tempo(self, value):
        self._set_feature("tempo", value)


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------

class AudioFeatures(BaseModel):
    danceability:     Optional[float] = Field(None, ge=0.0, le=1.0)
    energy:           Optional[float] = Field(None, ge=0.0, le=1.0)
    valence:          Optional[float] = Field(None, ge=0.0, le=1.0)
    acousticness:     Optional[float] = Field(None, ge=0.0, le=1.0)
    instrumentalness: Optional[float] = Field(None, ge=0.0, le=1.0)
    speechiness:      Optional[float] = Field(None, ge=0.0, le=1.0)
    tempo:            Optional[float] = Field(None, ge=0.0, le=300.0)


# --- Request ---

class SnapshotCreate(AudioFeatures):
    """Payload for POST /evolution/snapshot"""
    user_id:          int
    archetype:        Optional[str] = None
    shadow_archetype: Optional[str] = None
    timestamp:        Optional[datetime] = Field(
        None,
        description="Defaults to now (UTC) if omitted.",
    )

    @field_validator("timestamp", mode="before")
    @classmethod
    def default_timestamp(cls, v: Optional[datetime]) -> datetime:
        return v or datetime.now(timezone.utc)


# --- Response: single snapshot ---

class SnapshotOut(AudioFeatures):
    id:               int
    user_id:          int
    timestamp:        datetime
    archetype:        Optional[str] = None
    shadow_archetype: Optional[str] = None

    model_config = {"from_attributes": True}


# --- Response: history list ---

class HistoryResponse(BaseModel):
    user_id:   int
    count:     int
    snapshots: List[SnapshotOut]


# --- Response: timeline (chart-ready) ---

class TimelinePoint(BaseModel):
    """One data-point per snapshot, shaped for frontend charting libraries."""
    snapshot_id:      int
    timestamp:        datetime
    archetype:        Optional[str]
    shadow_archetype: Optional[str]
    danceability:     Optional[float]
    energy:           Optional[float]
    valence:          Optional[float]
    acousticness:     Optional[float]
    instrumentalness: Optional[float]
    speechiness:      Optional[float]
    tempo:            Optional[float]


class FeatureSeries(BaseModel):
    """Named series ready for a multi-line chart."""
    feature: str
    label:   str
    unit:    str
    data:    List[Dict[str, Any]]   # [{x: ISO timestamp, y: float}, ...]


class TimelineResponse(BaseModel):
    user_id:          int
    total_snapshots:  int
    date_range:       Dict[str, Optional[datetime]]   # {from, to}
    series:           List[FeatureSeries]
    archetype_bands:  List[Dict[str, Any]]            # archetype change annotations


# --- Response: trends ---

class FeatureTrend(BaseModel):
    feature:     str
    first_value: Optional[float]
    last_value:  Optional[float]
    delta:       Optional[float]
    pct_change:  Optional[float]
    direction:   str   # "increase" | "decrease" | "stable"


class ArchetypeTransition(BaseModel):
    from_archetype: Optional[str]
    to_archetype:   Optional[str]
    at:             datetime
    snapshot_id:    int


class TrendsResponse(BaseModel):
    user_id:              int
    snapshot_count:       int
    analysis_window:      Dict[str, Optional[datetime]]
    strongest_increase:   Optional[FeatureTrend]
    strongest_decrease:   Optional[FeatureTrend]
    stable_features:      List[str]
    archetype_changes:    List[ArchetypeTransition]
    shadow_changes:       List[ArchetypeTransition]
    evolution_summary:    str
    feature_trends:       List[FeatureTrend]


# ---------------------------------------------------------------------------
# Service Layer
# ---------------------------------------------------------------------------

class EvolutionService:
    """
    Business logic for genome evolution.
    All database access and computation live here, fully decoupled from HTTP.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_user_or_404(self, user_id: int) -> User:
        user = self.db.get(User, user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User {user_id} not found.",
            )
        return user

    def _snapshots_for_user(
        self,
        user_id: int,
        order: str = "asc",
        limit: Optional[int] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> List[GenomeSnapshot]:
        q = self.db.query(GenomeSnapshot).filter(
            GenomeSnapshot.user_id == user_id
        )
        if since:
            q = q.filter(GenomeSnapshot.timestamp >= since)
        if until:
            q = q.filter(GenomeSnapshot.timestamp <= until)

        q = q.order_by(
            asc(GenomeSnapshot.timestamp)
            if order == "asc"
            else desc(GenomeSnapshot.timestamp)
        )
        if limit:
            q = q.limit(limit)
        return q.all()

    @staticmethod
    def _feature_value(snap: GenomeSnapshot, feature: str) -> Optional[float]:
        return getattr(snap, feature, None)

    @staticmethod
    def _normalise_tempo(value: Optional[float]) -> Optional[float]:
        """Normalise tempo to [0, 1] for cross-feature comparisons."""
        if value is None:
            return None
        return round(value / 300.0, 6)

    @staticmethod
    def _compute_trend(
        feature: str,
        first: Optional[float],
        last: Optional[float],
    ) -> FeatureTrend:
        delta: Optional[float] = None
        pct: Optional[float] = None
        direction = "stable"

        if first is not None and last is not None:
            delta = round(last - first, 6)
            pct = round((delta / first) * 100, 2) if first != 0 else None
            if abs(delta) < 1e-4:
                direction = "stable"
            elif delta > 0:
                direction = "increase"
            else:
                direction = "decrease"

        return FeatureTrend(
            feature=feature,
            first_value=first,
            last_value=last,
            delta=delta,
            pct_change=pct,
            direction=direction,
        )

    @staticmethod
    def _build_evolution_summary(
        trends: List[FeatureTrend],
        archetype_changes: List[ArchetypeTransition],
        snapshot_count: int,
    ) -> str:
        if snapshot_count < MIN_SNAPSHOTS_FOR_TRENDS:
            return (
                "Not enough snapshots to summarise evolution yet. "
                "Keep listening — your genome will grow richer over time."
            )

        increases = [t for t in trends if t.direction == "increase" and t.delta]
        decreases = [t for t in trends if t.direction == "decrease" and t.delta]
        stables   = [t for t in trends if t.direction == "stable"]

        parts: List[str] = []

        if increases:
            top = max(increases, key=lambda t: abs(t.delta or 0))
            parts.append(
                f"Your {top.feature} has grown the most "
                f"(+{top.delta:.3f}{', ' + str(round(top.pct_change, 1)) + '%' if top.pct_change else ''})."
            )

        if decreases:
            top = min(decreases, key=lambda t: t.delta or 0)
            parts.append(
                f"Your {top.feature} has pulled back the most "
                f"({top.delta:.3f}{', ' + str(round(top.pct_change, 1)) + '%' if top.pct_change else ''})."
            )

        if stables:
            parts.append(
                f"{', '.join(t.feature for t in stables)} "
                f"{'remains' if len(stables) == 1 else 'remain'} consistent across your listening history."
            )

        if archetype_changes:
            parts.append(
                f"Your archetype has shifted {len(archetype_changes)} "
                f"time{'s' if len(archetype_changes) != 1 else ''} — "
                f"your musical identity is still evolving."
            )
        else:
            parts.append("Your archetype has remained stable throughout.")

        return " ".join(parts) if parts else "Your genome is evolving steadily."

    # ------------------------------------------------------------------
    # Public service methods
    # ------------------------------------------------------------------

    def create_snapshot(self, payload: SnapshotCreate) -> GenomeSnapshot:
        """Persist a new genome snapshot and return it."""
        self._get_user_or_404(payload.user_id)

        snap = GenomeSnapshot(
            user_id=payload.user_id,
            timestamp=payload.timestamp or datetime.now(timezone.utc),
            archetype=payload.archetype,
            shadow_archetype=payload.shadow_archetype,
            danceability=payload.danceability,
            energy=payload.energy,
            valence=payload.valence,
            acousticness=payload.acousticness,
            instrumentalness=payload.instrumentalness,
            speechiness=payload.speechiness,
            tempo=payload.tempo,
        )
        self.db.add(snap)
        self.db.commit()
        self.db.refresh(snap)
        return snap

    def get_history(
        self,
        user_id: int,
        limit: int = MAX_HISTORY_LIMIT,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> HistoryResponse:
        self._get_user_or_404(user_id)
        snaps = self._snapshots_for_user(
            user_id, order="asc", limit=limit, since=since, until=until
        )
        return HistoryResponse(
            user_id=user_id,
            count=len(snaps),
            snapshots=[SnapshotOut.model_validate(s) for s in snaps],
        )

    def get_latest(self, user_id: int) -> SnapshotOut:
        self._get_user_or_404(user_id)
        snap = (
            self.db.query(GenomeSnapshot)
            .filter(GenomeSnapshot.user_id == user_id)
            .order_by(desc(GenomeSnapshot.timestamp))
            .first()
        )
        if snap is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No snapshots found for user {user_id}.",
            )
        return SnapshotOut.model_validate(snap)

    def get_timeline(
        self,
        user_id: int,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        downsample: Optional[int] = None,
    ) -> TimelineResponse:
        """
        Returns chart-ready multi-series data.

        `downsample` thins the snapshot list to at most N evenly spaced points
        — useful for rendering performance when history is very long.
        """
        self._get_user_or_404(user_id)
        snaps = self._snapshots_for_user(
            user_id, order="asc", since=since, until=until
        )

        if not snaps:
            return TimelineResponse(
                user_id=user_id,
                total_snapshots=0,
                date_range={"from": None, "to": None},
                series=[],
                archetype_bands=[],
            )

        # Optional downsampling: pick indices evenly spaced across the list
        if downsample and len(snaps) > downsample:
            step = len(snaps) / downsample
            snaps = [snaps[int(i * step)] for i in range(downsample)]

        date_range = {
            "from": snaps[0].timestamp,
            "to":   snaps[-1].timestamp,
        }

        # Build one series per audio feature
        series: List[FeatureSeries] = []
        feature_meta = {
            "danceability":     ("Danceability",     "0–1"),
            "energy":           ("Energy",           "0–1"),
            "valence":          ("Valence",          "0–1"),
            "acousticness":     ("Acousticness",     "0–1"),
            "instrumentalness": ("Instrumentalness", "0–1"),
            "speechiness":      ("Speechiness",      "0–1"),
            "tempo":            ("Tempo",            "BPM"),
        }

        for feature, (label, unit) in feature_meta.items():
            data = [
                {
                    "x": s.timestamp.isoformat(),
                    "y": self._feature_value(s, feature),
                    "snapshot_id": s.id,
                }
                for s in snaps
                if self._feature_value(s, feature) is not None
            ]
            if data:
                series.append(
                    FeatureSeries(feature=feature, label=label, unit=unit, data=data)
                )

        # Archetype change bands — annotate spans where archetype was constant
        archetype_bands: List[Dict[str, Any]] = []
        if snaps:
            band_start = snaps[0]
            current_arch = snaps[0].archetype
            for snap in snaps[1:]:
                if snap.archetype != current_arch:
                    archetype_bands.append(
                        {
                            "archetype": current_arch,
                            "from":      band_start.timestamp.isoformat(),
                            "to":        snap.timestamp.isoformat(),
                        }
                    )
                    band_start = snap
                    current_arch = snap.archetype
            # Close the last band
            archetype_bands.append(
                {
                    "archetype": current_arch,
                    "from":      band_start.timestamp.isoformat(),
                    "to":        snaps[-1].timestamp.isoformat(),
                }
            )

        return TimelineResponse(
            user_id=user_id,
            total_snapshots=len(snaps),
            date_range=date_range,
            series=series,
            archetype_bands=archetype_bands,
        )

    def get_trends(
        self,
        user_id: int,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> TrendsResponse:
        """
        Computes directional trends across all audio features plus
        archetype / shadow-archetype transition history.
        """
        self._get_user_or_404(user_id)
        snaps = self._snapshots_for_user(
            user_id, order="asc", since=since, until=until
        )

        count = len(snaps)
        analysis_window = {
            "from": snaps[0].timestamp  if snaps else None,
            "to":   snaps[-1].timestamp if snaps else None,
        }

        if count < MIN_SNAPSHOTS_FOR_TRENDS:
            return TrendsResponse(
                user_id=user_id,
                snapshot_count=count,
                analysis_window=analysis_window,
                strongest_increase=None,
                strongest_decrease=None,
                stable_features=[],
                archetype_changes=[],
                shadow_changes=[],
                evolution_summary=(
                    "Not enough snapshot history yet. "
                    "At least 2 snapshots are needed for trend analysis."
                ),
                feature_trends=[],
            )

        first_snap = snaps[0]
        last_snap  = snaps[-1]

        # --- feature trends ---
        feature_trends: List[FeatureTrend] = []
        for feature in AUDIO_FEATURES:
            first_val = self._feature_value(first_snap, feature)
            last_val  = self._feature_value(last_snap, feature)
            feature_trends.append(
                self._compute_trend(feature, first_val, last_val)
            )

        increases = [t for t in feature_trends if t.direction == "increase" and t.delta is not None]
        decreases = [t for t in feature_trends if t.direction == "decrease" and t.delta is not None]
        stables   = [t.feature for t in feature_trends if t.direction == "stable"]

        strongest_increase: Optional[FeatureTrend] = (
            max(increases, key=lambda t: abs(t.delta or 0)) if increases else None
        )
        strongest_decrease: Optional[FeatureTrend] = (
            min(decreases, key=lambda t: t.delta or 0) if decreases else None
        )

        # --- archetype change log ---
        archetype_changes: List[ArchetypeTransition] = []
        shadow_changes:    List[ArchetypeTransition] = []
        prev_arch   = snaps[0].archetype
        prev_shadow = snaps[0].shadow_archetype

        for snap in snaps[1:]:
            if snap.archetype != prev_arch:
                archetype_changes.append(
                    ArchetypeTransition(
                        from_archetype=prev_arch,
                        to_archetype=snap.archetype,
                        at=snap.timestamp,
                        snapshot_id=snap.id,
                    )
                )
                prev_arch = snap.archetype

            if snap.shadow_archetype != prev_shadow:
                shadow_changes.append(
                    ArchetypeTransition(
                        from_archetype=prev_shadow,
                        to_archetype=snap.shadow_archetype,
                        at=snap.timestamp,
                        snapshot_id=snap.id,
                    )
                )
                prev_shadow = snap.shadow_archetype

        summary = self._build_evolution_summary(
            feature_trends, archetype_changes, count
        )

        return TrendsResponse(
            user_id=user_id,
            snapshot_count=count,
            analysis_window=analysis_window,
            strongest_increase=strongest_increase,
            strongest_decrease=strongest_decrease,
            stable_features=stables,
            archetype_changes=archetype_changes,
            shadow_changes=shadow_changes,
            evolution_summary=summary,
            feature_trends=feature_trends,
        )


# ---------------------------------------------------------------------------
# FastAPI Router
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/evolution",
    tags=["Genome Evolution"],
    responses={
        404: {"description": "Resource not found"},
        422: {"description": "Validation error"},
        500: {"description": "Internal server error"},
    },
)


@router.post(
    "/snapshot",
    response_model=SnapshotOut,
    status_code=status.HTTP_201_CREATED,
    summary="Store a genome snapshot",
    description=(
        "Persists a new immutable genome snapshot for the given user. "
        "Snapshots are never updated — each call appends a new record. "
        "Timestamp defaults to now (UTC) if not provided."
    ),
)
def create_snapshot(
    payload: SnapshotCreate,
    db: Session = Depends(get_db),
) -> SnapshotOut:
    service = EvolutionService(db)
    snap = service.create_snapshot(payload)
    return SnapshotOut.model_validate(snap)


@router.get(
    "/history/{user_id}",
    response_model=HistoryResponse,
    summary="Return all genome snapshots for a user",
    description=(
        "Returns every stored genome snapshot for the user, oldest first. "
        "Supports optional `since` / `until` date filtering and a `limit` cap. "
        "Designed to handle thousands of records efficiently."
    ),
)
def get_history(
    user_id: int,
    limit: int = Query(
        MAX_HISTORY_LIMIT,
        ge=1,
        le=MAX_HISTORY_LIMIT,
        description="Maximum number of snapshots to return.",
    ),
    since: Optional[datetime] = Query(
        None, description="Return snapshots at or after this ISO-8601 timestamp."
    ),
    until: Optional[datetime] = Query(
        None, description="Return snapshots at or before this ISO-8601 timestamp."
    ),
    db: Session = Depends(get_db),
) -> HistoryResponse:
    service = EvolutionService(db)
    return service.get_history(user_id=user_id, limit=limit, since=since, until=until)


@router.get(
    "/latest/{user_id}",
    response_model=SnapshotOut,
    summary="Return the most recent genome snapshot",
    description="Returns the single most recent genome snapshot for the user.",
)
def get_latest(
    user_id: int,
    db: Session = Depends(get_db),
) -> SnapshotOut:
    service = EvolutionService(db)
    return service.get_latest(user_id=user_id)


@router.get(
    "/timeline/{user_id}",
    response_model=TimelineResponse,
    summary="Return chart-ready timeline data",
    description=(
        "Returns one named series per audio feature, each as a list of "
        "`{x: ISO timestamp, y: float}` data-points — ready to drop into "
        "Recharts, Chart.js, D3, or any charting library. "
        "Also returns archetype-change band annotations for overlay rendering. "
        "Use `downsample` to limit points for large histories."
    ),
)
def get_timeline(
    user_id: int,
    since: Optional[datetime] = Query(None, description="Start of window (ISO-8601)."),
    until: Optional[datetime] = Query(None, description="End of window (ISO-8601)."),
    downsample: Optional[int] = Query(
        None,
        ge=2,
        le=5000,
        description=(
            "Thin to at most N evenly spaced points. "
            "Omit to return every snapshot."
        ),
    ),
    db: Session = Depends(get_db),
) -> TimelineResponse:
    service = EvolutionService(db)
    return service.get_timeline(
        user_id=user_id,
        since=since,
        until=until,
        downsample=downsample,
    )


@router.get(
    "/trends/{user_id}",
    response_model=TrendsResponse,
    summary="Return evolution trends and listening summary",
    description=(
        "Analyses the full snapshot history and returns: "
        "the audio feature with the strongest increase, "
        "the feature with the strongest decrease, "
        "stable features, "
        "archetype transition log, "
        "shadow-archetype transition log, "
        "and a human-readable evolution summary string. "
        "Requires at least 2 snapshots."
    ),
)
def get_trends(
    user_id: int,
    since: Optional[datetime] = Query(None, description="Start of analysis window (ISO-8601)."),
    until: Optional[datetime] = Query(None, description="End of analysis window (ISO-8601)."),
    db: Session = Depends(get_db),
) -> TrendsResponse:
    service = EvolutionService(db)
    return service.get_trends(user_id=user_id, since=since, until=until)


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------

def include_router(app: Any) -> None:
    """
    Call this from your main FastAPI app file:

        from genome_evolution import include_router
        include_router(app)
    """
    app.include_router(router)
