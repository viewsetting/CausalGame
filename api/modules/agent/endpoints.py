"""
Agent API Endpoints - Separate from admin/frontend endpoints.

These endpoints return FILTERED data:
- HP values are hidden
- Agility is hidden
- Internal state is hidden

Agent can only see:
- DEF values
- hit_count
- survival status
- visible environment variables
"""

from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List, Tuple

from .action_space import (
    AgentActionSpace,
    DeployAction,
    SubmitAction,
    DeployResult,
    SubmitResult,
)
from .session import SessionManager, AgentSession


# Router for agent endpoints
router = APIRouter(prefix="/api/agent", tags=["agent"])


# ============================================================
# Request/Response Models
# ============================================================

class DeployRequest(BaseModel):
    """Request to deploy drones."""
    design: Dict[str, int] = Field(
        ...,
        description="DEF values for each component",
        example={"engine_def": 20, "cockpit_def": 20, "wing_def": 15}
    )
    count: int = Field(
        default=1,
        ge=1,
        le=50,
        description="Number of drones to deploy"
    )
    equipment: Optional[Dict[str, str]] = Field(
        default=None,
        description="Equipment choices for discrete action slots",
        example={"signal_processing": "noise_reduction", "power_mode": "balanced"}
    )


class SubmitRequest(BaseModel):
    """Request to submit final design."""
    design: Dict[str, int] = Field(
        ...,
        description="Final DEF design for Stage 2 evaluation"
    )
    equipment: Optional[Dict[str, str]] = Field(
        default=None,
        description="Equipment choices for discrete action slots"
    )


class RegisterRequest(BaseModel):
    """Request to register agent."""
    model_name: Optional[str] = Field(
        default=None,
        description="Name of the AI model"
    )
    agent_name: Optional[str] = Field(
        default=None,
        description="Agent identifier"
    )
    experiment: Optional[str] = Field(
        default=None,
        description="Experiment name (if not specified, uses server default)"
    )
    execution_mode: str = Field(
        default="legacy",
        description="Execution mode: 'legacy' (code execution) or 'hybrid' (tool calling)"
    )


class LogRequest(BaseModel):
    """Request to log a message."""
    # Support both formats: agent format (type, content, metadata) and simple format (message, level)
    message: Optional[str] = None
    level: str = "info"
    # Agent format fields
    type: Optional[str] = None
    content: Optional[str] = None
    timestamp: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class ReportErrorRequest(BaseModel):
    """Request to report an error."""
    error: str = Field(
        description="Error message"
    )
    error_type: Optional[str] = Field(
        default=None,
        description="Error type (e.g., 'api_error', 'timeout', 'llm_error')"
    )
    fatal: bool = Field(
        default=True,
        description="Whether this error is fatal (ends the session)"
    )


class DeployResponse(BaseModel):
    """Response from deploy endpoint."""
    status: str
    deployed: int
    survived: int
    destroyed: int
    average_hit_count: float
    drones_remaining: int
    results: List[Dict[str, Any]]
    environment: Dict[str, Any]  # Can contain floats or strings (e.g., altitude_band)


class SubmitResponse(BaseModel):
    """Response from submit endpoint."""
    status: str
    fleet_size: int
    survived: int
    survival_rate: str
    final_score: str
    victory: bool
    victory_threshold: str
    message: str


class StatusResponse(BaseModel):
    """Response from status endpoint."""
    drones_remaining: int
    drones_used: int
    total_drones: int
    history_count: int
    victory_threshold: float
    stage2_fleet_size: int
    experiment: Dict[str, str]
    game_over: bool = False
    final_evaluation: Optional[Dict[str, Any]] = None
    # Deployment budget (optional)
    deployments_used: Optional[int] = None
    deployments_remaining: Optional[int] = None
    stage1_deployment_budget: Optional[int] = None
    # Environment query budget
    env_queries_used: Optional[int] = None
    env_queries_remaining: Optional[int] = None
    env_query_budget: Optional[int] = None
    # Token usage (for resume support)
    token_usage: Optional[Dict[str, int]] = None


# ============================================================
# Dependency Injection
# ============================================================

# Global session manager (will be set during app initialization)
_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """Get the session manager."""
    if _session_manager is None:
        raise HTTPException(
            status_code=500,
            detail="Session manager not initialized"
        )
    return _session_manager


def set_session_manager(manager: SessionManager) -> None:
    """Set the global session manager."""
    global _session_manager
    _session_manager = manager


def get_default_session(
    manager: SessionManager = Depends(get_session_manager)
) -> AgentSession:
    """Get the default session for backward compatibility."""
    return manager.get_or_create_default_session()


def get_action_space(
    manager: SessionManager = Depends(get_session_manager)
) -> AgentActionSpace:
    """Get action space for default session."""
    session = manager.get_or_create_default_session()
    action_space = manager.get_action_space(session.session_id)
    if action_space is None:
        raise HTTPException(status_code=500, detail="Action space not found")
    return action_space


def get_session_and_action_space(
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
    manager: SessionManager = Depends(get_session_manager)
) -> Tuple[AgentSession, AgentActionSpace, SessionManager]:
    """
    Get session, action space, and manager by session ID.

    If X-Session-ID header is provided, use that session.
    Otherwise, fall back to default session for backward compatibility.
    """
    if x_session_id:
        session = manager.get_session(x_session_id)
        if session is None:
            raise HTTPException(
                status_code=404,
                detail=f"Session '{x_session_id}' not found. Register first via /api/agent/register"
            )
    else:
        # Backward compatibility: use default session
        session = manager.get_or_create_default_session()

    action_space = manager.get_action_space(session.session_id)
    if action_space is None:
        raise HTTPException(status_code=500, detail="Action space not found")

    return session, action_space, manager


# ============================================================
# Agent Endpoints
# ============================================================

@router.post("/register")
async def register_agent(
    request: RegisterRequest,
    manager: SessionManager = Depends(get_session_manager)
) -> Dict[str, Any]:
    """
    Register an agent and create a session.

    Returns session ID and initial status.
    """
    session = manager.create_session(
        agent_name=request.agent_name,
        model_name=request.model_name,
        experiment_name=request.experiment,
        execution_mode=request.execution_mode
    )

    # Hide experiment name from agent - return generic name
    initial_status = session.to_dict()
    if 'experiment_name' in initial_status:
        initial_status['experiment_name'] = "mission"

    return {
        "status": "registered",
        "session_id": session.session_id,
        "experiment": "mission",
        "initial_status": initial_status
    }


@router.post("/report_error")
async def report_error(
    request: ReportErrorRequest,
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
    manager: SessionManager = Depends(get_session_manager)
) -> Dict[str, Any]:
    """
    Report an error from the agent.

    This is used to mark a session as failed due to an actual error
    (API error, LLM error, etc.) rather than timeout-based detection.

    Headers:
        X-Session-ID: Session ID (required)

    Body:
        error: Error message
        error_type: Optional error type classification
        fatal: Whether the error is fatal (ends session)
    """
    if not x_session_id:
        raise HTTPException(status_code=400, detail="X-Session-ID header required")

    session = manager.get_session(x_session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{x_session_id}' not found")

    # Record the error
    error_msg = request.error
    if request.error_type:
        error_msg = f"[{request.error_type}] {error_msg}"

    session.error = error_msg
    if request.fatal:
        session.game_over = True

    manager._save_session(x_session_id)

    return {
        "status": "error_recorded",
        "session_id": x_session_id,
        "error": error_msg,
        "fatal": request.fatal
    }


@router.get("/status")
async def get_status(
    session_and_action: Tuple[AgentSession, AgentActionSpace, SessionManager] = Depends(get_session_and_action_space)
) -> StatusResponse:
    """
    Get current mission status (agent view).

    Headers:
        X-Session-ID: Optional session ID (uses default if not provided)

    Returns filtered data - HP and agility are hidden.
    """
    session, action_space, _ = session_and_action
    status = action_space._get_status()

    return StatusResponse(
        drones_remaining=status['drones_remaining'],
        drones_used=status['drones_used'],
        total_drones=status['total_drones'],
        history_count=status['history_count'],
        victory_threshold=status['victory_threshold'],
        stage2_fleet_size=status['stage2_fleet_size'],
        experiment={
            "name": "mission",
            "display_name": "Canyon Mission"
        },
        game_over=session.game_over,
        final_evaluation=session.final_result,
        # Deployment budget info (optional)
        deployments_used=status.get('deployments_used'),
        deployments_remaining=status.get('deployments_remaining'),
        stage1_deployment_budget=status.get('stage1_deployment_budget'),
        # Environment query budget
        env_queries_used=session.env_queries_used,
        env_queries_remaining=session.env_query_budget - session.env_queries_used,
        env_query_budget=session.env_query_budget,
        # Token usage (for resume support)
        token_usage=session.token_usage,
    )


@router.post("/deploy")
async def deploy_drones(
    request: DeployRequest,
    session_and_action: Tuple[AgentSession, AgentActionSpace, SessionManager] = Depends(get_session_and_action_space)
) -> DeployResponse:
    """
    Deploy drones with specified design.

    Headers:
        X-Session-ID: Optional session ID (uses default if not provided)

    Returns:
    - Survival statistics
    - hit_count (visible)
    - Environment data (visible variables only)

    Does NOT return:
    - HP values (hidden)
    - Agility (hidden)
    - Detection probability (hidden)
    """
    session, action_space, manager = session_and_action

    # Execute deployment
    action = DeployAction(
        design=request.design,
        count=request.count,
        equipment=request.equipment or {}
    )
    result = action_space.execute(action)

    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    # Update session with FULL results (for admin visibility)
    session.drones_used += result.deployed
    session.deployments_used += 1  # Track deployment calls
    for r in result.full_results:
        session.add_flight(r)

    # Add DEPLOYMENT log with structured data for frontend display
    session.add_log(
        log_type="DEPLOYMENT",
        content=f"Deployed {result.deployed} drones",
        metadata={
            "design": request.design,
            "count": request.count,
            "deployed": result.deployed,
            "survived": result.survived,
            "destroyed": result.destroyed,
        }
    )

    # Auto-save session after deployment
    manager._save_session(session.session_id)

    return DeployResponse(
        status="BATCH_COMPLETE",
        deployed=result.deployed,
        survived=result.survived,
        destroyed=result.destroyed,
        average_hit_count=result.average_hit_count,
        drones_remaining=action_space.drones_remaining,
        results=result.results,
        environment=result.environment
    )


@router.post("/submit")
async def submit_final_design(
    request: SubmitRequest,
    session_and_action: Tuple[AgentSession, AgentActionSpace, SessionManager] = Depends(get_session_and_action_space)
) -> SubmitResponse:
    """
    Submit final design for Stage 2 evaluation.

    Headers:
        X-Session-ID: Optional session ID (uses default if not provided)

    This is a one-shot evaluation with the full fleet.
    """
    session, action_space, manager = session_and_action

    if session.game_over:
        raise HTTPException(
            status_code=400,
            detail="Game already over. Reset to try again."
        )

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

    # Auto-save session after submission
    manager._save_session(session.session_id)

    # Format response
    victory_msg = "VICTORY! Mission accomplished!" if result.victory else "DEFEAT. Mission failed."

    return SubmitResponse(
        status="EVALUATION_COMPLETE",
        fleet_size=result.fleet_size,
        survived=result.survived,
        survival_rate=f"{result.survival_rate * 100:.1f}%",
        final_score=f"{result.final_score * 100:.1f}%",
        victory=result.victory,
        victory_threshold=f"{result.victory_threshold * 100:.1f}%",
        message=victory_msg
    )


@router.get("/history")
async def get_history(
    session_and_action: Tuple[AgentSession, AgentActionSpace, SessionManager] = Depends(get_session_and_action_space)
) -> List[Dict[str, Any]]:
    """
    Get flight history (agent view).

    Headers:
        X-Session-ID: Optional session ID (uses default if not provided)

    Returns filtered data for each flight.
    """
    _, action_space, _ = session_and_action
    return action_space._get_history()


@router.post("/log")
async def add_log(
    request: LogRequest,
    session_and_action: Tuple[AgentSession, AgentActionSpace, SessionManager] = Depends(get_session_and_action_space)
) -> Dict[str, str]:
    """
    Add a log entry from agent.

    Headers:
        X-Session-ID: Optional session ID (uses default if not provided)

    Supports two formats:
    1. Simple: {"message": "...", "level": "info"}
    2. Agent: {"type": "THOUGHT|REPORT", "content": "...", "timestamp": "...", "metadata": {...}}
    """
    session, _, manager = session_and_action

    # Check which format is being used
    if request.type or request.content:
        # Agent format
        session.add_log(
            log_type=request.type,
            content=request.content,
            timestamp=request.timestamp,
            metadata=request.metadata
        )
    else:
        # Simple format
        session.add_log(message=request.message, level=request.level)

    # Auto-save session after logging
    manager._save_session(session.session_id)

    return {"status": "logged"}


@router.post("/reset")
async def reset_session(
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
    manager: SessionManager = Depends(get_session_manager)
) -> Dict[str, str]:
    """
    Reset the current session.

    Headers:
        X-Session-ID: Optional session ID (uses default if not provided)
    """
    if x_session_id:
        session = manager.get_session(x_session_id)
        if session is None:
            raise HTTPException(
                status_code=404,
                detail=f"Session '{x_session_id}' not found"
            )
    else:
        session = manager.get_or_create_default_session()

    manager.reset_session(session.session_id)
    return {"status": "reset", "session_id": session.session_id}


# ============================================================
# Environment Query Endpoint
# ============================================================

class QueryEnvironmentRequest(BaseModel):
    """Request to query environment interpreter."""
    query: Optional[str] = Field(
        default=None,
        description="Single natural language query about environment variables",
        example="What weather data do you have?"
    )
    queries: Optional[List[str]] = Field(
        default=None,
        description="List of queries (each query counts as 1 against budget)",
        example=["What weather data do you have?", "Do you have temperature data?"]
    )


class QueryEnvironmentResponse(BaseModel):
    """Response from environment interpreter."""
    success: bool
    message: str
    discovered_variables: List[str] = []
    env_queries_used: int
    env_queries_remaining: int


@router.post("/query_environment")
async def query_environment(
    request: QueryEnvironmentRequest,
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
    manager: SessionManager = Depends(get_session_manager)
) -> QueryEnvironmentResponse:
    """
    Query the environment interpreter to discover hidden variables.

    Headers:
        X-Session-ID: Optional session ID (uses default if not provided)

    The interpreter uses an LLM to understand natural language queries
    and reveal relevant environment variables to the agent.
    """
    # Validate request - must provide either query or queries
    if not request.query and not request.queries:
        raise HTTPException(
            status_code=400,
            detail="Must provide either 'query' or 'queries'"
        )

    # Get session
    if x_session_id:
        session = manager.get_session(x_session_id)
        if session is None:
            raise HTTPException(
                status_code=404,
                detail=f"Session '{x_session_id}' not found"
            )
    else:
        session = manager.get_or_create_default_session()

    # Check query budget
    if session.env_queries_used >= session.env_query_budget:
        raise HTTPException(
            status_code=400,
            detail=f"Query budget exhausted. Used {session.env_queries_used}/{session.env_query_budget}"
        )

    # Get interpreter
    interpreter = manager.get_interpreter(session.session_id)
    if interpreter is None:
        raise HTTPException(
            status_code=503,
            detail="Environment interpreter not available for this session"
        )

    # Get list of queries (support both single query and batch queries)
    queries = request.queries if request.queries else [request.query]
    query_count = len(queries)

    # Check if we have enough budget for all queries
    if session.env_queries_used + query_count > session.env_query_budget:
        remaining = session.env_query_budget - session.env_queries_used
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient query budget. Requested {query_count} queries, but only {remaining} remaining."
        )

    # Execute each query
    all_discovered = []
    all_messages = []
    all_success = True

    for q in queries:
        try:
            result = interpreter.query(q)
            all_discovered.extend(result.get("discovered_variables", []))
            all_messages.append(result.get("message", ""))
            if not result.get("success", False):
                all_success = False

            # Log each query
            session.query_history.append({
                "query": q,
                "success": result.get("success", False),
                "discovered": result.get("discovered_variables", []),
                "response": result.get("message", "")
            })
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Interpreter error: {str(e)}"
            )

    # Update session - count each query as 1
    session.env_queries_used += query_count
    session.update_activity()

    # Save session to persist query_history and env_queries_used
    manager._save_session(session.session_id)

    # Combine messages for response
    combined_message = "\n\n---\n\n".join(all_messages) if len(all_messages) > 1 else (all_messages[0] if all_messages else "")

    return QueryEnvironmentResponse(
        success=all_success,
        message=combined_message,
        discovered_variables=list(set(all_discovered)),  # Deduplicate
        env_queries_used=session.env_queries_used,
        env_queries_remaining=session.env_query_budget - session.env_queries_used
    )


# ============================================================
# Token Usage Tracking
# ============================================================

class UpdateTokenUsageRequest(BaseModel):
    """Request to update token usage for the session."""
    input_tokens: int = Field(default=0, ge=0, description="Total input tokens consumed")
    output_tokens: int = Field(default=0, ge=0, description="Total output tokens consumed")


class UpdateSessionConfigRequest(BaseModel):
    """Request to update session configuration."""
    max_turns: Optional[int] = Field(default=None, ge=1, description="Maximum turns for this session")
    current_turn: Optional[int] = Field(default=None, ge=0, description="Current turn number")
    final_turn: Optional[int] = Field(default=None, ge=0, description="Turn when final design was submitted")


class UpdateConversationHistoryRequest(BaseModel):
    """Request to update conversation history for resume support."""
    conversation_history: List[Dict[str, str]] = Field(
        ...,
        description="LLM conversation history (list of {role, content} messages)"
    )


@router.post("/token_usage")
async def update_token_usage(
    request: UpdateTokenUsageRequest,
    session_and_action: Tuple[AgentSession, AgentActionSpace, SessionManager] = Depends(get_session_and_action_space)
) -> Dict[str, Any]:
    """
    Update token usage for the session.

    Headers:
        X-Session-ID: Optional session ID (uses default if not provided)

    This endpoint allows the agent to report its token consumption
    at the end of the session or periodically during execution.
    """
    session, _, manager = session_and_action

    # Update token usage
    session.token_usage = {
        "input_tokens": request.input_tokens,
        "output_tokens": request.output_tokens,
        "total_tokens": request.input_tokens + request.output_tokens,
    }
    session.update_activity()

    # Auto-save session
    manager._save_session(session.session_id)

    return {
        "status": "updated",
        "token_usage": session.token_usage,
    }


@router.post("/session_config")
async def update_session_config(
    request: UpdateSessionConfigRequest,
    session_and_action: Tuple[AgentSession, AgentActionSpace, SessionManager] = Depends(get_session_and_action_space)
) -> Dict[str, Any]:
    """
    Update session configuration (max_turns, current_turn).

    Headers:
        X-Session-ID: Optional session ID (uses default if not provided)

    This endpoint allows the orchestrator to record max_turns
    and current_turn for tracking purposes.
    """
    session, _, manager = session_and_action

    # Update config
    if request.max_turns is not None:
        session.max_turns = request.max_turns
    if request.current_turn is not None:
        session.current_turn = request.current_turn
    if request.final_turn is not None:
        session.final_turn = request.final_turn

    session.update_activity()

    # Auto-save session
    manager._save_session(session.session_id)

    return {
        "status": "updated",
        "max_turns": session.max_turns,
        "current_turn": session.current_turn,
        "final_turn": session.final_turn,
    }


@router.post("/conversation_history")
async def update_conversation_history(
    request: UpdateConversationHistoryRequest,
    session_and_action: Tuple[AgentSession, AgentActionSpace, SessionManager] = Depends(get_session_and_action_space)
) -> Dict[str, Any]:
    """
    Update conversation history for the session (for resume support).

    Headers:
        X-Session-ID: Optional session ID (uses default if not provided)

    This endpoint allows the agent to save its LLM conversation history
    so that the session can be resumed after interruption.
    """
    session, _, manager = session_and_action

    # Update conversation history
    session.conversation_history = request.conversation_history
    session.update_activity()

    # Auto-save session
    manager._save_session(session.session_id)

    return {
        "status": "updated",
        "conversation_history_length": len(session.conversation_history),
    }


@router.get("/conversation_history")
async def get_conversation_history(
    session_and_action: Tuple[AgentSession, AgentActionSpace, SessionManager] = Depends(get_session_and_action_space)
) -> Dict[str, Any]:
    """
    Get conversation history for resuming a session.

    Headers:
        X-Session-ID: Session ID to resume

    Returns the saved LLM conversation history for the session.
    """
    session, _, _ = session_and_action

    return {
        "session_id": session.session_id,
        "conversation_history": session.conversation_history,
        "conversation_history_length": len(session.conversation_history),
        "game_over": session.game_over,
        "stage": session.stage,
        "drones_used": session.drones_used,
    }


# ============================================================
# Test Endpoints (for testing/debugging only)
# ============================================================

class SetEvaluationModeRequest(BaseModel):
    """Request to set evaluation mode for testing."""
    is_evaluation: bool


@router.post("/test/set_evaluation_mode")
async def set_evaluation_mode(
    request: SetEvaluationModeRequest,
    session_and_action: Tuple[AgentSession, AgentActionSpace, SessionManager] = Depends(get_session_and_action_space)
) -> Dict[str, Any]:
    """
    Set evaluation mode for SCM testing (TEST ONLY).

    This endpoint allows switching between Stage 1 and Stage 2 weather distributions
    without consuming the submit budget. Useful for testing weather-dependent experiments.

    Args:
        request: {"is_evaluation": true/false}

    Returns:
        Success confirmation with current mode
    """
    session, action_space, manager = session_and_action

    # Call action space method
    action_space.set_evaluation_mode(request.is_evaluation)

    return {
        "success": True,
        "message": f"Evaluation mode set to {request.is_evaluation}",
        "is_evaluation": request.is_evaluation
    }
