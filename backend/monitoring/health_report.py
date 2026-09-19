"""
health_report.py — Structured health snapshot generation.

Produces a single JSON-serializable health report from the MetricsStore,
enriched with anomaly flags. Designed for dev dashboards, admin endpoints,
and periodic logging — never user-facing.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from .metrics_store import MetricsStore, get_store


@dataclass
class HealthStatus:
    """Top-level health verdict."""
    status: str = "healthy"          # "healthy" | "degraded" | "unhealthy"
    score: float = 1.0               # 0.0 - 1.0
    active_anomalies: int = 0
    uptime_seconds: float = 0.0
    generated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LatencySummary:
    """Per-stage latency summary."""
    stage: str = ""
    mean_ms: Optional[float] = None
    p50_ms: Optional[float] = None
    p95_ms: Optional[float] = None
    max_ms: Optional[float] = None
    sample_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class CacheSummary:
    """Cache health summary."""
    name: str = ""
    hit_rate: Optional[float] = None
    total_lookups: int = 0
    verdict: str = "ok"              # "ok" | "cold" | "degraded"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class QualitySummary:
    """Recommendation quality summary."""
    metric: str = ""
    mean: Optional[float] = None
    min_val: Optional[float] = None
    trend: str = "stable"            # "improving" | "stable" | "declining"
    sample_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class HealthReport:
    """Full health report snapshot."""
    status: Optional[HealthStatus] = None
    latencies: List[LatencySummary] = field(default_factory=list)
    caches: List[CacheSummary] = field(default_factory=list)
    quality: List[QualitySummary] = field(default_factory=list)
    counters: Dict[str, Any] = field(default_factory=dict)
    session_distribution: Dict[str, float] = field(default_factory=dict)
    anomalies: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.to_dict() if self.status else {},
            "latencies": [l.to_dict() for l in self.latencies],
            "caches": [c.to_dict() for c in self.caches],
            "quality": [q.to_dict() for q in self.quality],
            "counters": self.counters,
            "session_distribution": self.session_distribution,
            "anomalies": self.anomalies,
        }


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def _trend(values: List[float], split: int = 2) -> str:
    """Determine trend from a list of values by comparing halves."""
    if len(values) < split * 2:
        return "stable"
    mid = len(values) // 2
    first_half = sum(values[:mid]) / mid
    second_half = sum(values[mid:]) / (len(values) - mid)
    delta = second_half - first_half
    if abs(delta) < 0.02:
        return "stable"
    return "improving" if delta > 0 else "declining"


def generate_health_report(
    store: Optional[MetricsStore] = None,
    *,
    window: int = 50,
    include_anomalies: bool = True,
) -> HealthReport:
    """
    Generate a structured health report from the metrics store.

    Parameters
    ----------
    store : MetricsStore or None
        If None, uses the global singleton.
    window : int
        Number of recent samples to consider.
    include_anomalies : bool
        Whether to run anomaly detection and include results.
    """
    store = store or get_store()
    snap = store.snapshot(window)

    # Latency summaries
    latencies: List[LatencySummary] = []
    for stage, stats in snap.get("latencies", {}).items():
        latencies.append(LatencySummary(
            stage=stage,
            mean_ms=stats.get("mean"),
            p50_ms=stats.get("p50"),
            p95_ms=stats.get("p95"),
            max_ms=stats.get("max"),
            sample_count=stats.get("count", 0),
        ))

    # Cache summaries
    caches: List[CacheSummary] = []
    for name, stats in snap.get("cache_rates", {}).items():
        rate = stats.get("rate")
        verdict = "ok"
        if rate is not None:
            if rate < 0.15:
                verdict = "cold"
            elif rate < 0.40:
                verdict = "degraded"
        caches.append(CacheSummary(
            name=name,
            hit_rate=rate,
            total_lookups=stats.get("count", 0),
            verdict=verdict,
        ))

    # Quality summaries
    quality: List[QualitySummary] = []
    for metric, stats in snap.get("quality_metrics", {}).items():
        qm = store._quality.get(metric)
        vals = qm.recent(window) if qm else []
        quality.append(QualitySummary(
            metric=metric,
            mean=stats.get("mean"),
            min_val=stats.get("min"),
            trend=_trend(vals),
            sample_count=stats.get("count", 0),
        ))

    # Anomalies
    anomaly_list: List[Dict[str, Any]] = []
    if include_anomalies:
        try:
            from .anomaly_detection import detect_anomalies
            anomaly_list = [a.to_dict() for a in detect_anomalies(store, window=window)]
        except Exception:
            pass

    # Overall status
    health_score = 1.0
    for a in anomaly_list:
        severity = a.get("severity", "low")
        if severity == "critical":
            health_score -= 0.3
        elif severity == "high":
            health_score -= 0.15
        elif severity == "medium":
            health_score -= 0.05
    health_score = max(0.0, round(health_score, 2))

    if health_score >= 0.8:
        status_label = "healthy"
    elif health_score >= 0.5:
        status_label = "degraded"
    else:
        status_label = "unhealthy"

    from datetime import datetime, timezone
    status = HealthStatus(
        status=status_label,
        score=health_score,
        active_anomalies=len(anomaly_list),
        uptime_seconds=snap.get("uptime_seconds", 0),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )

    return HealthReport(
        status=status,
        latencies=latencies,
        caches=caches,
        quality=quality,
        counters=snap.get("counters", {}),
        session_distribution=snap.get("session_distribution", {}),
        anomalies=anomaly_list,
    )
