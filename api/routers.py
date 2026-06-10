"""
Router Aggregation - Combines all API routers.

This module:
1. Includes agent endpoints (/api/agent/...)
2. Includes admin endpoints (/api/admin/...)
3. Provides legacy endpoint compatibility
"""

from fastapi import FastAPI, APIRouter
from typing import Dict, Any

from .modules.agent.endpoints import router as agent_router
from .admin.endpoints import router as admin_router


# ============================================================
# Legacy Router (backward compatibility)
# ============================================================

legacy_router = APIRouter(tags=["legacy"])


@legacy_router.get("/api/health")
async def health_check() -> Dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "version": "2.0.0"}


@legacy_router.get("/api/mission_status")
async def legacy_mission_status() -> Dict[str, Any]:
    """
    Legacy mission status endpoint.

    Redirects to new agent status endpoint internally.
    """
    from .modules.agent.endpoints import get_session_manager

    manager = get_session_manager()
    session = manager.get_or_create_default_session()
    action_space = manager.get_action_space(session.session_id)

    if action_space is None:
        return {"error": "Not initialized"}

    status = action_space._get_status()

    return {
        "drones_remaining": status['drones_remaining'],
        "hp_remaining": 0,  # Legacy field, not used in v2
        "total_drones": status['total_drones'],
        "total_hp": 0,  # Legacy field
        "hp_per_drone": 0,  # Legacy field
        "stage2_fleet_size": status['stage2_fleet_size'],
        "victory_threshold": status['victory_threshold'],
        "history_count": status['history_count'],
        "survivors": sum(1 for f in action_space._history if f.get('status') == 'RETURNED'),
        "game_over": session.game_over,
        "experiment": {
            "name": "mission",
            "display_name": "Canyon Mission"
        }
    }


@legacy_router.get("/api/mission_data")
async def legacy_mission_data(session_id: str = None):
    """
    Legacy mission data endpoint (for admin/frontend - shows ALL drones).

    Returns flight history. If session_id is provided, returns only that session's data.
    Otherwise returns data from all active sessions.
    Combines INIT observations and SESSION deployments.

    Note: This endpoint returns FULL history including failed drones,
    as it's used by admin/frontend. Agent endpoints filter based on config.
    """
    from .modules.agent.endpoints import get_session_manager

    manager = get_session_manager()

    # If session_id provided, return only that session's data
    if session_id:
        action_space = manager.get_action_space(session_id)
        if action_space:
            return action_space._get_full_history()
        return []

    # Collect history from all sessions
    all_history = []
    for sid, session in manager._sessions.items():
        action_space = manager.get_action_space(sid)
        if action_space:
            all_history.extend(action_space._get_full_history())

    return all_history


@legacy_router.get("/api/session_history")
async def legacy_session_history(session_id: str = None):
    """
    Legacy session history endpoint (for admin/frontend - shows ALL drones).

    Returns flight history. If session_id is provided, returns only that session's data.
    Otherwise returns data from all active sessions.

    Note: This endpoint returns FULL history including failed drones,
    as it's used by admin/frontend. Agent endpoints filter based on config.
    """
    from .modules.agent.endpoints import get_session_manager

    manager = get_session_manager()

    # If session_id provided, return only that session's data
    if session_id:
        action_space = manager.get_action_space(session_id)
        if action_space:
            return action_space._get_full_history()
        return []

    # Collect history from all sessions
    all_history = []
    for sid, session in manager._sessions.items():
        action_space = manager.get_action_space(sid)
        if action_space:
            all_history.extend(action_space._get_full_history())

    return all_history


@legacy_router.post("/api/deploy_drone")
async def legacy_deploy_drone(request: Dict[str, Any]):
    """
    Legacy deploy endpoint.

    Converts old format to new format.
    """
    from .modules.agent.endpoints import get_session_manager
    from .modules.agent.action_space import DeployAction

    manager = get_session_manager()
    session = manager.get_or_create_default_session()
    action_space = manager.get_action_space(session.session_id)

    if action_space is None:
        return {"error": "Not initialized"}

    # Extract design and count
    design = request.get('design', {})
    count = request.get('count', 1)

    # Convert HP-based design to DEF-based if needed
    def_design = {}
    for key, value in design.items():
        if key.endswith('_def'):
            def_design[key] = value
        else:
            # Assume it's already a component name, add _def suffix
            def_design[f"{key}_def"] = value

    action = DeployAction(design=def_design, count=count)
    result = action_space.execute(action)

    if not result.success:
        return {"status": "ERROR", "error": result.error}

    # Update session
    session.drones_used += result.deployed

    return {
        "status": "BATCH_COMPLETE",
        "deployed": result.deployed,
        "survived": result.survived,
        "remaining_drones": action_space.drones_remaining,
        "results": result.results,
        "environment": result.environment,
    }


@legacy_router.post("/api/evaluate_final_design")
async def legacy_evaluate_final_design(request: Dict[str, Any]):
    """
    Legacy final evaluation endpoint.
    """
    from .modules.agent.endpoints import get_session_manager
    from .modules.agent.action_space import SubmitAction

    manager = get_session_manager()
    session = manager.get_or_create_default_session()
    action_space = manager.get_action_space(session.session_id)

    if action_space is None:
        return {"error": "Not initialized"}

    # Extract design
    design = request.get('design', {})

    # Convert to DEF format
    def_design = {}
    for key, value in design.items():
        if key.endswith('_def'):
            def_design[key] = value
        else:
            def_design[f"{key}_def"] = value

    action = SubmitAction(design=def_design)
    result = action_space.execute(action)

    if not result.success:
        return {"status": "ERROR", "error": result.error}

    session.game_over = True
    session.stage = 2

    return {
        "status": "EVALUATION_COMPLETE",
        "design_tested": def_design,
        "fleet_size": result.fleet_size,
        "survived": result.survived,
        "survival_rate": f"{result.survival_rate * 100:.1f}%",
        "final_score": f"{result.final_score * 100:.1f}%",
        "victory": result.victory,
        "victory_threshold": f"{result.victory_threshold * 100:.1f}%",
    }


@legacy_router.post("/api/reset")
async def legacy_reset():
    """
    Legacy reset endpoint.
    """
    from .modules.agent.endpoints import get_session_manager

    manager = get_session_manager()
    session = manager.get_or_create_default_session()
    manager.reset_session(session.session_id)

    return {"status": "RESET"}


# ============================================================
# V2 API Endpoints (placeholder - will be implemented)
# ============================================================

v2_router = APIRouter(prefix="/api/v2", tags=["v2"])


@v2_router.get("/mission_status")
async def v2_mission_status():
    """V2 mission status - DEF-based."""
    from .modules.agent.endpoints import get_session_manager

    manager = get_session_manager()
    session = manager.get_or_create_default_session()
    action_space = manager.get_action_space(session.session_id)

    if action_space is None:
        return {"error": "Not initialized"}

    status = action_space._get_status()

    # Get standard design from config
    standard_design = {}
    if hasattr(action_space, 'config') and action_space.config:
        drone_config = action_space.config.get('drone', {})
        standard_design = drone_config.get('standard_design', {})

    # Get experiment name from manager (the current configured experiment)
    experiment_name = manager.default_experiment

    # Get stage1_deployment_budget from config
    stage1_deployment_budget = None
    if hasattr(action_space, 'config') and action_space.config:
        resources = action_space.config.get('resources', {})
        stage1_deployment_budget = resources.get('stage1_deployment_budget')

    return {
        "api_version": "v2",
        "experiment_name": "mission",
        "drones_remaining": status['drones_remaining'],
        "total_drone_budget": status['total_drones'],
        "total_drones": status['total_drones'],
        "stage2_fleet_size": status['stage2_fleet_size'],
        "victory_threshold": status['victory_threshold'],
        "history_count": status['history_count'],
        "standard_design": standard_design,
        "stage1_deployment_budget": stage1_deployment_budget,
        "experiment": {
            "name": "mission",
        }
    }


@v2_router.get("/action_space")
async def v2_get_action_space():
    """
    Get action space configuration for the current experiment.

    Returns the agent-visible view of available actions:
    - Numerical actions (DEF values with ranges)
    - Discrete actions (equipment choices with descriptions)
    - Boolean actions (toggle flags)
    - Constraints (DEF budget, etc.)

    Note: Hidden effects are NOT included in this response.
    """
    from .modules.agent.endpoints import get_session_manager
    from .modules.action_space import get_action_space

    manager = get_session_manager()
    session = manager.get_or_create_default_session()
    experiment_name = manager.default_experiment  # Use current configured experiment

    try:
        config = get_action_space(experiment_name)
        return {
            "api_version": "v2",
            "experiment_name": "mission",
            "action_space": config.get_agent_view(),
            "defaults": config.get_defaults(),
        }
    except Exception as e:
        return {
            "api_version": "v2",
            "experiment_name": "mission",
            "error": str(e),
            "action_space": None,
        }


@v2_router.post("/deploy_drone")
async def v2_deploy_drone(request: Dict[str, Any]):
    """
    V2 deploy endpoint - DEF-based with optional equipment.

    Request body:
    {
        "design": {"engine_def": 20, "cockpit_def": 20, ...},
        "equipment": {"coating": "stealth", "antenna_mode": "passive"},  // optional
        "count": 5
    }
    """
    from .modules.agent.endpoints import get_session_manager
    from .modules.agent.action_space import DeployAction

    manager = get_session_manager()
    session = manager.get_or_create_default_session()
    action_space = manager.get_action_space(session.session_id)

    if action_space is None:
        return {"error": "Not initialized"}

    design = request.get('design', {})
    equipment = request.get('equipment', {})
    count = request.get('count', 1)

    action = DeployAction(design=design, equipment=equipment, count=count)
    result = action_space.execute(action)

    if not result.success:
        return {"status": "ERROR", "error": result.error}

    session.drones_used += result.deployed

    return {
        "status": "BATCH_COMPLETE",
        "count": result.deployed,
        "survived": result.survived,
        "destroyed": result.destroyed,
        "average_hit_count": result.average_hit_count,
        "drones_remaining": action_space.drones_remaining,
        "environment": result.environment,
        "results": result.results,
        "equipment": equipment if equipment else None,
    }


@v2_router.post("/evaluate_final_design")
async def v2_evaluate_final_design(request: Dict[str, Any]):
    """
    V2 final evaluation endpoint with optional equipment.

    Request body:
    {
        "design": {"engine_def": 20, ...},
        "equipment": {"coating": "stealth", ...}  // optional
    }
    """
    from .modules.agent.endpoints import get_session_manager
    from .modules.agent.action_space import SubmitAction

    manager = get_session_manager()
    session = manager.get_or_create_default_session()
    action_space = manager.get_action_space(session.session_id)

    if action_space is None:
        return {"error": "Not initialized"}

    design = request.get('design', {})
    equipment = request.get('equipment', {})
    action = SubmitAction(design=design, equipment=equipment)
    result = action_space.execute(action)

    if not result.success:
        return {"status": "ERROR", "error": result.error}

    session.game_over = True

    response = {
        "status": "EVALUATION_COMPLETE",
        "design": design,
        "fleet_size": result.fleet_size,
        "results": {
            "survived": result.survived,
            "destroyed": result.fleet_size - result.survived,
            "survival_rate": f"{result.survival_rate * 100:.1f}%"
        },
        "scoring": {
            "survival_component": f"{result.survival_rate * 100:.1f}%",
            "efficiency_component": f"{(1.0 - min(1.0, sum(design.values()) / 300)) * 100:.1f}%",
            "final_score": f"{result.final_score * 100:.1f}%"
        },
        "victory": result.victory,
        "victory_threshold": f"{result.victory_threshold * 100:.1f}%",
        "message": "VICTORY!" if result.victory else "DEFEAT"
    }

    if equipment:
        response["equipment"] = equipment

    return response


# ============================================================
# Router Setup
# ============================================================

def setup_routers(app: FastAPI) -> None:
    """
    Setup all routers on the FastAPI app.

    Args:
        app: FastAPI application instance
    """
    # New agent endpoints
    app.include_router(agent_router)

    # Legacy endpoints (backward compatibility)
    app.include_router(legacy_router)

    # V2 API endpoints
    app.include_router(v2_router)

    # Admin endpoints
    app.include_router(admin_router)
