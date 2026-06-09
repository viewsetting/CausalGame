"""
Analysis sandbox for CausalGame agent.

This package provides an isolated execution environment for data analysis
that has access to pandas/numpy but NOT direct API access.
"""

from .context import (
    AnalysisContext,
    AnalysisResult,
)
from .workspace import SessionWorkspace

__all__ = [
    "AnalysisContext",
    "AnalysisResult",
    "SessionWorkspace",
]
