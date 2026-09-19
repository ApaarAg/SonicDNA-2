from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence
from urllib.parse import quote


AUDIO_EXTENSIONS = (".mp3", ".wav", ".ogg", ".m4a")

FOLDER_ALIASES = {
    "bollywood": "BollywoodIndian Classical",
    "indian": "BollywoodIndian Classical",
    "kpop": "K-popJ-pop",
    "jpop": "K-popJ-pop",
    "blues": "BluesSoul",
    "soul": "BluesSoul",
    "reggae": "ReggaeDancehall",
    "dancehall": "ReggaeDancehall",
    "classical": "Classical",
    "orchestral": "Orchestral",
}


def _stable_int(value: str) -> int:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _clip_category(clip_id: str, clip_data: dict) -> str:
    folder = str(clip_data.get("folder") or "").strip()
    if folder:
        return folder
    tags = clip_data.get("tags") or []
    return str(tags[0]) if tags else str(clip_id)


def _feature_distance(a: dict, b: dict) -> float:
    keys = ["danceability", "energy", "valence", "acousticness", "instrumentalness", "speechiness"]
    fa = a.get("features") or {}
    fb = b.get("features") or {}
    return sum((float(fa.get(k, 0.5)) - float(fb.get(k, 0.5))) ** 2 for k in keys) ** 0.5


def _ordered_ids(ids: Iterable[str], session_key: str, salt: str) -> List[str]:
    return sorted(ids, key=lambda clip_id: (_stable_int(f"{session_key}|{salt}|{clip_id}"), clip_id))


def _round_robin_categories(
    features: Dict[str, dict],
    ids: Sequence[str],
    count: int,
    session_key: str,
) -> List[str]:
    by_category: dict[str, List[str]] = defaultdict(list)
    for clip_id in ids:
        by_category[_clip_category(clip_id, features[clip_id])].append(clip_id)

    categories = sorted(
        by_category,
        key=lambda category: (_stable_int(f"{session_key}|category|{category}"), category),
    )
    for category in categories:
        by_category[category] = _ordered_ids(by_category[category], session_key, category)

    selected: List[str] = []
    cursor = 0
    while len(selected) < count and categories:
        category = categories[cursor % len(categories)]
        bucket = by_category[category]
        if bucket:
            selected.append(bucket.pop(0))
        categories = [cat for cat in categories if by_category[cat]]
        cursor += 1
    return selected


def select_round_clip_ids(
    features: Dict[str, dict],
    count: int,
    session_key: str = "",
    exclude_ids: Optional[Iterable[str]] = None,
    preferred_ids: Optional[Iterable[str]] = None,
) -> List[str]:
    """Select clips with category coverage first, then deterministic rotation."""
    count = max(0, int(count or 0))
    if count == 0:
        return []

    excluded = set(exclude_ids or [])
    preferred = [clip_id for clip_id in (preferred_ids or []) if clip_id in features and clip_id not in excluded]
    all_ids = [clip_id for clip_id in features if clip_id not in excluded]

    selected = _round_robin_categories(features, preferred, min(count, len(preferred)), session_key)
    if len(selected) < count:
        remaining = [clip_id for clip_id in all_ids if clip_id not in set(selected)]
        selected.extend(_round_robin_categories(features, remaining, count - len(selected), f"{session_key}|all"))
    return selected[:count]


def select_adaptive_clip_ids(
    features: Dict[str, dict],
    existing_ratings: Sequence[dict],
    count: int,
    session_key: str = "",
    exclude_ids: Optional[Iterable[str]] = None,
) -> List[str]:
    """Select follow-up clips near the rated taste vector without replaying categories too tightly."""
    count = max(0, int(count or 0))
    if count == 0:
        return []

    excluded = {str(r.get("clip_id")) for r in existing_ratings if r.get("clip_id")}
    excluded.update(exclude_ids or [])
    available = [clip_id for clip_id in features if clip_id not in excluded]
    if not existing_ratings:
        return select_round_clip_ids(features, count, session_key=session_key, exclude_ids=excluded)
    if not available:
        return []

    feature_keys = ["danceability", "energy", "valence", "acousticness", "instrumentalness", "speechiness"]
    weighted = {key: 0.0 for key in feature_keys}
    total_weight = 0.0
    used_categories = set()
    for rating in existing_ratings:
        clip_id = rating.get("clip_id")
        clip = features.get(clip_id)
        if not clip:
            continue
        used_categories.add(_clip_category(clip_id, clip))
        weight = max(1.0, float(rating.get("rating") or 3))
        for key in feature_keys:
            weighted[key] += float((clip.get("features") or {}).get(key, 0.5)) * weight
        total_weight += weight

    if total_weight <= 0:
        return select_round_clip_ids(features, count, session_key=session_key, exclude_ids=excluded)

    target = {key: weighted[key] / total_weight for key in feature_keys}

    def score(clip_id: str) -> tuple[float, int, str]:
        clip = features[clip_id]
        feats = clip.get("features") or {}
        dist = sum((float(feats.get(key, 0.5)) - target[key]) ** 2 for key in feature_keys) ** 0.5
        category = _clip_category(clip_id, clip)
        category_bonus = 0.35 if category not in used_categories else 0.0
        jitter = (_stable_int(f"{session_key}|adaptive|{clip_id}") % 1000) / 1_000_000
        return (-(dist) + category_bonus + jitter, -len(used_categories & {category}), clip_id)

    ranked = sorted(available, key=score, reverse=True)
    selected: List[str] = []
    selected_categories = set()
    for clip_id in ranked:
        category = _clip_category(clip_id, features[clip_id])
        if category in selected_categories and len(selected_categories) < count:
            continue
        selected.append(clip_id)
        selected_categories.add(category)
        if len(selected) >= count:
            return selected

    for clip_id in ranked:
        if clip_id not in selected:
            selected.append(clip_id)
        if len(selected) >= count:
            break
    return selected[:count]


def clip_distribution_diagnostics(
    features: Dict[str, dict],
    selected_ids: Sequence[str],
    clips_dir: Optional[Path] = None,
) -> dict:
    categories = [_clip_category(clip_id, features[clip_id]) for clip_id in selected_ids if clip_id in features]
    all_categories = {_clip_category(clip_id, data) for clip_id, data in features.items()} if features else set()
    playable_assets = {}
    if clips_dir is not None:
        try:
            rotator = ClipAssetRotator(features, clips_dir)
            for category in all_categories:
                folder = rotator.resolve_folder(category)
                playable_assets[category] = len(rotator.audio_files(folder)) if folder else 0
        except Exception:
            playable_assets = {}

    return {
        "selected_count": len(selected_ids),
        "selected_unique_categories": len(set(categories)),
        "available_categories": len(all_categories) or len(DEFAULT_ROTATION_GENRES),
        "category_counts": dict(sorted(Counter(categories).items())),
        "coverage_ratio": round(len(set(categories)) / (len(all_categories) or 1), 3) if all_categories else 1.0,
        "playable_assets_by_category": playable_assets,
    }


DEFAULT_ROTATION_GENRES = [
    "dark_orchestral",
    "latin",
    "acoustic",
    "electronic",
    "hip-hop",
    "pop",
    "classical",
    "jazz",
    "blues",
    "reggae",
    "indie",
    "ambient",
]


class DynamicClipRotator:
    """
    Dynamic Clip Rotator powered by Spotify Search API.
    Fetches real 30-second preview clips across genres, caches them,
    and formats them for SonicDNA's onboarding calibration.
    """

    def __init__(self, features: Optional[Dict[str, dict]] = None, clips_dir: Optional[Path] = None, audio_mount: str = "/audio"):
        self.features = features or {}
        self.clips_dir = Path(clips_dir) if clips_dir else None
        self.audio_mount = audio_mount.rstrip("/")
        self.genres = list(DEFAULT_ROTATION_GENRES)

    def get_round_clips(
        self,
        count: int = 8,
        session_key: str = "",
        exclude_ids: Optional[Iterable[str]] = None,
    ) -> List[dict]:
        """Fetch count dynamic preview clips across diversified genres."""
        from dynamic_clips import fetch_genre_previews, GENRE_FEATURE_PROFILES
        count = max(1, int(count or 8))
        excluded = set(exclude_ids or [])

        # Rotate genres deterministically by session_key
        ordered_genres = sorted(
            self.genres,
            key=lambda g: _stable_int(f"{session_key}|genre|{g}")
        )

        clips: List[dict] = []
        genre_idx = 0

        while len(clips) < count and genre_idx < len(ordered_genres) * 3:
            current_genre = ordered_genres[genre_idx % len(ordered_genres)]
            tracks = fetch_genre_previews(current_genre, limit=5)

            for track in tracks:
                clip_id = f"dyn_{track['spotify_id']}"
                if clip_id in excluded or any(c["clip_id"] == clip_id for c in clips):
                    continue

                clips.append({
                    "clip_id": clip_id,
                    "title": track["name"],
                    "artist": track["artist"],
                    "description": f"Gut reaction: {current_genre.replace('_', ' ').title()}",
                    "genre_hint": current_genre.replace("_", " ").title(),
                    "category": current_genre,
                    "album_art": track.get("album_art"),
                    "audio_url": track["preview_url"],   # Direct Spotify 30-sec preview
                    "preview_url": track["preview_url"],
                    "spotify_url": track.get("spotify_url"),
                    "features": track.get("features") or GENRE_FEATURE_PROFILES.get(current_genre, {}),
                })
                break  # Maximize genre diversity: 1 clip per genre first

            genre_idx += 1

        return clips[:count]

    def resolve_folder(self, folder_name: str) -> Optional[Path]:
        if not self.clips_dir or not folder_name:
            return None
        direct = self.clips_dir / folder_name
        if direct.exists() and direct.is_dir():
            return direct
        alias = FOLDER_ALIASES.get(_slug(folder_name))
        if alias:
            aliased = self.clips_dir / alias
            if aliased.exists() and aliased.is_dir():
                return aliased
        return None

    def audio_files(self, folder: Optional[Path]) -> List[Path]:
        if not folder or not folder.exists():
            return []
        return sorted(
            [path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS],
            key=lambda path: path.name.lower(),
        )

    def response_for(self, clip_id: str, session_key: str = "", play_index: int = 0) -> Optional[dict]:
        """Resolve clip response: checks dynamic clips first, then static features."""
        from dynamic_clips import fetch_genre_previews, GENRE_FEATURE_PROFILES
        # 1. If static feature exists in features dict and local files exist, support legacy
        clip_data = self.features.get(clip_id) if self.features else None
        if clip_data and self.clips_dir and self.clips_dir.exists():
            folder_name = clip_data.get("folder") or ""
            folder = self.resolve_folder(folder_name)
            files = self.audio_files(folder)
            if folder and files:
                offset = _stable_int(f"{session_key}|{clip_id}|asset")
                asset_index = (offset + max(0, int(play_index or 0))) % len(files)
                audio_file = files[asset_index]
                audio_url = f"{self.audio_mount}/{quote(folder.name)}/{quote(audio_file.name)}"
                return {
                    "clip_id": clip_id,
                    "title": clip_data.get("title", folder_name),
                    "description": clip_data.get("description", "Rate your gut reaction"),
                    "genre_hint": clip_data.get("genre_hint", ""),
                    "category": folder.name,
                    "asset_index": asset_index,
                    "asset_count": len(files),
                    "audio_url": audio_url,
                    "preview_url": audio_url,
                }

        # 2. Dynamic Spotify preview resolution
        genre = self.genres[play_index % len(self.genres)]
        tracks = fetch_genre_previews(genre, limit=5)
        if not tracks:
            return None
        track = tracks[play_index % len(tracks)]
        return {
            "clip_id": clip_id,
            "title": track["name"],
            "artist": track["artist"],
            "description": f"Rate your reaction: {genre.replace('_', ' ').title()}",
            "genre_hint": genre.replace("_", " ").title(),
            "category": genre,
            "album_art": track.get("album_art"),
            "audio_url": track["preview_url"],
            "preview_url": track["preview_url"],
            "spotify_url": track.get("spotify_url"),
            "features": track.get("features", {}),
        }


# Aliased for backward compatibility with existing tests and main.py
ClipAssetRotator = DynamicClipRotator
