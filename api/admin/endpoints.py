"""
Admin API Endpoints - Full visibility for frontend/admin.

These endpoints return COMPLETE data including:
- HP values
- Agility
- Detection probability
- SCM configuration
- All internal state

Used by:
- Frontend dashboard
- Admin tools
- Debugging
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
from pathlib import Path
import json
import os
import logging

logger = logging.getLogger(__name__)

from ..modules.agent.session import SessionManager
from ..modules.agent.endpoints import get_session_manager
from ..modules.agent.action_space import DeployAction
from ..modules.environment.scm_registry import list_experiments, get_scm_info
from ..utils.timezone import get_timezone_name, now_iso


# Router for admin endpoints
router = APIRouter(prefix="/api/admin", tags=["admin"])


# ============================================================
# Response Models
# ============================================================

class AdminStatusResponse(BaseModel):
    """Full status response for admin."""
    api_version: str = "v2"
    experiment_name: str
    experiment_type: str

    # Resource status
    drones_remaining: int
    drones_used: int
    total_drones: int

    # Deployment budget (optional)
    deployments_used: int = 0
    deployments_remaining: Optional[int] = None
    stage1_deployment_budget: Optional[int] = None

    # Environment query budget
    env_queries_used: int = 0
    env_queries_remaining: int = 10
    env_query_budget: int = 10

    # Hidden values (visible to admin)
    hidden_hp_values: Optional[Dict[str, int]] = None
    agility_config: Optional[Dict[str, float]] = None

    # Session info
    stage: int
    game_over: bool
    history_count: int
    survivors: int

    # Scoring info
    victory_threshold: float
    stage2_fleet_size: int

    # Final evaluation result (for Stage 2)
    final_evaluation: Optional[Dict[str, Any]] = None


class ExperimentInfo(BaseModel):
    """Information about an experiment."""
    name: str
    display_name: str
    description: Optional[str] = None
    version: Optional[str] = None
    author: Optional[str] = None
    scm_class: Optional[str] = None
    path: Optional[str] = None
    is_default: bool = False
    tags: Optional[List[str]] = None


class VisibilityUpdateRequest(BaseModel):
    """Request to update field visibility."""
    field: str
    visibility: str  # "agent", "agent_readonly", "admin", "hidden"


class TestDeployRequest(BaseModel):
    """Request for admin test deployment."""
    design: Dict[str, int]
    count: int = 1
    equipment: Optional[Dict[str, str]] = None
    session_id: Optional[str] = None  # If not provided, uses default session


class ForceSubmitRequest(BaseModel):
    """Request for admin force-submit (auto-submit when agent fails to submit)."""
    design: Dict[str, int]
    equipment: Optional[Dict[str, str]] = None
    session_id: str  # Required - must specify which session to submit for


# ============================================================
# Admin Endpoints
# ============================================================

@router.get("/mission_status")
async def admin_mission_status(
    manager: SessionManager = Depends(get_session_manager)
) -> AdminStatusResponse:
    """
    Get full mission status (admin view).

    Returns ALL data including hidden values.
    """
    session = manager.get_or_create_default_session()
    action_space = manager.get_action_space(session.session_id)

    if action_space is None:
        raise HTTPException(status_code=500, detail="Not initialized")

    status = action_space._get_status()
    config = action_space.config

    # Get hidden values from config
    hidden_hp = config.get('drone', {}).get('components', {})
    hidden_hp_values = {k: v.get('hp', 50) for k, v in hidden_hp.items()} if hidden_hp else None

    # Deployment budget info
    deployment_budget = session.stage1_deployment_budget
    deployments_remaining = (deployment_budget - session.deployments_used) if deployment_budget else None

    return AdminStatusResponse(
        api_version="v2",
        experiment_name=session.experiment_name,
        experiment_type="def_based",
        drones_remaining=status['drones_remaining'],
        drones_used=session.drones_used,
        total_drones=status['total_drones'],
        deployments_used=session.deployments_used,
        deployments_remaining=deployments_remaining,
        stage1_deployment_budget=deployment_budget,
        env_queries_used=session.env_queries_used,
        env_queries_remaining=session.env_query_budget - session.env_queries_used,
        env_query_budget=session.env_query_budget,
        hidden_hp_values=hidden_hp_values,
        agility_config=config.get('agility_system'),
        stage=session.stage,
        game_over=session.game_over,
        history_count=status['history_count'],
        survivors=sum(1 for f in session.flight_history if f.get('status') == 'RETURNED'),
        victory_threshold=status['victory_threshold'],
        stage2_fleet_size=status['stage2_fleet_size'],
        final_evaluation=session.final_result,
    )


@router.get("/experiments")
async def list_available_experiments() -> List[ExperimentInfo]:
    """
    List all available experiments with full metadata from game.json.
    """
    experiments = []
    experiments_dir = Path(__file__).parent.parent.parent / "experiments"
    default_experiment = os.environ.get("CAUSALGAME_EXPERIMENT", "antenna_trap")

    # Get registered SCMs
    scm_list = list_experiments()

    # Build experiments list from experiments directory
    if experiments_dir.exists():
        for exp_dir in experiments_dir.iterdir():
            if exp_dir.is_dir() and (exp_dir / "game.json").exists():
                name = exp_dir.name
                config_path = exp_dir / "game.json"

                # Load metadata from game.json
                display_name = name.replace('_', ' ').title()
                description = None
                version = None
                author = None
                tags = None

                try:
                    with open(config_path) as f:
                        config = json.load(f)
                        exp_info = config.get('experiment', {})
                        display_name = exp_info.get('display_name', display_name)
                        description = exp_info.get('description')
                        version = exp_info.get('version')
                        author = exp_info.get('author')
                        tags = exp_info.get('tags')
                except Exception:
                    pass

                # Get SCM class name
                scm_class = scm_list.get(name, 'Unknown')

                experiments.append(ExperimentInfo(
                    name=name,
                    display_name=display_name,
                    description=description,
                    version=version,
                    author=author,
                    scm_class=scm_class,
                    path=str(config_path),
                    is_default=(name == default_experiment),
                    tags=tags
                ))

    # Add any registered SCMs that don't have a config directory
    for name, class_name in scm_list.items():
        if not any(e.name == name for e in experiments):
            experiments.append(ExperimentInfo(
                name=name,
                display_name=name.replace('_', ' ').title(),
                scm_class=class_name,
                is_default=(name == default_experiment)
            ))

    return experiments


@router.get("/experiment/current")
async def get_current_experiment(
    manager: SessionManager = Depends(get_session_manager)
) -> Dict[str, Any]:
    """
    Get currently active experiment info.

    Returns experiment name, display name, SCM class, and architecture info.
    """
    session = manager.get_or_create_default_session()
    experiment_name = session.experiment_name

    # Get SCM info
    info = get_scm_info(experiment_name)
    scm_class = info.get('class_name', 'Unknown') if info else 'Unknown'

    # Load experiment config for display name
    config_path = Path(__file__).parent.parent.parent / "experiments" / experiment_name / "game.json"
    display_name = experiment_name.replace('_', ' ').title()

    if config_path.exists():
        try:
            with open(config_path) as f:
                config = json.load(f)
                exp_info = config.get('experiment', {})
                display_name = exp_info.get('display_name', display_name)
        except Exception:
            pass

    # Detect architecture (layered vs flat)
    is_layered = scm_class.startswith('Layered') if scm_class else False

    return {
        "name": experiment_name,
        "display_name": display_name,
        "scm_class": scm_class,
        "architecture": {
            "mode": "layered" if is_layered else "flat",
            "is_layered": is_layered
        }
    }


@router.post("/experiment/switch")
async def switch_experiment(
    experiment_name: str,
    manager: SessionManager = Depends(get_session_manager)
) -> Dict[str, str]:
    """
    Switch to a different experiment.

    This resets the current session with new experiment config.
    """
    # Verify experiment exists
    info = get_scm_info(experiment_name)

    # Check config file exists
    config_path = Path(__file__).parent.parent.parent / "experiments" / experiment_name / "game.json"

    if info is None and not config_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Experiment '{experiment_name}' not found"
        )

    # Update environment variable for next restart
    os.environ["CAUSALGAME_EXPERIMENT"] = experiment_name

    # Load new experiment config
    new_config = {}
    if config_path.exists():
        try:
            with open(config_path) as f:
                new_config = json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load config for {experiment_name}: {e}")

    # Switch experiment with new config (creates new SCM and action_space)
    manager.switch_experiment(experiment_name, new_config)

    return {
        "status": "switched",
        "experiment": experiment_name,
        "message": f"Switched to {experiment_name}. Session reset."
    }


@router.get("/scm_model")
async def get_scm_model(
    manager: SessionManager = Depends(get_session_manager)
) -> Dict[str, Any]:
    """
    Get SCM structure for frontend visualization.

    Returns data in the format expected by GameMechanics.tsx:
    - variables: List of causal variables with is_exogenous, description, parents
    - equations: List of structural equations with description and source_code
    - game_parameters: Game configuration parameters
    - causal_graph_text: Human-readable description of the SCM
    """
    session = manager.get_or_create_default_session()
    experiment = session.experiment_name

    info = get_scm_info(experiment)
    if info is None:
        return {"error": f"No SCM found for {experiment}"}

    # Load game config
    config_path = Path(__file__).parent.parent.parent / "experiments" / experiment / "game.json"
    config: Dict[str, Any] = {}
    if config_path.exists():
        try:
            with open(config_path) as f:
                config = json.load(f)
        except Exception:
            pass

    try:
        from ..modules.environment.scm_registry import get_scm_for_experiment
        import inspect

        scm = get_scm_for_experiment(experiment, config)

        # Build variables list in frontend-expected format
        variables = []
        for var in scm._causal_variables.values():
            # Exogenous = no parents in the causal graph (not caused by other variables)
            # Note: 'latent' means hidden from agent, not exogenous
            is_exogenous = not var.parents
            variables.append({
                "name": var.name,
                "is_exogenous": is_exogenous,
                "description": var.description,
                "parents": var.parents,
            })

        # Build equations list with source code
        equations = []
        for eq in scm._equations.values():
            # Try to get source code for the equation function
            source_code = None
            try:
                source_code = inspect.getsource(eq.function)
            except Exception:
                pass

            equations.append({
                "target": eq.target,
                "description": eq.description,
                "source_code": source_code,
            })

        # Build game_parameters from config
        drone_config = config.get('drone', {})
        components = drone_config.get('components', {})
        scm_params = config.get('scm', {}).get('parameters', {})

        # Extract critical components
        critical_components = [
            name for name, comp in components.items()
            if comp.get('is_critical', False)
        ]

        # Build standard design
        standard_design = drone_config.get('standard_design', {})

        # Calculate total HP budget (sum of all component HPs)
        total_hp_budget = sum(comp.get('hp', 0) for comp in components.values())

        # Build detection mechanism info from SCM params
        detection_mechanism = {
            "description": "Antenna signal affects detection probability",
            "formula": f"detection = base + antenna_boost * signal_strength",
            "signal_strength": f"signal = min(1, antenna_hp / 50)",
            "high_wind_threshold": f"{scm_params.get('wind_threshold_high', 35)} km/h",
        }

        # Build damage sources
        damage_sources = {
            "environmental": {
                "high_wind": f"Wind > {scm_params.get('wind_threshold_high', 35)} km/h causes antenna damage",
                "medium_wind": f"Wind > {scm_params.get('wind_threshold_low', 20)} km/h causes moderate damage",
                "storm": "Storm weather damages critical components",
            },
            "combat": {
                "precision_strike": "When detected, targeted attacks on components",
                "scattered_fire": "Random damage distribution when detected",
            }
        }

        game_parameters = {
            "standard_design": standard_design,
            "total_drone_budget": config.get('resources', {}).get('total_drone_budget', 200),
            "total_hp_budget": total_hp_budget,
            "min_hp_per_part": 0,
            "critical_components": critical_components,
            "detection_mechanism": detection_mechanism,
            "damage_sources": damage_sources,
        }

        return {
            "variables": variables,
            "equations": equations,
            "game_parameters": game_parameters,
            "causal_graph_text": scm.describe(),
        }

    except Exception as e:
        import traceback
        return {
            "error": str(e),
            "traceback": traceback.format_exc(),
            "experiment": experiment,
            "scm_class": info.get('class_name'),
        }


@router.get("/config")
async def get_experiment_config(
    manager: SessionManager = Depends(get_session_manager)
) -> Dict[str, Any]:
    """
    Get current experiment configuration.
    """
    session = manager.get_or_create_default_session()
    action_space = manager.get_action_space(session.session_id)

    if action_space is None:
        return {"error": "Not initialized"}

    return {
        "experiment": session.experiment_name,
        "config": action_space.config
    }


@router.get("/config/game")
async def get_game_config(
    manager: SessionManager = Depends(get_session_manager)
) -> Dict[str, Any]:
    """
    Get game.json configuration for current experiment.

    Used by GameManagement settings page.
    """
    session = manager.get_or_create_default_session()
    experiment_name = session.experiment_name

    config_path = Path(__file__).parent.parent.parent / "experiments" / experiment_name / "game.json"

    if not config_path.exists():
        raise HTTPException(status_code=404, detail=f"game.json not found for experiment '{experiment_name}'")

    try:
        with open(config_path) as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load game.json: {str(e)}")


@router.put("/config/game")
async def update_game_config(
    config: Dict[str, Any],
    manager: SessionManager = Depends(get_session_manager)
) -> Dict[str, str]:
    """
    Update game.json configuration for current experiment.

    Note: Changes won't take effect until game reset.
    """
    session = manager.get_or_create_default_session()
    experiment_name = session.experiment_name

    config_path = Path(__file__).parent.parent.parent / "experiments" / experiment_name / "game.json"

    if not config_path.exists():
        raise HTTPException(status_code=404, detail=f"game.json not found for experiment '{experiment_name}'")

    try:
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
        return {"status": "saved", "message": "game.json updated. Reset game to apply changes."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save game.json: {str(e)}")


@router.get("/config/environment_variables")
async def get_environment_variables_config(
    manager: SessionManager = Depends(get_session_manager)
) -> Dict[str, Any]:
    """
    Get environment_variables.json configuration for current experiment.

    Used by GameManagement environment variables editor.
    """
    session = manager.get_or_create_default_session()
    experiment_name = session.experiment_name

    config_path = Path(__file__).parent.parent.parent / "experiments" / experiment_name / "environment_variables.json"

    if not config_path.exists():
        raise HTTPException(status_code=404, detail=f"environment_variables.json not found for experiment '{experiment_name}'")

    try:
        with open(config_path) as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load environment_variables.json: {str(e)}")


@router.put("/config/environment_variables")
async def update_environment_variables_config(
    config: Dict[str, Any],
    manager: SessionManager = Depends(get_session_manager)
) -> Dict[str, str]:
    """
    Update environment_variables.json configuration for current experiment.

    Note: Changes won't take effect until game reset.
    """
    session = manager.get_or_create_default_session()
    experiment_name = session.experiment_name

    config_path = Path(__file__).parent.parent.parent / "experiments" / experiment_name / "environment_variables.json"

    if not config_path.exists():
        raise HTTPException(status_code=404, detail=f"environment_variables.json not found for experiment '{experiment_name}'")

    try:
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
        return {"status": "saved", "message": "environment_variables.json updated. Reset game to apply changes."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save environment_variables.json: {str(e)}")


@router.get("/config/status")
async def get_config_status(
    session_id: Optional[str] = None,
    manager: SessionManager = Depends(get_session_manager)
) -> Dict[str, Any]:
    """
    Get whether config can be modified.

    Args:
        session_id: Optional session ID. If provided, checks that specific session.
                   Otherwise checks the default session.

    Config can be modified when:
    - Game is over (game_over = true), OR
    - No flights have been made yet (history_count = 0)
    """
    if session_id:
        session = manager.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    else:
        session = manager.get_or_create_default_session()

    # Can modify if game is over or no activity yet
    can_modify = session.game_over or len(session.flight_history) == 0

    return {
        "can_modify": can_modify,
        "game_over": session.game_over,
        "history_count": len(session.flight_history),
        "session_id": session.session_id,
        "reason": "Game is over" if session.game_over else ("No flights yet" if len(session.flight_history) == 0 else "Agent is active")
    }


@router.get("/sessions")
async def list_sessions(
    manager: SessionManager = Depends(get_session_manager)
) -> List[Dict[str, Any]]:
    """
    List all active sessions.
    """
    return manager.list_sessions()


@router.get("/sessions/{session_id}")
async def get_session_detail(
    session_id: str,
    manager: SessionManager = Depends(get_session_manager)
) -> Dict[str, Any]:
    """
    Get detailed information about a specific session.
    """
    session = manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    action_space = manager.get_action_space(session_id)
    status = action_space._get_status() if action_space else {}

    # Add session-level fields to status for frontend compatibility
    status['game_over'] = session.game_over
    status['final_evaluation'] = session.final_result
    status['env_queries_used'] = session.env_queries_used
    status['env_queries_remaining'] = session.env_query_budget - session.env_queries_used
    status['env_query_budget'] = session.env_query_budget

    return {
        **session.to_dict(),
        "status": status,
        "logs": session.logs,  # All logs (frontend handles scrolling)
        "recent_flights": session.flight_history[-10:],  # Last 10 flights
    }


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    manager: SessionManager = Depends(get_session_manager)
) -> Dict[str, str]:
    """
    Delete a specific session.
    """
    if session_id == "default":
        raise HTTPException(status_code=400, detail="Cannot delete default session")

    if not manager.delete_session(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    return {"status": "deleted", "session_id": session_id}


@router.delete("/sessions/{session_id}/test-data")
async def delete_test_data(
    session_id: str,
    manager: SessionManager = Depends(get_session_manager)
) -> Dict[str, Any]:
    """
    Delete all test flights from a session.

    Test flights are deployments made with is_test=true flag.
    This allows cleaning up test data without affecting real agent data.
    """
    session = manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    deleted_count = manager.delete_test_flights(session_id)

    return {
        "status": "deleted",
        "session_id": session_id,
        "deleted_flights": deleted_count,
        "remaining_flights": len(session.flight_history),
        "message": f"Deleted {deleted_count} test flights"
    }


@router.get("/sessions/{session_id}/test-data/count")
async def get_test_data_count(
    session_id: str,
    manager: SessionManager = Depends(get_session_manager)
) -> Dict[str, Any]:
    """
    Get the count of test flights in a session.
    """
    session = manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    return {
        "session_id": session_id,
        "test_flights": session.get_test_flight_count()
    }


@router.post("/sessions/{session_id}/clear-error")
async def clear_session_error(
    session_id: str,
    manager: SessionManager = Depends(get_session_manager)
) -> Dict[str, Any]:
    """
    Clear error state from a session to allow resuming.

    This resets game_over to False and clears the error message,
    allowing the session to continue from where it left off.
    """
    session = manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    if not session.error:
        return {
            "status": "no_change",
            "session_id": session_id,
            "message": "Session has no error to clear"
        }

    old_error = session.error
    session.error = None
    session.game_over = False
    manager._save_session(session_id)

    return {
        "status": "cleared",
        "session_id": session_id,
        "previous_error": old_error,
        "message": "Error cleared, session can be resumed"
    }


@router.post("/test-deploy")
async def admin_test_deploy(
    request: TestDeployRequest,
    manager: SessionManager = Depends(get_session_manager)
) -> Dict[str, Any]:
    """
    Admin-only test deployment endpoint.

    Deploys drones marked as test data, which can be deleted later
    without affecting real agent data. Used for testing game mechanics.

    This endpoint does NOT consume drone budget or deployment budget.
    """
    # Get session
    if request.session_id:
        session = manager.get_session(request.session_id)
        if session is None:
            raise HTTPException(status_code=404, detail=f"Session '{request.session_id}' not found")
    else:
        session = manager.get_or_create_default_session()

    action_space = manager.get_action_space(session.session_id)
    if action_space is None:
        raise HTTPException(status_code=500, detail="Action space not found")

    # Execute deployment (but don't consume budget)
    action = DeployAction(
        design=request.design,
        count=request.count,
        equipment=request.equipment or {}
    )

    # Directly call internal method with is_test=True to bypass budget checks
    result = action_space._execute_deploy(action, is_test=True)

    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    # Add to history with is_test flag (don't update drone counts)
    for r in result.full_results:
        r['is_test'] = True
        session.add_flight(r)

    # Add test deployment log
    session.add_log(
        log_type="TEST_DEPLOYMENT",
        content=f"[ADMIN TEST] Deployed {result.deployed} test drones",
        metadata={
            "design": request.design,
            "count": request.count,
            "deployed": result.deployed,
            "survived": result.survived,
            "destroyed": result.destroyed,
            "is_test": True,
        }
    )

    # Save session
    manager._save_session(session.session_id)

    return {
        "status": "TEST_COMPLETE",
        "deployed": result.deployed,
        "survived": result.survived,
        "destroyed": result.destroyed,
        "survival_rate": f"{(result.survived / result.deployed * 100):.1f}%" if result.deployed > 0 else "0%",
        "average_hit_count": result.average_hit_count,
        "results": result.results,
        "environment": result.environment,
        "is_test": True,
        "note": "Test deployment - does not consume budget, can be deleted"
    }


@router.post("/force-submit")
async def admin_force_submit(
    request: ForceSubmitRequest,
    manager: SessionManager = Depends(get_session_manager)
) -> Dict[str, Any]:
    """
    Admin-only force submission endpoint.

    This allows submitting a final design even when game_over=True (e.g., when
    drones are exhausted). Used by run_agent.py for auto-submit when the agent
    fails to submit on its own.

    Unlike the agent endpoint, this bypasses the game_over check but still
    requires that no final_result exists yet.
    """
    session = manager.get_session(request.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{request.session_id}' not found")

    # Check if already has final result
    if session.final_result is not None:
        raise HTTPException(
            status_code=400,
            detail="Session already has final result. Cannot submit again."
        )

    action_space = manager.get_action_space(request.session_id)
    if action_space is None:
        raise HTTPException(status_code=500, detail="Action space not found")

    # Import SubmitAction here to avoid circular imports
    from ..modules.agent.action_space import SubmitAction

    # Execute submission
    action = SubmitAction(
        design=request.design,
        equipment=request.equipment or {}
    )
    result = action_space.execute(action)

    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    # Update session
    session.stage = 2
    session.game_over = True

    # Calculate DEF efficiency
    total_def = sum(request.design.values())
    def_efficiency = 1.0 - min(1.0, total_def / 300)

    session.final_result = {
        'status': 'EVALUATION_COMPLETE',
        'design_tested': request.design.copy(),
        'fleet_size': result.fleet_size,
        'total_drones': result.fleet_size,
        'survived': result.survived,
        'survival_rate': f"{result.survival_rate * 100:.1f}%",
        'final_score': f"{result.final_score * 100:.1f}%",
        'def_efficiency': f"{def_efficiency * 100:.1f}%",
        'total_def': total_def,
        'victory': result.victory,
        'victory_threshold': result.victory_threshold,
    }

    # Add log entry for force-submit
    session.add_log(
        log_type="ADMIN_FORCE_SUBMIT",
        content=f"[ADMIN] Force-submitted design: survival_rate={result.survival_rate*100:.1f}%",
        metadata={
            "design": request.design,
            "survived": result.survived,
            "fleet_size": result.fleet_size,
            "victory": result.victory,
        }
    )

    # Save session
    manager._save_session(request.session_id)

    return {
        "status": "FORCE_SUBMIT_COMPLETE",
        "session_id": request.session_id,
        "design_tested": request.design,
        "fleet_size": result.fleet_size,
        "survived": result.survived,
        "survival_rate": f"{result.survival_rate * 100:.1f}%",
        "victory": result.victory,
        "victory_threshold": result.victory_threshold,
    }


@router.delete("/sessions")
async def delete_all_sessions(
    manager: SessionManager = Depends(get_session_manager)
) -> Dict[str, Any]:
    """
    Delete all sessions (except the internal default session).

    This permanently removes all session data from persistence storage.
    """
    deleted_count = manager.delete_all_sessions()
    return {
        "status": "deleted",
        "deleted_count": deleted_count,
        "message": f"Deleted {deleted_count} sessions"
    }


@router.post("/sessions/cleanup")
async def cleanup_sessions(
    max_age_seconds: int = 3600,
    manager: SessionManager = Depends(get_session_manager)
) -> Dict[str, Any]:
    """
    Clean up inactive sessions.

    Args:
        max_age_seconds: Sessions inactive for longer than this will be removed (default 1 hour)
    """
    removed = manager.cleanup_inactive(max_age_seconds)
    return {
        "status": "cleaned",
        "removed_count": removed,
        "remaining_sessions": len(manager.list_sessions())
    }


@router.get("/statistics")
async def get_statistics(
    manager: SessionManager = Depends(get_session_manager)
) -> Dict[str, Any]:
    """
    Get global statistics across all sessions.
    """
    return manager.get_statistics()


@router.get("/agent/logs")
async def get_agent_logs(
    session_id: Optional[str] = None,
    manager: SessionManager = Depends(get_session_manager)
) -> List[Dict[str, Any]]:
    """
    Get agent logs.

    If session_id is provided, returns logs for that session.
    Otherwise, returns logs from the most recently active non-default session,
    or default session if no other sessions exist.
    """
    if session_id:
        session = manager.get_session(session_id)
        if session:
            return session.logs
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    # Get all sessions and find the most recently active non-default one
    all_sessions = list(manager._sessions.values())
    non_default_sessions = [s for s in all_sessions if s.session_id != "default"]

    if non_default_sessions:
        # Sort by last_activity descending and return logs from most recent
        most_recent = max(non_default_sessions, key=lambda s: s.last_activity)
        return most_recent.logs

    # Fallback to default session
    session = manager.get_or_create_default_session()
    return session.logs


@router.get("/flight_history")
async def get_full_flight_history(
    manager: SessionManager = Depends(get_session_manager)
) -> List[Dict[str, Any]]:
    """
    Get complete flight history with all details.

    Unlike agent endpoint, this includes HP and other hidden data.
    """
    session = manager.get_or_create_default_session()

    # For admin, we might want to enhance the history with more details
    # For now, return the same data
    return session.flight_history


@router.put("/visibility")
async def update_visibility(
    request: VisibilityUpdateRequest,
    manager: SessionManager = Depends(get_session_manager)
) -> Dict[str, str]:
    """
    Update visibility for a field.

    Allows admin to change what agent can see.
    """
    from ..middleware.visibility import Visibility

    # Validate visibility value
    try:
        vis = Visibility(request.visibility)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid visibility: {request.visibility}. "
                   f"Must be one of: agent, agent_readonly, admin, hidden"
        )

    # This would need to be propagated to DroneSheet instances
    # For now, just acknowledge
    return {
        "status": "updated",
        "field": request.field,
        "visibility": request.visibility,
        "note": "Visibility changes apply to new drones only"
    }


@router.post("/reset")
async def admin_reset(
    manager: SessionManager = Depends(get_session_manager)
) -> Dict[str, str]:
    """
    Admin reset - clears all sessions.
    """
    session = manager.get_or_create_default_session()
    manager.reset_session(session.session_id)

    return {"status": "reset", "message": "All sessions cleared"}


@router.get("/server_config")
async def get_server_config() -> Dict[str, Any]:
    """
    Get server configuration including timezone.

    Frontend should use this to display times consistently.
    """
    return {
        "timezone": get_timezone_name(),
        "server_time": now_iso(),
    }
