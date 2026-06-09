"""
DefaultSCM - Minimal SCM with no traps.

Use this as a starting point for new experiments.
No component damage, constant detection/combat modifiers.
"""

from typing import Dict, Any
import random

from .scm_base import BaseSCM, EnvironmentState
from .scm_registry import register_scm


@register_scm("base")
class DefaultSCM(BaseSCM):
    """
    Default SCM with minimal effects.

    Use this as a starting point for new experiments.
    No component damage, constant detection/combat modifiers.
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.base_detection = config.get('base_detection', 0.3)
        self.base_combat_intensity = config.get('base_combat_intensity', 1.0)

    def sample_environment(self, equipment: dict = None) -> EnvironmentState:
        """Sample basic environment variables (no latent confounders).

        Args:
            equipment: Optional equipment choices (unused in this SCM)
        """
        return EnvironmentState(
            visible={
                'wind_speed': random.uniform(10, 40),
                'humidity': random.uniform(30, 70),
                'temperature': random.uniform(15, 30),
            },
            latent={},
            derived={},
        )

    def _compute_effects(self, sheet, env):
        """Minimal effects - constant modifiers, no damage."""
        try:
            from ...middleware.drone_state import EnvironmentEffects
        except ImportError:
            from middleware.drone_state import EnvironmentEffects

        return EnvironmentEffects(
            component_damage={},
            detection_modifier=self.base_detection,
            combat_rounds_modifier=self.base_combat_intensity,
            weather_pattern=0.5,  # Neutral
            raw_environment=env.visible.copy(),
        )
