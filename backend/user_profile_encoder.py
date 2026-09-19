from typing import Iterable, List, Optional

import numpy as np

SIGNAL_WEIGHTS = {
    "quiz": 0.5,
    "spotify": 0.3,
    "clips": 0.2,
}


def normalize_embedding(embedding) -> Optional[np.ndarray]:
    if embedding is None:
        return None
    vec = np.asarray(embedding, dtype=np.float32)
    if vec.ndim != 1 or vec.size == 0:
        return None
    norm = float(np.linalg.norm(vec))
    if not np.isfinite(norm) or norm <= 0:
        return None
    return vec / norm


def cosine_similarity(a, b) -> float:
    left = normalize_embedding(a)
    right = normalize_embedding(b)
    if left is None or right is None or left.shape != right.shape:
        return 0.0
    return float(np.clip(np.dot(left, right), -1.0, 1.0))


def _clean(value) -> str:
    return str(value or "").replace("\x00", " ").strip()


def _flatten_text(values) -> List[str]:
    if not values:
        return []
    if isinstance(values, str):
        return [_clean(values)] if _clean(values) else []
    if isinstance(values, dict):
        parts = []
        for key in ("answer", "text", "question", "reasoning", "label", "name"):
            if values.get(key):
                parts.append(_clean(values[key]))
        return parts
    if isinstance(values, Iterable):
        parts = []
        for value in values:
            parts.extend(_flatten_text(value))
        return parts
    text = _clean(values)
    return [text] if text else []


def _feature_words(genome: Optional[dict]) -> List[str]:
    if not genome:
        return []
    specs = [
        ("energy", "calm", "high energy electric"),
        ("valence", "dark melancholic", "bright joyful"),
        ("danceability", "still textural", "danceable rhythmic"),
        ("acousticness", "electronic synthetic", "acoustic organic"),
        ("instrumentalness", "vocal lyrical", "instrumental cinematic"),
        ("speechiness", "melodic", "rap spoken word"),
        ("tempo", "slow patient", "fast kinetic"),
    ]
    words = []
    for key, low, high in specs:
        try:
            value = float(genome.get(key, 0.0))
        except Exception:
            value = 0.0
        if value >= 0.35:
            words.append(high)
        elif value <= -0.35:
            words.append(low)
    return words


def quiz_to_text(quiz_responses=None, genome: Optional[dict] = None, archetype: Optional[dict] = None) -> str:
    parts = _flatten_text(quiz_responses)
    if archetype:
        parts.extend(_flatten_text([
            archetype.get("name"),
            archetype.get("tagline"),
            archetype.get("traits") or [],
        ]))
    parts.extend(_feature_words(genome))
    if not parts:
        parts.append("balanced exploratory music listener")
    return " ".join(parts)[:1200]


def spotify_to_text(spotify_taste_profile: Optional[dict]) -> str:
    if not spotify_taste_profile:
        return ""
    artists = spotify_taste_profile.get("artists") or spotify_taste_profile.get("top_artists") or []
    artist_names = []
    for artist in artists[:12]:
        artist_names.append(_clean(artist.get("name") if isinstance(artist, dict) else artist))
    genres = [_clean(g) for g in (spotify_taste_profile.get("genres") or [])[:12] if g]
    tracks = [
        _clean(track.get("name"))
        for track in (spotify_taste_profile.get("top_tracks") or [])[:8]
        if isinstance(track, dict) and track.get("name")
    ]
    descriptors = []
    if spotify_taste_profile.get("regional_affinity"):
        descriptors.append(f"{spotify_taste_profile.get('regional_affinity')} regional affinity")
    for key, low, high in (
        ("energy_preference", "calm", "energetic"),
        ("mood_preference", "melancholic", "bright"),
        ("danceability_preference", "less dance focused", "danceable"),
    ):
        value = spotify_taste_profile.get(key)
        if value is None:
            continue
        try:
            descriptors.append(high if float(value) >= 0.58 else low if float(value) <= 0.42 else "balanced")
        except Exception:
            continue
    text = " ".join([
        "top artists include", " ".join(a for a in artist_names if a),
        "preferred genres include", " ".join(genres),
        "liked tracks include", " ".join(tracks),
        " ".join(descriptors),
    ]).strip()
    return text[:1200]


def clips_to_text(clip_reactions=None, clip_genome: Optional[dict] = None) -> str:
    parts = _flatten_text(clip_reactions)
    parts.extend(_feature_words(clip_genome))
    if not parts:
        return ""
    return "prefers " + " ".join(parts)[:1000]


class UserProfileEncoder:
    def __init__(self, embedding_ranker=None):
        if embedding_ranker is not None:
            self.embedding_ranker = embedding_ranker
        else:
            try:
                from embedding_ranker import EmbeddingRanker
                self.embedding_ranker = EmbeddingRanker()
            except Exception as exc:
                print(f"[user_profile_encoder.init_error] error={exc}")
                self.embedding_ranker = None

    def encode_text(self, text: str) -> Optional[np.ndarray]:
        if not self.embedding_ranker or not _clean(text):
            return None
        try:
            return normalize_embedding(self.embedding_ranker.embed_cached(_clean(text)))
        except Exception as exc:
            print(f"[user_profile_encoder.encode_error] error={exc}")
            return None

    def get_user_embedding(
        self,
        quiz_responses=None,
        spotify_taste_profile: Optional[dict] = None,
        clip_reactions=None,
        quiz_genome: Optional[dict] = None,
        clip_genome: Optional[dict] = None,
        archetype: Optional[dict] = None,
    ) -> Optional[np.ndarray]:
        signal_texts = {
            "quiz": quiz_to_text(quiz_responses, quiz_genome, archetype),
            "spotify": spotify_to_text(spotify_taste_profile),
            "clips": clips_to_text(clip_reactions, clip_genome),
        }
        weighted = []
        total_weight = 0.0
        for signal, text in signal_texts.items():
            vec = self.encode_text(text)
            if vec is None:
                continue
            weight = SIGNAL_WEIGHTS[signal]
            weighted.append(vec * weight)
            total_weight += weight
        if not weighted or total_weight <= 0:
            return None
        return normalize_embedding(np.sum(weighted, axis=0) / total_weight)

    def get_track_embedding(self, track: dict) -> Optional[np.ndarray]:
        if not self.embedding_ranker:
            return None
        try:
            text = self.embedding_ranker.build_text(track)
            return normalize_embedding(self.embedding_ranker.embed_cached(text))
        except Exception as exc:
            print(f"[user_profile_encoder.track_encode_error] error={exc}")
            return None


_default_encoder = None


def get_user_embedding(
    quiz_responses=None,
    spotify_taste_profile: Optional[dict] = None,
    clip_reactions=None,
    quiz_genome: Optional[dict] = None,
    clip_genome: Optional[dict] = None,
    archetype: Optional[dict] = None,
    embedding_ranker=None,
):
    encoder = UserProfileEncoder(embedding_ranker=embedding_ranker) if embedding_ranker is not None else _get_default_encoder()
    return encoder.get_user_embedding(
        quiz_responses=quiz_responses,
        spotify_taste_profile=spotify_taste_profile,
        clip_reactions=clip_reactions,
        quiz_genome=quiz_genome,
        clip_genome=clip_genome,
        archetype=archetype,
    )


def _get_default_encoder() -> UserProfileEncoder:
    global _default_encoder
    if _default_encoder is None:
        _default_encoder = UserProfileEncoder()
    return _default_encoder
