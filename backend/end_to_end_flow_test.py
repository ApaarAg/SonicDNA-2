import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from fastapi.testclient import TestClient


def test_round1_clip_endpoint_returns_requested_playable_audio():
    import main

    client = TestClient(main.app)
    for requested in (10, 20):
        response = client.get(f"/clips/round1?count={requested}&session_key=test-{requested}&diagnostics=true")

        assert response.status_code == 200
        payload = response.json()
        clips = payload["clips"]
        assert len(clips) == requested

        for clip in clips:
            assert clip["audio_url"]
            audio_response = client.get(clip["audio_url"])
            assert audio_response.status_code == 200
            assert audio_response.headers["content-type"] == "audio/mpeg"
            assert len(audio_response.content) > 100_000


def test_recommendations_default_to_full_result_count(monkeypatch):
    import main

    class FakeSpotify:
        def search_regional_tracks(self, cluster_id, region_key, limit):
            self.requested = limit
            return [
                {"id": f"track-{idx}", "name": f"Track {idx}", "artist": "Artist"}
                for idx in range(limit)
            ]

    fake = FakeSpotify()
    monkeypatch.setattr(main, "spotify", fake)

    payload = main.get_recommendations(3, "global_english")

    assert fake.requested == 20
    assert payload["count"] == 20


def test_recommendations_fall_back_when_spotify_is_unavailable(monkeypatch):
    import main

    monkeypatch.setattr(main, "spotify", None)

    payload = main.get_recommendations(3, "global_english")

    assert payload["count"] == 20
    assert payload["source"] == "internal_fallback"
    assert payload["tracks"][0]["name"]


def test_trial_playlist_falls_back_when_spotify_is_unavailable(monkeypatch):
    import main

    monkeypatch.setattr(main, "spotify", None)

    payload = main.PlaylistTrialPayload(
        genome={"energy": 0.7, "valence": 0.6, "danceability": 0.5},
        cluster_id=3,
        region_key="global_english",
        target_minutes=None,
        playlist_size=12,
    )

    result = main.generate_trial_playlist(payload)

    assert result["source"] == "internal_fallback"
    assert result["size"] == 12
    assert len(result["tracks"]) == 12


def test_analyze_adaptive_uses_clip_fallback_when_ai_provider_fails(monkeypatch):
    import main

    class BrokenGroq:
        @property
        def chat(self):
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(main, "groq_client", BrokenGroq())

    payload = main.AdaptiveOpenPayload(
        answers=["I like bright energetic music because it keeps me moving."],
        clip_ratings=[
            {"clip_id": "cal_01", "rating": 5},
            {"clip_id": "cal_02", "rating": 4},
            {"clip_id": "cal_03", "rating": 2},
        ],
        region="global_english",
    )

    result = main.analyze_adaptive(payload)

    assert result["source"] in {"adaptive_clip_fallback", "adaptive_blend"}
    assert result["genome_features"]
    assert result["archetype"]["name"]
