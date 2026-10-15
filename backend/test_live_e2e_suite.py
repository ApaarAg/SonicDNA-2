import os
import sys
import json
import urllib.request
import urllib.parse
import pytest

BASE_URL = "http://127.0.0.1:8000"

def request_json(method: str, path: str, data: dict = None, headers: dict = None):
    url = f"{BASE_URL}{path}"
    headers = headers or {}
    if "Content-Type" not in headers and data is not None:
        headers["Content-Type"] = "application/json"
    
    payload = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=payload, headers=headers, method=method)
    
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = resp.read().decode("utf-8")
        status = resp.status
        try:
            return status, json.loads(body)
        except Exception:
            return status, body

def request_raw(method: str, path: str, headers: dict = None):
    url = f"{BASE_URL}{path}"
    headers = headers or {}
    req = urllib.request.Request(url, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.status, resp.read().decode("utf-8"), dict(resp.headers)

def test_01_root_and_static_serving():
    """Verify root HTML delivery, index.html, login.html, and JSON negotiation."""
    # Browser GET to / returns HTML
    status, body, headers = request_raw("GET", "/", {"Accept": "text/html"})
    assert status == 200
    assert "<!doctype html>" in body.lower()
    assert "Sonic DNA" in body
    assert 'id="scene-1"' in body
    assert 'id="scene-quiz"' in body
    assert 'id="scene-share"' in body
    
    # Direct GET to /index.html
    status, body, _ = request_raw("GET", "/index.html")
    assert status == 200
    assert "<!doctype html>" in body.lower()

    # Direct GET to /login.html
    status, body, _ = request_raw("GET", "/login.html")
    assert status == 200
    assert "login" in body.lower()
    assert "guest-btn" in body

    # API GET to / with Accept: application/json returns operational JSON
    status, data = request_json("GET", "/", headers={"Accept": "application/json"})
    assert status == 200
    assert data.get("status") == "operational"
    assert "endpoints" in data

def test_02_health_and_ready():
    """Verify /health and /ready endpoints."""
    status, data = request_json("GET", "/health")
    assert status == 200
    assert data["status"] == "ok"
    assert data["services"]["genome_engine"] is True

    status, data = request_json("GET", "/ready")
    assert status == 200
    assert data["status"] in ["ready", "degraded"]
    assert "genome_engine" in data["services"]

def test_03_full_user_onboarding_journey():
    """Simulate full guest user journey from session init to DNA synthesis, playlist, and share."""
    # Step 1: Session initialization
    status, session_data = request_json("POST", "/user/session", {})
    assert status == 200
    session_token = session_data["session_token"]
    assert session_token.startswith("sd1.") or session_token.startswith("sess_")

    # Step 2: Auth Me check
    status, me_data = request_json("GET", f"/auth/me?session_token={session_token}")
    assert status == 200
    user_id = me_data["user_id"]
    assert bool(user_id)

    # Step 3: Fetch calibration audio clips
    status, clips_data = request_json("GET", f"/clips/round1?count=8&session_key=test_sess_123")
    assert status == 200
    clips = clips_data if isinstance(clips_data, list) else clips_data.get("clips", [])
    assert len(clips) >= 8

    # Step 4: Submit clip ratings
    clip_ratings = [{"clip_id": c["clip_id"], "rating": 5} for c in clips[:4]]
    status, submit_resp = request_json("POST", "/clips/submit", {
        "ratings": clip_ratings,
        "round_number": 1,
        "session_key": "test_sess_123"
    })
    assert status == 200

    # Step 5: Adaptive Question Generation
    status, question_resp = request_json("POST", "/adaptive_question", {
        "previous_answers": [],
        "clip_ratings": clip_ratings,
        "covered_dimensions": [],
        "asked_questions": []
    })
    assert status == 200
    assert "question" in question_resp

    # Step 6: Psychometric Genome Analysis
    answers = [
        "I seek quiet solitude and introspective ambient melodies late at night.",
        "Rhythmic basslines and layered acoustic harmonies bring me sudden euphoria.",
        "Experimental music that challenges conventional structures inspires my creativity."
    ]
    status, analysis_result = request_json("POST", "/analyze_adaptive", {
        "answers": answers,
        "clip_ratings": clip_ratings,
        "region": "japan",
        "session_token": session_token
    })
    assert status == 200
    assert "archetype" in analysis_result
    assert "genome_features" in analysis_result
    cluster_id = analysis_result.get("cluster_id", 0)
    genome_features = analysis_result["genome_features"]
    for trait in ["danceability", "energy", "valence", "acousticness", "instrumentalness", "speechiness", "tempo"]:
        assert trait in genome_features

    # Step 7: Save user snapshot
    status, snapshot_resp = request_json("POST", "/user/save_snapshot", {
        "session_token": session_token,
        "result": analysis_result,
        "region": "japan"
    })
    assert status == 200
    assert snapshot_resp.get("saved") is True or snapshot_resp.get("status") in ["saved", "ok"]

    # Step 8: Generate Flow Playlist
    status, playlist_resp = request_json("POST", f"/playlist/session/{cluster_id}", {
        "user_id": user_id,
        "count": 10,
        "region": "japan"
    })
    assert status == 200
    assert "tracks" in playlist_resp
    assert len(playlist_resp["tracks"]) > 0

    # Step 9: Fetch Worlds / Regional Recommendations
    status, recs_resp = request_json("GET", f"/recommendations/{cluster_id}/japan")
    assert status == 200
    assert isinstance(recs_resp, list) or "tracks" in recs_resp or "recommendations" in recs_resp

    # Step 10: Create and Fetch Share Link
    status, share_resp = request_json("POST", "/share/create", {
        "user_id": user_id,
        "genome_data": {
            "archetype": analysis_result["archetype"],
            "cluster_id": cluster_id,
            "genome_features": genome_features
        }
    })
    assert status == 200
    share_code = share_resp.get("share_code")
    assert share_code is not None

    status, fetched_share = request_json("GET", f"/share/{share_code}")
    assert status == 200
    assert fetched_share.get("share_code") == share_code

    # Step 11: Telemetry Feedback
    status, fb_resp = request_json("POST", "/feedback/events", {
        "session_token": session_token,
        "events": [{"event": "onboarding_completed", "cluster_id": cluster_id}]
    })
    assert status == 200

def test_04_social_and_compatibility():
    """Verify social constellation and user compatibility comparison."""
    # Social stats
    status, stats = request_json("GET", "/social/stats")
    assert status == 200
    assert "total_nodes" in stats or "total_profiles" in stats or "network_density" in stats

    # Social constellation graph
    status, constellation = request_json("GET", "/social/constellation?limit=50&min_similarity=0.4")
    assert status == 200
    assert "nodes" in constellation

    # Compatibility comparison between User A and User B via share code
    _, session_a = request_json("POST", "/user/session", {})
    token_a = session_a["session_token"]
    genome_a = {"danceability": 0.82, "energy": 0.74, "valence": 0.60, "acousticness": 0.20, "instrumentalness": 0.10, "speechiness": 0.05, "tempo": 122}
    result_a = {
        "archetype": "The Midnight Drifter",
        "archetype_name": "The Midnight Drifter",
        "genome_features": genome_a,
        "cluster_id": 0
    }
    request_json("POST", "/user/save_snapshot", {
        "session_token": token_a,
        "result": result_a,
        "region": "japan"
    })

    _, session_b = request_json("POST", "/user/session", {})
    token_b = session_b["session_token"]
    _, me_b = request_json("GET", f"/auth/me?session_token={token_b}")
    user_b_id = me_b["user_id"]

    genome_b = {"danceability": 0.75, "energy": 0.68, "valence": 0.65, "acousticness": 0.25, "instrumentalness": 0.12, "speechiness": 0.06, "tempo": 118}
    result_b = {
        "archetype": "The Solar Dynamo",
        "archetype_name": "The Solar Dynamo",
        "genome_features": genome_b,
        "cluster_id": 3
    }
    request_json("POST", "/user/save_snapshot", {
        "session_token": token_b,
        "result": result_b,
        "region": "japan"
    })

    _, share_b = request_json("POST", "/share/create", {
        "user_id": user_b_id,
        "genome_data": result_b
    })
    share_code_b = share_b["share_code"]

    status, comp_result = request_json("POST", "/compatibility/compare", {
        "session_token": token_a,
        "share_code": share_code_b
    })
    assert status == 200
    assert "score" in comp_result or "overall_compatibility" in comp_result or "genome_similarity" in comp_result

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
