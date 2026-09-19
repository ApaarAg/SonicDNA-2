"""
Controlled offline scenario execution.

Scenarios encode persona/session inputs only. They call the existing
PlaylistGenerator surface and then observe the output using current evaluators.
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional

from evaluation import evaluate_playlist
from flow_evaluation import evaluate_flow
from playlist_generator import PlaylistGenerator

try:
    from explanation_engine import generate_playlist_explanations
except Exception:  # pragma: no cover
    generate_playlist_explanations = None


@dataclass(frozen=True)
class Scenario:
    name: str
    session_type: str = "default"
    genome: Mapping[str, float] = field(default_factory=dict)
    cluster_id: int = 1
    region_key: str = "global_english"
    playlist_size: int = 24
    discovery_ratio: float = 0.35
    exploration_ratio: float = 0.0
    target_minutes: Optional[int] = None
    mood: Optional[str] = None
    taste_profile: Optional[Mapping[str, Any]] = None
    user_tracks: Optional[List[dict]] = None
    description: str = ""


DEFAULT_GENOME = {
    "danceability": 0.56,
    "energy": 0.58,
    "valence": 0.54,
    "acousticness": -0.15,
    "instrumentalness": -0.35,
    "speechiness": -0.45,
    "tempo": 0.0,
}


SCENARIOS: Dict[str, Scenario] = {
    "focus": Scenario(
        name="focus",
        session_type="focus",
        genome={**DEFAULT_GENOME, "energy": 0.38, "valence": 0.5, "acousticness": 0.35},
        discovery_ratio=0.2,
        exploration_ratio=0.05,
        mood="focused",
        description="Low-variance concentration session.",
    ),
    "workout": Scenario(
        name="workout",
        session_type="workout",
        genome={**DEFAULT_GENOME, "danceability": 0.85, "energy": 0.88, "valence": 0.68},
        discovery_ratio=0.35,
        exploration_ratio=0.05,
        mood="energetic",
        description="High-energy movement session.",
    ),
    "emotional": Scenario(
        name="emotional",
        session_type="emotional",
        genome={**DEFAULT_GENOME, "energy": 0.42, "valence": 0.32, "acousticness": 0.25},
        discovery_ratio=0.3,
        exploration_ratio=0.05,
        mood="sad",
        description="Emotional arc and resolution check.",
    ),
    "discovery": Scenario(
        name="discovery",
        session_type="discovery",
        genome={**DEFAULT_GENOME, "energy": 0.62, "valence": 0.58},
        discovery_ratio=0.7,
        exploration_ratio=0.18,
        description="Variety-first controlled discovery.",
    ),
    "conservative_listener": Scenario(
        name="conservative_listener",
        session_type="default",
        discovery_ratio=0.15,
        exploration_ratio=0.0,
        description="Familiarity-heavy listener with minimal exploration.",
    ),
    "adventurous_listener": Scenario(
        name="adventurous_listener",
        session_type="discovery",
        discovery_ratio=0.75,
        exploration_ratio=0.2,
        description="High exploration tolerance and discovery appetite.",
    ),
    "mainstream_heavy_listener": Scenario(
        name="mainstream_heavy_listener",
        session_type="default",
        genome={**DEFAULT_GENOME, "danceability": 0.7, "energy": 0.66, "valence": 0.62},
        discovery_ratio=0.25,
        exploration_ratio=0.03,
        taste_profile={"genres": ["pop", "dance pop"], "top_artists": ["Taylor Swift", "The Weeknd"]},
        description="Popularity-tolerant mainstream profile.",
    ),
    "niche_listener": Scenario(
        name="niche_listener",
        session_type="discovery",
        genome={**DEFAULT_GENOME, "energy": 0.5, "valence": 0.48, "acousticness": 0.2},
        discovery_ratio=0.65,
        exploration_ratio=0.15,
        taste_profile={"genres": ["indie", "alternative", "ambient"], "top_artists": ["Beach House"]},
        description="Lower-mainstream, genre-diverse profile.",
    ),
    "cross_region_discovery_probe": Scenario(
        name="cross_region_discovery_probe",
        session_type="discovery",
        genome={**DEFAULT_GENOME, "energy": 0.64, "valence": 0.56, "danceability": 0.72},
        region_key="india_tamil",
        discovery_ratio=0.75,
        exploration_ratio=0.20,
        mood="festival discovery",
        taste_profile={"genres": ["tamil kuthu", "electronic", "afrobeats"], "top_artists": []},
        description="Stress-test cross-region exploration connectivity without changing recommendation behavior.",
    ),
    "texture_bridge_probe": Scenario(
        name="texture_bridge_probe",
        session_type="night_drive",
        genome={**DEFAULT_GENOME, "energy": 0.54, "valence": 0.42, "acousticness": -0.45, "instrumentalness": 0.55},
        region_key="global_english",
        discovery_ratio=0.65,
        exploration_ratio=0.18,
        mood="nocturnal atmospheric",
        taste_profile={"genres": ["ambient electronic", "synthwave", "indie folk"], "top_artists": []},
        description="Stress-test cross-genre retrieval where texture coherence should carry discovery.",
    ),
    "long_horizon_drift_probe": Scenario(
        name="long_horizon_drift_probe",
        session_type="discovery",
        genome={**DEFAULT_GENOME, "energy": 0.60, "valence": 0.52, "danceability": 0.66},
        region_key="global_english",
        discovery_ratio=0.80,
        exploration_ratio=0.20,
        mood="wide discovery",
        taste_profile={"genres": ["indie", "electronic", "latin", "afrobeats"], "top_artists": []},
        description="Repeated-run probe for semantic corridor and attractor recurrence across sessions.",
    ),
    "novelty_sustainability_probe": Scenario(
        name="novelty_sustainability_probe",
        session_type="discovery",
        genome={**DEFAULT_GENOME, "energy": 0.50, "valence": 0.50, "acousticness": 0.10},
        region_key="global_english",
        discovery_ratio=0.70,
        exploration_ratio=0.18,
        mood="sustainable discovery",
        taste_profile={"genres": ["ambient", "folk", "regional pop", "dance"], "top_artists": []},
        description="Repeated-run probe for novelty decay and repeated bridge-region reuse.",
    ),
    "topology_permeability_probe": Scenario(
        name="topology_permeability_probe",
        session_type="discovery",
        genome={**DEFAULT_GENOME, "energy": 0.58, "valence": 0.54, "danceability": 0.68},
        region_key="india_tamil",
        discovery_ratio=0.78,
        exploration_ratio=0.20,
        mood="permeable discovery",
        taste_profile={"genres": ["tamil", "afrobeats", "latin", "j-pop"], "top_artists": []},
        description="Offline stress-test for cross-family exploration diversity and regional permeability balance.",
    ),
    "macro_family_shortcut_probe": Scenario(
        name="macro_family_shortcut_probe",
        session_type="discovery",
        genome={**DEFAULT_GENOME, "energy": 0.64, "valence": 0.58, "danceability": 0.74},
        region_key="india_tamil",
        discovery_ratio=0.80,
        exploration_ratio=0.20,
        mood="macro family shortcut",
        taste_profile={"genres": ["tamil", "punjabi", "hindi", "bollywood"], "top_artists": []},
        description="Offline stress-test for macro-family over-concentration and bridge-genre over-reliance.",
    ),
    "perceived_discovery_quality_probe": Scenario(
        name="perceived_discovery_quality_probe",
        session_type="discovery",
        genome={**DEFAULT_GENOME, "energy": 0.58, "valence": 0.52, "danceability": 0.66},
        region_key="global_english",
        discovery_ratio=0.72,
        exploration_ratio=0.20,
        mood="meaningful discovery",
        taste_profile={"genres": ["indie", "regional pop", "afrobeats", "folk"], "top_artists": []},
        description="Offline human-review probe for fake novelty versus meaningful discovery.",
    ),
    "emotional_realism_probe": Scenario(
        name="emotional_realism_probe",
        session_type="emotional",
        genome={**DEFAULT_GENOME, "energy": 0.40, "valence": 0.34, "acousticness": 0.30},
        region_key="global_english",
        discovery_ratio=0.35,
        exploration_ratio=0.06,
        mood="emotionally realistic",
        taste_profile={"genres": ["singer-songwriter", "indie folk", "ambient pop"], "top_artists": []},
        description="Offline human-review probe for over-smoothed or artificial emotional arcs.",
    ),
    "memorability_probe": Scenario(
        name="memorability_probe",
        session_type="discovery",
        genome={**DEFAULT_GENOME, "energy": 0.56, "valence": 0.50, "danceability": 0.58},
        region_key="global_english",
        discovery_ratio=0.58,
        exploration_ratio=0.14,
        mood="memorable but coherent",
        taste_profile={"genres": ["alternative", "left-field pop", "global indie"], "top_artists": []},
        description="Offline human-review probe for playlists that score healthy but are forgettable.",
    ),
    "subjective_coherence_probe": Scenario(
        name="subjective_coherence_probe",
        session_type="night_drive",
        genome={**DEFAULT_GENOME, "energy": 0.48, "valence": 0.42, "instrumentalness": 0.35},
        region_key="global_english",
        discovery_ratio=0.62,
        exploration_ratio=0.16,
        mood="coherent discovery",
        taste_profile={"genres": ["ambient electronic", "indie", "soul", "regional pop"], "top_artists": []},
        description="Offline human-review probe for subjective coherence under varied discovery.",
    ),
}


def list_scenarios() -> List[dict]:
    return [asdict(scenario) for scenario in SCENARIOS.values()]


def _resolve_scenario(scenario: str | Scenario | Mapping[str, Any]) -> Scenario:
    if isinstance(scenario, Scenario):
        return scenario
    if isinstance(scenario, str):
        key = scenario.strip().lower()
        if key not in SCENARIOS:
            raise KeyError(f"Unknown calibration scenario: {scenario}")
        return SCENARIOS[key]
    return Scenario(**dict(scenario))


def run_scenario(
    scenario: str | Scenario | Mapping[str, Any],
    *,
    generator: Optional[Any] = None,
    spotify_service: Optional[Any] = None,
    overrides: Optional[Mapping[str, Any]] = None,
    include_explanations: bool = True,
) -> dict:
    """Run one controlled playlist scenario and return observed metrics."""
    resolved = _resolve_scenario(scenario)
    data = asdict(resolved)
    data.update(dict(overrides or {}))
    generator = generator or PlaylistGenerator(spotify_service=spotify_service)

    playlist = generator.generate_regional_genome_playlist(
        user_tracks=copy.deepcopy(data.get("user_tracks") or []),
        genome=dict(data["genome"]),
        cluster_id=int(data["cluster_id"]),
        region_key=str(data["region_key"]),
        playlist_size=int(data["playlist_size"]),
        discovery_ratio=float(data["discovery_ratio"]),
        target_minutes=data.get("target_minutes"),
        mood=data.get("mood"),
        taste_profile=copy.deepcopy(data.get("taste_profile")),
        user_embedding=data.get("user_embedding"),
        exploration_ratio=float(data["exploration_ratio"]),
        include_explanations=include_explanations,
        session_type=str(data["session_type"]),
    )

    tracks = playlist.get("tracks", [])
    if include_explanations and generate_playlist_explanations is not None and "recommendation_explanations" not in playlist:
        playlist["recommendation_explanations"] = generate_playlist_explanations(
            tracks,
            taste_profile=data.get("taste_profile"),
            requested_mood=data.get("mood"),
        )

    return {
        "scenario": {
            "name": data["name"],
            "description": data.get("description", ""),
            "session_type": data["session_type"],
            "region_key": data["region_key"],
            "cluster_id": data["cluster_id"],
            "discovery_ratio": data["discovery_ratio"],
            "exploration_ratio": data["exploration_ratio"],
            "mood": data.get("mood"),
        },
        "playlist": playlist,
        "evaluation": evaluate_playlist(tracks, user_embedding=data.get("user_embedding")),
        "flow_report": evaluate_flow(tracks, session_type=data["session_type"]),
    }


def run_scenarios(
    scenarios: Iterable[str | Scenario | Mapping[str, Any]],
    *,
    generator: Optional[Any] = None,
    spotify_service: Optional[Any] = None,
    overrides: Optional[Mapping[str, Any]] = None,
) -> List[dict]:
    return [
        run_scenario(
            scenario,
            generator=generator,
            spotify_service=spotify_service,
            overrides=overrides,
        )
        for scenario in scenarios
    ]
