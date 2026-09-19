import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))

from fastapi.testclient import TestClient

import main
from spotify_oauth_service import SpotifyOAuthService


def test_oauth_state_round_trips_session_and_rejects_unsafe_return_url():
    service = SpotifyOAuthService("test-secret")

    state = service.make_state("session-123", "https://evil.example/callback")
    payload = service.parse_state(state)

    assert payload["session_token"] == "session-123"
    assert payload["return_to"] is None
    assert service.parse_state(state + "tampered") is None


def test_sanitize_track_tolerates_malformed_spotify_metadata():
    service = SpotifyOAuthService("test-secret")

    track = service.sanitize_track(
        {
            "id": None,
            "name": None,
            "artists": [{"id": "a1", "name": None}, "bad-artist"],
            "album": {"name": None, "images": "bad-images"},
            "duration_ms": "not-a-number",
            "popularity": "popular",
            "external_urls": "not-a-dict",
            "preview_url": None,
        },
        artist_genres={"a1": "indie pop"},
    )

    assert track["name"] == "Unknown Track"
    assert track["artist"] == "Unknown Artist"
    assert track["genres"] == ["indie pop"]
    assert track["duration_ms"] == 180000
    assert track["popularity"] == 0
    assert track["external_url"] == ""


def test_spotify_status_marks_missing_refresh_token_as_reconnect_required(monkeypatch):
    expired = (datetime.utcnow() - timedelta(minutes=5)).isoformat()
    monkeypatch.setattr(main.spotify_oauth, "configured", lambda: True)
    monkeypatch.setattr(
        main,
        "get_spotify_connection",
        lambda user_id: {
            "spotify_user_id": "sp-user",
            "access_token": "expired-access",
            "refresh_token": "",
            "token_expires_at": expired,
        },
    )
    monkeypatch.setattr(main, "get_user_spotify_tracks", lambda user_id: [])

    status = main._spotify_status_payload("user-1")

    assert status["connected"] is False
    assert status["reconnect_required"] is True
    assert status["auth_status"] == "missing_refresh_token"
    assert status["profile_ready"] is False


def test_spotify_callback_rejects_first_connection_without_refresh_token(monkeypatch):
    saved = []
    monkeypatch.setattr(main.spotify_oauth, "parse_state", lambda state: {"session_token": "valid-session", "return_to": "http://127.0.0.1:3000"})
    monkeypatch.setattr(main, "resolve_session_token", lambda token: "user-1" if token == "valid-session" else None)
    monkeypatch.setattr(main.spotify_oauth, "exchange_code", lambda code: {"access_token": "access-only", "expires_in": 3600})
    monkeypatch.setattr(main.spotify_oauth, "get_current_user", lambda access_token: {"id": "sp-user", "display_name": "Listener"})
    monkeypatch.setattr(main, "get_spotify_connection", lambda user_id: None)
    monkeypatch.setattr(main, "save_spotify_connection", lambda **kwargs: saved.append(kwargs))

    response = main.spotify_callback(code="code", state="state")

    assert "spotify=error" in response.headers["location"]
    assert "missing_refresh_token" in response.headers["location"]
    assert saved == []


def test_spotify_disconnect_clears_connection_for_session(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "resolve_session_token", lambda token: "user-1" if token == "valid-session" else None)
    monkeypatch.setattr(main, "delete_spotify_connection", lambda user_id: calls.append(user_id) or True)

    client = TestClient(main.app)
    response = client.post("/spotify/disconnect", json={"session_token": "valid-session"})

    assert response.status_code == 200
    assert response.json() == {"connected": False, "disconnected": True}
    assert calls == ["user-1"]


def test_spotify_tokens_are_encrypted_at_rest(monkeypatch):
    from cryptography.fernet import Fernet
    from token_security import decrypt_token, encrypt_token, is_encrypted_token

    monkeypatch.setenv("SPOTIFY_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

    encrypted = encrypt_token("refresh-secret")

    assert encrypted != "refresh-secret"
    assert is_encrypted_token(encrypted)
    assert decrypt_token(encrypted) == "refresh-secret"
    assert decrypt_token("legacy-plaintext") == "legacy-plaintext"


def test_production_environment_validation_blocks_insecure_defaults(monkeypatch):
    for key in (
        "SESSION_TOKEN_SECRET",
        "SPOTIFY_REDIRECT_URI",
        "FRONTEND_URL",
        "SONICDNA_FRONTEND_URL",
        "SPOTIFY_TOKEN_ENCRYPTION_KEY",
        "CORS_ALLOW_ORIGINS",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SONICDNA_ENV", "production")

    report = main.validate_deployment_environment()

    joined = "\n".join(report["errors"])
    assert "SESSION_TOKEN_SECRET" in joined
    assert "SPOTIFY_REDIRECT_URI" in joined
    assert "FRONTEND_URL" in joined
    assert "SPOTIFY_TOKEN_ENCRYPTION_KEY" in joined


def test_cors_origins_are_restricted_in_production(monkeypatch):
    monkeypatch.setenv("SONICDNA_ENV", "production")
    monkeypatch.setenv("SONICDNA_FRONTEND_URL", "https://app.sonicdna.example/home")
    monkeypatch.delenv("FRONTEND_URL", raising=False)
    monkeypatch.delenv("CORS_ALLOW_ORIGINS", raising=False)

    assert main._cors_origins() == ["https://app.sonicdna.example"]


def test_redacts_tokens_from_log_text():
    redacted = main._redact_for_log(
        "Authorization: Bearer access-secret access_token=access-secret refresh_token=refresh-secret"
    )

    assert "access-secret" not in redacted
    assert "refresh-secret" not in redacted
    assert "[redacted]" in redacted


def test_spotify_disconnect_records_latency(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "resolve_session_token", lambda token: "user-1" if token == "valid-session" else None)
    monkeypatch.setattr(main, "delete_spotify_connection", lambda user_id: True)
    monkeypatch.setattr(main, "_record_latency", lambda metric, duration_ms, context=None: calls.append((metric, context)))

    client = TestClient(main.app)
    response = client.post("/spotify/disconnect", json={"session_token": "valid-session"})

    assert response.status_code == 200
    assert ("spotify_api", "spotify_disconnect") in calls


def test_readiness_endpoint_is_deploy_safe_and_omits_secret_values(monkeypatch):
    monkeypatch.setenv("SONICDNA_ENV", "production")
    monkeypatch.setenv("SESSION_TOKEN_SECRET", "x" * 48)
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "https://api.sonicdna.example/spotify/callback")
    monkeypatch.setenv("SONICDNA_FRONTEND_URL", "https://sonicdna.example")
    monkeypatch.setenv("SPOTIFY_TOKEN_ENCRYPTION_KEY", "secret-encryption-key")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://sonicdna.example")

    client = TestClient(main.app)
    response = client.get("/ready")
    body = response.json()
    text = str(body)

    assert response.status_code == 200
    assert body["status"] in {"ready", "degraded"}
    assert body["environment"] == "production"
    assert "secret-encryption-key" not in text
    assert "xxxxxxxx" not in text


def test_security_headers_are_attached_to_api_responses():
    client = TestClient(main.app)
    response = client.get("/health")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert response.headers["cache-control"] == "no-store"


def test_production_exception_handler_hides_internal_error_type(monkeypatch):
    monkeypatch.setenv("SONICDNA_ENV", "production")

    import anyio

    class Boom(Exception):
        pass

    response = anyio.run(main.global_exception_handler, None, Boom("database password leaked"))
    body = response.body.decode("utf-8")

    assert response.status_code == 500
    assert "database password leaked" not in body
    assert "Boom" not in body
