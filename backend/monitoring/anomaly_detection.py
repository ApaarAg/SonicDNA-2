"""
anomaly_detection.py — Threshold-based anomaly flagging.

Scans the MetricsStore for operational anomalies and returns structured
findings. Pure observation — never mutates behavior or state.

Detected anomalies
------------------
* latency_spike        — p95 latency exceeds threshold
* cache_collapse       — cache hit rate drops below floor
* exploration_gone     — exploration injection rate drops to zero
* diversity_collapse   — playlist diversity drops below threshold
* flow_degradation     — flow quality score consistently low
* elevated_failures    — failure rate exceeds threshold
* empty_candidates     — candidate retrieval returning empty frequently
* instability          — recommendation stability score too low
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from .metrics_store import MetricsStore, get_store


# ---------------------------------------------------------------------------
# Thresholds (all tunable, no magic)
# ---------------------------------------------------------------------------

THRESHOLDS = {
    # Latency p95 thresholds in ms
    "latency_recommendation_total": 2000.0,
    "latency_candidate_retrieval": 1500.0,
    "latency_embedding_rerank": 500.0,
    "latency_genome_scoring": 200.0,
    "latency_flow_sequencing": 100.0,
    "latency_spotify_api": 3000.0,
    # Cache hit rate floors
    "cache_search_floor": 0.20,
    "cache_regional_floor": 0.15,
    "cache_embedding_floor": 0.30,
    # Quality floors
    "diversity_floor": 0.25,
    "flow_quality_floor": 0.35,
    "stability_floor": 0.40,
    # Operational rate floors
    "exploration_rate_floor": 0.02,
    "candidate_nonempty_floor": 0.70,
    "playlist_success_floor": 0.85,
    # Failure rate ceiling (failures per minute)
    "failure_rate_ceiling": 5.0,
}


@dataclass
class Anomaly:
    """A single detected anomaly."""
    type: str = ""
    severity: str = "medium"    # "low" | "medium" | "high" | "critical"
    metric: str = ""
    current_value: Optional[float] = None
    threshold: Optional[float] = None
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


# ---------------------------------------------------------------------------
# Detection functions
# ---------------------------------------------------------------------------

def _check_latency_spikes(store: MetricsStore, window: int) -> List[Anomaly]:
    anomalies: List[Anomaly] = []
    latency_thresholds = {
        "recommendation_total": ("latency_recommendation_total", "critical"),
        "candidate_retrieval": ("latency_candidate_retrieval", "high"),
        "embedding_rerank": ("latency_embedding_rerank", "medium"),
        "genome_scoring": ("latency_genome_scoring", "medium"),
        "flow_sequencing": ("latency_flow_sequencing", "low"),
        "spotify_api": ("latency_spotify_api", "high"),
    }
    for metric, (threshold_key, severity) in latency_thresholds.items():
        stats = store.get_latency_stats(metric, window)
        p95 = stats.get("p95")
        threshold = THRESHOLDS.get(threshold_key)
        if p95 is not None and threshold is not None and p95 > threshold:
            anomalies.append(Anomaly(
                type="latency_spike",
                severity=severity,
                metric=metric,
                current_value=p95,
                threshold=threshold,
                message=f"{metric} p95={p95:.0f}ms exceeds {threshold:.0f}ms",
            ))
    return anomalies


def _check_cache_collapse(store: MetricsStore, window: int) -> List[Anomaly]:
    anomalies: List[Anomaly] = []
    cache_floors = {
        "search": "cache_search_floor",
        "regional": "cache_regional_floor",
        "embedding": "cache_embedding_floor",
    }
    for cache_name, threshold_key in cache_floors.items():
        rate = store.get_cache_rate(cache_name, window)
        floor = THRESHOLDS.get(threshold_key)
        if rate is not None and floor is not None and rate < floor:
            anomalies.append(Anomaly(
                type="cache_collapse",
                severity="high" if rate < floor * 0.5 else "medium",
                metric=f"cache_{cache_name}",
                current_value=rate,
                threshold=floor,
                message=f"{cache_name} cache hit rate {rate:.1%} below floor {floor:.1%}",
            ))
    return anomalies


def _check_exploration_disappearance(store: MetricsStore, window: int) -> List[Anomaly]:
    r = store._ratios.get("exploration_injection")
    if r is None:
        return []
    rate = r.rate(window)
    floor = THRESHOLDS["exploration_rate_floor"]
    if rate is not None and rate < floor and r._hits:
        return [Anomaly(
            type="exploration_gone",
            severity="high",
            metric="exploration_injection_rate",
            current_value=rate,
            threshold=floor,
            message=f"Exploration injection rate {rate:.1%} — tracks may lack diversity",
        )]
    return []


def _check_quality_collapse(store: MetricsStore, window: int) -> List[Anomaly]:
    anomalies: List[Anomaly] = []
    checks = [
        ("playlist_diversity", "diversity_floor", "diversity_collapse", "high"),
        ("flow_quality", "flow_quality_floor", "flow_degradation", "medium"),
        ("recommendation_stability", "stability_floor", "instability", "medium"),
    ]
    for metric, threshold_key, anomaly_type, severity in checks:
        qm = store._quality.get(metric)
        if qm is None or qm.count == 0:
            continue
        stats = qm.stats(window)
        mean = stats.get("mean")
        floor = THRESHOLDS.get(threshold_key)
        if mean is not None and floor is not None and mean < floor:
            anomalies.append(Anomaly(
                type=anomaly_type,
                severity=severity,
                metric=metric,
                current_value=mean,
                threshold=floor,
                message=f"{metric} mean={mean:.3f} below floor {floor:.3f}",
            ))
    return anomalies


def _check_elevated_failures(store: MetricsStore, _window: int) -> List[Anomaly]:
    c = store._counters.get("playlist_failed")
    if c is None or c.total == 0:
        return []
    rate = c.rate_per_minute()
    ceiling = THRESHOLDS["failure_rate_ceiling"]
    if rate > ceiling:
        return [Anomaly(
            type="elevated_failures",
            severity="critical" if rate > ceiling * 2 else "high",
            metric="playlist_failures_per_min",
            current_value=rate,
            threshold=ceiling,
            message=f"Failure rate {rate:.1f}/min exceeds ceiling {ceiling:.1f}/min",
        )]
    return []


def _check_empty_candidates(store: MetricsStore, window: int) -> List[Anomaly]:
    r = store._ratios.get("candidate_nonempty")
    if r is None:
        return []
    rate = r.rate(window)
    floor = THRESHOLDS["candidate_nonempty_floor"]
    if rate is not None and rate < floor:
        return [Anomaly(
            type="empty_candidates",
            severity="high",
            metric="candidate_nonempty_rate",
            current_value=rate,
            threshold=floor,
            message=f"Candidate retrieval non-empty rate {rate:.1%} below {floor:.1%}",
        )]
    return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_anomalies(
    store: Optional[MetricsStore] = None,
    *,
    window: int = 50,
) -> List[Anomaly]:
    """
    Run all anomaly checks against the metrics store.

    Returns a list of detected anomalies sorted by severity.
    """
    store = store or get_store()
    anomalies: List[Anomaly] = []
    anomalies.extend(_check_latency_spikes(store, window))
    anomalies.extend(_check_cache_collapse(store, window))
    anomalies.extend(_check_exploration_disappearance(store, window))
    anomalies.extend(_check_quality_collapse(store, window))
    anomalies.extend(_check_elevated_failures(store, window))
    anomalies.extend(_check_empty_candidates(store, window))

    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    anomalies.sort(key=lambda a: severity_order.get(a.severity, 4))
    return anomalies
