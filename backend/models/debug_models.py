"""
debug_models.py — Internal diagnostics and trace schemas.

Rules
-----
* NEVER expose these models directly in user-facing API responses.
* All fields here are internal-only. They are gated by is_flow_debug_enabled()
  or equivalent environment guards before being produced.
* Raw embeddings, graph artifacts, ranking intermediates, and full arc series
  are ONLY acceptable here.
* These models wrap the raw dicts currently scattered across the pipeline so
  that debug output has explicit boundaries instead of being appended ad-hoc
  to the mutable playlist result dict.

Covered entities
----------------
  ScoringTrace              — per-track genome/embedding/graph score breakdown
  RecommendationTrace       — collected per-track traces for a playlist
  FlowQualityReport         — typed output from flow_evaluation.evaluate_flow()
  FlowEvaluationReport      — full evaluate_flow() report with all sub-metrics
  CalibrationScenarioReport — single A/B scenario from calibration harness
  CalibrationReport         — full benchmark run with aggregate + regression
  DebugPlayloadEnvelope     — wrapper that gates all debug payloads behind env flag
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Per-track scoring trace (ranking internals — debug only)
# ---------------------------------------------------------------------------

@dataclass
class ScoringTrace:
    """
    Intermediate scoring breakdown for a single track.

    Only produced when debug mode is active.  Never forwarded to users or
    persisted in durable storage.
    """

    track_id: Optional[str] = None
    track_name: Optional[str] = None
    artist: Optional[str] = None
    source: Optional[str] = None

    # Primary scoring components
    genome_score: Optional[float] = None
    popularity_score: Optional[float] = None
    mood_score: Optional[float] = None
    region_score: Optional[float] = None
    quality_score: Optional[float] = None
    primary_score: Optional[float] = None

    # Post-embedding reranking
    semantic_similarity: Optional[float] = None
    pre_embedding_score: Optional[float] = None
    post_embedding_score: Optional[float] = None

    # Graph-flow bonus (additive, post-genome)
    graph_flow_bonus: Optional[float] = None
    pre_graph_score: Optional[float] = None

    # Final pipeline position
    final_rank_score: Optional[float] = None
    pre_exploration_rank: Optional[int] = None

    @classmethod
    def from_track(cls, raw: Dict[str, Any]) -> "ScoringTrace":
        """Extract scoring trace from a raw pipeline track dict."""
        trace = raw.get("recommendation_trace") or {}
        return cls(
            track_id=raw.get("id"),
            track_name=raw.get("name"),
            artist=raw.get("artist"),
            source=raw.get("source"),
            genome_score=trace.get("genome_score"),
            popularity_score=trace.get("popularity_score"),
            mood_score=trace.get("mood_score"),
            region_score=trace.get("region_score"),
            quality_score=trace.get("quality_score"),
            primary_score=trace.get("primary_score"),
            semantic_similarity=trace.get("semantic_similarity"),
            pre_embedding_score=trace.get("pre_embedding_score"),
            post_embedding_score=trace.get("post_embedding_score"),
            graph_flow_bonus=raw.get("graph_flow_bonus") or trace.get("graph_flow_bonus"),
            pre_graph_score=trace.get("pre_graph_score"),
            final_rank_score=trace.get("final_rank_score"),
            pre_exploration_rank=trace.get("pre_exploration_rank"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


# ---------------------------------------------------------------------------
# Full playlist-level recommendation trace
# ---------------------------------------------------------------------------

@dataclass
class RecommendationTrace:
    """
    Collected per-track scoring traces for a full playlist.

    Wraps what ``_attach_final_trace()`` and ``_score_tracks_by_genome()``
    embed into each track dict.  Surfaces them as a structured, separable
    debug artifact instead of inline mutable track mutations.
    """

    playlist_name: Optional[str] = None
    region: Optional[str] = None
    cluster_id: Optional[int] = None
    session_type: Optional[str] = None
    mood: Optional[str] = None
    track_count: int = 0
    familiar_count: int = 0
    discovery_count: int = 0
    exploration_count: int = 0
    track_traces: List[ScoringTrace] = field(default_factory=list)

    @classmethod
    def from_playlist(cls, raw: Dict[str, Any]) -> "RecommendationTrace":
        """Build from a raw pipeline playlist dict (before or after sanitization)."""
        tracks_raw: List[Dict[str, Any]] = raw.get("tracks") or []
        traces = [ScoringTrace.from_track(t) for t in tracks_raw]
        return cls(
            playlist_name=raw.get("name"),
            region=raw.get("region"),
            cluster_id=raw.get("cluster_id"),
            session_type=raw.get("session_type"),
            mood=raw.get("mood"),
            track_count=len(tracks_raw),
            familiar_count=int(raw.get("familiar_count") or 0),
            discovery_count=int(raw.get("discovery_count") or 0),
            exploration_count=int(raw.get("exploration_count") or 0),
            track_traces=traces,
        )

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["track_traces"] = [t for t in d.get("track_traces", [])]
        return {k: v for k, v in d.items() if v is not None}


# ---------------------------------------------------------------------------
# Flow evaluation report (typed output of flow_evaluation.evaluate_flow)
# ---------------------------------------------------------------------------

@dataclass
class FlowQualityReport:
    """Top-level flow quality composite from evaluate_flow()."""

    overall_flow_score: Optional[float] = None
    grade: Optional[str] = None
    flow_entropy: Optional[float] = None
    track_count: Optional[int] = None
    session_type: Optional[str] = None
    component_scores: Dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_raw(cls, raw: Dict[str, Any]) -> "FlowQualityReport":
        fq = raw.get("flow_quality") or raw
        return cls(
            overall_flow_score=fq.get("overall_flow_score"),
            grade=fq.get("grade"),
            flow_entropy=fq.get("flow_entropy"),
            track_count=fq.get("track_count"),
            session_type=fq.get("session_type"),
            component_scores=dict(fq.get("component_scores") or {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class AntiPatternEntry:
    pattern: str = ""
    description: str = ""
    severity: str = "low"
    detail: str = ""


@dataclass
class FlowEvaluationReport:
    """
    Full structured report from flow_evaluation.evaluate_flow().

    Includes arc series, transition distances, anti-pattern list — all of which
    are internal diagnostics that must not appear in user-facing responses or
    persistence records.
    """

    flow_quality: Optional[FlowQualityReport] = None
    transition_metrics: Dict[str, Any] = field(default_factory=dict)
    arc_metrics: Dict[str, Any] = field(default_factory=dict)
    exploration_metrics: Dict[str, Any] = field(default_factory=dict)
    repetition_metrics: Dict[str, Any] = field(default_factory=dict)
    start_end_metrics: Dict[str, Any] = field(default_factory=dict)
    session_adherence: Dict[str, Any] = field(default_factory=dict)
    anti_patterns: List[AntiPatternEntry] = field(default_factory=list)
    anti_pattern_count: int = 0

    @classmethod
    def from_raw(cls, raw: Dict[str, Any]) -> "FlowEvaluationReport":
        """
        Build from the dict returned by ``flow_evaluation.evaluate_flow()``.
        Wraps all sub-dicts including arc energy/valence series (debug only).
        """
        anti_patterns = [
            AntiPatternEntry(
                pattern=ap.get("pattern", ""),
                description=ap.get("description", ""),
                severity=ap.get("severity", "low"),
                detail=ap.get("detail", ""),
            )
            for ap in (raw.get("anti_patterns") or [])
        ]
        return cls(
            flow_quality=FlowQualityReport.from_raw(raw),
            transition_metrics=dict(raw.get("transition_metrics") or {}),
            arc_metrics=dict(raw.get("arc_metrics") or {}),        # includes energy_series
            exploration_metrics=dict(raw.get("exploration_metrics") or {}),
            repetition_metrics=dict(raw.get("repetition_metrics") or {}),
            start_end_metrics=dict(raw.get("start_end_metrics") or {}),
            session_adherence=dict(raw.get("session_adherence") or {}),
            anti_patterns=anti_patterns,
            anti_pattern_count=int(raw.get("anti_pattern_count") or len(anti_patterns)),
        )

    def public_summary(self) -> Dict[str, Any]:
        """
        User-safe subset — only grade, score, and high-severity anti-pattern names.
        Suitable for embedding in a PlaylistResponse without exposing internals.
        """
        fq = self.flow_quality
        high_severity = [ap.pattern for ap in self.anti_patterns if ap.severity == "high"]
        return {
            "overall_flow_score": fq.overall_flow_score if fq else None,
            "grade": fq.grade if fq else None,
            "high_severity_issues": high_severity,
        }

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None}


# ---------------------------------------------------------------------------
# Calibration benchmark report
# ---------------------------------------------------------------------------

@dataclass
class RegressionFinding:
    scenario: str = ""
    metric: str = ""
    value: Optional[float] = None
    threshold: Optional[float] = None
    detail: str = ""


@dataclass
class RegressionDetection:
    regression_count: int = 0
    has_regressions: bool = False
    findings: List[RegressionFinding] = field(default_factory=list)
    thresholds: Dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_raw(cls, raw: Dict[str, Any]) -> "RegressionDetection":
        findings = [
            RegressionFinding(
                scenario=f.get("scenario", ""),
                metric=f.get("metric", ""),
                value=f.get("value"),
                threshold=f.get("threshold"),
                detail=f.get("detail", ""),
            )
            for f in (raw.get("findings") or [])
        ]
        return cls(
            regression_count=int(raw.get("regression_count") or 0),
            has_regressions=bool(raw.get("has_regressions")),
            findings=findings,
            thresholds=dict(raw.get("thresholds") or {}),
        )


@dataclass
class CalibrationScenarioReport:
    """Single A/B scenario result from the calibration benchmark harness."""

    scenario_name: Optional[str] = None
    config_a_label: Optional[str] = None
    config_b_label: Optional[str] = None
    playlist_overlap: Optional[float] = None
    flow_quality_delta: Optional[float] = None
    metric_deltas: Dict[str, float] = field(default_factory=dict)
    diversity_delta: Dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_raw(cls, raw: Dict[str, Any]) -> "CalibrationScenarioReport":
        scenario = raw.get("scenario") or {}
        config_a = raw.get("config_a") or {}
        config_b = raw.get("config_b") or {}
        return cls(
            scenario_name=scenario.get("name") or str(scenario),
            config_a_label=config_a.get("label"),
            config_b_label=config_b.get("label"),
            playlist_overlap=raw.get("playlist_overlap"),
            flow_quality_delta=raw.get("flow_quality_delta"),
            metric_deltas=dict(raw.get("metric_deltas") or {}),
            diversity_delta=dict(raw.get("diversity_delta") or {}),
        )


@dataclass
class CalibrationAggregate:
    average_playlist_overlap: Optional[float] = None
    average_flow_quality_delta: Optional[float] = None
    scenario_count: int = 0


@dataclass
class CalibrationReport:
    """
    Full A/B calibration benchmark report.

    Produced by ``calibration.benchmark_runner.run_ab_benchmark()``.
    Contains regression detection, per-scenario deltas, and aggregate summaries.
    This is debug/internal only — never exposed to end users.
    """

    config_a_label: Optional[str] = None
    config_b_label: Optional[str] = None
    scenario_count: int = 0
    scenario_reports: List[CalibrationScenarioReport] = field(default_factory=list)
    aggregate: Optional[CalibrationAggregate] = None
    regression_detection: Optional[RegressionDetection] = None

    @classmethod
    def from_raw(cls, raw: Dict[str, Any]) -> "CalibrationReport":
        """Build from ``run_ab_benchmark()`` output dict."""
        config_a = raw.get("config_a") or {}
        config_b = raw.get("config_b") or {}
        agg_raw = raw.get("aggregate") or {}
        reg_raw = raw.get("regression_detection") or {}
        scenario_raws = raw.get("scenario_reports") or []

        scenarios = [CalibrationScenarioReport.from_raw(s) for s in scenario_raws]
        aggregate = CalibrationAggregate(
            average_playlist_overlap=agg_raw.get("average_playlist_overlap"),
            average_flow_quality_delta=agg_raw.get("average_flow_quality_delta"),
            scenario_count=int(agg_raw.get("scenario_count") or 0),
        )
        regression = RegressionDetection.from_raw(reg_raw)

        return cls(
            config_a_label=config_a.get("label"),
            config_b_label=config_b.get("label"),
            scenario_count=int(raw.get("scenario_count") or len(scenarios)),
            scenario_reports=scenarios,
            aggregate=aggregate,
            regression_detection=regression,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


# ---------------------------------------------------------------------------
# Debug envelope — gates all debug payloads
# ---------------------------------------------------------------------------

@dataclass
class DebugPlayloadEnvelope:
    """
    Top-level debug payload container.

    Collect all debug artifacts for a single playlist generation cycle here.
    The envelope is only constructed when ``is_flow_debug_enabled()`` returns
    True.  It is never attached to user-facing responses or persistence records.

    Usage
    -----
    from flow_evaluation import is_flow_debug_enabled
    from models.debug_models import DebugPlayloadEnvelope, RecommendationTrace, FlowEvaluationReport

    if is_flow_debug_enabled():
        debug = DebugPlayloadEnvelope(
            recommendation_trace=RecommendationTrace.from_playlist(raw_playlist),
            flow_report=FlowEvaluationReport.from_raw(flow_dict),
        )
        # log / route to internal debug endpoint only
    """

    recommendation_trace: Optional[RecommendationTrace] = None
    flow_report: Optional[FlowEvaluationReport] = None
    calibration_report: Optional[CalibrationReport] = None

    # Arbitrary extra diagnostics (e.g. embedding pool sizes, graph stats)
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {}
        if self.recommendation_trace:
            d["recommendation_trace"] = self.recommendation_trace.to_dict()
        if self.flow_report:
            d["flow_report"] = self.flow_report.to_dict()
        if self.calibration_report:
            d["calibration_report"] = self.calibration_report.to_dict()
        if self.extra:
            d["extra"] = self.extra
        return d
