import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from playlist_flow_engine import PlaylistFlowEngine, _transition_distance, _transition_semantics_reward


def _track(idx, energy, valence, artist=None):
    return {
        "id": f"t{idx}",
        "name": f"Track {idx}",
        "artist": artist or f"Artist {idx}",
        "energy": energy,
        "valence": valence,
        "danceability": 0.45 + energy * 0.25,
        "tempo": 90 + energy * 90,
    }


def test_emotional_flow_adds_traceable_contrast_and_recovery_without_abrupt_jumps():
    tracks = [
        _track(0, 0.44, 0.56),
        _track(1, 0.42, 0.54),
        _track(2, 0.43, 0.55),
        _track(3, 0.41, 0.53),
        _track(4, 0.58, 0.42),
        _track(5, 0.62, 0.38),
        _track(6, 0.34, 0.32),
        _track(7, 0.31, 0.29),
        _track(8, 0.47, 0.48),
        _track(9, 0.52, 0.52),
        _track(10, 0.36, 0.36),
        _track(11, 0.50, 0.58),
    ]

    reordered = PlaylistFlowEngine().reorder(tracks, session_type="emotional", protect_top=1)
    traces = [track.get("flow_trace") or {} for track in reordered[1:]]
    arc_roles = {trace.get("arc_role") for trace in traces if trace.get("arc_role")}
    transition_distances = [
        _transition_distance(reordered[i], reordered[i + 1])
        for i in range(len(reordered) - 1)
    ]

    assert "contrast" in arc_roles
    assert "recovery" in arc_roles
    assert max(transition_distances) < 0.35
    assert [track["id"] for track in reordered] == [track["id"] for track in PlaylistFlowEngine().reorder(tracks, session_type="emotional", protect_top=1)]


def test_emotional_flow_breaks_long_flat_runs_before_outro():
    tracks = [_track(0, 0.45, 0.55)]
    tracks.extend(_track(i, 0.36 + (i % 2) * 0.01, 0.31 + (i % 2) * 0.01) for i in range(1, 9))
    tracks.extend([
        _track(9, 0.55, 0.50),
        _track(10, 0.58, 0.45),
        _track(11, 0.48, 0.57),
    ])

    reordered = PlaylistFlowEngine().reorder(tracks, session_type="emotional", protect_top=1)
    traces = [track.get("flow_trace") or {} for track in reordered[1:9]]
    middle_energies = [track["energy"] for track in reordered[2:9]]

    assert any(trace.get("arc_role") == "contrast" for trace in traces)
    assert max(middle_energies) - min(middle_energies) >= 0.10


def test_focus_flow_preserves_low_variance_identity():
    tracks = [_track(i, energy, valence) for i, (energy, valence) in enumerate([
        (0.39, 0.50),
        (0.42, 0.52),
        (0.36, 0.48),
        (0.60, 0.70),
        (0.38, 0.51),
        (0.41, 0.53),
        (0.58, 0.66),
        (0.37, 0.49),
    ])]

    reordered = PlaylistFlowEngine().reorder(tracks, session_type="focus", protect_top=1)
    traces = [track.get("flow_trace") or {} for track in reordered[1:]]

    assert all(trace.get("arc_role") != "contrast" for trace in traces)
    assert reordered[1]["energy"] < 0.5


def test_flow_places_sparse_salient_anchors_without_scripted_structure():
    tracks = [
        _track(0, 0.46, 0.54),
        _track(1, 0.47, 0.55),
        _track(2, 0.49, 0.57),
        _track(3, 0.50, 0.58),
        _track(4, 0.55, 0.62),
        _track(5, 0.63, 0.66),
        _track(6, 0.76, 0.71),
        _track(7, 0.58, 0.50),
        _track(8, 0.40, 0.37),
        _track(9, 0.35, 0.34),
        _track(10, 0.48, 0.52),
        _track(11, 0.53, 0.60),
    ]
    tracks[6].update({"popularity": 96, "quality_score": 0.92})
    tracks[8].update({"exploration": True, "quality_score": 0.88})

    reordered = PlaylistFlowEngine().reorder(tracks, session_type="default", protect_top=1)
    repeated = PlaylistFlowEngine().reorder(tracks, session_type="default", protect_top=1)
    traces = [track.get("flow_trace") or {} for track in reordered[1:]]
    anchor_roles = [trace.get("anchor_role") for trace in traces if trace.get("anchor_role")]
    transition_distances = [
        _transition_distance(reordered[i], reordered[i + 1])
        for i in range(len(reordered) - 1)
    ]

    assert "climax" in anchor_roles
    assert any(role in anchor_roles for role in {"recovery", "release"})
    assert len(anchor_roles) <= 3
    assert max(transition_distances) < 0.35
    assert [track["id"] for track in reordered] == [track["id"] for track in repeated]


def test_flow_penalizes_emotional_monotony_when_a_coherent_pivot_exists():
    tracks = [_track(0, 0.50, 0.55)]
    tracks.extend(_track(i, 0.51 + (i % 2) * 0.01, 0.56 + (i % 2) * 0.01) for i in range(1, 8))
    tracks.extend([
        _track(8, 0.63, 0.61),
        _track(9, 0.45, 0.45),
        _track(10, 0.54, 0.57),
        _track(11, 0.56, 0.58),
    ])

    reordered = PlaylistFlowEngine().reorder(tracks, session_type="default", protect_top=1)
    early_ids = {track["id"] for track in reordered[2:8]}
    early_moods = [(track["energy"], track["valence"]) for track in reordered[1:8]]

    assert {"t8", "t9"} & early_ids
    assert not any(
        max(e for e, _ in early_moods[i:i + 4]) - min(e for e, _ in early_moods[i:i + 4]) < 0.03
        and max(v for _, v in early_moods[i:i + 4]) - min(v for _, v in early_moods[i:i + 4]) < 0.03
        for i in range(len(early_moods) - 3)
    )


def test_transition_semantics_prefers_meaningful_contrast_over_plain_smoothness():
    tracks = [
        _track(0, 0.46, 0.40),
        _track(1, 0.48, 0.41),
        _track(2, 0.50, 0.42),
        _track(3, 0.53, 0.44),
        _track(4, 0.58, 0.57),
        _track(5, 0.62, 0.62),
        _track(6, 0.64, 0.66),
        _track(7, 0.45, 0.43),
    ]
    tracks[4]["danceability"] = tracks[3]["danceability"] + 0.01
    tracks[4]["tempo"] = tracks[3]["tempo"] + 2
    tracks[5]["danceability"] = 0.88
    tracks[5]["tempo"] = 160

    reordered = PlaylistFlowEngine().reorder(tracks, session_type="default", protect_top=1)
    traces = [track.get("flow_trace") or {} for track in reordered[1:]]
    identities = {trace.get("transition_identity") for trace in traces if trace.get("transition_identity")}
    transition_distances = [
        _transition_distance(reordered[i], reordered[i + 1])
        for i in range(len(reordered) - 1)
    ]

    assert "emotional_contrast" in identities
    assert max(transition_distances) < 0.35


def test_transition_semantics_marks_atmospheric_rhythmic_and_release_moves():
    tracks = [
        _track(0, 0.55, 0.46),
        _track(1, 0.56, 0.47),
        _track(2, 0.57, 0.48),
        _track(3, 0.66, 0.52),
        _track(4, 0.68, 0.54),
        _track(5, 0.49, 0.58),
        _track(6, 0.48, 0.59),
        _track(7, 0.50, 0.60),
    ]
    for idx in (1, 2):
        tracks[idx]["acousticness"] = 0.72
        tracks[idx]["tempo"] = 106 + idx
        tracks[idx]["danceability"] = 0.50
    for idx in (3, 4):
        tracks[idx]["danceability"] = 0.80
        tracks[idx]["tempo"] = 142 + idx
        tracks[idx]["acousticness"] = 0.18
    for idx in (5, 6, 7):
        tracks[idx]["acousticness"] = 0.62
        tracks[idx]["tempo"] = 112 + idx
        tracks[idx]["danceability"] = 0.54

    reordered = PlaylistFlowEngine().reorder(tracks, session_type="default", protect_top=1)
    traces = [track.get("flow_trace") or {} for track in reordered[1:]]
    identities = {trace.get("transition_identity") for trace in traces if trace.get("transition_identity")}

    assert "atmospheric_continuity" in identities
    assert "rhythmic_continuity" in identities
    assert "release_transition" in identities


def test_transition_semantics_allows_emotional_contrast_when_texture_stays_coherent():
    profile = {
        "energy_curve": [0.45, 0.65, 0.52],
        "valence_curve": [0.40, 0.55, 0.42],
        "smooth_reward": 0.14,
        "energy_spike_penalty": 0.20,
        "allow_abrupt_at": [],
        "pacing_window": 4,
    }
    prev = {
        **_track("prev", 0.50, 0.36),
        "genres": ["ambient electronic", "synthwave"],
        "danceability": 0.42,
        "tempo": 102,
        "acousticness": 0.08,
        "instrumentalness": 0.84,
        "speechiness": 0.03,
    }
    coherent_pivot = {
        **_track("coherent", 0.58, 0.56),
        "genres": ["cinematic ambient", "electronic"],
        "danceability": 0.44,
        "tempo": 104,
        "acousticness": 0.10,
        "instrumentalness": 0.80,
        "speechiness": 0.04,
    }
    mood_only_neighbor = {
        **_track("mood-only", 0.52, 0.39),
        "genres": ["acoustic folk", "singer-songwriter"],
        "danceability": 0.42,
        "tempo": 103,
        "acousticness": 0.86,
        "instrumentalness": 0.01,
        "speechiness": 0.09,
    }

    coherent_reward, coherent_identity, coherent_details = _transition_semantics_reward(
        prev, coherent_pivot, [prev], 3, 8, profile
    )
    mood_reward, mood_identity, mood_details = _transition_semantics_reward(
        prev, mood_only_neighbor, [prev], 3, 8, profile
    )

    assert coherent_identity == "emotional_contrast"
    assert coherent_details["texture_coherence"] > mood_details["texture_coherence"]
    assert coherent_reward > mood_reward
    assert mood_identity != "emotional_contrast"
