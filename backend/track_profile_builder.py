"""
Semantic track profile construction for embedding text.

This module intentionally stays lightweight: it enriches existing metadata with
soft descriptors, then hands plain text back to the current embedding pipeline.
It does not rank, train, fetch, or introduce a new model.
"""

from typing import Iterable, List, Optional


STOPWORDS = {
    "a",
    "an",
    "and",
    "by",
    "feat",
    "featuring",
    "for",
    "from",
    "ft",
    "in",
    "mix",
    "of",
    "on",
    "or",
    "remastered",
    "song",
    "songs",
    "the",
    "to",
    "version",
    "with",
}

SHORT_TOKEN_ALLOWLIST = {"dj", "edm", "rnb", "uk"}

REDUNDANT_DESCRIPTOR_SUPPRESSORS = {
    "synthetic-texture": {"synthetic"},
    "organic-texture": {"organic"},
    "dense-atmosphere": {"atmospheric", "textural"},
    "sparse-atmosphere": {"textural"},
    "low-vocal-density": {"melodic", "sung", "vocal", "lyrical", "song-focused"},
    "vocal-forward": {"sung", "vocal", "lyrical", "song-focused"},
    "cinematic-scale": {"cinematic", "immersive", "dramatic"},
    "intimate-scale": {"intimate"},
    "polished-production": {"polished"},
    "raw-production": {"raw"},
    "rhythmic-aggressive": {
        "danceable",
        "driving",
        "electric",
        "energetic",
        "groove",
        "groovy",
        "high-energy",
        "high-intensity",
        "high-tempo",
        "kinetic",
        "movement",
        "rhythmic",
        "urgent",
    },
    "gentle-rhythm": {"low-intensity"},
    "ambient-heavy": {"atmospheric", "immersive", "textural"},
}


def build_track_profile(track: dict) -> str:
    """Build rich semantic text for a track embedding."""
    if not isinstance(track, dict):
        return ""

    name = _clean(track.get("name"))
    artist = _artist_text(track)
    genres = _list_values(track.get("artist_genres") or track.get("genres"))
    query = _clean(track.get("search_query"))
    region = _clean(track.get("region") or track.get("region_key"))
    popularity = _float(track.get("popularity"))
    proxy = track.get("proxy_features") if isinstance(track.get("proxy_features"), dict) else {}

    context_text = " ".join([name, artist, " ".join(genres), query]).lower()

    genre_descriptors = _genre_descriptors(genres, context_text)
    title_descriptors = _title_context_descriptors(context_text)
    texture_descriptors = _texture_descriptors(track, proxy, context_text)
    feature_descriptors = _feature_descriptors(track, proxy)
    popularity_descriptors = _popularity_descriptors(popularity)
    region_descriptors = _region_descriptors(region or _infer_region_from_query(query))
    query_descriptors = _query_descriptors(query)

    metadata_terms = []
    for genre in genres[:6]:
        metadata_terms.extend(_meaningful_tokens(genre, limit=3))
    descriptor_count = sum(
        len(group)
        for group in (
            genre_descriptors,
            title_descriptors,
            texture_descriptors,
            feature_descriptors,
            popularity_descriptors,
            region_descriptors,
            query_descriptors,
        )
    )
    if descriptor_count < 8:
        metadata_terms.extend(_meaningful_tokens(name, limit=3))
        metadata_terms.extend(_meaningful_tokens(artist, limit=3))

    parts = _build_grouped_profile(
        identity_terms=genre_descriptors + region_descriptors + metadata_terms,
        secondary_terms=title_descriptors + texture_descriptors + feature_descriptors,
        context_terms=popularity_descriptors + query_descriptors,
    )
    if not parts:
        fallback = _dedupe(_meaningful_tokens(" ".join([name, artist, query]), limit=16))
        parts = _format_semantic_groups(fallback, [], [])

    return " ".join(parts).strip()


def example_track_profile() -> str:
    """Small demonstration useful for smoke tests and docs."""
    return build_track_profile(
        {
            "name": "After Dark",
            "artist": "Mr.Kitty",
            "genres": ["synthwave", "electronic"],
            "popularity": 58,
            "search_query": "dark synthwave nocturnal electronic",
            "energy": 0.46,
            "valence": 0.28,
            "danceability": 0.62,
            "acousticness": 0.12,
            "instrumentalness": 0.18,
            "tempo": 112,
        }
    )


def _clean(value) -> str:
    return str(value or "").replace("\x00", " ").strip()


def _list_values(value) -> List[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, Iterable):
        return [_clean(item) for item in value if _clean(item)]
    return [_clean(value)] if _clean(value) else []


def _artist_text(track: dict) -> str:
    artist = track.get("artist")
    if artist:
        return _clean(artist)
    artists = track.get("artists")
    if isinstance(artists, list):
        names = []
        for item in artists:
            if isinstance(item, dict):
                names.append(_clean(item.get("name")))
            else:
                names.append(_clean(item))
        return ", ".join(name for name in names if name)
    return ""


def _float(value, default: Optional[float] = None) -> Optional[float]:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _feature(track: dict, proxy: dict, key: str, default: Optional[float] = None) -> Optional[float]:
    value = track.get(key)
    if value is None:
        value = proxy.get(key)
    return _float(value, default)


def _tempo_value(track: dict, proxy: dict) -> Optional[float]:
    value = _feature(track, proxy, "tempo")
    if value is None:
        return None
    if 0.0 <= value <= 1.0:
        return 70.0 + value * 110.0
    return value


def _feature_descriptors(track: dict, proxy: dict) -> List[str]:
    energy = _feature(track, proxy, "energy")
    valence = _feature(track, proxy, "valence")
    mood = _feature(track, proxy, "mood", valence)
    danceability = _feature(track, proxy, "danceability")
    acousticness = _feature(track, proxy, "acousticness")
    instrumentalness = _feature(track, proxy, "instrumentalness")
    speechiness = _feature(track, proxy, "speechiness")
    tempo = _tempo_value(track, proxy)

    descriptors = []
    descriptors.extend(_banded(energy, "calm mellow gentle", "steady balanced", "energetic kinetic electric"))
    descriptors.extend(_banded(mood, "dark melancholic emotional", "bittersweet reflective", "bright uplifting joyful"))
    descriptors.extend(_banded(danceability, "still textural listening-focused", "rhythmic midtempo", "danceable groovy movement"))
    descriptors.extend(_banded(acousticness, "electronic synthetic polished", "", "acoustic organic warm"))
    descriptors.extend(_banded(instrumentalness, "vocal lyrical song-focused", "", "instrumental cinematic immersive"))
    descriptors.extend(_banded(speechiness, "melodic sung", "", "rap spoken-word lyrical"))

    if tempo is not None:
        if tempo >= 140:
            descriptors.extend(["fast", "driving", "high-tempo"])
        elif tempo <= 85:
            descriptors.extend(["slow", "patient", "spacious"])

    intensity = None
    if energy is not None and tempo is not None:
        tempo_norm = max(0.0, min(1.0, (tempo - 70.0) / 110.0))
        intensity = (energy * 0.65) + (tempo_norm * 0.35)
    elif energy is not None:
        intensity = energy
    descriptors.extend(_banded(intensity, "low-intensity relaxed", "moderate-intensity", "high-intensity urgent"))

    if acousticness is not None and acousticness < 0.28 and instrumentalness is not None and instrumentalness > 0.22:
        descriptors.extend(["cinematic", "atmospheric"])
    elif danceability is not None and danceability > 0.62 and instrumentalness is not None and instrumentalness < 0.2:
        descriptors.extend(["casual", "social", "playlist-friendly"])

    return descriptors


def _texture_descriptors(track: dict, proxy: dict, context_text: str) -> List[str]:
    """
    Describe sonic-world texture using existing metadata only.

    These descriptors are deliberately coarse: they enrich embedding text and
    preserve transition semantics without becoming a mood taxonomy.
    """
    energy = _feature(track, proxy, "energy", 0.5)
    danceability = _feature(track, proxy, "danceability", 0.5)
    acousticness = _feature(track, proxy, "acousticness", 0.35)
    instrumentalness = _feature(track, proxy, "instrumentalness", 0.0)
    speechiness = _feature(track, proxy, "speechiness", 0.05)
    liveness = _feature(track, proxy, "liveness", 0.18)
    tempo = _tempo_value(track, proxy)

    tempo_norm = 0.5
    if tempo is not None:
        tempo_norm = max(0.0, min(1.0, (tempo - 70.0) / 110.0))

    electronic_context = _has_any(
        context_text,
        ["ambient", "synth", "electronic", "edm", "techno", "house", "score", "soundtrack"],
    )
    organic_context = _has_any(
        context_text,
        ["acoustic", "folk", "country", "singer-songwriter", "blues", "orchestral", "live"],
    )
    raw_context = _has_any(context_text, ["live", "demo", "garage", "punk", "raw", "session"])

    synthetic = max(0.0, min(1.0, (1.0 - acousticness) * 0.65 + (0.25 if electronic_context else 0.0)))
    organic = max(0.0, min(1.0, acousticness * 0.72 + (0.22 if organic_context else 0.0)))
    atmosphere_density = max(
        0.0,
        min(
            1.0,
            instrumentalness * 0.38
            + (1.0 - acousticness) * 0.28
            + (0.24 if electronic_context else 0.0)
            + (1.0 - min(1.0, speechiness * 4.0)) * 0.10,
        ),
    )
    vocal_density = max(0.0, min(1.0, (1.0 - instrumentalness) * 0.72 + min(1.0, speechiness * 4.0) * 0.28))
    rhythmic_aggression = max(0.0, min(1.0, energy * 0.42 + danceability * 0.34 + tempo_norm * 0.24))
    ambient_weight = max(
        0.0,
        min(1.0, atmosphere_density * 0.72 + instrumentalness * 0.18 + (0.10 if "ambient" in context_text else 0.0)),
    )
    cinematic = max(0.0, min(1.0, atmosphere_density * 0.48 + instrumentalness * 0.32 + synthetic * 0.20))
    intimate = max(0.0, min(1.0, organic * 0.36 + vocal_density * 0.34 + (1.0 - energy) * 0.20 + liveness * 0.10))
    polished = max(0.0, min(1.0, synthetic * 0.45 + (1.0 - liveness) * 0.25 + (1.0 - speechiness) * 0.15 + energy * 0.15))
    raw = max(0.0, min(1.0, organic * 0.36 + liveness * 0.30 + (0.22 if raw_context else 0.0) + (1.0 - polished) * 0.12))

    descriptors = []
    descriptors.append("synthetic-texture" if synthetic >= organic else "organic-texture")
    descriptors.append("dense-atmosphere" if atmosphere_density >= 0.62 else "sparse-atmosphere")
    if vocal_density >= 0.62:
        descriptors.append("vocal-forward")
    elif vocal_density <= 0.36:
        descriptors.append("low-vocal-density")
    else:
        descriptors.append("balanced-vocal-density")
    descriptors.append("cinematic-scale" if cinematic >= intimate else "intimate-scale")
    descriptors.append("polished-production" if polished >= raw else "raw-production")
    descriptors.append("rhythmic-aggressive" if rhythmic_aggression >= 0.62 else "gentle-rhythm")
    descriptors.append("ambient-heavy" if ambient_weight >= 0.58 else "ambient-light")
    return descriptors


def _banded(value: Optional[float], low: str, mid: str, high: str) -> List[str]:
    if value is None:
        return []
    if value <= 0.38:
        return low.split()
    if value >= 0.62:
        return high.split()
    return mid.split()


def _popularity_descriptors(popularity: Optional[float]) -> List[str]:
    if popularity is None:
        return []
    if popularity >= 75:
        return ["mainstream", "popular", "familiar"]
    if popularity >= 55:
        return ["accessible", "known"]
    if popularity <= 25:
        return ["underground", "niche", "discovery"]
    return ["emerging", "discovery-friendly"]


def _genre_descriptors(genres: List[str], context_text: str) -> List[str]:
    text = " ".join(genres).lower()
    descriptors = []

    if _has_any(text, ["synth", "wave", "electronic", "edm", "house", "techno"]):
        descriptors.extend(["electronic", "synthetic", "atmospheric"])
    if _has_any(text, ["synthwave", "retrowave", "vaporwave"]):
        descriptors.extend(["retro", "nocturnal", "neon"])
    if _has_any(text, ["ambient", "lofi", "chill", "downtempo"]):
        descriptors.extend(["soft", "textural", "relaxed"])
    if _has_any(text, ["pop", "indie"]):
        descriptors.extend(["melodic", "accessible"])
    if _has_any(text, ["rock", "metal", "punk", "alt"]):
        descriptors.extend(["guitar-driven", "raw", "intense"])
    if _has_any(text, ["rap", "hip hop", "trap", "drill"]):
        descriptors.extend(["rhythmic", "vocal", "percussive"])
    if _has_any(text, ["r&b", "rnb", "soul", "blues"]):
        descriptors.extend(["smooth", "soulful", "emotional"])
    if _has_any(text, ["folk", "acoustic", "country", "singer-songwriter"]):
        descriptors.extend(["organic", "intimate", "warm"])
    if _has_any(text, ["classical", "score", "soundtrack", "orchestral"]):
        descriptors.extend(["cinematic", "orchestral", "dramatic"])
    if _has_any(text, ["dance", "disco", "funk", "reggaeton", "bhangra", "kuthu", "afrobeats"]):
        descriptors.extend(["danceable", "groove", "rhythmic"])

    if not descriptors and genres:
        descriptors.extend(_meaningful_tokens(" ".join(genres), limit=8))
    if _has_any(context_text, ["live", "concert", "acoustic version"]):
        descriptors.extend(["live", "performance"])
    if _has_any(context_text, ["remix", "club mix", "edit"]):
        descriptors.extend(["remix", "club-ready"])
    return descriptors


def _title_context_descriptors(text: str) -> List[str]:
    descriptors = []
    if _has_any(text, ["dark", "night", "midnight", "after dark", "shadow"]):
        descriptors.extend(["dark", "nocturnal", "moody"])
    if _has_any(text, ["sad", "heartbreak", "lonely", "alone", "tears", "rain", "broken"]):
        descriptors.extend(["melancholic", "vulnerable", "emotional"])
    if _has_any(text, ["dream", "sky", "moon", "space", "ocean", "echo"]):
        descriptors.extend(["dreamy", "spacious", "atmospheric"])
    if _has_any(text, ["love", "heart", "romance"]):
        descriptors.extend(["romantic", "emotional"])
    if _has_any(text, ["happy", "sun", "summer", "smile", "celebration"]):
        descriptors.extend(["bright", "warm", "feel-good"])
    if _has_any(text, ["party", "club", "dance", "banger", "anthem"]):
        descriptors.extend(["party", "high-energy", "social"])
    return descriptors


def _query_descriptors(query: str) -> List[str]:
    if not query:
        return []
    tokens = _meaningful_tokens(query, limit=10)
    if not tokens:
        return []
    return ["search-context"] + tokens


def _region_descriptors(region: str) -> List[str]:
    if not region:
        return []
    text = region.replace("_", " ").replace("-", " ").lower()
    descriptors = _meaningful_tokens(text, limit=4)
    if "india" in text:
        descriptors.append("indian")
    if "tamil" in text or "hindi" in text or "punjabi" in text:
        descriptors.append("regional")
    if "korea" in text:
        descriptors.extend(["korean", "k-pop"])
    if "japan" in text:
        descriptors.extend(["japanese", "j-pop"])
    if "latin" in text:
        descriptors.append("latin")
    if "arab" in text:
        descriptors.append("arabic")
    if "nigeria" in text:
        descriptors.extend(["nigerian", "afrobeats"])
    if "brazil" in text:
        descriptors.append("brazilian")
    if "france" in text:
        descriptors.append("french")
    return descriptors


def _infer_region_from_query(query: str) -> str:
    text = (query or "").lower()
    for marker in ("tamil", "hindi", "punjabi", "korean", "japanese", "latin", "arabic", "nigerian", "brazilian", "french"):
        if marker in text:
            return marker
    return ""


def _meaningful_tokens(text: str, limit: int = 12) -> List[str]:
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in _clean(text))
    tokens = []
    for token in cleaned.split():
        if token in STOPWORDS:
            continue
        if len(token) < 3 and token not in SHORT_TOKEN_ALLOWLIST:
            continue
        tokens.append(token)
        if len(tokens) >= limit:
            break
    return tokens


def _has_any(text: str, terms: List[str]) -> bool:
    padded = f" {text.lower()} "
    return any(term in padded for term in terms)


def _dedupe(values: List[str]) -> List[str]:
    seen = set()
    result = []
    for raw in values:
        value = _clean(raw).lower()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result[:48]


def _prune_redundant_descriptors(values: List[str]) -> List[str]:
    present = set(values)
    suppressed = {"search-context"}
    for precise, broad_terms in REDUNDANT_DESCRIPTOR_SUPPRESSORS.items():
        if precise in present:
            suppressed.update(broad_terms)

    return [value for value in values if value not in suppressed]


def _build_grouped_profile(
    identity_terms: List[str],
    secondary_terms: List[str],
    context_terms: List[str],
) -> List[str]:
    all_terms = _dedupe(identity_terms + secondary_terms + context_terms)
    pruned_terms = set(_prune_redundant_descriptors(all_terms))
    seen = set()

    def _group(values: List[str]) -> List[str]:
        result = []
        for value in _dedupe(values):
            if value not in pruned_terms or value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result

    identity = _group(identity_terms)
    secondary = _group(secondary_terms)
    context = _group(context_terms)
    return _format_semantic_groups(identity, secondary, context)


def _format_semantic_groups(
    identity: List[str],
    secondary: List[str],
    context: List[str],
) -> List[str]:
    parts = []
    if identity:
        parts.extend(["identity"] + identity)
    if secondary:
        parts.extend(["secondary"] + secondary)
    if context:
        parts.extend(["context"] + context)
    return parts
