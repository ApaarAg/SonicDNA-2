# ============================================
# MUSIC TASTE GENOME — Complete API v3.0
# Connects all backend services properly
# ============================================

import json
import base64
import hashlib
import hmac
import os,random
import re
import sys
import time
import traceback
from pathlib import Path
from typing import List, Optional, Dict
from datetime import datetime, timedelta
from contextlib import asynccontextmanager, contextmanager
from fastapi.responses import JSONResponse, RedirectResponse
import urllib.parse
from urllib.parse import urlparse
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from groq import Groq
from pydantic import BaseModel

# Load environment variables first. The project stores credentials in backend/.ENV,
# so load that exact file instead of relying on the process working directory.
ENV_PATH = Path(__file__).parent / ".ENV"
load_dotenv(dotenv_path=ENV_PATH)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── Import all services ──────────────────────
from app_database import (
    get_conn,
    get_or_create_user, save_genome_snapshot, get_user_timeline,
    get_user_by_id, get_snapshot_by_id, migrate_database,
    save_genome_comparison, get_genome_comparisons,
    get_spotify_connection, get_user_spotify_tracks,
    save_spotify_connection, save_spotify_tracks, update_spotify_tokens,
    delete_spotify_connection, count_duplicate_spotify_connections,
    get_or_create_session_user, latest_snapshot_id_for_user,
    find_user_by_display_name, attach_email_to_session_user,
    save_generated_playlist, get_user_playlists,
    get_or_create_user_from_spotify, update_user_genome_profile,
    get_taste_drift_history,
)

from engine import (
    ARCHETYPES, CLUSTER_CENTROIDS, GenomeEngine,
    RADAR_FEATURES, RADAR_LABELS, SHARED_FEATURES,
    analyze_clips_ratings, analyze_open_questions,
    analyze_quiz, _build_profile_from_genome,
    get_adaptive_clips, get_calibration_clips,
)
# SpotifyService from fixed module
from spotify_service_fixed import REGIONS, SpotifyService

from Compatibility import CompatibilityEngine, format_comparison_for_frontend

from Share_link import (
    create_share_links_table, generate_share_link,
    get_share_link_details, complete_share_link,
    get_user_share_links, invalidate_share_link,
    get_share_link_analytics, get_global_viral_stats
)

from Leaderboard import (
    create_city_tracking_table, save_user_location,
    get_city_archetype_distribution, get_top_cities_leaderboard,
    get_archetype_strongholds, get_global_archetype_distribution,
    compare_city_vs_global, generate_city_shareable_text,
    get_city_comparison_headline
)

from playlist_generator import PlaylistGenerator
from spotify_oauth_service import SpotifyOAuthService
from token_security import token_encryption_configured
from adaptive_questions import AdaptiveQuestionService
from clip_rotation import ClipAssetRotator, DynamicClipRotator, clip_distribution_diagnostics, select_round_clip_ids
from gemini_service import gemini_service
from feedback.feedback_models import make_feedback_subject_id, new_feedback_subject_id
from feedback.feedback_store import JsonlFeedbackStore

# ── Schema separation models (serialization boundary only) ────────────────
try:
    from models.response_models import PlaylistResponse
    from models.debug_models import (
        DebugPlayloadEnvelope, RecommendationTrace, FlowEvaluationReport
    )
    _MODELS_AVAILABLE = True
except ImportError:
    _MODELS_AVAILABLE = False  # pragma: no cover

from Email_service import (
    migrate_email_system, queue_email,
    send_comparison_complete_notification,
    send_retake_reminder, send_share_link_created_notification,
    process_email_queue
)
from email_scheduler import (
    start_email_scheduler,
    stop_email_scheduler,
    trigger_recalibration_reminders
)
from genome_verification import run_genome_verification

# ── Taste Drift / Evolution Engine ───────────────────────────────────────────
try:
    from taste_evolution import track_taste_drift, DRIFT_INTERVAL_DAYS as _DRIFT_INTERVAL_DAYS
    _TASTE_EVOLUTION_AVAILABLE = True
except Exception as _te_err:
    print(f"[startup.warn] taste_evolution unavailable: {_te_err}")
    track_taste_drift = None
    _DRIFT_INTERVAL_DAYS = 7
    _TASTE_EVOLUTION_AVAILABLE = False

# ── New Feature Module Routers ────────────────────────────────────────────────
# Each module already declares its own router prefix; we just include them.
try:
    from social_constellation import router as gravity_router
    _GRAVITY_AVAILABLE = True
except Exception as _e:
    print(f"[startup.warn] social_constellation unavailable: {_e}")
    gravity_router = None
    _GRAVITY_AVAILABLE = False

try:
    from genome_evolution import router as evolution_router
    _EVOLUTION_AVAILABLE = True
except Exception as _e:
    print(f"[startup.warn] genome_evolution unavailable: {_e}")
    evolution_router = None
    _EVOLUTION_AVAILABLE = False

try:
    from share_manager import router as share_mgr_router, compat_router as compat_invites_router
    _SHARE_MGR_AVAILABLE = True
except Exception as _e:
    print(f"[startup.warn] share_manager unavailable: {_e}")
    share_mgr_router = None
    compat_invites_router = None
    _SHARE_MGR_AVAILABLE = False

try:
    from music_atlas import router as atlas_router
    _ATLAS_AVAILABLE = True
except Exception as _e:
    print(f"[startup.warn] music_atlas unavailable: {_e}")
    atlas_router = None
    _ATLAS_AVAILABLE = False

try:
    from leaderboards import router as leaderboard_router
    _LEADERBOARD_AVAILABLE = True
except Exception as _e:
    print(f"[startup.warn] leaderboards unavailable: {_e}")
    leaderboard_router = None
    _LEADERBOARD_AVAILABLE = False

try:
    from identity_narratives import router as identity_router
    _IDENTITY_AVAILABLE = True
except Exception as _e:
    print(f"[startup.warn] identity_narratives unavailable: {_e}")
    identity_router = None
    _IDENTITY_AVAILABLE = False

try:
    from recommendations import router as recommendations_router
    _RECOMMENDATIONS_AVAILABLE = True
except Exception as _e:
    print(f"[startup.warn] recommendations unavailable: {_e}")
    recommendations_router = None
    _RECOMMENDATIONS_AVAILABLE = False

try:
    from app_database import create_new_module_tables
    _APP_DB_AVAILABLE = True
except Exception as _e:
    print(f"[startup.warn] app_database unavailable: {_e}")
    create_new_module_tables = None
    _APP_DB_AVAILABLE = False

# ── Paths ─────────────────────────────────────
DATA_DIR = Path(__file__).parent / "data"
STATIC_DIR = Path(__file__).parent / "static"
CLIPS_DIR = DATA_DIR / "clips"


LOCAL_FRONTEND_FALLBACK = "http://localhost:5500/frontend/index.html"
INSECURE_SESSION_SECRETS = {
    "",
    "sonicdna-local-session-secret",
    "change-me",
    "changeme",
    "secret",
    "password",
}


def _app_environment() -> str:
    return (os.getenv("SONICDNA_ENV") or os.getenv("APP_ENV") or os.getenv("ENV") or "development").lower()


def _is_production_environment() -> bool:
    return _app_environment() in {"production", "prod"}


def _frontend_url() -> Optional[str]:
    return os.getenv("SONICDNA_FRONTEND_URL") or os.getenv("FRONTEND_URL")


def _origin_from_url(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def _split_csv_env(value: Optional[str]) -> List[str]:
    return [item.strip().rstrip("/") for item in (value or "").split(",") if item.strip()]


def _cors_origins() -> List[str]:
    raw_frontend = os.getenv("FRONTEND_URL") or os.getenv("SONICDNA_FRONTEND_URL") or ""
    frontend_origins = []
    for item in _split_csv_env(raw_frontend):
        orig = _origin_from_url(item) or item
        if orig and orig not in frontend_origins:
            frontend_origins.append(orig)

    configured = _split_csv_env(os.getenv("CORS_ALLOW_ORIGINS"))
    combined = []
    for item in frontend_origins + configured:
        orig = _origin_from_url(item) or item
        if orig and orig not in combined:
            combined.append(orig)

    if _is_production_environment():
        # Strictly accept domains specified in FRONTEND_URL / CORS_ALLOW_ORIGINS; exclude '*' and 'null'
        return [orig for orig in combined if orig != "*" and orig != "null"]

    # In development/test, return configured origins or wildcard without appending 'null'
    origins = [orig for orig in combined if orig != "null"]
    return origins or ["*"]



def _redact_for_log(value: object) -> str:
    text = str(value)
    text = re.sub(
        r"(?i)(authorization\s*:\s*bearer\s+)[A-Za-z0-9._~+/=-]+",
        r"\1[redacted]",
        text,
    )
    text = re.sub(
        r"(?i)([\"']?\b(?:access_token|refresh_token|client_secret|SESSION_TOKEN_SECRET|SPOTIFY_TOKEN_ENCRYPTION_KEY)\b[\"']?\s*[:=]\s*[\"']?)[^,\"'\s&}]+",
        r"\1[redacted]",
        text,
    )
    return text


def _is_local_url(value: Optional[str]) -> bool:
    parsed = urlparse(value or "")
    host = (parsed.hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local")


def _is_https_url(value: Optional[str]) -> bool:
    return urlparse(value or "").scheme == "https"


def validate_deployment_environment() -> dict:
    env = _app_environment()
    production = _is_production_environment()
    errors = []
    warnings = []

    session_secret = os.getenv("SESSION_TOKEN_SECRET") or ""
    spotify_redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI") or ""
    frontend_url = _frontend_url() or ""
    cors_origins = _split_csv_env(os.getenv("CORS_ALLOW_ORIGINS"))

    if not session_secret:
        message = "SESSION_TOKEN_SECRET is not set; session tokens will use an unsafe fallback."
        (errors if production else warnings).append(message)
    elif session_secret.strip().lower() in INSECURE_SESSION_SECRETS or len(session_secret) < 32:
        message = "SESSION_TOKEN_SECRET is too weak for production session signing."
        (errors if production else warnings).append(message)

    if not spotify_redirect_uri:
        message = "SPOTIFY_REDIRECT_URI is not set; Spotify OAuth callbacks may fail."
        (errors if production else warnings).append(message)
    elif production and (not _is_https_url(spotify_redirect_uri) or _is_local_url(spotify_redirect_uri)):
        errors.append("SPOTIFY_REDIRECT_URI must be a public HTTPS URL in production.")

    if not frontend_url:
        message = "FRONTEND_URL or SONICDNA_FRONTEND_URL is not set; OAuth redirects will use a local fallback."
        (errors if production else warnings).append(message)
    elif production and (not _is_https_url(frontend_url) or _is_local_url(frontend_url)):
        errors.append("FRONTEND_URL / SONICDNA_FRONTEND_URL must be a public HTTPS URL in production.")

    if production and "*" in cors_origins:
        errors.append("CORS_ALLOW_ORIGINS must not include '*' in production.")
    if production and not _cors_origins():
        errors.append("Production CORS has no allowed origins configured.")

    if not token_encryption_configured():
        message = "SPOTIFY_TOKEN_ENCRYPTION_KEY is not set; token encryption uses a development fallback key."
        (errors if production else warnings).append(message)

    return {
        "environment": env,

        "production": production,
        "errors": errors,
        "warnings": warnings,
        "cors_origins": _cors_origins(),
    }


def enforce_deployment_environment() -> dict:
    report = validate_deployment_environment()
    for warning in report["warnings"]:
        print(f"[startup.config.warning] {warning}")
    for error in report["errors"]:
        print(f"[startup.config.error] {error}")
    if report["production"] and report["errors"]:
        raise RuntimeError("Unsafe production configuration: " + "; ".join(report["errors"]))
    try:
        duplicates = count_duplicate_spotify_connections()
        if duplicates:
            print(f"[startup.spotify.warning] duplicate_spotify_connections={duplicates}")
    except Exception as exc:
        print(f"[startup.spotify.warning] duplicate_check_failed={_redact_for_log(exc)}")
    return report


def _production_safe_detail(prefix: str, exc: Exception) -> str:
    """Return a generic error message in production, detailed one in development."""
    if _is_production_environment():
        return f"{prefix}."
    return f"{prefix}: {_redact_for_log(exc)}"


def _record_latency(metric: str, duration_ms: float, context: Optional[str] = None) -> None:
    try:
        from monitoring.metrics_store import get_store
        get_store().record_latency(metric, duration_ms)
    except Exception:
        pass
    label = f" context={context}" if context else ""
    print(f"[latency] metric={metric}{label} duration_ms={duration_ms:.2f}")


@contextmanager
def _latency_span(metric: str, context: Optional[str] = None):
    start = time.perf_counter()
    try:
        yield
    finally:
        _record_latency(metric, (time.perf_counter() - start) * 1000, context=context)

# ══════════════════════════════════════════════
# LIFESPAN HANDLER (replaces on_startup/on_shutdown)
# ══════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Modern FastAPI lifespan handler.
    Runs migrations and initialization on startup.
    """
    # STARTUP
    enforce_deployment_environment()
    print("[startup] Running database migrations...")
    try:
        migrate_database()
        print("[startup.ok] Database migrations complete")
    except Exception as e:
        print(f"[startup.warn] Database migration failed: {e}")
    
    try:
        create_share_links_table()
        print("[startup.ok] Share links table ready")
    except Exception as e:
        print(f"[startup.warn] Share links table creation failed: {e}")
    
    try:
        create_city_tracking_table()
        print("[startup.ok] City tracking table ready")
    except Exception as e:
        print(f"[startup.warn] City tracking table creation failed: {e}")
    
    try:
        migrate_email_system()
        print("[startup.ok] Email system migrated")
    except Exception as e:
        print(f"[startup.warn] Email system migration failed: {e}")

    # Create tables for new feature modules (SQLAlchemy-based)
    if create_new_module_tables:
        try:
            create_new_module_tables()
        except Exception as e:
            print(f"[startup.warn] New module table creation failed: {e}")

    try:
        start_email_scheduler()
        print("[startup.ok] Background email reminder scheduler started")
    except Exception as e:
        print(f"[startup.warn] Failed to start email scheduler: {e}")

    # ── Taste Drift background loop ──────────────────────────────────────
    _drift_stop_event: asyncio.Event = asyncio.Event()

    async def _drift_loop() -> None:
        """Repeating asyncio task: runs track_taste_drift() every DRIFT_INTERVAL_DAYS."""
        interval_secs = _DRIFT_INTERVAL_DAYS * 86_400
        while not _drift_stop_event.is_set():
            try:
                if track_taste_drift is not None:
                    await track_taste_drift()
            except Exception as _drift_exc:
                print(f"[drift.warn] Unhandled error in drift loop: {_drift_exc}")
            try:
                await asyncio.wait_for(
                    _drift_stop_event.wait(), timeout=float(interval_secs)
                )
            except asyncio.TimeoutError:
                pass  # Normal: interval elapsed, run again

    _drift_task: Optional[asyncio.Task] = None
    if _TASTE_EVOLUTION_AVAILABLE:
        try:
            _drift_task = asyncio.create_task(_drift_loop())
            print(
                f"[startup.ok] Taste drift scheduler started "
                f"(interval={_DRIFT_INTERVAL_DAYS}d)"
            )
        except Exception as _e:
            print(f"[startup.warn] Taste drift scheduler failed to start: {_e}")
            _drift_task = None

    yield  # App runs here

    # SHUTDOWN
    print("[shutdown] Shutting down gracefully...")
    # Stop drift loop
    _drift_stop_event.set()
    if _drift_task and not _drift_task.done():
        try:
            await asyncio.wait_for(_drift_task, timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            _drift_task.cancel()
    print("[shutdown.ok] Taste drift scheduler stopped")

    try:
        stop_email_scheduler()
        print("[shutdown.ok] Background email scheduler stopped")
    except Exception as e:
        print(f"[shutdown.warn] Error stopping email scheduler: {e}")

# ── Initialize FastAPI App ────────────────────
app = FastAPI(
    title="Music Taste Genome API",
    version="3.0.0",
    description="Complete API with Compatibility, Leaderboards, and Social Features",
    lifespan=lifespan  # ← FIX: Use modern lifespan instead of on_startup
)


@app.middleware("http")
async def production_safety_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if _is_production_environment() and request.url.scheme == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")

    path = request.url.path
    if path.startswith(("/user", "/spotify", "/share", "/feedback", "/admin", "/health", "/ready")):
        response.headers.setdefault("Cache-Control", "no-store")
    elif path.startswith(("/audio", "/static")):
        response.headers.setdefault("Cache-Control", "public, max-age=86400")
    return response


# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static file mounts
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

if CLIPS_DIR.exists():
    app.mount("/audio", StaticFiles(directory=str(CLIPS_DIR)), name="audio")

# ── Register new feature module routers ──────────────────────────────────────
if _GRAVITY_AVAILABLE and gravity_router:
    app.include_router(gravity_router)
    print("[startup.ok] Gravity Network router registered (/social/...)")

if _EVOLUTION_AVAILABLE and evolution_router:
    app.include_router(evolution_router)
    print("[startup.ok] Genome Evolution router registered (/evolution/...)")

if _SHARE_MGR_AVAILABLE and share_mgr_router:
    app.include_router(share_mgr_router)
    print("[startup.ok] Share Manager router registered (/share/...)")

if _SHARE_MGR_AVAILABLE and compat_invites_router:
    app.include_router(compat_invites_router)
    print("[startup.ok] Compatibility Invites router registered (/compatibility/...)")

if _ATLAS_AVAILABLE and atlas_router:
    app.include_router(atlas_router)
    print("[startup.ok] Music Atlas router registered (/atlas/...)")

if _LEADERBOARD_AVAILABLE and leaderboard_router:
    app.include_router(leaderboard_router)
    print("[startup.ok] Leaderboard router registered (/leaderboard/...)")

if _IDENTITY_AVAILABLE and identity_router:
    app.include_router(identity_router)
    print("[startup.ok] Identity Narratives router registered (/identity/...)")

if _RECOMMENDATIONS_AVAILABLE and recommendations_router:
    app.include_router(recommendations_router)
    print("[startup.ok] Recommendations router registered (/recommendations/...)")

# ── Initialize Services ───────────────────────

print("[startup] Initializing services...")

try:
    engine = GenomeEngine(lazy=True)
    print("[startup.ok] GenomeEngine loaded")
except Exception as e:
    print(f"[startup.warn] GenomeEngine initialization failed: {e}")
    engine = None

try:
    spotify = SpotifyService()
    print("[startup.ok] SpotifyService authenticated")
except Exception as e:
    print(f"[startup.warn] SpotifyService initialization failed: {e}")
    spotify = None

try:
    groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    print("[startup.ok] Groq client ready")
except Exception as e:
    print(f"[startup.warn] Groq client initialization failed: {e}")
    groq_client = None

# Initialize Phase 2 engines
compatibility_engine = CompatibilityEngine()
playlist_generator = PlaylistGenerator(spotify_service=spotify) if spotify else PlaylistGenerator()
adaptive_question_service = AdaptiveQuestionService.from_env()

print("[startup.ok] All engines initialized")

# ── Load clip metadata ────────────────────────
CLIP_FEATURES_PATH = DATA_DIR / "clip_features.json"
CLIP_FEATURES: dict = {}
if CLIP_FEATURES_PATH.exists():
    with open(CLIP_FEATURES_PATH, encoding="utf-8") as f:
        CLIP_FEATURES = json.load(f)
    print(f"[startup.ok] Loaded {len(CLIP_FEATURES)} clip features")

# ════════════════════════════════════════════
# PYDANTIC MODELS
# ════════════════════════════════════════════

class QuizPayload(BaseModel):
    answers: List[int]

class OpenQuizPayload(BaseModel):
    q1: str
    q2: str = ""
    q3: str = ""
    region: str = "global_english"

class AdaptiveOpenPayload(BaseModel):
    answers: List[str]
    clip_ratings: List[dict] = []
    region: str = "global_english"
    session_token: Optional[str] = None
    user_id: Optional[str] = None

class ClipRating(BaseModel):
    clip_id: str
    rating: int

class ClipRatingsPayload(BaseModel):
    ratings: List[ClipRating]
    region: str = "global_english"
    session_token: Optional[str] = None
    user_id: Optional[str] = None

class AdaptiveQuestionPayload(BaseModel):
    previous_answers: List[str]
    clip_ratings: List[dict]
    covered_dimensions: List[str] = []
    asked_questions: List[str] = []

class AdaptiveClipsPayload(BaseModel):
    existing_ratings: List[dict]
    round_number: int = 2
    session_key: Optional[str] = None

class UserPayload(BaseModel):
    email: str
    display_name: Optional[str] = None

class SessionUserPayload(BaseModel):
    session_token: Optional[str] = None
    user_id: Optional[str] = None
    display_name: Optional[str] = None
    email: Optional[str] = None
    requested_minutes: Optional[int] = None
    target_minutes: Optional[int] = None
    session_type: Optional[str] = None

class SaveSpotifyTrackPayload(BaseModel):
    session_token: str
    track_id: str

class SaveSnapshotPayload(BaseModel):
    session_token: Optional[str] = None
    user_id: Optional[str] = None
    result: dict
    region: str = "global_english"

class CompareUsersPayload(BaseModel):
    session_token: Optional[str] = None
    share_code: Optional[str] = None
    display_name: Optional[str] = None
    user_a_id: Optional[str] = None
    user_b_id: Optional[str] = None
    snapshot_a_id: Optional[str] = None
    snapshot_b_id: Optional[str] = None

class ShareLinkPayload(BaseModel):
    session_token: Optional[str] = None
    user_id: Optional[str] = None
    snapshot_id: Optional[str] = None
    expiry_days: int = 30

class CompleteShareLinkPayload(BaseModel):
    share_code: str
    session_token: Optional[str] = None
    invitee_user_id: Optional[str] = None
    invitee_snapshot_id: Optional[str] = None

class LocationPayload(BaseModel):
    user_id: str
    city: str
    country: Optional[str] = None
    region: Optional[str] = None
    ip_address: Optional[str] = None

class PlaylistTrialPayload(BaseModel):
    genome: Dict[str, float]
    playlist_size: int = 12
    target_minutes: Optional[int] = 30
    mode: str = "regional"
    cluster_id: int = 3
    region_key: str = "global_english"
    discovery_ratio: float = 0.5
    mood: Optional[str] = None
    exploration_factor: float = 0.3
    include_explanations: bool = False
    session_type: Optional[str] = None   # flow-engine sequencing profile

class FeedbackEventsPayload(BaseModel):
    session_token: Optional[str] = None
    session_id: Optional[str] = None
    feedback_subject_id: Optional[str] = None
    events: List[dict]


clip_rotator = DynamicClipRotator(CLIP_FEATURES, CLIPS_DIR)
SESSION_SECRET = os.getenv("SESSION_TOKEN_SECRET") or os.getenv("GROQ_API_KEY") or "sonicdna-local-session-secret"
spotify_oauth = SpotifyOAuthService(SESSION_SECRET)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def make_session_token(user_id: str) -> str:
    payload = _b64(str(user_id).lower().encode("ascii"))
    sig = hmac.new(SESSION_SECRET.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).digest()
    return f"sd1.{payload}.{_b64(sig)}"


def resolve_session_token(session_token: Optional[str]) -> Optional[str]:
    if not session_token:
        return None
    try:
        prefix, payload, sig = session_token.split(".", 2)
        if prefix != "sd1":
            return None
        expected = hmac.new(SESSION_SECRET.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64(expected), sig):
            return None
        user_id = _unb64(payload).decode("ascii")
        return user_id if get_user_by_id(user_id) else None
    except Exception:
        return None


def public_user(user: dict) -> dict:
    return {
        "display_name": user.get("display_name") or "Anonymous Listener",
        "is_anonymous": not user.get("email") or str(user.get("email")).endswith("@sonicdna.local"),
    }


def issue_public_session(user: dict) -> dict:
    source_id = str(user.get("id", "")).replace("-", "").upper()
    profile_code = f"SD-{source_id[:6]}" if source_id else "SD-ANON"
    return {
        "session_token": make_session_token(user["id"]),
        "display_name": user.get("display_name") or "Anonymous Listener",
        "email": user.get("email"),
        "profile_code": profile_code,
        "is_new": bool(user.get("is_new")),
        "is_anonymous": bool(user.get("is_anonymous", not user.get("email"))),
    }


def resolve_payload_user(session_token: Optional[str] = None, user_id: Optional[str] = None) -> Optional[str]:
    return resolve_session_token(session_token) or user_id


def _feedback_events_path() -> Path:
    configured = os.getenv("SONICDNA_FEEDBACK_EVENTS_PATH")
    return Path(configured) if configured else DATA_DIR / "feedback_events.jsonl"


def _feedback_subject_for(payload: FeedbackEventsPayload) -> str:
    user_id = resolve_session_token(payload.session_token)
    if user_id:
        return make_feedback_subject_id(user_id)
    if payload.feedback_subject_id:
        return str(payload.feedback_subject_id)
    if payload.session_id or payload.session_token:
        return make_feedback_subject_id(payload.session_id or payload.session_token or "")
    return new_feedback_subject_id()


def _safe_feedback_event(raw_event: dict, *, subject: str, session_id: str) -> dict:
    allowed_keys = {
        "event_type",
        "playlist_id",
        "track_id",
        "track_name",
        "artist",
        "position",
        "skip_after_ms",
        "replay_count",
        "source",
        "is_exploration",
        "client_context",
    }
    event = {key: value for key, value in dict(raw_event).items() if key in allowed_keys and value is not None}
    event_type = str(event.get("event_type") or "client_event").strip().lower()
    if not re.match(r"^[a-z0-9_:-]{1,80}$", event_type):
        event_type = "client_event"
    context = event.get("client_context") if isinstance(event.get("client_context"), dict) else {}
    event["event_type"] = event_type
    event["client_context"] = {
        key: value
        for key, value in context.items()
        if isinstance(key, str) and len(key) <= 64
    }
    event["feedback_subject_id"] = subject
    event["session_id"] = session_id
    event["timestamp"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    event["privacy"] = {
        "canonical_identity_stored": False,
        "stores_raw_profile": False,
        "intended_use": "offline_analysis_only",
    }
    return event


def _redirect_with_spotify_status(
    return_to: Optional[str],
    status: str,
    detail: str = "",
    session_token: Optional[str] = None,
) -> RedirectResponse:
    base_url = (
        return_to
        or _frontend_url()
        or LOCAL_FRONTEND_FALLBACK
    )
    separator = "&" if "?" in base_url else "?"
    query_params = {"spotify": status}
    if detail:
        query_params["detail"] = detail[:80]
    if session_token:
        query_params["session_token"] = session_token
    params = urllib.parse.urlencode(query_params)
    return RedirectResponse(f"{base_url}{separator}{params}")


def _average_tracks(tracks: List[dict], key: str, default: float = 0.5) -> float:
    values = [float(t.get(key)) for t in tracks if t.get(key) is not None]
    return round(sum(values) / len(values), 3) if values else default


def _regional_affinity_from_genres(genres: List[str]) -> str:
    text = " ".join(genres or []).lower()
    markers = {
        "india": ["bollywood", "tamil", "telugu", "punjabi", "desi", "indian", "hindi"],
        "latin_america": ["latin", "reggaeton", "salsa", "bachata"],
        "korea": ["k-pop", "korean"],
        "japan": ["j-pop", "japanese"],
        "arab_world": ["arab", "khaleeji", "egyptian"],
        "africa": ["afrobeats", "afropop", "amapiano", "naija"],
    }
    for region, terms in markers.items():
        if any(term in text for term in terms):
            return region
    return "global"


def _cached_spotify_taste_profile(user_id: str) -> Optional[dict]:
    try:
        tracks = get_user_spotify_tracks(user_id)
    except Exception as e:
        print(f"[spotify.taste.cache_error] user_id={user_id} error={_redact_for_log(e)}")
        return None
    if not tracks:
        return None

    genre_counts = {}
    artists = []
    for track in tracks:
        artist = track.get("artist")
        if artist and artist not in artists:
            artists.append(artist)
        for genre in track.get("genres") or []:
            genre_counts[genre] = genre_counts.get(genre, 0) + 1
    genres = [g for g, _ in sorted(genre_counts.items(), key=lambda item: item[1], reverse=True)[:12]]
    return {
        "genres": genres,
        "artists": artists[:12],
        "top_artists": [{"name": artist, "genres": []} for artist in artists[:12]],
        "top_tracks": tracks[:20],
        "energy_preference": _average_tracks(tracks, "energy"),
        "mood_preference": _average_tracks(tracks, "valence"),
        "danceability_preference": _average_tracks(tracks, "danceability"),
        "regional_affinity": _regional_affinity_from_genres(genres),
        "music_diversity": round(min(1.0, len(genres) / 12.0), 3),
        "embedding_query": " ".join([*genres[:8], *artists[:8], *[t.get("name", "") for t in tracks[:8]]])[:1000],
        "source": "spotify_cache",
    }


def _ensure_spotify_access_token(user_id: str) -> Optional[str]:
    connection = get_spotify_connection(user_id)
    if not connection:
        return None
    if not spotify_oauth.configured():
        return connection.get("access_token")
    if not spotify_oauth.token_expired(connection):
        return connection.get("access_token")
    if not connection.get("refresh_token"):
        print(f"[spotify.oauth.refresh_missing] user_id={user_id}")
        return None
    try:
        with _latency_span("spotify_api", "spotify_refresh"):
            refreshed = spotify_oauth.refresh_access_token(connection["refresh_token"])
        update_spotify_tokens(
            user_id,
            refreshed["access_token"],
            int(refreshed.get("expires_in") or 3600),
            refreshed.get("refresh_token"),
        )
        return refreshed["access_token"]
    except Exception as e:
        print(f"[spotify.oauth.refresh_failed] user_id={user_id} error={_redact_for_log(e)}")
        return None


def _load_spotify_taste_profile(user_id: str) -> Optional[dict]:
    if not user_id or not spotify_oauth.configured() or not get_spotify_connection(user_id):
        return _cached_spotify_taste_profile(user_id) if user_id else None
    access_token = _ensure_spotify_access_token(user_id)
    if not access_token:
        return _cached_spotify_taste_profile(user_id)
    try:
        with _latency_span("spotify_api", "spotify_taste_retrieval"):
            top_artists = spotify_oauth.get_user_top_artists(access_token, limit=20)
            top_tracks = spotify_oauth.get_user_top_tracks(access_token, limit=30)
            recent_tracks = spotify_oauth.get_recent_tracks(access_token, limit=20)

            track_artist_ids = []
            for track in top_tracks[:30]:
                for artist in track.get("artists") or []:
                    artist_id = artist.get("id") if isinstance(artist, dict) else None
                    if artist_id and artist_id not in track_artist_ids:
                        track_artist_ids.append(artist_id)
            known_artist_ids = {a.get("id") for a in top_artists if isinstance(a, dict)}
            missing_artist_ids = [artist_id for artist_id in track_artist_ids if artist_id not in known_artist_ids]
            if missing_artist_ids:
                top_artists = list(top_artists) + spotify_oauth.get_artists(access_token, missing_artist_ids)

        profile = spotify_oauth.build_music_profile(top_tracks, top_artists, recent_tracks)
        save_spotify_tracks(user_id, profile.get("top_tracks", [])[:30], "medium_term")
        return profile
    except Exception as e:
        print(f"[spotify.taste.fetch_failed] user_id={user_id} error={_redact_for_log(e)}")
        return _cached_spotify_taste_profile(user_id)


def _spotify_status_payload(user_id: str, connected: bool = True) -> dict:
    connection = get_spotify_connection(user_id)
    if not connection:
        return {
            "connected": False,
            "reconnect_required": False,
            "auth_status": "not_connected",
            "profile_ready": False,
            "top_artists": [],
            "top_genres": [],
            "profile": {},
        }

    reconnect_required = False
    auth_status = "connected"
    if spotify_oauth.configured() and spotify_oauth.token_expired(connection):
        if not connection.get("refresh_token"):
            reconnect_required = True
            auth_status = "missing_refresh_token"
        elif not _ensure_spotify_access_token(user_id):
            reconnect_required = True
            auth_status = "refresh_failed"

    profile = _load_spotify_taste_profile(user_id)
    profile_ready = bool((profile or {}).get("top_tracks") or (profile or {}).get("artists") or (profile or {}).get("genres"))
    return {
        "connected": bool(connected and connection and not reconnect_required),
        "reconnect_required": reconnect_required,
        "auth_status": auth_status,
        "profile_ready": profile_ready,
        "top_artists": (profile or {}).get("artists", [])[:5],
        "top_genres": (profile or {}).get("genres", [])[:6],
        "profile": {
            "energy_preference": (profile or {}).get("energy_preference"),
            "mood_preference": (profile or {}).get("mood_preference"),
            "danceability_preference": (profile or {}).get("danceability_preference"),
            "regional_affinity": (profile or {}).get("regional_affinity"),
            "music_diversity": (profile or {}).get("music_diversity"),
        } if profile else {},
    }


def _blend_spotify_taste_into_result(result: dict, user_id: Optional[str]) -> dict:
    if not result or result.get("spotify_taste_influence") or not user_id:
        return result
    profile = _load_spotify_taste_profile(user_id)
    if not profile:
        return result

    current = dict(result.get("genome_features") or {})
    if not current:
        return result
    spotify_genome = {
        "energy": (float(profile.get("energy_preference", 0.5)) - 0.5) * 4,
        "valence": (float(profile.get("mood_preference", 0.5)) - 0.5) * 4,
        "danceability": (float(profile.get("danceability_preference", 0.5)) - 0.5) * 4,
    }
    blended = dict(current)
    for feature, spotify_value in spotify_genome.items():
        blended[feature] = round(float(current.get(feature, 0.0)) * 0.88 + spotify_value * 0.12, 3)

    preserved = {
        key: value for key, value in result.items()
        if key not in {"cluster_id", "cluster_size", "archetype_scores", "archetype", "radar", "genre_affinities", "genome_features", "dual_identity"}
    }
    preserved["spotify_taste_influence"] = {
        "applied": True,
        "blend_weight": 0.12,
        "top_artists": profile.get("artists", [])[:5],
        "top_genres": profile.get("genres", [])[:6],
        "regional_affinity": profile.get("regional_affinity"),
        "music_diversity": profile.get("music_diversity"),
    }
    source = result.get("source") or "analysis"
    return _build_profile_from_genome(blended, source, preserved)


def sanitized_timeline(user_id: str) -> List[dict]:
    clean = []
    for snap in get_user_timeline(user_id):
        clean.append({
            "taken_at": snap.get("taken_at"),
            "archetype_id": snap.get("archetype_id"),
            "archetype_name": snap.get("archetype_name"),
            "primary_pct": snap.get("primary_pct"),
            "secondary_name": snap.get("secondary_name"),
            "secondary_pct": snap.get("secondary_pct"),
            "genome": snap.get("genome", {}),
            "region": snap.get("region"),
        })
    return clean


def latest_snapshot_or_error(user_id: str, label: str) -> str:
    snapshot_id = latest_snapshot_id_for_user(user_id)
    if not snapshot_id:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "missing_snapshot_for_user",
                "user": label,
                "message": f"Missing saved Sonic DNA snapshot for {label}.",
            },
        )
    return snapshot_id


def drift_response_for_user(user_id: str) -> dict:
    timeline = get_user_timeline(user_id)
    if not timeline:
        return {
            "status": "missing_snapshot_for_user",
            "message": "No Sonic DNA snapshot exists yet.",
            "snapshot_count": 0,
            "baseline_available": False,
        }
    if len(timeline) == 1:
        return {
            "status": "baseline_not_available_yet",
            "message": "Baseline stored. Retake once to unlock drift.",
            "snapshot_count": 1,
            "baseline_available": False,
            "latest": {
                "taken_at": timeline[0].get("taken_at"),
                "archetype_name": timeline[0].get("archetype_name"),
                "genome": timeline[0].get("genome", {}),
            },
        }
    from retention_engine import RetentionEngine
    decision = RetentionEngine().evaluate(timeline[1], timeline[0])
    return {
        "status": "ok",
        "message": "Drift compared against previous snapshot.",
        "snapshot_count": len(timeline),
        "baseline_available": True,
        "previous": {
            "taken_at": timeline[1].get("taken_at"),
            "archetype_name": timeline[1].get("archetype_name"),
        },
        "latest": {
            "taken_at": timeline[0].get("taken_at"),
            "archetype_name": timeline[0].get("archetype_name"),
        },
        "drift": decision,
    }


def standard_comparison_response(comparison: dict, user_a_name: str, user_b_name: str) -> dict:
    formatted = format_comparison_for_frontend(comparison, user_a_name, user_b_name)
    return {
        "score": formatted["score"],
        "tier": formatted["tier"],
        "genome_similarity": comparison["genome_similarity"],
        "archetype_chemistry": comparison["archetype_chemistry"],
        "insights": formatted["insights"],
        "features": formatted["features"],
        "pairing": formatted["pairing"],
        "users": formatted["users"],
    }


def compare_internal(
    user_a_id: str,
    user_b_id: str,
    snapshot_a_id: Optional[str] = None,
    snapshot_b_id: Optional[str] = None,
) -> dict:
    snapshot_a_id = snapshot_a_id or latest_snapshot_or_error(user_a_id, "current_user")
    snapshot_b_id = snapshot_b_id or latest_snapshot_or_error(user_b_id, "comparison_user")
    snapshot_a = get_snapshot_by_id(snapshot_a_id)
    snapshot_b = get_snapshot_by_id(snapshot_b_id)
    if not snapshot_a:
        raise HTTPException(status_code=409, detail={"error": "missing_snapshot_for_user", "user": "current_user"})
    if not snapshot_b:
        raise HTTPException(status_code=409, detail={"error": "missing_snapshot_for_user", "user": "comparison_user"})

    comparison = compatibility_engine.calculate_compatibility(snapshot_a, snapshot_b)
    user_a = get_user_by_id(user_a_id) or {}
    user_b = get_user_by_id(user_b_id) or {}
    save_genome_comparison(
        user_a_id,
        user_b_id,
        snapshot_a_id,
        snapshot_b_id,
        {
            "overall_similarity": comparison["overall_score"],
            "genome_similarity": comparison["genome_similarity"],
            "archetype_match": comparison["archetype_chemistry"],
            "detailed_comparison": comparison,
        },
    )
    return standard_comparison_response(
        comparison,
        user_a.get("display_name") or "You",
        user_b.get("display_name") or "Friend",
    )




# ════════════════════════════════════════════
# CORE ROUTES
# ════════════════════════════════════════════

@app.get("/")
def root():
    """API root with all available endpoints."""
    return {
        "name": "Music Taste Genome API",
        "version": "3.0.0",
        "status": "operational",
        "features": [
            "Quiz Analysis (Multiple Choice & Open Questions)",
            "Adaptive Question Flow",
            "Audio Clip Ratings",
            "User Compatibility Comparison",
            "Share Links & Viral Loop",
            "City/Global Leaderboards",
            "Playlist Generation",
            "Email Notifications"
        ],
        "endpoints": {
            "health": "/health",
            "quiz": [
                "/analyze",
                "/analyze_open",
                "/analyze_adaptive",
                "/analyze_combined"
            ],
            "clips": [
                "/clips/round1",
                "/clips/submit"
            ],
            "adaptive": [
                "/adaptive_question"
            ],
            "users": [
                "/user/login",
                "/user/session",
                "/user/save_snapshot",
                "/user/timeline",
                "/user/drift"
            ],
            "compatibility": [
                "/compatibility/compare"
            ],
            "share_links": [
                "/share/create",
                "/share/{share_code}",
                "/share/{share_code}/complete",
                "/share/my"
            ],
            "leaderboard": [
                "/leaderboard/cities",
                "/leaderboard/city/{city}",
                "/leaderboard/archetype/{archetype_id}/strongholds",
                "/leaderboard/global",
                "/leaderboard/user/location"
            ],
            "recommendations": [
                "/recommendations/{cluster_id}/{region_key}"
            ],
            "meta": [
                "/archetypes",
                "/regions"
            ]
        }
    }


@app.get("/health")
def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "services": {
            "genome_engine": engine is not None,
            "spotify_service": spotify is not None,
            "groq_client": groq_client is not None,
            "openrouter_question_provider": adaptive_question_service.provider.configured if adaptive_question_service.provider else False,
            "compatibility_engine": True,
            "playlist_generator": True
        },
        "data": {
            "users_loaded": engine.users_loaded_count if engine else 0,
            "clips_loaded": len(CLIP_FEATURES),
        },
        "config": {
            "groq_key_set": bool(os.getenv("GROQ_API_KEY")),
            "openrouter_key_set": bool(os.getenv("OPENROUTER_API_KEY")),
            "openrouter_quiz_model": os.getenv("OPENROUTER_QUIZ_MODEL") or os.getenv("OPENROUTER_MODEL") or "openrouter/free",
            "spotify_key_set": bool(os.getenv("SPOTIFY_CLIENT_ID")),
            "smtp_configured": bool(os.getenv("SMTP_USERNAME"))
        }
    }


# ════════════════════════════════════════════
# QUIZ ANALYSIS ENDPOINTS
# ════════════════════════════════════════════

@app.get("/ready")
def readiness():
    """Deployment readiness check without secret values or raw internals."""
    deployment = validate_deployment_environment()
    services = {
        "genome_engine": engine is not None,
        "spotify_service": spotify is not None,
        "playlist_generator": playlist_generator is not None,
        "adaptive_questions": adaptive_question_service is not None,
    }
    config_ok = not deployment["errors"]
    core_services_ok = services["genome_engine"] and services["playlist_generator"]
    ready = config_ok and core_services_ok
    status_code = 200 if config_ok or not deployment["production"] else 503
    payload = {
        "status": "ready" if ready else "degraded",
        "environment": deployment["environment"],
        "production": deployment["production"],
        "timestamp": datetime.utcnow().isoformat(),
        "services": services,
        "config": {
            "errors": len(deployment["errors"]),
            "warnings": len(deployment["warnings"]),
            "cors_origins_configured": len(deployment["cors_origins"]),
        },
    }
    return JSONResponse(payload, status_code=status_code)


@app.post("/analyze")
def analyze(payload: QuizPayload):
    """Legacy multiple choice quiz analysis."""
    if len(payload.answers) != 8:
        raise HTTPException(status_code=400, detail="Exactly 8 answers required.")
    for a in payload.answers:
        if a not in range(1, 6):
            raise HTTPException(status_code=400, detail="Each answer must be 1-5.")
    
    try:
        return analyze_quiz(payload.answers)
    except Exception as e:
        raise HTTPException(status_code=500, detail=_production_safe_detail("Analysis failed", e))


@app.post("/analyze_open")
def analyze_open(payload: OpenQuizPayload):
    """Open-ended questions via Groq AI."""
    if len(payload.q1.strip()) < 5:
        raise HTTPException(status_code=400, detail="Q1 answer too short.")
    
    try:
        result = analyze_open_questions(
            payload.q1,
            payload.q2 or "Not provided",
            payload.q3 or "Not provided",
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=_production_safe_detail("Analysis failed", e))


class MessageRequest(BaseModel):
    primary: str
    shadow: str
    scores: Dict[str, float]


@app.post("/message/personalized")
def generate_personalized_message(payload: MessageRequest):
    """Generate a truly personalized one-sentence reading from Groq AI."""
    if not groq_client:
        return {"message": "You are the only person who hears what your library means."}
        
    try:
        scores_desc = ", ".join(f"{k}: {v}%" for k, v in payload.scores.items())
        prompt = f"""You are a poetic music taste analyst writing a personalized sentence for a user's music identity.
        
Their primary music archetype is "{payload.primary}".
Their shadow music archetype is "{payload.shadow}".
Their normalized genome scores (on a 0-100 scale) are:
{scores_desc}

Write a single, evocative, poetic, and deeply personal sentence (about 10-18 words) that summarizes their unique relationship with sound.
Guidelines:
1. Address the user directly ("You...").
2. Make it feel profound and artistic (e.g., "You collect songs the way astronomers collect stars" or "You build entire cathedrals out of restraint").
3. DO NOT wrap in quotes.
4. DO NOT say "Here is the sentence" or add extra text. Only return the single sentence."""

        msg = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}]
        )
        text = msg.choices[0].message.content.strip().strip('"').strip("'")
        return {"message": text}
    except Exception as e:
        print(f"[message.error] failed to generate personalized message: {e}")
        return {"message": "You are the only person who hears what your library means."}


@app.post("/analyze_adaptive")
def analyze_adaptive(payload: AdaptiveOpenPayload):
    """
    Analyze adaptive quiz submissions with variable-length answers.
    Combines text answers with optional clip ratings.
    """
    answers = [a.strip() for a in payload.answers if a.strip()]
    if not answers:
        raise HTTPException(status_code=400, detail="At least one answer required.")

    q1 = answers[0] if len(answers) > 0 else "Not provided"
    q2 = answers[1] if len(answers) > 1 else "Not provided"
    q3 = " | ".join(answers[2:]) if len(answers) > 2 else "Not provided"
    user_id = resolve_payload_user(payload.session_token, payload.user_id)
    print(
        f"[analysis.adaptive.request] answers={len(answers)} "
        f"clip_ratings={len(payload.clip_ratings or [])} region={payload.region}"
    )

    try:
        clip_genome = {}
        if payload.clip_ratings:
            clip_ratings_objs = [ClipRating(**r) for r in payload.clip_ratings]
            clip_result = analyze_clips_ratings(clip_ratings_objs)
            clip_genome = dict(clip_result.get("genome_features") or {})
            print(
                f"[analysis.adaptive.clips] received={len(payload.clip_ratings)} "
                f"valid={len(clip_result.get('rated_clips') or [])} genome_keys={len(clip_genome)}"
            )

        gemini_profile = None
        if gemini_service:
            try:
                gemini_profile = gemini_service.analyze_psychological_answers(answers, user_id=user_id)
                print(f"[analysis.adaptive.gemini_ok] archetype={gemini_profile.archetype}")
            except Exception as ge:
                print(f"[analysis.adaptive.gemini_fallback] error={_redact_for_log(ge)}")

        if payload.clip_ratings and gemini_profile:
            try:
                text_genome = gemini_profile.genome.model_dump()
                reasoning = gemini_profile.reasoning

                # Blend: 60% text (Gemini), 40% clips
                final_genome = {}
                for feat in ["danceability", "energy", "valence", "acousticness",
                            "instrumentalness", "speechiness", "tempo"]:
                    text_val = float(text_genome.get(feat, 0.0) or 0.0)
                    clip_val = float(clip_genome.get(feat, 0.0) or 0.0)
                    final_genome[feat] = text_val * 0.6 + clip_val * 0.4

                extra = {
                    "claude_reasoning": reasoning,
                    "text_answers": answers,
                    "clip_ratings_count": len(payload.clip_ratings),
                    "blend_method": "60% text (Gemini) + 40% clips",
                    "archetype": gemini_profile.archetype,
                    "shadow_archetype": gemini_profile.shadow_archetype,
                    "psychological_analysis": gemini_profile.psychological_analysis.model_dump(),
                }
                result = _build_profile_from_genome(final_genome, "adaptive_blend", extra)
                print(f"[analysis.adaptive.ok] source=adaptive_blend cluster={result.get('cluster_id')}")
                return _blend_spotify_taste_into_result(result, user_id)
            except Exception as blend_err:
                print(f"[analysis.adaptive.blend_error] {blend_err}")

        if payload.clip_ratings and groq_client:
            try:
                # Blend clip ratings + text answers
                all_answers_text = "\n".join(f"A{i+1}: {a}" for i, a in enumerate(answers))

                blend_prompt = f"""You are a music taste analyst. Extract a musical genome vector from these answers.

User answers to adaptive music questions:
{all_answers_text}

Return ONLY a valid JSON object with exactly these keys and float values from -2.0 to +2.0:
{{
  "danceability": <float>,
  "energy": <float>,
  "valence": <float>,
  "acousticness": <float>,
  "instrumentalness": <float>,
  "speechiness": <float>,
  "tempo": <float>,
  "reasoning": "<1-2 sentence explanation>"
}}
No markdown, no extra text. Just the JSON."""

                msg = groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    max_tokens=512,
                    messages=[{"role": "user", "content": blend_prompt}]
                )
                raw = msg.choices[0].message.content.strip()

                try:
                    text_genome = json.loads(raw)
                except json.JSONDecodeError:
                    import re
                    match = re.search(r'\{.*\}', raw, re.DOTALL)
                    text_genome = json.loads(match.group()) if match else {}

                reasoning = text_genome.pop("reasoning", "Your musical genome has been decoded.")

                # Blend: 60% text, 40% clips
                final_genome = {}
                for feat in ["danceability", "energy", "valence", "acousticness",
                            "instrumentalness", "speechiness", "tempo"]:
                    text_val = float(text_genome.get(feat, 0.0) or 0.0)
                    clip_val = float(clip_genome.get(feat, 0.0) or 0.0)
                    final_genome[feat] = text_val * 0.6 + clip_val * 0.4

                extra = {
                    "claude_reasoning": reasoning,
                    "text_answers": answers,
                    "clip_ratings_count": len(payload.clip_ratings),
                    "blend_method": "60% text + 40% clips"
                }
                result = _build_profile_from_genome(final_genome, "adaptive_blend", extra)
                print(f"[analysis.adaptive.ok] source=adaptive_blend cluster={result.get('cluster_id')}")
                return _blend_spotify_taste_into_result(result, user_id)
            except Exception as provider_error:
                print(f"[analysis.adaptive.provider_fallback] error={_redact_for_log(provider_error)}")
                if clip_genome:
                    extra = {
                        "claude_reasoning": "Provider unavailable; decoded from audio reactions.",
                        "text_answers": answers,
                        "clip_ratings_count": len(payload.clip_ratings),
                        "blend_method": "clip-only fallback",
                    }
                    result = _build_profile_from_genome(clip_genome, "adaptive_clip_fallback", extra)
                    print(f"[analysis.adaptive.ok] source=adaptive_clip_fallback cluster={result.get('cluster_id')}")
                    return _blend_spotify_taste_into_result(result, user_id)
                raise

        if gemini_profile and not payload.clip_ratings:
            text_genome = gemini_profile.genome.model_dump()
            extra = {
                "claude_reasoning": gemini_profile.reasoning,
                "text_answers": answers,
                "blend_method": "Gemini psychometric profile",
                "archetype": gemini_profile.archetype,
                "shadow_archetype": gemini_profile.shadow_archetype,
                "psychological_analysis": gemini_profile.psychological_analysis.model_dump(),
            }
            result = _build_profile_from_genome(text_genome, "adaptive_gemini", extra)
            print(f"[analysis.adaptive.ok] source=adaptive_gemini cluster={result.get('cluster_id')}")
            return _blend_spotify_taste_into_result(result, user_id)

        if clip_genome:
            extra = {
                "claude_reasoning": "Decoded from audio reactions.",
                "text_answers": answers,
                "clip_ratings_count": len(payload.clip_ratings),
                "blend_method": "clip-only",
            }
            result = _build_profile_from_genome(clip_genome, "adaptive_clip_fallback", extra)
            print(f"[analysis.adaptive.ok] source=adaptive_clip_fallback cluster={result.get('cluster_id')}")
            return _blend_spotify_taste_into_result(result, user_id)

        # Text-only analysis fallback
        result = analyze_open_questions(q1, q2, q3)
        print(f"[analysis.adaptive.ok] source={result.get('source')} cluster={result.get('cluster_id')}")
        return _blend_spotify_taste_into_result(result, user_id)

    except Exception as e:
        print(f"[error] analyze_adaptive: {_redact_for_log(e)}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=_production_safe_detail("Adaptive analysis failed", e))


@app.post("/clips/submit")
def submit_clips(payload: ClipRatingsPayload):
    """Submit clip ratings and get genome analysis."""
    try:
        result = analyze_clips_ratings(payload.ratings)
        user_id = resolve_payload_user(payload.session_token, payload.user_id)
        return _blend_spotify_taste_into_result(result, user_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=_production_safe_detail("Clip analysis failed", e))


def _clip_response(clip_id: str, session_key: str = "", play_index: int = 0) -> Optional[dict]:
    """Build the frontend clip payload, including a playable static audio URL."""
    clip = clip_rotator.response_for(clip_id, session_key=session_key, play_index=play_index)
    if not clip:
        print(f"[clip.warn] Clip unavailable for {clip_id}")
    return clip


def _build_playable_clip_batch(
    clip_ids: List[str],
    requested_count: int,
    session_key: str,
    play_index_offset: int = 0,
    exclude_ids: Optional[set] = None,
) -> List[dict]:
    requested_count = max(0, int(requested_count or 0))
    selected: List[dict] = []
    seen = set(exclude_ids or set())
    failures = []

    for clip_id in clip_ids:
        if clip_id in seen:
            continue
        clip = _clip_response(clip_id, session_key=session_key, play_index=play_index_offset + len(selected))
        seen.add(clip_id)
        if clip:
            selected.append(clip)
        else:
            failures.append(clip_id)
        if len(selected) >= requested_count:
            break

    if len(selected) < requested_count:
        fallback_ids = select_round_clip_ids(
            CLIP_FEATURES,
            requested_count - len(selected),
            session_key=f"{session_key}|backfill",
            exclude_ids=seen,
        )
        for clip_id in fallback_ids:
            clip = _clip_response(clip_id, session_key=session_key, play_index=play_index_offset + len(selected))
            seen.add(clip_id)
            if clip:
                selected.append(clip)
            else:
                failures.append(clip_id)
            if len(selected) >= requested_count:
                break

    print(
        f"[clips.batch] requested={requested_count} received_ids={len(clip_ids)} "
        f"rendered={len(selected)} failures={len(failures)}"
    )
    if failures:
        print(f"[clips.batch.failures] ids={','.join(failures[:12])}")
    return selected


@app.get("/clips/round1")
def get_round1_clips(count: int = 8, session_key: Optional[str] = None, diagnostics: bool = False):
    """Get initial calibration clips for audio rating round."""
    try:
        key = session_key or ""
        requested_count = max(1, min(count, len(CLIP_FEATURES)))
        clip_ids = get_calibration_clips(requested_count, session_key=key)
        clips = _build_playable_clip_batch(clip_ids, requested_count, key)

        if not clips:
            raise HTTPException(status_code=500, detail="No playable clips found")
        
        print(f"[clips.ok] Returning {len(clips)} clips")
        diag = clip_distribution_diagnostics(CLIP_FEATURES, [clip["clip_id"] for clip in clips])
        print(f"Returning {len(clips)} clips coverage={diag['coverage_ratio']} categories={diag['selected_unique_categories']}")
        if diagnostics:
            return {"clips": clips, "diagnostics": diag}
        return clips
        
    except Exception as e:
        print(f"[error] Loading clips: {_redact_for_log(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=_production_safe_detail("Failed to load clips", e))


@app.post("/clips/adaptive")
def get_adaptive_clip_round(payload: AdaptiveClipsPayload):
    """Get follow-up clips based on the user's first round ratings."""
    try:
        n = 2 if payload.round_number >= 2 else 3
        key = payload.session_key or ""
        clip_ids = get_adaptive_clips(payload.existing_ratings, n=n, session_key=key)
        excluded = {str(r.get("clip_id")) for r in payload.existing_ratings if r.get("clip_id")}
        clips = _build_playable_clip_batch(
            clip_ids,
            n,
            key,
            play_index_offset=len(payload.existing_ratings),
            exclude_ids=excluded,
        )

        print(f"[clips.ok] Returning {len(clips)} adaptive clips")
        diag = clip_distribution_diagnostics(CLIP_FEATURES, [clip["clip_id"] for clip in clips])
        return {"clips": clips, "diagnostics": diag}

    except Exception as e:
        print(f"[error] Loading adaptive clips: {_redact_for_log(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=_production_safe_detail("Failed to load adaptive clips", e))


# ── Adaptive Question Flow ───────────────────

MIN_QUESTIONS = 1
MAX_QUESTIONS = 5

@app.post("/adaptive_question")
def get_adaptive_question(payload: AdaptiveQuestionPayload):
    """
    Adaptive question engine that decides if more questions are needed.
    Returns next question or signals completion.
    """
    prev = payload.previous_answers
    ratings = payload.clip_ratings
    qnum = len(prev) + 1

    # Hard caps
    force_continue = qnum <= MIN_QUESTIONS
    if qnum > MAX_QUESTIONS:
        return {"continue": False, "question": "", "hint": "", "question_number": qnum}

    try:
        return adaptive_question_service.next_question(
            previous_answers=prev,
            clip_ratings=ratings,
            covered_dimensions=payload.covered_dimensions,
            asked_questions=payload.asked_questions,
        )
    except Exception as e:
        print(f"adaptive_question service fallback: {e}")
        return AdaptiveQuestionService(provider=None).next_question(
            previous_answers=prev,
            clip_ratings=ratings,
            covered_dimensions=payload.covered_dimensions,
            asked_questions=payload.asked_questions,
        )




# ════════════════════════════════════════════
# USER MANAGEMENT
# ════════════════════════════════════════════

@app.post("/user/login")
def login_or_register(payload: UserPayload):
    """Get or create a user by email."""
    try:
        user = get_or_create_user(payload.email, payload.display_name)
        return issue_public_session(user)
    except Exception as e:
        raise HTTPException(status_code=500, detail=_production_safe_detail("User operation failed", e))


@app.post("/user/session")
def session_user(payload: SessionUserPayload):
    """Create or reuse a browser/session-scoped user identity."""
    try:
        user_id = resolve_session_token(payload.session_token) or payload.user_id
        user = get_or_create_session_user(user_id, payload.display_name)
        if payload.email:
            # Always use the resolved user ID to prevent duplicate user creation
            user = attach_email_to_session_user(user["id"], payload.email, payload.display_name)
        return issue_public_session(user)
    except Exception as e:
        raise HTTPException(status_code=500, detail=_production_safe_detail("Session user operation failed", e))


@app.post("/user/update_email")
def update_user_email(payload: SessionUserPayload):
    """Update email for an existing session user. Email is optional - users can remain anonymous."""
    try:
        user_id = resolve_session_token(payload.session_token) or payload.user_id
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid session - no user found.")
        
        if not payload.email:
            raise HTTPException(status_code=400, detail="Email is required for this endpoint.")
        
        # Attach email to the existing session user - never creates duplicate
        user = attach_email_to_session_user(user_id, payload.email, payload.display_name)
        return issue_public_session(user)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=_production_safe_detail("Email update failed", e))


@app.post("/user/save_snapshot")
def save_snapshot(payload: SaveSnapshotPayload, background_tasks: BackgroundTasks):
    """Save quiz result snapshot for a user."""
    try:
        user_id = resolve_payload_user(payload.session_token, payload.user_id)
        if not user_id:
            user = get_or_create_session_user(None)
            user_id = user["id"]
        result = _blend_spotify_taste_into_result(payload.result, user_id)
        snapshot_id = save_genome_snapshot(
            user_id,
            result,
            payload.region
        )

        return {
            "saved": True,
            "snapshot_count": len(get_user_timeline(user_id)),
            "drift": drift_response_for_user(user_id),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=_production_safe_detail("Save failed", e))


@app.post("/feedback/events")
def record_feedback_events(payload: FeedbackEventsPayload):
    """Record privacy-preserving client feedback events for offline analysis."""
    if not payload.events:
        return {"recorded": 0}
    if len(payload.events) > 50:
        raise HTTPException(status_code=400, detail="Too many feedback events in one request.")

    try:
        subject = _feedback_subject_for(payload)
        session_id = payload.session_id or payload.session_token or "browser-session"
        store = JsonlFeedbackStore(_feedback_events_path())
        for raw_event in payload.events:
            store.record(_safe_feedback_event(raw_event, subject=subject, session_id=session_id))
        return {"recorded": len(payload.events)}
    except HTTPException:
        raise
    except Exception as exc:
        print(f"[feedback.warning] record_failed={_redact_for_log(exc)}")
        raise HTTPException(status_code=202, detail="Feedback accepted but could not be persisted.")


@app.post("/user/timeline")
def get_timeline(payload: SessionUserPayload):
    """Get user's genome evolution timeline."""
    try:
        user_id = resolve_payload_user(payload.session_token, payload.user_id)
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid session.")
        timeline = sanitized_timeline(user_id)
        return {"snapshots": timeline, "count": len(timeline)}
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=_production_safe_detail("Timeline fetch failed", e))


@app.post("/user/drift")
def get_drift(payload: SessionUserPayload):
    """Compare current user's latest snapshot against the immediate previous snapshot."""
    try:
        user_id = resolve_payload_user(payload.session_token, payload.user_id)
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid session.")
        return drift_response_for_user(user_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=_production_safe_detail("Drift fetch failed", e))


@app.get("/api/evolution/{user_id}")
def get_evolution_timeline(user_id: str, limit: int = 90, source: Optional[str] = None):
    """
    GET /api/evolution/{user_id}

    Returns a chronological array of TasteDriftSnapshot records for the given
    user, ordered oldest-first and formatted for frontend charting libraries.

    Query params:
      limit  — max rows to return (default 90, ≈3 months of weekly snapshots)
      source — optional filter: "background_spotify" | "quiz" | "manual"

    Response shape::

        {
          "user_id": "...",
          "count": 12,
          "snapshots": [
            {
              "date": "2026-09-12T14:00:00",
              "energy": 0.71,
              "valence": 0.58,
              "danceability": 0.65,
              "acousticness": 0.22,
              "archetype": "The Storm Chaser",
              "source": "background_spotify"
            },
            ...
          ]
        }
    """
    try:
        user = get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found.")

        rows = get_taste_drift_history(
            user_id=user_id,
            limit=max(1, min(int(limit), 500)),
            source=source or None,
        )

        snapshots = [
            {
                "date": r.get("recorded_at"),
                "energy": r.get("energy"),
                "valence": r.get("valence"),
                "danceability": r.get("danceability"),
                "acousticness": r.get("acousticness"),
                "archetype": r.get("active_archetype"),
                "source": r.get("source"),
            }
            for r in rows
        ]

        return {
            "user_id": user_id,
            "count": len(snapshots),
            "snapshots": snapshots,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=_production_safe_detail("Evolution timeline fetch failed", exc),
        )



# ════════════════════════════════════════════
# AUTH ENDPOINTS — email / password accounts
# ════════════════════════════════════════════

# Optional bcrypt; fall back to pbkdf2_hmac if not installed.
try:
    import bcrypt as _bcrypt
    def _hash_password(password: str) -> str:
        return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()
    def _verify_password(password: str, hashed: str) -> bool:
        try:
            return _bcrypt.checkpw(password.encode(), hashed.encode())
        except Exception:
            return False
except ImportError:
    import hashlib as _hashlib, secrets as _secrets
    def _hash_password(password: str) -> str:
        salt = _secrets.token_hex(16)
        key = _hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260000)
        return f"pbkdf2:{salt}:{key.hex()}"
    def _verify_password(password: str, hashed: str) -> bool:
        try:
            _, salt, stored = hashed.split(":", 2)
            key = _hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260000)
            return key.hex() == stored
        except Exception:
            return False

# In-memory reset-token store (adequate for single-instance dev; replace with DB table in prod)
_reset_tokens: dict[str, tuple[str, float]] = {}  # token -> (user_id, expires_epoch)


class AuthRegisterPayload(BaseModel):
    email: str
    password: str
    display_name: Optional[str] = None
    session_token: Optional[str] = None  # elevate anonymous session to account


class AuthLoginPayload(BaseModel):
    email: str
    password: str


class AuthResetRequestPayload(BaseModel):
    email: str


class AuthResetPayload(BaseModel):
    token: str
    new_password: str


def _get_user_password_hash(user_id: str) -> Optional[str]:
    """Fetch password_hash for a user (None if column missing or not set)."""
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT password_hash FROM users WHERE id = ?", user_id
            )
            row = cursor.fetchone()
            return row[0] if row else None
    except Exception:
        return None


def _set_user_password_hash(user_id: str, password_hash: str) -> None:
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                password_hash, user_id
            )
            conn.commit()
    except Exception as exc:
        raise RuntimeError(f"Could not persist password hash: {exc}") from exc


def _find_user_by_email_strict(email: str) -> Optional[dict]:
    """Return user dict if email matches a non-anonymous account row."""
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, email, display_name, created_at FROM users WHERE LOWER(email) = LOWER(?)",
                email.strip()
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "id": str(row[0]),
                "email": row[1],
                "display_name": row[2],
                "created_at": row[3].isoformat() if row[3] else None,
            }
    except Exception:
        return None


@app.post("/auth/register")
def auth_register(payload: AuthRegisterPayload):
    """
    Register a new account with email + password.
    If `session_token` is provided the anonymous session is elevated
    and its genome snapshots are preserved.
    """
    email = (payload.email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email address is required.")
    if not payload.password or len(payload.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    # Reject if email already has a password (i.e. real account exists)
    existing = _find_user_by_email_strict(email)
    if existing:
        existing_hash = _get_user_password_hash(existing["id"])
        if existing_hash:
            raise HTTPException(status_code=409, detail="An account with this email already exists. Please log in.")

    try:
        password_hash = _hash_password(payload.password)
        # Elevate anonymous session if present
        session_user_id = resolve_session_token(payload.session_token)
        if session_user_id:
            user = attach_email_to_session_user(session_user_id, email, payload.display_name)
        elif existing:
            # Email row exists but no password — attach password
            user = existing
        else:
            user = get_or_create_user(email, payload.display_name or email.split("@")[0])
        _set_user_password_hash(user["id"], password_hash)
        return {**issue_public_session(user), "registered": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=_production_safe_detail("Registration failed", e))


@app.post("/auth/login")
def auth_login(payload: AuthLoginPayload):
    """Authenticate with email + password."""
    email = (payload.email or "").strip().lower()
    if not email or not payload.password:
        raise HTTPException(status_code=400, detail="Email and password are required.")

    user = _find_user_by_email_strict(email)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    stored_hash = _get_user_password_hash(user["id"])
    if not stored_hash or not _verify_password(payload.password, stored_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    try:
        return {**issue_public_session(user), "logged_in": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=_production_safe_detail("Login failed", e))


@app.post("/auth/reset-request")
def auth_reset_request(payload: AuthResetRequestPayload):
    """Send password reset email (token returned in dev; email in prod)."""
    email = (payload.email or "").strip().lower()
    user = _find_user_by_email_strict(email)
    # Always return 200 to prevent email enumeration
    if not user:
        return {"requested": True, "message": "If that email exists, a reset link has been sent."}

    token = secrets.token_urlsafe(32)
    expires = time.time() + 3600  # 1 hour
    _reset_tokens[token] = (user["id"], expires)

    reset_url = f"{_frontend_url() or 'http://localhost:5173'}/reset-password?token={token}"
    try:
        queue_email(
            user_id=user["id"],
            email_type="password_reset",
            recipient_email=email,
            template_data={"reset_url": reset_url, "display_name": user.get("display_name", "")},
        )
        process_email_queue()
    except Exception as exc:
        print(f"[auth.reset.email_warn] {_redact_for_log(exc)}")

    env = _app_environment()
    return {
        "requested": True,
        "message": "If that email exists, a reset link has been sent.",
        **({"dev_token": token, "dev_reset_url": reset_url} if env != "production" else {}),
    }


@app.post("/auth/reset")
def auth_reset(payload: AuthResetPayload):
    """Complete a password reset using a valid token."""
    entry = _reset_tokens.get(payload.token)
    if not entry:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token.")
    user_id, expires = entry
    if time.time() > expires:
        _reset_tokens.pop(payload.token, None)
        raise HTTPException(status_code=400, detail="Reset token has expired.")
    if not payload.new_password or len(payload.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters.")

    try:
        _set_user_password_hash(user_id, _hash_password(payload.new_password))
        _reset_tokens.pop(payload.token, None)
        user = get_user_by_id(user_id)
        return {**issue_public_session(user), "password_reset": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=_production_safe_detail("Password reset failed", e))


@app.get("/auth/me")
def auth_me(session_token: str):
    """Return the current user's profile from a session token."""
    user_id = resolve_session_token(session_token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired session.")
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    snapshot_count = len(get_user_timeline(user_id))
    return {
        **public_user(user),
        "user_id": user_id,
        "session_token": session_token,
        "snapshot_count": snapshot_count,
        "has_password": bool(_get_user_password_hash(user_id)),
        "spotify_connected": bool(get_spotify_connection(user_id)),
    }


@app.get("/user/public/{display_name}")
def get_public_profile(display_name: str):
    """Return a public user profile by display name for public profile pages."""
    user = find_user_by_display_name(display_name)
    if not user:
        raise HTTPException(status_code=404, detail="Profile not found.")
    timeline = sanitized_timeline(user["id"])
    latest = timeline[0] if timeline else None
    return {
        "display_name": user.get("display_name") or display_name,
        "snapshot_count": len(timeline),
        "archetype": latest.get("archetype_name") if latest else None,
        "genome": latest.get("genome") if latest else None,
        "taken_at": latest.get("taken_at") if latest else None,
        "timeline_count": len(timeline),
    }


# ════════════════════════════════════════════
# COMPATIBILITY & SOCIAL COMPARISON
# ════════════════════════════════════════════

@app.post("/compatibility/compare")
def compare_users(payload: CompareUsersPayload):
    """
    Compare two users' music genomes.
    Returns detailed compatibility breakdown.
    """
    try:
        user_a_id = resolve_payload_user(payload.session_token, payload.user_a_id)
        if not user_a_id:
            raise HTTPException(status_code=401, detail="Invalid current user session.")

        user_b_id = payload.user_b_id
        snapshot_b_id = payload.snapshot_b_id

        if payload.share_code:
            details = get_share_link_details(payload.share_code)
            if not details:
                raise HTTPException(status_code=404, detail="Share link not found")
            user_b_id = details["inviter_user_id"]
            snapshot_b_id = details["inviter_snapshot_id"]
        elif payload.display_name:
            user_b = find_user_by_display_name(payload.display_name)
            if not user_b:
                raise HTTPException(status_code=404, detail={"error": "user_not_found", "message": "No saved listener found with that display name."})
            user_b_id = user_b["id"]

        if not user_b_id:
            raise HTTPException(status_code=400, detail="Provide a share code or display name to compare.")

        return compare_internal(user_a_id, user_b_id, payload.snapshot_a_id, snapshot_b_id)
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[error] Compatibility comparison: {_redact_for_log(e)}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=_production_safe_detail("Comparison failed", e))


@app.get("/compatibility/{user_a_id}/{user_b_id}")
def get_compatibility(user_a_id: str, user_b_id: str):
    """Get existing compatibility comparison between two users."""
    raise HTTPException(status_code=410, detail="Raw user comparison routes are disabled. Use /compatibility/compare with a session token and share code.")


# ════════════════════════════════════════════
# SHARE LINKS (Viral Loop)
# ════════════════════════════════════════════

@app.post("/share/create")
def create_share(payload: ShareLinkPayload, background_tasks: BackgroundTasks):
    """Create a shareable link for a user's quiz result."""
    try:
        user_id = resolve_payload_user(payload.session_token, payload.user_id)
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid session.")
        snapshot_id = payload.snapshot_id or latest_snapshot_or_error(user_id, "current_user")
        link = generate_share_link(
            user_id,
            snapshot_id,
            payload.expiry_days
        )
        configured_share_base = (os.getenv("SONIC_SHARE_BASE_URL") or "").strip().rstrip("/")
        full_url = f"{configured_share_base}?share={link['share_code']}" if configured_share_base else None
        
        # Send email notification
        if link["is_new"]:
            background_tasks.add_task(
                send_share_link_created_notification,
                user_id,
                link["share_code"]
            )
        
        return {
            "share_code": link["share_code"],
            "full_url": full_url,
            "expires_at": link.get("expires_at"),
            "is_new": link.get("is_new", False),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=_production_safe_detail("Share link creation failed", e))


@app.get("/share/{share_code}")
def get_share(share_code: str):
    """Get share link details by code."""
    try:
        details = get_share_link_details(share_code)
        
        if not details:
            raise HTTPException(status_code=404, detail="Share link not found")
        
        if not details["is_valid"]:
            if details["is_expired"]:
                raise HTTPException(status_code=410, detail="Share link expired")
        
        return {
            "share_code": share_code,
            "status": details["status"],
            "is_valid": details["is_valid"],
            "is_expired": details["is_expired"],
            "is_completed": details["is_completed"],
            "expires_at": details["expires_at"],
            "created_at": details["created_at"],
            "times_accessed": details["times_accessed"],
            "inviter": {
                "display_name": details["inviter"].get("display_name"),
                "archetype_name": details["inviter"].get("archetype_name"),
                "archetype_id": details["inviter"].get("archetype_id"),
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=_production_safe_detail("Fetch failed", e))


@app.post("/share/{share_code}/complete")
def complete_share(share_code: str, payload: CompleteShareLinkPayload, background_tasks: BackgroundTasks):
    """Mark share link as completed after friend finishes quiz."""
    try:
        invitee_user_id = resolve_payload_user(payload.session_token, payload.invitee_user_id)
        if not invitee_user_id:
            raise HTTPException(status_code=401, detail="Invalid session.")
        invitee_snapshot_id = payload.invitee_snapshot_id or latest_snapshot_or_error(invitee_user_id, "current_user")
        success = complete_share_link(
            share_code,
            invitee_user_id,
            invitee_snapshot_id
        )
        
        if not success:
            raise HTTPException(status_code=400, detail="Failed to complete share link")
        
        # Get share link details to trigger compatibility calculation
        details = get_share_link_details(share_code)
        
        if details:
            # Calculate compatibility
            comparison = compare_internal(
                details["inviter_user_id"],
                invitee_user_id,
                details["inviter_snapshot_id"],
                invitee_snapshot_id,
            )
            
            # Send notification to inviter
            invitee = get_user_by_id(invitee_user_id)
            background_tasks.add_task(
                send_comparison_complete_notification,
                details["inviter_user_id"],
                invitee["display_name"] if invitee else "Someone",
                comparison["score"],
                share_code
            )
            
            return {
                "completed": True,
                "compatibility": comparison
            }
        
        return {"completed": True}
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[error] Complete share: {_redact_for_log(e)}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=_production_safe_detail("Completion failed", e))


@app.get("/share/user/{user_id}")
def get_user_shares(user_id: str, include_expired: bool = False):
    """Get all share links created by a user."""
    raise HTTPException(status_code=410, detail="Raw user share routes are disabled. Use /share/my with a session token.")


@app.post("/share/my")
def get_my_shares(payload: SessionUserPayload, include_expired: bool = False):
    """Get share links for the current session without exposing internal user IDs."""
    try:
        user_id = resolve_payload_user(payload.session_token, payload.user_id)
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid session.")
        links = get_user_share_links(user_id, include_expired)
        return {"share_links": links, "count": len(links)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=_production_safe_detail("Fetch failed", e))


@app.get("/share/analytics/{user_id}")
def get_share_analytics(user_id: str):
    """Get viral loop analytics for a user."""
    raise HTTPException(status_code=410, detail="Raw user analytics routes are disabled.")


@app.get("/share/analytics/global")
def get_global_analytics():
    """Get platform-wide viral statistics."""
    try:
        stats = get_global_viral_stats()
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=_production_safe_detail("Global stats fetch failed", e))


# ════════════════════════════════════════════
# LEADERBOARD & CITY RANKINGS
# ════════════════════════════════════════════

@app.post("/leaderboard/user/location")
def save_location(payload: LocationPayload):
    """Save user's location for leaderboard tracking."""
    try:
        save_user_location(
            payload.user_id,
            payload.city,
            payload.country,
            payload.region,
            payload.ip_address
        )
        return {"saved": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=_production_safe_detail("Location save failed", e))


@app.get("/leaderboard/cities")
def get_cities_leaderboard(limit: int = 20, min_users: int = 5):
    """Get leaderboard of top cities."""
    try:
        cities = get_top_cities_leaderboard(limit, min_users)
        return {"cities": cities, "count": len(cities)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=_production_safe_detail("Leaderboard fetch failed", e))


@app.get("/leaderboard/city/{city}")
def get_city_stats(city: str):
    """Get archetype distribution for a specific city."""
    try:
        stats = get_city_archetype_distribution(city)
        
        if not stats:
            raise HTTPException(status_code=404, detail="City not found")
        
        return stats
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=_production_safe_detail("City stats fetch failed", e))


@app.get("/leaderboard/archetype/{archetype_id}/strongholds")
def get_archetype_cities(archetype_id: int, limit: int = 10):
    """Get cities where an archetype is most dominant."""
    try:
        if archetype_id not in ARCHETYPES:
            raise HTTPException(status_code=400, detail="Invalid archetype ID")
        
        strongholds = get_archetype_strongholds(archetype_id, limit)
        return {
            "archetype_id": archetype_id,
            "archetype_name": ARCHETYPES[archetype_id]["name"],
            "strongholds": strongholds,
            "count": len(strongholds)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=_production_safe_detail("Strongholds fetch failed", e))


@app.get("/leaderboard/global")
def get_global_stats():
    """Get global archetype distribution."""
    try:
        distribution = get_global_archetype_distribution()
        return distribution
    except Exception as e:
        raise HTTPException(status_code=500, detail=_production_safe_detail("Global stats fetch failed", e))


@app.get("/leaderboard/compare/{city_a}/{city_b}")
def compare_cities(city_a: str, city_b: str):
    """Compare archetype distributions between two cities."""
    try:
        comparison = get_city_comparison_headline(city_a, city_b)
        
        if not comparison:
            raise HTTPException(status_code=404, detail="Insufficient data for comparison")
        
        return comparison
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=_production_safe_detail("City comparison failed", e))


# ════════════════════════════════════════════
# RECOMMENDATIONS & SPOTIFY
# ════════════════════════════════════════════

def _fallback_tracks(region_key: str, requested_limit: int) -> List[dict]:
    discovery_tracks = playlist_generator._internal_discovery_tracks(region_key, None)
    familiar_tracks = playlist_generator._curated_familiar_seed_tracks(region_key, None)
    tracks = []
    seen = set()
    for track in discovery_tracks + familiar_tracks:
        key = track.get("id") or f"{track.get('name')}|{track.get('artist')}"
        if key in seen:
            continue
        seen.add(key)
        tracks.append(track)
        if len(tracks) >= requested_limit:
            break
    return tracks


def _fallback_recommendations(cluster_id: int, region_key: str, requested_limit: int, reason: str) -> dict:
    tracks = _fallback_tracks(region_key, requested_limit)
    print(
        f"[recommendations.fallback] reason={reason} region={region_key} "
        f"returned={len(tracks)} requested={requested_limit}"
    )
    return {
        "cluster_id": cluster_id,
        "archetype": ARCHETYPES[cluster_id]["name"],
        "region": region_key,
        "tracks": tracks,
        "count": len(tracks),
        "source": "internal_fallback",
        "fallback_reason": reason,
    }


def _fallback_playlist_response(payload: PlaylistTrialPayload, requested_size: int, reason: str) -> dict:
    tracks = _fallback_tracks(payload.region_key, requested_size)
    region_name = REGIONS.get(payload.region_key, payload.region_key)
    if isinstance(region_name, dict):
        region_name = region_name.get("name", payload.region_key)
    print(
        f"[playlist.fallback] reason={reason} region={payload.region_key} "
        f"returned={len(tracks)} requested={requested_size}"
    )
    return {
        "name": f"{region_name} Genome Playlist",
        "description": "Fallback playlist built from Sonic DNA seed tracks.",
        "tracks": tracks,
        "size": len(tracks),
        "target_minutes": payload.target_minutes,
        "actual_minutes": None,
        "type": "genome_based",
        "source": "internal_fallback",
        "fallback_reason": reason,
    }


def get_recommendations(cluster_id: int, region_key: str, limit: int = 20) -> dict:
    """Helper used as playlist fallback and for legacy test compatibility."""
    if spotify:
        try:
            tracks = spotify.search_regional_tracks(cluster_id, region_key, limit=limit)
            if tracks:
                return {
                    "cluster_id": cluster_id,
                    "archetype": ARCHETYPES[cluster_id]["name"],
                    "region": region_key,
                    "tracks": tracks,
                    "count": len(tracks),
                    "source": "spotify_regional",
                }
        except Exception as e:
            print(f"[recommendations.error] Spotify regional search failed: {e}")
    
    return _fallback_recommendations(cluster_id, region_key, limit, "spotify_unavailable")



# ════════════════════════════════════════════
# METADATA ENDPOINTS
# ════════════════════════════════════════════

@app.get("/archetypes")
def get_archetypes():
    """Get all archetype definitions."""
    return {"archetypes": ARCHETYPES}


@app.get("/regions")
def get_regions():
    """Get all available music regions."""
    return {"regions": REGIONS}


@app.get("/profile/{user_id}")
def get_profile(user_id: str):
    """Get dataset profile for a user (if using pre-computed genomes)."""
    raise HTTPException(status_code=410, detail="Raw profile lookup is disabled.")


# ════════════════════════════════════════════
# BACKGROUND TASKS
# ════════════════════════════════════════════

@app.post("/admin/process_email_queue")
def process_emails(max_batch: int = 10):
    """
    Manually trigger email queue processing.
    In production, this should be called by a cron job.
    """
    try:
        process_email_queue(max_batch)
        return {"processed": True, "max_batch": max_batch}
    except Exception as e:
        raise HTTPException(status_code=500, detail=_production_safe_detail("Email processing failed", e))


# ── Monitoring (dev-only health endpoint) ─────────────────────────────────
try:
    from monitoring import generate_health_report as _gen_health
    from monitoring.metrics_store import is_monitoring_enabled as _mon_enabled
    _MONITORING_ROUTE_AVAILABLE = True
except ImportError:
    _MONITORING_ROUTE_AVAILABLE = False


@app.get("/admin/health")
def get_health_report():
    """Dev-only health report with rolling metrics and anomaly detection."""
    if not _MONITORING_ROUTE_AVAILABLE:
        raise HTTPException(status_code=501, detail="Monitoring module not available")
    if not _mon_enabled():
        raise HTTPException(status_code=403, detail="Monitoring disabled in this environment")
    try:
        report = _gen_health()
        return report.to_dict()
    except Exception as e:
        raise HTTPException(status_code=500, detail=_production_safe_detail("Health report failed", e))


# ════════════════════════════════════════════
# ERROR HANDLERS
# ════════════════════════════════════════════

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler for unhandled errors."""
    print(f"[error] Unhandled: {_redact_for_log(exc)}")
    print(traceback.format_exc())
    
    payload = {
        "error": "Internal server error",
        "message": "An internal error occurred." if _is_production_environment() else str(exc),
    }
    if not _is_production_environment():
        payload["type"] = type(exc).__name__
    return JSONResponse(payload, status_code=500)


def _generate_user_playlist_internal(
    cluster_id: int,
    user_id: str,
    playlist_size: int = 20,
    target_minutes: Optional[int] = None,
    include_explanations: bool = False,
    session_type: Optional[str] = None,
    mood: Optional[str] = None,
    discovery_ratio: float = 0.5,
    exploration_ratio: float = 0.0,
):
    timeline = get_user_timeline(user_id)
    if not timeline:
        raise HTTPException(status_code=404, detail="No genome data for user")

    # Try to consume hybrid recommendation cache first
    try:
        from app_database import SessionLocal
        from models.recommendation_models import RecommendationCache
        db = SessionLocal()
        try:
            cached_rec = db.query(RecommendationCache).filter(
                RecommendationCache.user_id == user_id,
                RecommendationCache.expires_at > datetime.utcnow()
            ).order_by(RecommendationCache.created_at.desc()).first()

            if cached_rec:
                print(f"[playlist.session] Consuming hybrid recommendation cache for user={user_id}")
                rec_data = json.loads(cached_rec.recommendations_json)
                playlist_tracks = []
                for t in rec_data.get("tracks", []):
                    playlist_tracks.append({
                        "id": t["spotify_uri"].split(":")[-1] if ":" in t["spotify_uri"] else t["spotify_uri"],
                        "uri": t["spotify_uri"],
                        "name": t["track_name"],
                        "artist": t["artist_name"],
                        "popularity": t["popularity"],
                        "reason": t["reason"],
                        "duration_ms": t.get("duration_ms", 180000)
                    })

                # Save generated playlist to database
                try:
                    save_generated_playlist(
                        user_id=user_id,
                        playlist_name=f"{rec_data.get('archetype', 'Genome')} · Playlist",
                        playlist_type=session_type or "hybrid_recommendation",
                        tracks=playlist_tracks,
                        description=rec_data.get("narrative", "") or "Tuned to your music genome archetype.",
                    )
                except Exception as e:
                    print(f"[warning] Failed to save generated playlist to DB: {e}")

                response = {
                    "playlist_name": f"{rec_data.get('archetype', 'Genome')} · Playlist",
                    "description": rec_data.get("narrative", "") or "Tuned to your music genome archetype.",
                    "tracks": playlist_tracks,
                    "size": len(playlist_tracks),
                    "target_minutes": target_minutes or 47,
                    "actual_minutes": len(playlist_tracks) * 3,
                    "type": session_type or "hybrid_recommendation",
                }
                if include_explanations:
                    response["recommendation_explanations"] = {t["id"]: t["reason"] for t in playlist_tracks}
                return response
        finally:
            db.close()
    except Exception as e:
        print(f"[playlist.session.warn] Cache lookup failed, falling back: {e}")

    latest = timeline[0]
    genome = latest["genome"]
    taste_profile = _load_spotify_taste_profile(user_id) if get_spotify_connection(user_id) else None
    tracks = (taste_profile or {}).get("top_tracks") or (get_user_spotify_tracks(user_id) if get_spotify_connection(user_id) else [])

    from user_profile_encoder import get_user_embedding
    user_embedding = get_user_embedding(
        spotify_taste_profile=taste_profile,
        quiz_genome=genome,
        clip_genome=genome,
        archetype={"name": latest.get("archetype_name")},
        embedding_ranker=getattr(spotify, "embedding_ranker", None) if spotify else None,
    )

    result = playlist_generator.generate_regional_genome_playlist(
        user_tracks=tracks,
        genome=genome,
        cluster_id=cluster_id,
        region_key=latest.get("region", "global_english"),
        playlist_size=playlist_size,
        target_minutes=target_minutes,
        taste_profile=taste_profile,
        user_embedding=user_embedding,
        include_explanations=include_explanations,
        session_type=session_type,
        mood=mood,
        discovery_ratio=discovery_ratio,
        exploration_ratio=exploration_ratio,
    )

    # Persist generated playlist to database
    try:
        save_generated_playlist(
            user_id=user_id,
            playlist_name=result.get("name") or "My Genome Playlist",
            playlist_type=session_type or result.get("type", "genome_based"),
            tracks=result.get("tracks") or [],
            description=result.get("description") or "",
        )
    except Exception as e:
        print(f"[warning] Failed to save generated playlist to DB: {e}")

    # ── Serialization boundary: project to response schema ───────────────────
    if _MODELS_AVAILABLE:
        playlist_resp = PlaylistResponse.from_playlist(
            result, include_explanations=include_explanations
        )
        response = playlist_resp.to_dict()
        response["playlist_name"] = response.pop("name", result.get("name"))
    else:
        response = {
            "playlist_name": result["name"],
            "description": result.get("description", ""),
            "tracks": result["tracks"],
            "size": len(result["tracks"]),
            "target_minutes": result.get("target_minutes"),
            "actual_minutes": result.get("actual_minutes"),
            "type": result.get("type", "genome_based"),
        }
        if include_explanations and result.get("recommendation_explanations"):
            response["recommendation_explanations"] = result["recommendation_explanations"]
    return response


@app.post("/playlist/session/{cluster_id}")
def generate_session_playlist(
    cluster_id: int,
    payload: SessionUserPayload,
    playlist_size: int = 20,
    target_minutes: Optional[int] = None,
    include_explanations: bool = False,
):
    user_id = resolve_payload_user(payload.session_token, payload.user_id)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid session.")
    target_minutes = target_minutes or payload.target_minutes or payload.requested_minutes
    with _latency_span("recommendation_total", "playlist_session"):
        return _generate_user_playlist_internal(
            cluster_id=cluster_id,
            user_id=user_id,
            playlist_size=playlist_size,
            target_minutes=target_minutes,
            include_explanations=include_explanations,
            session_type=payload.session_type,
        )


@app.post("/playlist/seasonal")
def generate_seasonal_playlist(
    payload: SessionUserPayload,
    playlist_size: int = 20,
    include_explanations: bool = False,
):
    user_id = resolve_payload_user(payload.session_token, payload.user_id)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid session.")

    timeline = get_user_timeline(user_id)
    if not timeline:
        raise HTTPException(status_code=404, detail="No genome data for user")
    cluster_id = timeline[0].get("cluster_id") or 3

    # Determine seasonal mood
    month = datetime.now().month
    if month in [12, 1, 2]:
        seasonal_mood = "calm"
    elif month in [3, 4, 5]:
        seasonal_mood = "focused"
    elif month in [6, 7, 8]:
        seasonal_mood = "energetic"
    else:
        seasonal_mood = "sad"

    target_minutes = payload.target_minutes or payload.requested_minutes or 30

    with _latency_span("recommendation_total", "playlist_seasonal"):
        return _generate_user_playlist_internal(
            cluster_id=cluster_id,
            user_id=user_id,
            playlist_size=playlist_size,
            target_minutes=target_minutes,
            include_explanations=include_explanations,
            session_type="seasonal",
            mood=seasonal_mood,
        )


@app.post("/playlist/discovery")
def generate_discovery_playlist(
    payload: SessionUserPayload,
    playlist_size: int = 20,
    include_explanations: bool = False,
):
    user_id = resolve_payload_user(payload.session_token, payload.user_id)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid session.")

    timeline = get_user_timeline(user_id)
    if not timeline:
        raise HTTPException(status_code=404, detail="No genome data for user")
    cluster_id = timeline[0].get("cluster_id") or 3

    target_minutes = payload.target_minutes or payload.requested_minutes or 30

    with _latency_span("recommendation_total", "playlist_discovery"):
        return _generate_user_playlist_internal(
            cluster_id=cluster_id,
            user_id=user_id,
            playlist_size=playlist_size,
            target_minutes=target_minutes,
            include_explanations=include_explanations,
            session_type="discovery",
            discovery_ratio=0.8,
            exploration_ratio=0.20,
        )


@app.get("/playlist/{cluster_id}/{user_id}")
def generate_user_playlist(
    cluster_id: int,
    user_id: str,
    playlist_size: int = 20,
    target_minutes: Optional[int] = None
):
    """
    Generate personalized playlist based on user's genome.
    Returns tracks matching their archetype.
    """
    raise HTTPException(status_code=410, detail="Raw user playlist routes are disabled. Use /playlist/session/{cluster_id}.")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid session.")
    try:
        # Get user's latest snapshot to extract genome
        timeline = get_user_timeline(user_id)
        if not timeline:
            raise HTTPException(status_code=404, detail="No genome data for user")
        
        latest = timeline[0]
        genome = latest["genome"]
        
        # Get user's Spotify tracks if available
        tracks = get_user_spotify_tracks(user_id) if get_spotify_connection(user_id) else []
        
        if not tracks:
            # Fallback: use recommendations endpoint
            region = latest.get("region", "global_english")
            return get_recommendations(cluster_id, region, playlist_size)
        
        # Generate playlist using PlaylistGenerator
        result = playlist_generator.generate_regional_genome_playlist(
            user_tracks=tracks,
            genome=genome,
            cluster_id=cluster_id,
            region_key=latest.get("region", "global_english"),
            playlist_size=playlist_size,
            target_minutes=target_minutes
        )
        
        return {
            "playlist_name": result["name"],
            "description": result.get("description", ""),
            "tracks": result["tracks"],
            "size": len(result["tracks"]),
            "target_minutes": result.get("target_minutes"),
            "actual_minutes": result.get("actual_minutes"),
            "type": result.get("type", "genome_based")
        }
        
    except Exception as e:
        print(f"[error] Playlist generation: {_redact_for_log(e)}")
        # Fallback to recommendations
        return get_recommendations(cluster_id, "global_english", playlist_size)


# Synthetic tracks removed - using real Spotify API only


@app.post("/playlist/trial")
def generate_trial_playlist(payload: PlaylistTrialPayload):
    """
    Trial endpoint using REAL Spotify data.
    Requires valid Spotify API credentials.
    """
    if payload.region_key not in REGIONS:
        raise HTTPException(status_code=400, detail=f"Unknown region: {payload.region_key}")

    if payload.target_minutes:
        estimated_size = int(payload.target_minutes / 3.5)
        size = max(5, min(estimated_size, 50))
    else:
        size = max(5, min(payload.playlist_size, 30))

    if not spotify:
        return _fallback_playlist_response(payload, size, "spotify_unavailable")
    
    if not _is_production_environment():
        print("\n" + "="*60)
        print("[playlist.trial] TRIAL PLAYLIST GENERATION")
        print("="*60)
        print(f"Region: {payload.region_key}")
        print(f"Cluster: {payload.cluster_id}")
        print(f"Discovery ratio: {payload.discovery_ratio}")
        print(f"Target minutes: {payload.target_minutes}")
    
    # Use real PlaylistGenerator with real Spotify service
    from user_profile_encoder import get_user_embedding
    trial_generator = PlaylistGenerator(spotify_service=spotify)
    trial_user_embedding = get_user_embedding(
        quiz_genome=payload.genome,
        clip_genome=payload.genome,
        embedding_ranker=getattr(spotify, "embedding_ranker", None),
    )
    
    try:
        with _latency_span("recommendation_total", "playlist_trial"):
            result = trial_generator.generate_regional_genome_playlist(
                user_tracks=[],  # Generator injects curated familiar seeds for trial.
                genome=payload.genome,
                cluster_id=max(0, min(payload.cluster_id, 6)),
                region_key=payload.region_key,
                playlist_size=size,
                discovery_ratio=payload.discovery_ratio,
                target_minutes=payload.target_minutes,
                mood=payload.mood,
                user_embedding=trial_user_embedding,
                exploration_ratio=payload.exploration_factor,
                include_explanations=payload.include_explanations,
                session_type=payload.session_type,
            )
        
        if not _is_production_environment():
            print(f"[playlist.ok] Generated {len(result['tracks'])} tracks")
            for i, track in enumerate(result['tracks'][:3], 1):
                print(f"  {i}. {track['name']} - {track['artist']}")

        # ── Debug envelope (env-gated, never user-facing) ─────────────────────
        if _MODELS_AVAILABLE:
            try:
                from flow_evaluation import is_flow_debug_enabled
                if is_flow_debug_enabled():
                    raw_flow = result.get("flow_report")
                    debug_envelope = DebugPlayloadEnvelope(
                        recommendation_trace=RecommendationTrace.from_playlist(result),
                        flow_report=FlowEvaluationReport.from_raw(raw_flow) if raw_flow else None,
                    )
                    print(f"[debug.envelope] trace_tracks={len(debug_envelope.recommendation_trace.track_traces if debug_envelope.recommendation_trace else [])}")
            except Exception as _dbg_err:
                print(f"[debug.envelope.warn] {_dbg_err}")

        # ── Serialization boundary: project to response schema ────────────────
        if _MODELS_AVAILABLE:
            playlist_resp = PlaylistResponse.from_playlist(
                result, include_explanations=payload.include_explanations
            )
            return playlist_resp.to_dict()
        return result
        
    except Exception as e:
        print(f"[error] Trial playlist generation failed: {_redact_for_log(e)}")
        import traceback
        traceback.print_exc()
        return _fallback_playlist_response(payload, size, "spotify_error")
@app.get("/auth/login")
def auth_login(
    session_token: Optional[str] = None,
    return_to: Optional[str] = None,
    format: Optional[str] = None,
):
    """
    Initiate Spotify OAuth authentication.
    Supports unauthenticated logins (creating/fetching users) as well as
    linking to an existing session.
    """
    with _latency_span("auth_api", "auth_login"):
        if not spotify_oauth or not spotify_oauth.configured():
            raise HTTPException(status_code=503, detail="Spotify OAuth is not configured.")
        state = spotify_oauth.make_state(session_token=session_token, return_to=return_to)
        url = spotify_oauth.authorization_url(state)
        if format == "json":
            return {"url": url, "state": state}
        return RedirectResponse(url)


@app.get("/auth/callback")
def auth_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    """
    Handle Spotify OAuth callback.
    Provisions or finds user in Supabase PostgreSQL via get_or_create_user_from_spotify(),
    stores encrypted connection tokens, issues a signed session token, and redirects
    to frontend.
    """
    with _latency_span("auth_api", "auth_callback"):
        state_payload = spotify_oauth.parse_state(state or "")
        return_to = (state_payload or {}).get("return_to")
        if error:
            return _redirect_with_spotify_status(return_to, "error", error)
        if not state_payload:
            raise HTTPException(status_code=400, detail="Invalid Spotify OAuth state.")
        if not code:
            return _redirect_with_spotify_status(return_to, "error", "missing_code")

        try:
            token_data = spotify_oauth.exchange_code(code)
            current_user = spotify_oauth.get_current_user(token_data["access_token"])

            # 1. Check if an existing session token was provided in state
            user_id = resolve_session_token(state_payload.get("session_token"))
            if not user_id:
                # 2. Provision or fetch existing user from Spotify record in Supabase PostgreSQL
                user = get_or_create_user_from_spotify(
                    spotify_user_id=current_user["id"],
                    display_name=current_user.get("display_name"),
                    email=current_user.get("email"),
                )
                user_id = user["id"]

            existing_connection = get_spotify_connection(user_id)
            refresh_token = token_data.get("refresh_token") or (existing_connection or {}).get("refresh_token")
            if not refresh_token:
                print(f"[auth.callback.missing_refresh_token] user_id={user_id}")
                return _redirect_with_spotify_status(return_to, "error", "missing_refresh_token")

            save_spotify_connection(
                user_id=user_id,
                spotify_user_id=current_user["id"],
                access_token=token_data["access_token"],
                refresh_token=refresh_token,
                expires_in=int(token_data.get("expires_in") or 3600),
            )
            try:
                _load_spotify_taste_profile(user_id)
            except Exception as profile_error:
                print(f"[auth.callback.profile_warning] user_id={user_id} error={_redact_for_log(profile_error)}")

            session_token = make_session_token(user_id)
            return _redirect_with_spotify_status(return_to, "connected", session_token=session_token)
        except Exception as e:
            print(f"[auth.callback.failed] error={_redact_for_log(e)}")
            return _redirect_with_spotify_status(return_to, "error", "connection_failed")


@app.get("/spotify/login")
def spotify_login(
    session_token: Optional[str] = None,
    return_to: Optional[str] = None,
    format: Optional[str] = None,
):
    return auth_login(session_token=session_token, return_to=return_to, format=format)


@app.get("/spotify/callback")
def spotify_callback(code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
    return auth_callback(code=code, state=state, error=error)


@app.get("/callback")
def legacy_spotify_callback(code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
    return auth_callback(code=code, state=state, error=error)


@app.get("/api/debug/verify-genome")
@app.post("/api/debug/verify-genome")
def api_verify_genome():
    """
    Run end-to-end database genome persistence diagnostics.
    Tests mock user insert, sanitizer cleansing, and in-place profile updates without duplication.
    """
    with _latency_span("debug_api", "verify_genome"):
        result = run_genome_verification()
        status_code = 200 if result.get("status") == "passed" else 500
        return JSONResponse(status_code=status_code, content=result)


@app.post("/api/email/trigger-reminders")
def api_trigger_email_reminders(min_days: int = 7, force: bool = False):
    """
    Trigger scheduled Taste Genome recalibration reminder emails.
    """
    with _latency_span("email_api", "trigger_reminders"):
        result = trigger_recalibration_reminders(min_days_since_calibration=min_days, force=force)
        return result


@app.get("/spotify/status")
def spotify_status(session_token: str):
    with _latency_span("spotify_api", "spotify_status"):
        user_id = resolve_session_token(session_token)
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid SonicDNA session.")
        return _spotify_status_payload(user_id, connected=True)


@app.post("/spotify/disconnect")
def spotify_disconnect(payload: SessionUserPayload):
    with _latency_span("spotify_api", "spotify_disconnect"):
        user_id = resolve_session_token(payload.session_token) or payload.user_id
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid SonicDNA session.")
        delete_spotify_connection(user_id)
        return {"connected": False, "disconnected": True}


@app.post("/spotify/save_track")
def save_spotify_track(payload: SaveSpotifyTrackPayload):
    with _latency_span("spotify_api", "spotify_save_track"):
        user_id = resolve_session_token(payload.session_token)
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid session.")

        connection = get_spotify_connection(user_id)
        if not connection:
            raise HTTPException(status_code=400, detail="Spotify account not connected.")

        if not spotify_oauth or not spotify_oauth.configured():
            raise HTTPException(status_code=503, detail="Spotify OAuth is not configured on the server.")

        access_token = connection.get("access_token")
        if spotify_oauth.token_expired(connection):
            try:
                print(f"[spotify.save] Refreshing expired token for user={user_id}")
                tokens = spotify_oauth.refresh_access_token(connection["refresh_token"])
                access_token = tokens["access_token"]
                expires_in = tokens.get("expires_in", 3600)
                token_expires_at = (datetime.utcnow() + timedelta(seconds=expires_in)).isoformat()
                update_spotify_tokens(
                    user_id=user_id,
                    access_token=access_token,
                    refresh_token=tokens.get("refresh_token") or connection["refresh_token"],
                    expires_at=token_expires_at,
                )
            except Exception as e:
                print(f"[error] Spotify token refresh failed: {e}")
                raise HTTPException(status_code=401, detail="Spotify connection needs re-authentication.")

        try:
            spotify_oauth.save_track_for_user(access_token, payload.track_id)
            return {"saved": True, "track_id": payload.track_id}
        except Exception as e:
            print(f"[error] Spotify save track failed: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to save track: {str(e)}")


# ════════════════════════════════════════════
# MAIN ENTRY POINT
# ════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    
    
    print("\n" + "="*50)
    print("🎵 MUSIC TASTE GENOME API v3.0")
    print("="*50)
    print("Features:")
    print("  ✅ Quiz Analysis (Multiple Paths)")
    print("  ✅ Adaptive Questions")
    print("  ✅ Audio Clip Ratings")
    print("  ✅ User Compatibility")
    print("  ✅ Viral Share Links")
    print("  ✅ City Leaderboards")
    print("  ✅ Email Notifications")
    print("  ✅ Spotify Integration")
    print("="*50 + "\n")
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8010")),
        reload=not _is_production_environment(),
        log_level="info"
    )
