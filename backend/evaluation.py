import math
from typing import Callable, Iterable, List, Optional, Sequence


def _track_identity(track: dict) -> str:
    return str(track.get("id") or f"{track.get('name', '')}:{track.get('artist', '')}").strip().lower()


def _primary_artist(track: dict) -> str:
    return str(track.get("artist", "")).split(",")[0].strip().lower()


def _track_genres(track: dict) -> List[str]:
    genres = track.get("artist_genres") or track.get("genres") or []
    if isinstance(genres, str):
        genres = genres.replace("[", "").replace("]", "").replace('"', "").split(",")
    return [str(genre).strip().lower() for genre in genres if str(genre).strip()]


def _as_vector(embedding) -> Optional[List[float]]:
    if embedding is None:
        return None
    try:
        values = embedding.tolist() if hasattr(embedding, "tolist") else list(embedding)
        vector = [float(value) for value in values]
    except Exception:
        return None
    if not vector or any(not math.isfinite(value) for value in vector):
        return None
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0:
        return None
    return [value / norm for value in vector]


def cosine_similarity(left_embedding, right_embedding) -> float:
    left = _as_vector(left_embedding)
    right = _as_vector(right_embedding)
    if left is None or right is None or len(left) != len(right):
        return 0.0
    return max(-1.0, min(1.0, sum(a * b for a, b in zip(left, right))))


def intra_list_diversity(tracks: Sequence[dict]) -> dict:
    if not tracks:
        return {"unique_artists_ratio": 0.0, "unique_genres_ratio": 0.0}
    artists = [_primary_artist(track) for track in tracks if _primary_artist(track)]
    genres = [genre for track in tracks for genre in _track_genres(track)]
    return {
        "unique_artists_ratio": round(len(set(artists)) / max(1, len(tracks)), 3),
        "unique_genres_ratio": round(len(set(genres)) / max(1, len(genres)), 3) if genres else 0.0,
    }


def novelty(tracks: Sequence[dict]) -> dict:
    if not tracks:
        return {
            "inverse_popularity": 0.0,
            "mainstream_ratio": 0.0,
            "niche_ratio": 0.0,
            "mainstream_niche_balance": 0.0,
        }
    popularities = [max(0.0, min(float(track.get("popularity") or 0), 100.0)) for track in tracks]
    inverse = sum(1.0 - (popularity / 100.0) for popularity in popularities) / len(popularities)
    mainstream = sum(1 for popularity in popularities if popularity >= 65.0) / len(popularities)
    niche = sum(1 for popularity in popularities if popularity <= 45.0) / len(popularities)
    return {
        "inverse_popularity": round(inverse, 3),
        "mainstream_ratio": round(mainstream, 3),
        "niche_ratio": round(niche, 3),
        "mainstream_niche_balance": round(1.0 - abs(mainstream - niche), 3),
    }


def playlist_overlap(left_tracks: Sequence[dict], right_tracks: Sequence[dict]) -> float:
    left_ids = {_track_identity(track) for track in left_tracks if _track_identity(track)}
    right_ids = {_track_identity(track) for track in right_tracks if _track_identity(track)}
    if not left_ids and not right_ids:
        return 0.0
    return round(len(left_ids & right_ids) / max(1, len(left_ids | right_ids)), 3)


def embedding_distance(left_embedding, right_embedding) -> float:
    return round(1.0 - ((cosine_similarity(left_embedding, right_embedding) + 1.0) / 2.0), 3)


def playlist_embedding_centroid(track_embeddings: Iterable) -> Optional[List[float]]:
    vectors = [_as_vector(embedding) for embedding in track_embeddings]
    vectors = [vector for vector in vectors if vector is not None]
    if not vectors:
        return None
    width = len(vectors[0])
    vectors = [vector for vector in vectors if len(vector) == width]
    if not vectors:
        return None
    centroid = [sum(vector[i] for vector in vectors) / len(vectors) for i in range(width)]
    return _as_vector(centroid)


def semantic_consistency(user_embedding, track_embeddings: Iterable) -> dict:
    centroid = playlist_embedding_centroid(track_embeddings)
    if user_embedding is None or centroid is None:
        return {"semantic_match": None, "embedding_distance": None}
    similarity = (cosine_similarity(user_embedding, centroid) + 1.0) / 2.0
    return {
        "semantic_match": round(similarity, 3),
        "embedding_distance": round(1.0 - similarity, 3),
    }


def personalization_separation(
    left_tracks: Sequence[dict],
    right_tracks: Sequence[dict],
    left_embedding=None,
    right_embedding=None,
) -> dict:
    return {
        "playlist_overlap": playlist_overlap(left_tracks, right_tracks),
        "embedding_distance": embedding_distance(left_embedding, right_embedding)
        if left_embedding is not None and right_embedding is not None else None,
    }


def ranking_consistency(first_ranking: Sequence, second_ranking: Sequence) -> dict:
    first_ids = [_track_identity(item) if isinstance(item, dict) else str(item) for item in first_ranking]
    second_ids = [_track_identity(item) if isinstance(item, dict) else str(item) for item in second_ranking]
    if not first_ids and not second_ids:
        return {"same_order_ratio": 1.0, "deterministic": True}
    shared = [track_id for track_id in first_ids if track_id in set(second_ids)]
    same_position = sum(
        1 for track_id in shared
        if first_ids.index(track_id) == second_ids.index(track_id)
    )
    return {
        "same_order_ratio": round(same_position / max(1, len(shared)), 3),
        "deterministic": first_ids == second_ids,
    }


def repeated_ranking_consistency(rankings: Sequence[Sequence]) -> dict:
    if len(rankings) < 2:
        return {"average_same_order_ratio": 1.0, "deterministic": True}
    results = [ranking_consistency(rankings[0], ranking) for ranking in rankings[1:]]
    return {
        "average_same_order_ratio": round(
            sum(result["same_order_ratio"] for result in results) / len(results),
            3,
        ),
        "deterministic": all(result["deterministic"] for result in results),
    }


def deterministic_ordering_validation(rankings: Sequence[Sequence]) -> bool:
    return bool(repeated_ranking_consistency(rankings)["deterministic"])


def evaluate_playlist(
    tracks: Sequence[dict],
    user_embedding=None,
    track_embedding_fn: Optional[Callable[[dict], object]] = None,
) -> dict:
    track_embeddings = []
    if track_embedding_fn:
        for track in tracks:
            try:
                embedding = track_embedding_fn(track)
                if embedding is not None:
                    track_embeddings.append(embedding)
            except Exception:
                continue
    semantic = semantic_consistency(user_embedding, track_embeddings) if track_embeddings else {
        "semantic_match": None,
        "embedding_distance": None,
    }
    return {
        "diversity": intra_list_diversity(tracks),
        "novelty": novelty(tracks),
        "semantic": semantic,
    }
