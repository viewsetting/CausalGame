"""
Survival judgment - Pure functions for determining drone survival.

This module contains the core game logic that determines whether
a drone survives based on its DroneState.

INVARIANT: These functions do NOT change between experiments.
They only answer: "Given this state, does the drone survive?"
"""

from dataclasses import dataclass
from typing import Dict, Optional, List

from ...middleware.drone_state import DroneState, JudgmentResult


# Critical components that must survive for drone to return
CRITICAL_COMPONENTS = ['engine', 'cockpit', 'wing', 'body']

# Failure reasons for each critical component
FAILURE_REASONS = {
    'engine': 'CRITICAL ENGINE FAILURE - Power systems destroyed',
    'cockpit': 'PILOT/AI CORE LOST - Control systems destroyed',
    'wing': 'AERODYNAMIC FAILURE - Flight surfaces destroyed',
    'body': 'STRUCTURAL COLLAPSE - Airframe integrity lost',
}


def judge_survival(state: DroneState) -> JudgmentResult:
    """
    Pure function: Determine if drone survives.

    Args:
        state: DroneState snapshot (immutable)

    Returns:
        JudgmentResult with status and details

    This function is the CORE of game judgment:
    - Check each critical component HP
    - If any critical HP <= 0, drone is DESTROYED
    - Otherwise, drone RETURNED safely
    """
    # Check each critical component
    for component in CRITICAL_COMPONENTS:
        hp = state.hp.get(component, 0)
        if hp <= 0:
            return JudgmentResult(
                status="DESTROYED",
                fail_reason=FAILURE_REASONS.get(component, f"{component} destroyed"),
                final_hp=state.hp.copy(),
                was_detected=True,  # Must have been detected to be destroyed
            )

    # All critical components intact
    return JudgmentResult(
        status="RETURNED",
        final_hp=state.hp.copy(),
    )


class SurvivalJudge:
    """
    Stateful wrapper for survival judgment.

    Provides additional functionality like damage logging
    and detailed failure analysis.
    """

    def __init__(
        self,
        critical_components: Optional[List[str]] = None,
        failure_reasons: Optional[Dict[str, str]] = None
    ):
        """
        Initialize SurvivalJudge.

        Args:
            critical_components: Override default critical components
            failure_reasons: Override default failure reasons
        """
        self.critical_components = critical_components or CRITICAL_COMPONENTS
        self.failure_reasons = failure_reasons or FAILURE_REASONS.copy()

    def judge(self, state: DroneState) -> JudgmentResult:
        """
        Judge drone survival with detailed logging.

        Args:
            state: DroneState to evaluate

        Returns:
            JudgmentResult with full details
        """
        damage_log = []

        # Check each critical component
        for component in self.critical_components:
            hp = state.hp.get(component, 0)

            if hp <= 0:
                damage_log.append(f"CRITICAL: {component} HP = {hp} <= 0")
                return JudgmentResult(
                    status="DESTROYED",
                    fail_reason=self.failure_reasons.get(component, f"{component} destroyed"),
                    final_hp=state.hp.copy(),
                    was_detected=True,
                    damage_log=damage_log,
                )
            else:
                damage_log.append(f"{component}: HP = {hp} (OK)")

        # All critical components intact
        damage_log.append("All critical components functional - RETURNED")

        return JudgmentResult(
            status="RETURNED",
            final_hp=state.hp.copy(),
            damage_log=damage_log,
        )

    def check_component(self, state: DroneState, component: str) -> bool:
        """Check if a specific component is functional."""
        return state.hp.get(component, 0) > 0

    def get_weakest_component(self, state: DroneState) -> tuple:
        """
        Find the weakest critical component.

        Returns:
            (component_name, hp_value)
        """
        weakest = None
        min_hp = float('inf')

        for component in self.critical_components:
            hp = state.hp.get(component, 0)
            if hp < min_hp:
                min_hp = hp
                weakest = component

        return weakest, min_hp

    def survival_margin(self, state: DroneState) -> int:
        """
        Calculate how much more damage drone can take.

        Returns minimum HP among critical components.
        """
        return min(state.hp.get(c, 0) for c in self.critical_components)
