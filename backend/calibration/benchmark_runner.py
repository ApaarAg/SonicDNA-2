"""
Offline A/B benchmark orchestration for recommendation calibration.

The runner compares two explicit configurations over controlled scenarios.
It restores scoring_config attributes after each run and never persists output.
"""

from __future__ import annotations

import contextlib
import copy
import statistics
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Tuple

from .playlist_diff import compare_playlists, compare_repeated_runs
from .scenario_runner import SCENARIOS, run_scenario

try:
    from config import scoring_config
except Exception:  # pragma: no cover
    scoring_config = None


DEFAULT_REGRESSION_THRESHOLDS = {
    "flow_quality_delta": -0.05,
    "diversity.unique_artists_ratio": -0.08,
    "diversity.novelty.mainstream_niche_balance": -0.1,
    "semantic.avg_trace_semantic_similarity": -0.08,
    "playlist_overlap_min": 0.35,
}

EXAMPLE_BENCHMARK_REPORT = {
    "config_a": {"label": "baseline"},
    "config_b": {"label": "candidate_exploration_0_15"},
    "metric_deltas": {
        "flow.overall_flow_score": 0.018,
        "diversity.unique_artists_ratio": 0.041,
        "semantic.avg_trace_semantic_similarity": -0.012,
    },
    "playlist_overlap": 0.62,
    "flow_quality_delta": 0.018,
    "diversity_delta": {"unique_artists_ratio": 0.041},
}


def _label(config: Mapping[str, Any], fallback: str) -> str:
    return str(config.get("label") or config.get("name") or fallback)


def _public_config(config: Mapping[str, Any], fallback: str) -> dict:
    hidden = {"generator", "spotify_service"}
    public = {key: value for key, value in config.items() if key not in hidden}
    public.setdefault("label", _label(config, fallback))
    return public


def _iter_overrides(overrides: Optional[Mapping[str, Any]]) -> Iterator[Tuple[type, str, Any]]:
    if not overrides or scoring_config is None:
        return iter(())

    items = []
    for key, value in overrides.items():
        if "." in key:
            section, attr = key.split(".", 1)
            target = getattr(scoring_config, section)
            items.append((target, attr, value))
        elif isinstance(value, Mapping):
            target = getattr(scoring_config, key)
            for attr, nested_value in value.items():
                items.append((target, str(attr), nested_value))
        else:
            raise ValueError(f"Config override must use SECTION.ATTR or nested mapping: {key}")
    return iter(items)


@contextlib.contextmanager
def temporary_scoring_overrides(overrides: Optional[Mapping[str, Any]]) -> Iterator[None]:
    """Temporarily patch centralized scoring config class attributes."""
    originals = []
    for target, attr, value in _iter_overrides(overrides):
        originals.append((target, attr, getattr(target, attr)))
        setattr(target, attr, value)
    try:
        yield
    finally:
        for target, attr, original in reversed(originals):
            setattr(target, attr, original)


def _run_config(config: Mapping[str, Any], scenario_name: str, scenario_overrides: Optional[Mapping[str, Any]]) -> dict:
    generator = config.get("generator")
    spotify_service = config.get("spotify_service")
    overrides = dict(scenario_overrides or {})
    overrides.update(dict(config.get("scenario_overrides") or {}))
    with temporary_scoring_overrides(config.get("scoring_overrides")):
        return run_scenario(
            scenario_name,
            generator=generator,
            spotify_service=spotify_service,
            overrides=overrides,
            include_explanations=bool(config.get("include_explanations", True)),
        )


def _scenario_report(
    scenario_name: str,
    result_a: Mapping[str, Any],
    result_b: Mapping[str, Any],
    config_a: Mapping[str, Any],
    config_b: Mapping[str, Any],
) -> dict:
    comparison = compare_playlists(
        result_a["playlist"],
        result_b["playlist"],
        session_type=result_a["scenario"].get("session_type"),
    )
    return {
        "scenario": result_a["scenario"],
        "config_a": _public_config(config_a, "config_a"),
        "config_b": _public_config(config_b, "config_b"),
        "metric_deltas": comparison["metric_deltas"],
        "playlist_overlap": comparison["playlist_overlap"],
        "flow_quality_delta": comparison["flow_quality_delta"],
        "diversity_delta": comparison["diversity_delta"],
        "semantic_consistency": comparison["semantic_consistency"],
        "semantic_balance": comparison["semantic_balance"],
        "recommendation_stability": comparison["recommendation_stability"],
        "flow_reports": comparison["flow_reports"],
        "playlists": {
            "config_a": result_a["playlist"],
            "config_b": result_b["playlist"],
        },
    }


def run_ab_benchmark(
    *,
    config_a: Mapping[str, Any],
    config_b: Mapping[str, Any],
    scenario_names: Optional[Iterable[str]] = None,
    scenario_overrides: Optional[Mapping[str, Any]] = None,
    regression_thresholds: Optional[Mapping[str, float]] = None,
) -> dict:
    """Run config A/B scenarios and return structured comparison reports."""
    names = list(scenario_names or SCENARIOS.keys())
    reports = []
    for name in names:
        result_a = _run_config(config_a, name, scenario_overrides)
        result_b = _run_config(config_b, name, scenario_overrides)
        reports.append(_scenario_report(name, result_a, result_b, config_a, config_b))

    return {
        "config_a": _public_config(config_a, "config_a"),
        "config_b": _public_config(config_b, "config_b"),
        "scenario_count": len(reports),
        "scenario_reports": reports,
        "aggregate": aggregate_reports(reports),
        "regression_detection": detect_regressions(
            reports,
            thresholds=dict(DEFAULT_REGRESSION_THRESHOLDS, **dict(regression_thresholds or {})),
        ),
    }


def aggregate_reports(reports: Iterable[Mapping[str, Any]]) -> dict:
    reports = list(reports)
    if not reports:
        return {}

    def values(key: str) -> List[float]:
        found = []
        for report in reports:
            value = report.get(key)
            if isinstance(value, (int, float)):
                found.append(float(value))
        return found

    overlap = values("playlist_overlap")
    flow = values("flow_quality_delta")
    return {
        "average_playlist_overlap": round(statistics.mean(overlap), 3) if overlap else None,
        "average_flow_quality_delta": round(statistics.mean(flow), 4) if flow else None,
        "scenario_count": len(reports),
    }


def _metric_value(report: Mapping[str, Any], metric: str) -> Optional[float]:
    if metric == "flow_quality_delta":
        value = report.get("flow_quality_delta")
    elif metric == "playlist_overlap_min":
        value = report.get("playlist_overlap")
    else:
        value = report.get("metric_deltas", {}).get(metric)
        if value is None and metric.startswith("diversity."):
            value = report.get("diversity_delta", {}).get(metric.removeprefix("diversity."))
    return float(value) if isinstance(value, (int, float)) else None


def detect_regressions(
    reports: Iterable[Mapping[str, Any]],
    *,
    thresholds: Optional[Mapping[str, float]] = None,
) -> dict:
    """Flag scenario-level candidate regressions against explicit thresholds."""
    thresholds = dict(DEFAULT_REGRESSION_THRESHOLDS, **dict(thresholds or {}))
    findings = []
    for report in reports:
        scenario = report.get("scenario", {}).get("name", "unknown")
        for metric, threshold in thresholds.items():
            value = _metric_value(report, metric)
            if value is None:
                continue
            if metric == "playlist_overlap_min":
                failed = value < threshold
                detail = f"overlap {value} below minimum {threshold}"
            else:
                failed = value < threshold
                detail = f"delta {value} below threshold {threshold}"
            if failed:
                findings.append(
                    {
                        "scenario": scenario,
                        "metric": metric,
                        "value": value,
                        "threshold": threshold,
                        "detail": detail,
                    }
                )
    return {
        "regression_count": len(findings),
        "has_regressions": bool(findings),
        "findings": findings,
        "thresholds": thresholds,
    }


def run_stability_benchmark(
    *,
    config: Mapping[str, Any],
    scenario_name: str,
    repetitions: int = 3,
    scenario_overrides: Optional[Mapping[str, Any]] = None,
) -> dict:
    """Run one config repeatedly to measure recommendation stability."""
    playlists = []
    scenario = None
    for _ in range(max(1, int(repetitions))):
        result = _run_config(config, scenario_name, copy.deepcopy(scenario_overrides or {}))
        playlists.append(result["playlist"])
        scenario = result["scenario"]
    stability = compare_repeated_runs(playlists, session_type=(scenario or {}).get("session_type"))
    return {
        "config": _public_config(config, "config"),
        "scenario": scenario,
        "stability": stability,
        "long_horizon_exploration": stability.get("long_horizon_exploration"),
        "topology_diagnostics": stability.get("topology_diagnostics"),
    }
