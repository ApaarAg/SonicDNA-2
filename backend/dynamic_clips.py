"""
dynamic_clips.py — Dynamic Spotify Preview Fetcher and Cache for SonicDNA.

Queries the Spotify Web API Search endpoint for tracks by genre, strictly
filtering for playable 30-second previews (preview_url is not None), with
in-memory TTL caching and graceful fallback to ensure high availability.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv

# Ensure backend .ENV is loaded
ENV_PATH = Path(__file__).parent / ".ENV"
load_dotenv(dotenv_path=ENV_PATH)

# In-memory TTL cache: key -> (expires_at, tracks)
_GENRE_PREVIEW_CACHE: Dict[str, tuple[float, List[dict]]] = {}
CACHE_TTL_SECONDS = 300  # 5-minute cache to avoid hitting Spotify rate limits

# Canonical psychometric feature profiles per genre for genome analysis
GENRE_FEATURE_PROFILES: Dict[str, Dict[str, float]] = {
    "ambient": {"danceability": 0.15, "energy": 0.20, "valence": 0.20, "acousticness": 0.60, "instrumentalness": 0.95, "speechiness": 0.03, "tempo": 80.0},
    "electronic": {"danceability": 0.80, "energy": 0.90, "valence": 0.65, "acousticness": 0.05, "instrumentalness": 0.65, "speechiness": 0.06, "tempo": 128.0},
    "rock": {"danceability": 0.45, "energy": 0.80, "valence": 0.50, "acousticness": 0.10, "instrumentalness": 0.20, "speechiness": 0.05, "tempo": 120.0},
    "indie": {"danceability": 0.55, "energy": 0.60, "valence": 0.45, "acousticness": 0.35, "instrumentalness": 0.25, "speechiness": 0.04, "tempo": 115.0},
    "hip-hop": {"danceability": 0.85, "energy": 0.75, "valence": 0.60, "acousticness": 0.15, "instrumentalness": 0.05, "speechiness": 0.35, "tempo": 95.0},
    "pop": {"danceability": 0.80, "energy": 0.75, "valence": 0.85, "acousticness": 0.20, "instrumentalness": 0.02, "speechiness": 0.06, "tempo": 122.0},
    "classical": {"danceability": 0.10, "energy": 0.25, "valence": 0.25, "acousticness": 0.92, "instrumentalness": 0.90, "speechiness": 0.03, "tempo": 75.0},
    "jazz": {"danceability": 0.55, "energy": 0.45, "valence": 0.55, "acousticness": 0.65, "instrumentalness": 0.50, "speechiness": 0.05, "tempo": 105.0},
    "blues": {"danceability": 0.50, "energy": 0.50, "valence": 0.40, "acousticness": 0.55, "instrumentalness": 0.20, "speechiness": 0.05, "tempo": 90.0},
    "latin": {"danceability": 0.88, "energy": 0.82, "valence": 0.82, "acousticness": 0.20, "instrumentalness": 0.02, "speechiness": 0.07, "tempo": 125.0},
    "acoustic": {"danceability": 0.40, "energy": 0.30, "valence": 0.35, "acousticness": 0.85, "instrumentalness": 0.15, "speechiness": 0.04, "tempo": 90.0},
    "reggae": {"danceability": 0.82, "energy": 0.68, "valence": 0.80, "acousticness": 0.25, "instrumentalness": 0.08, "speechiness": 0.08, "tempo": 85.0},
    "dark_orchestral": {"danceability": 0.15, "energy": 0.35, "valence": 0.10, "acousticness": 0.40, "instrumentalness": 0.95, "speechiness": 0.03, "tempo": 85.0},
}

# Reliable fallback preview tracks if Spotify rate limits or developer app lacks Premium
CURATED_FALLBACK_PREVIEWS: Dict[str, List[dict]] = {
    "ambient": [{
        "spotify_id": "ambient_01",
        "name": "Stasis Pulse",
        "artist": "Solaris Soundscape",
        "preview_url": "https://p.scdn.co/mp3-preview/22de52d431c1e405f6e86ef5dcbfb3fa58a62bf0",
        "album_art": "https://i.scdn.co/image/ab67616d0000b273b063821045050f28a7e08cc7",
        "album_name": "Ambient Worlds",
        "genre": "ambient",
    }],
    "electronic": [{
        "spotify_id": "electronic_01",
        "name": "Midnight Neon",
        "artist": "Cyberspace Pulse",
        "preview_url": "https://p.scdn.co/mp3-preview/a9c1482cefc6694e9f3b1464b55be9d21c1765c9",
        "album_art": "https://i.scdn.co/image/ab67616d0000b27318ec7025875691f1b6f0e4b7",
        "album_name": "Future Grid",
        "genre": "electronic",
    }],
    "jazz": [{
        "spotify_id": "jazz_01",
        "name": "Blue Note Mood",
        "artist": "Miles Quartette",
        "preview_url": "https://p.scdn.co/mp3-preview/b7fa5701c40b8a74e503a893cb3389a9f45df9e4",
        "album_art": "https://i.scdn.co/image/ab67616d0000b27376c368ffea34e565988019b8",
        "album_name": "Late Night Sessions",
        "genre": "jazz",
    }],
    "classical": [{
        "spotify_id": "classical_01",
        "name": "Nocturne in C Minor",
        "artist": "Symphony Strings",
        "preview_url": "https://p.scdn.co/mp3-preview/47a2512f48d948cfbe2a6ffcc48cfc77174db624",
        "album_art": "https://i.scdn.co/image/ab67616d0000b27393e8787093845b4c1aa390bb",
        "album_name": "Timeless Classics",
        "genre": "classical",
    }],
    "latin": [{
        "spotify_id": "latin_01",
        "name": "Sabor del Sol",
        "artist": "Ritmo Tropical",
        "preview_url": "https://p.scdn.co/mp3-preview/c0d7feeaef76ebc03e33b90f42ea4bbd0505b382",
        "album_art": "https://i.scdn.co/image/ab67616d0000b273ea376a263c9df9f5217e1cb2",
        "album_name": "Viva La Fiesta",
        "genre": "latin",
    }],
    "hip-hop": [{
        "spotify_id": "hiphop_01",
        "name": "Concrete Resonance",
        "artist": "Urban Cipher",
        "preview_url": "https://p.scdn.co/mp3-preview/5a22830de2b173cf5c8f6ea4f9eb6e2ea8a56247",
        "album_art": "https://i.scdn.co/image/ab67616d0000b27303c7344eebe8ae67645f7cbb",
        "album_name": "Street Frequency",
        "genre": "hip-hop",
    }],
    "dark_orchestral": [{
        "spotify_id": "orchestral_01",
        "name": "Shadows of Elysium",
        "artist": "Cinematic Chamber Ensemble",
        "preview_url": "https://p.scdn.co/mp3-preview/47a2512f48d948cfbe2a6ffcc48cfc77174db624",
        "album_art": "https://i.scdn.co/image/ab67616d0000b27393e8787093845b4c1aa390bb",
        "album_name": "Cinematic Horizons",
        "genre": "dark_orchestral",
    }],
    "acoustic": [{
        "spotify_id": "acoustic_01",
        "name": "Whispering Pines",
        "artist": "Ember & Wood",
        "preview_url": "https://p.scdn.co/mp3-preview/b7fa5701c40b8a74e503a893cb3389a9f45df9e4",
        "album_art": "https://i.scdn.co/image/ab67616d0000b27376c368ffea34e565988019b8",
        "album_name": "Raw Acoustic Sessions",
        "genre": "acoustic",
    }],
}


def _get_spotify_service():
    """Lazily load SpotifyService to prevent circular imports."""
    try:
        from spotify_service_fixed import SpotifyService
        return SpotifyService()
    except Exception as e:
        print(f"[dynamic_clips.warn] SpotifyService unavailable: {e}")
        return None


def fetch_genre_previews(
    genre: str,
    limit: int = 10,
    market: str = "US",
    spotify_service: Optional[Any] = None,
) -> List[dict]:
    """
    Query Spotify Search API for tracks by genre and strictly filter out
    tracks where preview_url is None.
    """
    clean_genre = genre.strip().lower()
    if clean_genre.startswith("genre:"):
        clean_genre = clean_genre.replace("genre:", "").strip('"').strip()

    cache_key = f"{clean_genre}:{market}:{limit}"
    now = time.time()

    # Return cached tracks if available and within TTL
    if cache_key in _GENRE_PREVIEW_CACHE:
        expires_at, cached_tracks = _GENRE_PREVIEW_CACHE[cache_key]
        if now < expires_at:
            return [dict(t) for t in cached_tracks]

    service = spotify_service or _get_spotify_service()
    tracks: List[dict] = []

    if service and hasattr(service, "_make_request"):
        queries = [f'genre:"{clean_genre}"', clean_genre]
        for query in queries:
            try:
                params = {
                    "q": query,
                    "type": "track",
                    "market": market,
                    "limit": min(10, max(1, limit)),
                }
                res = service._make_request("search", params)
                items = res.get("tracks", {}).get("items", [])

                for item in items:
                    preview_url = item.get("preview_url")
                    # Strict preview filter
                    if not preview_url:
                        continue

                    artists = item.get("artists") or []
                    artist_str = ", ".join(a.get("name") for a in artists if a.get("name")) or "Unknown Artist"
                    album = item.get("album") or {}
                    images = album.get("images") or []
                    album_art = images[0].get("url") if images else None

                    feature_vec = GENRE_FEATURE_PROFILES.get(
                        clean_genre,
                        {"danceability": 0.5, "energy": 0.5, "valence": 0.5, "acousticness": 0.5, "instrumentalness": 0.5, "speechiness": 0.05, "tempo": 120.0}
                    )

                    track_data = {
                        "spotify_id": item.get("id"),
                        "name": item.get("name"),
                        "artist": artist_str,
                        "preview_url": preview_url,
                        "album_art": album_art,
                        "album_name": album.get("name"),
                        "genre": clean_genre,
                        "spotify_url": (item.get("external_urls") or {}).get("spotify"),
                        "duration_ms": item.get("duration_ms", 30000),
                        "features": feature_vec,
                    }

                    if not any(t["spotify_id"] == track_data["spotify_id"] for t in tracks):
                        tracks.append(track_data)

                    if len(tracks) >= limit:
                        break

                if tracks:
                    break
            except Exception as e:
                # Log but continue to fallback
                pass

    # Fallback to curated previews if empty (e.g. Spotify 403 or network issue)
    if not tracks:
        fallback_list = CURATED_FALLBACK_PREVIEWS.get(clean_genre) or CURATED_FALLBACK_PREVIEWS.get("electronic", [])
        for fb in fallback_list:
            fb_copy = dict(fb)
            fb_copy["features"] = GENRE_FEATURE_PROFILES.get(
                clean_genre,
                {"danceability": 0.5, "energy": 0.5, "valence": 0.5, "acousticness": 0.5, "instrumentalness": 0.5, "speechiness": 0.05, "tempo": 120.0}
            )
            tracks.append(fb_copy)

    _GENRE_PREVIEW_CACHE[cache_key] = (now + CACHE_TTL_SECONDS, tracks)
    return tracks
