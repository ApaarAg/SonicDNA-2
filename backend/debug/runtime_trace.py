"""
runtime_trace.py — Unified runtime observability for the recommendation pipeline.

Provides structured engineering traces covering timing, attribution, ranking
path, promotion/demotion events, exploration decisions, flow adjustments,
cache usage, and failure warnings across all pipeline stages.

Design principles
-----------------
* Zero overhead when disabled (default).  Activation via env var or explicit opt-in.
* Never mutates recommendation behavior — observation only.
* Never persists into canonical state or user-facing responses.
* Thread-safe per-request via PipelineTrace instances.
* All timing is monotonic (time.perf_counter).

Activation
----------
Set ``SONICDNA_TRACE=1`` or ``DEBUG_TRACE=1`` in the environment,
or pass ``trace=True`` to individual helpers.

Usage
-----
    from debug.runtime_trace import PipelineTrace, is_trace_enabled, timed

    # --- Per-request trace ---
    trace = PipelineTrace()
    trace.start("candidate_retrieval")
    # ... do work ...
    trace.stop("candidate_retrieval", metadata={"count": 120})

    # --- Decorator for method timing ---
    @timed("embedding_rerank")
    def _apply_user_embedding_similarity(self, ...):
        ...

    # --- At end of request ---
    if is_trace_enabled():
        print(json.dumps(trace.to_dict(), indent=2))
"""

from __future__ import annotations

import functools
import json
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional


# ---------------------------------------------------------------------------
# Activation guard
# ---------------------------------------------------------------------------

def is_trace_enabled() -> bool:
    """Return True when runtime tracing is active."""
    for key in ("SONICDNA_TRACE", "DEBUG_TRACE"):
        if os.getenv(key, "").lower() in {"1", "true", "yes"}:
            return True
    env = (os.getenv("SONICDNA_ENV") or os.getenv("APP_ENV") or "").lower()
    return env in {"development", "dev", "local", "debug"}


# ---------------------------------------------------------------------------
# Event dataclasses
# ---------------------------------------------------------------------------

@dataclass
class TimingEntry:
    """Wall-clock span for a single pipeline stage."""
    stage: str = ""
    start_ts: float = 0.0
    end_ts: float = 0.0
    duration_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "stage": self.stage,
            "duration_ms": round(self.duration_ms, 2),
        }
        if self.metadata:
            d["metadata"] = self.metadata
        return d


@dataclass
class RankingStep:
    """A single step in the ranking path (position change for a track)."""
    track_id: str = ""
    track_name: str = ""
    stage: str = ""
    rank_before: Optional[int] = None
    rank_after: Optional[int] = None
    score_before: Optional[float] = None
    score_after: Optional[float] = None
    delta: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class PromotionEvent:
    """A track that moved up significantly between pipeline stages."""
    track_id: str = ""
    track_name: str = ""
    from_stage: str = ""
    to_stage: str = ""
    rank_change: int = 0
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExplorationEvent:
    """Record of an exploration injection decision."""
    track_id: str = ""
    track_name: str = ""
    artist: str = ""
    action: str = ""           # "injected" | "rejected" | "replaced"
    exploration_score: Optional[float] = None
    semantic_relatedness: Optional[float] = None
    position: Optional[int] = None
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class FlowAdjustment:
    """Record of a flow-sequencing position change."""
    track_id: str = ""
    track_name: str = ""
    original_position: Optional[int] = None
    new_position: Optional[int] = None
    flow_score: Optional[float] = None
    zone: Optional[str] = None       # "intro" | "body" | "outro"
    dominant_signal: str = ""        # e.g. "smooth_reward", "abrupt_penalty"

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class CacheEvent:
    """Record of a cache hit or miss."""
    cache_name: str = ""             # "search", "regional", "embedding"
    hit: bool = False
    key_hint: str = ""               # sanitized, no secrets
    entry_count: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class FailureWarning:
    """Non-fatal failure observed during the pipeline."""
    stage: str = ""
    error_type: str = ""
    message: str = ""
    recoverable: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# PipelineTrace — per-request collector
# ---------------------------------------------------------------------------

class PipelineTrace:
    """
    Collects structured observability data for a single playlist generation
    request.  Designed to be instantiated at the top of a request handler
    and serialized at the end.

    Thread-safe: each request gets its own instance.

    Example
    -------
        trace = PipelineTrace()
        with trace.span("candidate_retrieval"):
            tracks = spotify.search_regional_tracks(...)
        trace.add_cache_event("regional", hit=True)
        trace.record_ranking_snapshot("genome_scoring", scored_tracks)
        ...
        if is_trace_enabled():
            log_trace(trace)
    """

    def __init__(self, request_id: Optional[str] = None) -> None:
        self._lock = threading.Lock()
        self.request_id = request_id or f"req_{int(time.time() * 1000) % 1_000_000_000}"
        self.created_at = time.time()
        self._timings: Dict[str, TimingEntry] = {}
        self._active_starts: Dict[str, float] = {}
        self.ranking_path: List[RankingStep] = []
        self.promotion_events: List[PromotionEvent] = []
        self.exploration_events: List[ExplorationEvent] = []
        self.flow_adjustments: List[FlowAdjustment] = []
        self.cache_events: List[CacheEvent] = []
        self.failure_warnings: List[FailureWarning] = []
        self._ranking_snapshots: Dict[str, List[str]] = {}

    # ── Timing ──────────────────────────────────────────────────────────

    def start(self, stage: str) -> None:
        """Begin timing a pipeline stage."""
        with self._lock:
            self._active_starts[stage] = time.perf_counter()

    def stop(self, stage: str, *, metadata: Optional[Dict[str, Any]] = None) -> float:
        """End timing and return elapsed ms."""
        end = time.perf_counter()
        with self._lock:
            start = self._active_starts.pop(stage, end)
            duration_ms = (end - start) * 1000.0
            self._timings[stage] = TimingEntry(
                stage=stage,
                start_ts=start,
                end_ts=end,
                duration_ms=duration_ms,
                metadata=metadata or {},
            )
            return duration_ms

    @contextmanager
    def span(self, stage: str, **extra_meta):
        """Context-manager for timing a stage. Catches and records failures."""
        self.start(stage)
        meta: Dict[str, Any] = dict(extra_meta)
        try:
            yield meta  # caller can add keys to meta inside the block
        except Exception as exc:
            meta["error"] = str(exc)
            self.add_warning(stage, type(exc).__name__, str(exc))
            raise
        finally:
            self.stop(stage, metadata=meta if meta else None)

    def get_duration_ms(self, stage: str) -> Optional[float]:
        entry = self._timings.get(stage)
        return round(entry.duration_ms, 2) if entry else None

    # ── Ranking snapshots & diff ────────────────────────────────────────

    def record_ranking_snapshot(
        self,
        stage: str,
        scored_tracks: List[dict],
        *,
        id_key: str = "id",
        score_key: str = "score",
    ) -> None:
        """
        Snapshot the current ranking order at a pipeline stage.
        Call at genome_scoring, embedding_rerank, graph_rerank, etc.
        """
        with self._lock:
            ids = []
            for item in scored_tracks:
                track = item.get("track", item)
                tid = track.get(id_key) or track.get("name", "?")
                ids.append(str(tid))
            self._ranking_snapshots[stage] = ids

    def diff_rankings(self, stage_a: str, stage_b: str, *, top_n: int = 10) -> List[RankingStep]:
        """
        Compare rankings between two stages and return tracks that moved.
        Automatically detects promotions (>= 3 positions up).
        """
        snap_a = self._ranking_snapshots.get(stage_a, [])
        snap_b = self._ranking_snapshots.get(stage_b, [])
        if not snap_a or not snap_b:
            return []

        pos_a = {tid: i for i, tid in enumerate(snap_a)}
        steps: List[RankingStep] = []

        for rank_b, tid in enumerate(snap_b[:top_n]):
            rank_a = pos_a.get(tid)
            delta = (rank_a - rank_b) if rank_a is not None else None
            step = RankingStep(
                track_id=tid,
                stage=f"{stage_a}->{stage_b}",
                rank_before=rank_a,
                rank_after=rank_b,
                delta=delta,
            )
            steps.append(step)
            if delta is not None and delta >= 3:
                self.promotion_events.append(PromotionEvent(
                    track_id=tid,
                    from_stage=stage_a,
                    to_stage=stage_b,
                    rank_change=delta,
                    reason=f"promoted {delta} positions",
                ))

        with self._lock:
            self.ranking_path.extend(steps)
        return steps

    # ── Event recording ─────────────────────────────────────────────────

    def add_exploration_event(
        self,
        track_id: str,
        action: str,
        *,
        track_name: str = "",
        artist: str = "",
        exploration_score: Optional[float] = None,
        semantic_relatedness: Optional[float] = None,
        position: Optional[int] = None,
        reason: str = "",
    ) -> None:
        with self._lock:
            self.exploration_events.append(ExplorationEvent(
                track_id=track_id,
                track_name=track_name,
                artist=artist,
                action=action,
                exploration_score=exploration_score,
                semantic_relatedness=semantic_relatedness,
                position=position,
                reason=reason,
            ))

    def add_flow_adjustment(
        self,
        track_id: str,
        original_position: int,
        new_position: int,
        *,
        track_name: str = "",
        flow_score: Optional[float] = None,
        zone: Optional[str] = None,
        dominant_signal: str = "",
    ) -> None:
        with self._lock:
            self.flow_adjustments.append(FlowAdjustment(
                track_id=track_id,
                track_name=track_name,
                original_position=original_position,
                new_position=new_position,
                flow_score=flow_score,
                zone=zone,
                dominant_signal=dominant_signal,
            ))

    def add_cache_event(
        self,
        cache_name: str,
        hit: bool,
        *,
        key_hint: str = "",
        entry_count: Optional[int] = None,
    ) -> None:
        with self._lock:
            self.cache_events.append(CacheEvent(
                cache_name=cache_name,
                hit=hit,
                key_hint=key_hint,
                entry_count=entry_count,
            ))

    def add_warning(
        self,
        stage: str,
        error_type: str,
        message: str,
        *,
        recoverable: bool = True,
    ) -> None:
        with self._lock:
            self.failure_warnings.append(FailureWarning(
                stage=stage,
                error_type=error_type,
                message=message,
                recoverable=recoverable,
            ))

    # ── Serialization ───────────────────────────────────────────────────

    def total_duration_ms(self) -> float:
        if not self._timings:
            return 0.0
        earliest = min(t.start_ts for t in self._timings.values())
        latest = max(t.end_ts for t in self._timings.values())
        return round((latest - earliest) * 1000.0, 2)

    def to_dict(self) -> Dict[str, Any]:
        """Full structured trace output for engineering inspection."""
        # Sort timings by start time
        sorted_timings = sorted(self._timings.values(), key=lambda t: t.start_ts)
        return {
            "request_id": self.request_id,
            "total_duration_ms": self.total_duration_ms(),
            "timing": {t.stage: t.to_dict() for t in sorted_timings},
            "ranking_path": [s.to_dict() for s in self.ranking_path] if self.ranking_path else [],
            "promotion_events": [e.to_dict() for e in self.promotion_events] if self.promotion_events else [],
            "exploration_events": [e.to_dict() for e in self.exploration_events] if self.exploration_events else [],
            "flow_adjustments": [a.to_dict() for a in self.flow_adjustments] if self.flow_adjustments else [],
            "cache_events": [c.to_dict() for c in self.cache_events] if self.cache_events else [],
            "failure_warnings": [w.to_dict() for w in self.failure_warnings] if self.failure_warnings else [],
        }

    def summary_line(self) -> str:
        """One-line log summary."""
        parts = [f"trace={self.request_id}"]
        parts.append(f"total={self.total_duration_ms():.0f}ms")
        for stage in ["candidate_retrieval", "genome_scoring", "embedding_rerank",
                       "graph_rerank", "exploration_injection", "flow_sequencing"]:
            d = self.get_duration_ms(stage)
            if d is not None:
                parts.append(f"{stage}={d:.0f}ms")
        if self.cache_events:
            hits = sum(1 for c in self.cache_events if c.hit)
            parts.append(f"cache_hits={hits}/{len(self.cache_events)}")
        if self.failure_warnings:
            parts.append(f"warnings={len(self.failure_warnings)}")
        return " ".join(parts)


# ---------------------------------------------------------------------------
# Decorator for method/function timing
# ---------------------------------------------------------------------------

def timed(stage: str, *, trace_attr: str = "_trace"):
    """
    Decorator that records method timing into a PipelineTrace.

    Looks for the trace object on ``self.<trace_attr>`` (for methods) or
    as the first positional argument (for functions receiving a trace).
    No-ops gracefully if no trace is found.

    Usage
    -----
        class PlaylistGenerator:
            _trace: Optional[PipelineTrace] = None

            @timed("genome_scoring")
            def _score_tracks_by_genome(self, ...):
                ...
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            # Find trace: try self.<trace_attr>, then kwargs, then skip
            trace: Optional[PipelineTrace] = None
            if args and hasattr(args[0], trace_attr):
                trace = getattr(args[0], trace_attr, None)
            if trace is None:
                trace = kwargs.get("trace")
            if trace is None or not isinstance(trace, PipelineTrace):
                return fn(*args, **kwargs)

            trace.start(stage)
            try:
                result = fn(*args, **kwargs)
                return result
            except Exception as exc:
                trace.add_warning(stage, type(exc).__name__, str(exc))
                raise
            finally:
                trace.stop(stage)

        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Trace-aware helpers for pipeline integration
# ---------------------------------------------------------------------------

def trace_ranking_diff(
    trace: Optional[PipelineTrace],
    stage_a: str,
    stage_b: str,
    scored_tracks: List[dict],
    *,
    id_key: str = "id",
) -> None:
    """Snapshot current ranking at stage_b and diff against stage_a."""
    if trace is None:
        return
    trace.record_ranking_snapshot(stage_b, scored_tracks, id_key=id_key)
    trace.diff_rankings(stage_a, stage_b)


def trace_exploration(
    trace: Optional[PipelineTrace],
    before_tracks: List[dict],
    after_tracks: List[dict],
) -> None:
    """Record which exploration tracks were injected."""
    if trace is None:
        return
    before_ids = {(t.get("id") or t.get("name", "")) for t in before_tracks}
    for i, track in enumerate(after_tracks):
        tid = track.get("id") or track.get("name", "")
        if tid not in before_ids and track.get("exploration"):
            meta = track.get("exploration_meta") or {}
            trace.add_exploration_event(
                track_id=tid,
                action="injected",
                track_name=track.get("name", ""),
                artist=track.get("artist", ""),
                exploration_score=track.get("exploration_score"),
                semantic_relatedness=meta.get("semantic_relatedness"),
                position=i,
            )


def trace_flow_reorder(
    trace: Optional[PipelineTrace],
    before_tracks: List[dict],
    after_tracks: List[dict],
) -> None:
    """Record flow-sequencing position changes."""
    if trace is None:
        return
    before_order = {
        (t.get("id") or t.get("name", "")): i
        for i, t in enumerate(before_tracks)
    }
    for new_pos, track in enumerate(after_tracks):
        tid = track.get("id") or track.get("name", "")
        old_pos = before_order.get(tid)
        if old_pos is not None and old_pos != new_pos:
            ft = track.get("flow_trace") or {}
            # Determine dominant signal
            signals = {
                "smooth_reward": ft.get("smooth_reward", 0),
                "zone_reward": ft.get("zone_reward", 0),
                "abrupt_penalty": -ft.get("abrupt_penalty", 0),
                "spike_penalty": -ft.get("spike_penalty", 0),
                "cluster_penalty": -ft.get("cluster_penalty", 0),
            }
            dominant = max(signals, key=lambda k: abs(signals[k])) if signals else ""
            zone_idx = None
            fp = track.get("flow_position")
            total = len(after_tracks)
            if fp is not None and total > 0:
                frac = fp / total
                zone_idx = "intro" if frac < 0.2 else ("outro" if frac > 0.83 else "body")

            trace.add_flow_adjustment(
                track_id=tid,
                track_name=track.get("name", ""),
                original_position=old_pos,
                new_position=new_pos,
                flow_score=ft.get("flow_score"),
                zone=zone_idx,
                dominant_signal=dominant,
            )


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

def log_trace(trace: PipelineTrace, *, verbose: bool = False) -> None:
    """Print trace to stdout (dev-only convenience)."""
    if verbose:
        print(json.dumps(trace.to_dict(), indent=2, default=str))
    else:
        print(f"[runtime_trace] {trace.summary_line()}")


def log_trace_if_enabled(trace: Optional[PipelineTrace], *, verbose: bool = False) -> None:
    """Conditional log — no-ops if trace is None or tracing is disabled."""
    if trace is not None and is_trace_enabled():
        log_trace(trace, verbose=verbose)
