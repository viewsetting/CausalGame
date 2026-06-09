"""
DroneSheet - Central middleware for drone data management.

This is the single source of truth for all drone attributes:
- Component HP values (hidden from agent)
- Component DEF values (agent visible)
- Component ATK values (agent visible)
- Derived values (computed, visibility controlled)

Data Flow:
1. Agent sets DEF values via set_def_design()
2. SCM writes environment effects via apply_environment_effects()
3. Combat system writes damage via apply_combat_damage()
4. Game reads state via to_drone_state()
5. Results filtered for agent via filter_for_agent()
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple
import math
import random
import numpy as np
import copy
import logging

from .drone_state import DroneState, EnvironmentEffects, JudgmentResult
from .visibility import VisibilityConfig, Visibility

logger = logging.getLogger(__name__)


# Default component configuration
DEFAULT_COMPONENTS = {
    "engine": {"hp": 100, "default_def": 20, "is_critical": True},
    "cockpit": {"hp": 100, "default_def": 20, "is_critical": True},
    "wing": {"hp": 80, "default_def": 15, "is_critical": True},
    "body": {"hp": 80, "default_def": 15, "is_critical": True},
    "antenna": {"hp": 50, "default_def": 10, "is_critical": False},
    "camera": {"hp": 40, "default_def": 5, "is_critical": False, "has_eft": True},
    "gun": {"hp": 40, "default_def": 5, "is_critical": False, "has_atk": True, "default_atk": 20},
}

# Critical components that must survive
CRITICAL_COMPONENTS = ['engine', 'cockpit', 'wing', 'body']


@dataclass
class AgilityConfig:
    """Configuration for agility calculation from DEF."""
    base_agility: float = 1.0
    linear_coefficient: float = 0.002
    exponential_decay_scale: float = 200.0
    min_agility: float = 0.1
    max_agility: float = 1.0


@dataclass
class ComponentConfig:
    """Configuration for a single component."""
    name: str
    hp: int
    default_def: int
    is_critical: bool = False
    has_atk: bool = False
    has_eft: bool = False
    default_atk: int = 0


class DroneSheet:
    """
    Drone data middleware.

    This class is the central hub that:
    1. Stores all drone attributes (HP, DEF, ATK, derived values)
    2. Controls what Agent can see vs what is hidden
    3. Computes derived values (Agility, Signal Strength, Stealth)
    4. Mediates between Agent actions and Game simulation
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        visibility_config: Optional[VisibilityConfig] = None
    ):
        """
        Initialize DroneSheet with configuration.

        Args:
            config: Experiment configuration dict
            visibility_config: Optional visibility configuration
        """
        config = config or {}

        # Load component configuration
        self._components: Dict[str, ComponentConfig] = {}
        self._load_components(config)

        # === Core storage ===
        # HP values (hidden from agent)
        self._hp: Dict[str, int] = {}

        # DEF values (agent visible)
        self._def: Dict[str, int] = {}

        # ATK values (agent visible)
        self._atk: Dict[str, int] = {}

        # EFT (effectiveness) values for functional components
        self._eft: Dict[str, float] = {}

        # === Derived values ===
        self._total_def: int = 0
        self._total_hp: int = 0
        self._agility: float = 1.0
        self._signal_strength: float = 1.0
        self._stealth_rating: float = 0.0
        self._firepower: float = 0.0

        # === Environment effects (written by SCM) ===
        self._env_effects: Optional[EnvironmentEffects] = None
        self._env_damage_applied: bool = False

        # === Combat state ===
        self._combat_damage: Dict[str, int] = {}
        self._hit_count: int = 0
        self._combat_log: List[str] = []

        # === Equipment (discrete choices) ===
        self._equipment: Dict[str, str] = {}  # slot -> choice_id
        self._equipment_effects: Optional['EquipmentEffects'] = None

        # === Configuration ===
        self._agility_config = AgilityConfig(
            **config.get('agility_system', {})
        )
        self._visibility = visibility_config or VisibilityConfig.from_config(config)
        self._def_reduction_factor = config.get('def_reduction_factor', 0.3)  # DEF is less effective

        # Initialize with defaults
        self._initialize_defaults()

    def _load_components(self, config: Dict[str, Any]) -> None:
        """Load component definitions from config or use defaults."""
        components_config = config.get('drone', {}).get('components', DEFAULT_COMPONENTS)

        for name, comp_cfg in components_config.items():
            if isinstance(comp_cfg, dict):
                self._components[name] = ComponentConfig(
                    name=name,
                    hp=comp_cfg.get('hp', 50),
                    default_def=comp_cfg.get('default_def', 10),
                    is_critical=comp_cfg.get('is_critical', False),
                    has_atk=comp_cfg.get('has_atk', False),
                    has_eft=comp_cfg.get('has_eft', False),
                    default_atk=comp_cfg.get('default_atk', 0),
                )

    def _initialize_defaults(self) -> None:
        """Initialize all values to defaults."""
        for name, comp in self._components.items():
            self._hp[name] = comp.hp
            self._def[name] = comp.default_def
            if comp.has_atk:
                self._atk[name] = comp.default_atk
            if comp.has_eft:
                self._eft[name] = 1.0

        self._recompute_derived()

    def reset(self) -> None:
        """Reset sheet to initial state."""
        self._initialize_defaults()
        self._env_effects = None
        self._env_damage_applied = False
        self._combat_damage.clear()
        self._hit_count = 0
        self._combat_log.clear()
        self._equipment.clear()
        self._equipment_effects = None

    # ========== AGENT INTERFACE ==========

    def set_def_design(self, design: Dict[str, int]) -> Tuple[bool, Optional[str]]:
        """
        Agent sets DEF values.

        This is the PRIMARY way agent modifies drone stats.

        Args:
            design: Dict mapping component_def to value
                    e.g., {"engine_def": 25, "cockpit_def": 20, ...}

        Returns:
            (success, error_message)
        """
        # Validate design
        is_valid, error = self._validate_def_design(design)
        if not is_valid:
            return False, error

        # Reset state for new design
        self._initialize_defaults()

        # Apply DEF values
        for key, value in design.items():
            # Handle both "engine_def" and "engine" formats
            component = key.replace('_def', '') if key.endswith('_def') else key
            if component in self._components:
                self._def[component] = value

        # Recompute derived values
        self._recompute_derived()

        return True, None

    def _validate_def_design(self, design: Dict[str, int]) -> Tuple[bool, Optional[str]]:
        """Validate a DEF design from agent."""
        if not design:
            return False, "Design cannot be empty"

        for key, value in design.items():
            component = key.replace('_def', '') if key.endswith('_def') else key

            # Check component exists
            if component not in self._components:
                return False, f"Unknown component: {component}"

            # Check value is non-negative
            if not isinstance(value, (int, float)) or value < 0:
                return False, f"Invalid DEF value for {component}: {value}"

        return True, None

    def set_equipment(self, equipment: Dict[str, str]) -> Tuple[bool, Optional[str]]:
        """
        Agent sets discrete equipment choices.

        Args:
            equipment: Dict mapping slot to choice_id
                       e.g., {"coating": "stealth", "antenna_mode": "passive"}

        Returns:
            (success, error_message)
        """
        if equipment:
            self._equipment = equipment.copy()
            logger.debug(f"Equipment set: {equipment}")
        return True, None

    def apply_equipment_effects(self, effects: 'EquipmentEffects') -> None:
        """
        Apply equipment effects to drone attributes.

        This is called after action space validation computes the combined
        effects from all discrete choices.

        Args:
            effects: EquipmentEffects computed from action space config
        """
        from ..modules.action_space.schema import EquipmentEffects as EE

        self._equipment_effects = effects

        # Apply detection modifier (will be used during detection calculation)
        # This is stored and applied when environment effects are computed

        # Apply agility modifier
        if hasattr(effects, 'agility_modifier') and effects.agility_modifier != 0:
            self._agility = max(
                self._agility_config.min_agility,
                min(self._agility_config.max_agility,
                    self._agility + effects.agility_modifier)
            )

        # Apply DEF multiplier to all components
        if hasattr(effects, 'def_multiplier') and effects.def_multiplier != 1.0:
            for comp in self._def:
                self._def[comp] = int(self._def[comp] * effects.def_multiplier)
            self._recompute_derived()

        # Apply HP modifiers to specific components
        if hasattr(effects, 'hp_modifiers') and effects.hp_modifiers:
            for comp, modifier in effects.hp_modifiers.items():
                if comp in self._hp:
                    self._hp[comp] = max(0, self._hp[comp] + modifier)
            self._recompute_derived()

        logger.debug(f"Equipment effects applied: detection={getattr(effects, 'detection_modifier', 0)}, "
                    f"agility={getattr(effects, 'agility_modifier', 0)}")

    def get_equipment_effects(self) -> Optional['EquipmentEffects']:
        """Get the current equipment effects (for SCM to use)."""
        return self._equipment_effects

    def get_equipment(self) -> Dict[str, str]:
        """Get current equipment choices."""
        return self._equipment.copy()

    def get_agent_view(self) -> Dict[str, Any]:
        """
        Return data visible to agent.

        Filters out hidden fields like HP and agility.
        """
        view = {
            # DEF values (visible)
            'def_values': {f"{k}_def": v for k, v in self._def.items()},
            'total_def': self._total_def,

            # ATK values (visible)
            'atk_values': {f"{k}_atk": v for k, v in self._atk.items()},

            # Equipment choices (visible, but not their effects)
            'equipment': self._equipment.copy() if self._equipment else {},

            # Component info (partial)
            'components': {
                name: {
                    'def': self._def.get(name, 0),
                    'atk': self._atk.get(name) if comp.has_atk else None,
                    'is_critical': comp.is_critical,
                }
                for name, comp in self._components.items()
            },
        }

        # Apply visibility filtering
        return self._visibility.filter_for_agent(view)

    # ========== SCM INTERFACE ==========

    def apply_environment_effects(self, effects: EnvironmentEffects) -> None:
        """
        SCM writes environment effects into middleware.

        This is the PRIMARY way SCM affects the simulation.

        Args:
            effects: EnvironmentEffects computed by SCM
        """
        self._env_effects = effects

        # Apply environment damage to HP
        if not self._env_damage_applied:
            for component, raw_damage in effects.component_damage.items():
                if component in self._hp:
                    # NOTE: 'antenna' damage is pre-computed by SCM (trap mechanism)
                    # Skip DEF reduction for antenna to avoid double calculation
                    if component == 'antenna':
                        actual_damage = raw_damage  # Already reduced by SCM
                    else:
                        # Apply DEF reduction for other components
                        def_value = self._def.get(component, 0)
                        actual_damage = self._calculate_damage(raw_damage, def_value)
                    self._hp[component] = max(0, self._hp[component] - actual_damage)

            self._env_damage_applied = True

        # Update derived values based on new HP
        self._recompute_derived()

    def _calculate_damage(self, raw_damage: int, def_value: int) -> int:
        """
        Calculate actual damage after DEF reduction.

        DEF reduction is significant to make armor investment worthwhile.
        This rewards proper armor allocation over simply minimizing weight.
        """
        # Each DEF point reduces 0.5 damage (increased from 0.3)
        reduction = int(def_value * self._def_reduction_factor)
        # Cap reduction at 65% of raw damage (increased from 50%)
        max_reduction = int(raw_damage * 0.65)
        reduction = min(reduction, max_reduction)
        return max(1, raw_damage - reduction)

    # ========== COMBAT INTERFACE ==========

    def apply_combat_damage(
        self,
        damage_by_component: Dict[str, int],
        hit_count: int = 0,
        combat_log: Optional[List[str]] = None
    ) -> None:
        """
        Apply combat damage to drone.

        Args:
            damage_by_component: Raw damage per component
            hit_count: Number of hits taken
            combat_log: Combat event log
        """
        for component, raw_damage in damage_by_component.items():
            if component in self._hp:
                def_value = self._def.get(component, 0)
                actual_damage = self._calculate_damage(raw_damage, def_value)
                self._hp[component] = max(0, self._hp[component] - actual_damage)
                self._combat_damage[component] = self._combat_damage.get(component, 0) + actual_damage

        self._hit_count += hit_count
        if combat_log:
            self._combat_log.extend(combat_log)

        # Update derived values
        self._recompute_derived()

    # ========== GAME INTERFACE ==========

    def to_drone_state(self) -> DroneState:
        """
        Generate standardized DroneState for Game module.

        This is what Game.judge_survival() receives.
        """
        # Get environment effects or defaults
        effects = self._env_effects or EnvironmentEffects()

        # Compute detection probability
        detection_prob = self._compute_detection_probability(effects)

        # Compute combat rounds
        combat_rounds = self._compute_combat_rounds(effects)

        return DroneState(
            # Core HP
            hp=self._hp.copy(),

            # DEF values
            def_values=self._def.copy(),

            # Derived combat attributes
            agility=self._agility,
            detection_probability=detection_prob,
            combat_rounds=combat_rounds,

            # Component states
            antenna_emitting=self._hp.get('antenna', 0) > 0,
            antenna_hp=self._hp.get('antenna', 0),

            # Combat modifiers
            combat_damage_modifier=effects.combat_damage_modifier,
            combat_accuracy_modifier=effects.combat_accuracy_modifier,

            # Functional component effectiveness
            camera_power=self._eft.get('camera', 1.0) * effects.camera_effectiveness,
            gun_power=self._eft.get('gun', 1.0) * effects.gun_effectiveness,

            # Environment info
            weather_pattern=effects.weather_pattern,
            environment_visible=self._get_visible_environment(effects),
        )

    def _compute_detection_probability(self, effects: EnvironmentEffects) -> float:
        """
        Compute final detection probability.

        The SCM is responsible for computing the detection probability based on:
        - Weather conditions
        - Antenna state (emitting signal or not)
        - Other environmental factors

        DroneSheet uses the detection_modifier from SCM as the base probability,
        then applies equipment effects if present.

        Design intent:
        - SCM computes detection_modifier considering antenna HP
        - Equipment effects can modify detection (e.g., stealth coating)
        - DroneSheet clamps and returns final value
        """
        # SCM provides detection_modifier as the base detection probability
        prob = effects.detection_modifier

        # Apply equipment effects if present
        if self._equipment_effects:
            equip_detection_mod = getattr(self._equipment_effects, 'detection_modifier', 0)
            prob += equip_detection_mod

        return min(0.95, max(0.01, prob))  # Clamp to 1%-95%

    def _compute_combat_rounds(self, effects: EnvironmentEffects) -> int:
        """
        Compute number of combat rounds.

        Combat rounds are fixed, only modified by environment.
        Agility does NOT affect combat rounds (only affects hit chance).
        """
        base_rounds = 10  # Base rounds (enough to be lethal)

        # Apply modifier from environment only
        rounds = base_rounds * effects.combat_rounds_modifier

        return max(1, int(rounds))

    def _get_visible_environment(self, effects: EnvironmentEffects) -> Dict[str, float]:
        """Get environment variables visible to agent."""
        visible_vars = ['wind_speed', 'humidity', 'temperature', 'uv_index']
        return {k: v for k, v in effects.raw_environment.items() if k in visible_vars}

    # ========== ADMIN INTERFACE ==========

    def get_full_stats(self) -> Dict[str, Any]:
        """
        Return ALL stats for admin/frontend.

        Includes hidden values like HP and agility.
        """
        effects = self._env_effects or EnvironmentEffects()

        result = {
            # HP values
            'hp': self._hp.copy(),
            'total_hp': self._total_hp,

            # DEF values
            'def_values': self._def.copy(),
            'total_def': self._total_def,

            # ATK values
            'atk_values': self._atk.copy(),

            # Equipment choices
            'equipment': self._equipment.copy() if self._equipment else {},

            # Derived values
            'agility': self._agility,
            'signal_strength': self._signal_strength,
            'stealth_rating': self._stealth_rating,
            'firepower': self._firepower,

            # Detection/combat
            'detection_probability': self._compute_detection_probability(effects),
            'combat_rounds': self._compute_combat_rounds(effects),

            # Environment effects
            'env_damage_applied': self._env_damage_applied,
            'weather_pattern': effects.weather_pattern if self._env_effects else None,

            # Combat stats
            'hit_count': self._hit_count,
            'combat_damage': self._combat_damage.copy(),

            # Component config
            'components': {
                name: {
                    'hp': self._hp.get(name, 0),
                    'def': self._def.get(name, 0),
                    'atk': self._atk.get(name),
                    'is_critical': comp.is_critical,
                    'has_atk': comp.has_atk,
                }
                for name, comp in self._components.items()
            },
        }

        # Include equipment effects for admin (hidden from agent)
        if self._equipment_effects:
            result['equipment_effects'] = {
                'detection_modifier': getattr(self._equipment_effects, 'detection_modifier', 0),
                'agility_modifier': getattr(self._equipment_effects, 'agility_modifier', 0),
                'def_multiplier': getattr(self._equipment_effects, 'def_multiplier', 1.0),
                'emi_resistance': getattr(self._equipment_effects, 'emi_resistance', 0),
            }

        return result

    def set_visibility(self, field: str, visibility: Visibility) -> None:
        """Admin changes field visibility."""
        self._visibility.set_visibility(field, visibility)

    # ========== DERIVED VALUE COMPUTATION ==========

    def _recompute_derived(self) -> None:
        """Recompute all derived values from current state."""
        # Total DEF
        self._total_def = sum(self._def.values())

        # Total HP
        self._total_hp = sum(self._hp.values())

        # Agility from total DEF
        self._agility = self._compute_agility(self._total_def)

        # Signal strength from antenna HP
        antenna_hp = self._hp.get('antenna', 0)
        antenna_max_hp = self._components.get('antenna', ComponentConfig('antenna', 50, 10)).hp
        self._signal_strength = min(1.0, max(0.0, antenna_hp / antenna_max_hp)) if antenna_max_hp > 0 else 0.0

        # Stealth rating (inverse of signal strength)
        self._stealth_rating = 1.0 - self._signal_strength

        # Firepower from gun ATK
        gun_atk = self._atk.get('gun', 0)
        self._firepower = gun_atk * self._eft.get('gun', 1.0)

    def _compute_agility(self, total_def: int) -> float:
        """
        Compute agility from total DEF.

        Higher DEF = Lower agility = More likely to be hit

        Formula: agility = base - linear_coeff * def * exp(-def / scale) - linear_penalty
        """
        if total_def <= 0:
            return self._agility_config.max_agility

        cfg = self._agility_config
        penalty = cfg.linear_coefficient * total_def * math.exp(-total_def / cfg.exponential_decay_scale)
        linear_penalty = 0.001 * total_def

        agility = cfg.base_agility - penalty - linear_penalty
        return max(cfg.min_agility, min(cfg.max_agility, agility))

    # ========== RESULT FILTERING ==========

    def filter_result_for_agent(self, result: JudgmentResult) -> Dict[str, Any]:
        """
        Filter JudgmentResult for agent consumption.

        Hides HP values and internal details.
        """
        effects = self._env_effects or EnvironmentEffects()

        filtered = {
            'status': result.status,
            'survived': result.survived,

            # Combat stats (agent can see hit count)
            'hit_count': result.hit_count,
            'was_detected': result.was_detected,

            # Visible environment
            'environment': self._get_visible_environment(effects),

            # NO HP values
            # NO agility
            # NO detection probability details
        }

        # Add DEF remaining values if visibility config allows
        if self._def_remaining_visible():
            filtered['def_remaining'] = self._def.copy()

        return filtered

    def _def_remaining_visible(self) -> bool:
        """Check if DEF remaining values should be visible to agent."""
        # Check if any DEF field is in agent_visible_override
        for def_field in ['engine_def', 'cockpit_def', 'wing_def', 'body_def',
                         'antenna_def', 'camera_def', 'gun_def']:
            if def_field in self._visibility.agent_visible_override:
                return True
        return False

    def filter_result_for_admin(self, result: JudgmentResult) -> Dict[str, Any]:
        """
        Full JudgmentResult for admin/frontend.
        """
        effects = self._env_effects or EnvironmentEffects()

        return {
            'status': result.status,
            'survived': result.survived,
            'fail_reason': result.fail_reason,

            # Full HP
            'final_hp': result.final_hp,

            # Combat stats
            'hit_count': result.hit_count,
            'was_detected': result.was_detected,
            'damage_taken': result.damage_taken,

            # Full drone stats
            'drone_stats': self.get_full_stats(),

            # Environment
            'environment': effects.raw_environment,
            'weather_pattern': effects.weather_pattern,

            # Logs
            'combat_log': result.combat_log,
            'damage_log': result.damage_log,
        }

    # ========== OBSERVATION NOISE ==========

    def add_observation_noise(self, result: Dict[str, Any], noise_std: float) -> Dict[str, Any]:
        """
        Add Gaussian observation noise to agent-visible results.

        This is called by action_space when SCM supports weather-dependent noise.

        Args:
            result: Filtered result for agent (from filter_result_for_agent)
            noise_std: Standard deviation as ratio of value (e.g., 0.20 for rain, 0.05 for clear)

        Returns:
            Noisy result for agent consumption
        """
        import numpy as np

        # Helper function to add Gaussian noise
        def add_noise(value: float, std_ratio: float) -> float:
            """Add Gaussian noise: value + N(0, (value * std_ratio)²)"""
            if value == 0:
                return 0
            std = abs(value) * std_ratio
            noise = np.random.normal(0, std)
            return max(0, value + noise)  # Ensure non-negative

        # Helper to flip status with small probability
        def flip_status(status: str) -> str:
            """Flip status between RETURNED and DESTROYED"""
            if status == 'RETURNED':
                return 'DESTROYED'
            elif status in ('DESTROYED', 'LOST'):
                return 'RETURNED'
            return status

        # Create a copy to avoid modifying original
        noisy_result = result.copy()

        # 1. Add noise to environment variables
        if 'environment' in noisy_result:
            for key, value in noisy_result['environment'].items():
                if isinstance(value, (int, float)):
                    noisy_result['environment'][key] = add_noise(float(value), noise_std)

        # 2. Add noise to hit_count (ensure it stays integer)
        if 'hit_count' in noisy_result and noisy_result['hit_count'] is not None:
            noisy_hit_count = add_noise(float(noisy_result['hit_count']), noise_std)
            noisy_result['hit_count'] = int(max(0, round(noisy_hit_count)))

        # 3. Flip status with small probability (proportional to noise level)
        # Rain (0.20): 2% flip chance, Clear (0.05): 0.5% flip chance
        if 'status' in noisy_result and random.random() < noise_std * 0.1:
            noisy_result['status'] = flip_status(noisy_result['status'])
            # Update survived flag to match flipped status
            noisy_result['survived'] = (noisy_result['status'] == 'RETURNED')

        # 4. Add noise to DEF remaining values (if visible)
        if 'def_remaining' in noisy_result:
            for component, value in noisy_result['def_remaining'].items():
                if isinstance(value, (int, float)):
                    noisy_result['def_remaining'][component] = add_noise(float(value), noise_std)

        return noisy_result

    # ========== UTILITY ==========

    def copy(self) -> 'DroneSheet':
        """Create a deep copy of this DroneSheet."""
        new_sheet = DroneSheet.__new__(DroneSheet)
        new_sheet._components = copy.deepcopy(self._components)
        new_sheet._hp = self._hp.copy()
        new_sheet._def = self._def.copy()
        new_sheet._atk = self._atk.copy()
        new_sheet._eft = self._eft.copy()
        new_sheet._total_def = self._total_def
        new_sheet._total_hp = self._total_hp
        new_sheet._agility = self._agility
        new_sheet._signal_strength = self._signal_strength
        new_sheet._stealth_rating = self._stealth_rating
        new_sheet._firepower = self._firepower
        new_sheet._env_effects = self._env_effects
        new_sheet._env_damage_applied = self._env_damage_applied
        new_sheet._combat_damage = self._combat_damage.copy()
        new_sheet._hit_count = self._hit_count
        new_sheet._combat_log = self._combat_log.copy()
        new_sheet._agility_config = self._agility_config
        new_sheet._visibility = self._visibility
        new_sheet._def_reduction_factor = self._def_reduction_factor
        new_sheet._equipment = self._equipment.copy()
        new_sheet._equipment_effects = self._equipment_effects
        return new_sheet
