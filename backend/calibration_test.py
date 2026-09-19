import copy
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from calibration.benchmark_runner import run_ab_benchmark, run_stability_benchmark
from calibration.human_perception import (
    PERCEPTUAL_STRESS_TEST_SCENARIOS,
    analyze_human_perception,
    normalize_human_review,
    summarize_human_reviews,
)
from calibration.playlist_diff import compare_playlists, compare_repeated_runs
from calibration.scenario_runner import SCENARIOS, run_scenario


def _tracks(offset=0.0):
    return [
        {
            "id": f"t{i}",
            "name": f"Track {i}",
            "artist": f"Artist {i % 3}",
            "popularity": 70 - i,
            "energy": min(1.0, 0.35 + offset + i * 0.04),
            "valence": min(1.0, 0.45 + offset + i * 0.03),
            "danceability": 0.5,
            "tempo": 105 + i,
            "source": "discovery" if i % 4 == 0 else "library",
            "genres": ["pop" if i % 2 else "indie"],
            "recommendation_trace": {"semantic_similarity": 0.7 - i * 0.01},
        }
        for i in range(10)
    ]


def _balance_tracks(identity_dominant=False):
    if identity_dominant:
        rows = [
            ("i1", "India Pulse", "india_tamil", ["tamil kuthu"], 0.08, 0.84, [1.0, 0.0]),
            ("i2", "India Room", "india_tamil", ["tamil kuthu"], 0.84, 0.02, [0.99, 0.01]),
            ("b1", "Brazil Pulse", "brazil", ["baile funk"], 0.10, 0.82, [0.82, 0.18]),
            ("b2", "Brazil Room", "brazil", ["baile funk"], 0.86, 0.01, [0.18, 0.82]),
        ]
    else:
        rows = [
            ("i1", "India Pulse", "india_tamil", ["tamil kuthu"], 0.08, 0.84, [1.0, 0.0]),
            ("b1", "Brazil Pulse", "brazil", ["baile funk"], 0.10, 0.82, [0.99, 0.01]),
            ("f1", "India Room", "india_tamil", ["indie folk"], 0.84, 0.02, [0.0, 1.0]),
            ("j1", "Japan Room", "japan", ["japanese acoustic"], 0.86, 0.01, [0.01, 0.99]),
        ]
    tracks = []
    for track_id, name, region, genres, acousticness, instrumentalness, embedding in rows:
        tracks.append(
            {
                "id": track_id,
                "name": name,
                "artist": f"Artist {track_id}",
                "region": region,
                "genres": genres,
                "energy": 0.58,
                "valence": 0.54,
                "danceability": 0.62,
                "tempo": 112,
                "acousticness": acousticness,
                "instrumentalness": instrumentalness,
                "speechiness": 0.04,
                "_embedding": embedding,
            }
        )
    base_region = tracks[0]["region"]
    exploration_index = next(
        (index for index, track in enumerate(tracks) if track["region"] != base_region),
        len(tracks) - 1,
    )
    tracks[exploration_index]["exploration"] = True
    tracks[exploration_index]["exploration_meta"] = {"semantic_relatedness": 0.72, "bridge_score": 0.8}
    return tracks


def _embedding(track):
    return track.get("_embedding")


def _long_horizon_playlist(session_index, corridor_region="brazil", archetype_genre="baile funk", popularity=35):
    base = [
        {
            "id": f"s{session_index}-base-{i}",
            "name": f"Base {i}",
            "artist": f"Base Artist {i}",
            "region": "india_tamil",
            "genres": ["tamil kuthu"],
            "popularity": 72 - i,
            "energy": 0.62,
            "valence": 0.58,
            "danceability": 0.74,
            "tempo": 124,
        }
        for i in range(3)
    ]
    explore = {
        "id": f"s{session_index}-explore",
        "name": f"Explore {session_index}",
        "artist": f"Discovery Artist {session_index}",
        "region": corridor_region,
        "genres": [archetype_genre],
        "popularity": popularity,
        "energy": 0.66,
        "valence": 0.57,
        "danceability": 0.78,
        "tempo": 126,
        "acousticness": 0.12,
        "instrumentalness": 0.1,
        "exploration": True,
        "source": "discovery",
        "exploration_meta": {
            "semantic_relatedness": 0.72,
            "bridge_score": 0.8,
            "graph_distance": 2,
        },
    }
    return {"tracks": base + [explore]}


def _topology_playlist(
    session_index,
    *,
    base_region="india_tamil",
    base_region_family="south_asia",
    base_family="south-asian-pop",
    explore_region="india_punjabi",
    explore_region_family="south_asia",
    explore_genre="bhangra",
    explore_family="south-asian-pop",
    bridge_score=0.82,
    relatedness=0.72,
):
    base = [
        {
            "id": f"topo-{session_index}-base-{i}",
            "name": f"Base {i}",
            "artist": f"Base Artist {i}",
            "region": base_region,
            "region_family": base_region_family,
            "genres": ["tamil"],
            "genre_families": [base_family],
            "energy": 0.62,
            "valence": 0.58,
            "danceability": 0.74,
            "tempo": 124,
        }
        for i in range(3)
    ]
    explore = {
        "id": f"topo-{session_index}-explore",
        "name": f"Explore {session_index}",
        "artist": f"Discovery Artist {session_index}",
        "region": explore_region,
        "region_family": explore_region_family,
        "genres": [explore_genre],
        "genre_families": [explore_family],
        "popularity": 38,
        "energy": 0.66,
        "valence": 0.57,
        "danceability": 0.78,
        "tempo": 126,
        "acousticness": 0.12,
        "instrumentalness": 0.08,
        "exploration": True,
        "source": "discovery",
        "exploration_meta": {
            "semantic_relatedness": relatedness,
            "bridge_score": bridge_score,
            "graph_distance": 2,
        },
    }
    return {"tracks": base + [explore]}


def _perceptual_playlist(*, bridge_score=0.12, relatedness=0.18, popularity=18, flat=True):
    tracks = []
    for i in range(10):
        exploration = i in {2, 5, 8}
        tracks.append(
            {
                "id": f"perceptual-{i}",
                "name": f"Perceptual {i}",
                "artist": f"Artist {i}",
                "region": "global_english" if not exploration else f"region_{i}",
                "genres": ["indie pop" if not exploration else "obscure regional pop"],
                "popularity": popularity if exploration else 68,
                "energy": 0.55 if flat else 0.35 + i * 0.05,
                "valence": 0.52 if flat else 0.40 + (i % 4) * 0.08,
                "danceability": 0.6,
                "tempo": 112,
                "source": "discovery" if exploration else "library",
                "exploration": exploration,
                "exploration_meta": {
                    "bridge_score": bridge_score,
                    "semantic_relatedness": relatedness,
                    "graph_distance": 3,
                } if exploration else {},
                "recommendation_trace": {"semantic_similarity": 0.74},
            }
        )
    return {"tracks": tracks}


class StubGenerator:
    def __init__(self, label, offset=0.0):
        self.label = label
        self.offset = offset
        self.calls = []

    def generate_regional_genome_playlist(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        tracks = _tracks(self.offset)
        if kwargs.get("exploration_ratio", 0) > 0:
            tracks[-1]["exploration"] = True
        return {
            "name": self.label,
            "tracks": tracks,
            "size": len(tracks),
            "config_label": self.label,
        }


def test_compare_playlists_returns_overlap_flow_diversity_and_semantic_sections():
    report = compare_playlists(
        {"tracks": _tracks(0.0)},
        {"tracks": _tracks(0.08)[2:]},
        session_type="focus",
    )

    assert report["playlist_overlap"] < 1.0
    assert "flow_quality_delta" in report
    assert "diversity_delta" in report
    assert "semantic_consistency" in report
    assert "recommendation_stability" in report
    assert "semantic_balance" in report


def test_compare_playlists_reports_embedding_semantic_balance_metrics():
    report = compare_playlists(
        {"tracks": _balance_tracks(False)},
        {"tracks": _balance_tracks(True)},
        track_embedding_fn=_embedding,
    )
    balance = report["semantic_balance"]["config_a"]

    assert balance["embedding_coverage"] == 1.0
    assert balance["embedding_neighborhood_diversity"] > 0.2
    assert balance["cross_region_discovery_connectivity"] == 1.0
    assert balance["cross_genre_texture_coherent_retrieval"] >= 0.75
    assert "semantic_balance.embedding_neighborhood_diversity" in report["metric_deltas"]


def test_semantic_balance_detects_identity_dominance_and_texture_underuse():
    report = compare_playlists(
        {"tracks": _balance_tracks(False)},
        {"tracks": _balance_tracks(True)},
        track_embedding_fn=_embedding,
    )
    dominant = report["semantic_balance"]["config_b"]

    assert dominant["identity_neighbor_share"] >= 0.75
    assert dominant["identity_overdominance_score"] > 0.4
    assert dominant["texture_underutilization_score"] > 0.2
    assert dominant["semantic_basin_collapse_score"] > 0.4
    assert "identity_overdominance" in dominant["flags"]


def test_run_scenario_passes_controlled_profile_to_generator():
    generator = StubGenerator("A")
    result = run_scenario("workout", generator=generator)

    assert result["scenario"]["name"] == "workout"
    assert result["playlist"]["size"] == 10
    assert generator.calls[0]["session_type"] == SCENARIOS["workout"].session_type
    assert generator.calls[0]["exploration_ratio"] == SCENARIOS["workout"].exploration_ratio


def test_calibration_includes_semantic_balance_stress_scenarios():
    assert "cross_region_discovery_probe" in SCENARIOS
    assert "texture_bridge_probe" in SCENARIOS
    assert "long_horizon_drift_probe" in SCENARIOS
    assert "novelty_sustainability_probe" in SCENARIOS
    assert "topology_permeability_probe" in SCENARIOS
    assert "macro_family_shortcut_probe" in SCENARIOS


def test_calibration_includes_perceptual_stress_scenarios():
    assert set(PERCEPTUAL_STRESS_TEST_SCENARIOS).issubset(SCENARIOS)
    assert "perceived_discovery_quality_probe" in SCENARIOS
    assert "emotional_realism_probe" in SCENARIOS
    assert "memorability_probe" in SCENARIOS


def test_compare_repeated_runs_reports_long_horizon_exploration_drift():
    playlists = [
        _long_horizon_playlist(0, "brazil", "baile funk", 42),
        _long_horizon_playlist(1, "brazil", "baile funk", 48),
        _long_horizon_playlist(2, "brazil", "baile funk", 56),
        _long_horizon_playlist(3, "brazil", "baile funk", 62),
    ]

    report = compare_repeated_runs(playlists, session_type="discovery")
    horizon = report["long_horizon_exploration"]

    assert horizon["session_count"] == 4
    assert horizon["exploration_session_coverage"] == 1.0
    assert horizon["cross_session_exploration_diversity"] == 1.0
    assert horizon["semantic_corridor_reuse_score"] == 1.0
    assert horizon["recurring_exploration_archetype_score"] == 1.0
    assert horizon["bridge_region_reuse_score"] == 1.0
    assert horizon["novelty_decay"] > 0
    assert horizon["long_term_semantic_attractor_score"] == 1.0
    assert "semantic_corridor_reuse" in horizon["flags"]
    assert "novelty_decay" in horizon["flags"]


def test_compare_repeated_runs_rewards_sustainable_discovery_spread():
    playlists = [
        _long_horizon_playlist(0, "brazil", "baile funk", 38),
        _long_horizon_playlist(1, "japan", "city pop", 36),
        _long_horizon_playlist(2, "nigeria", "afrobeats", 34),
        _long_horizon_playlist(3, "latin", "reggaeton", 35),
    ]

    horizon = compare_repeated_runs(playlists, session_type="discovery")["long_horizon_exploration"]

    assert horizon["semantic_corridor_reuse_score"] <= 0.25
    assert horizon["bridge_region_reuse_score"] <= 0.25
    assert horizon["recurring_exploration_archetype_score"] <= 0.25
    assert horizon["novelty_decay"] <= 0
    assert horizon["flags"] == []


def test_compare_repeated_runs_reports_topology_behavior_metrics():
    playlists = [
        _topology_playlist(0, explore_region="india_punjabi", explore_region_family="south_asia", explore_family="south-asian-pop", explore_genre="bhangra"),
        _topology_playlist(1, explore_region="india_hindi", explore_region_family="south_asia", explore_family="south-asian-pop", explore_genre="bollywood"),
        _topology_playlist(2, explore_region="india_punjabi", explore_region_family="south_asia", explore_family="south-asian-pop", explore_genre="punjabi"),
        _topology_playlist(3, explore_region="india_hindi", explore_region_family="south_asia", explore_family="south-asian-pop", explore_genre="hindi"),
    ]

    topology = compare_repeated_runs(playlists, session_type="discovery")["topology_diagnostics"]

    assert topology["cross_family_exploration_diversity"] == 0.25
    assert topology["macro_family_overconcentration_score"] == 1.0
    assert topology["bridge_genre_overreliance_score"] == 1.0
    assert topology["regional_permeability_balance"] == 1.0
    assert topology["semantic_shortcut_collapse_score"] >= 0.7
    assert topology["culturally_meaningful_crossover_quality"] >= 0.7
    assert "macro_family_overconcentration" in topology["flags"]
    assert "bridge_genre_overreliance" in topology["flags"]
    assert "semantic_shortcut_collapse" in topology["flags"]


def test_compare_repeated_runs_rewards_permeable_multi_family_topology():
    playlists = [
        _topology_playlist(0, explore_region="brazil", explore_region_family="latin_america", explore_family="latin-dance", explore_genre="funk brasileiro"),
        _topology_playlist(1, explore_region="nigeria", explore_region_family="west_africa", explore_family="afro-pop", explore_genre="afrobeats"),
        _topology_playlist(2, explore_region="japan", explore_region_family="east_asia", explore_family="east-asian-pop", explore_genre="j-pop"),
        _topology_playlist(3, explore_region="arab_world", explore_region_family="arabic_world", explore_family="arabic-pop", explore_genre="arabic"),
    ]

    topology = compare_repeated_runs(playlists, session_type="discovery")["topology_diagnostics"]

    assert topology["cross_family_exploration_diversity"] == 1.0
    assert topology["macro_family_overconcentration_score"] <= 0.25
    assert topology["bridge_genre_overreliance_score"] <= 0.25
    assert topology["semantic_shortcut_collapse_score"] <= 0.25
    assert topology["culturally_meaningful_crossover_quality"] >= 0.7
    assert topology["flags"] == []


def test_ab_benchmark_returns_required_structured_report_shape():
    report = run_ab_benchmark(
        config_a={"label": "baseline", "generator": StubGenerator("A", 0.0)},
        config_b={"label": "candidate", "generator": StubGenerator("B", 0.1)},
        scenario_names=["focus"],
    )

    focus = report["scenario_reports"][0]
    assert set(["config_a", "config_b", "metric_deltas", "playlist_overlap"]).issubset(focus)
    assert "flow_quality_delta" in focus
    assert "diversity_delta" in focus
    assert "semantic_balance" in focus
    assert "regression_detection" in report


def test_stability_benchmark_includes_long_horizon_exploration_section():
    report = run_stability_benchmark(
        config={"label": "stable", "generator": StubGenerator("A")},
        scenario_name="discovery",
        repetitions=2,
    )

    assert "long_horizon_exploration" in report
    assert "topology_diagnostics" in report


def test_human_review_schema_normalizes_ratings_and_summarizes_dimensions():
    review = normalize_human_review(
        {
            "playlist_id": "offline-run-1",
            "reviewer_id": "r1",
            "overall_quality": 4,
            "discovery_magic": 2,
            "emotional_realism": 1,
            "memorability": 3,
            "subjective_coherence": 5,
            "perceived_novelty": 2,
            "rating_scale": 5,
            "notes": "Technically smooth but forgettable.",
        }
    )
    summary = summarize_human_reviews([review])

    assert review["ratings"]["overall_quality"] == 0.8
    assert review["ratings"]["emotional_realism"] == 0.2
    assert summary["review_count"] == 1
    assert summary["average_ratings"]["subjective_coherence"] == 1.0
    assert "emotional_realism" in summary["low_dimensions"]


def test_human_perception_flags_metric_disagreement_and_emotional_weakness_without_mutation():
    playlist = _perceptual_playlist(flat=True)
    original = copy.deepcopy(playlist)

    report = analyze_human_perception(
        playlist,
        [
            {
                "reviewer_id": "r1",
                "overall_quality": 2,
                "discovery_magic": 2,
                "emotional_realism": 1,
                "memorability": 2,
                "subjective_coherence": 4,
                "perceived_novelty": 2,
                "rating_scale": 5,
            }
        ],
        session_type="discovery",
    )

    flags = set(report["disagreement_diagnostics"]["flags"])
    assert report["mode"] == "offline_human_perception_calibration_only"
    assert "technically_healthy_but_emotionally_weak" in flags
    assert "over_smoothed_emotional_arc" in flags
    assert "metric_human_disagreement" in flags
    assert playlist == original


def test_human_perception_flags_fake_novelty_and_artificial_exploration():
    report = analyze_human_perception(
        _perceptual_playlist(bridge_score=0.05, relatedness=0.1, popularity=12, flat=False),
        [
            {
                "reviewer_id": "r1",
                "overall_quality": 3,
                "discovery_magic": 1,
                "emotional_realism": 3,
                "memorability": 2,
                "subjective_coherence": 2,
                "perceived_novelty": 1,
                "rating_scale": 5,
            }
        ],
        session_type="discovery",
    )

    diagnostics = report["disagreement_diagnostics"]
    flags = set(diagnostics["flags"])

    assert "fake_novelty" in flags
    assert "artificial_feeling_exploration" in flags
    assert any(item["dimension"] == "discovery_magic" for item in diagnostics["dimension_disagreements"])
    assert report["metric_reasoning"]["perceived_discovery_quality"]
