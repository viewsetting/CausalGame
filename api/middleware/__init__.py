"""
Middleware layer for CausalGame.

This module provides the central data hub (DroneSheet) that mediates between:
- Agent actions (modifying visible values)
- SCM effects (writing environment effects)
- Game judgment (reading standardized DroneState)
"""

from .drone_state import DroneState, EnvironmentEffects
from .drone_sheet import DroneSheet
from .visibility import VisibilityConfig, Visibility

__all__ = [
    'DroneState',
    'EnvironmentEffects',
    'DroneSheet',
    'VisibilityConfig',
    'Visibility',
]
