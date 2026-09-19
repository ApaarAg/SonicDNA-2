"""
app_database.py
===============
SonicDNA — Unified SQLAlchemy 2.0 Persistence Layer for Supabase (PostgreSQL).

Consolidates all database access, models, connections, and domain operations.
Eliminates legacy MS SQL / pyodbc and provides robust pooling and native UUID support.
"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from dotenv import load_dotenv
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Uuid,
    create_engine,
    desc,
    func,
    or_,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker
from sqlalchemy.types import TypeDecorator


class GUID(TypeDecorator):
    """Platform-independent GUID/UUID type.
    Uses PostgreSQL native UUID type in PostgreSQL.
    Uses String(36) in SQLite and other dialects.
    Allows arbitrary test IDs without strict UUID hex validation failure.
    """
    impl = String(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=False))
        return dialect.type_descriptor(String(36))

    def process_bind_param(self, value, dialect):
        return str(value) if value is not None else None

    def process_result_value(self, value, dialect):
        return str(value) if value is not None else None

from persistence_sanitizer import (
    sanitize_playlist_for_persistence,
    sanitize_snapshot_payload,
)
from token_security import decrypt_token, encrypt_token

# ── Environment & Connection String ──────────────────────────────────────────
ENV_PATH = Path(__file__).parent / ".ENV"
load_dotenv(dotenv_path=ENV_PATH, override=False)


def resolve_database_url() -> str:
    raw = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DATABASE_URL") or ""
    raw = raw.strip().strip('"').strip("'")
    if not raw:
        raw = "postgresql+psycopg2://postgres.psfdwezsgypxxmfzmvfb:s7C%23%2F95C7qKjjU4@aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres"

    if raw.startswith("postgres://"):
        raw = raw.replace("postgres://", "postgresql+psycopg2://", 1)
    elif raw.startswith("postgresql://") and not raw.startswith("postgresql+"):
        raw = raw.replace("postgresql://", "postgresql+psycopg2://", 1)

    return raw


DATABASE_URL = resolve_database_url()

# ── SQLAlchemy Engine & Session Configuration ────────────────────────────────
_engine_kwargs: Dict[str, Any] = {
    "echo": False,
    "pool_pre_ping": True,
}

if not DATABASE_URL.startswith("sqlite"):
    _engine_kwargs.update({
        "pool_size": 10,
        "max_overflow": 20,
        "pool_recycle": 300,
    })

engine = create_engine(DATABASE_URL, **_engine_kwargs)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


# ── Dependency & Raw Connection ──────────────────────────────────────────────
def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a SQLAlchemy Session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_conn():
    """Compatibility context manager providing a raw DB connection with commit/rollback."""
    connection = engine.raw_connection()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


# ── ORM Models ───────────────────────────────────────────────────────────────

class User(Base):  # type: ignore[misc]
    """User ORM model with native UUID support and backward-compatible properties."""
    __tablename__ = "users"
    __table_args__ = {"extend_existing": True}

    id = Column(GUID(), primary_key=True, default=lambda: str(uuid.uuid4()))
    display_name = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True, index=True)
    archetype = Column(String(80), nullable=True)
    shadow_archetype = Column(String(80), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def username(self) -> Optional[str]:
        return self.display_name

    @username.setter
    def username(self, val: Optional[str]) -> None:
        self.display_name = val

    @property
    def genome_vector(self) -> list[float]:
        from sqlalchemy.orm import object_session
        session = object_session(self)
        if session:
            snap = (
                session.query(GenomeSnapshot)
                .filter(GenomeSnapshot.user_id == self.id)
                .order_by(GenomeSnapshot.taken_at.desc())
                .first()
            )
            if snap:
                try:
                    g = json.loads(snap.genome or "{}") if isinstance(snap.genome, str) else (snap.genome or {})
                    feats = ["danceability", "energy", "valence", "acousticness", "instrumentalness", "speechiness", "tempo"]
                    vec = []
                    for f in feats:
                        val = g.get(f, 0.0)
                        if val is None:
                            val = 0.0
                        val = float(val)
                        if f == "tempo" and val > 10:
                            val = (val - 120.0) / 35.0
                        vec.append(val)
                    return vec
                except Exception:
                    pass
        return [0.0] * 7


class SpotifyConnection(Base):
    __tablename__ = "spotify_connections"
    __table_args__ = {"extend_existing": True}

    id = Column(GUID(), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    spotify_user_id = Column(String(255), nullable=False)
    access_token = Column(Text, nullable=False)
    refresh_token = Column(Text, nullable=False)
    token_expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SpotifyTrack(Base):
    __tablename__ = "spotify_tracks"
    __table_args__ = {"extend_existing": True}

    id = Column(GUID(), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    spotify_track_id = Column(String(255), nullable=False)
    track_name = Column(String(255), nullable=False)
    artist_name = Column(String(255), nullable=False)
    album_name = Column(String(255), nullable=True)
    genres = Column(Text, nullable=True)
    danceability = Column(Float, nullable=True)
    energy = Column(Float, nullable=True)
    valence = Column(Float, nullable=True)
    acousticness = Column(Float, nullable=True)
    instrumentalness = Column(Float, nullable=True)
    speechiness = Column(Float, nullable=True)
    tempo = Column(Float, nullable=True)
    loudness = Column(Float, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    popularity = Column(Integer, nullable=True)
    is_top_track = Column(Boolean, default=True)
    time_range = Column(String(50), default="medium_term")
    imported_at = Column(DateTime, default=datetime.utcnow)


class GeneratedPlaylist(Base):
    __tablename__ = "generated_playlists"
    __table_args__ = {"extend_existing": True}

    id = Column(GUID(), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    playlist_name = Column(String(255), nullable=False)
    playlist_type = Column(String(100), default="genome_based")
    description = Column(Text, nullable=True)
    tracks = Column(Text, nullable=True)
    genome_snapshot_id = Column(GUID(), nullable=True)
    spotify_playlist_id = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class GenomeComparison(Base):
    __tablename__ = "genome_comparisons"
    __table_args__ = {"extend_existing": True}

    id = Column(GUID(), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_a_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    user_b_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    snapshot_a_id = Column(GUID(), nullable=True)
    snapshot_b_id = Column(GUID(), nullable=True)
    overall_similarity = Column(Float, nullable=True)
    genome_similarity = Column(Float, nullable=True)
    archetype_match = Column(Boolean, nullable=True)
    shared_genres = Column(Text, nullable=True)
    unique_to_a = Column(Text, nullable=True)
    unique_to_b = Column(Text, nullable=True)
    comparison_data = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class GenomeSnapshot(Base):
    __tablename__ = "genome_snapshots"
    __table_args__ = {"extend_existing": True}

    id = Column(GUID(), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    archetype_id = Column(Integer, nullable=True)
    archetype_name = Column(String(255), nullable=True)
    primary_pct = Column(Float, nullable=True)
    secondary_name = Column(String(255), nullable=True)
    secondary_pct = Column(Float, nullable=True)
    genome = Column(Text, nullable=True)
    region = Column(String(100), default="global_english")
    taken_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

    @property
    def timestamp(self):
        return self.taken_at

    @timestamp.setter
    def timestamp(self, val):
        self.taken_at = val

    @property
    def archetype(self):
        return self.archetype_name

    @archetype.setter
    def archetype(self, val):
        self.archetype_name = val

    @property
    def shadow_archetype(self):
        return self.secondary_name

    @shadow_archetype.setter
    def shadow_archetype(self, val):
        self.secondary_name = val

    @property
    def genome_data(self):
        return self.genome

    @genome_data.setter
    def genome_data(self, val):
        self.genome = val

    @property
    def genome_json(self):
        if not hasattr(self, "_parsed_genome"):
            if self.genome:
                try:
                    self._parsed_genome = json.loads(self.genome)
                except Exception:
                    self._parsed_genome = {}
            else:
                self._parsed_genome = {}
        return self._parsed_genome

    def _set_feature(self, key, value):
        js = self.genome_json
        js[key] = value
        self.genome = json.dumps(js)

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


class UserLocation(Base):
    __tablename__ = "user_locations"
    __table_args__ = {"extend_existing": True}

    id = Column(GUID(), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    city = Column(String(100), nullable=True, index=True)
    country = Column(String(100), nullable=True, index=True)
    region = Column(String(100), nullable=True)
    ip_address = Column(String(50), nullable=True)
    detected_at = Column(DateTime, default=datetime.utcnow)


class ShareLink(Base):
    __tablename__ = "share_links"
    __table_args__ = {"extend_existing": True}

    id = Column(GUID(), primary_key=True, default=lambda: str(uuid.uuid4()))
    share_code = Column(String(32), unique=True, nullable=False, index=True)
    inviter_user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    inviter_snapshot_id = Column(GUID(), nullable=True)
    invitee_user_id = Column(GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    invitee_snapshot_id = Column(GUID(), nullable=True)
    status = Column(String(20), default="pending")
    times_accessed = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)


class EmailQueue(Base):
    __tablename__ = "email_queue"
    __table_args__ = {"extend_existing": True}

    id = Column(GUID(), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    recipient_email = Column(String(255), nullable=False)
    subject = Column(String(500), nullable=False)
    body_html = Column(Text, nullable=False)
    email_type = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    sent_at = Column(DateTime, nullable=True)
    failed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    status = Column(String(50), default="pending", index=True)
    retry_count = Column(Integer, default=0)


# ── Table Migration & Schema Creation ─────────────────────────────────────────

def migrate_database() -> None:
    """Create and verify all database tables via SQLAlchemy metadata."""
    create_new_module_tables()


def create_new_module_tables() -> None:
    """Import all feature modules to register ORM models, then create all tables."""
    _safe_import_module_tables()
    try:
        Base.metadata.create_all(bind=engine, checkfirst=True)
        print("[startup.ok] Supabase/PostgreSQL schema verified and tables synchronized.")
    except Exception as exc:
        print(f"[startup.warn] Table creation failed: {exc}")


def _safe_import_module_tables() -> None:
    modules = [
        "social_constellation",
        "genome_evolution",
        "share_manager",
        "music_atlas",
        "leaderboards",
        "identity_narratives",
        "recommendations",
    ]
    for module_name in modules:
        try:
            __import__(module_name)
        except Exception as exc:
            print(f"[startup.warn] Could not import {module_name} for table creation: {exc}")


# ── Domain Persistence Functions ──────────────────────────────────────────────

def _decrypt_persisted_spotify_token(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        return decrypt_token(value)
    except ValueError as exc:
        print(f"[spotify.token.decrypt_failed] {exc}")
        return ""


def get_or_create_user(email: str, display_name: Optional[str] = None) -> dict:
    """Find a user by email or create them if they do not exist."""
    normalized_email = (email or "").strip().lower()
    with SessionLocal() as db:
        user = db.query(User).filter(func.lower(User.email) == normalized_email).first()
        if user:
            user.last_seen = datetime.utcnow()
            db.commit()
            return {
                "id": str(user.id),
                "email": user.email,
                "display_name": user.display_name,
                "created_at": user.created_at.isoformat() if user.created_at else None,
                "is_new": False,
            }

        new_id = str(uuid.uuid4())
        name = display_name or normalized_email.split("@")[0]
        user = User(
            id=new_id,
            email=normalized_email,
            display_name=name,
            created_at=datetime.utcnow(),
            last_seen=datetime.utcnow(),
        )
        db.add(user)
        db.commit()
        return {
            "id": new_id,
            "email": normalized_email,
            "display_name": name,
            "created_at": user.created_at.isoformat(),
            "is_new": True,
        }


def create_session_user(display_name: Optional[str] = None) -> dict:
    """Create an anonymous browser/session-scoped user."""
    new_id = str(uuid.uuid4())
    name = display_name or "Anonymous Listener"
    with SessionLocal() as db:
        user = User(
            id=new_id,
            email=f"anonymous+{new_id}@sonicdna.local",
            display_name=name,
            created_at=datetime.utcnow(),
            last_seen=datetime.utcnow(),
        )
        db.add(user)
        db.commit()

    return {
        "id": new_id,
        "email": None,
        "display_name": name,
        "created_at": datetime.utcnow().isoformat(),
        "is_new": True,
        "is_anonymous": True,
    }


def get_or_create_session_user(user_id: Optional[str] = None, display_name: Optional[str] = None) -> dict:
    """Reuse a known session user when valid, otherwise create a new one."""
    if user_id:
        existing = get_user_by_id(user_id)
        if existing:
            with SessionLocal() as db:
                user = db.query(User).filter(User.id == user_id).first()
                if user:
                    if display_name and display_name.strip() and user.display_name != display_name.strip():
                        user.display_name = display_name.strip()
                        existing["display_name"] = display_name.strip()
                    user.last_seen = datetime.utcnow()
                    db.commit()
            existing["is_new"] = False
            existing["is_anonymous"] = not existing.get("email") or str(existing.get("email")).endswith("@sonicdna.local")
            return existing

    return create_session_user(display_name)


def attach_email_to_session_user(user_id: str, email: str, display_name: Optional[str] = None) -> dict:
    """Attach or update email on an existing session user or merge session data."""
    normalized_email = (email or "").strip().lower()
    if not user_id or not normalized_email:
        raise ValueError("user_id and email are required")

    with SessionLocal() as db:
        current_user = db.query(User).filter(User.id == user_id).first()
        if not current_user:
            return get_or_create_user(normalized_email, display_name)

        existing_user = db.query(User).filter(
            func.lower(User.email) == normalized_email,
            User.id != user_id
        ).first()

        if existing_user:
            # Merge current session user's artifacts into the existing registered account
            target_id = existing_user.id
            db.query(GenomeSnapshot).filter(GenomeSnapshot.user_id == user_id).update({"user_id": target_id})
            db.query(SpotifyConnection).filter(SpotifyConnection.user_id == user_id).delete()
            db.query(SpotifyTrack).filter(SpotifyTrack.user_id == user_id).update({"user_id": target_id})
            db.query(GeneratedPlaylist).filter(GeneratedPlaylist.user_id == user_id).update({"user_id": target_id})
            db.query(ShareLink).filter(ShareLink.inviter_user_id == user_id).update({"inviter_user_id": target_id})
            db.query(ShareLink).filter(ShareLink.invitee_user_id == user_id).update({"invitee_user_id": target_id})
            db.query(UserLocation).filter(UserLocation.user_id == user_id).update({"user_id": target_id})
            db.delete(current_user)
            existing_user.last_seen = datetime.utcnow()
            db.commit()
            merged_info = get_user_by_id(str(target_id))
            if merged_info:
                merged_info["is_new"] = False
                merged_info["merged_from_session"] = True
                return merged_info
            return {"id": str(target_id), "email": normalized_email, "is_new": False, "merged_from_session": True}

        # No conflict: update current user email
        current_user.email = normalized_email
        if display_name and display_name.strip():
            current_user.display_name = display_name.strip()
        current_user.last_seen = datetime.utcnow()
        db.commit()

        user_info = get_user_by_id(user_id)
        if user_info:
            user_info["is_new"] = False
            user_info["merged_from_session"] = False
            return user_info
        return {"id": user_id, "email": normalized_email, "is_new": False, "merged_from_session": False}


def get_user_by_id(user_id: str) -> Optional[dict]:
    """Fetch a user by their UUID."""
    with SessionLocal() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return None
        return {
            "id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
            "archetype": user.archetype,
            "shadow_archetype": user.shadow_archetype,
            "last_seen": user.last_seen.isoformat() if user.last_seen else None,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        }


def find_user_by_display_name(display_name: str) -> Optional[dict]:
    """Find the most recently active user with a matching display name."""
    name = (display_name or "").strip()
    if not name:
        return None
    with SessionLocal() as db:
        user = (
            db.query(User)
            .filter(func.lower(func.trim(User.display_name)) == name.lower())
            .order_by(desc(func.coalesce(User.last_seen, User.created_at)))
            .first()
        )
        if not user:
            return None
        return {
            "id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        }


def get_user_by_spotify_id(spotify_user_id: str) -> Optional[dict]:
    """Fetch user dict by their connected Spotify User ID."""
    if not spotify_user_id:
        return None
    with SessionLocal() as db:
        conn = db.query(SpotifyConnection).filter(SpotifyConnection.spotify_user_id == spotify_user_id).first()
        if conn:
            user = db.query(User).filter(User.id == conn.user_id).first()
            if user:
                return {
                    "id": str(user.id),
                    "email": user.email,
                    "display_name": user.display_name,
                    "archetype": user.archetype,
                    "shadow_archetype": user.shadow_archetype,
                    "created_at": user.created_at.isoformat() if user.created_at else None,
                }
    return None


def get_or_create_user_from_spotify(
    spotify_user_id: str,
    display_name: Optional[str] = None,
    email: Optional[str] = None,
) -> dict:
    """
    Find existing user by Spotify ID or email, or provision a new User record via SQLAlchemy.
    Never duplicates user accounts.
    """
    existing_by_spotify = get_user_by_spotify_id(spotify_user_id)
    if existing_by_spotify:
        with SessionLocal() as db:
            user = db.query(User).filter(User.id == existing_by_spotify["id"]).first()
            if user:
                if display_name and display_name.strip() and not user.display_name:
                    user.display_name = display_name.strip()
                if email and not user.email:
                    user.email = email.strip().lower()
                user.last_seen = datetime.utcnow()
                db.commit()
        existing_by_spotify["is_new"] = False
        return existing_by_spotify

    normalized_email = (email or "").strip().lower()
    if normalized_email and not normalized_email.endswith("@sonicdna.local"):
        with SessionLocal() as db:
            existing_user = db.query(User).filter(func.lower(User.email) == normalized_email).first()
            if existing_user:
                existing_user.last_seen = datetime.utcnow()
                if display_name and not existing_user.display_name:
                    existing_user.display_name = display_name.strip()
                db.commit()
                return {
                    "id": str(existing_user.id),
                    "email": existing_user.email,
                    "display_name": existing_user.display_name,
                    "archetype": existing_user.archetype,
                    "shadow_archetype": existing_user.shadow_archetype,
                    "created_at": existing_user.created_at.isoformat() if existing_user.created_at else None,
                    "is_new": False,
                }

    new_id = str(uuid.uuid4())
    name = (display_name or "").strip() or f"Spotify User {spotify_user_id[:6]}"
    with SessionLocal() as db:
        user = User(
            id=new_id,
            email=normalized_email or f"spotify+{spotify_user_id}@sonicdna.local",
            display_name=name,
            created_at=datetime.utcnow(),
            last_seen=datetime.utcnow(),
        )
        db.add(user)
        db.commit()
        return {
            "id": new_id,
            "email": user.email,
            "display_name": name,
            "archetype": None,
            "shadow_archetype": None,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "is_new": True,
        }


def update_user_genome_profile(user_id: str, result: dict, region: str = "global_english") -> dict:
    """
    Perform an UPDATE on the existing User profile record (archetype, shadow_archetype, last_seen)
    and append a clean GenomeSnapshot. Ensures zero row duplication for the user.
    """
    sanitized = sanitize_snapshot_payload(result)
    raw_arch = sanitized.get("archetype")
    arch_dict = {"name": raw_arch} if isinstance(raw_arch, str) else (raw_arch if isinstance(raw_arch, dict) else {})

    dual_id = sanitized.get("dual_identity") if isinstance(sanitized.get("dual_identity"), dict) else {}
    sec_arch = dual_id.get("secondary_archetype")
    sec_dict = {"name": sec_arch} if isinstance(sec_arch, str) else (sec_arch if isinstance(sec_arch, dict) else {})

    primary_name = arch_dict.get("name") or sanitized.get("archetype_name")
    secondary_name = (
        sec_dict.get("name")
        or sanitized.get("secondary_name")
        or sanitized.get("shadow_archetype")
        or arch_dict.get("secondary_name")
    )

    with SessionLocal() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ValueError(f"User {user_id} does not exist for profile update.")
        user.archetype = primary_name
        user.shadow_archetype = secondary_name
        user.last_seen = datetime.utcnow()
        db.commit()

    snapshot_id = save_genome_snapshot(user_id, sanitized, region)
    return {
        "user_id": user_id,
        "archetype": primary_name,
        "shadow_archetype": secondary_name,
        "snapshot_id": snapshot_id,
        "updated": True,
    }


def latest_snapshot_id_for_user(user_id: str) -> Optional[str]:
    """Return the newest snapshot ID for a user."""
    with SessionLocal() as db:
        snap = (
            db.query(GenomeSnapshot.id)
            .filter(GenomeSnapshot.user_id == user_id)
            .order_by(desc(GenomeSnapshot.taken_at))
            .first()
        )
        return str(snap[0]) if snap else None


def save_spotify_connection(
    user_id: str,
    spotify_user_id: str,
    access_token: str,
    refresh_token: str,
    expires_in: int,
) -> str:
    """Save or update Spotify OAuth connection for a user."""
    expires_datetime = datetime.utcnow() + timedelta(seconds=int(expires_in or 3600))
    encrypted_access = encrypt_token(access_token)

    with SessionLocal() as db:
        existing = db.query(SpotifyConnection).filter(SpotifyConnection.user_id == user_id).first()
        if existing:
            persisted_refresh = _decrypt_persisted_spotify_token(existing.refresh_token)
            resolved_refresh = refresh_token or persisted_refresh
            existing.spotify_user_id = spotify_user_id
            existing.access_token = encrypted_access
            existing.refresh_token = encrypt_token(resolved_refresh)
            existing.token_expires_at = expires_datetime
            existing.updated_at = datetime.utcnow()
            conn_id = str(existing.id)
        else:
            conn_id = str(uuid.uuid4())
            new_conn = SpotifyConnection(
                id=conn_id,
                user_id=user_id,
                spotify_user_id=spotify_user_id,
                access_token=encrypted_access,
                refresh_token=encrypt_token(refresh_token),
                token_expires_at=expires_datetime,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(new_conn)
        db.commit()
        return conn_id


def delete_spotify_connection(user_id: str, clear_tracks: bool = True) -> bool:
    """Disconnect Spotify for a user and optionally clear cached tracks."""
    with SessionLocal() as db:
        if clear_tracks:
            db.query(SpotifyTrack).filter(SpotifyTrack.user_id == user_id).delete()
        count = db.query(SpotifyConnection).filter(SpotifyConnection.user_id == user_id).delete()
        db.commit()
        return bool(count)


def update_spotify_tokens(
    user_id: str,
    access_token: str,
    expires_in: int,
    refresh_token: Optional[str] = None,
) -> None:
    """Refresh stored Spotify tokens."""
    expires_datetime = datetime.utcnow() + timedelta(seconds=int(expires_in or 3600))
    encrypted_access = encrypt_token(access_token)

    with SessionLocal() as db:
        conn = db.query(SpotifyConnection).filter(SpotifyConnection.user_id == user_id).first()
        if conn:
            conn.access_token = encrypted_access
            conn.token_expires_at = expires_datetime
            conn.updated_at = datetime.utcnow()
            if refresh_token:
                conn.refresh_token = encrypt_token(refresh_token)
            db.commit()


def get_spotify_connection(user_id: str) -> Optional[dict]:
    """Get Spotify connection details for a user."""
    with SessionLocal() as db:
        conn = db.query(SpotifyConnection).filter(SpotifyConnection.user_id == user_id).first()
        if not conn:
            return None
        return {
            "id": str(conn.id),
            "spotify_user_id": conn.spotify_user_id,
            "access_token": _decrypt_persisted_spotify_token(conn.access_token),
            "refresh_token": _decrypt_persisted_spotify_token(conn.refresh_token),
            "token_expires_at": conn.token_expires_at.isoformat() if conn.token_expires_at else None,
            "created_at": conn.created_at.isoformat() if conn.created_at else None,
            "updated_at": conn.updated_at.isoformat() if conn.updated_at else None,
        }


def count_duplicate_spotify_connections() -> int:
    """Return duplicate Spotify connection count if any."""
    with SessionLocal() as db:
        subq = (
            db.query(SpotifyConnection.user_id, func.count(SpotifyConnection.id).label("cnt"))
            .group_by(SpotifyConnection.user_id)
            .having(func.count(SpotifyConnection.id) > 1)
            .subquery()
        )
        result = db.query(func.coalesce(func.sum(subq.c.cnt - 1), 0)).scalar()
        return int(result or 0)


def save_spotify_tracks(user_id: str, tracks: List[dict], time_range: str = "medium_term") -> None:
    """Save imported Spotify tracks with audio features."""
    with SessionLocal() as db:
        db.query(SpotifyTrack).filter(
            SpotifyTrack.user_id == user_id,
            SpotifyTrack.time_range == time_range,
        ).delete()

        for track in tracks:
            genres = track.get("genres") or track.get("artist_genres") or []
            if not isinstance(genres, str):
                genres = json.dumps(genres)
            st = SpotifyTrack(
                id=str(uuid.uuid4()),
                user_id=user_id,
                spotify_track_id=track.get("id", ""),
                track_name=track.get("name", "Unknown Track"),
                artist_name=track.get("artist", "Unknown Artist"),
                album_name=track.get("album"),
                genres=genres,
                danceability=track.get("danceability"),
                energy=track.get("energy"),
                valence=track.get("valence"),
                acousticness=track.get("acousticness"),
                instrumentalness=track.get("instrumentalness"),
                speechiness=track.get("speechiness"),
                tempo=track.get("tempo"),
                loudness=track.get("loudness"),
                duration_ms=track.get("duration_ms"),
                popularity=track.get("popularity"),
                is_top_track=track.get("is_top_track", True),
                time_range=time_range,
                imported_at=datetime.utcnow(),
            )
            db.add(st)
        db.commit()


def get_user_spotify_tracks(user_id: str, time_range: str = "medium_term") -> List[dict]:
    """Get user's imported Spotify tracks."""
    with SessionLocal() as db:
        rows = (
            db.query(SpotifyTrack)
            .filter(SpotifyTrack.user_id == user_id, SpotifyTrack.time_range == time_range)
            .order_by(desc(SpotifyTrack.imported_at))
            .all()
        )
        tracks = []
        for r in rows:
            try:
                genres = json.loads(r.genres) if r.genres else []
            except Exception:
                genres = [g.strip() for g in str(r.genres or "").split(",") if g.strip()]
            tracks.append({
                "id": r.spotify_track_id,
                "name": r.track_name,
                "artist": r.artist_name,
                "album": r.album_name,
                "genres": genres,
                "artist_genres": genres,
                "danceability": r.danceability,
                "energy": r.energy,
                "valence": r.valence,
                "acousticness": r.acousticness,
                "instrumentalness": r.instrumentalness,
                "speechiness": r.speechiness,
                "tempo": r.tempo,
                "loudness": r.loudness,
                "duration_ms": r.duration_ms,
                "popularity": r.popularity,
                "is_top_track": r.is_top_track,
                "imported_at": r.imported_at.isoformat() if r.imported_at else None,
            })
        return tracks


def save_generated_playlist(
    user_id: str,
    playlist_name: str,
    tracks: List[dict],
    playlist_type: str = "genome_based",
    description: Optional[str] = None,
    genome_snapshot_id: Optional[str] = None,
) -> str:
    """Save a generated playlist."""
    playlist_id = str(uuid.uuid4())
    persisted_tracks = sanitize_playlist_for_persistence(tracks)
    with SessionLocal() as db:
        pl = GeneratedPlaylist(
            id=playlist_id,
            user_id=user_id,
            playlist_name=playlist_name,
            playlist_type=playlist_type,
            description=description,
            tracks=json.dumps(persisted_tracks),
            genome_snapshot_id=genome_snapshot_id,
            created_at=datetime.utcnow(),
        )
        db.add(pl)
        db.commit()
    return playlist_id


def get_user_playlists(user_id: str) -> List[dict]:
    """Get all generated playlists for a user."""
    with SessionLocal() as db:
        rows = (
            db.query(GeneratedPlaylist)
            .filter(GeneratedPlaylist.user_id == user_id)
            .order_by(desc(GeneratedPlaylist.created_at))
            .all()
        )
        playlists = []
        for r in rows:
            playlists.append({
                "id": str(r.id),
                "name": r.playlist_name,
                "type": r.playlist_type,
                "description": r.description,
                "tracks": json.loads(r.tracks) if r.tracks else [],
                "spotify_playlist_id": r.spotify_playlist_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            })
        return playlists


def save_genome_comparison(
    user_a_id: str,
    user_b_id: str,
    snapshot_a_id: str,
    snapshot_b_id: str,
    comparison_result: dict,
) -> str:
    """Save a genome comparison between two users."""
    comparison_id = str(uuid.uuid4())
    with SessionLocal() as db:
        gc = GenomeComparison(
            id=comparison_id,
            user_a_id=user_a_id,
            user_b_id=user_b_id,
            snapshot_a_id=snapshot_a_id,
            snapshot_b_id=snapshot_b_id,
            overall_similarity=comparison_result.get("overall_similarity"),
            genome_similarity=comparison_result.get("genome_similarity"),
            archetype_match=comparison_result.get("archetype_match"),
            shared_genres=json.dumps(comparison_result.get("shared_genres", [])),
            unique_to_a=json.dumps(comparison_result.get("unique_to_a", [])),
            unique_to_b=json.dumps(comparison_result.get("unique_to_b", [])),
            comparison_data=json.dumps(comparison_result.get("detailed_comparison", {})),
            created_at=datetime.utcnow(),
        )
        db.add(gc)
        db.commit()
    return comparison_id


def get_genome_comparisons(user_id: str) -> List[dict]:
    """Get all genome comparisons involving a user."""
    with SessionLocal() as db:
        rows = (
            db.query(GenomeComparison)
            .filter(or_(GenomeComparison.user_a_id == user_id, GenomeComparison.user_b_id == user_id))
            .order_by(desc(GenomeComparison.created_at))
            .all()
        )
        comparisons = []
        for r in rows:
            comparisons.append({
                "id": str(r.id),
                "user_a_id": str(r.user_a_id),
                "user_b_id": str(r.user_b_id),
                "snapshot_a_id": str(r.snapshot_a_id) if r.snapshot_a_id else None,
                "snapshot_b_id": str(r.snapshot_b_id) if r.snapshot_b_id else None,
                "overall_similarity": r.overall_similarity,
                "genome_similarity": r.genome_similarity,
                "archetype_match": r.archetype_match,
                "shared_genres": json.loads(r.shared_genres) if r.shared_genres else [],
                "unique_to_a": json.loads(r.unique_to_a) if r.unique_to_a else [],
                "unique_to_b": json.loads(r.unique_to_b) if r.unique_to_b else [],
                "comparison_data": json.loads(r.comparison_data) if r.comparison_data else {},
                "created_at": r.created_at.isoformat() if r.created_at else None,
            })
        return comparisons


def save_genome_snapshot(user_id: str, result: dict, region: str = "global_english") -> str:
    """Save a genome analysis result as an immutable snapshot."""
    sanitized = sanitize_snapshot_payload(result)
    snapshot_id = str(uuid.uuid4())
    genome = result.get("genome_features") or result.get("genome") or {}
    raw_archetype = result.get("archetype")
    if isinstance(raw_archetype, str):
        archetype_dict = {"name": raw_archetype}
    elif isinstance(raw_archetype, dict):
        archetype_dict = raw_archetype
    else:
        archetype_dict = {}

    archetype_name = archetype_dict.get("name") or result.get("archetype_name")
    cluster_id = archetype_dict.get("cluster_id") or archetype_dict.get("id") or result.get("cluster_id") or 0

    dual_id = result.get("dual_identity") if isinstance(result.get("dual_identity"), dict) else {}
    sec_arch = dual_id.get("secondary_archetype")
    if isinstance(sec_arch, str):
        sec_arch_dict = {"name": sec_arch}
    elif isinstance(sec_arch, dict):
        sec_arch_dict = sec_arch
    else:
        sec_arch_dict = {}

    primary_pct = dual_id.get("primary_pct")
    if primary_pct is None:
        primary_pct = result.get("primary_pct")
    if primary_pct is None:
        primary_pct = archetype_dict.get("primary_pct")
    if primary_pct is None:
        primary_pct = 100.0

    secondary_name = (
        sec_arch_dict.get("name")
        or result.get("secondary_name")
        or archetype_dict.get("secondary_name")
        or result.get("shadow_archetype")
    )
    secondary_pct = dual_id.get("secondary_pct")
    if secondary_pct is None:
        secondary_pct = result.get("secondary_pct")
    if secondary_pct is None:
        secondary_pct = archetype_dict.get("secondary_pct")
    if secondary_pct is None:
        secondary_pct = 0.0

    with SessionLocal() as db:
        snap = GenomeSnapshot(
            id=snapshot_id,
            user_id=user_id,
            archetype_id=int(cluster_id) if cluster_id is not None else None,
            archetype_name=archetype_name,
            primary_pct=float(primary_pct) if primary_pct is not None else 100.0,
            secondary_name=secondary_name,
            secondary_pct=float(secondary_pct) if secondary_pct is not None else 0.0,
            genome=json.dumps(genome),
            region=region,
            taken_at=datetime.utcnow(),
            created_at=datetime.utcnow(),
        )
        db.add(snap)
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            if archetype_name:
                user.archetype = archetype_name
            if secondary_name:
                user.shadow_archetype = secondary_name
            user.last_seen = datetime.utcnow()
        db.commit()
    return snapshot_id


def get_snapshot_by_id(snapshot_id: str) -> Optional[dict]:
    """Fetch a single genome snapshot by its ID."""
    with SessionLocal() as db:
        row = db.query(GenomeSnapshot).filter(GenomeSnapshot.id == snapshot_id).first()
        if not row:
            return None
        try:
            genome = json.loads(row.genome) if row.genome else {}
        except Exception:
            genome = {}
        return {
            "id": str(row.id),
            "user_id": str(row.user_id),
            "archetype_id": row.archetype_id,
            "archetype_name": row.archetype_name,
            "primary_pct": row.primary_pct,
            "secondary_name": row.secondary_name,
            "secondary_pct": row.secondary_pct,
            "genome": genome,
            "region": row.region,
            "taken_at": row.taken_at.isoformat() if row.taken_at else None,
        }


def get_user_timeline(user_id: str) -> List[dict]:
    """Get all genome snapshots for a user, newest first."""
    with SessionLocal() as db:
        rows = (
            db.query(GenomeSnapshot)
            .filter(GenomeSnapshot.user_id == user_id)
            .order_by(desc(GenomeSnapshot.taken_at))
            .all()
        )
        snapshots = []
        for r in rows:
            try:
                genome = json.loads(r.genome) if r.genome else {}
            except Exception:
                genome = {}
            snapshots.append({
                "id": str(r.id),
                "archetype_id": r.archetype_id,
                "archetype_name": r.archetype_name,
                "primary_pct": r.primary_pct,
                "secondary_name": r.secondary_name,
                "secondary_pct": r.secondary_pct,
                "genome": genome,
                "region": r.region,
                "taken_at": r.taken_at.isoformat() if r.taken_at else None,
            })
        return snapshots


def create_share_link(
    inviter_user_id: str,
    snapshot_id: Optional[str] = None,
    expiry_days: int = 30,
) -> dict:
    """Create a share link for genome comparison."""
    link_id = str(uuid.uuid4())
    share_code = uuid.uuid4().hex[:12].upper()
    expires_at = datetime.utcnow() + timedelta(days=expiry_days)

    with SessionLocal() as db:
        link = ShareLink(
            id=link_id,
            share_code=share_code,
            inviter_user_id=inviter_user_id,
            inviter_snapshot_id=snapshot_id,
            expires_at=expires_at,
            created_at=datetime.utcnow(),
        )
        db.add(link)
        db.commit()

    return {
        "share_code": share_code,
        "expires_at": expires_at.isoformat(),
        "link_id": link_id,
    }


def get_share_link(share_code: str) -> Optional[dict]:
    """Fetch share link details by code."""
    with SessionLocal() as db:
        row = db.query(ShareLink).filter(ShareLink.share_code == share_code).first()
        if not row:
            return None
        return {
            "id": str(row.id),
            "share_code": row.share_code,
            "inviter_user_id": str(row.inviter_user_id) if row.inviter_user_id else None,
            "inviter_snapshot_id": str(row.inviter_snapshot_id) if row.inviter_snapshot_id else None,
            "invitee_user_id": str(row.invitee_user_id) if row.invitee_user_id else None,
            "invitee_snapshot_id": str(row.invitee_snapshot_id) if row.invitee_snapshot_id else None,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }


def complete_share_link(
    share_code: str,
    invitee_user_id: str,
    invitee_snapshot_id: Optional[str] = None,
) -> bool:
    """Complete a share link by recording the invitee details."""
    with SessionLocal() as db:
        link = db.query(ShareLink).filter(ShareLink.share_code == share_code).first()
        if not link:
            return False
        link.invitee_user_id = invitee_user_id
        link.invitee_snapshot_id = invitee_snapshot_id
        link.status = "completed"
        link.completed_at = datetime.utcnow()
        db.commit()
        return True


def get_user_share_links(user_id: str) -> List[dict]:
    """Get all share links created by a user."""
    with SessionLocal() as db:
        rows = (
            db.query(ShareLink)
            .filter(ShareLink.inviter_user_id == user_id)
            .order_by(desc(ShareLink.created_at))
            .all()
        )
        links = []
        for r in rows:
            links.append({
                "id": str(r.id),
                "share_code": r.share_code,
                "snapshot_id": str(r.inviter_snapshot_id) if r.inviter_snapshot_id else None,
                "has_invitee": bool(r.invitee_user_id),
                "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            })
        return links
