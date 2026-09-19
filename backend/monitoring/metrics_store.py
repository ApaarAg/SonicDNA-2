"""
metrics_store.py — Thread-safe rolling metrics collection.

Design
------
* In-memory only — never persists to DB or user state.
* Fixed-size circular buffers (deques) — bounded memory.
* Thread-safe via a single lock per store instance.
* Module-level singleton via get_store() for global pipeline use.
* Zero overhead when not recording (callers check is_monitoring_enabled()).

Activation
----------
Set SONICDNA_MONITOR=1 or SONICDNA_ENV=development.
"""

from __future__ import annotations

import os
import statistics
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Activation guard
# ---------------------------------------------------------------------------

def is_monitoring_enabled() -> bool:
    for key in ("SONICDNA_MONITOR", "DEBUG_MONITOR"):
        if os.getenv(key, "").lower() in {"1", "true", "yes"}:
            return True
    env = (os.getenv("SONICDNA_ENV") or os.getenv("APP_ENV") or "").lower()
    return env in {"development", "dev", "local", "debug"}


# ---------------------------------------------------------------------------
# Rolling metric buffer
# ---------------------------------------------------------------------------

@dataclass
class RollingMetric:
    """Fixed-size circular buffer for a single named metric."""
    name: str
    unit: str = ""
    _values: Deque[Tuple[float, float]] = field(default_factory=lambda: deque(maxlen=500))

    def record(self, value: float, timestamp: Optional[float] = None) -> None:
        self._values.append((timestamp or time.time(), float(value)))

    @property
    def count(self) -> int:
        return len(self._values)

    @property
    def values(self) -> List[float]:
        return [v for _, v in self._values]

    def recent(self, n: int = 50) -> List[float]:
        items = list(self._values)
        return [v for _, v in items[-n:]]

    def since(self, cutoff_ts: float) -> List[float]:
        return [v for ts, v in self._values if ts >= cutoff_ts]

    def stats(self, window: int = 50) -> Dict[str, Any]:
        vals = self.recent(window)
        if not vals:
            return {"count": 0, "mean": None, "p50": None, "p95": None, "min": None, "max": None}
        sorted_vals = sorted(vals)
        p95_idx = max(0, int(len(sorted_vals) * 0.95) - 1)
        return {
            "count": len(vals),
            "mean": round(statistics.mean(vals), 3),
            "p50": round(statistics.median(vals), 3),
            "p95": round(sorted_vals[p95_idx], 3),
            "min": round(min(vals), 3),
            "max": round(max(vals), 3),
        }


# ---------------------------------------------------------------------------
# Counter metric (monotonic)
# ---------------------------------------------------------------------------

@dataclass
class Counter:
    """Simple monotonic counter with windowed rate calculation."""
    name: str
    _total: int = 0
    _timestamps: Deque[float] = field(default_factory=lambda: deque(maxlen=1000))

    def increment(self, n: int = 1) -> None:
        self._total += n
        ts = time.time()
        for _ in range(n):
            self._timestamps.append(ts)

    @property
    def total(self) -> int:
        return self._total

    def rate_per_minute(self, window_seconds: int = 300) -> float:
        cutoff = time.time() - window_seconds
        recent = sum(1 for ts in self._timestamps if ts >= cutoff)
        minutes = window_seconds / 60.0
        return round(recent / minutes, 2) if minutes > 0 else 0.0


# ---------------------------------------------------------------------------
# Distribution tracker (for ratios, percentages)
# ---------------------------------------------------------------------------

@dataclass
class RatioTracker:
    """Tracks a success/failure ratio over a rolling window."""
    name: str
    _hits: Deque[Tuple[float, bool]] = field(default_factory=lambda: deque(maxlen=500))

    def record(self, success: bool) -> None:
        self._hits.append((time.time(), success))

    def rate(self, window: int = 100) -> Optional[float]:
        recent = list(self._hits)[-window:]
        if not recent:
            return None
        successes = sum(1 for _, s in recent if s)
        return round(successes / len(recent), 4)

    def stats(self, window: int = 100) -> Dict[str, Any]:
        recent = list(self._hits)[-window:]
        if not recent:
            return {"count": 0, "rate": None}
        successes = sum(1 for _, s in recent if s)
        return {
            "count": len(recent),
            "successes": successes,
            "failures": len(recent) - successes,
            "rate": round(successes / len(recent), 4),
        }


# ---------------------------------------------------------------------------
# Category distribution tracker
# ---------------------------------------------------------------------------

@dataclass
class DistributionTracker:
    """Tracks category distribution over a rolling window."""
    name: str
    _entries: Deque[Tuple[float, str]] = field(default_factory=lambda: deque(maxlen=500))

    def record(self, category: str) -> None:
        self._entries.append((time.time(), category))

    def distribution(self, window: int = 100) -> Dict[str, float]:
        recent = list(self._entries)[-window:]
        if not recent:
            return {}
        counts: Dict[str, int] = {}
        for _, cat in recent:
            counts[cat] = counts.get(cat, 0) + 1
        total = len(recent)
        return {k: round(v / total, 4) for k, v in sorted(counts.items(), key=lambda x: -x[1])}


# ---------------------------------------------------------------------------
# MetricsStore — centralized rolling metrics
# ---------------------------------------------------------------------------

class MetricsStore:
    """
    Thread-safe, in-memory metrics store for pipeline observability.

    Never persists to disk or user state. Bounded memory via deques.

    Usage
    -----
        store = get_store()
        store.record_latency("recommendation", 245.3)
        store.record_cache("embedding", hit=True)
        store.record_counter("playlist_generated")
        report = store.snapshot()
    """

    def __init__(self, window_size: int = 500) -> None:
        self._lock = threading.Lock()
        self._window = window_size
        self._created_at = time.time()

        # Latency metrics (ms)
        self._latencies: Dict[str, RollingMetric] = {}
        for name in [
            "recommendation_total", "candidate_retrieval", "genome_scoring",
            "embedding_rerank", "graph_rerank", "exploration_injection",
            "flow_sequencing", "flow_evaluation", "spotify_api",
        ]:
            self._latencies[name] = RollingMetric(name=name, unit="ms")

        # Cache hit/miss ratios
        self._caches: Dict[str, RatioTracker] = {}
        for name in ["search", "regional", "embedding"]:
            self._caches[name] = RatioTracker(name=name)

        # Operational ratios
        self._ratios: Dict[str, RatioTracker] = {}
        for name in ["exploration_injection", "playlist_success", "candidate_nonempty"]:
            self._ratios[name] = RatioTracker(name=name)

        # Quality metrics (0-1 scale)
        self._quality: Dict[str, RollingMetric] = {}
        for name in ["playlist_diversity", "flow_quality", "recommendation_stability"]:
            self._quality[name] = RollingMetric(name=name, unit="score")

        # Counters
        self._counters: Dict[str, Counter] = {}
        for name in [
            "playlist_generated", "playlist_failed", "empty_candidates",
            "cache_flush", "api_errors",
        ]:
            self._counters[name] = Counter(name=name)

        # Session profile distribution
        self._session_dist = DistributionTracker(name="session_type")

    # ── Recording API ───────────────────────────────────────────────────

    def record_latency(self, metric: str, duration_ms: float) -> None:
        with self._lock:
            if metric in self._latencies:
                self._latencies[metric].record(duration_ms)

    def record_cache(self, cache_name: str, hit: bool) -> None:
        with self._lock:
            if cache_name in self._caches:
                self._caches[cache_name].record(hit)

    def record_ratio(self, name: str, success: bool) -> None:
        with self._lock:
            if name in self._ratios:
                self._ratios[name].record(success)

    def record_quality(self, name: str, score: float) -> None:
        with self._lock:
            if name in self._quality:
                self._quality[name].record(max(0.0, min(1.0, score)))

    def record_counter(self, name: str, n: int = 1) -> None:
        with self._lock:
            if name in self._counters:
                self._counters[name].increment(n)

    def record_session_type(self, session_type: str) -> None:
        with self._lock:
            self._session_dist.record(session_type or "default")

    # ── Snapshot API ────────────────────────────────────────────────────

    def snapshot(self, window: int = 50) -> Dict[str, Any]:
        """Return a full metrics snapshot for health reporting."""
        with self._lock:
            return {
                "uptime_seconds": round(time.time() - self._created_at, 1),
                "latencies": {
                    name: m.stats(window) for name, m in self._latencies.items()
                    if m.count > 0
                },
                "cache_rates": {
                    name: r.stats(window) for name, r in self._caches.items()
                    if r._hits
                },
                "operational_rates": {
                    name: r.stats(window) for name, r in self._ratios.items()
                    if r._hits
                },
                "quality_metrics": {
                    name: m.stats(window) for name, m in self._quality.items()
                    if m.count > 0
                },
                "counters": {
                    name: {"total": c.total, "rate_per_min": c.rate_per_minute()}
                    for name, c in self._counters.items()
                    if c.total > 0
                },
                "session_distribution": self._session_dist.distribution(window),
            }

    def get_latency_stats(self, metric: str, window: int = 50) -> Dict[str, Any]:
        with self._lock:
            m = self._latencies.get(metric)
            return m.stats(window) if m else {}

    def get_cache_rate(self, cache_name: str, window: int = 100) -> Optional[float]:
        with self._lock:
            r = self._caches.get(cache_name)
            return r.rate(window) if r else None

    def reset(self) -> None:
        """Reset all metrics — useful for test isolation."""
        with self._lock:
            for m in self._latencies.values():
                m._values.clear()
            for r in self._caches.values():
                r._hits.clear()
            for r in self._ratios.values():
                r._hits.clear()
            for m in self._quality.values():
                m._values.clear()
            for c in self._counters.values():
                c._total = 0
                c._timestamps.clear()
            self._session_dist._entries.clear()
            self._created_at = time.time()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_store: Optional[MetricsStore] = None
_store_lock = threading.Lock()


def get_store() -> MetricsStore:
    """Return the module-level MetricsStore singleton (lazy init)."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = MetricsStore()
    return _store
