import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))

import exploration_engine
from track_graph import TrackGraph, _genre_overlap, _regional_overlap


def test_track_graph_uses_genre_families_for_alias_adjacency_without_exact_collapse():
    left = {"genres": ["afrobeats"], "genre_families": ["afro-pop"]}
    right = {"genres": ["afropop"], "genre_families": ["afro-pop"]}
    unrelated = {"genres": ["singer-songwriter"], "genre_families": ["folk-acoustic"]}

    assert _genre_overlap(left, right) > 0.0
    assert _genre_overlap(left, right) < 1.0
    assert _genre_overlap(left, unrelated) == 0.0


def test_track_graph_rewards_regional_crossover_less_than_exact_region():
    tamil = {"region": "india_tamil", "region_family": "south_asia"}
    punjabi = {"region": "india_punjabi", "region_family": "south_asia"}
    exact = {"region": "india_tamil", "region_family": "south_asia"}
    global_track = {"region": "global_english", "region_family": "global"}

    assert _regional_overlap(tamil, exact) == 1.0
    assert 0.0 < _regional_overlap(tamil, punjabi) < 1.0
    assert _regional_overlap(tamil, global_track) == 0.0


def test_track_graph_build_connects_related_crossover_neighbors():
    tracks = [
        {
            "id": "tamil",
            "name": "Tamil Pulse",
            "artist": "Artist A",
            "genres": ["tamil"],
            "genre_families": ["south-asian-pop"],
            "region": "india_tamil",
            "region_family": "south_asia",
        },
        {
            "id": "punjabi",
            "name": "Punjabi Pulse",
            "artist": "Artist B",
            "genres": ["bhangra"],
            "genre_families": ["south-asian-pop"],
            "region": "india_punjabi",
            "region_family": "south_asia",
        },
    ]
    graph = TrackGraph(top_k=2).build(tracks, [np.array([1.0, 0.0]), np.array([0.98, 0.02])])

    related = graph.get_related_tracks("tamil")

    assert related
    assert related[0]["id"] == "punjabi"


def test_exploration_community_uses_canonical_genre_to_reduce_alias_fragmentation():
    left = {"region": "nigeria", "genres": ["Afro Beats"]}
    right = {"region": "nigeria", "genres": ["afrobeats"]}

    assert exploration_engine._community(left) == exploration_engine._community(right)
