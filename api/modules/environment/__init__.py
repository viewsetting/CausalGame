"""
Environment module - SCM and environment variable handling.

This module contains:
- CausalSCM: Abstract base class for all SCMs
- SCM Registry: Factory for creating SCM instances
- Individual SCM implementations in separate files
- EnvironmentGenerator: Variable generation with discovery system
- EnvironmentInterpreter: LLM-powered variable discovery interface

Key principle: Only this module changes for different causal experiments.
Game module remains fixed.

Available SCMs:
- DefaultSCM ("base"): Minimal SCM with no traps
- AntennaTrapSCM ("antenna_trap"): Antenna detection trap experiment
"""

from .scm_base import (
    CausalSCM,
    BaseSCM,
    EnvironmentState,
    CausalVariable,
    StructuralEquation,
)
from .scm_registry import (
    get_scm_for_experiment,
    register_scm,
    list_experiments,
    SCM_REGISTRY,
)

# Import SCM classes for direct access
from .default_scm import DefaultSCM
from .antenna_trap_scm import AntennaTrapSCM

# Import environment generator and interpreter
from .generator import EnvironmentGenerator
from .interpreter import EnvironmentInterpreter

__all__ = [
    # Base classes
    'CausalSCM',
    'BaseSCM',
    'EnvironmentState',
    'CausalVariable',
    'StructuralEquation',
    # Registry
    'get_scm_for_experiment',
    'register_scm',
    'list_experiments',
    'SCM_REGISTRY',
    # SCM implementations
    'DefaultSCM',
    'AntennaTrapSCM',
    # Environment utilities
    'EnvironmentGenerator',
    'EnvironmentInterpreter',
]
