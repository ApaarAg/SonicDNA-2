"""
Background scheduling utility for periodic Taste Genome recalibration reminders.
Finds users who haven't updated their profile in 7-14 days and dispatches email notifications.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from app_database import SessionLocal, User, GenomeSnapshot, EmailQueue
from email_client import send_email
from email_templates import render_recalibration_reminder
from persistence_sanitizer import sanitize_email_payload

logger = logging.getLogger("sonicdna.scheduler")

_scheduler_task: Optional[asyncio.Task] = None
_stop_event: Optional[asyncio.Event] = None


def _to_naive_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _get_frontend_url() -> str:
    return (
        os.getenv("FRONTEND_URL")
        or os.getenv("SONICDNA_FRONTEND_URL")
        or "https://sonicdna.app"
    ).rstrip("/")


def trigger_recalibration_reminders(
    min_days_since_calibration: int = 7,
    cooldown_days: int = 7,
    force: bool = False,
    limit: int = 50,
) -> Dict[str, Any]:
    """
    Check for eligible users and send Taste Genome recalibration reminders.
    Ensures users are not messaged more than once per cooldown period.
    """
    frontend_url = _get_frontend_url()
    recalibrate_url = f"{frontend_url}/#quiz"
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff_calibration = now - timedelta(days=min_days_since_calibration)
    cooldown_cutoff = now - timedelta(days=cooldown_days)

    sent_count = 0
    skipped_count = 0
    failed_count = 0
    processed_users = 0

    with SessionLocal() as db:
        users = (
            db.query(User)
            .filter(User.email.isnot(None))
            .filter(~User.email.endswith("@sonicdna.local"))
            .order_by(User.last_seen.asc())
            .limit(limit)
            .all()
        )

        for user in users:
            processed_users += 1
            user_id = str(user.id)
            user_email = user.email.strip()

            # Find latest snapshot
            latest_snapshot = (
                db.query(GenomeSnapshot)
                .filter(GenomeSnapshot.user_id == user.id)
                .order_by(GenomeSnapshot.taken_at.desc())
                .first()
            )

            raw_date = latest_snapshot.taken_at if latest_snapshot else user.created_at
            last_date = _to_naive_utc(raw_date)
            if not last_date:
                skipped_count += 1
                continue

            days_elapsed = max(1, (now - last_date).days)
            if last_date > cutoff_calibration and not force:
                skipped_count += 1
                continue

            # Check cooldown via EmailQueue
            recent_emails = (
                db.query(EmailQueue)
                .filter(EmailQueue.user_id == user.id)
                .filter(EmailQueue.email_type == "genome_recalibration_reminder")
                .filter(EmailQueue.status == "sent")
                .order_by(EmailQueue.sent_at.desc())
                .limit(5)
                .all()
            )
            is_in_cooldown = False
            for em in recent_emails:
                sent_date = _to_naive_utc(em.sent_at)
                if sent_date and sent_date >= cooldown_cutoff:
                    is_in_cooldown = True
                    break

            if is_in_cooldown and not force:
                skipped_count += 1
                continue

            # Render email
            archetype = user.archetype or (latest_snapshot.archetype_name if latest_snapshot else None)
            shadow_archetype = user.shadow_archetype or (latest_snapshot.secondary_name if latest_snapshot else None)
            subject = "🎵 Has your music taste evolved? Recalibrate your SonicDNA"
            html_body = render_recalibration_reminder(
                display_name=user.display_name or "Sonic Explorer",
                archetype=archetype,
                shadow_archetype=shadow_archetype,
                days_elapsed=days_elapsed,
                recalibrate_url=recalibrate_url,
            )

            # Queue item in EmailQueue
            clean_payload = sanitize_email_payload({
                "user_id": user_id,
                "recipient_email": user_email,
                "subject": subject,
                "body_html": html_body,
                "email_type": "genome_recalibration_reminder",
            })

            queue_entry = EmailQueue(
                user_id=clean_payload["user_id"],
                recipient_email=clean_payload["recipient_email"],
                subject=clean_payload["subject"],
                body_html=clean_payload["body_html"],
                email_type=clean_payload["email_type"],
                status="pending",
                created_at=now,
            )
            db.add(queue_entry)
            db.commit()

            # Dispatch via email client
            dispatch = send_email(
                to_email=user_email,
                subject=subject,
                html_content=html_body,
            )

            if dispatch.get("status") in ("sent", "simulated"):
                queue_entry.status = "sent"
                queue_entry.sent_at = datetime.utcnow()
                sent_count += 1
            else:
                queue_entry.status = "failed"
                queue_entry.failed_at = datetime.utcnow()
                queue_entry.error_message = dispatch.get("error") or "Unknown error"
                failed_count += 1

            db.commit()

    return {
        "status": "ok",
        "processed_users": processed_users,
        "sent": sent_count,
        "skipped": skipped_count,
        "failed": failed_count,
        "timestamp": now.isoformat() + "Z",
    }


async def _scheduler_loop(interval_seconds: int = 86400):
    logger.info(f"[email.scheduler] Background runner started with interval {interval_seconds}s")
    while _stop_event and not _stop_event.is_set():
        try:
            # Run reminder check in thread pool so it does not block the async event loop
            await asyncio.to_thread(trigger_recalibration_reminders)
        except Exception as exc:
            logger.error(f"[email.scheduler.error] {exc}", exc_info=True)

        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=float(interval_seconds))
        except asyncio.TimeoutError:
            pass


def start_email_scheduler(interval_seconds: Optional[int] = None) -> None:
    """Start background email reminder scheduler."""
    global _scheduler_task, _stop_event
    if _scheduler_task and not _scheduler_task.done():
        return

    # Check if disabled
    if os.getenv("DISABLE_EMAIL_SCHEDULER", "").lower() in ("true", "1", "yes"):
        logger.info("[email.scheduler] Disabled via DISABLE_EMAIL_SCHEDULER")
        return

    interval = interval_seconds or int(os.getenv("EMAIL_SCHEDULER_INTERVAL_SECONDS", "86400"))
    _stop_event = asyncio.Event()
    loop = asyncio.get_event_loop()
    _scheduler_task = loop.create_task(_scheduler_loop(interval))


def stop_email_scheduler() -> None:
    """Stop background email scheduler gracefully."""
    global _scheduler_task, _stop_event
    if _stop_event:
        _stop_event.set()
    if _scheduler_task:
        _scheduler_task.cancel()
        _scheduler_task = None
