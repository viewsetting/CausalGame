"""
Game module - Pure judgment functions.

This module contains the game mechanics that are INDEPENDENT of SCM.
All functions here are pure: given DroneState, return JudgmentResult.

Key principle: Game knows NOTHING about environment or SCM.
All effects are pre-computed in DroneState.
"""

from .judge import (
    judge_survival,
    SurvivalJudge,
    CRITICAL_COMPONENTS,
    FAILURE_REASONS,
)
from .damage import (
    calculate_damage,
    apply_def_reduction,
    DamageCalculator,
)
from .combat import (
    simulate_combat,
    CombatSimulator,
    CombatConfig,
)

__all__ = [
    # Judge
    'judge_survival',
    'SurvivalJudge',
    'CRITICAL_COMPONENTS',
    'FAILURE_REASONS',
    # Damage
    'calculate_damage',
    'apply_def_reduction',
    'DamageCalculator',
    # Combat
    'simulate_combat',
    'CombatSimulator',
    'CombatConfig',
]
