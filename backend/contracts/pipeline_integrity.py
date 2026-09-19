"""
Stage-level recommendation pipeline integrity checks.

These validators inspect intermediate pipeline state before final response or
debug-boundary validation. They are advisory-only: no auto-correction, no
reordering, no persistence, and no changes to recommendation decisions.
"""

from __future__ import annotations

import math
from collections import Counter
from enum import Enum
from typing import Any, Iterable, List, Mapping, Sequence

from .contract_validators import enforce_contracts
from .invariant_checks import ContractViolation, check_score_ranges


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        try:
            return dict(value.to_dict())
        except Exception:
            return {}
    if isinstance(value, Mapping):
        return value
    return {}


def _is_finite_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _clean(value: Any) -> str:
    return str(value or "").strip().lower()


def _track_key(track: Mapping[str, Any]) -> str:
    explicit = _clean(track.get("id"))
    if explicit:
        return explicit
    name = _clean(track.get("name"))
    artist = _clean(track.get("artist"))
    return f"{name}::{artist}" if name or artist else ""


def _primary_artist(track: Mapping[str, Any]) -> str:
    return _clean(str(track.get("artist", "")).split(",")[0])


def _is_track_like(track: Any) -> bool:
    if not isinstance(track, Mapping):
        return False
    has_identity = bool(_track_key(track))
    has_display = bool(track.get("name")) and bool(track.get("artist"))
    return has_identity and has_display


def _track_list(tracks: Any) -> list:
    return tracks if isinstance(tracks, list) else []


def _pool_stats(tracks: Sequence[Mapping[str, Any]]) -> dict:
    count = len(tracks)
    keys = [_track_key(track) for track in tracks]
    artists = [_primary_artist(track) for track in tracks if _primary_artist(track)]
    unique_keys = len(set(key for key in keys if key))
    unique_artists = len(set(artists))
    return {
        "count": count,
        "unique_keys": unique_keys,
        "unique_artists": unique_artists,
        "diversity_ratio": unique_artists / max(1, count),
        "duplicate_key_count": count - unique_keys if unique_keys else count,
    }


def _corrupted_track_violations(stage: str, tracks: Sequence[Any]) -> List[ContractViolation]:
    violations: List[ContractViolation] = []
    for index, track in enumerate(tracks):
        if not _is_track_like(track):
            violations.append(
                ContractViolation(
                    code="corrupted_candidate_pool",
                    message=f"{stage} contains a non-track or structurally incomplete track.",
                    path=f"{stage}[{index}]",
                    value=track,
                    hint="Intermediate tracks should carry stable identity plus name and artist.",
                )
            )
    return violations


def _score_payload_from_tracks(tracks: Sequence[Any]) -> dict:
    payload = {"tracks": []}
    for track in tracks:
        if isinstance(track, Mapping):
            payload["tracks"].append(
                {
                    key: track.get(key)
                    for key in (
                        "quality_score",
                        "primary_score",
                        "final_rank_score",
                        "semantic_similarity",
                        "user_embedding_similarity",
                        "exploration_score",
                        "exploration_ratio",
                        "exploration_injection_rate",
                    )
                    if key in track
                }
            )
    return payload


def validate_candidate_pool_integrity(
    stage_name: str,
    tracks: Any,
    *,
    min_count: int = 1,
    diversity_floor: float = 0.4,
) -> List[ContractViolation]:
    """Validate a retrieved or scored candidate pool before downstream stages."""

    violations: List[ContractViolation] = []
    if not isinstance(tracks, list):
        return [
            ContractViolation(
                code="empty_or_corrupted_pool",
                message=f"{stage_name} is not a list of candidates.",
                path=stage_name,
                value=type(tracks).__name__,
                hint="Pipeline stages should pass list[dict] pools between ranking stages.",
            )
        ]

    if not tracks:
        violations.append(
            ContractViolation(
                code="empty_or_corrupted_pool",
                message=f"{stage_name} produced an empty candidate pool.",
                path=stage_name,
                value={"count": 0},
                hint="Empty pools are allowed to fall back, but should be visible in dev contracts.",
            )
        )

    if len(tracks) < min_count:
        violations.append(
            ContractViolation(
                code="candidate_starvation",
                message=f"{stage_name} has {len(tracks)} candidates, below target {min_count}.",
                path=stage_name,
                value={"count": len(tracks), "target": min_count},
                hint="Starvation can make later selection, exploration, or sequencing structurally fragile.",
            )
        )

    violations.extend(_corrupted_track_violations(stage_name, tracks))
    stats = _pool_stats([track for track in tracks if isinstance(track, Mapping)])
    if stats["count"] >= 3 and stats["diversity_ratio"] < diversity_floor:
        violations.append(
            ContractViolation(
                code="diversity_collapse",
                message=f"{stage_name} artist diversity ratio is {stats['diversity_ratio']:.3f}.",
                path=stage_name,
                value=stats,
                hint="This is advisory only; diversity collapse here should not be auto-repaired.",
            )
        )
    if stats["duplicate_key_count"] > 0:
        violations.append(
            ContractViolation(
                code="unstable_ordering_conditions",
                message=f"{stage_name} contains duplicate or missing stable track keys.",
                path=stage_name,
                value=stats,
                hint="Duplicate keys can make later ordering diffs ambiguous.",
            )
        )

    violations.extend(check_score_ranges(_score_payload_from_tracks(tracks)))
    return violations


def validate_post_intent_gate_health(
    pool_health: Any,
    *,
    target_size: int,
    diversity_floor: float = 0.4,
) -> List[ContractViolation]:
    """Validate the health object returned by adaptive intent gating."""

    health = _as_mapping(pool_health)
    pool_name = str(health.get("pool_name") or "intent_gate")
    pre_count = int(health.get("pre_gate", health.get("pre_gate_count", 0)) or 0)
    post_count = int(health.get("post_gate", health.get("post_gate_count", 0)) or 0)
    unique_artists = int(health.get("unique_artists", 0) or 0)
    diversity_ratio = float(health.get("diversity_ratio", unique_artists / max(1, post_count)) or 0.0)
    survival_rate = float(health.get("survival_rate", post_count / max(1, pre_count)) or 0.0)

    violations: List[ContractViolation] = []
    if post_count < target_size or bool(health.get("is_starved")):
        violations.append(
            ContractViolation(
                code="candidate_starvation",
                message=f"{pool_name} intent gate left {post_count} candidates for target {target_size}.",
                path=pool_name,
                value=dict(health),
                hint="Gate relaxation may still leave a structurally weak pool.",
            )
        )
    if post_count >= 3 and (diversity_ratio < diversity_floor or unique_artists < 2):
        violations.append(
            ContractViolation(
                code="diversity_collapse",
                message=f"{pool_name} intent gate collapsed artist diversity.",
                path=pool_name,
                value=dict(health),
                hint="Keep diversity interpretation separate from exploration or novelty.",
            )
        )
    if post_count > pre_count or survival_rate < 0.0 or survival_rate > 1.0:
        violations.append(
            ContractViolation(
                code="impossible_metric_state",
                message=f"{pool_name} gate health has impossible counts or survival rate.",
                path=pool_name,
                value=dict(health),
                hint="Pool health metrics should be observation-only but internally consistent.",
            )
        )
    return violations


def validate_adaptive_relaxation_outcome(
    pool_health: Any,
    *,
    fallback_history: Iterable[str] = (),
    max_relaxation_tier: int = 3,
) -> List[ContractViolation]:
    """Validate relaxation outcomes and repeated fallback loop indicators."""

    health = _as_mapping(pool_health)
    pool_name = str(health.get("pool_name") or "adaptive_relaxation")
    tier = int(health.get("relaxation_tier", 0) or 0)
    is_starved = bool(health.get("is_starved"))
    violations: List[ContractViolation] = []

    if tier >= max_relaxation_tier and is_starved:
        violations.append(
            ContractViolation(
                code="adaptive_relaxation_exhausted",
                message=f"{pool_name} exhausted relaxation tier {tier} while still starved.",
                path=pool_name,
                value=dict(health),
                hint="Relaxation is advisory here; do not auto-heal or alter ranking policy.",
            )
        )

    fallback_counts = Counter(str(item) for item in fallback_history if item)
    repeated = {reason: count for reason, count in fallback_counts.items() if count > 1}
    if repeated:
        violations.append(
            ContractViolation(
                code="repeated_fallback_loop",
                message=f"{pool_name} observed repeated fallback reason(s).",
                path=pool_name,
                value=repeated,
                hint="Repeated fallback loops should be investigated without changing recommendation behavior.",
            )
        )
    return violations


def validate_exploration_injection_integrity(
    *,
    before_tracks: Any,
    after_tracks: Any,
    candidate_pool: Any,
    requested_ratio: float,
) -> List[ContractViolation]:
    """Validate controlled exploration injection without changing its result."""

    before = _track_list(before_tracks)
    after = _track_list(after_tracks)
    candidates = _track_list(candidate_pool)
    violations: List[ContractViolation] = []
    violations.extend(check_score_ranges({"exploration_ratio": requested_ratio}))

    if len(after) != len(before):
        violations.append(
            ContractViolation(
                code="exploration_injection_integrity",
                message="Exploration injection changed playlist length.",
                path="exploration_injection",
                value={"before": len(before), "after": len(after)},
                hint="Injection may replace tail tracks but should preserve playlist size.",
            )
        )

    before_exploration = sum(1 for track in before if isinstance(track, Mapping) and track.get("exploration"))
    after_exploration = sum(1 for track in after if isinstance(track, Mapping) and track.get("exploration"))
    if requested_ratio > 0 and candidates and before and after_exploration <= before_exploration:
        violations.append(
            ContractViolation(
                code="exploration_disappearance",
                message="Exploration was requested with candidates available but no exploration track appeared.",
                path="exploration_injection",
                value={
                    "requested_ratio": requested_ratio,
                    "candidate_count": len(candidates),
                    "before_exploration": before_exploration,
                    "after_exploration": after_exploration,
                },
                hint="This is advisory; absence may be legitimate if semantic gates rejected all candidates.",
            )
        )

    stats = _pool_stats([track for track in after if isinstance(track, Mapping)])
    if stats["duplicate_key_count"] > 0:
        violations.append(
            ContractViolation(
                code="unstable_ordering_conditions",
                message="Post-exploration playlist contains duplicate or missing track keys.",
                path="exploration_injection",
                value=stats,
                hint="Duplicate tracks can make later flow ordering unstable.",
            )
        )
    violations.extend(check_score_ranges(_score_payload_from_tracks(after)))
    return violations


def validate_sequencing_preconditions(tracks: Any) -> List[ContractViolation]:
    """Validate selected tracks before flow ordering."""

    if not isinstance(tracks, list):
        return [
            ContractViolation(
                code="invalid_sequencing_input",
                message="Sequencing input is not a list.",
                path="flow_sequencing",
                value=type(tracks).__name__,
                hint="Flow ordering expects a selected list of track dictionaries.",
            )
        ]

    violations: List[ContractViolation] = []
    if len(tracks) < 2:
        violations.append(
            ContractViolation(
                code="invalid_sequencing_input",
                message="Sequencing input has fewer than two tracks.",
                path="flow_sequencing",
                value={"count": len(tracks)},
                hint="Single-track playlists are allowed, but flow metrics are not meaningful.",
            )
        )

    required_audio = ("energy", "valence", "danceability", "tempo")
    for index, track in enumerate(tracks):
        if not _is_track_like(track):
            violations.append(
                ContractViolation(
                    code="invalid_sequencing_input",
                    message="Sequencing input contains a structurally incomplete track.",
                    path=f"flow_sequencing[{index}]",
                    value=track,
                    hint="Flow ordering needs stable track identity and display fields.",
                )
            )
            continue
        invalid_audio = [field for field in required_audio if not _is_finite_number(track.get(field))]
        if invalid_audio:
            violations.append(
                ContractViolation(
                    code="invalid_sequencing_input",
                    message="Sequencing input contains invalid audio feature values.",
                    path=f"flow_sequencing[{index}]",
                    value={"invalid_audio_fields": invalid_audio},
                    hint="Flow ordering can coerce defaults, but invalid inputs should be visible.",
                )
            )

    stats = _pool_stats([track for track in tracks if isinstance(track, Mapping)])
    if stats["duplicate_key_count"] > 0:
        violations.append(
            ContractViolation(
                code="unstable_ordering_conditions",
                message="Sequencing input contains duplicate or missing stable keys.",
                path="flow_sequencing",
                value=stats,
                hint="Stable keys are needed for deterministic trace diffs and ratio preservation checks.",
            )
        )
    violations.extend(check_score_ranges(_score_payload_from_tracks(tracks)))
    return violations


def validate_final_ordered_playlist(
    tracks: Any,
    *,
    requested_size: int,
    requested_exploration_ratio: float = 0.0,
) -> List[ContractViolation]:
    """Validate final ordered playlist structural sanity."""

    if not isinstance(tracks, list):
        return [
            ContractViolation(
                code="final_playlist_structural_sanity",
                message="Final playlist is not a list.",
                path="final_playlist",
                value=type(tracks).__name__,
                hint="Final recommendation output should remain a list of track dictionaries.",
            )
        ]

    violations: List[ContractViolation] = []
    if not tracks or len(tracks) != requested_size:
        violations.append(
            ContractViolation(
                code="final_playlist_structural_sanity",
                message=f"Final playlist has {len(tracks)} tracks for requested size {requested_size}.",
                path="final_playlist",
                value={"actual": len(tracks), "requested": requested_size},
                hint="Short playlists can be valid under duration limits, but should be visible to operators.",
            )
        )

    stats = _pool_stats([track for track in tracks if isinstance(track, Mapping)])
    if stats["count"] >= 3 and stats["diversity_ratio"] < 0.4:
        violations.append(
            ContractViolation(
                code="diversity_collapse",
                message="Final playlist has low artist diversity.",
                path="final_playlist",
                value=stats,
                hint="This is a structural sanity signal, not a recommendation failure verdict.",
            )
        )
    if stats["duplicate_key_count"] > 0:
        violations.append(
            ContractViolation(
                code="unstable_ordering_conditions",
                message="Final playlist contains duplicate or missing stable keys.",
                path="final_playlist",
                value=stats,
                hint="Duplicate keys can make final order unstable or hard to audit.",
            )
        )

    flow_positions = [
        track.get("flow_position")
        for track in tracks
        if isinstance(track, Mapping) and track.get("flow_position") is not None
    ]
    if flow_positions:
        expected = set(range(len(tracks)))
        observed = set(pos for pos in flow_positions if isinstance(pos, int))
        if observed and not observed.issubset(expected):
            violations.append(
                ContractViolation(
                    code="impossible_metric_state",
                    message="Final playlist contains impossible flow_position values.",
                    path="final_playlist.flow_position",
                    value={"observed": sorted(observed), "expected_range": [0, max(0, len(tracks) - 1)]},
                    hint="Flow positions are zero-based positions in the final ordered playlist.",
                )
            )

    exploration_count = sum(1 for track in tracks if isinstance(track, Mapping) and track.get("exploration"))
    if requested_exploration_ratio > 0 and len(tracks) >= 2 and exploration_count > len(tracks):
        violations.append(
            ContractViolation(
                code="impossible_metric_state",
                message="Final exploration count exceeds playlist length.",
                path="final_playlist.exploration_count",
                value={"exploration_count": exploration_count, "track_count": len(tracks)},
                hint="Exploration counts must stay within final playlist bounds.",
            )
        )

    violations.extend(check_score_ranges(_score_payload_from_tracks(tracks)))
    return violations


class PipelineStage(Enum):
    """Dispatch helper for stage-specific validators."""

    CANDIDATE_RETRIEVAL = "candidate_retrieval"
    POST_INTENT_GATE = "post_intent_gate"
    ADAPTIVE_RELAXATION = "adaptive_relaxation"
    EXPLORATION_INJECTION = "exploration_injection"
    SEQUENCING_PRECONDITION = "sequencing_precondition"
    FINAL_ORDERED_PLAYLIST = "final_ordered_playlist"

    def validate(self, *, emit_warnings: bool = False, **kwargs: Any) -> List[ContractViolation]:
        if self is PipelineStage.CANDIDATE_RETRIEVAL:
            violations = validate_candidate_pool_integrity(
                self.value,
                kwargs.get("tracks"),
                min_count=int(kwargs.get("min_count", 1)),
            )
        elif self is PipelineStage.POST_INTENT_GATE:
            violations = validate_post_intent_gate_health(
                kwargs.get("pool_health"),
                target_size=int(kwargs.get("target_size", 1)),
            )
        elif self is PipelineStage.ADAPTIVE_RELAXATION:
            violations = validate_adaptive_relaxation_outcome(
                kwargs.get("pool_health"),
                fallback_history=kwargs.get("fallback_history", ()),
            )
        elif self is PipelineStage.EXPLORATION_INJECTION:
            violations = validate_exploration_injection_integrity(
                before_tracks=kwargs.get("before_tracks"),
                after_tracks=kwargs.get("after_tracks"),
                candidate_pool=kwargs.get("candidate_pool"),
                requested_ratio=float(kwargs.get("requested_ratio", 0.0) or 0.0),
            )
        elif self is PipelineStage.SEQUENCING_PRECONDITION:
            violations = validate_sequencing_preconditions(kwargs.get("tracks"))
        elif self is PipelineStage.FINAL_ORDERED_PLAYLIST:
            violations = validate_final_ordered_playlist(
                kwargs.get("tracks"),
                requested_size=int(kwargs.get("requested_size", 1)),
                requested_exploration_ratio=float(kwargs.get("requested_exploration_ratio", 0.0) or 0.0),
            )
        else:
            violations = []

        if emit_warnings:
            enforce_contracts(violations)
        return violations
