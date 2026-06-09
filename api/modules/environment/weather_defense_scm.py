"""
WeatherDefenseSCM - Weather-Dependent DEF Correlation Experiment.

This experiment demonstrates an ENVIRONMENT SHIFT trap where the
optimal strategy changes between Stage 1 and Stage 2.

Causal Structure:
- Rainy (storm): High antenna DEF protects antenna → navigation works → high survival
- Sunny: High antenna DEF = strong antenna = strong signal = high detection = low survival
- Engine DEF: Always positive correlation (protects power core)

Environment Shift:
- Stage 1 (exploration): 70% rainy → Agent learns "high antenna DEF is good"
- Stage 2 (evaluation): 70% sunny → Optimal strategy is completely different!

The trap: Agent must discover the weather-dependent correlation and adapt for Stage 2.
"""

from typing import Dict, Any
import random
import numpy as np

from .scm_base import BaseSCM, EnvironmentState
from .scm_registry import register_scm


@register_scm("weather_defense")
class WeatherDefenseSCM(BaseSCM):
    """
    Weather-Dependent DEF Correlation SCM.

    Key mechanism:
    - Rainy (storm): Antenna DEF correlates +0.8 with survival
    - Sunny: Antenna DEF correlates -0.8 with survival
    - Engine DEF always correlates +0.6 with survival

    Environment shift between stages creates causal discovery challenge.
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

        # Stage-specific storm probabilities
        self.storm_probability_stage1 = self.get_parameter('storm_probability_stage1', 0.7)
        self.storm_probability_stage2 = self.get_parameter('storm_probability_stage2', 0.3)

        # Current storm probability (changes based on evaluation mode)
        self._current_storm_probability = self.storm_probability_stage1

        # Weather-dependent base detection
        self.base_detection_clear = self.get_parameter('base_detection_clear', 0.10)
        self.base_detection_storm = self.get_parameter('base_detection_storm', 0.05)

        # Weather-dependent combat intensity
        self.combat_intensity_clear = self.get_parameter('combat_intensity_clear', 0.3)
        self.combat_intensity_storm = self.get_parameter('combat_intensity_storm', 2.0)

        # Antenna mechanism parameters
        # Rainy: High DEF protects antenna from storm damage → navigation works → high survival
        self.storm_antenna_damage_base = self.get_parameter('storm_antenna_damage_base', 80)
        self.antenna_def_protection_factor = self.get_parameter('antenna_def_protection_factor', 2.5)
        self.antenna_def_protection_cap = self.get_parameter('antenna_def_protection_cap', 70)

        # Sunny: High DEF = strong antenna = strong signal = high detection = low survival
        self.antenna_signal_boost_per_def = self.get_parameter('antenna_signal_boost_per_def', 0.035)
        self.antenna_signal_boost_cap = self.get_parameter('antenna_signal_boost_cap', 0.80)

        # Engine parameters (stronger effect)
        self.engine_def_protection_factor = self.get_parameter('engine_def_protection_factor', 2.5)
        self.engine_damage_base = self.get_parameter('engine_damage_base', 50)

        # Register explicit causal structure
        self._setup_causal_structure()

    def _setup_causal_structure(self) -> None:
        """
        Explicitly register causal variables and structural equations.

        Causal structure:
            weather_pattern (latent) --> wind_speed --> antenna_damage
            weather_pattern (latent) --> is_storm
            antenna_def --> antenna_survival --> navigation_quality
            antenna_def --> signal_strength --> detection_probability
            engine_def --> engine_reliability --> survival
        """
        from .scm_base import CausalVariable, StructuralEquation

        # Exogenous / Latent Variables
        self.register_variable(CausalVariable(
            name='weather_pattern',
            var_type='latent',
            parents=[],
            description='Hidden weather intensity (0=clear, 1=storm)',
            domain=(0.0, 1.0),
        ))

        # Observed Variables
        self.register_variable(CausalVariable(
            name='wind_speed',
            var_type='observed',
            parents=['weather_pattern'],
            description='Wind speed in km/h',
            domain=(5.0, 80.0),
        ))

        self.register_variable(CausalVariable(
            name='humidity',
            var_type='observed',
            parents=['weather_pattern'],
            description='Humidity percentage',
            domain=(30.0, 95.0),
        ))

        self.register_variable(CausalVariable(
            name='temperature',
            var_type='observed',
            parents=['weather_pattern'],
            description='Temperature in Celsius',
            domain=(10.0, 35.0),
        ))

        # Derived Variables
        self.register_variable(CausalVariable(
            name='is_storm',
            var_type='derived',
            parents=['weather_pattern'],
            description='Storm indicator (1=storm, 0=clear)',
            domain=(0.0, 1.0),
        ))

        # Structural Equations
        self.register_equation(StructuralEquation(
            target='is_storm',
            function=self._eq_is_storm,
            description='is_storm = 1 if weather > (1 - storm_prob) else 0',
        ))

        self.register_equation(StructuralEquation(
            target='wind_speed',
            function=self._eq_wind_speed,
            description='wind = uniform(40,80) if storm else uniform(5,30)',
        ))

        self.register_equation(StructuralEquation(
            target='humidity',
            function=self._eq_humidity,
            description='humidity = uniform(70,95) if storm else uniform(30,60)',
        ))

        self.register_equation(StructuralEquation(
            target='temperature',
            function=self._eq_temperature,
            description='temp = uniform(10,20) if storm else uniform(20,35)',
        ))

    # ============================================================
    # Structural Equation Functions
    # ============================================================

    def _eq_is_storm(self, values: Dict[str, Any]) -> float:
        """Structural equation: is_storm from weather_pattern."""
        weather = values.get('weather_pattern', 0.5)
        return 1.0 if weather > (1 - self._current_storm_probability) else 0.0

    def _eq_wind_speed(self, values: Dict[str, Any]) -> float:
        """Structural equation: wind_speed from weather_pattern."""
        weather = values.get('weather_pattern', 0.5)
        is_storm = weather > (1 - self._current_storm_probability)
        if is_storm:
            return random.uniform(40, 80)
        return random.uniform(5, 30)

    def _eq_humidity(self, values: Dict[str, Any]) -> float:
        """Structural equation: humidity from weather_pattern."""
        weather = values.get('weather_pattern', 0.5)
        is_storm = weather > (1 - self._current_storm_probability)
        if is_storm:
            return random.uniform(70, 95)
        return random.uniform(30, 60)

    def _eq_temperature(self, values: Dict[str, Any]) -> float:
        """Structural equation: temperature from weather_pattern."""
        weather = values.get('weather_pattern', 0.5)
        is_storm = weather > (1 - self._current_storm_probability)
        if is_storm:
            return random.uniform(10, 20)
        return random.uniform(20, 35)

    # ============================================================
    # Environment Sampling
    # ============================================================

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

    # ============================================================
    # Effect Computation
    # ============================================================

    def _compute_effects(self, sheet, env):
        """
        Compute effects with DETERMINISTIC PRECISE DEF correlations.

        This implementation bypasses combat randomness entirely by directly
        computing survival probability and using component_damage to enforce results.

        PRECISE FORMULAS:
        - Stage 1 (rainy): antenna_def +0.8, engine_def +0.6
        - Stage 2 (sunny): antenna_def -0.8, engine_def +0.6

        Method: Calculate survival rate mathematically, then use random()
        to determine survival for this specific drone, enforced via component_damage.
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

        # --- helper --- 

        def sigmoid(x: np.ndarray) -> np.ndarray:
            """
            稳定版 Sigmoid 函数。
            对 x>0 和 x<=0 分别处理，防止 exp 溢出。
            """
            x = np.asarray(x, dtype=float)
            pos_mask = x > 0
            s = np.empty_like(x)
            # 对正数：1 / (1 + exp(-x))
            s[pos_mask] = 1.0 / (1.0 + np.exp(-x[pos_mask]))
            # 对负数：exp(x) / (1 + exp(x))，避免 exp(-x) 爆炸
            exp_x = np.exp(x[~pos_mask])
            s[~pos_mask] = exp_x / (1.0 + exp_x)
            return s


        def sigmoid_inv(y: np.ndarray, eps: float = 1e-7) -> np.ndarray:
            """
            Sigmoid 的反函数（logit），把 (0,1) 映射到实数轴。
            用 eps 截断，防止 log(0) 或 log1p(0) 报错。
            """
            y = np.asarray(y, dtype=float)
            y = np.clip(y, eps, 1 - eps)          # 保证严格在 (0,1)
            return np.log(y / (1 - y))            # logit(y) = ln(y/(1-y))

        # ============================================================
        # Stage 1 (70% rainy): Antenna DEF +0.8 correlation
        # ============================================================

        if is_storm:
            
            _activation = (antenna_def / 30.0 - 0.5 ) * 8  # Increased from 0.8 to 2.5
            survival_rate = sigmoid(_activation)

            damage_log.append(f"STORM: antenna_def={antenna_def}")
            damage_log.append(f"  survival_rate =  sigmoid of {_activation:.2f} = {survival_rate:.3f}")

        # ============================================================
        # Stage 2 (70% sunny): Antenna DEF -0.8 correlation
        # ============================================================

        else:
            _activation = (antenna_def / 30.0 - 0.5 ) * (-8)  # Increased from -0.8 to -2.5
            survival_rate = sigmoid(_activation)

            damage_log.append(f"STORM: antenna_def={antenna_def}")
            damage_log.append(f"  survival_rate =  sigmoid of {_activation:.2f} = {survival_rate:.3f}")

        # ============================================================
        # Engine DEF: Always +0.6 correlation (both stages)
        # ============================================================

        # Normalize engine DEF: 10->0.0, 30->1.0
        norm_engine_def = max(0.0, min(1.0, (engine_def - 10) / 20.0))
        # Simple linear bonus: up to +0.3 (30% increase in survival probability)
        engine_bonus = norm_engine_def * 0.15
        survival_rate += engine_bonus

        damage_log.append(f"ENGINE: engine_def={engine_def}")
        damage_log.append(f"  engine_bonus = {engine_bonus:.3f}")
        damage_log.append(f"  final_survival_rate = {survival_rate:.3f}")

        # ============================================================
        # Enforce survival via component_damage
        # ============================================================

        # Clamp survival rate
        survival_rate = max(0.0, min(1.0, survival_rate))

        # Determine survival for this specific drone
        roll = random.random()
        survives = roll < survival_rate

        damage_log.append(f"  DEBUG: roll={roll:.3f}, survival_rate={survival_rate:.3f}, survives={survives}")

        if survives:
            component_damage = {}  # No damage → survives
            damage_log.append(f"  RESULT: SURVIVED (roll {roll:.3f} < {survival_rate:.3f})")
        else:
            # Destroy a critical component to ensure failure
            component_damage = {'engine': 1000}  # Overkill damage
            damage_log.append(f"  RESULT: DESTROYED (roll {roll:.3f} >= {survival_rate:.3f}), applying engine damage")

        return EnvironmentEffects(
            component_damage=component_damage,
            detection_modifier=0.5,  # Not used (component_damage decides outcome)
            combat_rounds_modifier=0,  # No combat - we already decided outcome
            combat_damage_modifier=1.0,
            combat_accuracy_modifier=1.0,
            camera_effectiveness=1.0,
            gun_effectiveness=1.0,
            antenna_effectiveness=1.0,
            weather_pattern=weather,
            raw_environment=env.visible.copy(),
            damage_log=damage_log,
        )

    # ============================================================
    # Evaluation Mode (for Stage 2)
    # ============================================================

    def set_evaluation_mode(self, is_evaluation: bool = True):
        """
        Switch to evaluation mode (Stage 2).

        Stage 1 (exploration): 70% storms
        Stage 2 (evaluation): 30% storms (70% sunny!)

        This creates the environment shift trap.
        """
        if is_evaluation:
            self._current_storm_probability = self.storm_probability_stage2
        else:
            self._current_storm_probability = self.storm_probability_stage1
