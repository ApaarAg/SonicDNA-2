"""
social_constellation.py
=======================
SonicDNA — Gravity Network Module

Powers the "Gravity Network" section of SonicDNA.
Represents users as nodes in a musical-genome graph, connects nodes by
similarity (genome distance + archetype affinity + shadow-archetype overlap),
and exposes the constellation, neighbour, cluster, and stats endpoints.

Assumptions about the existing SonicDNA codebase
-------------------------------------------------
* A shared SQLAlchemy `Base` and `SessionLocal` / `get_db` already exist
  (imported from `app.database`).
* A `User` ORM model already exists with at least:
    - id            : int / UUID (primary key)
    - username      : str
    - genome_vector : JSON / ARRAY column  (list[float], length GENOME_DIM)
    - archetype     : str
    - shadow_archetype : str
* Environment variable DATABASE_URL is already set for the main app.

New database objects introduced here
-------------------------------------
* UserSimilarity  — pre-computed pairwise similarity cache
* SocialCluster   — community / cluster membership
"""

from __future__ import annotations

import math
import os
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import (
    JSON,
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
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import Session, relationship

# ---------------------------------------------------------------------------
# Shared database objects  (adjust import path to match your project layout)
# ---------------------------------------------------------------------------
try:
    from app.database import Base, SessionLocal, get_db  # type: ignore
    from app.models import User  # type: ignore  – existing User model
except ImportError:
    # Fallback for standalone testing / documentation builds
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

    # Minimal stub so the module is importable without the full app
    class User(Base):  # type: ignore[no-redef]
        __tablename__ = "users"
        id = Column(Integer, primary_key=True, index=True)
        username = Column(String(120), unique=True, nullable=False)
        genome_vector = Column(JSON, nullable=True)   # list[float]
        archetype = Column(String(80), nullable=True)
        shadow_archetype = Column(String(80), nullable=True)


USER_ID_TYPE = User.id.type

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GENOME_DIM: int = 128          # expected genome vector dimensionality
MAX_NEIGHBOURS: int = 50       # hard cap on neighbour queries
DEFAULT_NEIGHBOURS: int = 10
SIMILARITY_THRESHOLD: float = 0.35   # minimum score to store an edge
CLUSTER_SIMILARITY_CUTOFF: float = 0.55   # minimum to be in same cluster


# ---------------------------------------------------------------------------
# ORM Models — new tables introduced by this module
# ---------------------------------------------------------------------------

class UserSimilarity(Base):
    """
    Pre-computed, directed similarity edge between two users.

    The pair (user_a_id, user_b_id) is always stored with user_a_id < user_b_id
    to avoid duplicates.  The `similarity_score` is the combined weighted score.
    """
    __tablename__ = "user_similarities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_a_id = Column(USER_ID_TYPE, ForeignKey("users.id"), nullable=False)
    user_b_id = Column(USER_ID_TYPE, ForeignKey("users.id"), nullable=False)

    # Component scores (stored for diagnostics / re-weighting)
    genome_score = Column(Float, nullable=False, default=0.0)
    archetype_score = Column(Float, nullable=False, default=0.0)
    shadow_score = Column(Float, nullable=False, default=0.0)
    similarity_score = Column(Float, nullable=False, default=0.0)   # weighted total

    computed_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    is_stale = Column(Boolean, nullable=False, default=False)

    user_a = relationship("User", foreign_keys=[user_a_id])
    user_b = relationship("User", foreign_keys=[user_b_id])

    __table_args__ = (
        UniqueConstraint("user_a_id", "user_b_id", name="uq_user_pair"),
        Index("ix_similarity_user_a", "user_a_id"),
        Index("ix_similarity_user_b", "user_b_id"),
        Index("ix_similarity_score", "similarity_score"),
    )


class SocialCluster(Base):
    """
    Community membership record.
    One row per (user, cluster) membership — a user belongs to exactly one
    primary cluster; secondary memberships can be added later.
    """
    __tablename__ = "social_clusters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cluster_label = Column(String(80), nullable=False)   # e.g. "cluster_7"
    user_id = Column(USER_ID_TYPE, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    archetype_signature = Column(String(80), nullable=True)   # dominant archetype in cluster
    centroid_vector = Column(JSON, nullable=True)              # mean genome vector
    member_count = Column(Integer, nullable=False, default=1)
    cohesion_score = Column(Float, nullable=True)             # mean intra-cluster similarity
    computed_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        Index("ix_cluster_label", "cluster_label"),
        Index("ix_cluster_user", "user_id"),
    )


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------

class ArchetypeEnum(str, Enum):
    """
    Known SonicDNA archetypes.
    Extend this list to match your actual archetype vocabulary.
    """
    EXPLORER = "explorer"
    DEVOTEE = "devotee"
    CURATOR = "curator"
    REBEL = "rebel"
    NOSTALGIST = "nostalgist"
    FUTURIST = "futurist"
    EMPATH = "empath"
    ANALYST = "analyst"
    UNKNOWN = "unknown"


# --- shared sub-schemas ---

class GenomeVector(BaseModel):
    vector: List[float] = Field(..., min_length=1, max_length=512)

    @field_validator("vector")
    @classmethod
    def must_be_unit_norm(cls, v: List[float]) -> List[float]:
        norm = math.sqrt(sum(x * x for x in v))
        if norm == 0:
            raise ValueError("Genome vector must not be a zero vector.")
        return v


class UserNodeBase(BaseModel):
    user_id: Union[int, str]
    username: str
    archetype: Optional[str] = None
    shadow_archetype: Optional[str] = None


class UserNode(UserNodeBase):
    similarity_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    genome_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    archetype_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    shadow_score: Optional[float] = Field(None, ge=0.0, le=1.0)

    model_config = {"from_attributes": True}


# --- endpoint response schemas ---

class ConstellationEdge(BaseModel):
    source_id: Union[int, str]
    target_id: Union[int, str]
    weight: float = Field(..., ge=0.0, le=1.0)
    archetype_match: bool


class ConstellationResponse(BaseModel):
    nodes: List[UserNode]
    edges: List[ConstellationEdge]
    total_nodes: int
    total_edges: int
    computed_at: datetime


class NeighboursResponse(BaseModel):
    user_id: Union[int, str]
    neighbours: List[UserNode]
    count: int


class ClusterMember(UserNode):
    cluster_label: str


class ClusterResponse(BaseModel):
    user_id: Union[int, str]
    cluster_label: str
    archetype_signature: Optional[str]
    cohesion_score: Optional[float]
    members: List[ClusterMember]
    member_count: int


class NetworkStats(BaseModel):
    total_users: int
    total_clusters: int
    average_similarity: float
    network_density: float
    most_connected_archetype: Optional[str]
    orphan_users: int               # users with zero similarity edges
    computed_at: datetime


# ---------------------------------------------------------------------------
# Similarity Engine
# ---------------------------------------------------------------------------

class SimilarityEngine:
    """
    Computes pairwise musical similarity between two SonicDNA users.

    Formula
    -------
    similarity = w_genome * genome_score
               + w_archetype * archetype_score
               + w_shadow * shadow_score

    Weights sum to 1.0.
    """

    W_GENOME: float = 0.60
    W_ARCHETYPE: float = 0.25
    W_SHADOW: float = 0.15

    # Archetype affinity table — symmetric bonus [0, 1]
    ARCHETYPE_AFFINITY: Dict[Tuple[str, str], float] = {
        ("explorer", "futurist"): 0.85,
        ("explorer", "rebel"): 0.75,
        ("devotee", "nostalgist"): 0.90,
        ("devotee", "empath"): 0.80,
        ("curator", "analyst"): 0.88,
        ("curator", "devotee"): 0.72,
        ("rebel", "futurist"): 0.78,
        ("nostalgist", "empath"): 0.82,
        ("analyst", "futurist"): 0.76,
        ("empath", "devotee"): 0.80,
    }

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        """Returns cosine similarity in [0, 1] (shifted from [-1,1])."""
        if len(a) != len(b):
            # Pad the shorter vector with zeros
            max_len = max(len(a), len(b))
            a = a + [0.0] * (max_len - len(a))
            b = b + [0.0] * (max_len - len(b))

        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))

        if norm_a == 0 or norm_b == 0:
            return 0.0

        raw = dot / (norm_a * norm_b)
        # Shift from [-1, 1] to [0, 1]
        return (raw + 1.0) / 2.0

    @classmethod
    def genome_score(cls, vec_a: List[float], vec_b: List[float]) -> float:
        return cls._cosine_similarity(vec_a, vec_b)

    @classmethod
    def archetype_score(cls, arch_a: Optional[str], arch_b: Optional[str]) -> float:
        if not arch_a or not arch_b:
            return 0.0
        if arch_a == arch_b:
            return 1.0
        key = tuple(sorted([arch_a.lower(), arch_b.lower()]))
        return cls.ARCHETYPE_AFFINITY.get(key, 0.30)  # type: ignore[arg-type]

    @classmethod
    def shadow_score(
        cls,
        shadow_a: Optional[str],
        shadow_b: Optional[str],
        arch_a: Optional[str],
        arch_b: Optional[str],
    ) -> float:
        """
        Shadow-archetype overlap rewards users whose shadow aligns with the
        other's primary archetype (psychological complementarity) or whose
        shadows match (shared repressed tendencies).
        """
        if not shadow_a or not shadow_b:
            return 0.0

        shadow_a_l = shadow_a.lower()
        shadow_b_l = shadow_b.lower()
        arch_a_l = (arch_a or "").lower()
        arch_b_l = (arch_b or "").lower()

        score = 0.0
        # Identical shadow archetypes — shared depth
        if shadow_a_l == shadow_b_l:
            score += 0.6

        # Cross-shadow / primary alignment (complementarity bonus)
        if shadow_a_l == arch_b_l:
            score += 0.4
        if shadow_b_l == arch_a_l:
            score += 0.4

        # Clamp to [0, 1]
        return min(score, 1.0)

    @classmethod
    def compute(
        cls,
        user_a: User,
        user_b: User,
    ) -> Dict[str, float]:
        vec_a: List[float] = user_a.genome_vector or []
        vec_b: List[float] = user_b.genome_vector or []

        g_score = cls.genome_score(vec_a, vec_b) if vec_a and vec_b else 0.0
        a_score = cls.archetype_score(user_a.archetype, user_b.archetype)
        s_score = cls.shadow_score(
            user_a.shadow_archetype,
            user_b.shadow_archetype,
            user_a.archetype,
            user_b.archetype,
        )

        total = (
            cls.W_GENOME * g_score
            + cls.W_ARCHETYPE * a_score
            + cls.W_SHADOW * s_score
        )

        return {
            "genome_score": round(g_score, 6),
            "archetype_score": round(a_score, 6),
            "shadow_score": round(s_score, 6),
            "similarity_score": round(total, 6),
        }


# ---------------------------------------------------------------------------
# Service Layer
# ---------------------------------------------------------------------------

class ConstellationService:
    """
    All business logic for the Gravity Network.
    Keeps database writes, similarity computation, and graph traversal
    decoupled from the HTTP layer.
    """

    def __init__(self, db: Session):
        self.db = db
        self.engine = SimilarityEngine()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_user_or_404(self, user_id: Union[int, str]) -> User:
        user = self.db.get(User, user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User {user_id} not found.",
            )
        return user

    def _ordered_pair(self, a: Union[int, str], b: Union[int, str]) -> Tuple[Union[int, str], Union[int, str]]:
        sa, sb = str(a), str(b)
        return (a, b) if sa < sb else (b, a)

    def _upsert_similarity(self, user_a: User, user_b: User) -> UserSimilarity:
        uid_lo, uid_hi = self._ordered_pair(user_a.id, user_b.id)
        scores = SimilarityEngine.compute(user_a, user_b)

        existing = (
            self.db.query(UserSimilarity)
            .filter(
                UserSimilarity.user_a_id == uid_lo,
                UserSimilarity.user_b_id == uid_hi,
            )
            .first()
        )

        if existing:
            existing.genome_score = scores["genome_score"]
            existing.archetype_score = scores["archetype_score"]
            existing.shadow_score = scores["shadow_score"]
            existing.similarity_score = scores["similarity_score"]
            existing.is_stale = False
            existing.computed_at = datetime.now(timezone.utc)
            self.db.flush()
            return existing

        record = UserSimilarity(
            user_a_id=uid_lo,
            user_b_id=uid_hi,
            **scores,
        )
        self.db.add(record)
        try:
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            return (
                self.db.query(UserSimilarity)
                .filter(
                    UserSimilarity.user_a_id == uid_lo,
                    UserSimilarity.user_b_id == uid_hi,
                )
                .one()
            )
        return record

    def _similarity_to_node(
        self,
        target_user: User,
        sim: UserSimilarity,
    ) -> UserNode:
        return UserNode(
            user_id=str(target_user.id),
            username=target_user.username,
            archetype=target_user.archetype,
            shadow_archetype=target_user.shadow_archetype,
            similarity_score=sim.similarity_score,
            genome_score=sim.genome_score,
            archetype_score=sim.archetype_score,
            shadow_score=sim.shadow_score,
        )

    # ------------------------------------------------------------------
    # Public service methods
    # ------------------------------------------------------------------

    def get_constellation(
        self,
        limit: int = 100,
        min_similarity: float = SIMILARITY_THRESHOLD,
    ) -> ConstellationResponse:
        """
        Returns a graph snapshot: nodes = users, edges = similarity links.
        Pulls the strongest edges and the users on both sides.
        """
        edges_q = (
            self.db.query(UserSimilarity)
            .filter(UserSimilarity.similarity_score >= min_similarity)
            .order_by(UserSimilarity.similarity_score.desc())
            .limit(limit)
            .all()
        )

        # Collect unique user IDs from edges
        user_ids: set[int] = set()
        for e in edges_q:
            user_ids.add(e.user_a_id)
            user_ids.add(e.user_b_id)

        users_map: Dict[int, User] = {}
        if user_ids:
            rows = self.db.query(User).filter(User.id.in_(list(user_ids))).all()
            users_map = {u.id: u for u in rows}

        nodes = [
            UserNode(
                user_id=str(u.id),
                username=u.username,
                archetype=u.archetype,
                shadow_archetype=u.shadow_archetype,
            )
            for u in users_map.values()
        ]

        edges = [
            ConstellationEdge(
                source_id=str(e.user_a_id),
                target_id=str(e.user_b_id),
                weight=e.similarity_score,
                archetype_match=(
                    users_map[e.user_a_id].archetype
                    == users_map[e.user_b_id].archetype
                )
                if e.user_a_id in users_map and e.user_b_id in users_map
                else False,
            )
            for e in edges_q
        ]

        return ConstellationResponse(
            nodes=nodes,
            edges=edges,
            total_nodes=len(nodes),
            total_edges=len(edges),
            computed_at=datetime.now(timezone.utc),
        )

    def get_neighbours(
        self,
        user_id: Union[int, str],
        limit: int = DEFAULT_NEIGHBOURS,
        min_similarity: float = SIMILARITY_THRESHOLD,
        recompute: bool = False,
    ) -> NeighboursResponse:
        """
        Returns the most similar listeners for a given user.
        If `recompute=True`, freshens similarity scores against all users.
        """
        target = self._get_user_or_404(user_id)

        if recompute:
            # Compute / refresh similarity against every other user
            all_users: List[User] = (
                self.db.query(User).filter(User.id != user_id).all()
            )
            for other in all_users:
                scores = SimilarityEngine.compute(target, other)
                if scores["similarity_score"] >= min_similarity:
                    self._upsert_similarity(target, other)
            self.db.commit()

        # Fetch stored similarities involving this user
        sims: List[UserSimilarity] = (
            self.db.query(UserSimilarity)
            .filter(
                (
                    (UserSimilarity.user_a_id == user_id)
                    | (UserSimilarity.user_b_id == user_id)
                ),
                UserSimilarity.similarity_score >= min_similarity,
            )
            .order_by(UserSimilarity.similarity_score.desc())
            .limit(limit)
            .all()
        )

        neighbour_nodes: List[UserNode] = []
        for sim in sims:
            other_id = sim.user_b_id if sim.user_a_id == user_id else sim.user_a_id
            other_user = self.db.get(User, other_id)
            if other_user:
                neighbour_nodes.append(self._similarity_to_node(other_user, sim))

        return NeighboursResponse(
            user_id=str(user_id),
            neighbours=neighbour_nodes,
            count=len(neighbour_nodes),
        )

    def get_cluster(self, user_id: Union[int, str]) -> ClusterResponse:
        """
        Returns the community / cluster the user belongs to.
        If no cluster membership exists, creates one on-the-fly using a
        greedy expansion from this user's neighbours.
        """
        self._get_user_or_404(user_id)

        membership: Optional[SocialCluster] = (
            self.db.query(SocialCluster)
            .filter(SocialCluster.user_id == user_id)
            .first()
        )

        if not membership:
            membership = self._assign_cluster(user_id)

        # Fetch all members of this cluster
        cluster_memberships: List[SocialCluster] = (
            self.db.query(SocialCluster)
            .filter(SocialCluster.cluster_label == membership.cluster_label)
            .all()
        )

        member_user_ids = [m.user_id for m in cluster_memberships]
        member_users: Dict[int, User] = {
            u.id: u
            for u in self.db.query(User).filter(User.id.in_(member_user_ids)).all()
        }

        members = [
            ClusterMember(
                user_id=str(uid),
                username=member_users[uid].username,
                archetype=member_users[uid].archetype,
                shadow_archetype=member_users[uid].shadow_archetype,
                cluster_label=membership.cluster_label,
            )
            for uid in member_user_ids
            if uid in member_users
        ]

        return ClusterResponse(
            user_id=str(user_id),
            cluster_label=membership.cluster_label,
            archetype_signature=membership.archetype_signature,
            cohesion_score=membership.cohesion_score,
            members=members,
            member_count=len(members),
        )

    def get_stats(self) -> NetworkStats:
        """Returns aggregate network statistics."""
        total_users: int = self.db.query(func.count(User.id)).scalar() or 0

        total_clusters: int = (
            self.db.query(func.count(func.distinct(SocialCluster.cluster_label))).scalar()
            or 0
        )

        avg_sim_row = self.db.query(
            func.avg(UserSimilarity.similarity_score)
        ).scalar()
        avg_similarity: float = round(float(avg_sim_row or 0.0), 4)

        # Network density = actual edges / possible edges
        total_edges: int = self.db.query(func.count(UserSimilarity.id)).scalar() or 0
        max_edges = (total_users * (total_users - 1)) / 2 if total_users > 1 else 1
        density: float = round(total_edges / max_edges, 6) if max_edges > 0 else 0.0

        # Most connected archetype (archetype with highest avg similarity)
        archetype_row = (
            self.db.query(
                User.archetype,
                func.avg(UserSimilarity.similarity_score).label("avg_sim"),
            )
            .join(
                UserSimilarity,
                (User.id == UserSimilarity.user_a_id)
                | (User.id == UserSimilarity.user_b_id),
            )
            .group_by(User.archetype)
            .order_by(func.avg(UserSimilarity.similarity_score).desc())
            .first()
        )
        most_connected_archetype: Optional[str] = (
            archetype_row[0] if archetype_row else None
        )

        # Orphan users — no similarity edges at all
        connected_ids_subq = self.db.query(
            func.distinct(UserSimilarity.user_a_id).label("uid")
        ).union(
            self.db.query(func.distinct(UserSimilarity.user_b_id).label("uid"))
        ).subquery()

        orphan_count: int = (
            self.db.query(func.count(User.id))
            .filter(User.id.not_in(select(connected_ids_subq)))
            .scalar()
            or 0
        )

        return NetworkStats(
            total_users=total_users,
            total_clusters=total_clusters,
            average_similarity=avg_similarity,
            network_density=density,
            most_connected_archetype=most_connected_archetype,
            orphan_users=orphan_count,
            computed_at=datetime.now(timezone.utc),
        )

    # ------------------------------------------------------------------
    # Private cluster assignment
    # ------------------------------------------------------------------

    def _assign_cluster(self, user_id: Union[int, str]) -> SocialCluster:
        """
        Greedy BFS cluster assignment.

        Starting from `user_id`, expands to all neighbours above the
        cluster similarity cutoff that share the same (or compatible)
        archetype, or are already in a cluster — joining that cluster.
        If none exist, creates a new cluster.
        """
        target: User = self.db.get(User, user_id)  # type: ignore[assignment]

        # Find neighbours above cluster cutoff
        sims: List[UserSimilarity] = (
            self.db.query(UserSimilarity)
            .filter(
                (
                    (UserSimilarity.user_a_id == user_id)
                    | (UserSimilarity.user_b_id == user_id)
                ),
                UserSimilarity.similarity_score >= CLUSTER_SIMILARITY_CUTOFF,
            )
            .all()
        )

        neighbour_ids = [
            sim.user_b_id if sim.user_a_id == user_id else sim.user_a_id
            for sim in sims
        ]

        # Check if any neighbour already has a cluster
        existing_cluster: Optional[SocialCluster] = (
            self.db.query(SocialCluster)
            .filter(SocialCluster.user_id.in_(neighbour_ids))
            .order_by(SocialCluster.member_count.desc())
            .first()
            if neighbour_ids
            else None
        )

        if existing_cluster:
            cluster_label = existing_cluster.cluster_label
            archetype_sig = existing_cluster.archetype_signature
        else:
            # Mint a new cluster label
            cluster_label = f"cluster_{uuid.uuid4().hex[:8]}"
            archetype_sig = target.archetype

        # Build centroid from this user's genome
        centroid = target.genome_vector or []

        membership = SocialCluster(
            cluster_label=cluster_label,
            user_id=user_id,
            archetype_signature=archetype_sig,
            centroid_vector=centroid,
            member_count=1,
        )
        self.db.add(membership)

        # Compute cohesion from stored similarities among cluster members
        cohesion: Optional[float] = None
        if sims:
            cohesion = round(
                sum(s.similarity_score for s in sims) / len(sims), 4
            )
            membership.cohesion_score = cohesion

        # Update member count on existing cluster rows
        if existing_cluster:
            (
                self.db.query(SocialCluster)
                .filter(SocialCluster.cluster_label == cluster_label)
                .update(
                    {
                        SocialCluster.member_count: SocialCluster.member_count + 1,
                        SocialCluster.cohesion_score: cohesion,
                    },
                    synchronize_session=False,
                )
            )

        self.db.commit()
        self.db.refresh(membership)
        return membership


# ---------------------------------------------------------------------------
# FastAPI Router
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/social",
    tags=["Gravity Network — Social Constellation"],
    responses={
        404: {"description": "Resource not found"},
        422: {"description": "Validation error"},
        500: {"description": "Internal server error"},
    },
)


@router.get(
    "/constellation",
    response_model=ConstellationResponse,
    summary="Get Gravity Network constellation",
    description=(
        "Returns a graph of nearby users (nodes) and their similarity connections "
        "(edges) for the Gravity Network visualisation.  The strongest edges are "
        "returned first, up to `limit`."
    ),
)
def get_constellation(
    limit: int = Query(100, ge=1, le=500, description="Max edges to return"),
    min_similarity: float = Query(
        SIMILARITY_THRESHOLD,
        ge=0.0,
        le=1.0,
        description="Minimum similarity score to include an edge",
    ),
    db: Session = Depends(get_db),
) -> ConstellationResponse:
    service = ConstellationService(db)
    return service.get_constellation(limit=limit, min_similarity=min_similarity)


@router.get(
    "/neighbors/{user_id}",
    response_model=NeighboursResponse,
    summary="Get most similar listeners",
    description=(
        "Returns the `limit` most musically similar users to the given user, "
        "ordered by composite similarity score (genome + archetype + shadow)."
    ),
)
def get_neighbours(
    user_id: Union[int, str],
    limit: int = Query(
        DEFAULT_NEIGHBOURS,
        ge=1,
        le=MAX_NEIGHBOURS,
        description="Number of neighbours to return",
    ),
    min_similarity: float = Query(
        SIMILARITY_THRESHOLD,
        ge=0.0,
        le=1.0,
        description="Minimum similarity threshold",
    ),
    recompute: bool = Query(
        False,
        description=(
            "If true, re-calculates similarity against all users before returning. "
            "Expensive — use only when the user's genome has changed."
        ),
    ),
    db: Session = Depends(get_db),
) -> NeighboursResponse:
    service = ConstellationService(db)
    return service.get_neighbours(
        user_id=user_id,
        limit=limit,
        min_similarity=min_similarity,
        recompute=recompute,
    )


@router.get(
    "/cluster/{user_id}",
    response_model=ClusterResponse,
    summary="Get user's musical community / cluster",
    description=(
        "Returns the cluster (community) the user belongs to, along with all "
        "other cluster members and the cluster's cohesion score. "
        "A cluster is auto-assigned on first request if none exists."
    ),
)
def get_cluster(
    user_id: Union[int, str],
    db: Session = Depends(get_db),
) -> ClusterResponse:
    service = ConstellationService(db)
    return service.get_cluster(user_id=user_id)


@router.get(
    "/stats",
    response_model=NetworkStats,
    summary="Get Gravity Network statistics",
    description=(
        "Returns aggregate network statistics: total users, total clusters, "
        "average similarity score, network density, most-connected archetype, "
        "and the number of orphan users (no similarity edges)."
    ),
)
def get_stats(
    db: Session = Depends(get_db),
) -> NetworkStats:
    service = ConstellationService(db)
    return service.get_stats()


# ---------------------------------------------------------------------------
# Utility: batch similarity computation (background job / CLI trigger)
# ---------------------------------------------------------------------------

def compute_all_similarities(db: Session, batch_size: int = 200) -> int:
    """
    Computes (or refreshes) pairwise similarities for all users.

    Designed to be called from a background task, Celery worker, or a
    management CLI command — NOT during a request/response cycle.

    Returns the number of similarity records written.
    """
    service = ConstellationService(db)
    users: List[User] = db.query(User).all()
    written = 0

    for i, user_a in enumerate(users):
        for user_b in users[i + 1 :]:
            scores = SimilarityEngine.compute(user_a, user_b)
            if scores["similarity_score"] >= SIMILARITY_THRESHOLD:
                service._upsert_similarity(user_a, user_b)
                written += 1
                if written % batch_size == 0:
                    db.commit()

    db.commit()
    return written


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------

def include_router(app: Any) -> None:
    """
    Call this from your main FastAPI app file:

        from social_constellation import include_router
        include_router(app)
    """
    app.include_router(router)
