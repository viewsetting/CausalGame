"""
AntennaTrapSCM - Antenna Detection Trap experiment.

The trap: Antenna affects detection probability.
- Working antenna = strong signal = high detection
- Damaged antenna = weak/no signal = low detection (stealth)

But removing antenna has other consequences:
- No navigation assistance
- No communication

Causal structure:
    weather_pattern (latent) ---> wind_speed ---> antenna_damage
    antenna_hp ---> signal_strength ---> detection_probability
"""

from typing import Dict, Any
import random

from .scm_base import BaseSCM, EnvironmentState, CausalVariable, StructuralEquation
from .scm_registry import register_scm


@register_scm("antenna_trap")
@register_scm("antenna_trap_no_history")
@register_scm("antenna_trap_biased_history")
@register_scm("antenna_trap_clear_weather")
@register_scm("antenna_trap_clear_weather_only")
@register_scm("antenna_trap_high_def")
@register_scm("antenna_trap_critical_focus")
@register_scm("antenna_trap_local_optima")
@register_scm("antenna_trap_simpsons_paradox")
@register_scm("antenna_trap_anti_correlation")
@register_scm("antenna_trap_random_designs")
@register_scm("antenna_trap_obs100")
@register_scm("antenna_trap_obs300")
@register_scm("antenna_trap_obs1000")
class AntennaTrapSCM(BaseSCM):
    """
    Antenna Detection Trap SCM.

    The trap: Antenna affects detection probability.
    - Working antenna = strong signal = high detection
    - Damaged antenna = weak/no signal = low detection (stealth)

    But removing antenna has other consequences:
    - No navigation assistance
    - No communication

    Causal structure:
        weather_pattern (latent) ---> wind_speed ---> antenna_damage
        antenna_hp ---> signal_strength ---> detection_probability
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

        # Load parameters from scm.parameters config (with fallback to top-level)
        # Latent weather confounder parameters
        self.storm_probability = self.get_parameter('storm_probability', 0.5)

        # Weather-dependent base detection
        self.base_detection_clear = self.get_parameter('base_detection_clear', 0.55)
        self.base_detection_storm = self.get_parameter('base_detection_storm', 0.20)

        # Weather-dependent combat intensity
        self.combat_intensity_clear = self.get_parameter('combat_intensity_clear', 1.0)
        self.combat_intensity_storm = self.get_parameter('combat_intensity_storm', 1.8)

        # Antenna trap parameters
        self.antenna_emission_boost = self.get_parameter('antenna_emission_boost', 0.55)
        self.stealth_mode_reduction = self.get_parameter('stealth_mode_reduction', 0.4)

        # Wind damage thresholds
        self.wind_threshold_high = self.get_parameter('wind_threshold_high', 35)
        self.wind_threshold_low = self.get_parameter('wind_threshold_low', 20)

        # Camera evasion parameters (hidden positive effect)
        # Camera provides situational awareness, reducing detection when functional
        self.camera_evasion_bonus = self.get_parameter('camera_evasion_bonus', 0.12)
        self.camera_destroyed_detection_penalty = self.get_parameter('camera_destroyed_detection_penalty', 1.20)

        # DEF protection factor for non-critical components
        # Lower = less protection from DEF, making antenna more vulnerable
        self.antenna_def_factor = self.get_parameter('antenna_def_factor', 5.0)
        self.camera_def_factor = self.get_parameter('camera_def_factor', 5.0)
        self.gun_def_factor = self.get_parameter('gun_def_factor', 3.0)

        # Gun combat effect parameters (hidden positive effect)
        # Gun provides firepower, reducing damage taken in combat when functional
        self.gun_damage_reduction = self.get_parameter('gun_damage_reduction', 0.35)
        self.gun_destroyed_damage_penalty = self.get_parameter('gun_destroyed_damage_penalty', 1.5)

        # Register explicit causal structure
        self._setup_causal_structure()

    def _setup_causal_structure(self) -> None:
        """
        Explicitly register causal variables and structural equations.

        Causal structure:
            weather_pattern (latent) --> wind_speed --> antenna_damage
            weather_pattern (latent) --> humidity
            weather_pattern (latent) --> is_storm
            antenna_hp --> signal_strength --> detection_probability
        """
        # ============================================================
        # Exogenous / Latent Variables
        # ============================================================
        self.register_variable(CausalVariable(
            name='weather_pattern',
            var_type='latent',
            parents=[],
            description='Hidden storm intensity (0=clear, 1=severe)',
            domain=(0.0, 1.0),
        ))

        # ============================================================
        # Observed Variables
        # ============================================================
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

        # ============================================================
        # Derived Variables
        # ============================================================
        self.register_variable(CausalVariable(
            name='is_storm',
            var_type='derived',
            parents=['weather_pattern'],
            description='Storm indicator (1=storm, 0=clear)',
            domain=(0.0, 1.0),
        ))

        self.register_variable(CausalVariable(
            name='antenna_damage',
            var_type='derived',
            parents=['wind_speed'],
            description='Raw antenna damage before DEF mitigation',
            domain=(0.0, 75.0),
        ))

        self.register_variable(CausalVariable(
            name='signal_strength',
            var_type='derived',
            parents=['antenna_hp'],
            description='Antenna signal strength (0=no signal, 1=full)',
            domain=(0.0, 1.0),
        ))

        self.register_variable(CausalVariable(
            name='detection_probability',
            var_type='derived',
            parents=['signal_strength', 'weather_pattern'],
            description='Probability of being detected by enemies',
            domain=(0.0, 1.0),
        ))

        # Placeholder for antenna HP (set during simulation)
        self.register_variable(CausalVariable(
            name='antenna_hp',
            var_type='observed',
            parents=['antenna_damage'],
            description='Antenna HP after damage (initial 50)',
            domain=(0.0, 50.0),
        ))

        # ============================================================
        # Structural Equations
        # ============================================================
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

        self.register_equation(StructuralEquation(
            target='antenna_damage',
            function=self._eq_antenna_damage,
            description='damage = f(wind_speed) based on thresholds',
        ))

        self.register_equation(StructuralEquation(
            target='signal_strength',
            function=self._eq_signal_strength,
            description='signal = min(1, antenna_hp / 50)',
        ))

        self.register_equation(StructuralEquation(
            target='detection_probability',
            function=self._eq_detection_probability,
            description='detection = base + boost * signal if emitting else base * stealth_reduction',
        ))

    # ============================================================
    # Structural Equation Functions
    # ============================================================

    def _eq_is_storm(self, values: Dict[str, Any]) -> float:
        """Structural equation: is_storm from weather_pattern."""
        weather = values.get('weather_pattern', 0.5)
        return 1.0 if weather > (1 - self.storm_probability) else 0.0

    def _eq_wind_speed(self, values: Dict[str, Any]) -> float:
        """Structural equation: wind_speed from weather_pattern."""
        weather = values.get('weather_pattern', 0.5)
        is_storm = weather > (1 - self.storm_probability)
        if is_storm:
            return random.uniform(40, 80)
        return random.uniform(5, 30)

    def _eq_humidity(self, values: Dict[str, Any]) -> float:
        """Structural equation: humidity from weather_pattern."""
        weather = values.get('weather_pattern', 0.5)
        is_storm = weather > (1 - self.storm_probability)
        if is_storm:
            return random.uniform(70, 95)
        return random.uniform(30, 60)

    def _eq_temperature(self, values: Dict[str, Any]) -> float:
        """Structural equation: temperature from weather_pattern."""
        weather = values.get('weather_pattern', 0.5)
        is_storm = weather > (1 - self.storm_probability)
        if is_storm:
            return random.uniform(10, 20)
        return random.uniform(20, 35)

    def _eq_antenna_damage(self, values: Dict[str, Any]) -> float:
        """Structural equation: antenna_damage from wind_speed."""
        wind_speed = values.get('wind_speed', 20)
        if wind_speed > self.wind_threshold_high:
            return random.uniform(55, 75)
        elif wind_speed > self.wind_threshold_low:
            return random.uniform(35, 55)
        return 0.0

    def _eq_signal_strength(self, values: Dict[str, Any]) -> float:
        """Structural equation: signal_strength from antenna_hp."""
        antenna_hp = values.get('antenna_hp', 50)
        if antenna_hp <= 0:
            return 0.0
        return min(1.0, antenna_hp / 50.0)

    def _eq_detection_probability(self, values: Dict[str, Any]) -> float:
        """Structural equation: detection from signal_strength and weather."""
        signal = values.get('signal_strength', 1.0)
        weather = values.get('weather_pattern', 0.5)
        antenna_emitting = signal > 0

        weather_detection = self._interpolate(
            weather, self.base_detection_clear, self.base_detection_storm
        )

        if antenna_emitting:
            return weather_detection + self.antenna_emission_boost * signal
        else:
            return weather_detection * self.stealth_mode_reduction

    def sample_environment(self, equipment: dict = None) -> EnvironmentState:
        """
        Sample environment with latent weather_pattern confounder.

        Similar to LatentConfounderSCM - weather affects both wind and detection.

        Args:
            equipment: Optional equipment choices (unused in this SCM)
        """
        weather = random.random()
        is_storm = weather > (1 - self.storm_probability)
        weather_pattern = weather if is_storm else weather * 0.5

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
                'weather_pattern': weather_pattern,
            },
            derived={
                'is_storm': float(is_storm),
            }
        )

    def _compute_effects(self, sheet, env):
        """
        Compute effects with antenna trap mechanism.

        Key causal mechanism:
        - weather_pattern -> wind_speed -> antenna_damage
        - antenna_hp (AFTER damage) -> signal_strength -> detection_probability

        IMPORTANT: Stealth mode is ONLY triggered by antenna being destroyed
        by environmental damage. Agent cannot directly control stealth by
        setting antenna_def=0. High DEF protects antenna from destruction.

        THE TRAP:
        - High antenna_def: Protects antenna → antenna survives → emits signal → detected
        - Low antenna_def: Antenna vulnerable → destroyed by storm → stealth mode
        - Agent must discover that protecting antenna leads to being detected
        """
        try:
            from ...middleware.drone_state import EnvironmentEffects
        except ImportError:
            from middleware.drone_state import EnvironmentEffects

        weather = env.latent.get('weather_pattern', env.derived.get('weather_pattern', 0.5))
        wind_speed = env.visible.get('wind_speed', 20)
        is_storm = env.derived.get('is_storm', 0) > 0.5

        # ========== Component damage from wind ==========
        component_damage = {}
        antenna_damage = 0
        camera_damage = 0
        gun_damage = 0

        # Storm causes antenna damage (raw value, will apply DEF reduction below)
        # KEY BALANCE: Only very low antenna_def should result in stealth
        if wind_speed > self.wind_threshold_high:
            antenna_damage = int(random.uniform(55, 75))  # High wind damage
            camera_damage = int(random.uniform(25, 40))   # Camera also damaged by high wind
            gun_damage = int(random.uniform(35, 50))      # Gun damaged by debris (gun HP=30)
        elif wind_speed > self.wind_threshold_low:
            antenna_damage = int(random.uniform(35, 55))  # Medium damage
            camera_damage = int(random.uniform(10, 25))   # Light camera damage
            gun_damage = int(random.uniform(20, 35))      # Gun damage in medium wind
        # NOTE: component_damage['antenna'] is set AFTER DEF reduction calculation below

        # Storm damages critical components
        # KEY BALANCE: Components with low DEF take MUCH more damage
        # This punishes Zero DEF strategies while rewarding smart allocation
        critical_components = ['engine', 'cockpit', 'wing', 'body']

        if wind_speed > 50:
            for comp in ['wing', 'engine']:
                comp_def = sheet._def.get(comp, 0)
                # Base damage from wind
                base_damage = random.uniform(40, 70)
                # LOW DEF PENALTY: Unprotected components take massive extra damage
                # If DEF < 15, take up to 100% extra damage (double damage!)
                if comp_def < 15:
                    vulnerability_mult = 1.0 + 1.0 * (1.0 - comp_def / 15.0)
                    base_damage *= vulnerability_mult
                component_damage[comp] = int(base_damage)

        if weather > 0.7:
            for comp in ['body', 'cockpit']:
                comp_def = sheet._def.get(comp, 0)
                base_damage = random.uniform(30, 55)
                # Same vulnerability penalty for low DEF
                if comp_def < 15:
                    vulnerability_mult = 1.0 + 1.0 * (1.0 - comp_def / 15.0)
                    base_damage *= vulnerability_mult
                component_damage[comp] = int(base_damage)

        # ========== Calculate actual antenna damage after DEF mitigation ==========
        antenna_def = sheet._def.get('antenna', 10)
        original_antenna_hp = sheet._hp.get('antenna', 50)

        # DEF reduces damage: higher DEF = better protection
        # This is the KEY mechanism: high antenna_def keeps antenna alive!
        #
        # NEW Balance target (stealth only at very low antenna_def):
        # - antenna_def = 0:  reduction = 0 → full damage → destroyed (stealth)
        # - antenna_def = 5:  reduction = 10 → significant damage → often destroyed
        # - antenna_def = 10: reduction = 20 → reduced damage → usually survives (detected!)
        # - antenna_def = 30: reduction = 60 → minimal damage → always survives (detected!)
        # Antenna DEF protection: higher factor = better protection
        # Use configurable factor from game.json (antenna_def_factor)
        # Lower factor = antenna more vulnerable to damage
        if antenna_damage > 0:
            reduction = int(antenna_def * self.antenna_def_factor)
            # Cap reduction at 80% of raw damage
            max_reduction = int(antenna_damage * 0.8)
            reduction = min(reduction, max_reduction)
            actual_antenna_damage = max(1, antenna_damage - reduction)
        else:
            actual_antenna_damage = 0

        predicted_antenna_hp = max(0, original_antenna_hp - actual_antenna_damage)

        # Store ACTUAL damage in component_damage (after DEF reduction)
        # This ensures DroneSheet uses the same damage we calculated
        if actual_antenna_damage > 0:
            component_damage['antenna'] = actual_antenna_damage

        # ========== Calculate camera damage after DEF mitigation ==========
        # Camera provides hidden positive effect (evasion/situational awareness)
        # Agent who blindly minimizes all non-critical DEF will lose camera benefit
        camera_def = sheet._def.get('camera', 5)
        original_camera_hp = sheet._hp.get('camera', 20)

        if camera_damage > 0:
            # Camera DEF protection (uses configurable factor)
            reduction = int(camera_def * self.camera_def_factor)
            max_reduction = int(camera_damage * 0.8)
            reduction = min(reduction, max_reduction)
            actual_camera_damage = max(1, camera_damage - reduction)
        else:
            actual_camera_damage = 0

        predicted_camera_hp = max(0, original_camera_hp - actual_camera_damage)

        if actual_camera_damage > 0:
            component_damage['camera'] = actual_camera_damage

        camera_functional = predicted_camera_hp > 0

        # ========== Calculate gun damage after DEF mitigation ==========
        # Gun provides hidden positive effect (combat damage reduction)
        # Agent who blindly minimizes all non-critical DEF will lose gun benefit
        gun_def = sheet._def.get('gun', 5)
        original_gun_hp = sheet._hp.get('gun', 30)

        if gun_damage > 0:
            # Gun DEF protection (uses configurable factor)
            reduction = int(gun_def * self.gun_def_factor)
            max_reduction = int(gun_damage * 0.8)
            reduction = min(reduction, max_reduction)
            actual_gun_damage = max(1, gun_damage - reduction)
        else:
            actual_gun_damage = 0

        predicted_gun_hp = max(0, original_gun_hp - actual_gun_damage)

        if actual_gun_damage > 0:
            component_damage['gun'] = actual_gun_damage

        gun_functional = predicted_gun_hp > 0

        # ========== THE TRAP: Antenna state determines detection ==========
        # CRITICAL: Stealth is ONLY achieved when antenna is DESTROYED
        # - Antenna survives (HP > 0) → emits signal → high detection
        # - Antenna destroyed (HP <= 0) → no signal → stealth mode
        #
        # Agent CANNOT directly control this. They can only:
        # - High antenna_def: Protects antenna → survives → detected!
        # - Low antenna_def: Antenna vulnerable → destroyed by storm → stealth
        #
        # The trap: protecting antenna seems right but leads to detection

        antenna_emitting = predicted_antenna_hp > 0  # ONLY destroyed antenna = stealth

        # ========== Detection probability based on antenna state ==========
        weather_detection = self._interpolate(
            weather, self.base_detection_clear, self.base_detection_storm
        )

        # ========== CAMERA EFFECT: Stealth effectiveness ==========
        # Camera provides situational awareness for stealth mode
        # Without camera, stealth mode is less effective (easier to be spotted visually)
        if camera_functional:
            camera_effectiveness = min(1.0, predicted_camera_hp / 20.0)
            # Camera bonus: slightly better stealth
            effective_stealth_reduction = self.stealth_mode_reduction * (1.0 - self.camera_evasion_bonus * camera_effectiveness)
            camera_accuracy_mod = 1.0 - self.camera_evasion_bonus * camera_effectiveness
        else:
            # Camera destroyed = cannot maintain proper stealth, easier to spot
            # Stealth reduction becomes much worse (higher detection in stealth mode)
            effective_stealth_reduction = self.stealth_mode_reduction * self.camera_destroyed_detection_penalty
            camera_accuracy_mod = self.camera_destroyed_detection_penalty

        if antenna_emitting:
            # Antenna alive = broadcasting signal = HIGH detection
            signal_strength = min(1.0, predicted_antenna_hp / 50.0)
            detection_modifier = weather_detection + self.antenna_emission_boost * signal_strength
        else:
            # Antenna destroyed = no signal = STEALTH mode
            # Detection reduced, but camera affects how effective stealth is
            detection_modifier = weather_detection * effective_stealth_reduction

        # ========== Combat intensity ==========
        base_combat = self._interpolate(
            weather, self.combat_intensity_clear, self.combat_intensity_storm
        )
        # More combat if detected (antenna emitting), fewer if stealth
        # Stealth encounters are brief (enemies quickly lose track)
        combat_rounds_mod = base_combat * (1.8 if antenna_emitting else 0.3)

        # ========== GUN EFFECT: Combat damage modifier ==========
        # Gun provides firepower for counter-attack/deterrence
        # With gun: enemies take more caution, deal less damage
        # Without gun: enemies are more aggressive, deal more damage
        if gun_functional:
            gun_effectiveness = min(1.0, predicted_gun_hp / 30.0)
            # Gun reduces incoming damage by up to gun_damage_reduction (35%)
            combat_damage_mod = 1.0 - self.gun_damage_reduction * gun_effectiveness
        else:
            # Gun destroyed = enemies more aggressive = more damage taken
            combat_damage_mod = self.gun_destroyed_damage_penalty

        return EnvironmentEffects(
            component_damage=component_damage,
            detection_modifier=detection_modifier,
            combat_rounds_modifier=combat_rounds_mod,
            combat_accuracy_modifier=camera_accuracy_mod,
            combat_damage_modifier=combat_damage_mod,
            weather_pattern=weather,
            raw_environment=env.visible.copy(),
            damage_log=[
                f"Weather pattern: {weather:.2f} (storm={is_storm})",
                f"Wind speed: {wind_speed:.1f}",
                f"Antenna DEF: {antenna_def}",
                f"Antenna damage: {antenna_damage} (mitigated: {actual_antenna_damage})",
                f"Antenna HP: {original_antenna_hp} -> {predicted_antenna_hp}",
                f"Antenna emitting: {antenna_emitting}",
                f"Camera DEF: {camera_def}",
                f"Camera damage: {camera_damage} (mitigated: {actual_camera_damage})",
                f"Camera HP: {original_camera_hp} -> {predicted_camera_hp}",
                f"Camera functional: {camera_functional}",
                f"Camera accuracy modifier: {camera_accuracy_mod:.2f}",
                f"Gun DEF: {gun_def}",
                f"Gun damage: {gun_damage} (mitigated: {actual_gun_damage})",
                f"Gun HP: {original_gun_hp} -> {predicted_gun_hp}",
                f"Gun functional: {gun_functional}",
                f"Combat damage modifier: {combat_damage_mod:.2f}",
                f"Detection modifier: {detection_modifier:.2f}",
                f"Combat rounds modifier: {combat_rounds_mod:.2f}",
            ]
        )
