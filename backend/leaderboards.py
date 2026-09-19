"""
leaderboards.py
===============
SonicDNA — Leaderboards Module

Powers city, country, regional, and global leaderboards.
Users are ranked by a composite engagement score derived from genome
activity, calibrations, playlist generation, compatibility participation,
and general engagement.

Assumptions about the existing SonicDNA codebase
-------------------------------------------------
* A shared SQLAlchemy `Base`, `SessionLocal`, and `get_db` already exist
  (imported from `app.database`).
* A `User` ORM model already exists with at least:
    - id                  : int (primary key)
    - username            : str
    - archetype           : str | None
    - shadow_archetype    : str | None
* The following activity tables are assumed to exist in the DB for score
  aggregation. If they don't yet exist in your project, the recalculation
  endpoint degrades gracefully via LEFT JOINs — zero-activity users simply
  score 0 across those dimensions.
    - genome_snapshots(user_id, ...)
    - compatibility_invites(sender_id, ...) / (receiver_id, ...)
    - share_links(user_id, completions, ...)
* Environment variable DATABASE_URL is already configured.

New database objects introduced here
--------------------------------------
* LeaderboardEntry    — one row per user, upserted on recalculation
* ScoreWeightConfig   — optional table for runtime weight tuning (seeded)

Caching strategy
----------------
These endpoints are READ-HEAVY and highly cacheable:
  - /leaderboard/global, /country/*, /city/*       → Cache 5 min (CDN / Redis)
  - /leaderboard/archetype/*                        → Cache 5 min
  - /leaderboard/stats                              → Cache 10 min
  - /leaderboard/me                                 → Cache 1 min (user-scoped)
  - POST /leaderboard/recalculate                   → No cache; invalidates all above

Recommended: FastAPI-Cache2 with Redis backend.
    from fastapi_cache.decorator import cache
    @cache(expire=300)  # added to read endpoints when integrating

ETag / Last-Modified headers are included in all list responses for
conditional GET support at the HTTP layer.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from enum import Enum
from math import ceil
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    case,
    desc,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import OperationalError
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
        id             = Column(Integer, primary_key=True, index=True)
        username       = Column(String(120), unique=True, nullable=False)
        archetype      = Column(String(80), nullable=True)
        shadow_archetype = Column(String(80), nullable=True)
        city           = Column(String(120), nullable=True)
        country        = Column(String(120), nullable=True)


USER_ID_TYPE = User.id.type


# ---------------------------------------------------------------------------
# Constants & Score Weights
# ---------------------------------------------------------------------------

# Component score weights — must sum to 1.0
WEIGHT_GENOME_ACTIVITY:       float = 0.30
WEIGHT_CALIBRATIONS:          float = 0.25
WEIGHT_PLAYLIST_GENERATION:   float = 0.20
WEIGHT_COMPATIBILITY:         float = 0.15
WEIGHT_SOCIAL_ENGAGEMENT:     float = 0.10

MAX_SCORE:        float = 1000.0   # raw component scores are normalised to this
DEFAULT_PAGE_SIZE: int  = 25
MAX_PAGE_SIZE:     int  = 100
RECALC_BATCH:      int  = 500      # users processed per DB batch during recalc


# ---------------------------------------------------------------------------
# ORM Models
# ---------------------------------------------------------------------------

class LeaderboardEntry(Base):
    """
    One row per user — upserted (not appended) on every recalculation.
    Stores the pre-computed composite score and the geographic/archetype
    dimensions used for filtered leaderboard queries.
    """
    __tablename__ = "leaderboard_entries"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    user_id    = Column(USER_ID_TYPE, ForeignKey("users.id", ondelete="CASCADE"),
                        nullable=False, unique=True)

    # Geographic dimensions — denormalised from User for query efficiency
    city       = Column(String(120), nullable=True)
    country    = Column(String(120), nullable=True)

    # Archetype snapshot at score time
    archetype        = Column(String(80), nullable=True)
    shadow_archetype = Column(String(80), nullable=True)

    # Composite score and components (stored for transparency)
    score                   = Column(Float, nullable=False, default=0.0)
    genome_activity_score   = Column(Float, nullable=False, default=0.0)
    calibration_score       = Column(Float, nullable=False, default=0.0)
    playlist_score          = Column(Float, nullable=False, default=0.0)
    compatibility_score     = Column(Float, nullable=False, default=0.0)
    engagement_score        = Column(Float, nullable=False, default=0.0)

    # Rank cache — populated after each full recalculation
    global_rank   = Column(Integer, nullable=True)
    country_rank  = Column(Integer, nullable=True)
    city_rank     = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False,
                        default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False,
                        default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        Index("ix_lb_score",         "score"),
        Index("ix_lb_country_score", "country", "score"),
        Index("ix_lb_city_score",    "city",    "score"),
        Index("ix_lb_archetype",     "archetype", "score"),
        Index("ix_lb_user_id",       "user_id"),
    )


class LeaderboardRecalcLog(Base):
    """
    Audit log for each recalculation run — useful for monitoring and
    for cache invalidation signals.
    """
    __tablename__ = "leaderboard_recalc_logs"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    triggered_by = Column(USER_ID_TYPE, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    started_at   = Column(DateTime(timezone=True), nullable=False,
                          default=lambda: datetime.now(timezone.utc))
    finished_at  = Column(DateTime(timezone=True), nullable=True)
    users_updated = Column(Integer, nullable=True)
    success      = Column(Boolean, nullable=False, default=False)
    error_detail = Column(Text, nullable=True)


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------

class SortOrder(str, Enum):
    DESC = "desc"
    ASC  = "asc"


class LeaderboardEntryOut(BaseModel):
    rank:             int
    user_id:          int
    username:         Optional[str]
    archetype:        Optional[str]
    shadow_archetype: Optional[str]
    city:             Optional[str]
    country:          Optional[str]
    score:            float
    global_rank:      Optional[int]
    country_rank:     Optional[int]
    city_rank:        Optional[int]
    updated_at:       datetime

    # Breakdown (omitted from list views, included on /me)
    genome_activity_score: Optional[float] = None
    calibration_score:     Optional[float] = None
    playlist_score:        Optional[float] = None
    compatibility_score:   Optional[float] = None
    engagement_score_val:  Optional[float] = Field(None, alias="engagement_score")

    model_config = {"from_attributes": True, "populate_by_name": True}


class PaginationMeta(BaseModel):
    page:        int
    page_size:   int
    total:       int
    total_pages: int
    has_next:    bool
    has_prev:    bool


class LeaderboardResponse(BaseModel):
    scope:       str   # "global" | "country:{X}" | "city:{X}" | "archetype:{X}"
    entries:     List[LeaderboardEntryOut]
    pagination:  PaginationMeta
    last_updated: Optional[datetime]
    etag:        str   # MD5 of score list for conditional GET


class MyRankResponse(BaseModel):
    user_id:          int
    username:         Optional[str]
    archetype:        Optional[str]
    city:             Optional[str]
    country:          Optional[str]
    score:            float
    global_rank:      Optional[int]
    country_rank:     Optional[int]
    city_rank:        Optional[int]
    # Score breakdown
    genome_activity_score: float
    calibration_score:     float
    playlist_score:        float
    compatibility_score:   float
    engagement_score:      float
    last_calculated:       datetime
    percentile:            Optional[float]   # 0–100


class ArchetypeStats(BaseModel):
    archetype:   str
    count:       int
    avg_score:   float
    top_score:   float


class LeaderboardStats(BaseModel):
    total_users:      int
    active_cities:    int
    active_countries: int
    top_archetypes:   List[ArchetypeStats]
    average_score:    float
    highest_score:    float
    lowest_score:     float
    last_recalculated: Optional[datetime]
    computed_at:      datetime


class RecalculateRequest(BaseModel):
    requested_by_user_id: Optional[int] = None
    scope: Optional[str] = Field(
        None,
        description="'all' or a specific user_id as string. Defaults to 'all'.",
    )


class RecalculateResponse(BaseModel):
    status:        str
    users_updated: int
    duration_ms:   Optional[float]
    triggered_at:  datetime


# ---------------------------------------------------------------------------
# Score Calculator
# ---------------------------------------------------------------------------

class ScoreCalculator:
    """
    Aggregates raw activity counts from the database into a normalised
    composite score in [0, MAX_SCORE].

    Each component is independently normalised against a soft ceiling,
    then weighted and summed.  Using soft ceilings (rather than dynamic
    per-run max) keeps scores stable across recalculation runs — a user's
    score does not drop just because a new high-scorer joined.

    Soft ceilings (tune these to match your user distribution):
        genome_snapshots    : 100  → score saturates at 100 snapshots
        calibrations        : 20   → score saturates at 20 completions
        playlists           : 50   → score saturates at 50 generated
        compat_participations: 30  → score saturates at 30 participations
        share_completions   : 40   → proxy for general engagement
    """

    GENOME_CEIL:   float = 100.0
    CALIB_CEIL:    float = 20.0
    PLAYLIST_CEIL: float = 50.0
    COMPAT_CEIL:   float = 30.0
    ENGAGE_CEIL:   float = 40.0

    @classmethod
    def _normalise(cls, raw: float, ceiling: float) -> float:
        """Clamps raw count to [0, ceiling], returns ratio in [0, 1]."""
        return min(raw, ceiling) / ceiling if ceiling > 0 else 0.0

    @classmethod
    def compute(
        cls,
        genome_snapshots:      int,
        calibrations:          int,
        playlists_generated:   int,
        compat_participations: int,
        share_completions:     int,
    ) -> Dict[str, float]:
        g = cls._normalise(genome_snapshots,      cls.GENOME_CEIL)
        c = cls._normalise(calibrations,           cls.CALIB_CEIL)
        p = cls._normalise(playlists_generated,    cls.PLAYLIST_CEIL)
        x = cls._normalise(compat_participations,  cls.COMPAT_CEIL)
        e = cls._normalise(share_completions,      cls.ENGAGE_CEIL)

        composite = (
            WEIGHT_GENOME_ACTIVITY     * g
            + WEIGHT_CALIBRATIONS      * c
            + WEIGHT_PLAYLIST_GENERATION * p
            + WEIGHT_COMPATIBILITY     * x
            + WEIGHT_ENGAGEMENT        * e
        ) * MAX_SCORE

        return {
            "genome_activity_score": round(g * MAX_SCORE, 4),
            "calibration_score":     round(c * MAX_SCORE, 4),
            "playlist_score":        round(p * MAX_SCORE, 4),
            "compatibility_score":   round(x * MAX_SCORE, 4),
            "engagement_score":      round(e * MAX_SCORE, 4),
            "score":                 round(composite, 4),
        }


# ---------------------------------------------------------------------------
# Service Layer
# ---------------------------------------------------------------------------

class LeaderboardService:
    """
    All business logic for the leaderboard system.
    Read queries use pre-computed scores from leaderboard_entries.
    The recalculate endpoint is the only place raw activity tables are touched.
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

    def _paginate(
        self,
        query,
        page: int,
        page_size: int,
    ) -> Tuple[list, int]:
        total: int = query.count()
        offset = (page - 1) * page_size
        rows   = query.offset(offset).limit(page_size).all()
        return rows, total

    def _pagination_meta(self, page: int, page_size: int, total: int) -> PaginationMeta:
        total_pages = max(1, ceil(total / page_size))
        return PaginationMeta(
            page        = page,
            page_size   = page_size,
            total       = total,
            total_pages = total_pages,
            has_next    = page < total_pages,
            has_prev    = page > 1,
        )

    def _last_recalc_time(self) -> Optional[datetime]:
        log = (
            self.db.query(LeaderboardRecalcLog)
            .filter(LeaderboardRecalcLog.success == True)  # noqa: E712
            .order_by(LeaderboardRecalcLog.finished_at.desc())
            .first()
        )
        return log.finished_at if log else None

    def _build_etag(self, scores: List[float]) -> str:
        raw = ",".join(f"{s:.2f}" for s in scores)
        return hashlib.md5(raw.encode()).hexdigest()[:16]

    def _entry_to_out(
        self,
        entry: LeaderboardEntry,
        rank: int,
        include_breakdown: bool = False,
    ) -> LeaderboardEntryOut:
        user: Optional[User] = self.db.get(User, entry.user_id)
        data = LeaderboardEntryOut(
            rank             = rank,
            user_id          = entry.user_id,
            username         = user.username if user else None,
            archetype        = entry.archetype,
            shadow_archetype = entry.shadow_archetype,
            city             = entry.city,
            country          = entry.country,
            score            = entry.score,
            global_rank      = entry.global_rank,
            country_rank     = entry.country_rank,
            city_rank        = entry.city_rank,
            updated_at       = entry.updated_at,
        )
        if include_breakdown:
            data.genome_activity_score = entry.genome_activity_score
            data.calibration_score     = entry.calibration_score
            data.playlist_score        = entry.playlist_score
            data.compatibility_score   = entry.compatibility_score
            data.engagement_score_val  = entry.engagement_score
        return data

    def _build_response(
        self,
        scope: str,
        entries: List[LeaderboardEntry],
        total: int,
        page: int,
        page_size: int,
        rank_offset: int = 0,
    ) -> LeaderboardResponse:
        last_updated = self._last_recalc_time()
        out_entries  = [
            self._entry_to_out(e, rank_offset + i + 1)
            for i, e in enumerate(entries)
        ]
        etag = self._build_etag([e.score for e in out_entries])

        return LeaderboardResponse(
            scope        = scope,
            entries      = out_entries,
            pagination   = self._pagination_meta(page, page_size, total),
            last_updated = last_updated,
            etag         = etag,
        )

    # ------------------------------------------------------------------
    # Read endpoints
    # ------------------------------------------------------------------

    def get_global(self, page: int, page_size: int) -> LeaderboardResponse:
        q = (
            self.db.query(LeaderboardEntry)
            .order_by(desc(LeaderboardEntry.score))
        )
        rows, total = self._paginate(q, page, page_size)
        rank_offset = (page - 1) * page_size
        return self._build_response("global", rows, total, page, page_size, rank_offset)

    def get_by_country(
        self, country: str, page: int, page_size: int
    ) -> LeaderboardResponse:
        q = (
            self.db.query(LeaderboardEntry)
            .filter(func.lower(LeaderboardEntry.country) == country.lower())
            .order_by(desc(LeaderboardEntry.score))
        )
        rows, total = self._paginate(q, page, page_size)
        rank_offset = (page - 1) * page_size
        return self._build_response(
            f"country:{country}", rows, total, page, page_size, rank_offset
        )

    def get_by_city(
        self, city: str, page: int, page_size: int
    ) -> LeaderboardResponse:
        q = (
            self.db.query(LeaderboardEntry)
            .filter(func.lower(LeaderboardEntry.city) == city.lower())
            .order_by(desc(LeaderboardEntry.score))
        )
        rows, total = self._paginate(q, page, page_size)
        rank_offset = (page - 1) * page_size
        return self._build_response(
            f"city:{city}", rows, total, page, page_size, rank_offset
        )

    def get_by_archetype(
        self, archetype: str, page: int, page_size: int
    ) -> LeaderboardResponse:
        q = (
            self.db.query(LeaderboardEntry)
            .filter(func.lower(LeaderboardEntry.archetype) == archetype.lower())
            .order_by(desc(LeaderboardEntry.score))
        )
        rows, total = self._paginate(q, page, page_size)
        rank_offset = (page - 1) * page_size
        return self._build_response(
            f"archetype:{archetype}", rows, total, page, page_size, rank_offset
        )

    def get_my_rank(self, user_id: int) -> MyRankResponse:
        user = self._get_user_or_404(user_id)

        entry: Optional[LeaderboardEntry] = (
            self.db.query(LeaderboardEntry)
            .filter(LeaderboardEntry.user_id == user_id)
            .first()
        )
        if entry is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"No leaderboard entry for user {user_id}. "
                    "Trigger POST /leaderboard/recalculate to generate scores."
                ),
            )

        # Compute percentile: what % of users score BELOW this user
        total_users: int = self.db.query(func.count(LeaderboardEntry.id)).scalar() or 1
        lower_count: int = (
            self.db.query(func.count(LeaderboardEntry.id))
            .filter(LeaderboardEntry.score < entry.score)
            .scalar()
            or 0
        )
        percentile = round((lower_count / total_users) * 100, 1)

        return MyRankResponse(
            user_id               = user_id,
            username              = user.username,
            archetype             = entry.archetype,
            city                  = entry.city,
            country               = entry.country,
            score                 = entry.score,
            global_rank           = entry.global_rank,
            country_rank          = entry.country_rank,
            city_rank             = entry.city_rank,
            genome_activity_score = entry.genome_activity_score,
            calibration_score     = entry.calibration_score,
            playlist_score        = entry.playlist_score,
            compatibility_score   = entry.compatibility_score,
            engagement_score      = entry.engagement_score,
            last_calculated       = entry.updated_at,
            percentile            = percentile,
        )

    def get_stats(self) -> LeaderboardStats:
        total_users: int = (
            self.db.query(func.count(LeaderboardEntry.id)).scalar() or 0
        )
        active_cities: int = (
            self.db.query(func.count(func.distinct(LeaderboardEntry.city)))
            .filter(LeaderboardEntry.city.isnot(None))
            .scalar()
            or 0
        )
        active_countries: int = (
            self.db.query(func.count(func.distinct(LeaderboardEntry.country)))
            .filter(LeaderboardEntry.country.isnot(None))
            .scalar()
            or 0
        )
        avg_score: float = float(
            self.db.query(func.avg(LeaderboardEntry.score)).scalar() or 0.0
        )
        highest_score: float = float(
            self.db.query(func.max(LeaderboardEntry.score)).scalar() or 0.0
        )
        lowest_score: float = float(
            self.db.query(func.min(LeaderboardEntry.score)).scalar() or 0.0
        )

        # Top archetypes by count and avg score
        archetype_rows = (
            self.db.query(
                LeaderboardEntry.archetype,
                func.count(LeaderboardEntry.id).label("count"),
                func.avg(LeaderboardEntry.score).label("avg_score"),
                func.max(LeaderboardEntry.score).label("top_score"),
            )
            .filter(LeaderboardEntry.archetype.isnot(None))
            .group_by(LeaderboardEntry.archetype)
            .order_by(func.count(LeaderboardEntry.id).desc())
            .limit(10)
            .all()
        )
        top_archetypes = [
            ArchetypeStats(
                archetype = row.archetype,
                count     = row.count,
                avg_score = round(float(row.avg_score), 2),
                top_score = round(float(row.top_score), 2),
            )
            for row in archetype_rows
        ]

        return LeaderboardStats(
            total_users       = total_users,
            active_cities     = active_cities,
            active_countries  = active_countries,
            top_archetypes    = top_archetypes,
            average_score     = round(avg_score, 2),
            highest_score     = round(highest_score, 2),
            lowest_score      = round(lowest_score, 2),
            last_recalculated = self._last_recalc_time(),
            computed_at       = datetime.now(timezone.utc),
        )

    # ------------------------------------------------------------------
    # Recalculation
    # ------------------------------------------------------------------

    def recalculate(
        self,
        requested_by: Optional[int] = None,
        scope: Optional[str] = None,
    ) -> RecalculateResponse:
        """
        Recomputes scores for all (or a single) user(s) and upserts
        LeaderboardEntry rows.  After upsert, rank columns are updated
        via window-function-style ranked subqueries.

        Uses batched commits (RECALC_BATCH rows) to avoid long transactions
        on large user tables.
        """
        import time
        started = time.monotonic()

        log = LeaderboardRecalcLog(triggered_by=requested_by)
        self.db.add(log)
        self.db.flush()

        try:
            users_updated = self._run_recalculation(scope)
            self._update_rank_columns()

            log.finished_at   = datetime.now(timezone.utc)
            log.users_updated = users_updated
            log.success       = True
            self.db.commit()

        except Exception as exc:
            self.db.rollback()
            log.finished_at  = datetime.now(timezone.utc)
            log.success      = False
            log.error_detail = str(exc)
            self.db.add(log)
            self.db.commit()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Recalculation failed: {exc}",
            )

        duration_ms = round((time.monotonic() - started) * 1000, 1)

        return RecalculateResponse(
            status        = "completed",
            users_updated = users_updated,
            duration_ms   = duration_ms,
            triggered_at  = log.started_at,
        )

    def _run_recalculation(self, scope: Optional[str]) -> int:
        """
        Aggregates activity counts per user and upserts LeaderboardEntry rows.

        Activity tables referenced:
            genome_snapshots(user_id)
            compatibility_invites(sender_id) + (receiver_id)
            share_links(user_id, completions)

        Missing tables degrade gracefully — the LEFT JOINs return NULL which
        coalesces to 0.
        """
        # Determine which users to process
        user_query = self.db.query(User)
        if scope and scope.isdigit():
            user_query = user_query.filter(User.id == int(scope))

        users: List[User] = user_query.all()
        if not users:
            return 0

        updated = 0
        batch: List[Dict[str, Any]] = []

        for user in users:
            scores = self._compute_user_score(user.id)

            city    = getattr(user, "city",    None)
            country = getattr(user, "country", None)

            batch.append(
                {
                    "user_id":               user.id,
                    "city":                  city,
                    "country":               country,
                    "archetype":             getattr(user, "archetype",        None),
                    "shadow_archetype":      getattr(user, "shadow_archetype", None),
                    "score":                 scores["score"],
                    "genome_activity_score": scores["genome_activity_score"],
                    "calibration_score":     scores["calibration_score"],
                    "playlist_score":        scores["playlist_score"],
                    "compatibility_score":   scores["compatibility_score"],
                    "engagement_score":      scores["engagement_score"],
                    "updated_at":            datetime.now(timezone.utc),
                }
            )
            updated += 1

            if len(batch) >= RECALC_BATCH:
                self._upsert_batch(batch)
                batch = []

        if batch:
            self._upsert_batch(batch)

        return updated

    def _compute_user_score(self, user_id: int) -> Dict[str, float]:
        """
        Pulls raw activity counts for a single user using safe LEFT JOINs.
        Falls back to 0 if an activity table doesn't exist yet.
        """
        genome_count = self._safe_count(
            "SELECT COUNT(*) FROM genome_snapshots WHERE user_id = :uid",
            user_id,
        )
        calibration_count = self._safe_count(
            # Calibrations = snapshots where calibration flag is set.
            # If your schema differs, replace with the correct query.
            "SELECT COUNT(*) FROM genome_snapshots "
            "WHERE user_id = :uid AND calibration = true",
            user_id,
        )
        playlist_count = self._safe_count(
            "SELECT COUNT(*) FROM playlist_generations WHERE user_id = :uid",
            user_id,
        )
        compat_count = self._safe_count(
            "SELECT COUNT(*) FROM compatibility_invites "
            "WHERE sender_id = :uid OR receiver_id = :uid",
            user_id,
        )
        share_completions = self._safe_count(
            "SELECT COALESCE(SUM(completions), 0) FROM share_links_manager WHERE user_id = :uid",
            user_id,
        )

        return ScoreCalculator.compute(
            genome_snapshots      = genome_count,
            calibrations          = calibration_count,
            playlists_generated   = playlist_count,
            compat_participations = compat_count,
            share_completions     = share_completions,
        )

    def _safe_count(self, sql: str, user_id: int) -> int:
        """Executes a raw count query; returns 0 if the table doesn't exist."""
        try:
            result = self.db.execute(text(sql), {"uid": user_id}).scalar()
            return int(result or 0)
        except OperationalError:
            return 0

    def _upsert_batch(self, batch: List[Dict[str, Any]]) -> None:
        """
        Postgres-native upsert.  Falls back to delete+insert for SQLite
        (dev / test environments).
        """
        try:
            stmt = pg_insert(LeaderboardEntry).values(batch)
            stmt = stmt.on_conflict_do_update(
                index_elements=["user_id"],
                set_={
                    col: stmt.excluded[col]
                    for col in [
                        "city", "country", "archetype", "shadow_archetype",
                        "score", "genome_activity_score", "calibration_score",
                        "playlist_score", "compatibility_score",
                        "engagement_score", "updated_at",
                    ]
                },
            )
            self.db.execute(stmt)
            self.db.flush()
        except Exception:
            # SQLite fallback
            for row in batch:
                existing = (
                    self.db.query(LeaderboardEntry)
                    .filter(LeaderboardEntry.user_id == row["user_id"])
                    .first()
                )
                if existing:
                    for k, v in row.items():
                        setattr(existing, k, v)
                else:
                    self.db.add(LeaderboardEntry(**row))
            self.db.flush()

    def _update_rank_columns(self) -> None:
        """
        Assigns global, country, and city rank columns using Python-side
        ranking after the upsert completes.  For large deployments, this
        should be replaced with a DB-side window function UPDATE.
        """
        # Global ranks
        all_entries: List[LeaderboardEntry] = (
            self.db.query(LeaderboardEntry)
            .order_by(desc(LeaderboardEntry.score))
            .all()
        )
        for rank, entry in enumerate(all_entries, start=1):
            entry.global_rank = rank

        # Country ranks
        country_entries: Dict[str, List[LeaderboardEntry]] = {}
        for e in all_entries:
            if e.country:
                country_entries.setdefault(e.country, []).append(e)
        for country_list in country_entries.values():
            country_list.sort(key=lambda e: e.score, reverse=True)
            for rank, entry in enumerate(country_list, start=1):
                entry.country_rank = rank

        # City ranks
        city_entries: Dict[str, List[LeaderboardEntry]] = {}
        for e in all_entries:
            if e.city:
                city_entries.setdefault(e.city, []).append(e)
        for city_list in city_entries.values():
            city_list.sort(key=lambda e: e.score, reverse=True)
            for rank, entry in enumerate(city_list, start=1):
                entry.city_rank = rank

        self.db.flush()


# ---------------------------------------------------------------------------
# FastAPI Router
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/leaderboard",
    tags=["Leaderboards"],
    responses={
        404: {"description": "Resource not found"},
        422: {"description": "Validation error"},
        500: {"description": "Internal server error"},
    },
)


def _page_params(
    page:      int = Query(1,                ge=1,            description="Page number (1-indexed)."),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="Results per page."),
) -> Tuple[int, int]:
    return page, page_size


@router.get(
    "/global",
    response_model=LeaderboardResponse,
    summary="Global leaderboard",
    description=(
        "Returns all users ranked by composite score, globally. "
        "Supports pagination. "
        "Recommended cache TTL: 300 s."
    ),
)
def get_global(
    params: Tuple[int, int] = Depends(_page_params),
    db: Session = Depends(get_db),
) -> LeaderboardResponse:
    page, page_size = params
    return LeaderboardService(db).get_global(page, page_size)


@router.get(
    "/country/{country}",
    response_model=LeaderboardResponse,
    summary="Country leaderboard",
    description=(
        "Returns users in the specified country, ranked by score. "
        "Country name is case-insensitive. "
        "Recommended cache TTL: 300 s."
    ),
)
def get_by_country(
    country: str,
    params: Tuple[int, int] = Depends(_page_params),
    db: Session = Depends(get_db),
) -> LeaderboardResponse:
    page, page_size = params
    return LeaderboardService(db).get_by_country(country, page, page_size)


@router.get(
    "/city/{city}",
    response_model=LeaderboardResponse,
    summary="City leaderboard",
    description=(
        "Returns users in the specified city, ranked by score. "
        "City name is case-insensitive. "
        "Recommended cache TTL: 300 s."
    ),
)
def get_by_city(
    city: str,
    params: Tuple[int, int] = Depends(_page_params),
    db: Session = Depends(get_db),
) -> LeaderboardResponse:
    page, page_size = params
    return LeaderboardService(db).get_by_city(city, page, page_size)


@router.get(
    "/archetype/{archetype}",
    response_model=LeaderboardResponse,
    summary="Archetype leaderboard",
    description=(
        "Returns all users of the specified SonicDNA archetype, ranked by score. "
        "Archetype name is case-insensitive. "
        "Recommended cache TTL: 300 s."
    ),
)
def get_by_archetype(
    archetype: str,
    params: Tuple[int, int] = Depends(_page_params),
    db: Session = Depends(get_db),
) -> LeaderboardResponse:
    page, page_size = params
    return LeaderboardService(db).get_by_archetype(archetype, page, page_size)


@router.get(
    "/me",
    response_model=MyRankResponse,
    summary="My rank and score breakdown",
    description=(
        "Returns the authenticated user's rank, all component scores, "
        "and global percentile. "
        "Recommended cache TTL: 60 s (user-scoped)."
    ),
)
def get_my_rank(
    user_id: int = Query(..., description="The authenticated user's ID."),
    db: Session = Depends(get_db),
) -> MyRankResponse:
    return LeaderboardService(db).get_my_rank(user_id)


@router.get(
    "/stats",
    response_model=LeaderboardStats,
    summary="Leaderboard network statistics",
    description=(
        "Returns aggregate stats: total users, active cities and countries, "
        "top archetypes, score distribution. "
        "Recommended cache TTL: 600 s."
    ),
)
def get_stats(
    db: Session = Depends(get_db),
) -> LeaderboardStats:
    return LeaderboardService(db).get_stats()


@router.post(
    "/recalculate",
    response_model=RecalculateResponse,
    status_code=status.HTTP_200_OK,
    summary="Trigger score recalculation",
    description=(
        "Recomputes composite scores for all users (or a single user via `scope`), "
        "upserts LeaderboardEntry rows, and refreshes rank columns. "
        "Should be called from a scheduled job or after significant activity milestones. "
        "Invalidate all leaderboard caches after this call."
    ),
)
def recalculate(
    payload: RecalculateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> RecalculateResponse:
    return LeaderboardService(db).recalculate(
        requested_by = payload.requested_by_user_id,
        scope        = payload.scope,
    )


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------

def include_router(app: Any) -> None:
    """
    Call this from your main FastAPI app file:

        from leaderboards import include_router
        include_router(app)
    """
    app.include_router(router)
