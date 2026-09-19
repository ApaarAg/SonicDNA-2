"""
Unified email client supporting Resend, SendGrid, SMTP, and simulated mock fallback.
Auto-detects provider based on EMAIL_API_KEY / RESEND_API_KEY / SENDGRID_API_KEY or SMTP credentials.
"""

from __future__ import annotations

import json
import logging
import os
import smtplib
import uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, Optional
import urllib.request
import urllib.error

from dotenv import load_dotenv

# Ensure local .ENV is loaded if present
ENV_PATH = Path(__file__).parent / ".ENV"
load_dotenv(dotenv_path=ENV_PATH)

logger = logging.getLogger("sonicdna.email")

DEFAULT_SENDER = os.getenv("EMAIL_FROM") or os.getenv("SENDER_EMAIL") or "SonicDNA <noreply@sonicdna.app>"


def get_email_provider() -> str:
    """
    Determine the active email provider based on environment variables.
    Returns one of: 'resend', 'sendgrid', 'smtp', 'mock'.
    """
    key = (os.getenv("EMAIL_API_KEY") or "").strip()
    resend_key = (os.getenv("RESEND_API_KEY") or "").strip()
    sendgrid_key = (os.getenv("SENDGRID_API_KEY") or "").strip()

    if resend_key or key.startswith("re_"):
        return "resend"
    if sendgrid_key or key.startswith("SG."):
        return "sendgrid"

    smtp_server = os.getenv("SMTP_SERVER") or os.getenv("SMTP_HOST")
    smtp_user = os.getenv("SMTP_USERNAME") or os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASSWORD") or os.getenv("SMTP_PASS")
    if smtp_server and smtp_user and smtp_pass:
        return "smtp"

    return "mock"


def _send_resend(
    to_email: str,
    subject: str,
    html_content: str,
    from_email: str,
    api_key: str,
) -> Dict[str, Any]:
    url = "https://api.resend.com/emails"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "SonicDNA-Backend/3.0",
    }
    payload = json.dumps({
        "from": from_email,
        "to": [to_email],
        "subject": subject,
        "html": html_content,
    }).encode("utf-8")

    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp_body = resp.read().decode("utf-8")
            data = json.loads(resp_body) if resp_body else {}
            return {
                "status": "sent",
                "provider": "resend",
                "id": data.get("id"),
                "error": None,
            }
    except urllib.error.HTTPError as err:
        err_msg = err.read().decode("utf-8", errors="ignore")
        logger.error(f"[email.resend.error] code={err.code} body={err_msg}")
        return {
            "status": "failed",
            "provider": "resend",
            "id": None,
            "error": f"HTTP {err.code}: {err_msg[:200]}",
        }
    except Exception as exc:
        logger.error(f"[email.resend.exception] {exc}")
        return {
            "status": "failed",
            "provider": "resend",
            "id": None,
            "error": str(exc),
        }


def _send_sendgrid(
    to_email: str,
    subject: str,
    html_content: str,
    from_email: str,
    api_key: str,
) -> Dict[str, Any]:
    url = "https://api.sendgrid.com/v3/mail/send"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "SonicDNA-Backend/3.0",
    }
    # Parse sender format "Name <email@domain>" if present
    sender_addr = from_email
    sender_name = "SonicDNA"
    if "<" in from_email and ">" in from_email:
        parts = from_email.split("<")
        sender_name = parts[0].strip() or sender_name
        sender_addr = parts[1].split(">")[0].strip()

    payload = json.dumps({
        "personalizations": [{"to": [{"email": to_email}]}],
        "from": {"email": sender_addr, "name": sender_name},
        "subject": subject,
        "content": [{"type": "text/html", "value": html_content}],
    }).encode("utf-8")

    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            msg_id = resp.headers.get("X-Message-Id") or f"sg-{uuid.uuid4().hex[:8]}"
            return {
                "status": "sent",
                "provider": "sendgrid",
                "id": msg_id,
                "error": None,
            }
    except urllib.error.HTTPError as err:
        err_msg = err.read().decode("utf-8", errors="ignore")
        logger.error(f"[email.sendgrid.error] code={err.code} body={err_msg}")
        return {
            "status": "failed",
            "provider": "sendgrid",
            "id": None,
            "error": f"HTTP {err.code}: {err_msg[:200]}",
        }
    except Exception as exc:
        logger.error(f"[email.sendgrid.exception] {exc}")
        return {
            "status": "failed",
            "provider": "sendgrid",
            "id": None,
            "error": str(exc),
        }


def _send_smtp(
    to_email: str,
    subject: str,
    html_content: str,
    from_email: str,
) -> Dict[str, Any]:
    host = os.getenv("SMTP_SERVER") or os.getenv("SMTP_HOST") or "localhost"
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USERNAME") or os.getenv("SMTP_USER") or ""
    pwd = os.getenv("SMTP_PASSWORD") or os.getenv("SMTP_PASS") or ""

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_email
        msg["To"] = to_email
        msg.attach(MIMEText(html_content, "html"))

        with smtplib.SMTP(host, port, timeout=10) as server:
            server.starttls()
            if user and pwd:
                server.login(user, pwd)
            server.send_message(msg)

        return {
            "status": "sent",
            "provider": "smtp",
            "id": f"smtp-{uuid.uuid4().hex[:8]}",
            "error": None,
        }
    except Exception as exc:
        logger.error(f"[email.smtp.failed] {exc}")
        return {
            "status": "failed",
            "provider": "smtp",
            "id": None,
            "error": str(exc),
        }


def send_email(
    to_email: str,
    subject: str,
    html_content: str,
    from_email: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Send an email via configured provider (Resend, SendGrid, SMTP, or Mock).
    Returns a standardized dictionary with status, provider, id, and error.
    """
    sender = from_email or DEFAULT_SENDER
    provider = get_email_provider()

    if provider == "resend":
        api_key = os.getenv("RESEND_API_KEY") or os.getenv("EMAIL_API_KEY") or ""
        return _send_resend(to_email, subject, html_content, sender, api_key)

    if provider == "sendgrid":
        api_key = os.getenv("SENDGRID_API_KEY") or os.getenv("EMAIL_API_KEY") or ""
        return _send_sendgrid(to_email, subject, html_content, sender, api_key)

    if provider == "smtp":
        return _send_smtp(to_email, subject, html_content, sender)

    # Provider == "mock"
    mock_id = f"mock-{uuid.uuid4().hex[:12]}"
    print(f"[email.mock_dispatch] to={to_email} subject='{subject}' provider=mock id={mock_id}")
    return {
        "status": "sent",
        "provider": "mock",
        "id": mock_id,
        "error": None,
        "simulated": True,
    }
