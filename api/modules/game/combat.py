"""
Combat simulation - Pure functions for combat mechanics.

This module handles:
- Detection check
- Combat round simulation
- Hit calculation
- Damage distribution

INVARIANT: Combat rules are fixed regardless of experiment.
Modifiers come from DroneState (pre-computed by SCM/middleware).
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, List, Tuple
import random
import math

from ...middleware.drone_state import DroneState, CombatResult
from .damage import DamageCalculator, DamageConfig


@dataclass
class CombatConfig:
    """Configuration for combat simulation."""
    base_damage_per_hit: int = 70          # Base damage per hit (very high to punish no DEF)
    damage_variance: float = 0.3           # Damage variance (±30%)
    base_hit_chance: float = 0.80          # Base hit probability (high)
    critical_hit_chance: float = 0.20      # Critical hit probability
    critical_multiplier: float = 2.0       # Critical hit damage multiplier

    # Target selection weights
    target_weights: Dict[str, float] = field(default_factory=lambda: {
        'engine': 1.5,
        'cockpit': 1.5,
        'wing': 1.2,
        'body': 1.0,
        'antenna': 0.8,
        'camera': 0.5,
        'gun': 0.5,
    })


def check_detection(state: DroneState) -> bool:
    """
    Check if drone is detected.

    Pure function using pre-computed detection_probability from DroneState.

    Args:
        state: DroneState with detection_probability

    Returns:
        True if detected, False otherwise
    """
    roll = random.random()
    return roll < state.detection_probability


def simulate_combat(
    state: DroneState,
    config: Optional[CombatConfig] = None
) -> CombatResult:
    """
    Simulate combat rounds.

    Pure function that takes DroneState and returns CombatResult.
    All modifiers are pre-computed in DroneState.

    Args:
        state: DroneState with combat parameters
        config: Optional combat configuration

    Returns:
        CombatResult with damage and statistics
    """
    config = config or CombatConfig()
    combat_log: List[str] = []
    damage_by_component: Dict[str, int] = {}
    total_damage = 0
    hit_count = 0

    # Get available targets (components with HP > 0)
    targets = [comp for comp, hp in state.hp.items() if hp > 0]

    if not targets:
        combat_log.append("No valid targets - combat skipped")
        return CombatResult(combat_log=combat_log)

    combat_log.append(f"Combat initiated: {state.combat_rounds} rounds")
    combat_log.append(f"Drone agility: {state.agility:.2f}")

    # Simulate each combat round
    for round_num in range(state.combat_rounds):
        combat_log.append(f"--- Round {round_num + 1} ---")

        # Calculate hit chance (agility has minimal effect)
        # Formula: agility barely affects hit chance
        # agility=1.0 → mult=1.0, agility=0.5 → mult=1.05, agility=0.1 → mult=1.09
        # Heavily reduced to make DEF the primary survival factor
        agility_penalty = math.exp(0.1 * (1.0 - state.agility))
        hit_chance = config.base_hit_chance * state.combat_accuracy_modifier
        hit_chance *= agility_penalty
        hit_chance = min(0.95, max(0.05, hit_chance))

        # Roll for hit
        if random.random() < hit_chance:
            hit_count += 1

            # Select target based on weights
            target = _select_target(targets, config.target_weights)

            # Calculate damage
            base_damage = config.base_damage_per_hit

            # Apply variance
            variance = random.uniform(1 - config.damage_variance, 1 + config.damage_variance)
            damage = int(base_damage * variance)

            # Check for critical hit
            is_critical = random.random() < config.critical_hit_chance
            if is_critical:
                damage = int(damage * config.critical_multiplier)
                combat_log.append(f"CRITICAL HIT on {target}!")

            # Apply combat damage modifier from environment
            damage = int(damage * state.combat_damage_modifier)

            # Accumulate damage
            damage_by_component[target] = damage_by_component.get(target, 0) + damage
            total_damage += damage

            combat_log.append(f"Hit {target} for {damage} damage")

            # Update available targets if component destroyed
            # (simplified - actual HP check happens in DroneSheet)
        else:
            combat_log.append("Miss!")

    combat_log.append(f"Combat ended: {hit_count} hits, {total_damage} total damage")

    return CombatResult(
        hit_count=hit_count,
        damage_by_component=damage_by_component,
        total_damage=total_damage,
        combat_log=combat_log,
        rounds_fought=state.combat_rounds,
    )


def _select_target(
    targets: List[str],
    weights: Dict[str, float]
) -> str:
    """
    Select a target based on weights.

    Args:
        targets: Available targets
        weights: Target selection weights

    Returns:
        Selected target component
    """
    if not targets:
        raise ValueError("No targets available")

    if len(targets) == 1:
        return targets[0]

    # Build weighted list
    weighted_targets = []
    for target in targets:
        weight = weights.get(target, 1.0)
        weighted_targets.append((target, weight))

    # Weighted random selection
    total_weight = sum(w for _, w in weighted_targets)
    roll = random.random() * total_weight

    cumulative = 0
    for target, weight in weighted_targets:
        cumulative += weight
        if roll < cumulative:
            return target

    # Fallback
    return targets[-1]


class CombatSimulator:
    """
    Stateful combat simulator with full logging.

    Provides detailed combat simulation with:
    - Round-by-round tracking
    - Damage accumulation
    - Statistical analysis
    """

    def __init__(
        self,
        config: Optional[CombatConfig] = None,
        damage_config: Optional[DamageConfig] = None
    ):
        """
        Initialize CombatSimulator.

        Args:
            config: Combat configuration
            damage_config: Damage calculation configuration
        """
        self.config = config or CombatConfig()
        self.damage_calculator = DamageCalculator(damage_config)

        # Statistics
        self._total_combats = 0
        self._total_hits = 0
        self._total_damage = 0

    def simulate(self, state: DroneState) -> CombatResult:
        """
        Run combat simulation.

        Args:
            state: DroneState to simulate combat for

        Returns:
            CombatResult with full details
        """
        result = simulate_combat(state, self.config)

        # Update statistics
        self._total_combats += 1
        self._total_hits += result.hit_count
        self._total_damage += result.total_damage

        return result

    def check_and_simulate(self, state: DroneState) -> Tuple[bool, Optional[CombatResult]]:
        """
        Check detection and simulate combat if detected.

        Args:
            state: DroneState to check

        Returns:
            (was_detected, combat_result or None)
        """
        was_detected = check_detection(state)

        if was_detected:
            return True, self.simulate(state)
        else:
            return False, None

    def get_statistics(self) -> Dict[str, float]:
        """Get accumulated combat statistics."""
        avg_hits = self._total_hits / self._total_combats if self._total_combats > 0 else 0
        avg_damage = self._total_damage / self._total_combats if self._total_combats > 0 else 0

        return {
            'total_combats': self._total_combats,
            'total_hits': self._total_hits,
            'total_damage': self._total_damage,
            'average_hits_per_combat': avg_hits,
            'average_damage_per_combat': avg_damage,
        }

    def reset_statistics(self) -> None:
        """Reset accumulated statistics."""
        self._total_combats = 0
        self._total_hits = 0
        self._total_damage = 0


def full_simulation(
    state: DroneState,
    combat_config: Optional[CombatConfig] = None
) -> Tuple[bool, CombatResult]:
    """
    Run full detection and combat simulation.

    Convenience function that:
    1. Checks detection
    2. If detected, simulates combat
    3. Returns results

    Args:
        state: DroneState to simulate
        combat_config: Optional combat configuration

    Returns:
        (was_detected, combat_result)
    """
    was_detected = check_detection(state)

    if was_detected:
        result = simulate_combat(state, combat_config)
        result = CombatResult(
            hit_count=result.hit_count,
            damage_by_component=result.damage_by_component,
            total_damage=result.total_damage,
            combat_log=["DETECTED!"] + result.combat_log,
            rounds_fought=result.rounds_fought,
        )
        return True, result
    else:
        return False, CombatResult(
            combat_log=["Not detected - no combat"],
        )
