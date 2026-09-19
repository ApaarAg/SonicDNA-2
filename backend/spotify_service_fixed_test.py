import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from spotify_service_fixed import (
    SpotifyService,
    _redact_spotify_log_text,
    genre_families_for_genres,
    region_family_for_region,
)


def _service():
    service = object.__new__(SpotifyService)
    service.search_cache = {}
    service.regional_cache = {}
    service.search_cooldown_until = 0.0
    service.embedding_ranker = None
    return service


def _spotify_track(track_id, name, artist, genres=None, popularity=60):
    return {
        "id": track_id,
        "name": name,
        "artists": [{"name": artist, "genres": genres or []}],
        "album": {"name": "Album", "images": []},
        "duration_ms": 210000,
        "popularity": popularity,
        "uri": f"spotify:track:{track_id}",
        "external_urls": {"spotify": f"https://open.spotify.com/track/{track_id}"},
    }


def test_artist_normalization_collapses_punctuation_and_joiner_noise():
    assert SpotifyService.normalize_artist_name("A. R. Rahman feat. Sid Sriram") == "ar rahman"
    assert SpotifyService.normalize_artist_name("A.R. Rahman & Sid Sriram") == "ar rahman"


def test_format_track_emits_consistent_normalized_metadata():
    service = _service()
    formatted = service._format_track(
        _spotify_track("t1", "Vaathi Coming - From Master", "Anirudh Ravichander", ["Kollywood", "Tamil Film"]),
        search_query="tamil dance",
        region_key="india_tamil",
    )

    assert formatted["primary_artist"] == "Anirudh Ravichander"
    assert formatted["primary_artist_normalized"] == "anirudh ravichander"
    assert formatted["artist_normalized"] == "anirudh ravichander"
    assert formatted["genres"] == ["tamil", "kollywood"]
    assert formatted["canonical_genres"] == ["tamil", "kollywood"]
    assert formatted["genre_families"] == ["south-asian-film-pop", "south-asian-pop"]
    assert formatted["region_family"] == "south_asia"
    assert formatted["track_fingerprint"] == "vaathi coming|anirudh ravichander"


def test_genre_family_normalization_groups_aliases_without_flattening_identity():
    assert SpotifyService.canonicalize_genres(["Afro Beats", "Afropop"]) == ["afrobeats", "afropop"]
    assert genre_families_for_genres(["Afro Beats", "Afropop"]) == ["afro-pop"]
    assert genre_families_for_genres(["Tamil Film", "Kollywood", "Punjabi Pop"]) == [
        "south-asian-film-pop",
        "south-asian-pop",
    ]


def test_region_family_groups_crossover_markets_but_keeps_exact_region():
    assert region_family_for_region("india_tamil") == "south_asia"
    assert region_family_for_region("india_punjabi") == "south_asia"
    assert region_family_for_region("brazil") == "latin_america"


def test_search_regional_tracks_suppresses_duplicate_song_versions(monkeypatch):
    service = _service()
    service._search_tracks_paged = lambda query, market, limit: [
        _spotify_track("a", "Vaathi Coming", "Anirudh Ravichander", ["tamil"], 80),
        _spotify_track("b", "Vaathi Coming - From Master", "Anirudh Ravichander", ["tamil"], 78),
        _spotify_track("c", "Kaavaalaa", "Shilpa Rao", ["tamil"], 76),
    ]
    service._regional_cache_get = lambda key: None
    service._regional_cache_set = lambda key, value: None

    tracks = service.search_regional_tracks(cluster_id=5, region_key="india_tamil", limit=10)

    assert [track["name"] for track in tracks].count("Vaathi Coming") == 1
    assert len({track["track_fingerprint"] for track in tracks}) == len(tracks)


def test_search_regional_tracks_keeps_searching_sparse_batches_until_limit(monkeypatch):
    service = _service()
    calls = []

    def sparse_search(query, market, limit):
        calls.append((query, market))
        base = len(calls) * 10
        return [
            _spotify_track(f"sparse-{base + idx}", f"Sparse Track {base + idx}", f"Artist {base + idx}", ["pop"], 70)
            for idx in range(2)
        ]

    service._search_tracks_paged = sparse_search
    service._regional_cache_get = lambda key: None
    service._regional_cache_set = lambda key, value: None

    tracks = service.search_regional_tracks(cluster_id=3, region_key="global_english", limit=12)

    assert len(tracks) == 12
    assert len(calls) > 4


def test_query_plan_uses_configured_fallback_markets_for_sparse_regions():
    service = _service()
    plan = service._build_query_plan(
        [("one", 1.0), ("two", 0.9), ("three", 0.8)],
        ["IN", "US"],
    )

    assert ("one", 1.0, "IN") in plan
    assert any(market == "US" for _, _, market in plan)
    assert len(plan) >= 4


def test_candidate_pool_diagnostics_flags_weak_low_diversity_pool():
    service = _service()
    tracks = [
        {"name": f"Track {i}", "artist": "Same Artist", "region_confidence": 0.3, "track_fingerprint": f"t{i}"}
        for i in range(5)
    ]

    diagnostics = service._candidate_pool_diagnostics(tracks, requested_limit=20)

    assert diagnostics["weak"] is True
    assert "low_count" in diagnostics["reasons"]
    assert "low_artist_diversity" in diagnostics["reasons"]


def test_spotify_error_log_redaction_masks_tokens():
    redacted = _redact_spotify_log_text(
        '{"access_token":"access-secret","refresh_token":"refresh-secret","client_secret":"client-secret"} '
        "Authorization: Bearer bearer-secret"
    )

    assert "access-secret" not in redacted
    assert "refresh-secret" not in redacted
    assert "client-secret" not in redacted
    assert "bearer-secret" not in redacted
