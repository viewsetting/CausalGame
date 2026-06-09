"""
DroneState - Standardized data structure for Game judgment system.

This module defines the immutable data structures that flow from
DroneSheet middleware to the Game module.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


@dataclass(frozen=True)
class EnvironmentEffects:
    """
    Environment effects computed by SCM.

    This is what SCM writes into DroneSheet.
    """
    # Damage from environment (wind, weather, etc.)
    component_damage: Dict[str, int] = field(default_factory=dict)

    # Detection modifiers
    detection_modifier: float = 1.0          # Multiplier for detection probability
    base_detection_prob: float = 0.70        # Base detection probability (70% base)

    # Combat modifiers
    combat_damage_modifier: float = 1.0      # Multiplier for combat damage
    combat_rounds_modifier: float = 1.0      # Multiplier for combat rounds
    combat_accuracy_modifier: float = 1.0    # Enemy accuracy modifier

    # Navigation modifiers
    navigation_modifier: float = 1.0         # Navigation difficulty

    # Component effectiveness (weather effects on functional components)
    camera_effectiveness: float = 1.0        # Camera performance in weather
    gun_effectiveness: float = 1.0           # Gun performance in weather
    antenna_effectiveness: float = 1.0       # Antenna performance in weather

    # Raw environment data (for logging)
    weather_pattern: float = 0.5             # 0=clear, 1=storm
    raw_environment: Dict[str, float] = field(default_factory=dict)

    # Damage log for debugging
    damage_log: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class DroneState:
    """
    Standardized input for Game judgment system.

    This is an IMMUTABLE snapshot of drone state at judgment time.
    Game module receives this and returns JudgmentResult.

    Design principle: Game knows NOTHING about SCM or environment.
    All effects are pre-computed and encoded in this state.
    """

    # === Core HP values (after all damage applied) ===
    hp: Dict[str, int]                       # {engine: 85, cockpit: 100, ...}

    # === DEF values (for reference, damage already applied) ===
    def_values: Dict[str, int] = field(default_factory=dict)

    # === Derived combat attributes ===
    agility: float = 1.0                     # 0.1~1.0, affects hit probability
    detection_probability: float = 0.15      # Probability of being detected
    combat_rounds: int = 3                   # Number of combat rounds if detected

    # === Component states ===
    antenna_emitting: bool = True            # Is antenna broadcasting signals?
    antenna_hp: int = 50                     # Antenna HP for trap mechanics

    # === Combat modifiers ===
    combat_damage_modifier: float = 1.0      # Damage multiplier in combat
    combat_accuracy_modifier: float = 1.0    # Enemy hit accuracy modifier

    # === Functional component effectiveness ===
    camera_power: float = 1.0                # Camera effectiveness
    gun_power: float = 1.0                   # Gun effectiveness

    # === Environment info (for logging only, not used in judgment) ===
    weather_pattern: float = 0.5
    environment_visible: Dict[str, float] = field(default_factory=dict)

    @property
    def critical_hp(self) -> Dict[str, int]:
        """Return only critical component HP values."""
        critical = ['engine', 'cockpit', 'wing', 'body']
        return {k: v for k, v in self.hp.items() if k in critical}

    @property
    def total_hp(self) -> int:
        """Total HP across all components."""
        return sum(self.hp.values())

    @property
    def total_def(self) -> int:
        """Total DEF across all components."""
        return sum(self.def_values.values())

    @property
    def is_functional(self) -> bool:
        """Check if drone has minimum functionality."""
        return all(self.hp.get(c, 0) > 0 for c in ['engine', 'cockpit'])


@dataclass
class JudgmentResult:
    """
    Result from Game judgment system.

    This is what Game.judge_survival() returns.
    """
    status: str                              # "RETURNED" | "DESTROYED" | "LOST"
    fail_reason: Optional[str] = None        # Why it failed (if applicable)
    final_hp: Dict[str, int] = field(default_factory=dict)

    # Combat statistics
    was_detected: bool = False
    hit_count: int = 0                       # Times hit in combat
    damage_taken: int = 0                    # Total damage taken

    # Detailed logs
    combat_log: List[str] = field(default_factory=list)
    damage_log: List[str] = field(default_factory=list)

    @property
    def survived(self) -> bool:
        """Did the drone survive?"""
        return self.status == "RETURNED"


@dataclass
class CombatResult:
    """
    Result from combat simulation.
    """
    hit_count: int = 0
    damage_by_component: Dict[str, int] = field(default_factory=dict)
    total_damage: int = 0
    combat_log: List[str] = field(default_factory=list)
    rounds_fought: int = 0
