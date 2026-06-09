"""
Damage calculation - Pure functions for damage computation.

This module handles:
- DEF reduction calculation
- Damage application
- Damage distribution

INVARIANT: Same formulas for all experiments.
"""

from dataclasses import dataclass
from typing import Dict, Optional, List, Tuple
import random


@dataclass
class DamageConfig:
    """Configuration for damage calculation."""
    reduction_factor: float = 0.5      # DEF to damage reduction ratio
    min_damage: int = 1                # Minimum damage after reduction
    max_reduction_percent: float = 0.9  # Maximum damage reduction (90%)


def apply_def_reduction(
    raw_damage: int,
    def_value: int,
    reduction_factor: float = 0.5,
    min_damage: int = 1
) -> int:
    """
    Calculate actual damage after DEF reduction.

    Pure function: damage = max(min_damage, raw - def * factor)

    Args:
        raw_damage: Raw damage before reduction
        def_value: DEF value of the target
        reduction_factor: How much DEF reduces damage (default 0.5)
        min_damage: Minimum damage that always goes through

    Returns:
        Actual damage after DEF reduction
    """
    reduction = int(def_value * reduction_factor)
    actual = raw_damage - reduction
    return max(min_damage, actual)


def calculate_damage(
    raw_damage: int,
    def_value: int,
    config: Optional[DamageConfig] = None
) -> int:
    """
    Calculate damage with full configuration.

    Args:
        raw_damage: Raw damage value
        def_value: DEF value for reduction
        config: Optional damage configuration

    Returns:
        Final damage value
    """
    config = config or DamageConfig()

    # Calculate reduction
    reduction = int(def_value * config.reduction_factor)

    # Cap reduction at max_reduction_percent
    max_reduction = int(raw_damage * config.max_reduction_percent)
    reduction = min(reduction, max_reduction)

    # Apply reduction
    actual = raw_damage - reduction

    return max(config.min_damage, actual)


class DamageCalculator:
    """
    Stateful damage calculator with configuration.

    Provides methods for:
    - Single target damage
    - Multi-target damage distribution
    - Damage logging
    """

    def __init__(self, config: Optional[DamageConfig] = None):
        """
        Initialize DamageCalculator.

        Args:
            config: Damage calculation configuration
        """
        self.config = config or DamageConfig()
        self._damage_log: List[str] = []

    def calculate(
        self,
        component: str,
        raw_damage: int,
        def_value: int
    ) -> int:
        """
        Calculate damage for a single component.

        Args:
            component: Target component name
            raw_damage: Raw damage value
            def_value: DEF value for reduction

        Returns:
            Actual damage after DEF
        """
        actual = calculate_damage(raw_damage, def_value, self.config)
        self._damage_log.append(
            f"{component}: {raw_damage} raw - {int(def_value * self.config.reduction_factor)} DEF = {actual} actual"
        )
        return actual

    def apply_damage(
        self,
        hp: Dict[str, int],
        damage_map: Dict[str, int],
        def_map: Dict[str, int]
    ) -> Dict[str, int]:
        """
        Apply damage to HP with DEF reduction.

        Args:
            hp: Current HP values {component: hp}
            damage_map: Raw damage per component {component: damage}
            def_map: DEF values {component: def}

        Returns:
            New HP values after damage
        """
        result = hp.copy()

        for component, raw_dmg in damage_map.items():
            if component in result:
                def_value = def_map.get(component, 0)
                actual_dmg = self.calculate(component, raw_dmg, def_value)
                result[component] = max(0, result[component] - actual_dmg)

        return result

    def distribute_damage(
        self,
        total_damage: int,
        targets: List[str],
        weights: Optional[Dict[str, float]] = None
    ) -> Dict[str, int]:
        """
        Distribute total damage across multiple targets.

        Args:
            total_damage: Total damage to distribute
            targets: List of target components
            weights: Optional weight per target (default: uniform)

        Returns:
            Damage per target {component: damage}
        """
        if not targets:
            return {}

        if weights is None:
            # Uniform distribution
            base_damage = total_damage // len(targets)
            remainder = total_damage % len(targets)
            result = {t: base_damage for t in targets}
            # Distribute remainder randomly
            for i in range(remainder):
                target = random.choice(targets)
                result[target] += 1
            return result
        else:
            # Weighted distribution
            total_weight = sum(weights.get(t, 1.0) for t in targets)
            result = {}
            remaining = total_damage

            for i, target in enumerate(targets):
                weight = weights.get(target, 1.0)
                if i == len(targets) - 1:
                    # Last target gets remainder
                    result[target] = remaining
                else:
                    damage = int(total_damage * weight / total_weight)
                    result[target] = damage
                    remaining -= damage

            return result

    def get_damage_log(self) -> List[str]:
        """Get accumulated damage log."""
        return self._damage_log.copy()

    def clear_log(self) -> None:
        """Clear damage log."""
        self._damage_log.clear()


