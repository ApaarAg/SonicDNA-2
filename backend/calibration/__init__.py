"""
Offline calibration harness for SonicDNA recommendations.

This package wraps existing generation and evaluation surfaces. It does not
write benchmark state, train models, tune weights, or alter production flow.
"""

from .benchmark_runner import detect_regressions, run_ab_benchmark, run_stability_benchmark
from .human_perception import (
    PERCEPTUAL_STRESS_TEST_SCENARIOS,
    analyze_human_perception,
    compare_human_reviews_to_metrics,
    human_review_schema,
    normalize_human_review,
    summarize_human_reviews,
)
from .playlist_diff import compare_playlists, compare_repeated_runs
from .scenario_runner import SCENARIOS, Scenario, run_scenario

__all__ = [
    "PERCEPTUAL_STRESS_TEST_SCENARIOS",
    "SCENARIOS",
    "Scenario",
    "analyze_human_perception",
    "compare_playlists",
    "compare_human_reviews_to_metrics",
    "compare_repeated_runs",
    "detect_regressions",
    "human_review_schema",
    "normalize_human_review",
    "run_ab_benchmark",
    "run_scenario",
    "run_stability_benchmark",
    "summarize_human_reviews",
]
