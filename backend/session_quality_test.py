import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from playlist_generator import PlaylistGenerator


def _playlist_track(idx, duration_ms=180_000):
    return {
        "id": f"track-{idx}",
        "name": f"Track {idx}",
        "artist": f"Artist {idx}",
        "album": "Test Album",
        "duration_ms": duration_ms,
        "popularity": 60,
        "danceability": 0.55,
        "energy": 0.52,
        "valence": 0.58,
        "acousticness": 0.25,
        "instrumentalness": 0.05,
        "speechiness": 0.06,
        "tempo": 118,
        "source": "library",
    }


def _target_ms(minutes):
    return minutes * 60_000


def test_playlist_generation_uses_duration_budget_for_15_30_and_60_minutes(monkeypatch):
    monkeypatch.setattr("playlist_generator._reorder_for_flow", None)
    generator = PlaylistGenerator()
    tracks = [_playlist_track(i) for i in range(40)]
    genome = {
        "danceability": 0.2,
        "energy": 0.1,
        "valence": 0.3,
        "acousticness": -0.2,
        "instrumentalness": -0.5,
        "speechiness": -0.4,
        "tempo": 0.0,
    }

    results = {}
    for minutes in (15, 30, 60):
        playlist = generator.generate_regional_genome_playlist(
            user_tracks=tracks,
            genome=genome,
            cluster_id=3,
            region_key="global_english",
            playlist_size=40,
            discovery_ratio=0.0,
            target_minutes=minutes,
        )
        total_ms = sum(track["duration_ms"] for track in playlist["tracks"])
        target_ms = _target_ms(minutes)
        assert target_ms * 0.90 <= total_ms <= target_ms * 1.10
        results[minutes] = len(playlist["tracks"])

    assert results == {15: 5, 30: 10, 60: 20}


def test_clip_asset_rotation_uses_all_files_before_repeating():
    from clip_rotation import ClipAssetRotator

    clips_dir = Path(__file__).parent / "data" / "clips"
    folder = clips_dir / "Upbeat latinafrobeats"
    assert len(list(folder.glob("*.mp3"))) >= 3

    features = {
        "cal_02": {
            "title": "Latin",
            "description": "Warm",
            "genre_hint": "Latin",
            "folder": "Upbeat latinafrobeats",
            "tags": ["latin"],
            "features": {"danceability": 0.9, "energy": 0.8},
        }
    }
    rotator = ClipAssetRotator(features, clips_dir)

    urls = [
        rotator.response_for("cal_02", session_key="session-a", play_index=i)["audio_url"]
        for i in range(3)
    ]

    assert len(set(urls)) == 3
    assert urls[0] != urls[1]


def test_clip_round_selection_prefers_category_coverage_before_repeating():
    from clip_rotation import select_round_clip_ids

    features = {
        "latin_a": {"folder": "Latin", "tags": ["latin"], "features": {"danceability": 0.9, "energy": 0.8}},
        "latin_b": {"folder": "Latin", "tags": ["latin"], "features": {"danceability": 0.85, "energy": 0.75}},
        "folk_a": {"folder": "Folk", "tags": ["folk"], "features": {"danceability": 0.2, "energy": 0.3}},
        "edm_a": {"folder": "EDM", "tags": ["edm"], "features": {"danceability": 0.7, "energy": 0.95}},
        "rap_a": {"folder": "Rap", "tags": ["rap"], "features": {"danceability": 0.8, "energy": 0.7}},
    }

    selected = select_round_clip_ids(features, count=4, session_key="coverage")
    selected_folders = [features[clip_id]["folder"] for clip_id in selected]

    assert len(selected) == 4
    assert len(set(selected_folders)) == 4


def test_adaptive_question_memory_rejects_repeated_semantic_template():
    from adaptive_questions import AdaptiveQuestionService

    class RepeatingProvider:
        def next_question(self, context):
            return {
                "continue": True,
                "question": "What emotion does your go-to music usually carry?",
                "hint": "Joy, sadness, hype, peace.",
                "dimension_probed": "emotional_context",
                "reasoning": "remote-repeat",
            }

    service = AdaptiveQuestionService(provider=RepeatingProvider())
    result = service.next_question(
        previous_answers=["Mostly nostalgic songs at night."],
        clip_ratings=[],
        covered_dimensions=["emotional_context"],
        asked_questions=["What emotion does your go-to music usually carry?"],
    )

    assert result["continue"] is True
    assert result["dimension_probed"] != "emotional_context"
    assert result["question"] != "What emotion does your go-to music usually carry?"
    assert result["provider"] == "local_fallback"


def test_openrouter_provider_sanitizes_response_and_retries():
    from adaptive_questions import OpenRouterQuestionProvider

    calls = []

    def requester(url, **kwargs):
        calls.append((url, kwargs))

        class Response:
            def __init__(self, payload):
                self._payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self._payload

        if len(calls) == 1:
            return Response({"choices": [{"message": {"content": "not json"}}]})
        return Response({
            "choices": [{
                "message": {
                    "content": """
                    ```json
                    {"continue": true, "question": "When does music feel most useful to you?", "hint": "A place or moment.", "dimension_probed": "listening_context"}
                    ```
                    """
                }
            }],
            "model": "openrouter/free",
        })

    provider = OpenRouterQuestionProvider(
        api_key="test-key",
        model="openrouter/free",
        requester=requester,
        timeout_seconds=1.5,
        max_retries=2,
    )

    result = provider.next_question({
        "question_number": 2,
        "previous_answers": ["I like warm dance music."],
        "clip_ratings": [],
        "covered_dimensions": ["movement_danceability"],
        "asked_questions": ["Does your music make you move, or hold you still?"],
    })

    assert result["question"] == "When does music feel most useful to you?"
    assert result["dimension_probed"] == "listening_context"
    assert len(calls) == 2
    assert calls[0][0] == "https://openrouter.ai/api/v1/chat/completions"
    assert calls[0][1]["timeout"] == 1.5
    assert calls[0][1]["json"]["model"] == "openrouter/free"
