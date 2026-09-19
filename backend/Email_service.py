# ============================================
# MUSIC TASTE GENOME — Email Service
# Phase 2: Retention & Notification System
# ============================================

import os
import smtplib
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, Dict
from datetime import datetime
import uuid
from app_database import SessionLocal, EmailQueue, create_new_module_tables, get_user_by_id, get_user_timeline
from dotenv import load_dotenv
from persistence_sanitizer import sanitize_email_payload

ENV_PATH = Path(__file__).parent / ".ENV"
load_dotenv(dotenv_path=ENV_PATH)

# ── Email Configuration ──────────────────────
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SENDER_EMAIL = os.getenv("SENDER_EMAIL", SMTP_USERNAME)
SENDER_NAME = os.getenv("SENDER_NAME", "Music Taste Genome")

# Frontend URL for links
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://127.0.0.1:3000")


# ════════════════════════════════════════════
# EMAIL QUEUE MIGRATION
# ════════════════════════════════════════════

def migrate_email_system():
    """Create email queue table for async email delivery."""
    create_new_module_tables()
    print("✅ Email system migration completed")


# ════════════════════════════════════════════
# EMAIL SENDING
# ════════════════════════════════════════════

def send_email(recipient: str, subject: str, html_body: str) -> bool:
    """
    Send an email using SMTP.
    Returns True if successful, False otherwise.
    """
    if not SMTP_USERNAME or not SMTP_PASSWORD:
        print("⚠️ SMTP credentials not configured, skipping email")
        return False
    
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{SENDER_NAME} <{SENDER_EMAIL}>"
        msg["To"] = recipient
        
        html_part = MIMEText(html_body, "html")
        msg.attach(html_part)
        
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
        
        print(f"✅ Email sent to {recipient}: {subject}")
        return True
    
    except Exception as e:
        print(f"❌ Failed to send email to {recipient}: {e}")
        return False


# ════════════════════════════════════════════
# EMAIL QUEUE MANAGEMENT
# ════════════════════════════════════════════

def queue_email(
    user_id: str,
    recipient_email: str,
    subject: str,
    body_html: str,
    email_type: str
) -> str:
    """Add an email to the queue for later delivery."""
    email_id = str(uuid.uuid4())
    payload = sanitize_email_payload({
        "user_id": user_id,
        "recipient_email": recipient_email,
        "subject": subject,
        "body_html": body_html,
        "email_type": email_type,
    })
    
    with SessionLocal() as db:
        item = EmailQueue(
            id=email_id,
            user_id=payload.get("user_id"),
            recipient_email=payload.get("recipient_email"),
            subject=payload.get("subject"),
            body_html=payload.get("body_html"),
            email_type=payload.get("email_type"),
            status="pending",
            created_at=datetime.utcnow(),
        )
        db.add(item)
        db.commit()
    
    return email_id


def process_email_queue(max_batch: int = 10):
    """
    Process pending emails in the queue.
    Call this from a background job/cron.
    """
    with SessionLocal() as db:
        emails = (
            db.query(EmailQueue)
            .filter(EmailQueue.status == "pending", EmailQueue.retry_count < 3)
            .order_by(EmailQueue.created_at.asc())
            .limit(max_batch)
            .all()
        )
    
        for item in emails:
            success = send_email(item.recipient_email, item.subject, item.body_html)
            if success:
                item.status = "sent"
                item.sent_at = datetime.utcnow()
            else:
                item.status = "failed"
                item.failed_at = datetime.utcnow()
                item.retry_count = (item.retry_count or 0) + 1
                item.error_message = "SMTP delivery failed"
            db.commit()


# ════════════════════════════════════════════
# EMAIL TEMPLATES
# ════════════════════════════════════════════

def get_comparison_complete_email(
    creator_name: str,
    friend_name: str,
    compatibility_score: float,
    share_code: str
) -> str:
    """Email sent when someone completes your comparison link."""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 40px 20px; }}
            .score {{ font-size: 48px; font-weight: bold; color: #6366f1; text-align: center; margin: 20px 0; }}
            .button {{ display: inline-block; background: #6366f1; color: white; padding: 12px 24px; 
                       text-decoration: none; border-radius: 6px; margin: 20px 0; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🎵 Someone Took Your Music Quiz!</h1>
            
            <p>Hey {creator_name},</p>
            
            <p><strong>{friend_name}</strong> just completed your Music Taste Genome quiz!</p>
            
            <div class="score">{compatibility_score}%</div>
            <p style="text-align: center; color: #666;">Musical Compatibility</p>
            
            <p style="text-align: center;">
                <a href="{FRONTEND_URL}/results/{share_code}" class="button">
                    View Full Comparison
                </a>
            </p>
            
            <p>See how your genomes align and discover your shared wavelength.</p>
            
            <hr style="margin: 40px 0; border: none; border-top: 1px solid #eee;">
            
            <p style="color: #666; font-size: 14px;">
                Music Taste Genome • Decode your sonic DNA
            </p>
        </div>
    </body>
    </html>
    """


def get_retake_reminder_email(
    user_name: str,
    last_taken_date: str,
    user_id: str
) -> str:
    """Email reminding users to retake the quiz."""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 40px 20px; }}
            .button {{ display: inline-block; background: #6366f1; color: white; padding: 12px 24px; 
                       text-decoration: none; border-radius: 6px; margin: 20px 0; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🎵 Has Your Taste Evolved?</h1>
            
            <p>Hey {user_name},</p>
            
            <p>It's been a while since you took the Music Taste Genome quiz (last time: {last_taken_date}).</p>
            
            <p>Your musical genome changes as you discover new artists and moods. 
               Even 2 data points on your timeline chart feel meaningful — see how you've evolved.</p>
            
            <p style="text-align: center;">
                <a href="{FRONTEND_URL}/quiz" class="button">
                    Retake the Quiz
                </a>
            </p>
            
            <p>Takes just 2 minutes, and you'll see your genome timeline chart.</p>
            
            <hr style="margin: 40px 0; border: none; border-top: 1px solid #eee;">
            
            <p style="color: #666; font-size: 14px;">
                Music Taste Genome • Track your sonic evolution
            </p>
        </div>
    </body>
    </html>
    """


def get_share_link_created_email(
    user_name: str,
    share_code: str
) -> str:
    """Email sent when user creates a share link."""
    share_url = f"{FRONTEND_URL}/compare/{share_code}"
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 40px 20px; }}
            .share-url {{ background: #f3f4f6; padding: 16px; border-radius: 8px; 
                          font-family: monospace; word-break: break-all; margin: 20px 0; }}
            .button {{ display: inline-block; background: #6366f1; color: white; padding: 12px 24px; 
                       text-decoration: none; border-radius: 6px; margin: 20px 0; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🎵 Your Share Link is Ready!</h1>
            
            <p>Hey {user_name},</p>
            
            <p>Share this link with friends to see how your music tastes compare:</p>
            
            <div class="share-url">{share_url}</div>
            
            <p>When they complete the quiz, you'll both see:</p>
            <ul>
                <li>📊 Compatibility score</li>
                <li>🎯 Archetype alignment</li>
                <li>🎵 Shared musical wavelength</li>
            </ul>
            
            <p style="text-align: center;">
                <a href="{share_url}" class="button">
                    View Your Share Link
                </a>
            </p>
            
            <p style="color: #666; font-size: 14px;">
                <strong>Pro tip:</strong> Every friend who takes your quiz is one more data point 
                showing how unique (or universal) your taste really is.
            </p>
            
            <hr style="margin: 40px 0; border: none; border-top: 1px solid #eee;">
            
            <p style="color: #666; font-size: 14px;">
                Music Taste Genome • Find your wavelength
            </p>
        </div>
    </body>
    </html>
    """


# ════════════════════════════════════════════
# HIGH-LEVEL EMAIL TRIGGERS
# ════════════════════════════════════════════

def send_comparison_complete_notification(
    creator_user_id: str,
    friend_name: str,
    compatibility_score: float,
    share_code: str
):
    """
    Notify the creator that someone completed their quiz.
    This is a KEY growth trigger — makes people feel the viral loop.
    """
    creator = get_user_by_id(creator_user_id)
    if not creator or not creator.get("email") or str(creator.get("email")).endswith("@sonicdna.local"):
        return
    
    subject = f"🎵 {friend_name} took your Music Taste Quiz!"
    body = get_comparison_complete_email(
        creator["display_name"],
        friend_name,
        compatibility_score,
        share_code
    )
    
    # Queue for delivery
    queue_email(
        creator_user_id,
        creator["email"],
        subject,
        body,
        "comparison_complete"
    )


def send_retake_reminder(user_id: str):
    """
    Send retake reminder to users who haven't taken the quiz in a while.
    Call this from a scheduled job.
    """
    user = get_user_by_id(user_id)
    if not user or not user.get("email") or str(user.get("email")).endswith("@sonicdna.local"):
        return
    
    timeline = get_user_timeline(user_id)
    if not timeline:
        return
    
    last_snapshot = timeline[0]
    last_taken = last_snapshot.get("taken_at", "")
    
    subject = "🎵 Has your music taste evolved?"
    body = get_retake_reminder_email(
        user["display_name"],
        last_taken[:10] if last_taken else "a while ago",
        user_id
    )
    
    queue_email(
        user_id,
        user["email"],
        subject,
        body,
        "retake_reminder"
    )


def send_share_link_created_notification(user_id: str, share_code: str):
    """
    Send confirmation when user creates a share link.
    Reinforces the action and provides easy copy-paste.
    """
    user = get_user_by_id(user_id)
    if not user or not user.get("email") or str(user.get("email")).endswith("@sonicdna.local"):
        return
    
    subject = "🎵 Your Music Taste share link is ready"
    body = get_share_link_created_email(
        user["display_name"],
        share_code
    )
    
    queue_email(
        user_id,
        user["email"],
        subject,
        body,
        "share_link_created"
    )
