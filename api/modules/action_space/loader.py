"""
Action Space Loader

Loads action space configurations from experiment JSON files.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from .schema import (
    ActionSpaceConfig,
    NumericalAction,
    DiscreteAction,
    DiscreteOption,
    DiscreteType,
    BooleanAction,
    Constraints,
    EquipmentEffects
)

logger = logging.getLogger(__name__)


def get_experiments_dir() -> Path:
    """Get the experiments directory path."""
    # Try relative to this file
    module_dir = Path(__file__).parent
    api_dir = module_dir.parent.parent
    project_root = api_dir.parent

    candidates = [
        project_root / "experiments",
        Path("/app/experiments"),  # Docker
        Path.cwd() / "experiments",
    ]

    for path in candidates:
        if path.exists():
            return path

    raise FileNotFoundError("Could not find experiments directory")


def load_action_space(experiment_name: str) -> ActionSpaceConfig:
    """
    Load action space configuration for an experiment.

    Looks for experiments/<name>/action_space.json.
    Falls back to default numerical-only config if not found.

    Args:
        experiment_name: Name of the experiment

    Returns:
        ActionSpaceConfig object
    """
    experiments_dir = get_experiments_dir()
    action_space_path = experiments_dir / experiment_name / "action_space.json"

    if not action_space_path.exists():
        logger.info(f"No action_space.json for {experiment_name}, using default config")
        return _create_default_config(experiment_name)

    try:
        with open(action_space_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        return _parse_config(data, experiment_name)

    except Exception as e:
        logger.error(f"Failed to load action_space.json for {experiment_name}: {e}")
        return _create_default_config(experiment_name)


def _parse_config(data: Dict[str, Any], experiment_name: str) -> ActionSpaceConfig:
    """Parse JSON data into ActionSpaceConfig"""

    config = ActionSpaceConfig(experiment_name=experiment_name)
    config.schema_version = data.get("$schema", data.get("version", "1.0"))

    # Parse numerical actions
    for name, action_data in data.get("numerical", {}).items():
        config.numerical[name] = NumericalAction(
            name=name,
            min=action_data.get("min", 0),
            max=action_data.get("max", 50),
            default=action_data.get("default", 10),
            step=action_data.get("step", 1),
            description=action_data.get("description", ""),
            visible=action_data.get("visible", True)
        )

    # Parse discrete actions
    for slot_name, slot_data in data.get("discrete", {}).items():
        options = {}
        for opt_id, opt_data in slot_data.get("options", {}).items():
            options[opt_id] = DiscreteOption(
                id=opt_id,
                name=opt_data.get("name", opt_id),
                description=opt_data.get("description", ""),
                cost=opt_data.get("cost", 0),
                prerequisites=opt_data.get("prerequisites", []),
                incompatible_with=opt_data.get("incompatible_with", [])
            )

        discrete_type = slot_data.get("type", "single_choice")
        config.discrete[slot_name] = DiscreteAction(
            name=slot_name,
            type=DiscreteType(discrete_type),
            description=slot_data.get("description", ""),
            options=options,
            default=slot_data.get("default", list(options.keys())[0] if options else ""),
            visible=slot_data.get("visible", True)
        )

    # Parse boolean actions
    for name, action_data in data.get("boolean", {}).items():
        config.boolean[name] = BooleanAction(
            name=name,
            description=action_data.get("description", ""),
            default=action_data.get("default", False),
            visible=action_data.get("visible", True)
        )

    # Parse constraints
    constraints_data = data.get("constraints", {})
    config.constraints = Constraints(
        total_def_budget=constraints_data.get("total_def_budget"),
        total_equipment_slots=constraints_data.get("total_equipment_slots"),
        max_weight=constraints_data.get("max_weight"),
        custom_rules=constraints_data.get("custom_rules", [])
    )

    # Parse hidden effects
    effects_data = data.get("_effects", data.get("effects", {}))
    for effect_id, effect_data in effects_data.items():
        if effect_id.startswith("_"):
            continue  # Skip comments
        config.effects[effect_id] = EquipmentEffects.from_dict(effect_data)

    return config


def _create_default_config(experiment_name: str) -> ActionSpaceConfig:
    """
    Create default action space config (numerical DEF only).

    Used when no action_space.json exists.
    """
    # Default components based on existing experiments
    default_components = [
        ("engine_def", 20),
        ("cockpit_def", 20),
        ("wing_def", 15),
        ("body_def", 15),
        ("antenna_def", 10),
        ("camera_def", 5),
        ("gun_def", 5),
    ]

    config = ActionSpaceConfig(experiment_name=experiment_name)

    for name, default in default_components:
        config.numerical[name] = NumericalAction(
            name=name,
            min=0,
            max=50,
            default=default,
            description=f"Defense value for {name.replace('_def', '')}"
        )

    config.constraints = Constraints(total_def_budget=100)

    return config


def load_action_space_from_game_config(
    experiment_name: str,
    game_config: Dict[str, Any]
) -> ActionSpaceConfig:
    """
    Create action space config from game.json if no action_space.json exists.

    This provides backward compatibility with existing experiments.

    Args:
        experiment_name: Name of the experiment
        game_config: Loaded game.json content

    Returns:
        ActionSpaceConfig object
    """
    # First try to load from action_space.json
    experiments_dir = get_experiments_dir()
    action_space_path = experiments_dir / experiment_name / "action_space.json"

    if action_space_path.exists():
        return load_action_space(experiment_name)

    # Fall back to game.json based config
    config = ActionSpaceConfig(experiment_name=experiment_name)

    # Extract component DEF from game config
    drone_config = game_config.get("drone", {})
    components = drone_config.get("components", {})
    standard_design = drone_config.get("standard_design", {})

    for comp_name, comp_data in components.items():
        def_name = f"{comp_name}_def"
        default_def = comp_data.get("default_def", standard_design.get(def_name, 10))

        config.numerical[def_name] = NumericalAction(
            name=def_name,
            min=0,
            max=50,
            default=default_def,
            description=f"Defense value for {comp_name}"
        )

    # Extract constraints
    resources = game_config.get("resources", {})
    config.constraints = Constraints(
        total_def_budget=drone_config.get("total_default_def", 100)
    )

    return config


# Registry of loaded action spaces (cached)
_action_space_cache: Dict[str, ActionSpaceConfig] = {}


def get_action_space(experiment_name: str, force_reload: bool = False) -> ActionSpaceConfig:
    """
    Get action space configuration with caching.

    Args:
        experiment_name: Name of the experiment
        force_reload: If True, reload from file even if cached

    Returns:
        ActionSpaceConfig object
    """
    if force_reload or experiment_name not in _action_space_cache:
        _action_space_cache[experiment_name] = load_action_space(experiment_name)

    return _action_space_cache[experiment_name]


def clear_cache():
    """Clear the action space cache"""
    _action_space_cache.clear()
