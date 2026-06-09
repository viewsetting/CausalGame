"""
Agent Action Space - Defines what actions agent can perform.

This module provides:
- Action definitions (deploy, query, submit)
- Action validation
- Action execution through DroneSheet middleware

Key principle: Agent modifies ONLY visible values.
Results are filtered to hide internal state.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple
from enum import Enum
import random
import logging

logger = logging.getLogger(__name__)

from ...middleware.drone_sheet import DroneSheet
from ...middleware.drone_state import DroneState, JudgmentResult, EnvironmentEffects
from ..environment.scm_base import CausalSCM
from ..game.judge import judge_survival
from ..game.combat import full_simulation


class ActionType(Enum):
    """Types of actions agent can perform."""
    DEPLOY = "deploy"
    SUBMIT_FINAL = "submit_final"
    QUERY_ENVIRONMENT = "query_environment"
    GET_STATUS = "get_status"
    GET_HISTORY = "get_history"


@dataclass
class AgentAction:
    """Base class for agent actions."""
    action_type: ActionType


@dataclass
class DeployAction(AgentAction):
    """Deploy drones with a design and optional equipment."""
    action_type: ActionType = ActionType.DEPLOY
    design: Dict[str, int] = field(default_factory=dict)
    equipment: Dict[str, str] = field(default_factory=dict)  # slot -> choice_id
    count: int = 1


@dataclass
class SubmitAction(AgentAction):
    """Submit final design for Stage 2 evaluation."""
    action_type: ActionType = ActionType.SUBMIT_FINAL
    design: Dict[str, int] = field(default_factory=dict)
    equipment: Dict[str, str] = field(default_factory=dict)  # slot -> choice_id


@dataclass
class QueryAction(AgentAction):
    """Query environment data."""
    action_type: ActionType = ActionType.QUERY_ENVIRONMENT
    query: str = ""


@dataclass
class DeployResult:
    """Result of a deployment action."""
    success: bool
    error: Optional[str] = None

    # Batch statistics
    deployed: int = 0
    survived: int = 0
    destroyed: int = 0

    # Per-drone results (filtered for agent, excludes failed if hide_failed_drones)
    results: List[Dict[str, Any]] = field(default_factory=list)

    # Full results for admin/session storage (includes all drones)
    full_results: List[Dict[str, Any]] = field(default_factory=list)

    # Environment data (visible only)
    environment: Dict[str, float] = field(default_factory=dict)

    # Average statistics
    average_hit_count: float = 0.0


@dataclass
class SubmitResult:
    """Result of final submission."""
    success: bool
    error: Optional[str] = None

    # Fleet statistics
    fleet_size: int = 0
    survived: int = 0
    survival_rate: float = 0.0

    # Scoring
    final_score: float = 0.0
    victory: bool = False
    victory_threshold: float = 0.55


class AgentActionSpace:
    """
    Defines and executes agent actions.

    This class:
    1. Validates agent actions
    2. Executes actions through middleware
    3. Filters results for agent visibility

    Usage:
        action_space = AgentActionSpace(scm, config)
        result = action_space.execute(DeployAction(design={...}, count=5))
    """

    def __init__(
        self,
        scm: CausalSCM,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize AgentActionSpace.

        Args:
            scm: SCM for environment effects
            config: Experiment configuration
        """
        self.scm = scm
        self.config = config or {}

        # Resource limits
        self.total_drone_budget = self.config.get('resources', {}).get('total_drone_budget', 200)
        self.stage2_fleet_size = self.config.get('resources', {}).get('stage2_fleet_size', 1000)
        self.victory_threshold = self.config.get('resources', {}).get('victory_threshold', 0.55)
        self.stage1_deployment_budget = self.config.get('resources', {}).get('stage1_deployment_budget', None)

        # Agent visibility settings
        agent_visibility = self.config.get('agent_visibility', {})
        self.hide_failed_drones = agent_visibility.get('hide_failed_drones', False)

        # Tracking
        self._drones_used = 0
        self._deployments_used = 0  # Track number of deploy calls
        self._history: List[Dict[str, Any]] = []
        self._session_drone_counter = 0  # Counter for SESSION IDs

    def execute(self, action: AgentAction) -> Any:
        """
        Execute an agent action.

        Args:
            action: AgentAction to execute

        Returns:
            Action result (type depends on action)
        """
        if action.action_type == ActionType.DEPLOY:
            return self._execute_deploy(action)
        elif action.action_type == ActionType.SUBMIT_FINAL:
            return self._execute_submit(action)
        elif action.action_type == ActionType.GET_STATUS:
            return self._get_status()
        elif action.action_type == ActionType.GET_HISTORY:
            return self._get_history()
        else:
            raise ValueError(f"Unknown action type: {action.action_type}")

    def _execute_deploy(self, action: DeployAction, is_test: bool = False) -> DeployResult:
        """
        Execute drone deployment.

        Args:
            action: DeployAction with design, equipment, and count
            is_test: If True, skip budget checks (for admin test deploys)

        Returns:
            DeployResult with filtered data
        """
        # Skip budget checks for test deployments
        if not is_test:
            # Validate deployment call budget (if configured)
            if self.stage1_deployment_budget is not None:
                if self._deployments_used >= self.stage1_deployment_budget:
                    return DeployResult(
                        success=False,
                        error=f"Deployment budget exhausted. Used {self._deployments_used}/{self.stage1_deployment_budget} calls.",
                    )

            # Validate drone budget
            if self._drones_used + action.count > self.total_drone_budget:
                remaining = self.total_drone_budget - self._drones_used
                return DeployResult(
                    success=False,
                    error=f"Insufficient budget. Remaining: {remaining}",
                )

        # Load action space config for equipment validation/effects
        action_space_config = None
        if action.equipment:
            try:
                from ..action_space import get_action_space
                experiment_name = self.config.get('experiment', {}).get('name', 'antenna_trap')
                action_space_config = get_action_space(experiment_name)
            except Exception as e:
                # Gracefully handle missing action space config
                logger.warning(f"Failed to load action space config: {e}")
                pass

        results = []
        survived = 0
        destroyed = 0
        total_hit_count = 0
        last_env = {}

        for i in range(action.count):
            # Create fresh DroneSheet for each drone
            sheet = DroneSheet(self.config)

            # Agent sets DEF design
            success, error = sheet.set_def_design(action.design)
            if not success:
                return DeployResult(success=False, error=error)

            # Apply equipment if provided
            if action.equipment:
                sheet.set_equipment(action.equipment)

                # Compute and apply equipment effects if config available
                if action_space_config:
                    full_design = {**action.design, 'equipment': action.equipment}
                    equipment_effects = action_space_config.compute_effects(full_design)
                    sheet.apply_equipment_effects(equipment_effects)

            # SCM samples environment and applies effects
            # Pass equipment to allow SCM to use agent's choices (e.g., flight_profile)
            env = self.scm.sample_environment(equipment=action.equipment)
            self.scm.apply_effects(sheet, env)

            # Check if SCM made a survival decision via component_damage
            # (WeatherDefenseSCM uses this to enforce deterministic survival)
            state_after_scm = sheet.to_drone_state()
            scm_decided_outcome = (
                state_after_scm.hp.get('engine', 100) <= 0 or
                state_after_scm.hp.get('cockpit', 100) <= 0
            )

            if scm_decided_outcome:
                # SCM decided outcome - skip combat, use SCM's decision directly
                judgment = judge_survival(state_after_scm)
                was_detected = False  # No combat if SCM decided
                combat_result = None
            else:
                # Normal combat flow
                was_detected, combat_result = full_simulation(state_after_scm)

                # Apply combat damage if detected
                if was_detected and combat_result:
                    sheet.apply_combat_damage(
                        combat_result.damage_by_component,
                        combat_result.hit_count,
                        combat_result.combat_log
                    )
                    total_hit_count += combat_result.hit_count

                # Update state after combat
                state = sheet.to_drone_state()

                # Judge survival
                judgment = judge_survival(state)
            judgment = JudgmentResult(
                status=judgment.status,
                fail_reason=judgment.fail_reason,
                final_hp=judgment.final_hp,
                was_detected=was_detected,
                hit_count=combat_result.hit_count if combat_result else 0,
            )

            if judgment.survived:
                survived += 1
            else:
                destroyed += 1

            # Filter result for agent (hide HP, agility)
            filtered_result = sheet.filter_result_for_agent(judgment)

            # Apply observation noise if SCM supports it
            if hasattr(self.scm, 'get_noise_std'):
                noise_std = self.scm.get_noise_std(env)
                filtered_result = sheet.add_observation_noise(filtered_result, noise_std)

            results.append(filtered_result)

            # Store environment for return
            last_env = env.visible.copy()

            # Record in history with SESSION prefix ID
            self._session_drone_counter += 1
            history_record = {
                'id': f'SESSION-{self._session_drone_counter:03d}',
                'design': action.design.copy(),
                'status': judgment.status,
                'hit_count': judgment.hit_count,
                'environment': env.visible.copy(),
            }
            if action.equipment:
                history_record['equipment'] = action.equipment.copy()
            self._history.append(history_record)

        # Update budget (skip for test deployments)
        if not is_test:
            self._drones_used += action.count
            self._deployments_used += 1  # Track deployment calls

        # Filter results for agent if hide_failed_drones is enabled
        if self.hide_failed_drones:
            visible_results = [r for r in results if r.get('status') == 'RETURNED']
        else:
            visible_results = results

        return DeployResult(
            success=True,
            deployed=action.count,
            survived=survived,
            destroyed=destroyed,
            results=visible_results,
            full_results=results,  # Unfiltered results for admin/session storage
            environment=last_env,
            average_hit_count=total_hit_count / action.count if action.count > 0 else 0,
        )

    def _execute_submit(self, action: SubmitAction) -> SubmitResult:
        """
        Execute final submission (Stage 2).

        Args:
            action: SubmitAction with final design and optional equipment

        Returns:
            SubmitResult with victory status
        """
        # Switch SCM to evaluation mode (Stage 2) if supported
        # This allows experiments to change weather distribution between stages
        if hasattr(self.scm, 'set_evaluation_mode'):
            self.scm.set_evaluation_mode(True)

        survived = 0

        # Load action space config for equipment validation/effects
        action_space_config = None
        if action.equipment:
            try:
                from ..action_space import get_action_space
                experiment_name = self.config.get('experiment', {}).get('name', 'antenna_trap')
                action_space_config = get_action_space(experiment_name)
            except Exception:
                pass

        for i in range(self.stage2_fleet_size):
            # Create drone and simulate
            sheet = DroneSheet(self.config)
            success, error = sheet.set_def_design(action.design)
            if not success:
                return SubmitResult(success=False, error=error)

            # Apply equipment if provided
            if action.equipment:
                sheet.set_equipment(action.equipment)
                if action_space_config:
                    full_design = {**action.design, 'equipment': action.equipment}
                    equipment_effects = action_space_config.compute_effects(full_design)
                    sheet.apply_equipment_effects(equipment_effects)

            # Pass equipment to allow SCM to use agent's choices (e.g., flight_profile)
            env = self.scm.sample_environment(equipment=action.equipment)
            self.scm.apply_effects(sheet, env)

            # Check if SCM made a survival decision via component_damage
            state_after_scm = sheet.to_drone_state()
            scm_decided_outcome = (
                state_after_scm.hp.get('engine', 100) <= 0 or
                state_after_scm.hp.get('cockpit', 100) <= 0
            )

            if scm_decided_outcome:
                # SCM decided outcome - skip combat, use SCM's decision directly
                judgment = judge_survival(state_after_scm)
            else:
                # Normal combat flow
                was_detected, combat_result = full_simulation(state_after_scm)

                if was_detected and combat_result:
                    sheet.apply_combat_damage(
                        combat_result.damage_by_component,
                        combat_result.hit_count,
                    )

                state = sheet.to_drone_state()
                judgment = judge_survival(state)

            if judgment.survived:
                survived += 1

        survival_rate = survived / self.stage2_fleet_size
        total_def = sum(action.design.values())
        def_efficiency = 1.0 - min(1.0, total_def / 300)

        # Final score calculation (for internal analysis, not shown to agent)
        final_score = survival_rate * 0.7 + def_efficiency * 0.3

        return SubmitResult(
            success=True,
            fleet_size=self.stage2_fleet_size,
            survived=survived,
            survival_rate=survival_rate,
            final_score=final_score,
            victory=survival_rate >= self.victory_threshold,  # Victory based on survival rate
            victory_threshold=self.victory_threshold,
        )

    def _get_status(self) -> Dict[str, Any]:
        """Get current status (filtered for agent)."""
        status = {
            'drones_remaining': self.total_drone_budget - self._drones_used,
            'drones_used': self._drones_used,
            'total_drones': self.total_drone_budget,
            'history_count': len(self._history),
            'victory_threshold': self.victory_threshold,
            'stage2_fleet_size': self.stage2_fleet_size,
        }
        # Include deployment budget info if configured
        if self.stage1_deployment_budget is not None:
            status['deployments_used'] = self._deployments_used
            status['deployments_remaining'] = self.stage1_deployment_budget - self._deployments_used
            status['stage1_deployment_budget'] = self.stage1_deployment_budget
        return status

    def _get_history(self, include_failed: bool = False) -> List[Dict[str, Any]]:
        """
        Get flight history (filtered for agent).

        Args:
            include_failed: If True, include all drones regardless of hide_failed_drones setting.
                           Used by admin endpoints to get full history.

        Returns:
            List of flight records, optionally filtered to only RETURNED drones.
        """
        if self.hide_failed_drones and not include_failed:
            # Filter to only show RETURNED drones
            return [r for r in self._history if r.get('status') == 'RETURNED']
        return self._history.copy()

    def _get_full_history(self) -> List[Dict[str, Any]]:
        """Get complete flight history (for admin, ignores hide_failed_drones)."""
        return self._history.copy()

    def reset(self) -> None:
        """Reset action space state."""
        self._drones_used = 0
        self._deployments_used = 0
        self._history.clear()
        self._session_drone_counter = 0

    def set_evaluation_mode(self, is_evaluation: bool = True) -> None:
        """
        Set evaluation mode for the SCM (used for testing).

        This allows switching between Stage 1 (exploration) and Stage 2 (evaluation)
        weather distributions without consuming submit budget.

        Args:
            is_evaluation: If True, switch to Stage 2 (30% storm for weather_defense)
                          If False, use Stage 1 (70% storm for weather_defense)
        """
        if hasattr(self.scm, 'set_evaluation_mode'):
            self.scm.set_evaluation_mode(is_evaluation)

    @property
    def drones_remaining(self) -> int:
        """Get remaining drone budget."""
        return self.total_drone_budget - self._drones_used

    def generate_initial_observations(self, count: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Generate initial observations for agent to analyze.

        These observations:
        - Use the standard design (or biased design if configured)
        - Have INIT prefix IDs
        - Do NOT consume drone budget
        - Are visible in the history

        Args:
            count: Number of initial observations (default from config)

        Returns:
            List of observation records

        Config options for history bias (in game.json resources):
        - initial_observation_bias: "none" | "trap" | "optimal"
          - "none": use standard design (default)
          - "trap": use high antenna_def design (misleads agent to protect antenna)
          - "optimal": use antenna_def=0 design (shows correct pattern)
        - initial_observation_design: custom design dict (overrides bias)
        """
        if count is None:
            count = self.config.get('resources', {}).get('initial_observations', 50)

        # Get standard design from config (filter to only _def fields)
        raw_design = self.config.get('drone', {}).get('standard_design', {
            'engine_def': 20,
            'cockpit_def': 20,
            'wing_def': 15,
            'body_def': 15,
            'antenna_def': 10,
            'camera_def': 5,
            'gun_def': 5,
        })
        # Filter to only include _def fields (exclude _atk, etc.)
        standard_design = {k: v for k, v in raw_design.items() if k.endswith('_def')}

        # Check for custom initial observation design or bias
        resources = self.config.get('resources', {})
        custom_design = resources.get('initial_observation_design')
        bias_type = resources.get('initial_observation_bias', 'none')

        # Bias configuration
        use_random_design = False
        force_clear_weather = False
        use_simpsons_paradox = False
        use_anti_correlation = False

        if custom_design:
            # Use explicit custom design
            observation_design = {k: v for k, v in custom_design.items() if k.endswith('_def')}
        elif bias_type == 'trap':
            # Misleading history: high antenna_def (makes agent think protecting antenna is good)
            observation_design = standard_design.copy()
            observation_design['antenna_def'] = 30
            observation_design['camera_def'] = 30
            observation_design['gun_def'] = 30
        elif bias_type == 'optimal':
            # Helpful history: antenna_def=0 (shows the correct pattern)
            observation_design = standard_design.copy()
            observation_design['antenna_def'] = 0
        elif bias_type == 'random_designs':
            # Each observation uses a random design (diverse exploration data)
            use_random_design = True
            observation_design = standard_design
        elif bias_type == 'clear_weather_only':
            # Only show clear weather observations (hides antenna-storm interaction)
            observation_design = standard_design.copy()
            force_clear_weather = True
        elif bias_type == 'high_total_def':
            # All components have high DEF (misleads into weight penalty trap)
            observation_design = {
                'engine_def': 35, 'cockpit_def': 35,
                'wing_def': 30, 'body_def': 30,
                'antenna_def': 25, 'camera_def': 20, 'gun_def': 20
            }
        elif bias_type == 'critical_focus':
            # High critical components, zero non-critical (partial trap discovery)
            observation_design = {
                'engine_def': 40, 'cockpit_def': 40,
                'wing_def': 30, 'body_def': 30,
                'antenna_def': 0, 'camera_def': 0, 'gun_def': 0
            }
        elif bias_type == 'local_optima':
            # Better than default but not optimal (antenna_def=5 instead of 0)
            observation_design = standard_design.copy()
            observation_design['antenna_def'] = 5
            observation_design['camera_def'] = 10
            observation_design['gun_def'] = 10
        elif bias_type == 'simpsons_paradox':
            # Mixed data creating misleading aggregate statistics
            use_simpsons_paradox = True
            observation_design = standard_design
        elif bias_type == 'anti_correlation':
            # Show lucky survivors with high antenna_def (opposite of optimal)
            use_anti_correlation = True
            observation_design = standard_design.copy()
            observation_design['antenna_def'] = 25
        # ============ Deployment Zone Trap Categorical Biases ============
        elif bias_type == 'deployment_zone_high_def':
            # High DEF design with wrong module - misleads agent to think defense is useless
            observation_design = {
                'engine_def': 30, 'cockpit_def': 30,
                'wing_def': 25, 'body_def': 25,
                'antenna_def': 20, 'camera_def': 15, 'gun_def': 15,
                'shield_def': 0  # Key: no shield!
            }
        elif bias_type == 'deployment_zone_local_optima':
            # TRUE local optimum trap: signal_filter works but DEF allocation misdirects
            # Agent sees ~70% survival and thinks "high engine/wing for altitude is key"
            # But actually shield_def is the key - this design has very low shield
            observation_design = {
                'engine_def': 35, 'cockpit_def': 30,  # HIGH - misdirects toward "altitude"
                'wing_def': 30, 'body_def': 25,       # HIGH - misdirects toward "turbulence"
                'antenna_def': 15, 'camera_def': 10, 'gun_def': 10,
                'shield_def': 5  # LOW - agent thinks shield is not important
            }
        elif bias_type == 'deployment_zone_simpsons_paradox':
            # Will be handled in the loop - creates altitude paradox
            use_simpsons_paradox = True
            observation_design = standard_design
        elif bias_type == 'deployment_zone_high_emi_only':
            # Only show high EMI zone data - hides the fact that low EMI zones are safe
            # Agent sees high loss rate and may not discover shield_def + signal_filter solution
            observation_design = standard_design.copy()
            observation_design['shield_def'] = 0
        else:
            # Default: use standard design
            observation_design = standard_design

        # Equipment configuration for deployment_zone_trap_categorical biases
        bias_equipment = None
        use_deployment_zone_simpsons = False
        use_deployment_zone_high_emi = False
        if bias_type == 'deployment_zone_high_def':
            bias_equipment = {'enhancement_module': 'radar_boost'}  # Wrong module
        elif bias_type == 'deployment_zone_local_optima':
            bias_equipment = {'enhancement_module': 'signal_filter'}  # Correct module but insufficient shield
        elif bias_type == 'deployment_zone_simpsons_paradox':
            use_deployment_zone_simpsons = True
            use_simpsons_paradox = False  # Override the antenna_trap simpsons paradox flag
        elif bias_type == 'deployment_zone_high_emi_only':
            use_deployment_zone_high_emi = True
            bias_equipment = {'enhancement_module': 'radar_boost'}  # Wrong module in dangerous zone

        observations = []

        for i in range(count):
            # Create fresh DroneSheet
            sheet = DroneSheet(self.config)

            # Determine current equipment for this observation
            current_equipment = bias_equipment.copy() if bias_equipment else None

            # Determine design for this observation
            if use_random_design:
                # Generate random design for each observation
                current_design = {
                    'engine_def': random.randint(10, 40),
                    'cockpit_def': random.randint(10, 40),
                    'wing_def': random.randint(5, 35),
                    'body_def': random.randint(5, 35),
                    'antenna_def': random.randint(0, 30),
                    'camera_def': random.randint(0, 25),
                    'gun_def': random.randint(0, 25),
                }
            elif use_deployment_zone_simpsons:
                # Deployment Zone Simpson's Paradox: alternate between high/low altitude zones
                # to create paradox where altitude appears irrelevant
                if i % 3 == 0:
                    # High altitude + High EMI (Epsilon zone) - high altitude but dangerous
                    current_design = standard_design.copy()
                    current_design['engine_def'] = 25
                    current_design['shield_def'] = 0
                    current_equipment = {'enhancement_module': 'radar_boost'}
                else:
                    # Low altitude + Low EMI (Delta zone) - low altitude but safe
                    current_design = standard_design.copy()
                    current_design['engine_def'] = 15
                    current_design['shield_def'] = 0
                    current_equipment = {'enhancement_module': 'thermal_shield'}
            elif use_simpsons_paradox:
                # Antenna Trap Simpson's Paradox: alternate between two designs
                if i % 3 == 0:
                    # Storm weather + high antenna (few survivors, but they have high antenna)
                    current_design = standard_design.copy()
                    current_design['antenna_def'] = 25
                else:
                    # Clear weather + high antenna (many survivors)
                    current_design = standard_design.copy()
                    current_design['antenna_def'] = 20
            elif use_anti_correlation:
                # Vary antenna_def but only keep lucky high-antenna survivors
                current_design = observation_design.copy()
                current_design['antenna_def'] = random.randint(15, 35)
            else:
                current_design = observation_design.copy()

            # Use observation design (may be standard, biased, or custom)
            success, error = sheet.set_def_design(current_design)
            if not success:
                continue

            # Apply equipment if provided (for deployment_zone_trap biases)
            if current_equipment:
                sheet.set_equipment(current_equipment)
                # Compute and apply equipment effects
                try:
                    from ..action_space import get_action_space
                    experiment_name = self.config.get('experiment', {}).get('name', 'antenna_trap')
                    action_space_config = get_action_space(experiment_name)
                    if action_space_config:
                        full_design = {**current_design, 'equipment': current_equipment}
                        equipment_effects = action_space_config.compute_effects(full_design)
                        sheet.apply_equipment_effects(equipment_effects)
                except Exception as e:
                    logger.warning(f"Failed to apply equipment effects for observation: {e}")

            # SCM samples environment and applies effects
            # Pass equipment to allow SCM to use agent's choices (e.g., flight_profile)
            if force_clear_weather:
                # Force clear weather by overriding the environment
                env = self.scm.sample_environment(equipment=current_equipment)
                # Modify to ensure clear weather (low storm probability condition)
                if hasattr(env, 'hidden') and 'weather_pattern' in env.hidden:
                    env.hidden['weather_pattern'] = random.uniform(0.0, 0.15)  # Force clear
                    # Re-apply effects with modified environment
                    sheet = DroneSheet(self.config)
                    sheet.set_def_design(current_design)
            elif use_deployment_zone_simpsons:
                # Force specific zones to create the altitude paradox
                env = self.scm.sample_environment(equipment=current_equipment)
                if hasattr(env, 'latent') and 'mission_zone' in env.latent:
                    if i % 3 == 0:
                        # Force epsilon zone: high altitude + high EMI
                        env.latent['mission_zone'] = 'epsilon'
                        env.latent['emi_level'] = 0.8 + random.uniform(-0.1, 0.1)
                        env.visible['altitude_band'] = 'high'
                    else:
                        # Force delta zone: low altitude + low EMI
                        env.latent['mission_zone'] = 'delta'
                        env.latent['emi_level'] = 0.1 + random.uniform(-0.05, 0.05)
                        env.visible['altitude_band'] = 'low'
                    # Recreate sheet to ensure clean state
                    sheet = DroneSheet(self.config)
                    sheet.set_def_design(current_design)
                    # Re-apply equipment if any
                    if current_equipment:
                        sheet.set_equipment(current_equipment)
                        try:
                            from ..action_space import get_action_space
                            experiment_name = self.config.get('experiment', {}).get('name', 'antenna_trap')
                            action_space_config = get_action_space(experiment_name)
                            if action_space_config:
                                full_design = {**current_design, 'equipment': current_equipment}
                                equipment_effects = action_space_config.compute_effects(full_design)
                                sheet.apply_equipment_effects(equipment_effects)
                        except Exception:
                            pass
            elif use_deployment_zone_high_emi:
                # Force high EMI zones only - hides safe low-EMI zones
                env = self.scm.sample_environment(equipment=current_equipment)
                if hasattr(env, 'latent') and 'mission_zone' in env.latent:
                    # Force high EMI zones (epsilon or zeta)
                    high_emi_zone = random.choice(['epsilon', 'zeta'])
                    env.latent['mission_zone'] = high_emi_zone
                    env.latent['emi_level'] = 0.7 + random.uniform(0, 0.2)  # High EMI: 0.7-0.9
                    # Altitude varies but EMI is always high
                    env.visible['altitude_band'] = random.choice(['low', 'medium', 'high'])
                    # Recreate sheet to ensure clean state
                    sheet = DroneSheet(self.config)
                    sheet.set_def_design(current_design)
                    # Re-apply equipment if any
                    if current_equipment:
                        sheet.set_equipment(current_equipment)
                        try:
                            from ..action_space import get_action_space
                            experiment_name = self.config.get('experiment', {}).get('name', 'antenna_trap')
                            action_space_config = get_action_space(experiment_name)
                            if action_space_config:
                                full_design = {**current_design, 'equipment': current_equipment}
                                equipment_effects = action_space_config.compute_effects(full_design)
                                sheet.apply_equipment_effects(equipment_effects)
                        except Exception:
                            pass
            else:
                env = self.scm.sample_environment(equipment=current_equipment)

            self.scm.apply_effects(sheet, env)

            # Check if SCM made a survival decision via component_damage
            state_after_scm = sheet.to_drone_state()
            scm_decided_outcome = (
                state_after_scm.hp.get('engine', 100) <= 0 or
                state_after_scm.hp.get('cockpit', 100) <= 0
            )

            if scm_decided_outcome:
                # SCM decided outcome - skip combat, use SCM's decision directly
                judgment = judge_survival(state_after_scm)
                was_detected = False
                hit_count = 0
            else:
                # Normal combat flow
                was_detected, combat_result = full_simulation(state_after_scm)

                # Apply combat damage if detected
                if was_detected and combat_result:
                    sheet.apply_combat_damage(
                        combat_result.damage_by_component,
                        combat_result.hit_count,
                        combat_result.combat_log if hasattr(combat_result, 'combat_log') else []
                    )

                # Update state after combat
                state = sheet.to_drone_state()

                # Judge survival
                judgment = judge_survival(state)
                hit_count = combat_result.hit_count if combat_result else 0

            # For anti_correlation bias, only keep "lucky" high-antenna survivors
            if use_anti_correlation and judgment.status != 'RETURNED':
                # Skip failed drones - we only want to show lucky survivors
                continue

            # Create observation record with INIT prefix
            observation = {
                'id': f'INIT-{i+1:03d}',
                'design': current_design.copy(),
                'status': judgment.status,
                'hit_count': hit_count,
                'was_detected': was_detected,
                'environment': env.visible.copy(),
            }
            # Include equipment in observation if used
            if current_equipment:
                observation['equipment'] = current_equipment.copy()

            observations.append(observation)

            # Add to history (so agent can query)
            self._history.append(observation)

        return observations
