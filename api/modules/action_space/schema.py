"""
Action Space Schema Definitions

Defines data structures for flexible action spaces including:
- Numerical actions (continuous values like DEF)
- Discrete actions (categorical choices like equipment)
- Boolean actions (on/off flags)
- Equipment effects (hidden from agent)
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Any, Optional
from enum import Enum


class ActionType(Enum):
    """Types of actions in the action space"""
    NUMERICAL = "numerical"
    DISCRETE = "discrete"
    BOOLEAN = "boolean"


class DiscreteType(Enum):
    """Types of discrete action selection"""
    SINGLE_CHOICE = "single_choice"
    MULTI_CHOICE = "multi_choice"


@dataclass
class NumericalAction:
    """
    A continuous numerical action (e.g., engine_def: 0-50)
    """
    name: str
    min: float
    max: float
    default: float
    step: float = 1.0
    description: str = ""
    visible: bool = True

    def validate(self, value: float) -> tuple[bool, Optional[str]]:
        """Validate a value for this action"""
        if value < self.min:
            return False, f"{self.name} must be >= {self.min}, got {value}"
        if value > self.max:
            return False, f"{self.name} must be <= {self.max}, got {value}"
        return True, None

    def to_agent_dict(self) -> Dict[str, Any]:
        """Convert to dict for agent view (no hidden info)"""
        return {
            "min": self.min,
            "max": self.max,
            "default": self.default,
            "step": self.step,
            "description": self.description
        }


@dataclass
class DiscreteOption:
    """
    A single option within a discrete action
    """
    id: str
    name: str
    description: str
    cost: float = 0.0
    prerequisites: List[str] = field(default_factory=list)
    incompatible_with: List[str] = field(default_factory=list)

    def to_agent_dict(self) -> Dict[str, Any]:
        """Convert to dict for agent view"""
        result = {
            "name": self.name,
            "description": self.description
        }
        if self.cost > 0:
            result["cost"] = self.cost
        if self.prerequisites:
            result["requires"] = self.prerequisites
        if self.incompatible_with:
            result["incompatible_with"] = self.incompatible_with
        return result


@dataclass
class DiscreteAction:
    """
    A categorical choice action (e.g., coating: standard/stealth/armor)
    """
    name: str
    type: DiscreteType
    description: str
    options: Dict[str, DiscreteOption]
    default: str
    visible: bool = True

    def validate(self, value: str) -> tuple[bool, Optional[str]]:
        """Validate a choice for this action"""
        if value not in self.options:
            valid_options = list(self.options.keys())
            return False, f"Invalid {self.name}: '{value}'. Valid options: {valid_options}"
        return True, None

    def to_agent_dict(self) -> Dict[str, Any]:
        """Convert to dict for agent view"""
        return {
            "description": self.description,
            "type": self.type.value,
            "options": {
                oid: opt.to_agent_dict()
                for oid, opt in self.options.items()
            },
            "default": self.default
        }


@dataclass
class BooleanAction:
    """
    A boolean on/off action
    """
    name: str
    description: str
    default: bool = False
    visible: bool = True

    def to_agent_dict(self) -> Dict[str, Any]:
        """Convert to dict for agent view"""
        return {
            "description": self.description,
            "default": self.default
        }


@dataclass
class EquipmentEffects:
    """
    Hidden effects applied when equipment is selected.
    These modify DroneSheet properties but are NOT visible to the agent.
    """
    # Detection and stealth
    detection_modifier: float = 0.0
    signal_strength_modifier: float = 0.0

    # Physical properties
    agility_modifier: float = 0.0
    weight_modifier: float = 0.0
    def_multiplier: float = 1.0

    # Special resistances
    emi_resistance: float = 0.0
    thermal_resistance: float = 0.0

    # Component-specific HP modifiers
    hp_modifiers: Dict[str, int] = field(default_factory=dict)

    # Custom effects for experiment-specific mechanics
    custom_effects: Dict[str, Any] = field(default_factory=dict)

    def combine(self, other: 'EquipmentEffects') -> 'EquipmentEffects':
        """Combine two effect sets (additive for most, multiplicative for multipliers)"""
        combined_hp = dict(self.hp_modifiers)
        for comp, mod in other.hp_modifiers.items():
            combined_hp[comp] = combined_hp.get(comp, 0) + mod

        combined_custom = dict(self.custom_effects)
        combined_custom.update(other.custom_effects)

        return EquipmentEffects(
            detection_modifier=self.detection_modifier + other.detection_modifier,
            signal_strength_modifier=self.signal_strength_modifier + other.signal_strength_modifier,
            agility_modifier=self.agility_modifier + other.agility_modifier,
            weight_modifier=self.weight_modifier + other.weight_modifier,
            def_multiplier=self.def_multiplier * other.def_multiplier,
            emi_resistance=min(1.0, self.emi_resistance + other.emi_resistance),
            thermal_resistance=min(1.0, self.thermal_resistance + other.thermal_resistance),
            hp_modifiers=combined_hp,
            custom_effects=combined_custom
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'EquipmentEffects':
        """Create from dictionary (for loading from JSON)"""
        return cls(
            detection_modifier=data.get('detection_modifier', 0.0),
            signal_strength_modifier=data.get('signal_strength_modifier', 0.0),
            agility_modifier=data.get('agility_modifier', 0.0),
            weight_modifier=data.get('weight_modifier', 0.0),
            def_multiplier=data.get('def_multiplier', 1.0),
            emi_resistance=data.get('emi_resistance', 0.0),
            thermal_resistance=data.get('thermal_resistance', 0.0),
            hp_modifiers=data.get('hp_modifier', data.get('hp_modifiers', {})),
            custom_effects=data.get('custom_effects', {})
        )


@dataclass
class Constraints:
    """
    Constraints on the action space
    """
    total_def_budget: Optional[int] = None
    total_equipment_slots: Optional[int] = None
    max_weight: Optional[float] = None
    custom_rules: List[str] = field(default_factory=list)

    def to_agent_dict(self) -> Dict[str, Any]:
        """Convert to dict for agent view"""
        result = {}
        if self.total_def_budget is not None:
            result["total_def_budget"] = self.total_def_budget
        if self.total_equipment_slots is not None:
            result["total_equipment_slots"] = self.total_equipment_slots
        if self.max_weight is not None:
            result["max_weight"] = self.max_weight
        return result


@dataclass
class ActionSpaceConfig:
    """
    Complete action space configuration for an experiment.

    Contains:
    - Numerical actions (DEF values, etc.)
    - Discrete actions (equipment choices)
    - Boolean actions (flags)
    - Constraints
    - Hidden effects mapping
    """
    numerical: Dict[str, NumericalAction] = field(default_factory=dict)
    discrete: Dict[str, DiscreteAction] = field(default_factory=dict)
    boolean: Dict[str, BooleanAction] = field(default_factory=dict)
    constraints: Constraints = field(default_factory=Constraints)
    effects: Dict[str, EquipmentEffects] = field(default_factory=dict)

    # Metadata
    schema_version: str = "1.0"
    experiment_name: str = ""

    def get_agent_view(self) -> Dict[str, Any]:
        """
        Return action space configuration visible to agent.
        EXCLUDES hidden effects!
        """
        result = {}

        # Numerical actions
        if self.numerical:
            result["numerical"] = {
                name: action.to_agent_dict()
                for name, action in self.numerical.items()
                if action.visible
            }

        # Discrete actions
        if self.discrete:
            result["discrete"] = {
                name: action.to_agent_dict()
                for name, action in self.discrete.items()
                if action.visible
            }

        # Boolean actions
        if self.boolean:
            result["boolean"] = {
                name: action.to_agent_dict()
                for name, action in self.boolean.items()
                if action.visible
            }

        # Constraints (excluding internal ones)
        constraints = self.constraints.to_agent_dict()
        if constraints:
            result["constraints"] = constraints

        return result

    def get_defaults(self) -> Dict[str, Any]:
        """Get default values for all actions"""
        defaults = {}

        # Numerical defaults
        for name, action in self.numerical.items():
            defaults[name] = action.default

        # Discrete defaults
        equipment = {}
        for name, action in self.discrete.items():
            equipment[name] = action.default
        if equipment:
            defaults["equipment"] = equipment

        # Boolean defaults
        for name, action in self.boolean.items():
            defaults[name] = action.default

        return defaults

    def validate_design(self, design: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        Validate a complete design against this action space.

        Args:
            design: {"engine_def": 20, "equipment": {"coating": "stealth"}, ...}

        Returns:
            (is_valid, error_message)
        """
        # Validate numerical values
        for name, action in self.numerical.items():
            if name in design:
                valid, error = action.validate(design[name])
                if not valid:
                    return False, error

        # Validate discrete choices
        equipment = design.get("equipment", {})
        for name, action in self.discrete.items():
            if name in equipment:
                valid, error = action.validate(equipment[name])
                if not valid:
                    return False, error

        # Check DEF budget constraint
        if self.constraints.total_def_budget is not None:
            total_def = sum(
                design.get(name, action.default)
                for name, action in self.numerical.items()
                if name.endswith("_def")
            )
            if total_def > self.constraints.total_def_budget:
                return False, f"Total DEF ({total_def}) exceeds budget ({self.constraints.total_def_budget})"

        return True, None

    def compute_effects(self, design: Dict[str, Any]) -> EquipmentEffects:
        """
        Compute combined equipment effects for a design.

        This is the HIDDEN mapping from choices to effects.
        """
        combined = EquipmentEffects()

        equipment = design.get("equipment", {})
        for slot, choice in equipment.items():
            if choice in self.effects:
                combined = combined.combine(self.effects[choice])

        # Boolean flags can also have effects
        for name, action in self.boolean.items():
            if design.get(name, action.default):
                if name in self.effects:
                    combined = combined.combine(self.effects[name])

        return combined
