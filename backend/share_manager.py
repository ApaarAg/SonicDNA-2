"""
share_manager.py
================
SonicDNA — Share Manager Module

Manages share links, invite flows, compatibility requests, and public
identity sharing for SonicDNA's viral growth and social features.

Assumptions about the existing SonicDNA codebase
-------------------------------------------------
* A shared SQLAlchemy `Base`, `SessionLocal`, and `get_db` already exist
  (imported from `app.database`).
* A `User` ORM model already exists with at least:
    - id       : int (primary key)
    - username : str
    - archetype : str (optional)
* Environment variables:
    - DATABASE_URL      : already configured
    - SONIC_DNA_BASE_URL: public base URL used when constructing share URLs
                          (e.g. "https://sonicdna.app")
                          Falls back to "https://sonicdna.app" if unset.

New database objects introduced here
--------------------------------------
* ShareLink           — one row per generated share link
* CompatibilityInvite — one row per sent compatibility invite
"""

from __future__ import annotations

import os
import random
import secrets
import string
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, HttpUrl, field_validator, computed_field
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    and_,
    or_,
)
from sqlalchemy.exc import IntegrityError
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

BASE_URL: str = os.getenv("SONIC_DNA_BASE_URL", "https://sonicdna.app").rstrip("/")

# Share code alphabet — URL-safe, no ambiguous chars (0/O, 1/l/I)
_CODE_ALPHABET: str = string.ascii_letters.replace("O", "").replace("l", "").replace("I", "") + string.digits.replace("0", "").replace("1", "")
CODE_LENGTH: int = 10
MAX_COLLISION_RETRIES: int = 8

# Default link TTL (days). None = no expiry.
DEFAULT_LINK_TTL_DAYS: int = 30

# Invite statuses
class InviteStatus(str, Enum):
    PENDING   = "pending"
    ACCEPTED  = "accepted"
    DECLINED  = "declined"
    EXPIRED   = "expired"
    CANCELLED = "cancelled"

# Share link types
class ShareType(str, Enum):
    PROFILE       = "profile"         # share your SonicDNA identity page
    COMPATIBILITY = "compatibility"   # invite someone to compare genomes
    CHALLENGE     = "challenge"       # musical taste challenge
    CONSTELLATION = "constellation"   # share your gravity network view


# ---------------------------------------------------------------------------
# ORM Models
# ---------------------------------------------------------------------------

class ShareLink(Base):
    """
    A unique, short-code-based share link owned by a user.
    Immutable after creation except for analytics counters and is_active flag.
    """
    __tablename__ = "share_links_manager"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    user_id     = Column(USER_ID_TYPE, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    share_code  = Column(String(32), nullable=False, unique=True, index=True)
    share_url   = Column(String(512), nullable=False)
    share_type  = Column(String(32), nullable=False, default=ShareType.PROFILE)
    label       = Column(String(120), nullable=True)   # optional human label

    created_at  = Column(DateTime(timezone=True), nullable=False,
                         default=lambda: datetime.now(timezone.utc))
    expires_at  = Column(DateTime(timezone=True), nullable=True)

    # Analytics
    clicks      = Column(Integer, nullable=False, default=0)
    completions = Column(Integer, nullable=False, default=0)

    is_active   = Column(Boolean, nullable=False, default=True)

    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        Index("ix_sharelink_user_id",    "user_id"),
        Index("ix_sharelink_is_active",  "is_active"),
        Index("ix_sharelink_created_at", "created_at"),
    )


class CompatibilityInvite(Base):
    """
    A directed compatibility invite from one user to another.
    Created when a receiver follows a compatibility share link.
    """
    __tablename__ = "compatibility_invites"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    sender_id    = Column(USER_ID_TYPE, ForeignKey("users.id"), nullable=False)
    receiver_id  = Column(USER_ID_TYPE, ForeignKey("users.id"), nullable=True)
    share_code   = Column(String(32), nullable=False, index=True)
    status       = Column(String(32), nullable=False, default=InviteStatus.PENDING)

    created_at   = Column(DateTime(timezone=True), nullable=False,
                          default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime(timezone=True), nullable=True)

    sender   = relationship("User", foreign_keys=[sender_id])
    receiver = relationship("User", foreign_keys=[receiver_id])

    __table_args__ = (
        Index("ix_invite_sender",       "sender_id"),
        Index("ix_invite_receiver",     "receiver_id"),
        Index("ix_invite_status",       "status"),
        Index("ix_invite_share_code",   "share_code"),
        # A receiver may only have one pending invite per share code
        UniqueConstraint("receiver_id", "share_code", name="uq_invite_receiver_code"),
    )


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------

# --- Shared sub-schemas ---

class ShareLinkBase(BaseModel):
    share_type: ShareType = ShareType.PROFILE
    label:      Optional[str] = Field(None, max_length=120)
    expires_in_days: Optional[int] = Field(
        DEFAULT_LINK_TTL_DAYS,
        ge=1,
        le=365,
        description="TTL in days from now. Set to null for a permanent link.",
    )


# --- Requests ---

class ShareCreateRequest(ShareLinkBase):
    user_id: int


class ShareCompleteRequest(BaseModel):
    """
    Called by the receiving user's client when they finish a share flow.
    `receiver_user_id` is optional — the sharer may be anonymous at
    completion time (e.g. a public profile view).
    """
    receiver_user_id: Optional[int] = None


# --- Responses ---

class ShareLinkOut(BaseModel):
    id:           int
    user_id:      int
    share_code:   str
    share_url:    str
    share_type:   str
    label:        Optional[str]
    created_at:   datetime
    expires_at:   Optional[datetime]
    clicks:       int
    completions:  int
    is_active:    bool
    conversion_rate: float = Field(
        0.0, description="completions / clicks, or 0 if no clicks yet"
    )

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_with_rate(cls, link: ShareLink) -> "ShareLinkOut":
        rate = (link.completions / link.clicks) if link.clicks > 0 else 0.0
        obj = cls.model_validate(link)
        obj.conversion_rate = round(rate, 4)
        return obj


class MyLinksResponse(BaseModel):
    user_id:      int
    total:        int
    active_count: int
    links:        List[ShareLinkOut]


class ResolvedShareLink(BaseModel):
    share_code:   str
    share_url:    str
    share_type:   str
    owner_id:     int
    owner_username: Optional[str]
    owner_archetype: Optional[str]
    label:        Optional[str]
    is_active:    bool
    is_expired:   bool
    expires_at:   Optional[datetime]
    clicks:       int


class ShareStatsResponse(BaseModel):
    total_shares:      int
    total_active:      int
    total_clicks:      int
    total_completions: int
    conversion_rate:   float
    top_share_type:    Optional[str]
    computed_at:       datetime


class InviteOut(BaseModel):
    id:           int
    sender_id:    int
    receiver_id:  Optional[int]
    share_code:   str
    status:       str
    created_at:   datetime
    completed_at: Optional[datetime]
    sender_username:  Optional[str] = None
    sender_archetype: Optional[str] = None

    model_config = {"from_attributes": True}


class InviteListResponse(BaseModel):
    user_id:  int
    pending:  List[InviteOut]
    received: List[InviteOut]
    total:    int


class DeactivateResponse(BaseModel):
    share_code: str
    deactivated: bool
    message: str


# ---------------------------------------------------------------------------
# Code Generator
# ---------------------------------------------------------------------------

class ShareCodeGenerator:
    """
    Generates collision-resistant, URL-safe share codes.

    Uses cryptographic randomness (`secrets`) for unpredictability,
    combined with a retry loop that checks the database for collisions.
    """

    @staticmethod
    def generate() -> str:
        return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(CODE_LENGTH))

    @classmethod
    def generate_unique(cls, db: Session) -> str:
        for attempt in range(MAX_COLLISION_RETRIES):
            code = cls.generate()
            exists = (
                db.query(ShareLink.id)
                .filter(ShareLink.share_code == code)
                .first()
            )
            if not exists:
                return code
        # Probabilistically impossible, but handle gracefully
        raise RuntimeError(
            "Failed to generate a unique share code after "
            f"{MAX_COLLISION_RETRIES} attempts. "
            "Consider increasing CODE_LENGTH."
        )


# ---------------------------------------------------------------------------
# Service Layer
# ---------------------------------------------------------------------------

class ShareManagerService:
    """
    All business logic for share link management and compatibility invites.
    Keeps database writes and analytics fully decoupled from HTTP concerns.
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

    def _get_link_or_404(self, share_code: str) -> ShareLink:
        link = (
            self.db.query(ShareLink)
            .filter(ShareLink.share_code == share_code)
            .first()
        )
        if link is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Share code '{share_code}' not found.",
            )
        return link

    def _is_expired(self, link: ShareLink) -> bool:
        if link.expires_at is None:
            return False
        return datetime.now(timezone.utc) > link.expires_at

    def _build_share_url(self, code: str, share_type: ShareType) -> str:
        paths: Dict[ShareType, str] = {
            ShareType.PROFILE:       f"/share/{code}",
            ShareType.COMPATIBILITY: f"/compatibility/{code}",
            ShareType.CHALLENGE:     f"/challenge/{code}",
            ShareType.CONSTELLATION: f"/constellation/{code}",
        }
        return BASE_URL + paths.get(share_type, f"/share/{code}")

    # ------------------------------------------------------------------
    # Share link operations
    # ------------------------------------------------------------------

    def create_link(self, payload: ShareCreateRequest) -> ShareLink:
        user = self._get_user_or_404(payload.user_id)

        code      = ShareCodeGenerator.generate_unique(self.db)
        share_url = self._build_share_url(code, payload.share_type)

        expires_at: Optional[datetime] = None
        if payload.expires_in_days is not None:
            expires_at = datetime.now(timezone.utc) + timedelta(days=payload.expires_in_days)

        link = ShareLink(
            user_id    = payload.user_id,
            share_code = code,
            share_url  = share_url,
            share_type = payload.share_type,
            label      = payload.label,
            expires_at = expires_at,
        )
        self.db.add(link)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Share code collision — please retry.",
            )
        self.db.refresh(link)
        return link

    def get_my_links(
        self,
        user_id: int,
        include_inactive: bool = False,
    ) -> MyLinksResponse:
        self._get_user_or_404(user_id)

        q = self.db.query(ShareLink).filter(ShareLink.user_id == user_id)
        if not include_inactive:
            q = q.filter(ShareLink.is_active == True)  # noqa: E712
        links: List[ShareLink] = q.order_by(ShareLink.created_at.desc()).all()

        active_count = sum(1 for lnk in links if lnk.is_active and not self._is_expired(lnk))

        return MyLinksResponse(
            user_id      = user_id,
            total        = len(links),
            active_count = active_count,
            links        = [ShareLinkOut.from_orm_with_rate(lnk) for lnk in links],
        )

    def resolve_link(self, share_code: str) -> ResolvedShareLink:
        """
        Resolves a share code, increments the click counter, and returns
        the link metadata (including owner info) for the landing page.
        Does NOT raise on expired/inactive links — returns them with flags
        set so the frontend can render appropriate messaging.
        """
        link = self._get_link_or_404(share_code)

        # Increment click counter regardless of expiry / active state
        link.clicks += 1
        self.db.commit()

        owner: Optional[User] = self.db.get(User, link.user_id)

        return ResolvedShareLink(
            share_code       = link.share_code,
            share_url        = link.share_url,
            share_type       = link.share_type,
            owner_id         = link.user_id,
            owner_username   = owner.username if owner else None,
            owner_archetype  = getattr(owner, "archetype", None) if owner else None,
            label            = link.label,
            is_active        = link.is_active,
            is_expired       = self._is_expired(link),
            expires_at       = link.expires_at,
            clicks           = link.clicks,
        )

    def complete_share(
        self,
        share_code: str,
        payload: ShareCompleteRequest,
    ) -> Dict[str, Any]:
        """
        Marks a share flow as completed.
        - Increments the completion counter on the ShareLink.
        - Creates a CompatibilityInvite if the link is compatibility-type
          and a receiver_user_id is provided.
        """
        link = self._get_link_or_404(share_code)

        if not link.is_active:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="This share link has been deactivated.",
            )
        if self._is_expired(link):
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="This share link has expired.",
            )

        link.completions += 1

        invite_created: bool = False
        invite_id: Optional[int] = None

        if (
            link.share_type == ShareType.COMPATIBILITY
            and payload.receiver_user_id
            and payload.receiver_user_id != link.user_id
        ):
            # Avoid duplicate pending invites for the same pair + code
            existing_invite = (
                self.db.query(CompatibilityInvite)
                .filter(
                    CompatibilityInvite.share_code  == share_code,
                    CompatibilityInvite.receiver_id == payload.receiver_user_id,
                )
                .first()
            )
            if not existing_invite:
                invite = CompatibilityInvite(
                    sender_id   = link.user_id,
                    receiver_id = payload.receiver_user_id,
                    share_code  = share_code,
                    status      = InviteStatus.PENDING,
                )
                self.db.add(invite)
                self.db.flush()
                invite_created = True
                invite_id = invite.id

        self.db.commit()

        return {
            "share_code":      share_code,
            "completions":     link.completions,
            "invite_created":  invite_created,
            "invite_id":       invite_id,
            "completed_at":    datetime.now(timezone.utc).isoformat(),
        }

    def deactivate_link(self, share_code: str, requesting_user_id: int) -> DeactivateResponse:
        link = self._get_link_or_404(share_code)

        if link.user_id != requesting_user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not own this share link.",
            )
        if not link.is_active:
            return DeactivateResponse(
                share_code   = share_code,
                deactivated  = False,
                message      = "Link was already inactive.",
            )

        link.is_active = False
        self.db.commit()

        return DeactivateResponse(
            share_code   = share_code,
            deactivated  = True,
            message      = "Share link deactivated successfully.",
        )

    def get_share_stats(self, user_id: Optional[int] = None) -> ShareStatsResponse:
        """
        Returns aggregate share analytics.
        If `user_id` is provided, scopes stats to that user only;
        otherwise returns platform-wide stats.
        """
        q = self.db.query(ShareLink)
        if user_id is not None:
            self._get_user_or_404(user_id)
            q = q.filter(ShareLink.user_id == user_id)

        total_shares:      int   = q.count()
        total_active:      int   = q.filter(ShareLink.is_active == True).count()  # noqa: E712
        total_clicks:      int   = self.db.query(func.coalesce(func.sum(ShareLink.clicks),      0)).scalar() or 0
        total_completions: int   = self.db.query(func.coalesce(func.sum(ShareLink.completions), 0)).scalar() or 0
        conversion_rate:   float = round(total_completions / total_clicks, 4) if total_clicks > 0 else 0.0

        # Top share type by completion count
        top_type_row = (
            self.db.query(
                ShareLink.share_type,
                func.sum(ShareLink.completions).label("total_completions"),
            )
            .group_by(ShareLink.share_type)
            .order_by(func.sum(ShareLink.completions).desc())
            .first()
        )
        top_share_type: Optional[str] = top_type_row[0] if top_type_row else None

        return ShareStatsResponse(
            total_shares      = total_shares,
            total_active      = total_active,
            total_clicks      = total_clicks,
            total_completions = total_completions,
            conversion_rate   = conversion_rate,
            top_share_type    = top_share_type,
            computed_at       = datetime.now(timezone.utc),
        )

    # ------------------------------------------------------------------
    # Compatibility invite operations
    # ------------------------------------------------------------------

    def get_invites(self, user_id: int) -> InviteListResponse:
        """
        Returns all pending invites sent by or addressed to this user.
        """
        self._get_user_or_404(user_id)

        # Auto-expire any pending invites whose share link has expired
        expired_codes_q = (
            self.db.query(ShareLink.share_code)
            .filter(
                ShareLink.expires_at  < datetime.now(timezone.utc),
                ShareLink.is_active   == True,  # noqa: E712
            )
        )
        self.db.query(CompatibilityInvite).filter(
            CompatibilityInvite.status     == InviteStatus.PENDING,
            CompatibilityInvite.share_code.in_(expired_codes_q),
        ).update(
            {"status": InviteStatus.EXPIRED},
            synchronize_session=False,
        )
        self.db.commit()

        # Sent invites (user is sender)
        sent_invites: List[CompatibilityInvite] = (
            self.db.query(CompatibilityInvite)
            .filter(CompatibilityInvite.sender_id == user_id)
            .order_by(CompatibilityInvite.created_at.desc())
            .all()
        )

        # Received invites (user is receiver)
        received_invites: List[CompatibilityInvite] = (
            self.db.query(CompatibilityInvite)
            .filter(CompatibilityInvite.receiver_id == user_id)
            .order_by(CompatibilityInvite.created_at.desc())
            .all()
        )

        def _enrich(inv: CompatibilityInvite) -> InviteOut:
            out = InviteOut.model_validate(inv)
            sender: Optional[User] = self.db.get(User, inv.sender_id)
            if sender:
                out.sender_username  = sender.username
                out.sender_archetype = getattr(sender, "archetype", None)
            return out

        pending_sent = [_enrich(i) for i in sent_invites if i.status == InviteStatus.PENDING]

        return InviteListResponse(
            user_id  = user_id,
            pending  = pending_sent,
            received = [_enrich(i) for i in received_invites],
            total    = len(sent_invites) + len(received_invites),
        )


# ---------------------------------------------------------------------------
# FastAPI Router
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/share-manager",
    tags=["Share Manager"],
    responses={
        404: {"description": "Resource not found"},
        403: {"description": "Forbidden"},
        409: {"description": "Conflict"},
        410: {"description": "Gone — link expired or deactivated"},
        422: {"description": "Validation error"},
    },
)

compat_router = APIRouter(
    prefix="/compatibility",
    tags=["Compatibility Invites"],
)


# ---------------------------------------------------------------------------
# Share link endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/create",
    response_model=ShareLinkOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new share link",
    description=(
        "Generates a unique, URL-safe share code and constructs the full share URL. "
        "Supports profile, compatibility, challenge, and constellation share types. "
        "Optional TTL (days); omit `expires_in_days` for a permanent link."
    ),
)
def create_share_link(
    payload: ShareCreateRequest,
    db: Session = Depends(get_db),
) -> ShareLinkOut:
    service = ShareManagerService(db)
    link = service.create_link(payload)
    return ShareLinkOut.from_orm_with_rate(link)


@router.get(
    "/my-links",
    response_model=MyLinksResponse,
    summary="Return all share links for a user",
    description=(
        "Returns all share links owned by the given user, newest first. "
        "Pass `include_inactive=true` to include deactivated links."
    ),
)
def get_my_links(
    user_id: int = Query(..., description="The authenticated user's ID."),
    include_inactive: bool = Query(False, description="Include deactivated links."),
    db: Session = Depends(get_db),
) -> MyLinksResponse:
    service = ShareManagerService(db)
    return service.get_my_links(user_id=user_id, include_inactive=include_inactive)


@router.get(
    "/stats",
    response_model=ShareStatsResponse,
    summary="Return share analytics",
    description=(
        "Returns aggregate share statistics. "
        "Pass `user_id` to scope to a single user; "
        "omit for platform-wide stats (admin use)."
    ),
)
def get_share_stats(
    user_id: Optional[int] = Query(None, description="Scope to a specific user."),
    db: Session = Depends(get_db),
) -> ShareStatsResponse:
    service = ShareManagerService(db)
    return service.get_share_stats(user_id=user_id)


@router.get(
    "/{share_code}",
    response_model=ResolvedShareLink,
    summary="Resolve a share link",
    description=(
        "Resolves a share code to its metadata and increments the click counter. "
        "Returns owner info, link state, and expiry flags. "
        "Does not raise on expired/inactive links — flags are returned instead "
        "so the frontend can render appropriate messaging."
    ),
)
def resolve_share_link(
    share_code: str,
    db: Session = Depends(get_db),
) -> ResolvedShareLink:
    service = ShareManagerService(db)
    return service.resolve_link(share_code)


@router.post(
    "/{share_code}/complete",
    response_model=Dict[str, Any],
    summary="Mark a share flow as complete",
    description=(
        "Called by the receiving user's client when the share flow is finished. "
        "Increments the completion counter. "
        "For compatibility-type links, also creates a CompatibilityInvite record "
        "if `receiver_user_id` is provided."
    ),
)
def complete_share(
    share_code: str,
    payload: ShareCompleteRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    service = ShareManagerService(db)
    return service.complete_share(share_code=share_code, payload=payload)


@router.delete(
    "/{share_code}",
    response_model=DeactivateResponse,
    summary="Deactivate a share link",
    description=(
        "Soft-deactivates the share link. The link record is preserved for "
        "analytics; it simply stops accepting completions. "
        "Only the link owner may deactivate it."
    ),
)
def deactivate_share_link(
    share_code: str,
    requesting_user_id: int = Query(..., description="Must match the link owner's user ID."),
    db: Session = Depends(get_db),
) -> DeactivateResponse:
    service = ShareManagerService(db)
    return service.deactivate_link(
        share_code=share_code,
        requesting_user_id=requesting_user_id,
    )


# ---------------------------------------------------------------------------
# Compatibility invite endpoint
# ---------------------------------------------------------------------------

@compat_router.get(
    "/invites",
    response_model=InviteListResponse,
    summary="Return pending and received compatibility invites",
    description=(
        "Returns all compatibility invites for the given user: "
        "pending invites they have sent, and all invites they have received. "
        "Auto-expires any pending invites whose underlying share link has passed its TTL."
    ),
)
def get_invites(
    user_id: int = Query(..., description="The authenticated user's ID."),
    db: Session = Depends(get_db),
) -> InviteListResponse:
    service = ShareManagerService(db)
    return service.get_invites(user_id=user_id)


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------

def include_router(app: Any) -> None:
    """
    Call this from your main FastAPI app file:

        from share_manager import include_router
        include_router(app)
    """
    app.include_router(router)
    app.include_router(compat_router)
