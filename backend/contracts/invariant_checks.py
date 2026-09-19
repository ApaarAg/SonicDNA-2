"""
Invariant checks shared by the contract validators.

These helpers are deliberately lightweight and side-effect free. They inspect
plain dictionaries/lists and return ContractViolation objects. Callers can turn
those into warnings in dev/debug environments without affecting recommendation
behavior.
"""

from __future__ import annotations

import os
import warnings
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


@dataclass(frozen=True)
class ContractViolation:
    """A single advisory architecture-contract violation."""

    code: str
    message: str
    path: str = ""
    severity: str = "warning"
    value: Any = None
    hint: str = ""

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        return {k: v for k, v in data.items() if v not in ("", None)}


@dataclass
class ContractReport:
    """Aggregated contract validation result."""

    violations: List[ContractViolation] = field(default_factory=list)

    @property
    def has_violations(self) -> bool:
        return bool(self.violations)

    @property
    def codes(self) -> List[str]:
        return [item.code for item in self.violations]

    @property
    def examples(self) -> List[Dict[str, Any]]:
        return [item.to_dict() for item in self.violations[:10]]

    def extend(self, items: Iterable[ContractViolation]) -> None:
        self.violations.extend(items)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "has_violations": self.has_violations,
            "violation_count": len(self.violations),
            "codes": self.codes,
            "examples": self.examples,
        }


def is_contract_enforcement_enabled() -> bool:
    """Return True when contract warnings should be emitted."""

    for key in ("SONICDNA_CONTRACTS", "DEBUG_CONTRACTS"):
        if os.getenv(key, "").lower() in {"1", "true", "yes"}:
            return True
    env = (os.getenv("SONICDNA_ENV") or os.getenv("APP_ENV") or "").lower()
    return env in {"development", "dev", "local", "debug"}


def warn_contract_violations(violations: Iterable[ContractViolation]) -> List[ContractViolation]:
    """Emit RuntimeWarning for violations only when contracts are enabled."""

    items = list(violations)
    if not is_contract_enforcement_enabled():
        return items
    for item in items:
        location = f" at {item.path}" if item.path else ""
        hint = f" Hint: {item.hint}" if item.hint else ""
        warnings.warn(
            f"[contract:{item.code}]{location} {item.message}{hint}",
            RuntimeWarning,
            stacklevel=2,
        )
    return items


def _walk(value: Any, path: str = ""):
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_path = f"{path}.{key}" if path else str(key)
            yield key_path, key, item
            yield from _walk(item, key_path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            item_path = f"{path}[{index}]" if path else f"[{index}]"
            yield item_path, index, item
            yield from _walk(item, item_path)


DEFAULT_SCORE_RANGES: Dict[str, Tuple[float, float]] = {
    "raw_cosine_similarity": (-1.0, 1.0),
    "cosine_similarity": (-1.0, 1.0),
    "popularity": (0.0, 100.0),
}


def _expected_range(name: str, explicit_ranges: Mapping[str, Tuple[float, float]]) -> Optional[Tuple[float, float]]:
    normalized = name.lower()
    if normalized in explicit_ranges:
        return explicit_ranges[normalized]
    if normalized in DEFAULT_SCORE_RANGES:
        return DEFAULT_SCORE_RANGES[normalized]
    if normalized.endswith(("_score", "_ratio", "_rate", "_similarity", "_quality")):
        return (0.0, 1.0)
    if normalized in {"overall_flow_score", "semantic_match", "flow_quality"}:
        return (0.0, 1.0)
    return None


def check_score_ranges(
    payload: Mapping[str, Any],
    *,
    ranges: Optional[Mapping[str, Tuple[float, float]]] = None,
) -> List[ContractViolation]:
    """Validate canonical score/rate/ratio fields against their expected range."""

    explicit = {k.lower(): v for k, v in dict(ranges or {}).items()}
    violations: List[ContractViolation] = []
    for path, key, value in _walk(payload):
        if not isinstance(key, str) or isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        expected = _expected_range(key, explicit)
        if expected is None:
            continue
        low, high = expected
        if float(value) < low or float(value) > high:
            violations.append(
                ContractViolation(
                    code="invalid_score_range",
                    message=f"{key}={value!r} is outside expected range [{low}, {high}].",
                    path=path,
                    value=value,
                    hint="Keep score/rate/ratio metrics on their documented scale.",
                )
            )
    return violations


SEQUENCE_SENSITIVE_METRICS = frozenset(
    {
        "overall_flow_score",
        "flow_quality",
        "flow_entropy",
        "flow_trace",
        "flow_position",
        "same_order_ratio",
        "artist_repeat_pressure",
        "community_repeat_pressure",
        "max_artist_run",
        "max_cluster_run",
        "adherence_score",
        "spike_violations",
    }
)


def check_sequence_sensitive_usage(metric_name: str, context: Mapping[str, Any]) -> List[ContractViolation]:
    """
    Ensure sequence-sensitive metrics are computed from ordered final playlists.

    The check is intentionally small: callers provide context such as
    tracks_are_ordered=False or source_stage="candidate_pool".
    """

    normalized = str(metric_name or "").strip().lower()
    if normalized not in SEQUENCE_SENSITIVE_METRICS:
        return []

    tracks_are_ordered = bool(context.get("tracks_are_ordered"))
    source_stage = str(context.get("source_stage", "")).lower()
    unordered_stage = source_stage in {"candidate_pool", "candidate_retrieval", "unordered_pool", "pre_sequence"}
    if tracks_are_ordered and not unordered_stage:
        return []

    return [
        ContractViolation(
            code="sequence_sensitive_misuse",
            message=f"{metric_name} is sequence-sensitive but context is not an ordered final playlist.",
            path=str(context.get("path", "")),
            value=dict(context),
            hint="Compute flow/repetition/order metrics after flow sequencing, not from candidate pools.",
        )
    ]


def _leaf_name(source: str) -> str:
    return str(source).split(".")[-1].upper()


def check_config_duplication(config_sources: Mapping[str, Any]) -> List[ContractViolation]:
    """
    Detect constants duplicated outside config.scoring_config.

    Input is a source map like {"config.scoring_config.FLOW.W_ZONE": 0.3,
    "playlist_flow_engine.W_ZONE": 0.3}. This keeps the check import-free and
    cheap; diagnostics or tests can pass only the sources they inspect.
    """

    by_leaf: Dict[str, List[Tuple[str, Any]]] = {}
    for source, value in config_sources.items():
        by_leaf.setdefault(_leaf_name(source), []).append((source, value))

    violations: List[ContractViolation] = []
    for leaf, entries in by_leaf.items():
        if len(entries) < 2:
            continue
        canonical = [source for source, _ in entries if "config.scoring_config" in source]
        duplicates = [source for source, _ in entries if "config.scoring_config" not in source]
        if not canonical or not duplicates:
            continue
        values = {repr(value) for _, value in entries}
        message = f"{leaf} appears in scoring_config and {len(duplicates)} non-config source(s)."
        if len(values) == 1:
            message += " Values are identical, which suggests copied configuration."
        violations.append(
            ContractViolation(
                code="config_duplication_detected",
                message=message,
                path=", ".join(source for source, _ in entries),
                value={source: value for source, value in entries},
                hint="Import the canonical value from config.scoring_config instead of duplicating it.",
            )
        )
    return violations


def check_sequence_sensitive_batch(checks: Sequence[Mapping[str, Any]]) -> List[ContractViolation]:
    """Run sequence-sensitive checks from a list of small check descriptors."""

    violations: List[ContractViolation] = []
    for item in checks:
        violations.extend(
            check_sequence_sensitive_usage(
                metric_name=str(item.get("metric_name", "")),
                context=dict(item.get("context") or {}),
            )
        )
    return violations
