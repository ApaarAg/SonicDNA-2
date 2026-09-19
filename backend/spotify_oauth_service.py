import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from urllib.parse import urlencode, urlparse

import requests


SPOTIFY_ACCOUNTS_URL = "https://accounts.spotify.com"
SPOTIFY_API_URL = "https://api.spotify.com/v1"
SPOTIFY_SCOPES = "user-top-read user-read-recently-played"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _clean_text(value, max_len: int = 500) -> str:
    if value is None:
        return ""
    return str(value).replace("\x00", "").strip()[:max_len]


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_mapping(value) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _safe_return_to(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.hostname in {"localhost", "127.0.0.1"}:
        return value
    return None


def _infer_music_features(text: str, popularity: float = 50.0) -> Dict[str, float]:
    text = (text or "").lower()
    pop = max(0.0, min(_safe_float(popularity, 50.0), 100.0)) / 100.0
    dance_terms = ["dance", "party", "club", "edm", "house", "pop", "funk", "disco", "bhangra", "reggaeton"]
    calm_terms = ["acoustic", "ambient", "chill", "lofi", "sleep", "soft", "piano", "classical", "study"]
    sad_terms = ["sad", "heartbreak", "alone", "lonely", "rain", "melancholy", "blues"]
    speech_terms = ["rap", "hip hop", "spoken", "trap"]
    hard_terms = ["rock", "metal", "punk", "drill", "bass", "drop"]

    dance = 0.16 if any(term in text for term in dance_terms) else 0.0
    calm = 0.14 if any(term in text for term in calm_terms) else 0.0
    sad = 0.13 if any(term in text for term in sad_terms) else 0.0
    speech = 0.13 if any(term in text for term in speech_terms) else 0.0
    hard = 0.10 if any(term in text for term in hard_terms) else 0.0

    seed = int(hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:8], 16) if text else 0
    jitter = ((seed % 100) / 1000.0) - 0.05

    def clamp(value: float) -> float:
        return round(max(0.0, min(1.0, value)), 3)

    return {
        "danceability": clamp(0.48 + pop * 0.18 + dance - calm * 0.35 + jitter),
        "energy": clamp(0.46 + pop * 0.18 + dance + hard - calm + jitter),
        "valence": clamp(0.48 + pop * 0.10 + dance * 0.35 - sad + jitter),
        "acousticness": clamp(0.33 + calm - dance * 0.35 - hard * 0.2),
        "instrumentalness": clamp(0.04 + (0.10 if any(term in text for term in ["instrumental", "score", "classical"]) else 0.0)),
        "speechiness": clamp(0.05 + speech),
        "tempo": round(90 + 80 * clamp(0.46 + dance + hard - calm * 0.8), 1),
    }


class SpotifyOAuthService:
    """Account-level Spotify OAuth and taste profiling.

    This is intentionally separate from SpotifyService, which remains the
    client-credentials search/ranking client used by the existing playlist flow.
    """

    def __init__(self, state_secret: str):
        self.client_id = os.getenv("SPOTIFY_CLIENT_ID")
        self.client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
        self.redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI")
        self.state_secret = state_secret

    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.redirect_uri)

    def make_state(self, session_token: str, return_to: Optional[str] = None) -> str:
        payload = {
            "session_token": session_token,
            "return_to": _safe_return_to(return_to),
            "nonce": secrets.token_urlsafe(12),
            "exp": int(time.time()) + 600,
        }
        encoded = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        sig = hmac.new(self.state_secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
        return f"{encoded}.{_b64(sig)}"

    def parse_state(self, state: str) -> Optional[dict]:
        try:
            encoded, sig = state.split(".", 1)
            expected = hmac.new(self.state_secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
            if not hmac.compare_digest(_b64(expected), sig):
                return None
            payload = json.loads(_unb64(encoded).decode("utf-8"))
            if int(payload.get("exp", 0)) < int(time.time()):
                return None
            return payload
        except Exception:
            return None

    def authorization_url(self, state: str) -> str:
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "scope": SPOTIFY_SCOPES,
            "state": state,
            "show_dialog": "false",
        }
        return f"{SPOTIFY_ACCOUNTS_URL}/authorize?{urlencode(params)}"

    def exchange_code(self, code: str) -> dict:
        response = requests.post(
            f"{SPOTIFY_ACCOUNTS_URL}/api/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            timeout=15,
        )
        if response.status_code != 200:
            raise RuntimeError(f"Spotify token exchange failed: {response.status_code}")
        return response.json()

    def refresh_access_token(self, refresh_token: str) -> dict:
        response = requests.post(
            f"{SPOTIFY_ACCOUNTS_URL}/api/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            timeout=15,
        )
        if response.status_code != 200:
            raise RuntimeError(f"Spotify token refresh failed: {response.status_code}")
        return response.json()

    def _get(self, access_token: str, endpoint: str, params: Optional[dict] = None) -> dict:
        response = requests.get(
            f"{SPOTIFY_API_URL}/{endpoint.lstrip('/')}",
            headers={"Authorization": f"Bearer {access_token}"},
            params=params or {},
            timeout=12,
        )
        if response.status_code != 200:
            raise RuntimeError(f"Spotify API error on {endpoint}: {response.status_code}")
        return response.json()

    def get_current_user(self, access_token: str) -> dict:
        user = self._get(access_token, "me")
        return {
            "id": _clean_text(user.get("id"), 255),
            "display_name": _clean_text(user.get("display_name"), 255),
        }

    def get_user_top_tracks(self, access_token: str, limit: int = 20, time_range: str = "medium_term") -> List[dict]:
        data = self._get(
            access_token,
            "me/top/tracks",
            {"limit": max(1, min(int(limit), 50)), "time_range": time_range},
        )
        return data.get("items") or []

    def get_user_top_artists(self, access_token: str, limit: int = 20, time_range: str = "medium_term") -> List[dict]:
        data = self._get(
            access_token,
            "me/top/artists",
            {"limit": max(1, min(int(limit), 50)), "time_range": time_range},
        )
        return data.get("items") or []

    def get_recent_tracks(self, access_token: str, limit: int = 20) -> List[dict]:
        data = self._get(access_token, "me/player/recently-played", {"limit": max(1, min(int(limit), 50))})
        return [item.get("track") for item in (data.get("items") or []) if item.get("track")]

    def get_artists(self, access_token: str, artist_ids: List[str]) -> List[dict]:
        clean_ids = []
        for artist_id in artist_ids:
            if artist_id and artist_id not in clean_ids:
                clean_ids.append(artist_id)
        artists = []
        for i in range(0, len(clean_ids), 50):
            data = self._get(access_token, "artists", {"ids": ",".join(clean_ids[i:i + 50])})
            artists.extend(data.get("artists") or [])
        return artists

    def sanitize_artist(self, artist: dict) -> dict:
        artist = _as_mapping(artist)
        raw_genres = _as_list(artist.get("genres"))
        return {
            "id": _clean_text(artist.get("id"), 100),
            "name": _clean_text(artist.get("name"), 255),
            "genres": [_clean_text(g, 100) for g in raw_genres[:8] if _clean_text(g, 100)],
            "popularity": _safe_int(artist.get("popularity"), 0),
        }

    def sanitize_track(self, track: dict, artist_genres: Optional[Dict[str, List[str]]] = None, source: str = "spotify_top") -> dict:
        track = _as_mapping(track)
        album = _as_mapping(track.get("album"))
        artists = [a for a in (track.get("artists") or []) if isinstance(a, dict)]
        genres = []
        for artist in artists:
            genres.extend(_as_list((artist_genres or {}).get(artist.get("id"), [])))
        genres = list(dict.fromkeys(_clean_text(g, 100) for g in genres if g))[:12]
        artist_names = ", ".join(_clean_text(a.get("name"), 255) for a in artists if a.get("name")) or "Unknown Artist"
        text = " ".join([track.get("name") or "", artist_names, " ".join(genres)])
        features = _infer_music_features(text, track.get("popularity") or 50)
        images = _as_list(album.get("images"))
        external_urls = _as_mapping(track.get("external_urls"))

        return {
            "id": _clean_text(track.get("id") or track.get("uri") or track.get("name"), 100),
            "name": _clean_text(track.get("name"), 500) or "Unknown Track",
            "artist": artist_names,
            "album": _clean_text(album.get("name"), 500),
            "genres": genres,
            "duration_ms": _safe_int(track.get("duration_ms"), 180000),
            "popularity": _safe_int(track.get("popularity"), 0),
            "uri": _clean_text(track.get("uri"), 255),
            "external_url": _clean_text(external_urls.get("spotify"), 500),
            "preview_url": _clean_text(track.get("preview_url"), 500),
            "album_art": _clean_text(images[0].get("url"), 500) if images and isinstance(images[0], dict) else None,
            "source": source,
            "artist_genres": genres,
            "feature_source": "spotify_metadata_heuristic",
            **features,
        }

    def build_music_profile(self, top_tracks: List[dict], top_artists: List[dict], recent_tracks: List[dict]) -> dict:
        safe_artists = [self.sanitize_artist(a) for a in top_artists]
        artist_genres = {a["id"]: a.get("genres", []) for a in safe_artists}
        tracks = [self.sanitize_track(t, artist_genres, "spotify_top") for t in top_tracks]
        tracks.extend(self.sanitize_track(t, artist_genres, "spotify_recent") for t in recent_tracks[:10])

        genre_counts: Dict[str, int] = {}
        for artist in safe_artists:
            for genre in artist.get("genres", []):
                genre_counts[genre] = genre_counts.get(genre, 0) + 2
        for track in tracks:
            for genre in track.get("genres", []):
                genre_counts[genre] = genre_counts.get(genre, 0) + 1
        genres = [g for g, _ in sorted(genre_counts.items(), key=lambda item: item[1], reverse=True)[:12]]

        def avg(key: str, default: float = 0.5) -> float:
            vals = [float(t.get(key)) for t in tracks if t.get(key) is not None]
            return round(sum(vals) / len(vals), 3) if vals else default

        genre_text = " ".join(genres).lower()
        regional_affinity = "global"
        region_markers = {
            "india": ["bollywood", "tamil", "telugu", "punjabi", "desi", "indian", "hindi"],
            "latin_america": ["latin", "reggaeton", "urbano", "salsa", "bachata"],
            "korea": ["k-pop", "korean"],
            "japan": ["j-pop", "japanese"],
            "arab_world": ["arab", "khaleeji", "egyptian", "levant"],
            "africa": ["afrobeats", "afropop", "amapiano", "naija"],
        }
        for region, markers in region_markers.items():
            if any(marker in genre_text for marker in markers):
                regional_affinity = region
                break

        profile = {
            "genres": genres,
            "artists": [a["name"] for a in safe_artists if a.get("name")][:12],
            "top_artists": safe_artists[:12],
            "top_tracks": tracks[:20],
            "energy_preference": avg("energy"),
            "mood_preference": avg("valence"),
            "danceability_preference": avg("danceability"),
            "regional_affinity": regional_affinity,
            "music_diversity": round(min(1.0, (len(genres) / 12.0) * 0.65 + (len({a.get("name") for a in safe_artists}) / 20.0) * 0.35), 3),
            "embedding_query": " ".join(
                [*(genres[:8]), *[a["name"] for a in safe_artists[:8] if a.get("name")],
                 *[t["name"] for t in tracks[:8] if t.get("name")]]
            )[:1000],
            "fetched_at": datetime.utcnow().isoformat() + "Z",
        }
        return profile

    def token_expired(self, connection: dict, skew_seconds: int = 90) -> bool:
        try:
            expires_at = datetime.fromisoformat(str(connection.get("token_expires_at")))
            return datetime.utcnow() + timedelta(seconds=skew_seconds) >= expires_at
        except Exception:
            return True

    def save_track_for_user(self, access_token: str, track_id: str) -> bool:
        if "spotify.com/track/" in track_id:
            clean_id = track_id.split("spotify.com/track/")[-1].split("?")[0]
        elif ":" in track_id:
            clean_id = track_id.split(":")[-1]
        else:
            clean_id = track_id

        response = requests.put(
            f"{SPOTIFY_API_URL}/me/tracks",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"ids": [clean_id]},
            timeout=10,
        )
        if response.status_code not in (200, 201):
            raise RuntimeError(f"Spotify save track failed: {response.status_code} - {response.text}")
        return True
