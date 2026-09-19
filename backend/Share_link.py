# ============================================
# SHARE LINK SYSTEM — Phase 2 Viral Loop
# ============================================

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import desc, func, or_

from app_database import (
    GenomeSnapshot,
    SessionLocal,
    ShareLink,
    User,
    create_new_module_tables,
)
from persistence_sanitizer import sanitize_share_payload


# ── Database Schema for Share Links ──────────

def create_share_links_table() -> None:
    """Create the share_links table if it doesn't exist."""
    create_new_module_tables()
    print("✅ Share links table created successfully")


# ── Share Link Generation ────────────────────

def generate_share_link(
    user_id: str,
    snapshot_id: str,
    expiry_days: int = 30,
) -> dict:
    """
    Generate a shareable link for a user's quiz result.
    Returns: {share_code, full_url, expires_at, is_new}
    """
    chars = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    share_code = "".join(secrets.choice(chars) for _ in range(8))
    expires_at = datetime.utcnow() + timedelta(days=expiry_days)

    with SessionLocal() as db:
        existing = (
            db.query(ShareLink)
            .filter(
                ShareLink.inviter_snapshot_id == snapshot_id,
                ShareLink.status == "pending",
                ShareLink.expires_at > datetime.utcnow(),
            )
            .first()
        )
        if existing:
            return sanitize_share_payload({
                "share_code": existing.share_code,
                "full_url": f"https://yourdomain.com/invite/{existing.share_code}",
                "expires_at": existing.expires_at.isoformat() if existing.expires_at else None,
                "is_new": False,
            })

        link_id = str(uuid.uuid4())
        link = ShareLink(
            id=link_id,
            share_code=share_code,
            inviter_user_id=user_id,
            inviter_snapshot_id=snapshot_id,
            expires_at=expires_at,
            status="pending",
            times_accessed=0,
            created_at=datetime.utcnow(),
        )
        db.add(link)
        db.commit()

    return sanitize_share_payload({
        "share_code": share_code,
        "full_url": f"https://yourdomain.com/invite/{share_code}",
        "expires_at": expires_at.isoformat(),
        "is_new": True,
    })


def get_share_link_details(share_code: str) -> Optional[dict]:
    """
    Get details of a share link by code.
    Returns inviter info and validates if link is still active.
    """
    with SessionLocal() as db:
        link = db.query(ShareLink).filter(ShareLink.share_code == share_code).first()
        if not link:
            return None

        link.times_accessed = (link.times_accessed or 0) + 1
        db.commit()

        inviter = db.query(User).filter(User.id == link.inviter_user_id).first()
        snapshot = None
        if link.inviter_snapshot_id:
            snapshot = db.query(GenomeSnapshot).filter(GenomeSnapshot.id == link.inviter_snapshot_id).first()

        is_expired = bool(link.expires_at and link.expires_at < datetime.utcnow())
        is_completed = link.status == "completed"

        return sanitize_share_payload({
            "id": str(link.id),
            "inviter_user_id": str(link.inviter_user_id) if link.inviter_user_id else None,
            "inviter_snapshot_id": str(link.inviter_snapshot_id) if link.inviter_snapshot_id else None,
            "status": link.status,
            "is_valid": not is_expired and not is_completed,
            "is_expired": is_expired,
            "is_completed": is_completed,
            "expires_at": link.expires_at.isoformat() if link.expires_at else None,
            "created_at": link.created_at.isoformat() if link.created_at else None,
            "times_accessed": link.times_accessed,
            "inviter": {
                "display_name": inviter.display_name if inviter else None,
                "email": inviter.email if inviter else None,
                "archetype_name": snapshot.archetype_name if snapshot else None,
                "archetype_id": snapshot.archetype_id if snapshot else None,
            },
        })


def complete_share_link(
    share_code: str,
    invitee_user_id: str,
    invitee_snapshot_id: str,
) -> bool:
    """Mark a share link as completed after friend finishes quiz."""
    with SessionLocal() as db:
        link = (
            db.query(ShareLink)
            .filter(ShareLink.share_code == share_code, ShareLink.status == "pending")
            .first()
        )
        if not link:
            return False

        link.invitee_user_id = invitee_user_id
        link.invitee_snapshot_id = invitee_snapshot_id
        link.status = "completed"
        link.completed_at = datetime.utcnow()
        db.commit()
        return True


def get_user_share_links(user_id: str, include_expired: bool = False) -> List[dict]:
    """Get all share links created by a user."""
    with SessionLocal() as db:
        query = db.query(ShareLink).filter(ShareLink.inviter_user_id == user_id)
        if not include_expired:
            now = datetime.utcnow()
            query = query.filter(or_(ShareLink.expires_at > now, ShareLink.status == "completed"))
        query = query.order_by(desc(ShareLink.created_at))
        rows = query.all()

        links = []
        for sl in rows:
            invitee_user = db.query(User).filter(User.id == sl.invitee_user_id).first() if sl.invitee_user_id else None
            invitee_snap = db.query(GenomeSnapshot).filter(GenomeSnapshot.id == sl.invitee_snapshot_id).first() if sl.invitee_snapshot_id else None
            links.append(sanitize_share_payload({
                "share_code": sl.share_code,
                "status": sl.status,
                "created_at": sl.created_at.isoformat() if sl.created_at else None,
                "completed_at": sl.completed_at.isoformat() if sl.completed_at else None,
                "times_accessed": sl.times_accessed or 0,
                "invitee": {
                    "display_name": invitee_user.display_name if invitee_user else None,
                    "email": invitee_user.email if invitee_user else None,
                    "archetype": invitee_snap.archetype_name if invitee_snap else None,
                } if invitee_user else None,
            }))
        return links


def invalidate_share_link(share_code: str) -> bool:
    """Manually invalidate a share link."""
    with SessionLocal() as db:
        link = (
            db.query(ShareLink)
            .filter(ShareLink.share_code == share_code, ShareLink.status == "pending")
            .first()
        )
        if not link:
            return False
        link.status = "expired"
        db.commit()
        return True


# ── Analytics ─────────────────────────────────

def get_share_link_analytics(user_id: str) -> dict:
    """Get viral loop analytics for a user."""
    with SessionLocal() as db:
        total_created = db.query(func.count(ShareLink.id)).filter(ShareLink.inviter_user_id == user_id).scalar() or 0
        completed = db.query(func.count(ShareLink.id)).filter(ShareLink.inviter_user_id == user_id, ShareLink.status == "completed").scalar() or 0
        total_views = db.query(func.coalesce(func.sum(ShareLink.times_accessed), 0)).filter(ShareLink.inviter_user_id == user_id).scalar() or 0

        conversion_rate = (completed / total_created * 100) if total_created > 0 else 0

        return sanitize_share_payload({
            "total_links_created": int(total_created),
            "links_completed": int(completed),
            "friends_brought": int(completed),
            "total_link_views": int(total_views),
            "conversion_rate": round(conversion_rate, 1),
        })


def get_global_viral_stats() -> dict:
    """Get platform-wide viral loop statistics."""
    with SessionLocal() as db:
        total_links = db.query(func.count(ShareLink.id)).scalar() or 0
        completed = db.query(func.count(ShareLink.id)).filter(ShareLink.status == "completed").scalar() or 0
        avg_views = db.query(func.coalesce(func.avg(ShareLink.times_accessed), 0.0)).scalar() or 0.0

        return sanitize_share_payload({
            "total_share_links_created": int(total_links),
            "total_completed": int(completed),
            "global_conversion_rate": round((completed / total_links * 100) if total_links > 0 else 0, 1),
            "avg_views_per_link": round(float(avg_views), 1),
            "viral_coefficient": round(completed / total_links, 2) if total_links > 0 else 0,
        })
