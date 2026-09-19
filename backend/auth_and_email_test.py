import os
import pytest
from fastapi.testclient import TestClient

from main import app
from email_client import get_email_provider, send_email
from email_templates import render_recalibration_reminder
from email_scheduler import trigger_recalibration_reminders
from genome_verification import run_genome_verification

client = TestClient(app)


def test_auth_login_redirect_and_json():
    # Test json format response
    res_json = client.get("/auth/login?format=json")
    assert res_json.status_code == 200
    data = res_json.json()
    assert "url" in data
    assert "state" in data
    assert "accounts.spotify.com/authorize" in data["url"]

    # Test standard redirect response
    res_redirect = client.get("/auth/login", follow_redirects=False)
    assert res_redirect.status_code in (302, 307)
    assert "accounts.spotify.com/authorize" in res_redirect.headers.get("location", "")


def test_auth_callback_validation():
    # Missing state
    res = client.get("/auth/callback", follow_redirects=False)
    assert res.status_code == 400

    # Error parameter from Spotify
    res_err = client.get("/auth/callback?error=access_denied&state=invalid", follow_redirects=False)
    assert res_err.status_code in (302, 307)
    assert "spotify=error" in res_err.headers.get("location", "")


def test_email_client_mock_dispatch():
    provider = get_email_provider()
    # In test environment without external API keys, it falls back to mock or configured SMTP
    assert provider in ("mock", "smtp", "resend", "sendgrid")

    res = send_email(
        to_email="explorer@test.local",
        subject="SonicDNA Test",
        html_content="<p>Test</p>",
    )
    assert res["status"] in ("sent", "simulated")


def test_email_template_rendering():
    html = render_recalibration_reminder(
        display_name="Sonic Pioneer",
        archetype="Neon Dreamer",
        shadow_archetype="The Maverick",
        days_elapsed=10,
        recalibrate_url="https://sonicdna.app/#quiz",
    )
    assert "Neon Dreamer" in html
    assert "The Maverick" in html
    assert "10 days" in html
    assert "https://sonicdna.app/#quiz" in html


def test_trigger_recalibration_reminders_structure():
    result = trigger_recalibration_reminders(min_days_since_calibration=30, limit=5)
    assert result["status"] == "ok"
    assert "processed_users" in result
    assert "sent" in result
    assert "skipped" in result


def test_genome_verification_endpoint():
    res = client.get("/api/debug/verify-genome")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "passed"
    checks = data["checks"]
    assert checks["sanitizer_cleansed_transients"] is True
    assert checks["user_inserted"] is True
    assert checks["initial_snapshot_created"] is True
    assert checks["user_archetype_synced"] is True
    assert checks["user_genome_vector_valid"] is True
    assert checks["profile_update_succeeded"] is True
    assert checks["no_duplicate_users"] is True
    assert checks["profile_updated_in_place"] is True
    assert checks["timeline_history_appended"] is True
    assert checks["cleanup_complete"] is True
