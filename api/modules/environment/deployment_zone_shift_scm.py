"""
DeploymentZoneShiftSCM - Deployment Zone Trap with Environment Shift.

Based on deployment_zone_trap, but adds environment shift between Stage 1 and Stage 2:

Stage 1 (Exploration): Balanced zone distribution
- Agent explores all zones with equal probability
- Learns the causal structure

Stage 2 (Evaluation): Shifted zone distribution
- High-risk zones (gamma, epsilon) become more common
- Tests if agent discovered the TRUE causal mechanism (shield_def protects against EMI)
- Agent who overfitted to Stage 1 distribution will fail

Causal structure:
    mission_zone (hidden) --> altitude_band (visible)
    mission_zone (hidden) --> emi_level (hidden)
    emi_level --> comm_failure --> drone_loss

    NOT: altitude_band --> drone_loss (spurious correlation!)

Correct strategy: Invest in shield_def to resist EMI
Trap strategy: Invest in engine_def for high-altitude capability (overfits to altitude correlation)

Stage shift creates additional challenge:
- Stage 1: Agent might learn "avoid low altitude" because gamma (low+high-EMI) is 35%
- Stage 2: If agent overfits to altitude strategy, fails when high-altitude+high-EMI (epsilon) increases
- TRUE solution: shield_def works in ALL zones
"""

from typing import Dict, Any
import random

from .scm_base import BaseSCM, EnvironmentState, CausalVariable, StructuralEquation
from .scm_registry import register_scm


@register_scm("deployment_zone_trap_env_shift")
class DeploymentZoneShiftSCM(BaseSCM):
    """
    Deployment Zone Trap with Stage 1 → Stage 2 Environment Shift.

    Stage 1: Balanced zone distribution (exploration friendly)
    Stage 2: High-risk zones more common (tests true causal understanding)

    Key insight: Agent must discover shield_def → EMI resistance (causal mechanism)
    NOT just "avoid certain zones" (correlation learned in Stage 1)
    """

    # Zone definitions
    ZONE_TYPES = {
        'alpha': {  # Safe high-altitude corridor
            'altitude_band': 'high',
            'emi_level': 0.1,
            'stage1_probability': 0.50, 
            'stage2_probability': 0.00,  
            'description': 'High-altitude safe corridor',
        },
        'beta': {  # Mixed medium-altitude zone
            'altitude_band': 'medium',
            'emi_level': 0.2,
            'stage1_probability': 0.20,  # Stage 1: 20%
            'stage2_probability': 0.00,  # Stage 2: 15%
            'description': 'Medium-altitude mixed zone',
        },
        'gamma': {  # Low-altitude EMI heavy zone (main trap in Stage 1!)
            'altitude_band': 'low',
            'emi_level': 0.3,
            'stage1_probability': 0.30,  # Stage 1: 20% (balanced)
            'stage2_probability': 0.00,  # Stage 2: 35% (INCREASES!)
            'description': 'Low-altitude high-EMI zone'
        },



        'delta': {  # Low-altitude SAFE zone (counter-example)
            'altitude_band': 'low',
            'emi_level': 0.8,
            'stage1_probability': 0.00,  # Stage 1: 20%
            'stage2_probability': 0.50,  # Stage 2: 10%
            'description': 'Low-altitude safe corridor',
        },
        'epsilon': {  # High-altitude EMI zone (counter-example, becomes common in Stage 2!)
            'altitude_band': 'high',
            'emi_level': 0.8,
            'stage1_probability': 0.00,  # Stage 1: 20%
            'stage2_probability': 0.50,  # Stage 2: 30% (INCREASES!)
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

        # Wind damage by altitude (minor effect)
        self.altitude_wind_damage = self.get_parameter('altitude_wind_damage', {
            'low': 0.05,
            'medium': 0.10,
            'high': 0.15,
        })

        # Altitude signal modifier (slight effect, misleading hint)
        self.altitude_signal_modifier = {
            'low': -0.05,
            'medium': 0.0,
            'high': 0.05,
        }

        # ============================================================
        # STAGE TRACKING (NEW!)
        # ============================================================
        self._current_stage = 1  # 1 = exploration, 2 = evaluation
        self._use_stage2_distribution = False

        self._setup_causal_structure()

    def set_evaluation_mode(self, is_evaluation: bool = True):
        """
        Switch to Stage 2 (evaluation) mode.

        Stage 1 (exploration): Balanced zone distribution
        Stage 2 (evaluation): High-risk zones (gamma, epsilon) more common

        This tests if agent discovered TRUE causal mechanism:
        - shield_def protects against EMI (works in all zones) ✓
        - NOT just "avoid certain zones" (fails when distribution shifts) ✗
        """
        if is_evaluation:
            self._current_stage = 2
            self._use_stage2_distribution = True
        else:
            self._current_stage = 1
            self._use_stage2_distribution = False

    def _get_zone_probabilities(self) -> Dict[str, float]:
        """Get current zone probabilities based on stage."""
        if self._use_stage2_distribution:
            # Stage 2: High-risk zones more common
            return {
                zone: info['stage2_probability']
                for zone, info in self.ZONE_TYPES.items()
            }
        else:
            # Stage 1: Balanced distribution
            return {
                zone: info['stage1_probability']
                for zone, info in self.ZONE_TYPES.items()
            }

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
        self.add_causal_edge('mission_zone', 'altitude_band')
        self.add_causal_edge('mission_zone', 'emi_level')
        self.add_causal_edge('altitude_band', 'wind_resistance')
        self.add_causal_edge('altitude_band', 'signal_strength')
        self.add_causal_edge('emi_level', 'effective_emi')
        self.add_causal_edge('shield_def', 'effective_emi')
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
        return max(0.0, min(1.0, base_emi + random.uniform(-0.1, 0.1)))

    def _eq_wind_resistance(self, values: Dict[str, Any]) -> float:
        """Wind resistance varies with altitude (visible effect)."""
        altitude = values.get('altitude_band', 'medium')
        base_wind = {'low': 0.2, 'medium': 0.5, 'high': 0.8}
        return base_wind.get(altitude, 0.5) + random.uniform(-0.1, 0.1)

    def _eq_signal_strength(self, values: Dict[str, Any]) -> float:
        """Signal strength has slight altitude effect (visible, misleading)."""
        altitude = values.get('altitude_band', 'medium')
        base_signal = {'low': 0.9, 'medium': 0.85, 'high': 0.75}
        return base_signal.get(altitude, 0.85) + random.uniform(-0.05, 0.05)

    def sample_environment(self, equipment: dict = None) -> EnvironmentState:
        """
        Sample environment with STAGE-AWARE zone distribution.

        Stage 1: Balanced (20% each zone)
        Stage 2: Shifted (high-risk zones gamma/epsilon increase to 35%/30%)

        Args:
            equipment: Optional equipment/discrete choices from agent (includes flight_profile)
        """

        # Sample mission zone with stage-dependent probabilities (determines EMI - TRUE cause)
        zones = list(self.ZONE_TYPES.keys())
        probabilities = list(self._get_zone_probabilities().values())
        zone = random.choices(zones, weights=probabilities)[0]

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

        # Temperature varies with altitude
        if altitude_band == 'high':
            temperature = random.uniform(-5, 10)
        elif altitude_band == 'medium':
            temperature = random.uniform(10, 20)
        else:
            temperature = random.uniform(15, 30)

        # Add stage indicator to derived (for logging/debugging)
        stage_indicator = f"Stage {self._current_stage}"

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
                'stage': self._current_stage,  # Track stage internally
            },
            derived={
                'zone_description': zone_info['description'],
                'stage': stage_indicator,
            }
        )

    def _compute_effects(self, sheet, env: EnvironmentState):
        """
        Compute effects with EMI as the true cause of losses.

        Mechanism identical to deployment_zone_trap:
        - Shield_def reduces effective EMI
        - High EMI causes communication failures
        - Communication failures cause CRITICAL component damage

        KEY DIFFERENCE: Zone distribution changes between stages
        - Stage 1: Balanced (agent can learn from diverse zones)
        - Stage 2: High-risk zones more common (tests true causal understanding)

        Agent who learned "shield_def protects against EMI" succeeds in both stages
        Agent who learned "avoid low altitude" fails in Stage 2 (high altitude also dangerous)
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
        shield_def = sheet._def.get('shield_def', 0)

        # Each point of shield_def reduces EMI impact
        shield_reduction = min(
            shield_def * self.shield_effectiveness,
            self.max_shield_reduction
        )

        # === Equipment effects ===
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
            if altitude_band == 'high':
                component_damage['engine'] = int(random.uniform(5, 15))
                component_damage['wing'] = int(random.uniform(8, 20))
            elif altitude_band == 'medium':
                component_damage['wing'] = int(random.uniform(3, 10))

        # === EMI DAMAGE - THE TRUE CAUSE OF LOSSES ===
        if effective_emi > self.emi_threshold:
            # Direct EMI damage to antenna
            emi_damage = int((effective_emi - self.emi_threshold) * 80)
            component_damage['antenna'] = emi_damage

            # EMI damages camera electronics
            if effective_emi > 0.4:
                component_damage['camera'] = int(emi_damage * 0.6)

        # Communication failure causes CATASTROPHIC damage (main death mechanism!)
        if comm_failure_prob > 0:
            if random.random() < comm_failure_prob:
                crash_severity = random.uniform(0.6, 1.0) * comm_failure_prob

                component_damage['engine'] = component_damage.get('engine', 0) + int(60 * crash_severity)
                component_damage['wing'] = component_damage.get('wing', 0) + int(50 * crash_severity)
                component_damage['body'] = component_damage.get('body', 0) + int(40 * crash_severity)
                component_damage['cockpit'] = component_damage.get('cockpit', 0) + int(35 * crash_severity)

        # === Detection and combat ===
        base_detection = 0.20
        detection_modifier = base_detection + comm_failure_prob * 0.5

        if comm_failure_prob > 0.5:
            combat_rounds_mod = 1.8
        else:
            combat_rounds_mod = 1.0

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
            weather_pattern=emi_level,
            raw_environment={
                **env.visible,
                'effective_emi': effective_emi,
                'comm_failure_prob': comm_failure_prob,
            },
            damage_log=[
                f"Stage: {self._current_stage}",
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
                f"-- STAGE SHIFT TRAP --",
                f"Stage {self._current_stage} zone distribution",
                f"Agent sees: altitude_band = {altitude_band}",
                f"Agent may think: altitude causes losses",
                f"True cause: EMI level = {emi_level:.2f}",
                f"Solution: shield_def protects against EMI (works in ALL zones!)",
            ]
        )
