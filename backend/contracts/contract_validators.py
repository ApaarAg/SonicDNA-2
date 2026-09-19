"""
Aggregate contract validators and dev-mode enforcement helpers.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from .invariant_checks import (
    ContractReport,
    ContractViolation,
    check_config_duplication,
    check_score_ranges,
    check_sequence_sensitive_batch,
    warn_contract_violations,
)
from .metric_contracts import validate_metric_terms
from .schema_guards import (
    validate_monitoring_diagnostic_namespaces,
    validate_persistence_boundary,
    validate_response_boundary,
    validate_trace_schema,
)


def enforce_contracts(violations: Iterable[ContractViolation]) -> list[ContractViolation]:
    """
    Emit warnings for violations when contracts are enabled, then return them.

    This is the runtime safeguard entry point. It prefers warning over failure
    and leaves hard-failure policy to tests or explicit caller assertions.
    """

    return warn_contract_violations(violations)


def validate_architectural_contracts(
    *,
    metric_names: Iterable[str] = (),
    response_payload: Mapping[str, Any] | None = None,
    persistence_payload: Mapping[str, Any] | None = None,
    trace_payload: Mapping[str, Any] | None = None,
    score_payload: Mapping[str, Any] | None = None,
    sequence_checks: Sequence[Mapping[str, Any]] = (),
    monitoring_payload: Mapping[str, Any] | None = None,
    diagnostics_payload: Mapping[str, Any] | None = None,
    config_sources: Mapping[str, Any] | None = None,
    emit_warnings: bool = False,
) -> ContractReport:
    """
    Run the complete lightweight architectural contract suite.

    All arguments are optional so callers can validate only the boundary they
    are crossing. No mutation is performed.
    """

    report = ContractReport()
    report.extend(validate_metric_terms(metric_names))

    if response_payload is not None:
        report.extend(validate_response_boundary(response_payload))
    if persistence_payload is not None:
        report.extend(validate_persistence_boundary(persistence_payload))
    if trace_payload is not None:
        report.extend(validate_trace_schema(trace_payload))
    if score_payload is not None:
        report.extend(check_score_ranges(score_payload))
    if sequence_checks:
        report.extend(check_sequence_sensitive_batch(sequence_checks))
    if monitoring_payload is not None or diagnostics_payload is not None:
        report.extend(
            validate_monitoring_diagnostic_namespaces(
                monitoring_payload=monitoring_payload,
                diagnostics_payload=diagnostics_payload,
            )
        )
    if config_sources is not None:
        report.extend(check_config_duplication(config_sources))

    if emit_warnings:
        enforce_contracts(report.violations)
    return report
