"""
Runtime contract safeguards for SonicDNA architecture boundaries.

The contracts package is intentionally observation-only. Validators return
structured violations and can emit warnings in debug/dev mode, but they do not
modify recommendation inputs, scoring, ordering, or persistence behavior.
"""

from .contract_validators import enforce_contracts, validate_architectural_contracts
from .invariant_checks import ContractReport, ContractViolation
from .pipeline_integrity import PipelineStage

__all__ = [
    "ContractReport",
    "ContractViolation",
    "PipelineStage",
    "enforce_contracts",
    "validate_architectural_contracts",
]
