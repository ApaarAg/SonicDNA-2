import argparse
import sys
from html import escape
from typing import Callable, Dict, List, Optional

from datetime import datetime, timedelta
from app_database import SessionLocal, get_user_timeline, User, GenomeSnapshot, EmailQueue
from sqlalchemy import func
from Email_service import FRONTEND_URL, queue_email
from retention_engine import RetentionEngine


RETENTION_EMAIL_TYPES = ("archetype_change", "genome_shift")
RECENT_SEND_WINDOW_DAYS = 4


def run_retention_pipeline(limit: Optional[int] = None, dry_run: bool = False) -> dict:
    """
    Evaluate users with at least two genome snapshots and queue retention emails.

    The scheduler only reads from the existing tables and queues via queue_email(),
    so it does not modify the email queue schema or bypass Email_service.
    """
    users = fetch_retention_candidates(limit=limit)
    engine = RetentionEngine()
    summary = {
        "users_checked": len(users),
        "eligible": 0,
        "queued": 0,
        "skipped": 0,
    }

    for user in users:
        timeline = get_user_timeline(user["id"])
        if len(timeline) < 2:
            summary["skipped"] += 1
            continue

        latest_snapshot = timeline[0]
        previous_snapshot = timeline[1]
        decision = engine.evaluate(previous_snapshot, latest_snapshot)

        if not decision.get("should_send"):
            summary["skipped"] += 1
            continue

        summary["eligible"] += 1

        if has_recent_retention_email(user["id"]):
            summary["skipped"] += 1
            continue

        if dry_run:
            summary["skipped"] += 1
            continue

        subject, body_html = build_retention_email(user, decision)
        queue_email(
            user["id"],
            user["email"],
            subject,
            body_html,
            decision["email_type"],
        )
        summary["queued"] += 1

    return summary


def fetch_retention_candidates(limit: Optional[int] = None) -> List[dict]:
    """Fetch users who have an email address and enough history to evaluate."""
    with SessionLocal() as db:
        subq = (
            db.query(GenomeSnapshot.user_id, func.count(GenomeSnapshot.id).label("snap_cnt"))
            .group_by(GenomeSnapshot.user_id)
            .having(func.count(GenomeSnapshot.id) >= 2)
            .subquery()
        )
        query = (
            db.query(User)
            .join(subq, User.id == subq.c.user_id)
            .filter(
                User.email.isnot(None),
                User.email != "",
                ~User.email.like("anonymous+%@sonicdna.local")
            )
            .order_by(User.created_at.asc())
        )
        if limit is not None:
            query = query.limit(max(0, int(limit)))
        users = query.all()
        return [
            {
                "id": str(u.id),
                "email": u.email,
                "display_name": u.display_name or (u.email.split("@")[0] if u.email else "there"),
            }
            for u in users
        ]


def has_recent_retention_email(
    user_id: str,
    window_days: int = RECENT_SEND_WINDOW_DAYS,
) -> bool:
    """Return True if any retention email was queued for the user recently."""
    cutoff = datetime.utcnow() - timedelta(days=int(window_days))
    with SessionLocal() as db:
        recent = (
            db.query(EmailQueue.id)
            .filter(
                EmailQueue.user_id == user_id,
                EmailQueue.email_type.in_(RETENTION_EMAIL_TYPES),
                EmailQueue.created_at >= cutoff,
            )
            .first()
        )
        return recent is not None


def build_retention_email(user: dict, decision: dict) -> tuple:
    """Choose a retention template based on the RetentionEngine email_type."""
    email_type = decision.get("email_type")
    template = EMAIL_TEMPLATES.get(email_type, _genome_shift_email)
    return template(user, decision)


def _archetype_change_email(user: dict, decision: dict) -> tuple:
    name = escape(user.get("display_name") or "there")
    old_archetype = escape(decision.get("old_archetype") or "your earlier profile")
    new_archetype = escape(decision.get("new_archetype") or "your new profile")
    shift_score = escape(str(decision.get("shift_score", 0)))
    results_url = f"{FRONTEND_URL}/timeline?user_id={user['id']}"

    subject = "Your SonicDNA archetype changed"
    body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 40px 20px; }}
            .button {{ display: inline-block; background: #6366f1; color: white; padding: 12px 24px;
                       text-decoration: none; border-radius: 6px; margin: 20px 0; }}
            .change {{ background: #f3f4f6; padding: 16px; border-radius: 8px; margin: 20px 0; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Your music profile has shifted</h1>
            <p>Hey {name},</p>
            <p>Your latest SonicDNA snapshot shows a new archetype.</p>
            <div class="change">
                <strong>{old_archetype}</strong> to <strong>{new_archetype}</strong><br>
                Shift score: {shift_score}
            </div>
            <p>Your listening patterns are moving in a new direction. Your timeline has the full comparison.</p>
            <p style="text-align: center;">
                <a href="{results_url}" class="button">View your timeline</a>
            </p>
            <hr style="margin: 40px 0; border: none; border-top: 1px solid #eee;">
            <p style="color: #666; font-size: 14px;">SonicDNA - Track your music evolution</p>
        </div>
    </body>
    </html>
    """
    return subject, body


def _genome_shift_email(user: dict, decision: dict) -> tuple:
    name = escape(user.get("display_name") or "there")
    shift_score = escape(str(decision.get("shift_score", 0)))
    dominant_change = decision.get("dominant_change") or {}
    feature = escape(str(dominant_change.get("feature") or "your sound"))
    direction = escape(str(dominant_change.get("direction") or "changed"))
    results_url = f"{FRONTEND_URL}/timeline?user_id={user['id']}"

    subject = "Your SonicDNA has noticeably shifted"
    body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 40px 20px; }}
            .button {{ display: inline-block; background: #6366f1; color: white; padding: 12px 24px;
                       text-decoration: none; border-radius: 6px; margin: 20px 0; }}
            .metric {{ background: #f3f4f6; padding: 16px; border-radius: 8px; margin: 20px 0; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Your music taste is evolving</h1>
            <p>Hey {name},</p>
            <p>Your latest SonicDNA snapshot shows a meaningful genome shift.</p>
            <div class="metric">
                Shift score: <strong>{shift_score}</strong><br>
                Biggest movement: <strong>{feature}</strong> {direction}
            </div>
            <p>Open your timeline to compare the two snapshots side by side.</p>
            <p style="text-align: center;">
                <a href="{results_url}" class="button">View your timeline</a>
            </p>
            <hr style="margin: 40px 0; border: none; border-top: 1px solid #eee;">
            <p style="color: #666; font-size: 14px;">SonicDNA - Track your music evolution</p>
        </div>
    </body>
    </html>
    """
    return subject, body


EMAIL_TEMPLATES: Dict[str, Callable[[dict, dict], tuple]] = {
    "archetype_change": _archetype_change_email,
    "genome_shift": _genome_shift_email,
}


def run(limit: Optional[int] = None, dry_run: bool = False) -> dict:
    """Convenience alias for cron or manual scripts."""
    return run_retention_pipeline(limit=limit, dry_run=dry_run)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the SonicDNA retention scheduler once.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Evaluate retention decisions without queueing emails.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of retention candidates to evaluate.",
    )
    args = parser.parse_args()

    try:
        summary = run_retention_pipeline(limit=args.limit, dry_run=args.dry_run)
    except Exception as exc:
        summary = {
            "users_checked": 0,
            "eligible": 0,
            "queued": 0,
            "skipped": 0,
        }
        raw_message = exc.args[1] if len(getattr(exc, "args", ())) > 1 else str(exc)
        message = raw_message.split(";")[0].strip()
        print(f"error: retention scheduler failed: {message}", file=sys.stderr)

    print(f"users_checked: {summary['users_checked']}")
    print(f"eligible: {summary['eligible']}")
    print(f"queued: {summary['queued']}")
    print(f"skipped: {summary['skipped']}")


if __name__ == "__main__":
    main()
