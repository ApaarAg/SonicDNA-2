"""
taste_evolution.py
==================
SonicDNA — Longitudinal Taste Drift Engine  (Loop Step 2)

Autonomous background worker that tracks how a user's musical taste evolves
over time by periodically pulling their Spotify listening activity, computing
average audio features, classifying an archetype, and persisting an immutable
``TasteDriftSnapshot`` row.

Architecture
------------
* Completely independent of the HTTP request cycle.
* Runs inside the FastAPI lifespan's background asyncio loop (see main.py).
* One failed user never aborts the loop — exceptions are caught per-user.
* Uses *only* the pure-Python ``_build_profile_from_genome`` / centroid logic
  from ``engine.py`` so that heavy pandas/numpy are NOT imported at module
  level — keeping cold-start memory under the 512 MB Render free-tier cap.

Public surface
--------------
  track_taste_drift()   — async coroutine; call once per scheduled interval.
  DRIFT_INTERVAL_DAYS   — how many days between automatic refreshes (default 7).
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sonicdna.taste_evolution")

# ── Constants ─────────────────────────────────────────────────────────────────

DRIFT_INTERVAL_DAYS: int = int(os.getenv("TASTE_DRIFT_INTERVAL_DAYS", "7"))
TRACKS_PER_PULL: int = 20       # number of recent/top tracks to fetch per user
MAX_USERS_PER_RUN: int = 100    # safety cap — avoids hammering Spotify API

# Audio features we care about for the drift snapshot (all 0–1 normalised)
_DRIFT_FEATURES = ("energy", "valence", "danceability", "acousticness")

# Genome feature names that the centroid similarity calculation expects
_SHARED_FEATURES = (
    "danceability", "energy", "valence",
    "acousticness", "instrumentalness", "speechiness", "tempo",
)

# Cluster centroids from engine.py (copied here so this module is self-contained
# and does NOT import engine.py at module level — preserving lazy-load semantics)
_CLUSTER_CENTROIDS: Dict[int, Dict[str, float]] = {
    0: {"danceability": -0.213, "energy": -0.112, "valence": -0.644,
        "acousticness": -0.090, "instrumentalness":  1.779,
        "speechiness": -0.082, "tempo": -0.122},
    1: {"danceability": -0.836, "energy":  1.184, "valence": -0.319,
        "acousticness": -1.024, "instrumentalness": -0.228,
        "speechiness":  0.311, "tempo":  0.776},
    2: {"danceability": -0.333, "energy": -0.230, "valence": -0.256,
        "acousticness":  0.218, "instrumentalness": -0.402,
        "speechiness": -0.370, "tempo":  0.331},
    3: {"danceability":  0.839, "energy":  0.180, "valence":  0.914,
        "acousticness": -0.212, "instrumentalness": -0.440,
        "speechiness": -0.248, "tempo": -0.316},
    4: {"danceability":  0.067, "energy": -0.111, "valence":  0.084,
        "acousticness":  0.119, "instrumentalness":  0.042,
        "speechiness": -0.144, "tempo": -0.057},
    5: {"danceability": -0.438, "energy": -1.776, "valence": -0.925,
        "acousticness":  1.845, "instrumentalness":  0.403,
        "speechiness": -0.611, "tempo": -0.803},
    6: {"danceability":  1.219, "energy":  0.232, "valence":  0.804,
        "acousticness": -0.328, "instrumentalness": -0.359,
        "speechiness":  2.488, "tempo": -0.295},
}

# Archetype names aligned with engine.ARCHETYPES
_ARCHETYPE_NAMES: Dict[int, str] = {
    0: "The Architect of Silence",
    1: "The Storm Chaser",
    2: "The Midnight Drifter",
    3: "The Eternal Optimist",
    4: "The Cartographer",
    5: "The Quiet Storm",
    6: "The Groove Architect",
}


# ── Pure-Python Genome Helpers (no pandas / sklearn) ──────────────────────────

def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """Cosine similarity between two equal-length float lists."""
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    denom = norm_a * norm_b
    return dot / denom if denom > 1e-9 else 0.0


def _classify_archetype(feature_avgs: Dict[str, float]) -> str:
    """
    Given a dict of average audio features (0–1 normalised, as returned by
    SpotifyOAuthService.sanitize_track), return the best-matching archetype
    name using cosine similarity against the cluster centroids.

    The centroids are in Z-score space, but a lightweight linear rescaling
    (value → value * 2 - 1.0) brings the 0-1 features into roughly the same
    sign-direction as the centroids, which is sufficient for a nearest-neighbour
    classification.  No pandas / sklearn required.
    """
    # Rescale 0-1 features towards centroid space sign conventions
    user_vec = [
        float(feature_avgs.get(f, 0.5)) * 2.0 - 1.0
        for f in _SHARED_FEATURES
    ]
    best_cluster, best_sim = 0, -999.0
    for cluster_id, centroid in _CLUSTER_CENTROIDS.items():
        c_vec = [float(centroid.get(f, 0.0)) for f in _SHARED_FEATURES]
        sim = _cosine_similarity(user_vec, c_vec)
        if sim > best_sim:
            best_sim = sim
            best_cluster = cluster_id
    return _ARCHETYPE_NAMES.get(best_cluster, "Unknown")


def _average_features(tracks: List[Dict[str, Any]]) -> Dict[str, float]:
    """
    Compute per-feature averages across a list of sanitized track dicts.
    Returns a dict with keys from _DRIFT_FEATURES (and the full _SHARED_FEATURES
    superset for archetype classification).
    """
    all_keys = set(_DRIFT_FEATURES) | set(_SHARED_FEATURES)
    totals: Dict[str, float] = {k: 0.0 for k in all_keys}
    counts: Dict[str, int] = {k: 0 for k in all_keys}

    for track in tracks:
        for key in all_keys:
            raw = track.get(key)
            if raw is not None:
                try:
                    totals[key] += float(raw)
                    counts[key] += 1
                except (TypeError, ValueError):
                    pass

    return {
        k: round(totals[k] / counts[k], 4) if counts[k] > 0 else 0.5
        for k in all_keys
    }


# ── User Eligibility Query ────────────────────────────────────────────────────

def _get_eligible_users() -> List[Dict[str, Any]]:
    """
    Return users who have a live Spotify connection AND whose last drift
    snapshot is either missing or older than DRIFT_INTERVAL_DAYS.

    Returns a list of dicts with keys: user_id, access_token, refresh_token,
    token_expires_at, spotify_user_id.
    """
    from app_database import (
        SessionLocal, User, SpotifyConnection, TasteDriftSnapshot,
    )
    from sqlalchemy import desc, func

    cutoff = datetime.utcnow() - timedelta(days=DRIFT_INTERVAL_DAYS)

    with SessionLocal() as db:
        # Subquery: latest drift snapshot recorded_at per user
        latest_drift_sq = (
            db.query(
                TasteDriftSnapshot.user_id,
                func.max(TasteDriftSnapshot.recorded_at).label("last_drift"),
            )
            .group_by(TasteDriftSnapshot.user_id)
            .subquery()
        )

        rows = (
            db.query(User, SpotifyConnection, latest_drift_sq.c.last_drift)
            .join(SpotifyConnection, SpotifyConnection.user_id == User.id)
            .outerjoin(latest_drift_sq, latest_drift_sq.c.user_id == User.id)
            .filter(
                # Only users where drift is stale or has never been recorded
                (latest_drift_sq.c.last_drift == None)  # noqa: E711
                | (latest_drift_sq.c.last_drift < cutoff)
            )
            .order_by(func.coalesce(latest_drift_sq.c.last_drift, User.created_at).asc())
            .limit(MAX_USERS_PER_RUN)
            .all()
        )

    # Decrypt tokens outside the session
    from token_security import decrypt_token

    eligible = []
    for user, conn, _last_drift in rows:
        try:
            access_token = decrypt_token(conn.access_token)
            refresh_token = decrypt_token(conn.refresh_token)
        except Exception:
            continue  # skip users with corrupted tokens
        eligible.append({
            "user_id": str(user.id),
            "spotify_user_id": conn.spotify_user_id,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_expires_at": conn.token_expires_at,
        })

    return eligible


# ── Per-User Processing ───────────────────────────────────────────────────────

def _refresh_token_if_needed(user_entry: Dict[str, Any]) -> str:
    """
    Check expiry; if within 90 seconds, refresh and persist the new token.
    Returns a valid access_token string.
    """
    from datetime import timezone
    from spotify_oauth_service import SpotifyOAuthService

    svc = SpotifyOAuthService(state_secret=os.getenv("STATE_SECRET", "sonicdna"))
    expires_at = user_entry["token_expires_at"]

    # Normalise timezone
    if expires_at and expires_at.tzinfo is not None:
        expires_at = expires_at.replace(tzinfo=None)

    needs_refresh = (
        expires_at is None
        or datetime.utcnow() + timedelta(seconds=90) >= expires_at
    )

    if needs_refresh:
        try:
            token_data = svc.refresh_access_token(user_entry["refresh_token"])
            new_access = token_data["access_token"]
            new_expires_in = int(token_data.get("expires_in", 3600))

            # Persist refreshed tokens
            from app_database import update_spotify_tokens
            update_spotify_tokens(
                user_id=user_entry["user_id"],
                access_token=new_access,
                expires_in=new_expires_in,
                refresh_token=token_data.get("refresh_token"),
            )
            return new_access
        except Exception as exc:
            logger.warning(
                "[drift.token_refresh_failed] user=%s err=%s",
                user_entry["user_id"], exc,
            )
            # Fall back to possibly-expired token; Spotify will 401 and we'll skip
            return user_entry["access_token"]

    return user_entry["access_token"]


def _process_user(user_entry: Dict[str, Any]) -> Optional[str]:
    """
    Execute the full drift pipeline for a single user.

    1. Refresh access token if near expiry.
    2. Fetch top + recent tracks from Spotify.
    3. Sanitize and compute average audio features.
    4. Classify archetype via centroid cosine similarity.
    5. Persist a TasteDriftSnapshot row.

    Returns the new snapshot UUID on success, or None on failure.
    """
    user_id = user_entry["user_id"]

    # Step 1: valid access token
    access_token = _refresh_token_if_needed(user_entry)

    # Step 2: fetch Spotify data
    from spotify_oauth_service import SpotifyOAuthService
    svc = SpotifyOAuthService(state_secret=os.getenv("STATE_SECRET", "sonicdna"))

    try:
        top_tracks = svc.get_user_top_tracks(
            access_token, limit=TRACKS_PER_PULL, time_range="short_term"
        )
    except Exception:
        top_tracks = []

    try:
        recent_raw = svc.get_recent_tracks(access_token, limit=TRACKS_PER_PULL)
    except Exception:
        recent_raw = []

    # Step 3: sanitize and combine
    all_tracks: List[Dict[str, Any]] = []
    for t in top_tracks:
        try:
            all_tracks.append(svc.sanitize_track(t, source="spotify_top"))
        except Exception:
            pass
    for t in recent_raw:
        try:
            all_tracks.append(svc.sanitize_track(t, source="spotify_recent"))
        except Exception:
            pass

    if not all_tracks:
        logger.info("[drift.no_tracks] user=%s — skipping snapshot", user_id)
        return None

    # Step 4: compute average features + classify archetype
    feature_avgs = _average_features(all_tracks)
    archetype_name = _classify_archetype(feature_avgs)

    # Step 5: persist
    from app_database import save_taste_drift_snapshot
    snap_id = save_taste_drift_snapshot(
        user_id=user_id,
        energy=feature_avgs.get("energy"),
        valence=feature_avgs.get("valence"),
        danceability=feature_avgs.get("danceability"),
        acousticness=feature_avgs.get("acousticness"),
        active_archetype=archetype_name,
        source="background_spotify",
    )

    logger.info(
        "[drift.snapshot_saved] user=%s archetype=%r snap_id=%s",
        user_id, archetype_name, snap_id,
    )
    return snap_id


# ── Main Scheduler Coroutine ──────────────────────────────────────────────────

async def track_taste_drift() -> Dict[str, Any]:
    """
    Async coroutine — entry point for the background drift scheduler.

    Finds all eligible users, processes each one (silently skipping failures),
    and returns a summary dict.  Designed to be called by the FastAPI lifespan
    asyncio loop on a weekly interval.

    Example usage (in lifespan)::

        asyncio.create_task(_drift_loop())

    where _drift_loop is the repeating wrapper defined in main.py.
    """
    logger.info("[drift.run_start] Scanning for users due for a taste drift update...")

    # Run blocking DB query in the thread-pool so we don't block the event loop
    loop = asyncio.get_event_loop()
    try:
        eligible = await loop.run_in_executor(None, _get_eligible_users)
    except Exception as exc:
        logger.error("[drift.eligible_query_failed] %s", exc)
        return {"status": "error", "error": str(exc), "processed": 0}

    logger.info("[drift.eligible_count] count=%d", len(eligible))

    processed, succeeded, failed = 0, 0, 0
    for user_entry in eligible:
        processed += 1
        try:
            snap_id = await loop.run_in_executor(None, _process_user, user_entry)
            if snap_id:
                succeeded += 1
            else:
                failed += 1
        except Exception as exc:
            failed += 1
            logger.warning(
                "[drift.user_failed] user=%s err=%s",
                user_entry.get("user_id", "?"), exc,
            )

        # Polite inter-user delay — avoids hitting Spotify rate limits
        await asyncio.sleep(0.5)

    summary = {
        "status": "ok",
        "processed": processed,
        "succeeded": succeeded,
        "failed": failed,
        "run_at": datetime.utcnow().isoformat() + "Z",
    }
    logger.info("[drift.run_complete] %s", summary)
    return summary
