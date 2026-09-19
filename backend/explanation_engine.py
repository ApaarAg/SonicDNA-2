"""
Lightweight recommendation explanation traces.

This module turns existing ranking metadata into concise, human-readable
explanations. It does not call an LLM, train a model, or influence ranking.
"""

from collections import Counter
from typing import List, Optional


def _clean(value) -> str:
    return str(value or "").strip()


def _primary_artist(track: dict) -> str:
    return _clean(str(track.get("artist", "")).split(",")[0]).lower()


def _genres(track: dict) -> List[str]:
    raw = track.get("artist_genres") or track.get("genres") or []
    if isinstance(raw, str):
        raw = [raw]
    return [_clean(genre).lower() for genre in raw if _clean(genre)]


def _track_key(track: dict) -> str:
    return _clean(track.get("id") or f"{track.get('name', '')}:{track.get('artist', '')}").lower()


def _round(value, default=None):
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return default


def _band(value: Optional[float], low: str, mid: str, high: str) -> str:
    if value is None:
        return mid
    if value >= 0.68:
        return high
    if value <= 0.42:
        return low
    return mid


def _taste_sets(taste_profile: Optional[dict]) -> tuple:
    if not taste_profile:
        return set(), set(), set()
    artists = set()
    for artist in (taste_profile.get("artists") or taste_profile.get("top_artists") or [])[:20]:
        if isinstance(artist, dict):
            artists.add(_clean(artist.get("name")).lower())
        else:
            artists.add(_clean(artist).lower())

    genres = {_clean(genre).lower() for genre in (taste_profile.get("genres") or [])[:24] if _clean(genre)}
    tracks = {
        _clean(track.get("name")).lower()
        for track in (taste_profile.get("top_tracks") or [])[:30]
        if isinstance(track, dict) and _clean(track.get("name"))
    }
    return artists, genres, tracks


def _spotify_alignment(track: dict, taste_profile: Optional[dict]) -> dict:
    artists, taste_genres, taste_tracks = _taste_sets(taste_profile)
    artist = _primary_artist(track)
    track_genres = set(_genres(track))
    name = _clean(track.get("name")).lower()

    matched = []
    if artist and artist in artists:
        matched.append("artist")
    if name and name in taste_tracks:
        matched.append("track")
    if track_genres and taste_genres and track_genres & taste_genres:
        matched.append("genre")

    if "track" in matched:
        level = "direct"
    elif "artist" in matched or "genre" in matched:
        level = "aligned"
    elif taste_profile:
        level = "adjacent"
    else:
        level = "unknown"

    return {
        "level": level,
        "matched_signals": matched,
    }


def _mood_continuity(track: dict, previous_track: Optional[dict], requested_mood: Optional[str]) -> dict:
    valence = _round(track.get("valence"))
    energy = _round(track.get("energy"))
    mood_score = _round((track.get("recommendation_trace") or {}).get("mood_score"))

    continuity = "balanced"
    if previous_track:
        prev_valence = _round(previous_track.get("valence"))
        prev_energy = _round(previous_track.get("energy"))
        if prev_valence is not None and valence is not None and prev_energy is not None and energy is not None:
            delta = abs(prev_valence - valence) + abs(prev_energy - energy)
            if delta <= 0.22:
                continuity = "smooth"
            elif delta >= 0.70:
                continuity = "contrast"

    if requested_mood and mood_score is not None:
        mood_label = _band(mood_score, "loose", "compatible", "strong")
    elif requested_mood:
        mood_label = "compatible"
    else:
        mood_label = "not requested"

    return {
        "requested_mood": requested_mood,
        "fit": mood_label,
        "flow_from_previous": continuity,
        "energy": energy,
        "valence": valence,
    }


def _artist_diversity(track: dict, playlist_tracks: List[dict]) -> dict:
    artist = _primary_artist(track)
    counts = Counter(_primary_artist(item) for item in playlist_tracks if _primary_artist(item))
    count = counts.get(artist, 0)
    if not artist:
        effect = "unknown"
    elif count <= 1:
        effect = "adds diversity"
    elif count == 2:
        effect = "light repeat"
    else:
        effect = "repeated artist"
    return {
        "artist": artist,
        "playlist_artist_count": count,
        "effect": effect,
    }


def _summary(track: dict, semantic_level: str, graph_level: str, spotify_level: str, mood_fit: str) -> str:
    name = _clean(track.get("name")) or "This track"
    if track.get("exploration"):
        return f"{name} is a controlled discovery pick: {semantic_level} semantic fit with {graph_level} graph reach."
    if spotify_level in {"direct", "aligned"}:
        return f"{name} matches your taste profile with {semantic_level} semantic fit and {mood_fit} mood fit."
    return f"{name} fits the playlist through {semantic_level} semantic similarity and {graph_level} neighborhood context."


def generate_recommendation_explanation(
    track: dict,
    *,
    position: Optional[int] = None,
    playlist_tracks: Optional[List[dict]] = None,
    previous_track: Optional[dict] = None,
    taste_profile: Optional[dict] = None,
    requested_mood: Optional[str] = None,
) -> dict:
    """Return a concise structured explanation for one recommendation."""
    playlist_tracks = playlist_tracks or []
    trace = track.get("recommendation_trace") or {}
    exploration_meta = track.get("exploration_meta") or {}

    semantic_score = _round(track.get("user_embedding_similarity") or trace.get("semantic_similarity"))
    if semantic_score is None:
        semantic_score = _round(exploration_meta.get("semantic_relatedness"))
    semantic_level = _band(semantic_score, "light", "moderate", "strong")

    graph_bonus = _round(trace.get("graph_flow_bonus") or track.get("graph_flow_bonus"), 0.0)
    graph_distance = exploration_meta.get("graph_distance")
    if track.get("exploration"):
        graph_level = "bridge" if graph_distance in {2, 3} else "peripheral"
    elif graph_bonus and graph_bonus > 0:
        graph_level = "nearby"
    else:
        graph_level = "neutral"

    spotify = _spotify_alignment(track, taste_profile)
    mood = _mood_continuity(track, previous_track, requested_mood)
    artist = _artist_diversity(track, playlist_tracks)

    reasons = []
    if semantic_score is not None:
        reasons.append(f"{semantic_level} semantic match ({semantic_score})")
    if graph_bonus and graph_bonus > 0:
        reasons.append(f"graph flow bonus {graph_bonus}")
    if track.get("exploration"):
        reasons.append("controlled exploration pick")
    if artist["effect"] == "adds diversity":
        reasons.append("adds artist diversity")
    elif artist["effect"] == "repeated artist":
        reasons.append("artist repetition was allowed by stronger fit")
    if spotify["level"] in {"direct", "aligned"}:
        reasons.append(f"Spotify {spotify['level']} taste alignment")
    if requested_mood:
        reasons.append(f"{mood['fit']} {requested_mood} mood fit")

    return {
        "track_id": _track_key(track),
        "position": position,
        "summary": _summary(track, semantic_level, graph_level, spotify["level"], mood["fit"]),
        "signals": {
            "semantic_similarity": semantic_score,
            "semantic_contribution": semantic_level,
            "graph_neighborhood": {
                "influence": graph_level,
                "flow_bonus": graph_bonus,
                "exploration_graph_distance": graph_distance,
            },
            "exploration": {
                "injected": bool(track.get("exploration")),
                "score": _round(track.get("exploration_score")),
                "bridge_score": _round(exploration_meta.get("bridge_score")),
                "local_density": _round(exploration_meta.get("local_density")),
            },
            "artist_diversity": artist,
            "spotify_taste_alignment": spotify,
            "mood_continuity": mood,
        },
        "reasons": reasons[:5],
    }


def generate_playlist_explanations(
    playlist_tracks: List[dict],
    *,
    taste_profile: Optional[dict] = None,
    requested_mood: Optional[str] = None,
) -> List[dict]:
    return [
        generate_recommendation_explanation(
            track,
            position=index + 1,
            playlist_tracks=playlist_tracks,
            previous_track=playlist_tracks[index - 1] if index > 0 else None,
            taste_profile=taste_profile,
            requested_mood=requested_mood,
        )
        for index, track in enumerate(playlist_tracks)
    ]
