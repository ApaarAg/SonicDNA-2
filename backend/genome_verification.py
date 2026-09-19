"""
Database Genome Persistence Verification Diagnostics.
Tests insert, fetch, and update of user genome vectors and archetypes in Supabase PostgreSQL.
Verifies:
1. Sanitization via persistence_sanitizer.py.
2. In-place profile UPDATE (zero duplicate user rows).
3. Genome vector and timeline persistence integrity.
4. Clean test artifact teardown.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict

from app_database import (
    SessionLocal,
    User,
    GenomeSnapshot,
    save_genome_snapshot,
    get_user_by_id,
    get_user_timeline,
    update_user_genome_profile,
)
from persistence_sanitizer import sanitize_snapshot_payload

logger = logging.getLogger("sonicdna.verify")


def run_genome_verification() -> Dict[str, Any]:
    """
    Execute end-to-end database genome persistence diagnostics.
    Returns structured results dictionary.
    """
    mock_uuid = uuid.uuid4()
    run_id = mock_uuid.hex[:8]
    mock_user_id = str(mock_uuid)
    mock_email = f"verify-{run_id}@sonicdna-test.local"
    checks = {}
    cleanup_success = False

    try:
        # ── Step 1: Sanitizer Verification ──
        dirty_payload = {
            "danceability": 0.74,
            "energy": 0.82,
            "valence": 0.65,
            "acousticness": 0.12,
            "instrumentalness": 0.05,
            "speechiness": 0.08,
            "tempo": 126.0,
            "ranking_diagnostics": "should_be_stripped",
            "_internal_cache": {"sample": 1},
            "candidate_pool": ["track_abc", "track_xyz"],
            "raw_embedding": [0.1, 0.2, 0.3],
        }
        sanitized = sanitize_snapshot_payload(dirty_payload)
        sanitizer_passed = (
            "ranking_diagnostics" not in sanitized
            and "_internal_cache" not in sanitized
            and "candidate_pool" not in sanitized
            and "raw_embedding" not in sanitized
            and sanitized.get("danceability") == 0.74
            and sanitized.get("tempo") == 126.0
        )
        checks["sanitizer_cleansed_transients"] = sanitizer_passed

        # ── Step 2: User Insertion ──
        with SessionLocal() as db:
            mock_user = User(
                id=mock_user_id,
                email=mock_email,
                display_name=f"Mock User {run_id}",
                created_at=datetime.utcnow(),
                last_seen=datetime.utcnow(),
            )
            db.add(mock_user)
            db.commit()

        initial_fetch = get_user_by_id(mock_user_id)
        checks["user_inserted"] = bool(initial_fetch and initial_fetch.get("id") == mock_user_id)

        # ── Step 3: Initial Snapshot & In-place Sync ──
        initial_result = {
            "archetype": "Neon Dreamer",
            "secondary_name": "The Maverick",
            "primary_pct": 75.0,
            "secondary_pct": 25.0,
            "genome": sanitized,
        }
        snap_id = save_genome_snapshot(
            user_id=mock_user_id,
            result=initial_result,
            region="global_english",
        )
        checks["initial_snapshot_created"] = bool(snap_id)

        # Verify User profile was synchronized with archetype
        user_after_snap = get_user_by_id(mock_user_id)
        checks["user_archetype_synced"] = (
            user_after_snap is not None
            and user_after_snap.get("archetype") == "Neon Dreamer"
            and user_after_snap.get("shadow_archetype") == "The Maverick"
        )

        # Verify User.genome_vector calculation
        with SessionLocal() as db:
            db_user = db.query(User).filter(User.id == mock_user_id).first()
            vec = db_user.genome_vector if db_user else []
            checks["user_genome_vector_valid"] = len(vec) == 7 and any(v > 0 for v in vec)

        # ── Step 4: Profile Update (Recalibration) & Anti-Duplication Check ──
        updated_result_payload = {
            "archetype": "Bass Alchemist",
            "shadow_archetype": "The Minimalist",
            "confidence": 0.91,
            "primary_pct": 80.0,
            "secondary_pct": 20.0,
            "genome": {
                "danceability": 0.89,
                "energy": 0.95,
                "valence": 0.40,
                "acousticness": 0.04,
                "instrumentalness": 0.28,
                "speechiness": 0.14,
                "tempo": 142.0,
                "temporary_ranking_diagnostics": "strip_me_too",
            },
        }

        update_summary = update_user_genome_profile(
            user_id=mock_user_id,
            result=updated_result_payload,
            region="global_english",
        )
        checks["profile_update_succeeded"] = bool(update_summary and update_summary.get("updated"))

        # Verify NO duplicate user rows were created in users table
        with SessionLocal() as db:
            user_count_by_id = db.query(User).filter(User.id == mock_user_id).count()
            user_count_by_email = db.query(User).filter(User.email == mock_email).count()
            checks["no_duplicate_users"] = (user_count_by_id == 1 and user_count_by_email == 1)

            # Check profile updated in place
            refreshed_user = db.query(User).filter(User.id == mock_user_id).first()
            checks["profile_updated_in_place"] = (
                refreshed_user is not None
                and refreshed_user.archetype == "Bass Alchemist"
                and refreshed_user.shadow_archetype == "The Minimalist"
            )

        # Verify timeline appended
        timeline = get_user_timeline(mock_user_id)
        checks["timeline_history_appended"] = len(timeline) == 2

    except Exception as exc:
        logger.error(f"[genome.verification.failure] {exc}", exc_info=True)
        checks["exception"] = str(exc)

    finally:
        # ── Step 5: Teardown Test Fixtures ──
        try:
            with SessionLocal() as db:
                db.query(GenomeSnapshot).filter(GenomeSnapshot.user_id == mock_user_id).delete()
                db.query(User).filter(User.id == mock_user_id).delete()
                db.commit()
            cleanup_success = True
        except Exception as cleanup_exc:
            logger.error(f"[genome.verification.cleanup_failed] {cleanup_exc}")
            cleanup_success = False

    checks["cleanup_complete"] = cleanup_success
    all_passed = (
        "exception" not in checks
        and len(checks) >= 7
        and all(v is True for k, v in checks.items() if k != "exception")
    )

    return {
        "status": "passed" if all_passed else "failed",
        "mock_user_id": mock_user_id,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "checks": checks,
    }
