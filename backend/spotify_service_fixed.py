
import base64
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List
import unicodedata
import requests

SEARCH_CACHE_TTL_SECONDS = 300
REGIONAL_CACHE_TTL_SECONDS = 120
MAX_DISCOVERY_SEARCH_CALLS = 12
SPOTIFY_SEARCH_COOLDOWN_SECONDS = 60
MIN_METADATA_SIGNAL = 0.05


def _redact_spotify_log_text(value) -> str:
    text = str(value)
    text = re.sub(
        r"(?i)(authorization\s*:\s*bearer\s+)[A-Za-z0-9._~+/=-]+",
        r"\1[redacted]",
        text,
    )
    text = re.sub(
        r"(?i)([\"']?\b(?:access_token|refresh_token|client_secret)\b[\"']?\s*[:=]\s*[\"']?)[^,\"'\s&}]+",
        r"\1[redacted]",
        text,
    )
    return text


REGIONS = {
    "japan": "Japan",
    "south_korea": "South Korea",
    "india_hindi": "India (Hindi)",
    "india_tamil": "India (Tamil)",
    "india_punjabi": "India (Punjabi)",
    "nigeria": "Nigeria",
    "brazil": "Brazil",
    "latin_america": "Latin America",
    "arab_world": "Arab World",
    "france": "France",
    "global_english": "Global (English)",
    "global_spanish": "Global (Spanish)",
    "global_arabic": "Global (Arabic)",
}

LOW_QUALITY_TERMS = [
    "live",
    "concert",
    "explanation",
    "devotional",
    "prayer",
    "classical",
    "interlude",
    "background score",
    "remix",
    "instrumental",
    "remaster",
    "non stop",
    "karaoke",
    "tribute",
    "cover version",
    "workout",
    "best music hits",
    "popular songs",
    "revival",
    "raga",
    "raag",
    "bhajan",
    "kirtan",
    "carnatic",
    "thiruchendur",
    "temple",
    "swami",
    "dhinakaran",
]

SIGNAL_STOPWORDS = {"the", "and", "for", "with", "hits", "songs"}
SIGNAL_SHORT_TOKEN_ALLOWLIST = {"dj", "edm", "uk"}
ARTIST_JOINER_PATTERN = re.compile(
    r"\s+(?:feat\.?|featuring|ft\.?|with|x|vs\.?|versus|and|&)\s+",
    re.IGNORECASE,
)
TITLE_VERSION_PATTERN = re.compile(
    r"\s*(?:-|–|—|\()\s*(?:from|feat\.?|featuring|ft\.?|with|remaster(?:ed)?|"
    r"radio edit|single version|sped up|slowed|lofi|acoustic|live|remix|version)\b.*$",
    re.IGNORECASE,
)
GENRE_ALIASES = {
    "tamil pop": "tamil",
    "tamil kuthu": "kuthu",
    "tamil film": "tamil",
    "tamil movie": "tamil",
    "kollywood": "kollywood",
    "punjabi pop": "punjabi",
    "punjabi hip hop": "punjabi-hip-hop",
    "indian pop": "indian-pop",
    "indian dance": "indian-dance",
    "bhangra": "bhangra",
    "hindi film": "hindi",
    "hindi pop": "hindi",
    "bollywood": "bollywood",
    "k pop": "k-pop",
    "kpop": "k-pop",
    "korean pop": "k-pop",
    "j pop": "j-pop",
    "jpop": "j-pop",
    "japanese pop": "j-pop",
    "afro beats": "afrobeats",
    "afrobeat": "afrobeats",
    "afrobeats": "afrobeats",
    "afropop": "afropop",
    "nigerian pop": "afropop",
    "baile funk": "funk brasileiro",
    "funk carioca": "funk brasileiro",
    "brazilian funk": "funk brasileiro",
    "brazilian pop": "brazilian-pop",
    "latin pop": "latin",
    "latin dance": "latin",
    "reggaeton": "reggaeton",
    "arab pop": "arabic",
    "arabic pop": "arabic",
    "middle eastern pop": "arabic",
    "french pop": "french-pop",
    "chanson pop": "french-pop",
}
GENRE_FAMILY_MAP = {
    "tamil": "south-asian-pop",
    "kuthu": "south-asian-pop",
    "kollywood": "south-asian-film-pop",
    "punjabi": "south-asian-pop",
    "punjabi-hip-hop": "south-asian-hip-hop",
    "bhangra": "south-asian-pop",
    "hindi": "south-asian-pop",
    "bollywood": "south-asian-film-pop",
    "indian-pop": "south-asian-pop",
    "indian-dance": "south-asian-pop",
    "k-pop": "east-asian-pop",
    "j-pop": "east-asian-pop",
    "afrobeats": "afro-pop",
    "afropop": "afro-pop",
    "funk brasileiro": "latin-dance",
    "brazilian-pop": "latin-pop",
    "latin": "latin-pop",
    "reggaeton": "latin-urban",
    "arabic": "arabic-pop",
    "french-pop": "western-pop",
    "pop": "western-pop",
    "dance pop": "western-pop",
    "indie pop": "western-pop",
    "hip hop": "hip-hop",
    "rap": "hip-hop",
    "electronic": "electronic",
    "edm": "electronic",
    "techno": "electronic",
    "synthwave": "electronic",
    "ambient": "electronic",
    "singer-songwriter": "folk-acoustic",
    "folk": "folk-acoustic",
    "indie folk": "folk-acoustic",
}
GENRE_PRIORITY = {
    "tamil": 0,
    "punjabi": 0,
    "hindi": 0,
    "k-pop": 0,
    "j-pop": 0,
    "afrobeats": 0,
    "latin": 0,
    "arabic": 0,
    "kollywood": 1,
    "bollywood": 1,
    "bhangra": 1,
    "kuthu": 1,
    "reggaeton": 1,
    "funk brasileiro": 1,
}
GENRE_FAMILY_PRIORITY = {
    "south-asian-film-pop": 0,
    "south-asian-pop": 1,
    "south-asian-hip-hop": 2,
    "east-asian-pop": 3,
    "afro-pop": 4,
    "latin-pop": 5,
    "latin-urban": 6,
    "latin-dance": 7,
    "arabic-pop": 8,
    "western-pop": 9,
    "hip-hop": 10,
    "electronic": 11,
    "folk-acoustic": 12,
}
REGION_FAMILY_MAP = {
    "india_tamil": "south_asia",
    "india_punjabi": "south_asia",
    "india_hindi": "south_asia",
    "south_korea": "east_asia",
    "japan": "east_asia",
    "nigeria": "west_africa",
    "brazil": "latin_america",
    "latin_america": "latin_america",
    "arab_world": "arabic_world",
    "global_arabic": "arabic_world",
    "france": "western_europe",
    "global_english": "global",
    "global_spanish": "latin_america",
}


def _bounded_signal(value: float, floor: float = MIN_METADATA_SIGNAL) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = floor
    return max(floor, min(1.0, numeric))


def _normalize_signal(value: float, default: float = 0.5) -> float:
    if value is None:
        return default
    return _bounded_signal(value)


def _centroid_signal(value: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = 0.0
    clamped = max(-3.0, min(3.0, numeric))
    return _bounded_signal((clamped + 3.0) / 6.0)


def _tokenize_signal_text(text: str) -> set:
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in str(text))
    return {
        token
        for token in cleaned.split()
        if token not in SIGNAL_STOPWORDS and (len(token) >= 3 or token in SIGNAL_SHORT_TOKEN_ALLOWLIST)
    }


def _normalize_signal_text(text: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in str(text))
    tokens = [
        token
        for token in cleaned.split()
        if token not in SIGNAL_STOPWORDS and (len(token) >= 3 or token in SIGNAL_SHORT_TOKEN_ALLOWLIST)
    ]
    return " ".join(tokens)


def _ascii_lower(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return ascii_text.lower()


def _compact_initial_tokens(tokens: List[str]) -> List[str]:
    compacted = []
    initials = []
    for token in tokens:
        if len(token) == 1:
            initials.append(token)
            continue
        if initials:
            compacted.append("".join(initials))
            initials = []
        compacted.append(token)
    if initials:
        compacted.append("".join(initials))
    return compacted


def normalize_artist_name(name: str) -> str:
    primary = ARTIST_JOINER_PATTERN.split(str(name or ""), maxsplit=1)[0]
    cleaned = re.sub(r"[^a-z0-9]+", " ", _ascii_lower(primary)).strip()
    tokens = _compact_initial_tokens(cleaned.split())
    return " ".join(tokens)


def normalize_track_title(title: str) -> str:
    cleaned = TITLE_VERSION_PATTERN.sub("", str(title or ""))
    cleaned = re.sub(r"\s*\[[^\]]+\]\s*", " ", cleaned)
    cleaned = re.sub(r"\s*\([^)]*\)\s*", " ", cleaned)
    cleaned = re.sub(r"[^a-z0-9]+", " ", _ascii_lower(cleaned)).strip()
    return " ".join(cleaned.split())


def canonicalize_genres(genres) -> List[str]:
    canonical = []
    seen = set()
    for genre in genres or []:
        normalized = re.sub(r"[^a-z0-9]+", " ", _ascii_lower(genre)).strip()
        if not normalized:
            continue
        value = GENRE_ALIASES.get(normalized, normalized.replace(" ", "-") if normalized in {"k pop", "j pop"} else normalized)
        if value not in seen:
            seen.add(value)
            canonical.append(value)
    return sorted(canonical, key=lambda value: (GENRE_PRIORITY.get(value, 5), value))


def genre_families_for_genres(genres) -> List[str]:
    families = []
    seen = set()
    for genre in canonicalize_genres(genres):
        family = GENRE_FAMILY_MAP.get(genre)
        if not family:
            normalized = genre.replace("-", " ")
            family = GENRE_FAMILY_MAP.get(normalized)
        if family and family not in seen:
            seen.add(family)
            families.append(family)
    return sorted(families, key=lambda value: (GENRE_FAMILY_PRIORITY.get(value, 99), value))


def region_family_for_region(region_key: str) -> str:
    normalized = str(region_key or "").strip().lower()
    return REGION_FAMILY_MAP.get(normalized, normalized or "")


def track_fingerprint(name: str, artist: str) -> str:
    title_key = normalize_track_title(name) or _normalize_signal_text(name)
    artist_key = normalize_artist_name(artist)
    return f"{title_key}|{artist_key}".strip("|")


def _weighted_keyword_signal(text: str, positive_terms, negative_terms=(), base: float = 0.5) -> float:
    lowered = f" {_normalize_signal_text(text)} "
    score = base
    for term, weight in positive_terms:
        if _contains_signal_term(lowered, term):
            score += weight
    for term, weight in negative_terms:
        if _contains_signal_term(lowered, term):
            score -= weight
    return _normalize_signal(score)


def _contains_signal_term(normalized_text: str, term: str) -> bool:
    normalized_term = _normalize_signal_text(term)
    return bool(normalized_term) and f" {normalized_term} " in normalized_text


def rank_tracks_by_similarity(tracks: List[dict], user_vec: dict, limit: int, similarity_fn) -> List[dict]:
    """Pure ranking: higher user similarity wins, stable tie-breakers included."""
    if not tracks or limit <= 0:
        return []

    scored_tracks = []
    for track in tracks:
        score = similarity_fn(track.get("proxy_features", {}), user_vec)
        ranked_track = dict(track)
        ranked_track["quality_score"] = round(_bounded_signal(score), 6)
        scored_tracks.append(ranked_track)

    ranked = sorted(
        scored_tracks,
        key=lambda t: (
            t["quality_score"],
            t.get("query_match_strength", MIN_METADATA_SIGNAL),
            t.get("region_confidence", MIN_METADATA_SIGNAL),
            t.get("popularity_norm", MIN_METADATA_SIGNAL),
            f"{(t.get('name') or '').lower()}|{(t.get('artist') or '').lower()}",
        ),
        reverse=True,
    )
    deduped = []
    artist_counts = {}

    for track in ranked:
        artist = track.get("primary_artist_normalized") or normalize_artist_name((track.get("artist") or "").split(",")[0])
        if not artist and isinstance(track.get("artists"), list):
            first_artist = next(
                (item for item in track["artists"] if isinstance(item, dict) and item.get("name")),
                None,
            )
            if first_artist:
                artist = normalize_artist_name(first_artist["name"])
            elif track["artists"] and isinstance(track["artists"][0], str):
                artist = normalize_artist_name(track["artists"][0])
        if not artist:
            artist = str(track.get("id") or track.get("name") or "unknown").lower()
        if artist_counts.get(artist, 0) < 2:
            deduped.append(track)
            artist_counts[artist] = artist_counts.get(artist, 0) + 1
        if len(deduped) >= limit:
            break

    return deduped

REGION_SEARCH_STRATEGIES = {
    "india_tamil": {
        "markets": ["IN", "US"],
        "min_popularity": 10,
        "queries": [
            ("Monica Coolie Tamil", 1.08),
            ("Anirudh Tamil hits", 1.06),
            ("tamil trending songs", 1.03),
            ("tamil film hit", 1.00),
            ("kollywood party", 0.95),
            ("tamil dance", 0.92),
            ("tamil hits 2024", 0.90),
            ("tamil hits 2025", 0.90),
            ("tamil pop", 0.88),
            ("latest tamil songs", 0.82),
            ("tamil movie songs", 0.78),
        ],
    },
    "india_punjabi": {
        "markets": ["IN", "US"],
        "min_popularity": 15,
        "queries": [
            ("AP Dhillon punjabi", 1.08),
            ("Diljit Dosanjh punjabi", 1.06),
            ("Sidhu Moose Wala", 1.04),
            ("punjabi pop", 1.00),
            ("bhangra hit", 0.97),
            ("punjabi dance", 0.94),
            ("punjabi hits 2024", 0.90),
            ("punjabi hits 2025", 0.90),
            ("latest punjabi songs", 0.88),
            ("punjabi party", 0.84),
            ("punjabi hip hop", 0.78),
        ],
    },
    "india_hindi": {
        "markets": ["IN"],
        "min_popularity": 28,
        "queries": [
            ("bollywood hits", 1.00),
            ("hindi pop", 0.95),
            ("bollywood dance", 0.92),
            ("latest hindi songs", 0.86),
            ("hindi party songs", 0.82),
        ],
    },
    "global_english": {
        "markets": ["US"],
        "min_popularity": 10,
        "queries": [
            ("Sabrina Carpenter pop", 1.08),
            ("Dua Lipa dance pop", 1.06),
            ("Taylor Swift pop", 1.05),
            ("The Weeknd pop", 1.04),
            ("Olivia Rodrigo pop", 1.02),
            ("Billie Eilish pop", 1.00),
            ("genre:pop", 1.00),
            ("viral pop", 0.94),
            ("modern dance pop", 0.90),
            ("top hits", 0.86),
            ("indie pop hits", 0.78),
        ],
    },
    "south_korea": {
        "markets": ["KR"],
        "min_popularity": 25,
        "queries": [("k-pop hits", 1.00), ("korean pop", 0.92), ("kpop dance", 0.88)],
    },
    "japan": {
        "markets": ["JP"],
        "min_popularity": 22,
        "queries": [("j-pop hits", 1.00), ("japanese pop", 0.92), ("anime pop", 0.78)],
    },
    "nigeria": {
        "markets": ["NG"],
        "min_popularity": 22,
        "queries": [("afrobeats hits", 1.00), ("nigerian pop", 0.92), ("afropop dance", 0.88)],
    },
    "brazil": {
        "markets": ["BR"],
        "min_popularity": 22,
        "queries": [("brazilian pop", 1.00), ("funk brasileiro", 0.92), ("samba pop", 0.80)],
    },
    "latin_america": {
        "markets": ["MX", "CO", "AR"],
        "min_popularity": 30,
        "queries": [("latin pop hits", 1.00), ("reggaeton hits", 0.95), ("latin dance", 0.90)],
    },
    "arab_world": {
        "markets": ["AE", "SA", "EG"],
        "min_popularity": 20,
        "queries": [("arabic pop", 1.00), ("arab pop hits", 0.92), ("middle eastern pop", 0.80)],
    },
    "france": {
        "markets": ["FR"],
        "min_popularity": 25,
        "queries": [("french pop", 1.00), ("chanson pop", 0.86), ("french hits", 0.84)],
    },
}


class SpotifyService:
    """Spotify Web API integration for regional discovery."""

    normalize_artist_name = staticmethod(normalize_artist_name)
    normalize_track_title = staticmethod(normalize_track_title)
    canonicalize_genres = staticmethod(canonicalize_genres)
    genre_families_for_genres = staticmethod(genre_families_for_genres)
    region_family_for_region = staticmethod(region_family_for_region)
    track_fingerprint = staticmethod(track_fingerprint)

    def __init__(self, client_id: str = None, client_secret: str = None):
        self.client_id = client_id or os.getenv("SPOTIFY_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("SPOTIFY_CLIENT_SECRET")

        if not self.client_id or not self.client_secret:
            raise Exception(
                "Spotify credentials required. Set SPOTIFY_CLIENT_ID and "
                "SPOTIFY_CLIENT_SECRET environment variables."
            )

        self.access_token = None
        self.token_expires_at = 0
        self.base_url = "https://api.spotify.com/v1"
        self.search_cache = {}
        self.regional_cache = {}
        self.search_cooldown_until = 0.0
        self._embedding_ranker = None

        self._authenticate()

    @property
    def embedding_ranker(self):
        if self._embedding_ranker is None:
            try:
                from embedding_ranker import EmbeddingRanker
                self._embedding_ranker = EmbeddingRanker()
            except Exception as e:
                print(f"[spotify.embedding.init_error] error={e}")
        return self._embedding_ranker

    @embedding_ranker.setter
    def embedding_ranker(self, value):
        self._embedding_ranker = value


    def _authenticate(self):
        auth_str = f"{self.client_id}:{self.client_secret}"
        headers = {
            "Authorization": f"Basic {base64.b64encode(auth_str.encode()).decode()}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        response = requests.post(
            "https://accounts.spotify.com/api/token",
            headers=headers,
            data={"grant_type": "client_credentials"},
            timeout=15,
        )

        if response.status_code != 200:
            raise Exception(f"Spotify authentication failed: {_redact_spotify_log_text(response.text)}")

        result = response.json()
        self.access_token = result["access_token"]
        self.token_expires_at = time.time() + 3000
        print("[spotify.auth] authenticated=true")

    def _ensure_valid_token(self):
        if time.time() >= self.token_expires_at:
            print("[spotify.auth] refresh=true")
            self._authenticate()

    def _make_request(self, endpoint: str, params: dict = None) -> dict:
        self._ensure_valid_token()

        url = f"{self.base_url}/{endpoint}"
        if endpoint == "search" and time.time() < self.search_cooldown_until:
            remaining = int(max(1, self.search_cooldown_until - time.time()))
            raise Exception(f"Spotify search cooldown active ({remaining}s)")

        response = None
        max_attempts = 2 if endpoint == "search" else 3
        saw_rate_limit = False
        for attempt in range(max_attempts):
            response = requests.get(
            url,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            },
            params=params,
            timeout=8,
            )
            if response.status_code != 429:
                break
            saw_rate_limit = True
            retry_after = response.headers.get("Retry-After")
            delay = min(float(retry_after), 0.75) if retry_after else min(0.75, 0.25 * (2 ** attempt))
            print(
                f"[spotify.rate_limit] endpoint={endpoint} attempt={attempt + 1} "
                f"delay={delay:.2f}"
            )
            time.sleep(delay)

        if endpoint == "search" and saw_rate_limit and response is not None and response.status_code == 429:
            self.search_cooldown_until = time.time() + SPOTIFY_SEARCH_COOLDOWN_SECONDS
            print(
                f"[spotify.cooldown] active=true seconds={SPOTIFY_SEARCH_COOLDOWN_SECONDS}"
            )

        if response.status_code != 200:
            safe_body = _redact_spotify_log_text(response.text)
            print(
                f"[spotify.error] endpoint={endpoint} status={response.status_code} "
                f"body={safe_body}"
            )
            raise Exception(f"Spotify API error: {response.status_code} - {safe_body}")

        return response.json()

    def _cache_get(self, key):
        cached = self.search_cache.get(key)
        if not cached:
            return None
        expires_at, value = cached
        if time.time() >= expires_at:
            self.search_cache.pop(key, None)
            return None
        return value

    def _cache_set(self, key, value):
        self.search_cache[key] = (time.time() + SEARCH_CACHE_TTL_SECONDS, value)

    def _regional_cache_get(self, key):
        cached = self.regional_cache.get(key)
        if not cached:
            return None
        expires_at, value = cached
        if time.time() >= expires_at:
            self.regional_cache.pop(key, None)
            return None
        return [dict(track) for track in value]

    def _regional_cache_set(self, key, value):
        self.regional_cache[key] = (
            time.time() + REGIONAL_CACHE_TTL_SECONDS,
            [dict(track) for track in value],
        )

    def _search_tracks_page(self, query: str, market: str, limit: int, offset: int = 0) -> List[dict]:
        params = {
            "q": str(query).strip(),
            "type": "track",
            "market": market,
            "limit": max(1, min(10, int(limit))),
            "offset": max(0, int(offset)),
        }
        cache_key = ("search", params["q"].lower(), params["market"], params["limit"], params["offset"])
        cached = self._cache_get(cache_key)
        if cached is not None:
            print(f"[spotify.search.cache] hit=true market={market} query='{query}'")
            return cached

        result = self._make_request("search", params)
        tracks = result.get("tracks", {}).get("items", [])
        self._cache_set(cache_key, tracks)
        print(f"[spotify.search.cache] hit=false market={market} query='{query}'")
        return tracks

    def _search_tracks_paged(self, query: str, market: str, limit: int) -> List[dict]:
        # Keep each query to one Spotify request. Discovery controls breadth with
        # progressive query fallback instead of paginating near-duplicates.
        return self._search_tracks_page(query, market, min(10, int(limit)), 0)

    def search_regional_tracks(self, cluster_id: int, region_key: str, limit: int = 50) -> List[dict]:
        archetype_terms = {
            0: "chill",
            1: "energetic",
            2: "indie",
            3: "upbeat",
            4: "alternative",
            5: "smooth",
            6: "hip hop",
        }
        config = REGION_SEARCH_STRATEGIES.get(region_key, {
            "markets": ["US"],
            "min_popularity": 20,
            "queries": [(region_key.replace("_", " "), 1.0)],
        })

        requested_limit = max(1, min(50, int(limit)))
        cache_key = ("regional", region_key, int(cluster_id), int(requested_limit))
        cached_regional = self._regional_cache_get(cache_key)
        if cached_regional is not None:
            print(
                f"[spotify.discovery.cache] hit=true region={region_key} "
                f"count={len(cached_regional)}"
            )
            return cached_regional

        if time.time() < self.search_cooldown_until:
            remaining = int(max(1, self.search_cooldown_until - time.time()))
            print(
                f"[spotify.cooldown] active=true skip_search=true "
                f"remaining_seconds={remaining}"
            )
            return []

        raw_candidates = []
        seen_track_ids = set()
        weighted_queries = self._dedupe_queries(list(config["queries"]))
        query_plan = self._build_query_plan(
            weighted_queries,
            config["markets"],
            max_calls=max(MAX_DISCOVERY_SEARCH_CALLS, min(20, requested_limit)),
        )

        calls_made = 0
        with ThreadPoolExecutor(max_workers=min(4, len(query_plan) or 1)) as executor:
            future_map = {
                executor.submit(self._search_tracks_paged, query, market, 10): (query, query_weight, market)
                for query, query_weight, market in query_plan
            }
            for future in as_completed(future_map):
                query, query_weight, market = future_map[future]
                calls_made += 1
                try:
                    tracks = future.result()
                    print(
                        f"[spotify.discovery] region={region_key} market={market} "
                        f"query='{query}' found={len(tracks)}"
                    )
                    for track in tracks:
                        track_id = track.get("id")
                        if not track_id or track_id in seen_track_ids:
                            continue
                        seen_track_ids.add(track_id)
                        raw_candidates.append((track, query, query_weight))
                except Exception as e:
                    print(
                        f"[spotify.discovery.error] region={region_key} "
                        f"query='{query}' error={e}"
                    )

        filtered, low_popularity, zero_popularity = [], [], []
        no_preview_count = 0
        min_popularity = config.get("min_popularity", 20)
        formatted_by_fingerprint = {}

        for track, query, query_weight in raw_candidates:
            if self._is_low_quality_track(track) or self._is_wrong_region_track(track, region_key):
                continue

            formatted = self._format_track(
                track,
                source="discovery",
                search_query=query,
                search_weight=query_weight,
                region_key=region_key,
            )
            fingerprint = formatted.get("track_fingerprint") or formatted.get("id")
            incumbent = formatted_by_fingerprint.get(fingerprint)
            if incumbent and not self._prefer_candidate(formatted, incumbent):
                continue
            formatted_by_fingerprint[fingerprint] = formatted
            if not formatted.get("preview_url"):
                no_preview_count += 1

        for formatted in formatted_by_fingerprint.values():
            if formatted["popularity"] <= 0:
                zero_popularity.append(formatted)
            elif formatted["popularity"] < min_popularity:
                low_popularity.append(formatted)
            else:
                filtered.append(formatted)
        
        all_tracks = filtered + low_popularity + zero_popularity
        pool_diagnostics = self._candidate_pool_diagnostics(all_tracks, requested_limit)
        if pool_diagnostics["weak"]:
            print(
                f"[spotify.discovery.weak_pool] region={region_key} "
                f"reasons={','.join(pool_diagnostics['reasons'])} "
                f"count={pool_diagnostics['count']} "
                f"unique_artists={pool_diagnostics['unique_artists']} "
                f"unique_tracks={pool_diagnostics['unique_tracks']} "
                f"avg_region_confidence={pool_diagnostics['avg_region_confidence']}"
            )
        user_vec = self._user_vector_for_cluster(cluster_id)
        selected = rank_tracks_by_similarity(
            all_tracks,
            user_vec,
            requested_limit,
            self._compute_similarity,
        )
        if selected:
            print(
                f"[spotify.discovery.rank] top='{selected[0]['name']}' "
                f"score={selected[0]['quality_score']} user_cluster={cluster_id}"
            )
        if not selected:
            selected = zero_popularity[:requested_limit]

        embedding_ranked = []
        if self.embedding_ranker is not None:
            try:
                embedding_query = ""
                for track in all_tracks:
                    candidate = track.get("search_query")
                    if candidate:
                        embedding_query = candidate
                        break
                if not embedding_query:
                    embedding_query = " ".join([
                        region_key.replace("_", " "),
                        "music playlist"
                    ])
                embedding_ranked = self.embedding_ranker.rank(
                    all_tracks,
                    user_query=embedding_query,
                    limit=requested_limit
                )
            except Exception as e:
                print(f"[spotify.embedding.rank_error] error={e}")
                embedding_ranked = []

        final = []
        seen = set()

        max_len = max(len(embedding_ranked), len(selected))
        for i in range(max_len):
            for t in (
                embedding_ranked[i] if i < len(embedding_ranked) else None,
                selected[i] if i < len(selected) else None,
            ):
                if not t:
                    continue
                track_id = t.get("track_fingerprint") or t.get("id") or t.get("name")
                if track_id in seen:
                    continue
                final.append(t)
                seen.add(track_id)
                if len(final) >= requested_limit:
                    break
            if len(final) >= requested_limit:
                break

        if not final:
            final = selected

        print(
            f"[spotify.discovery.summary] region={region_key} raw={len(raw_candidates)} "
            f"query_count={calls_made} cache_size={len(self.search_cache)} "
            f"filtered={len(filtered)} low_popularity={len(low_popularity)} "
            f"zero_popularity={len(zero_popularity)} "
            f"no_preview={no_preview_count} "
            f"returned={len(final)}"
        )
        self._regional_cache_set(cache_key, final)
        print(
            f"[spotify.discovery.cache] hit=false region={region_key} "
            f"stored={len(final)} regional_cache_size={len(self.regional_cache)}"
        )
        return final

    def search_genre_previews(self, genre: str, limit: int = 20, market: str = "US") -> List[dict]:
        """
        Query Spotify Search API for tracks by genre and strictly filter for tracks
        with valid 30-second preview URLs (preview_url is not None).
        """
        clean_genre = genre.strip()
        if clean_genre.startswith("genre:"):
            query = clean_genre
        else:
            query = f'genre:"{clean_genre}"'

        cache_key = ("genre_preview", query.lower(), market, int(limit))
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        items = []
        try:
            params = {
                "q": query,
                "type": "track",
                "market": market,
                "limit": min(10, max(1, limit)),
            }
            result = self._make_request("search", params)
            items = result.get("tracks", {}).get("items", [])
        except Exception as e:
            print(f"[spotify.search_genre_previews.error] query='{query}' error={e}")

        # Fallback softer query if strict genre tag returned nothing
        if not items and not clean_genre.startswith("genre:"):
            try:
                params = {
                    "q": clean_genre,
                    "type": "track",
                    "market": market,
                    "limit": min(10, max(1, limit)),
                }
                result = self._make_request("search", params)
                items = result.get("tracks", {}).get("items", [])
            except Exception as e:
                print(f"[spotify.search_genre_previews.fallback_error] query='{clean_genre}' error={e}")

        valid_tracks = []
        for track in items:
            preview_url = track.get("preview_url")
            # Directive 2: strictly filter out tracks where preview_url is None
            if not preview_url:
                continue

            artists = track.get("artists") or []
            artist_name = ", ".join(a.get("name") for a in artists if a.get("name")) or "Unknown Artist"
            album = track.get("album") or {}
            images = album.get("images") or []
            album_art = images[0].get("url") if images else None

            valid_tracks.append({
                "spotify_id": track.get("id"),
                "name": track.get("name"),
                "artist": artist_name,
                "preview_url": preview_url,
                "album_art": album_art,
                "album_name": album.get("name"),
                "duration_ms": track.get("duration_ms", 30000),
                "spotify_url": (track.get("external_urls") or {}).get("spotify"),
                "genre": clean_genre.replace("genre:", "").strip('"'),
            })
            if len(valid_tracks) >= limit:
                break

        self._cache_set(cache_key, valid_tracks)
        return valid_tracks

    def _dedupe_queries(self, queries):
        seen = set()
        deduped = []
        for query, weight in queries:
            key = " ".join(
                token
                for token in query.lower().replace(":", " ").split()
                if token not in {"alternative", "smooth", "energetic", "upbeat"}
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append((query, weight))
        return deduped

    def _build_query_plan(self, weighted_queries, markets, max_calls: int = None):
        available_markets = [market for market in (markets or []) if market] or ["US"]
        max_calls = max(1, int(max_calls or MAX_DISCOVERY_SEARCH_CALLS))
        plan = []
        seen = set()
        for index, (query, query_weight) in enumerate(weighted_queries):
            market = available_markets[index % len(available_markets)]
            key = (str(query).lower(), market)
            if key in seen:
                continue
            seen.add(key)
            plan.append((query, query_weight, market))
            if len(plan) >= max_calls:
                break
        if len(plan) < max_calls:
            for query, query_weight in weighted_queries:
                for market in available_markets:
                    key = (str(query).lower(), market)
                    if key in seen:
                        continue
                    seen.add(key)
                    plan.append((query, query_weight, market))
                    if len(plan) >= max_calls:
                        return plan
        return plan

    def _prefer_candidate(self, candidate: dict, incumbent: dict) -> bool:
        candidate_key = (
            int(candidate.get("popularity") or 0),
            float(candidate.get("region_confidence") or 0),
            float(candidate.get("query_match_strength") or 0),
            str(candidate.get("id") or ""),
        )
        incumbent_key = (
            int(incumbent.get("popularity") or 0),
            float(incumbent.get("region_confidence") or 0),
            float(incumbent.get("query_match_strength") or 0),
            str(incumbent.get("id") or ""),
        )
        return candidate_key > incumbent_key

    def _candidate_pool_diagnostics(self, tracks: List[dict], requested_limit: int) -> dict:
        count = len(tracks or [])
        unique_artists = {
            track.get("primary_artist_normalized")
            or normalize_artist_name(track.get("artist", ""))
            for track in tracks or []
            if track.get("artist") or track.get("primary_artist_normalized")
        }
        unique_tracks = {
            track.get("track_fingerprint")
            or track_fingerprint(track.get("name", ""), track.get("artist", ""))
            for track in tracks or []
        }
        region_values = [
            float(track.get("region_confidence", 0.0))
            for track in tracks or []
            if isinstance(track.get("region_confidence"), (int, float))
        ]
        avg_region_confidence = (
            round(sum(region_values) / len(region_values), 3)
            if region_values else 0.0
        )
        target = max(1, min(50, int(requested_limit or 1)))
        reasons = []
        if count < min(target, 12):
            reasons.append("low_count")
        if count and len(unique_tracks) / max(1, count) < 0.75:
            reasons.append("duplicate_pressure")
        if count >= 4 and len(unique_artists) < min(4, max(2, count // 3)):
            reasons.append("low_artist_diversity")
        if count and avg_region_confidence < 0.45:
            reasons.append("low_region_confidence")
        return {
            "weak": bool(reasons),
            "reasons": reasons,
            "count": count,
            "unique_artists": len(unique_artists),
            "unique_tracks": len(unique_tracks),
            "avg_region_confidence": avg_region_confidence,
        }

    def _is_low_quality_track(self, spotify_track: dict) -> bool:
        album = spotify_track.get("album") or {}
        artists = [
            artist for artist in (spotify_track.get("artists") or [])
            if isinstance(artist, dict)
        ]
        text = " ".join([
            spotify_track.get("name") or "",
            album.get("name") or "",
            " ".join(artist.get("name", "") for artist in artists),
        ]).lower()
        return any(term in text for term in LOW_QUALITY_TERMS)

    def _is_wrong_region_track(self, spotify_track: dict, region_key: str) -> bool:
        album = spotify_track.get("album") or {}
        artists = [
            artist for artist in (spotify_track.get("artists") or [])
            if isinstance(artist, dict)
        ]
        text = " ".join([
            spotify_track.get("name") or "",
            album.get("name") or "",
            " ".join(artist.get("name", "") for artist in artists),
        ]).lower()
        competing_markers = {
            "india_tamil": ["punjabi", "bhangra", "hindi", "bollywood"],
            "india_punjabi": ["tamil", "kollywood", "hindi classical", "carnatic"],
            "india_hindi": ["tamil", "kollywood", "punjabi folk"],
        }
        return any(marker in text for marker in competing_markers.get(region_key, []))

    def _region_confidence(self, spotify_track: dict, region_key: str, search_query: str) -> float:
        album = spotify_track.get("album") or {}
        artists = [
            artist for artist in (spotify_track.get("artists") or [])
            if isinstance(artist, dict)
        ]
        text = " ".join([
            spotify_track.get("name") or "",
            album.get("name") or "",
            " ".join(artist.get("name", "") for artist in artists),
            " ".join(
                genre
                for artist in artists
                for genre in (artist.get("genres") or [])
            ),
            search_query or "",
        ]).lower()

        markers = {
            "india_tamil": ["tamil", "kollywood"],
            "india_punjabi": ["punjabi", "bhangra"],
            "india_hindi": ["hindi", "bollywood"],
            "global_english": ["pop", "viral", "dance"],
            "south_korea": ["k-pop", "kpop", "korean"],
            "japan": ["j-pop", "japanese", "anime"],
            "nigeria": ["afrobeats", "afropop", "nigerian"],
            "brazil": ["brazil", "brasileiro", "samba"],
            "latin_america": ["latin", "reggaeton"],
            "arab_world": ["arabic", "arab"],
            "france": ["french", "france"],
        }
        hits = sum(1 for term in markers.get(region_key, []) if term in text)
        query_bonus = 0.12 if any(term in (search_query or "").lower() for term in markers.get(region_key, [])) else 0.0
        return _bounded_signal(0.55 + hits * 0.22 + query_bonus)

    def _user_vector_for_cluster(self, cluster_id: int) -> dict:
        try:
            from engine import CLUSTER_CENTROIDS
        except Exception:
            CLUSTER_CENTROIDS = {}

        try:
            cluster_key = int(cluster_id)
        except (TypeError, ValueError):
            cluster_key = 2
        centroid = CLUSTER_CENTROIDS.get(cluster_key, CLUSTER_CENTROIDS.get(2, {}))
        return {
            "energy": _centroid_signal(centroid.get("energy", 0.0)),
            "mood": _centroid_signal(centroid.get("valence", 0.0)),
            "danceability": _centroid_signal(centroid.get("danceability", 0.0)),
            "tempo": _centroid_signal(centroid.get("tempo", 0.0)),
        }

    def _extract_track_features(
        self,
        spotify_track: dict,
        search_query: str,
        search_weight: float,
        region_key: str,
    ) -> dict:
        album = spotify_track.get("album") or {}
        artists = [
            artist for artist in (spotify_track.get("artists") or [])
            if isinstance(artist, dict)
        ]
        artist_genres = canonicalize_genres([
            genre
            for artist in artists
            for genre in (artist.get("genres") or [])
        ])
        artist_names = " ".join(artist.get("name", "") for artist in artists)
        artist_text = artist_names or "unknown artist"
        track_text = " ".join([
            spotify_track.get("name") or "",
            album.get("name") or "",
            artist_text,
            " ".join(artist_genres),
        ])
        query_tokens = _tokenize_signal_text(search_query or "")
        track_tokens = _tokenize_signal_text(track_text)
        overlap = len(query_tokens & track_tokens) / max(1, len(query_tokens))
        query_match = _bounded_signal((overlap * 0.72) + (_bounded_signal(search_weight) * 0.28))
        duration_ms = spotify_track.get("duration_ms") or 0
        popularity_norm = _bounded_signal((spotify_track.get("popularity") or 0) / 100)

        signal_text = " ".join([
            spotify_track.get("name") or "",
            artist_text,
            search_query or "",
        ]).strip().lower()
        if not signal_text:
            signal_text = (search_query or "").strip().lower()
        if not signal_text:
            signal_text = "music"
        energy = _normalize_signal(_weighted_keyword_signal(
            signal_text,
            [
                ("dance", 0.18), ("party", 0.16), ("club", 0.15), ("remix", 0.14),
                ("banger", 0.16), ("anthem", 0.13), ("kuthu", 0.16), ("bhangra", 0.15),
                ("rock", 0.12), ("drop", 0.14), ("fire", 0.10), ("upbeat", 0.12),
            ],
            [
                ("acoustic", 0.14), ("sleep", 0.16), ("lullaby", 0.18), ("soft", 0.12),
                ("slow", 0.12), ("calm", 0.14), ("lofi", 0.10), ("piano", 0.09),
            ],
            base=0.46 + popularity_norm * 0.08,
        ) * 0.9)
        mood = _normalize_signal(_weighted_keyword_signal(
            signal_text,
            [
                ("happy", 0.18), ("love", 0.10), ("summer", 0.12), ("sunshine", 0.14),
                ("party", 0.10), ("feel good", 0.16), ("celebration", 0.15),
                ("smile", 0.12), ("dream", 0.07),
            ],
            [
                ("sad", 0.20), ("heartbreak", 0.20), ("lonely", 0.17), ("alone", 0.15),
                ("dark", 0.14), ("tears", 0.16), ("rain", 0.09), ("broken", 0.16),
                ("slow", 0.08),
            ],
            base=0.50 + popularity_norm * 0.04,
        ))
        danceability = _normalize_signal(_weighted_keyword_signal(
            signal_text,
            [
                ("dance", 0.20), ("party", 0.14), ("club", 0.14), ("groove", 0.16),
                ("beat", 0.12), ("bhangra", 0.16), ("kuthu", 0.16), ("funk", 0.14),
                ("rap", 0.09), ("hip hop", 0.10), ("reggaeton", 0.16),
            ],
            [("acoustic", 0.10), ("piano", 0.12), ("sleep", 0.16), ("ambient", 0.13)],
            base=0.42 + query_match * 0.12,
        ) * 0.85)
        normalized_signal_text = f" {_normalize_signal_text(signal_text)} "
        tempo_boost = 0.1 if any(
            _contains_signal_term(normalized_signal_text, term)
            for term in ["remix", "club", "dance"]
        ) else 0.0
        tempo = _normalize_signal((0.35 + popularity_norm * 0.22 + query_match * 0.23 + tempo_boost) * 0.75)
        artist_tokens = _tokenize_signal_text(artist_text)
        artist_bias = 0.03 if len(artist_tokens & query_tokens) >= 2 else 0.0

        return {
            "popularity_norm": popularity_norm,
            "query_match_strength": query_match,
            "region_confidence": self._region_confidence(spotify_track, region_key, search_query),
            "duration_score": 1.0 if 120_000 <= duration_ms <= 330_000 else 0.65,
            "artist_genres": artist_genres,
            "genre_families": genre_families_for_genres(artist_genres),
            "proxy_features": {
                "energy": energy,
                "mood": mood,
                "danceability": danceability,
                "tempo": tempo,
                "query_affinity": query_match,
                "popularity": popularity_norm,
                "artist_bias": artist_bias,
            },
        }

    def _compute_similarity(self, track_features: dict, user_vec: dict) -> float:
        if not isinstance(track_features, dict) or not track_features:
            return MIN_METADATA_SIGNAL
        if not isinstance(user_vec, dict) or not user_vec:
            return MIN_METADATA_SIGNAL

        weights = {
            "energy": 0.30,
            "mood": 0.25,
            "danceability": 0.20,
            "tempo": 0.15,
        }
        weight_total = sum(weights.values()) or 1.0
        distance = sum(
            (
                _normalize_signal(track_features.get(feature, 0.5))
                - _normalize_signal(user_vec.get(feature, 0.5))
            ) ** 2 * (weight / weight_total)
            for feature, weight in weights.items()
        ) ** 0.5
        artist_bias = min(0.04, max(0.0, track_features.get("artist_bias", 0.0)))
        return _bounded_signal((1.0 / (1.0 + distance)) + artist_bias)

    def _track_quality_score(self, track: dict) -> float:
        neutral_user_vec = {"energy": 0.5, "mood": 0.5, "danceability": 0.5, "tempo": 0.5}
        return rank_tracks_by_similarity([track], neutral_user_vec, 1, self._compute_similarity)[0]["quality_score"]

    def _preferred_artist_score(self, spotify_track: dict, region_key: str) -> float:
        artist_text = " ".join(
            normalize_artist_name(artist.get("name", ""))
            for artist in (spotify_track.get("artists") or [])
            if isinstance(artist, dict)
        )
        preferred = {
            "india_tamil": [
                "anirudh",
                "gv prakash",
                "gv prakash",
                "yuvan",
                "dhanush",
                "sid sriram",
                "santosh narayanan",
                "hiphop tamizha",
                "arivu",
            ],
            "india_punjabi": [
                "ap dhillon",
                "diljit",
                "sidhu moose wala",
                "karan aujla",
                "shubh",
                "harrdy sandhu",
                "badshah",
                "ikka",
                "gurinder gill",
            ],
            "india_hindi": [
                "arijit",
                "pritam",
                "badshah",
                "shreya",
                "vishal shekhar",
                "amit trivedi",
            ],
            "global_english": [
                "sabrina carpenter",
                "dua lipa",
                "taylor swift",
                "the weeknd",
                "olivia rodrigo",
                "billie eilish",
                "harry styles",
                "ariana grande",
                "doja cat",
                "chappell roan",
            ],
        }
        return 1.0 if any(name in artist_text for name in preferred.get(region_key, [])) else 0.0

    def _format_track(
        self,
        spotify_track: dict,
        source: str = "discovery",
        search_query: str = "",
        search_weight: float = 0.5,
        region_key: str = "",
    ) -> dict:
        album = spotify_track.get("album") or {}
        images = album.get("images") or []
        artists = [
            artist for artist in (spotify_track.get("artists") or [])
            if isinstance(artist, dict)
        ]
        track_id = spotify_track.get("id") or spotify_track.get("uri") or spotify_track.get("name") or "unknown-track"
        track_name = spotify_track.get("name") or "Unknown Track"
        artist_names = [artist.get("name", "").strip() for artist in artists if artist.get("name")]
        primary_artist = artist_names[0] if artist_names else "Unknown Artist"
        artist_display = ", ".join(artist_names) or "Unknown Artist"
        primary_artist_normalized = normalize_artist_name(primary_artist)
        artist_normalized = ", ".join(
            normalized
            for normalized in (normalize_artist_name(name) for name in artist_names)
            if normalized
        ) or primary_artist_normalized or "unknown artist"
        canonical_genres = canonicalize_genres(
            genre
            for artist in artists
            for genre in (artist.get("genres") or [])
        )
        genre_families = genre_families_for_genres(canonical_genres)
        region_family = region_family_for_region(region_key)
        preferred_artist_raw = self._preferred_artist_score(spotify_track, region_key)
        metadata_features = self._extract_track_features(
            spotify_track,
            search_query,
            search_weight,
            region_key,
        )
        if preferred_artist_raw:
            metadata_features["region_confidence"] = max(metadata_features["region_confidence"], 0.85)

        formatted = {
            "id": track_id,
            "name": track_name,
            "artist": artist_display,
            "artists": artist_names,
            "primary_artist": primary_artist,
            "artist_normalized": artist_normalized,
            "primary_artist_normalized": primary_artist_normalized,
            "genres": canonical_genres,
            "canonical_genres": canonical_genres,
            "genre_families": genre_families,
            "region_key": region_key,
            "region": region_key,
            "region_family": region_family,
            "track_fingerprint": track_fingerprint(track_name, primary_artist),
            "album": album.get("name") or "",
            "duration_ms": spotify_track.get("duration_ms") or 180_000,
            "popularity": spotify_track.get("popularity") or 0,
            "uri": spotify_track.get("uri", ""),
            "external_url": spotify_track.get("external_urls", {}).get("spotify", ""),
            "preview_url": spotify_track.get("preview_url"),
            "source": source,
            "search_query": search_query,
            "search_weight": search_weight,
            "preferred_artist_score": _bounded_signal(preferred_artist_raw),
            "album_art": images[0].get("url") if images and isinstance(images[0], dict) else None,
        }
        formatted.update(metadata_features)
        formatted["quality_score"] = self._track_quality_score(formatted)
        return formatted
    
    # # temporary function for evaluation the bug
    
