import json
import hashlib
import os
import uuid
import datetime
from typing import List, Optional, Dict, Any
import requests

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app_database import get_db, User
from models.recommendation_models import SpotifySearchCache, RecommendationCache
from genome_evolution import GenomeSnapshot
from gemini_service import GeminiService as LocalLLMClient
from spotify_service_fixed import SpotifyService
from app_database import get_user_spotify_tracks

router = APIRouter(prefix="/recommendations", tags=["Recommendations"])

# ── Pydantic Request/Response Models ──────────────────────────────────────────

class RecRequest(BaseModel):
    user_id: str
    mood: Optional[str] = None
    intent: Optional[str] = "discovery"  # "discovery" | "familiarity" | "balanced"
    discovery_ratio: float = Field(0.5, ge=0.0, le=1.0)
    exploration_ratio: float = Field(0.1, ge=0.0, le=0.2)
    use_cache: bool = True

class TrackRecommendation(BaseModel):
    spotify_uri: str
    track_name: str
    artist_name: str
    popularity: int
    reason: str
    genre: Optional[str] = "ambient"
    duration_ms: Optional[int] = 180000
    preview_url: Optional[str] = None
    album_image: Optional[str] = None
    spotify_url: Optional[str] = None

class RecResponse(BaseModel):
    recommendation_id: str
    user_id: str
    archetype: str
    tracks: List[TrackRecommendation]
    narrative: str
    cached: bool

# ── Service Layer ────────────────────────────────────────────────────────────

class RecommendationService:
    def __init__(self, db: Session):
        self.db = db
        self.local_llm = LocalLLMClient(db)
        try:
            self.spotify = SpotifyService()
        except Exception as e:
            print(f"[recommendations.spotify_error] Initializing dummy/disabled Spotify: {e}")
            self.spotify = None

    def _get_context_key(self, req: RecRequest) -> str:
        """Generate a stable cache key based on request context."""
        parts = [
            f"mood={req.mood or 'none'}",
            f"intent={req.intent}",
            f"disc={round(req.discovery_ratio, 2)}",
            f"exp={round(req.exploration_ratio, 2)}"
        ]
        return ":".join(parts)

    def _get_query_hash(self, artist: str, track: str) -> str:
        """Generate a SHA256 hash for search query caching."""
        normalized = f"{artist.strip().lower()}|{track.strip().lower()}"
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _resolve_cached_track(self, artist: str, track: str) -> Optional[Dict[str, Any]]:
        """Look up a track in the local Spotify Search cache."""
        qh = self._get_query_hash(artist, track)
        cached = self.db.query(SpotifySearchCache).filter(
            SpotifySearchCache.query_hash == qh,
            SpotifySearchCache.expires_at > datetime.datetime.utcnow()
        ).first()
        
        if cached:
            features = json.loads(cached.audio_features) if cached.audio_features else {}
            return {
                "id": cached.spotify_id,
                "uri": cached.spotify_uri,
                "name": cached.track_name,
                "artist": cached.artist_name,
                "popularity": cached.popularity,
                "duration_ms": cached.duration_ms,
                "preview_url": cached.preview_url,
                "album_image": features.get("album_image"),
                "spotify_url": features.get("spotify_url"),
                "audio_features": features
            }
        return None

    def _cache_track(self, query_artist: str, query_track: str, track_data: Dict[str, Any]):
        """Save a validated track to the local Spotify Search cache (30-day TTL)."""
        qh = self._get_query_hash(query_artist, query_track)
        
        # Expiry is 30 days
        expiry = datetime.datetime.utcnow() + datetime.timedelta(days=30)
        
        features = track_data.get("audio_features", {})
        if not isinstance(features, dict):
            features = {}
        features["album_image"] = track_data.get("album_image")
        features["spotify_url"] = track_data.get("spotify_url")
        
        cache_entry = SpotifySearchCache(
            query_hash=qh,
            search_query=f"{query_artist} - {query_track}",
            spotify_id=track_data["id"],
            spotify_uri=track_data["uri"],
            track_name=track_data["name"],
            artist_name=track_data["artist"],
            popularity=track_data.get("popularity", 0),
            duration_ms=track_data.get("duration_ms", 0),
            preview_url=track_data.get("preview_url"),
            audio_features=json.dumps(features),
            expires_at=expiry
        )
        try:
            self.db.merge(cache_entry)
            self.db.commit()
        except Exception as e:
            self.db.rollback()
            print(f"[recommendations.cache_track_error] error={e}")

    def _validate_candidates(self, candidates: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        """Validate candidate songs against Spotify search, using the database cache when possible."""
        validated = []
        remaining_candidates = []

        # 1. First, check cache for all candidates
        for c in candidates:
            artist = c.get("artist_name", "").strip()
            track = c.get("track_name", "").strip()
            if not artist or not track:
                continue

            cached = self._resolve_cached_track(artist, track)
            if cached:
                validated.append(cached)
            else:
                remaining_candidates.append(c)

        # 2. If Spotify is not available, return mock tracks for the remaining ones
        if not self.spotify:
            for idx, c in enumerate(remaining_candidates[:25]):
                validated.append({
                    "id": f"mock_id_{idx}",
                    "uri": f"spotify:track:mock_uri_{idx}",
                    "name": c["track_name"],
                    "artist": c["artist_name"],
                    "popularity": 45 + (idx % 20),
                    "duration_ms": 180000,
                    "preview_url": None,
                    "album_image": None,
                    "spotify_url": f"https://open.spotify.com/track/mock_uri_{idx}",
                    "audio_features": {"danceability": 0.5, "energy": 0.6, "valence": 0.4}
                })
            return validated

        # 3. Query Spotify API for cache misses
        for c in remaining_candidates:
            artist = c.get("artist_name", "").strip()
            track = c.get("track_name", "").strip()

            try:
                # Use track & artist query format to be specific
                query_str = f"track:{track} artist:{artist}"
                # Call search page helper (limit=1)
                results = self.spotify._search_tracks_page(query_str, market="US", limit=1)
                if results:
                    spotify_track = results[0]
                    # Format matching spotify_service_fixed
                    artists_names = ", ".join([a["name"] for a in spotify_track.get("artists", [])])
                    
                    # Extract album image and Spotify URL
                    album = spotify_track.get("album") or {}
                    images = album.get("images") or []
                    album_image = images[0].get("url") if images and isinstance(images[0], dict) else None
                    spotify_url = spotify_track.get("external_urls", {}).get("spotify", "")

                    formatted = {
                        "id": spotify_track["id"],
                        "uri": spotify_track["uri"],
                        "name": spotify_track["name"],
                        "artist": artists_names,
                        "popularity": spotify_track.get("popularity", 0),
                        "duration_ms": spotify_track.get("duration_ms", 0),
                        "preview_url": spotify_track.get("preview_url"),
                        "album_image": album_image,
                        "spotify_url": spotify_url
                    }
                    
                    # Fetch audio features in a batch/single mode
                    features_list = self.spotify._fetch_audio_features_batch([formatted])
                    formatted["audio_features"] = features_list[0].get("proxy_features", {}) if features_list else {}

                    # Cache verified track details
                    self._cache_track(artist, track, formatted)
                    validated.append(formatted)
            except Exception as e:
                print(f"[recommendations.search_failed] artist='{artist}' track='{track}' error={e}")
                # Fallback to mock track on API exception
                mock_track = {
                    "id": f"mock_id_{self._get_query_hash(artist, track)[:8]}",
                    "uri": f"spotify:track:mock_uri_{self._get_query_hash(artist, track)[:8]}",
                    "name": track,
                    "artist": artist,
                    "popularity": 45,
                    "duration_ms": 180000,
                    "preview_url": None,
                    "album_image": None,
                    "spotify_url": f"https://open.spotify.com/track/mock_uri_{self._get_query_hash(artist, track)[:8]}",
                    "audio_features": {"danceability": 0.5, "energy": 0.6, "valence": 0.4}
                }
                validated.append(mock_track)
                
        return validated

    def _rank_via_openrouter(
        self, 
        genome: Dict[str, float], 
        archetype: str, 
        candidates: List[Dict[str, Any]], 
        discovery_ratio: float
    ) -> List[Dict[str, Any]]:
        """
        Orchestrates final sorting via cloud LLM (OpenRouter).
        Inputs user preferences and track metrics. Avoids popularity bias.
        """
        openrouter_key = os.getenv("OPENROUTER_API_KEY")
        if not openrouter_key:
            print("[recommendations.openrouter] Key missing. Falling back to local scoring.")
            return self._fallback_local_ranker(genome, candidates, discovery_ratio)

        model = os.getenv("OPENROUTER_RECOMMENDATION_MODEL") or os.getenv("OPENROUTER_MODEL") or "google/gemini-2.5-flash"
        
        # Prepare lightweight track representations to stay within low token limit
        tracks_input = []
        for idx, track in enumerate(candidates):
            tracks_input.append({
                "index": idx,
                "name": track["name"],
                "artist": track["artist"],
                "popularity": track["popularity"],
                "audio_features": track.get("audio_features", {})
            })

        system_prompt = (
            "You are the ranking component of the SonicDNA recommendation system. "
            "Your task is to sort a list of candidate songs based on how well they match the user's music genome "
            "and archetype, while avoiding popularity bias and ensuring artist diversity. "
            "Return ONLY a JSON object containing a list called 'ranked_indices' containing the ranked track indices, "
            "and a 'reasons' dictionary mapping the track index to a 1-sentence reason why it matches."
        )

        user_prompt = f"""
        User Profile:
        - Archetype: {archetype}
        - Music Genome Preferences: {json.dumps(genome)}
        - Discovery Ratio: {discovery_ratio} (higher means favor lower popularity tracks, i.e., popularity between 15-55)
        
        Candidate Tracks:
        {json.dumps(tracks_input, indent=2)}
        
        Select and rank the top 20 best-matching tracks.
        Rules:
        1. Diversity: No single artist can appear more than twice.
        2. Discovery: Avoid recommending only highly popular tracks (popularity > 75) unless they are a perfect match. Give preference to tracks with popularity under 60.
        3. Format: Return valid JSON matching schema: {{'ranked_indices': [int], 'reasons': {{'index': 'string'}}}}
        """

        try:
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {openrouter_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "http://localhost",
                    "X-Title": "SonicDNA",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": 0.2,
                    "max_tokens": 1000,
                    "response_format": {"type": "json_object"}
                },
                timeout=12.0
            )
            
            if resp.status_code == 200:
                payload = resp.json()
                content = payload["choices"][0]["message"]["content"]
                # Clean fences
                cleaned = content.strip()
                if "```" in cleaned:
                    cleaned = cleaned.split("```")[1]
                    if cleaned.lower().startswith("json"):
                        cleaned = cleaned[4:]
                
                parsed = json.loads(cleaned)
                ranked_indices = parsed.get("ranked_indices", [])
                reasons = parsed.get("reasons", {})
                
                ranked_tracks = []
                for idx in ranked_indices:
                    if 0 <= idx < len(candidates):
                        track = dict(candidates[idx])
                        track["reason"] = reasons.get(str(idx)) or reasons.get(idx) or "Matches your sonic profile features."
                        ranked_tracks.append(track)
                return ranked_tracks
            else:
                print(f"[recommendations.openrouter_failed] status={resp.status_code} body={resp.text}")
        except Exception as e:
            print(f"[recommendations.openrouter_exception] error={e}")

        # Fallback ranking logic
        return self._fallback_local_ranker(genome, candidates, discovery_ratio)

    def _fallback_local_ranker(self, genome: Dict[str, float], candidates: List[Dict[str, Any]], discovery_ratio: float) -> List[Dict[str, Any]]:
        """Deterministic heuristic fallback when OpenRouter is unreachable."""
        scored = []
        for track in candidates:
            # Basic feature distance (Euclidean distance on matching keys)
            dist = 0.0
            feat = track.get("audio_features") or {}
            match_count = 0
            for k, target_val in genome.items():
                if k in feat and feat[k] is not None:
                    dist += (feat[k] - target_val) ** 2
                    match_count += 1
            
            sim_score = 1.0 - (dist ** 0.5) if match_count > 0 else 0.5
            
            # Discovery score adjustment: penalty for high popularity, bonus for low popularity
            pop = track.get("popularity", 50)
            discovery_factor = 0.0
            if discovery_ratio > 0.5:
                if pop > 75:
                    discovery_factor = -0.2 * discovery_ratio
                elif 15 <= pop <= 55:
                    discovery_factor = 0.15 * discovery_ratio
            
            total_score = sim_score + discovery_factor
            scored.append((total_score, track))
            
        scored.sort(key=lambda x: x[0], reverse=True)
        
        # Select top 20 with artist deduplication (max 2 tracks per artist)
        selected = []
        artist_counts = {}
        for score, track in scored:
            artist = track["artist"].lower()
            if artist_counts.get(artist, 0) < 2:
                track_copy = dict(track)
                track_copy["reason"] = f"Aligned with your taste (score: {score:.2f})."
                selected.append(track_copy)
                artist_counts[artist] = artist_counts.get(artist, 0) + 1
            if len(selected) >= 20:
                break
                
        return selected

    def generate(self, req: RecRequest) -> Dict[str, Any]:
        """Orchestrate the hybrid recommendation pipeline."""
        # 1. Fetch latest user genome snapshot via ORM
        snap = self.db.query(GenomeSnapshot).filter(
            GenomeSnapshot.user_id == req.user_id
        ).order_by(GenomeSnapshot.timestamp.desc()).first()
        
        if not snap:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"User {req.user_id} has no completed genome snapshots. Please complete the quiz first."
            )

        # Parse genome features
        genome = snap.genome_json
        archetype = snap.archetype or "Unknown"
        shadow = snap.shadow_archetype or "Unknown"

        # 2. Check Recommendation Cache
        context_key = self._get_context_key(req)
        if req.use_cache:
            cached_rec = self.db.query(RecommendationCache).filter(
                RecommendationCache.user_id == req.user_id,
                RecommendationCache.context_key == context_key,
                RecommendationCache.expires_at > datetime.datetime.utcnow()
            ).first()
            if cached_rec:
                print(f"[recommendations.cache] hit=true user_id={req.user_id}")
                cached_data = json.loads(cached_rec.recommendations_json)
                cached_data["cached"] = True
                return cached_data

        # 3. Local Model: Archetype Interpretation and Mood Expansion
        interpretation = self.local_llm.interpret_archetype(genome, archetype, shadow)
        target_moods = interpretation.get("target_moods", ["chill", "contemplative"])
        adjacent_genres = interpretation.get("adjacent_genres", ["indie"])

        # 4. Fetch seed tracks for Candidate context
        seed_tracks = get_user_spotify_tracks(req.user_id)

        # 5. Local Model: Candidate Generation
        candidates = self.local_llm.generate_candidates(archetype, target_moods, adjacent_genres, seed_tracks)

        # 6. Spotify search: Validate existence and populate popularity/audio features
        validated_candidates = self._validate_candidates(candidates)

        # 7. OpenRouter: Final ranking and QC filter
        ranked_tracks = self._rank_via_openrouter(genome, archetype, validated_candidates, req.discovery_ratio)

        # 8. Local Model: Narrative description
        narrative = self.local_llm.generate_narrative(snap.user.username if snap.user else "Listener", archetype, ranked_tracks, genome)

        # Resolve a canonical genre for frontend color matching
        canonical_genres = ["ambient", "indie", "electronic", "r&b", "world", "cinematic", "pop", "rock", "jazz", "classical"]
        resolved_genre = "ambient"
        for g in adjacent_genres:
            g_low = g.lower()
            found = False
            for cg in canonical_genres:
                if cg in g_low:
                    resolved_genre = cg
                    found = True
                    break
            if found:
                break

        # 9. Format response payload
        rec_id = str(uuid.uuid4())
        tracks_out = []
        for t in ranked_tracks:
            tracks_out.append({
                "spotify_uri": t["uri"],
                "track_name": t["name"],
                "artist_name": t["artist"],
                "popularity": t["popularity"],
                "reason": t.get("reason", "Aligned with your sonic profile."),
                "genre": resolved_genre,
                "duration_ms": t.get("duration_ms", 180000),
                "preview_url": t.get("preview_url"),
                "album_image": t.get("album_image") or t.get("album_art"),
                "spotify_url": t.get("spotify_url") or t.get("external_url")
            })

        response_payload = {
            "recommendation_id": rec_id,
            "user_id": req.user_id,
            "archetype": archetype,
            "tracks": tracks_out,
            "narrative": narrative,
            "cached": False
        }

        # 10. Cache results (24-hour TTL)
        expiry = datetime.datetime.utcnow() + datetime.timedelta(hours=24)
        cache_entry = RecommendationCache(
            id=rec_id,
            user_id=req.user_id,
            genome_snapshot_id=snap.id,
            context_key=context_key,
            recommendations_json=json.dumps(response_payload),
            expires_at=expiry
        )
        try:
            self.db.add(cache_entry)
            self.db.commit()
        except Exception as e:
            self.db.rollback()
            print(f"[recommendations.cache_rec_error] error={e}")

        return response_payload

# ── API Endpoint Declarations ────────────────────────────────────────────────

@router.post("/generate", response_model=RecResponse, status_code=status.HTTP_200_OK)
def generate_recommendations(payload: RecRequest, db: Session = Depends(get_db)):
    """
    Main recommendation engine endpoint.
    Orchestrates local model generation, Spotify validation, and OpenRouter ranking.
    """
    service = RecommendationService(db)
    result = service.generate(payload)
    return result

@router.delete("/cache/{user_id}", status_code=status.HTTP_200_OK)
def clear_rec_cache(user_id: str, db: Session = Depends(get_db)):
    """Evicts all cached recommendation sets for a specific user."""
    try:
        deleted = db.query(RecommendationCache).filter(RecommendationCache.user_id == user_id).delete()
        db.commit()
        return {"user_id": user_id, "deleted_count": deleted}
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to clear cache: {e}"
        )
