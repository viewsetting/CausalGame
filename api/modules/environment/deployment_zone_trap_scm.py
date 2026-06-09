"""
DeploymentZoneTrapSCM - Deployment Zone Trap experiment.

Based on William Farr's altitude-cholera research (1849):
- Farr observed: Low altitude areas had high cholera death rates
- Farr concluded: "Miasma" (bad air) at low altitude caused disease
- True cause: Water source pollution (hidden confounder)

Isomorphic mapping to drone scenario:
- Agent observes: Low altitude flight = high loss rate (spurious correlation)
- Agent may conclude: High altitude is safer, invest in engine_def
- True cause: EMI (electromagnetic interference) in certain zones
- The confounder: Mission zone determines BOTH altitude AND EMI level

Causal structure:
    mission_zone (hidden) --> altitude_band (visible)
    mission_zone (hidden) --> emi_level (hidden)
    emi_level --> comm_failure --> drone_loss

    NOT: altitude_band --> drone_loss (this is the spurious correlation trap!)

Correct strategy: Invest in shield_def to resist EMI
Trap strategy: Invest in engine_def for high-altitude capability
"""

from typing import Dict, Any
import random

from .scm_base import BaseSCM, EnvironmentState, CausalVariable, StructuralEquation
from .scm_registry import register_scm


@register_scm("deployment_zone_trap")
@register_scm("deployment_zone_trap_categorical")
@register_scm("deployment_zone_trap_categorical_no_history")
@register_scm("deployment_zone_trap_categorical_high_def")
@register_scm("deployment_zone_trap_categorical_local_optima")
@register_scm("deployment_zone_trap_categorical_simpsons_paradox")
@register_scm("deployment_zone_trap_categorical_high_emi_only")
class DeploymentZoneTrapSCM(BaseSCM):
    """
    Deployment Zone Trap SCM.

    The trap: Low altitude correlates with high loss rate, but altitude
    is NOT the cause. EMI (electromagnetic interference) is the true cause.
    Low-altitude zones HAPPEN to have more EMI sources (spurious correlation).

    Key insight: The agent must discover that:
    1. Altitude-loss correlation is spurious
    2. EMI is the hidden confounder
    3. Shield_def protects against EMI

    Causal structure:
        mission_zone (hidden confounder)
            |
            +--> altitude_band (visible, but NOT causal!)
            |
            +--> emi_level (hidden) --> comm_failure --> loss
    """

    # Zone definitions with altitude and EMI properties
    ZONE_TYPES = {
        'alpha': {  # Safe high-altitude corridor
            'altitude_band': 'high',
            'emi_level': 0.1,
            'probability': 0.15,
            'description': 'High-altitude safe corridor',
        },
        'beta': {  # Mixed medium-altitude zone
            'altitude_band': 'medium',
            'emi_level': 0.4,
            'probability': 0.25,
            'description': 'Medium-altitude mixed zone',
        },
        'gamma': {  # Low-altitude EMI heavy zone (main trap!)
            'altitude_band': 'low',
            'emi_level': 0.9,
            'probability': 0.35,
            'description': 'Low-altitude high-EMI zone',
        },
        'delta': {  # Low-altitude SAFE zone (counter-example!)
            'altitude_band': 'low',
            'emi_level': 0.1,
            'probability': 0.10,
            'description': 'Low-altitude safe corridor',
        },
        'epsilon': {  # High-altitude EMI zone (counter-example!)
            'altitude_band': 'high',
            'emi_level': 0.8,
            'probability': 0.15,
            'description': 'High-altitude EMI zone',
        },
    }

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

        # EMI effect parameters
        self.emi_base_failure_rate = self.get_parameter('emi_base_failure_rate', 0.7)
        self.emi_threshold = self.get_parameter('emi_threshold', 0.3)

        # Shield effectiveness
        self.shield_effectiveness = self.get_parameter('shield_effectiveness', 0.025)
        self.max_shield_reduction = self.get_parameter('max_shield_reduction', 0.8)

        # Communication failure consequences
        self.comm_failure_loss_rate = self.get_parameter('comm_failure_loss_rate', 0.85)
        self.base_loss_rate = self.get_parameter('base_loss_rate', 0.12)

        # Wind damage by altitude (minor effect, NOT the main cause)
        self.altitude_wind_damage = self.get_parameter('altitude_wind_damage', {
            'low': 0.05,
            'medium': 0.10,
            'high': 0.15,
        })

        # Altitude signal modifier (slight effect, misleading hint)
        self.altitude_signal_modifier = {
            'low': -0.05,   # Low altitude = slightly better signal
            'medium': 0.0,
            'high': 0.05,   # High altitude = slightly worse signal
        }

        self._setup_causal_structure()

    def _setup_causal_structure(self) -> None:
        """Register causal variables and structural equations."""

        # === Exogenous variable: Mission Zone (THE HIDDEN CONFOUNDER) ===
        self.register_variable(CausalVariable(
            name='mission_zone',
            var_type='latent',
            parents=[],
            description='Mission zone assignment (hidden confounder)',
        ))

        # === Observed variables ===
        self.register_variable(CausalVariable(
            name='altitude_band',
            var_type='observed',
            parents=['mission_zone'],
            description='Flight altitude band (low/medium/high) - VISIBLE but NOT causal!',
        ))

        self.register_variable(CausalVariable(
            name='wind_resistance',
            var_type='observed',
            parents=['altitude_band'],
            description='Wind resistance coefficient',
            domain=(0.1, 1.0),
        ))

        self.register_variable(CausalVariable(
            name='signal_strength',
            var_type='observed',
            parents=['altitude_band'],
            description='Base signal strength (visible, slight altitude effect)',
            domain=(0.0, 1.0),
        ))

        # === Action variables (Agent can intervene) ===
        self.register_variable(CausalVariable(
            name='shield_def',
            var_type='action',
            parents=[],
            description='Shield defense value - Agent intervention point',
            domain=(0, 50),
        ))

        # === Latent variables (THE TRUE CAUSES) ===
        self.register_variable(CausalVariable(
            name='emi_level',
            var_type='latent',
            parents=['mission_zone'],
            description='EMI intensity - THE TRUE CAUSE (hidden!)',
            domain=(0.0, 1.0),
        ))

        self.register_variable(CausalVariable(
            name='effective_emi',
            var_type='latent',
            parents=['emi_level', 'shield_def'],
            description='EMI after shield mitigation',
            domain=(0.0, 1.0),
        ))

        self.register_variable(CausalVariable(
            name='comm_failure_prob',
            var_type='latent',
            parents=['effective_emi'],
            description='Communication failure probability',
            domain=(0.0, 1.0),
        ))

        self.register_variable(CausalVariable(
            name='drone_loss',
            var_type='outcome',
            parents=['comm_failure_prob'],
            description='Drone destruction outcome',
            domain=(0.0, 1.0),
        ))

        # === Causal edges ===
        # The key spurious correlation: zone -> altitude AND zone -> emi
        self.add_causal_edge('mission_zone', 'altitude_band')
        self.add_causal_edge('mission_zone', 'emi_level')

        # Observable effects of altitude (minor, misleading)
        self.add_causal_edge('altitude_band', 'wind_resistance')
        self.add_causal_edge('altitude_band', 'signal_strength')

        # TRUE causal path: EMI -> comm_failure -> loss
        self.add_causal_edge('emi_level', 'effective_emi')
        self.add_causal_edge('shield_def', 'effective_emi')  # Agent intervention
        self.add_causal_edge('effective_emi', 'comm_failure_prob')
        self.add_causal_edge('comm_failure_prob', 'drone_loss')

        # === Structural equations ===
        self.register_equation(StructuralEquation(
            target='altitude_band',
            function=self._eq_altitude_band,
            description='Altitude determined by zone',
        ))

        self.register_equation(StructuralEquation(
            target='emi_level',
            function=self._eq_emi_level,
            description='EMI determined by zone',
        ))

        self.register_equation(StructuralEquation(
            target='wind_resistance',
            function=self._eq_wind_resistance,
            description='Wind resistance varies with altitude',
        ))

        self.register_equation(StructuralEquation(
            target='signal_strength',
            function=self._eq_signal_strength,
            description='Signal strength has slight altitude effect',
        ))

    def _eq_altitude_band(self, values: Dict[str, Any]) -> str:
        """Altitude band determined by mission zone."""
        zone = values.get('mission_zone', 'beta')
        return self.ZONE_TYPES.get(zone, {}).get('altitude_band', 'medium')

    def _eq_emi_level(self, values: Dict[str, Any]) -> float:
        """EMI level determined by mission zone (with noise)."""
        zone = values.get('mission_zone', 'beta')
        base_emi = self.ZONE_TYPES.get(zone, {}).get('emi_level', 0.4)
        # Add some noise
        return max(0.0, min(1.0, base_emi + random.uniform(-0.1, 0.1)))

    def _eq_wind_resistance(self, values: Dict[str, Any]) -> float:
        """Wind resistance varies with altitude (visible effect)."""
        altitude = values.get('altitude_band', 'medium')
        base_wind = {'low': 0.2, 'medium': 0.5, 'high': 0.8}
        return base_wind.get(altitude, 0.5) + random.uniform(-0.1, 0.1)

    def _eq_signal_strength(self, values: Dict[str, Any]) -> float:
        """Signal strength has slight altitude effect (visible, misleading)."""
        altitude = values.get('altitude_band', 'medium')
        # High altitude = slightly worse signal (misleading hint!)
        base_signal = {'low': 0.9, 'medium': 0.85, 'high': 0.75}
        return base_signal.get(altitude, 0.85) + random.uniform(-0.05, 0.05)

    def sample_environment(self, equipment: dict = None) -> EnvironmentState:
        """Sample environment with hidden zone confounder.

        Args:
            equipment: Optional equipment/discrete choices from agent (includes flight_profile)
        """

        # Sample mission zone (determines EMI - the TRUE cause)
        zones = list(self.ZONE_TYPES.keys())
        weights = [self.ZONE_TYPES[z]['probability'] for z in zones]
        zone = random.choices(zones, weights=weights)[0]

        zone_info = self.ZONE_TYPES[zone]

        # Get EMI from zone (hidden!) - THIS IS THE TRUE CAUSE
        emi_level = zone_info['emi_level'] + random.uniform(-0.1, 0.1)
        emi_level = max(0.0, min(1.0, emi_level))

        # Altitude is determined by agent's flight_profile choice (if provided)
        # This is the TRAP: agent thinks they control altitude, but altitude doesn't affect survival!
        # EMI (from mission_zone) is the true cause.
        if equipment and 'flight_profile' in equipment:
            altitude_band = equipment['flight_profile']  # Agent's choice
        else:
            # Fallback to zone-based altitude (for historical data / no choice)
            altitude_band = zone_info['altitude_band']

        # Compute visible variables
        wind_resistance = self._eq_wind_resistance({'altitude_band': altitude_band})
        signal_strength = self._eq_signal_strength({'altitude_band': altitude_band})

        # Temperature varies with altitude (visible environmental detail)
        if altitude_band == 'high':
            temperature = random.uniform(-5, 10)
        elif altitude_band == 'medium':
            temperature = random.uniform(10, 20)
        else:
            temperature = random.uniform(15, 30)

        return EnvironmentState(
            visible={
                'altitude_band': altitude_band,
                'wind_resistance': wind_resistance,
                'signal_strength': signal_strength,
                'temperature': temperature,
            },
            latent={
                'mission_zone': zone,
                'emi_level': emi_level,
            },
            derived={
                'zone_description': zone_info['description'],
            }
        )

    def _compute_effects(self, sheet, env: EnvironmentState):
        """
        Compute effects with EMI as the true cause of losses.

        Key mechanism:
        - Shield_def reduces effective EMI
        - High EMI causes communication failures
        - Communication failures cause CRITICAL component damage (the main death mechanism)

        The trap:
        - Agent sees altitude correlates with loss
        - Agent may invest in engine_def for high-altitude
        - But altitude doesn't cause losses!
        - EMI causes losses, and shield_def protects against it
        """
        try:
            from ...middleware.drone_state import EnvironmentEffects
        except ImportError:
            from middleware.drone_state import EnvironmentEffects

        # Get hidden EMI level
        emi_level = env.latent.get('emi_level', 0.4)
        altitude_band = env.visible.get('altitude_band', 'medium')
        mission_zone = env.latent.get('mission_zone', 'beta')

        # === Shield mitigation of EMI ===
        shield_def = sheet._def.get('shield', 0)

        # Each point of shield_def reduces EMI impact
        shield_reduction = min(
            shield_def * self.shield_effectiveness,
            self.max_shield_reduction
        )

        # === Equipment effects (discrete action space choices) ===
        # Equipment can provide additional emi_resistance (or negative!)
        equipment_emi_resistance = 0.0
        if hasattr(sheet, '_equipment_effects') and sheet._equipment_effects:
            equipment_emi_resistance = getattr(sheet._equipment_effects, 'emi_resistance', 0.0)

        # Combine shield reduction with equipment resistance
        total_emi_reduction = min(0.95, shield_reduction + equipment_emi_resistance)
        effective_emi = emi_level * (1 - total_emi_reduction)

        # === Communication failure probability ===
        if effective_emi < self.emi_threshold:
            comm_failure_prob = 0.0
        else:
            # EMI above threshold causes communication issues
            comm_failure_prob = (effective_emi - self.emi_threshold) * \
                               self.emi_base_failure_rate

        # Slight altitude modifier (misleading!)
        altitude_mod = self.altitude_signal_modifier.get(altitude_band, 0)
        comm_failure_prob = min(0.95, max(0.0, comm_failure_prob + altitude_mod))

        # === Component damage ===
        component_damage = {}

        # Wind damage (varies with altitude - visible effect, MINOR)
        wind_damage_rate = self.altitude_wind_damage.get(altitude_band, 0.1)
        if wind_damage_rate > 0:
            # Wind affects engine and wing - but only slightly
            if altitude_band == 'high':
                component_damage['engine'] = int(random.uniform(5, 15))
                component_damage['wing'] = int(random.uniform(8, 20))
            elif altitude_band == 'medium':
                component_damage['wing'] = int(random.uniform(3, 10))

        # === EMI DAMAGE - THE TRUE CAUSE OF LOSSES ===
        # Communication failure leads to control loss, which damages CRITICAL components
        # This is the key mechanism: EMI -> comm failure -> crash (critical damage)

        if effective_emi > self.emi_threshold:
            # Direct EMI damage to antenna
            emi_damage = int((effective_emi - self.emi_threshold) * 80)
            component_damage['antenna'] = emi_damage

            # EMI damages camera electronics
            if effective_emi > 0.4:
                component_damage['camera'] = int(emi_damage * 0.6)

        # Communication failure causes CATASTROPHIC damage (the main death mechanism!)
        # When comm fails, drone loses control and crashes into terrain/obstacles
        if comm_failure_prob > 0:
            # Roll for comm failure event
            if random.random() < comm_failure_prob:
                # Communication failure! Drone loses control!
                # This causes MASSIVE damage to critical components
                crash_severity = random.uniform(0.6, 1.0) * comm_failure_prob

                # Damage to critical components from loss of control
                component_damage['engine'] = component_damage.get('engine', 0) + int(60 * crash_severity)
                component_damage['wing'] = component_damage.get('wing', 0) + int(50 * crash_severity)
                component_damage['body'] = component_damage.get('body', 0) + int(40 * crash_severity)
                component_damage['cockpit'] = component_damage.get('cockpit', 0) + int(35 * crash_severity)

        # === Detection and combat ===
        # Higher comm failure = out of control = higher detection
        base_detection = 0.20
        detection_modifier = base_detection + comm_failure_prob * 0.5

        # Combat rounds affected by communication status
        if comm_failure_prob > 0.5:
            # Lost communication = can't coordinate = longer engagement
            combat_rounds_mod = 1.8
        else:
            combat_rounds_mod = 1.0

        # Combat damage modifier - EMI affects defensive systems
        if effective_emi > 0.5:
            combat_damage_mod = 1.0 + (effective_emi - 0.5) * 0.5
        else:
            combat_damage_mod = 1.0

        return EnvironmentEffects(
            component_damage=component_damage,
            detection_modifier=detection_modifier,
            combat_rounds_modifier=combat_rounds_mod,
            combat_damage_modifier=combat_damage_mod,
            combat_accuracy_modifier=1.0,
            weather_pattern=emi_level,  # Repurposed for logging
            raw_environment={
                **env.visible,
                'effective_emi': effective_emi,
                'comm_failure_prob': comm_failure_prob,
            },
            damage_log=[
                f"Mission zone: {mission_zone} ({env.derived.get('zone_description', '')})",
                f"Altitude band: {altitude_band}",
                f"EMI level: {emi_level:.2f} (hidden!)",
                f"Shield DEF: {shield_def}",
                f"Shield reduction: {shield_reduction:.2%}",
                f"Equipment EMI resistance: {equipment_emi_resistance:.2%}",
                f"Total EMI reduction: {total_emi_reduction:.2%}",
                f"Effective EMI: {effective_emi:.2f}",
                f"Comm failure prob: {comm_failure_prob:.2%}",
                f"Wind damage rate: {wind_damage_rate:.2%}",
                f"Detection modifier: {detection_modifier:.2f}",
                f"Combat damage modifier: {combat_damage_mod:.2f}",
                f"-- THE TRAP --",
                f"Agent sees: altitude_band = {altitude_band}",
                f"Agent may think: altitude causes losses",
                f"True cause: EMI level = {emi_level:.2f}",
                f"Solution: shield_def protects against EMI",
            ]
        )
