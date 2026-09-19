"""
Rule-based diagnostic correlation helpers.

This package is optional/dev-only and never changes recommendation behavior.
"""

from .diagnostic_engine import DiagnosticEngine, is_diagnostics_enabled
from .correlation_rules import DiagnosticHypothesis, SupportingSignal
from .diagnostics_report import build_diagnostics_report, example_diagnostic_reports

__all__ = [
    "DiagnosticEngine",
    "DiagnosticHypothesis",
    "SupportingSignal",
    "build_diagnostics_report",
    "example_diagnostic_reports",
    "is_diagnostics_enabled",
]
