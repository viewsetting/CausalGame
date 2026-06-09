"""
Flexible Action Space Module

Provides configurable action spaces for experiments including:
- Numerical actions (continuous values like DEF)
- Discrete actions (categorical choices like equipment)
- Boolean actions (on/off flags)
- Hidden effect mapping

Each experiment can define its own action_space.json to customize
what actions are available to the agent.
"""

from .schema import (
    ActionSpaceConfig,
    NumericalAction,
    DiscreteAction,
    DiscreteOption,
    DiscreteType,
    BooleanAction,
    EquipmentEffects,
    Constraints,
    ActionType,
)

from .loader import (
    load_action_space,
    load_action_space_from_game_config,
    get_action_space,
    clear_cache,
)

__all__ = [
    # Schema classes
    'ActionSpaceConfig',
    'NumericalAction',
    'DiscreteAction',
    'DiscreteOption',
    'DiscreteType',
    'BooleanAction',
    'EquipmentEffects',
    'Constraints',
    'ActionType',

    # Loader functions
    'load_action_space',
    'load_action_space_from_game_config',
    'get_action_space',
    'clear_cache',
]
