import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from track_profile_builder import build_track_profile


SECTION_MARKERS = {"identity", "secondary", "context"}


def _semantic_terms(profile):
    return [token for token in profile.split() if token not in SECTION_MARKERS]


def _section(profile, marker, next_marker=None):
    tokens = profile.split()
    start = tokens.index(marker) + 1
    end = tokens.index(next_marker) if next_marker else len(tokens)
    return tokens[start:end]


def test_track_profile_emits_texture_specific_sonic_world_descriptors():
    profile = build_track_profile(
        {
            "name": "Neon Fog",
            "artist": "Glass Circuit",
            "genres": ["ambient techno", "synthwave"],
            "search_query": "nocturnal ambient electronic",
            "energy": 0.72,
            "valence": 0.36,
            "danceability": 0.78,
            "acousticness": 0.08,
            "instrumentalness": 0.86,
            "speechiness": 0.03,
            "tempo": 132,
            "popularity": 66,
        }
    )

    for term in {
        "synthetic-texture",
        "dense-atmosphere",
        "low-vocal-density",
        "cinematic-scale",
        "polished-production",
        "rhythmic-aggressive",
        "ambient-heavy",
    }:
        assert term in profile


def test_track_profile_distinguishes_organic_intimate_raw_texture():
    profile = build_track_profile(
        {
            "name": "Room Take",
            "artist": "Mira Lane",
            "genres": ["indie folk", "singer-songwriter"],
            "energy": 0.34,
            "valence": 0.48,
            "danceability": 0.31,
            "acousticness": 0.84,
            "instrumentalness": 0.02,
            "speechiness": 0.07,
            "liveness": 0.62,
            "tempo": 78,
            "popularity": 21,
        }
    )

    for term in {
        "organic-texture",
        "sparse-atmosphere",
        "vocal-forward",
        "intimate-scale",
        "raw-production",
        "gentle-rhythm",
        "ambient-light",
    }:
        assert term in profile


def test_track_profile_prunes_redundant_broad_descriptors():
    profile = build_track_profile(
        {
            "name": "Neon Fog",
            "artist": "Glass Circuit",
            "genres": ["ambient techno", "synthwave"],
            "search_query": "nocturnal ambient electronic",
            "energy": 0.72,
            "valence": 0.36,
            "danceability": 0.78,
            "acousticness": 0.08,
            "instrumentalness": 0.86,
            "speechiness": 0.03,
            "tempo": 132,
            "popularity": 66,
        }
    )
    tokens = profile.split()

    assert len(_semantic_terms(profile)) <= 28
    assert "synthetic-texture" in tokens
    assert "synthetic" not in tokens
    assert "dense-atmosphere" in tokens
    assert "atmospheric" not in tokens
    assert "cinematic-scale" in tokens
    assert "cinematic" not in tokens
    assert "polished-production" in tokens
    assert "polished" not in tokens
    assert "rhythmic-aggressive" in tokens
    assert "high-intensity" not in tokens


def test_track_profile_preserves_discriminative_genre_and_region_terms():
    profile = build_track_profile(
        {
            "name": "Festival Engine",
            "artist": "Local Pulse",
            "genres": ["tamil kuthu", "indian dance"],
            "region": "india_tamil",
            "search_query": "festival kuthu percussion",
            "energy": 0.82,
            "valence": 0.68,
            "danceability": 0.87,
            "acousticness": 0.24,
            "instrumentalness": 0.12,
            "speechiness": 0.08,
            "tempo": 148,
            "popularity": 42,
        }
    )
    tokens = profile.split()

    assert len(_semantic_terms(profile)) <= 30
    for term in {"tamil", "kuthu", "indian", "regional", "percussion"}:
        assert term in tokens
    assert profile == build_track_profile(
        {
            "name": "Festival Engine",
            "artist": "Local Pulse",
            "genres": ["tamil kuthu", "indian dance"],
            "region": "india_tamil",
            "search_query": "festival kuthu percussion",
            "energy": 0.82,
            "valence": 0.68,
            "danceability": 0.87,
            "acousticness": 0.24,
            "instrumentalness": 0.12,
            "speechiness": 0.08,
            "tempo": 148,
            "popularity": 42,
        }
    )


def test_track_profile_groups_identity_secondary_and_context_terms():
    profile = build_track_profile(
        {
            "name": "Festival Engine",
            "artist": "Local Pulse",
            "genres": ["tamil kuthu", "indian dance"],
            "region": "india_tamil",
            "search_query": "festival kuthu percussion",
            "energy": 0.82,
            "valence": 0.68,
            "danceability": 0.87,
            "acousticness": 0.24,
            "instrumentalness": 0.12,
            "speechiness": 0.08,
            "tempo": 148,
            "popularity": 42,
        }
    )
    tokens = profile.split()

    assert tokens[0] == "identity"
    assert tokens.index("identity") < tokens.index("secondary") < tokens.index("context")

    identity = _section(profile, "identity", "secondary")
    secondary = _section(profile, "secondary", "context")
    context = _section(profile, "context")

    for term in {"tamil", "kuthu", "indian", "regional"}:
        assert term in identity
    for term in {"synthetic-texture", "rhythmic-aggressive", "bright"}:
        assert term in secondary
    for term in {"festival", "percussion", "emerging"}:
        assert term in context


def test_track_profile_keeps_hierarchy_sparse_and_deterministic():
    track = {
        "name": "Neon Fog",
        "artist": "Glass Circuit",
        "genres": ["ambient techno", "synthwave"],
        "search_query": "nocturnal ambient electronic",
        "energy": 0.72,
        "valence": 0.36,
        "danceability": 0.78,
        "acousticness": 0.08,
        "instrumentalness": 0.86,
        "speechiness": 0.03,
        "tempo": 132,
        "popularity": 66,
    }

    profile = build_track_profile(track)
    identity = _section(profile, "identity", "secondary")
    secondary = _section(profile, "secondary", "context")
    context = _section(profile, "context")

    assert len(_semantic_terms(profile)) <= 28
    assert {"electronic", "synthwave", "techno"} <= set(identity)
    assert {"dense-atmosphere", "ambient-heavy", "dark"} <= set(secondary)
    assert {"accessible", "known"} <= set(context)
    assert profile == build_track_profile(track)
