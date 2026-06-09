"""
WeatherNoiseSCM - Weather-Dependent Observation Noise Experiment.

This experiment tests agent's ability to discover causal relationships
in the presence of weather-dependent observation noise.

Key Mechanism:
- Rainy (storm): High observation noise (σ = 20%)
- Sunny (clear): Low observation noise (σ = 5%)

Noise affects:
1. Environment variables (wind_speed, humidity, temperature)
2. hit_count (combat observations)
3. status (survival observations - small flip probability)
4. DEF remaining values (if visible)

The Challenge:
- Agent must learn to deploy more drones in rainy conditions to average out noise
- Agent must distinguish between noise and true causal patterns
- High-quality data in sunny conditions vs noisy data in rainy conditions
"""

from typing import Dict, Any
import random
import numpy as np

from .scm_base import BaseSCM, EnvironmentState
from .scm_registry import register_scm


@register_scm("weather_noise")
class WeatherNoiseSCM(BaseSCM):
    """
    Weather-Dependent Observation Noise SCM.

    Key mechanism:
    - Rainy days: High observation noise (σ = 20%)
    - Sunny days: Low observation noise (σ = 5%)

    This creates an environment where data quality varies with weather,
    forcing agents to adapt their exploration strategies.
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

        # Stage-specific storm probabilities
        self.storm_probability_stage1 = self.get_parameter('storm_probability_stage1', 0.7)
        self.storm_probability_stage2 = self.get_parameter('storm_probability_stage2', 0.3)

        # Current storm probability (changes based on evaluation mode)
        self._current_storm_probability = self.storm_probability_stage1

        # Noise parameters (standard deviation as ratio of value)
        self.noise_rain = self.get_parameter('noise_rain', 0.20)   # 20% std in rain
        self.noise_clear = self.get_parameter('noise_clear', 0.05)  # 5% std in clear

        # Base survival mechanism (same as weather_defense)
        # Antenna DEF correlation: +0.8 in rain, -0.8 in sun
        # Engine DEF correlation: +0.6 in both stages
        self.storm_antenna_damage_base = self.get_parameter('storm_antenna_damage_base', 80)
        self.antenna_def_protection_factor = self.get_parameter('antenna_def_protection_factor', 2.5)
        self.antenna_def_protection_cap = self.get_parameter('antenna_def_protection_cap', 70)
        self.antenna_signal_boost_per_def = self.get_parameter('antenna_signal_boost_per_def', 0.035)
        self.antenna_signal_boost_cap = self.get_parameter('antenna_signal_boost_cap', 0.80)
        self.engine_def_protection_factor = self.get_parameter('engine_def_protection_factor', 2.5)
        self.engine_damage_base = self.get_parameter('engine_damage_base', 50)

    def sample_environment(self, equipment: dict = None) -> EnvironmentState:
        """
        Sample environment with current storm probability.

        Storm probability differs between Stage 1 (70%) and Stage 2 (30%).

        Args:
            equipment: Optional equipment choices (unused in this SCM)
        """
        weather = random.random()
        is_storm = weather > (1 - self._current_storm_probability)

        if is_storm:
            wind_speed = random.uniform(40, 80)
            humidity = random.uniform(70, 95)
            temperature = random.uniform(10, 20)
        else:
            wind_speed = random.uniform(5, 30)
            humidity = random.uniform(30, 60)
            temperature = random.uniform(20, 35)

        return EnvironmentState(
            visible={
                'wind_speed': wind_speed,
                'humidity': humidity,
                'temperature': temperature,
            },
            latent={
                'weather_pattern': weather,
            },
            derived={
                'is_storm': float(is_storm),
            }
        )

    def _compute_effects(self, sheet, env):
        """
        Compute effects with deterministic survival (like weather_defense).

        The survival mechanism is the same as WeatherDefenseSCM,
        but observation noise will be added later at the filtering stage.
        """
        try:
            from ...middleware.drone_state import EnvironmentEffects
        except ImportError:
            from middleware.drone_state import EnvironmentEffects

        weather = env.latent.get('weather_pattern', env.derived.get('weather_pattern', 0.5))
        is_storm = env.derived.get('is_storm', 0) > 0.5

        # Get DEF values
        antenna_def = sheet._def.get('antenna', 10)
        engine_def = sheet._def.get('engine', 20)

        damage_log = []

        # Helper functions
        def sigmoid(x):
            """Stable sigmoid function."""
            if x > 0:
                return 1.0 / (1.0 + np.exp(-x))
            else:
                exp_x = np.exp(x)
                return exp_x / (1.0 + exp_x)

        # Stage 1/2 survival mechanism (same as weather_defense)
        if is_storm:
            # Rainy: High antenna DEF = high survival
            _activation = (antenna_def / 30.0) * 2.5 - 4
            survival_rate = sigmoid(_activation)
            damage_log.append(f"STORM: antenna_def={antenna_def}")
        else:
            # Sunny: High antenna DEF = low survival
            _activation = (antenna_def / 30.0) * (-2.5) - 4
            survival_rate = sigmoid(_activation)
            damage_log.append(f"CLEAR: antenna_def={antenna_def}")

        # Engine DEF bonus (always positive)
        norm_engine_def = max(0.0, min(1.0, (engine_def - 10) / 20.0))
        engine_bonus = norm_engine_def * 0.3
        survival_rate += engine_bonus

        damage_log.append(f"ENGINE: engine_def={engine_def}, bonus={engine_bonus:.3f}")
        damage_log.append(f"final_survival_rate = {survival_rate:.3f}")

        # Enforce survival via component_damage
        survival_rate = max(0.0, min(1.0, survival_rate))
        roll = random.random()
        survives = roll < survival_rate

        damage_log.append(f"DEBUG: roll={roll:.3f}, survival_rate={survival_rate:.3f}, survives={survives}")

        if survives:
            component_damage = {}
            damage_log.append(f"RESULT: SURVIVED")
        else:
            component_damage = {'engine': 1000}
            damage_log.append(f"RESULT: DESTROYED, applying engine damage")

        return EnvironmentEffects(
            component_damage=component_damage,
            detection_modifier=0.5,
            combat_rounds_modifier=0,
            combat_damage_modifier=1.0,
            combat_accuracy_modifier=1.0,
            camera_effectiveness=1.0,
            gun_effectiveness=1.0,
            antenna_effectiveness=1.0,
            weather_pattern=weather,
            raw_environment=env.visible.copy(),
            damage_log=damage_log,
        )

    def get_noise_std(self, env: EnvironmentState) -> float:
        """
        Get observation noise standard deviation for current weather.

        Args:
            env: Environment state

        Returns:
            Noise standard deviation as ratio of value (0.20 for rain, 0.05 for clear)
        """
        is_storm = env.derived.get('is_storm', 0) > 0.5
        return self.noise_rain if is_storm else self.noise_clear

    def set_evaluation_mode(self, is_evaluation: bool = True):
        """
        Switch to evaluation mode (Stage 2).

        Stage 1 (exploration): 70% storms
        Stage 2 (evaluation): 30% storms (70% sunny!)

        This creates the weather shift like weather_defense.
        """
        if is_evaluation:
            self._current_storm_probability = self.storm_probability_stage2
        else:
            self._current_storm_probability = self.storm_probability_stage1
