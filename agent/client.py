"""
Canyon Client - API client for CausalGame agent interactions.

Simplified API - all methods use the current DEF-based system with equipment support.
Session management is automatic and transparent to the agent.
"""

import requests
from typing import Dict, List, Any, Optional


class CanyonClient:
    """
    Client for interacting with the CausalGame backend.

    Session management is automatic - the client registers a session on init
    and includes X-Session-ID in all requests transparently.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        model_name: Optional[str] = None,
        agent_name: Optional[str] = None,
        experiment: Optional[str] = None,
        execution_mode: str = "legacy",
        auto_register: bool = True
    ):
        """
        Initialize the Canyon client.

        Args:
            base_url: Backend server URL
            model_name: Model identifier for tracking
            agent_name: Agent identifier for tracking
            experiment: Experiment name (if not specified, uses server default)
            execution_mode: Execution mode - "legacy" or "hybrid"
            auto_register: Whether to auto-register a session (default: True)
        """
        self.base_url = base_url.rstrip('/')
        self.model_name = model_name
        self.agent_name = agent_name
        self.experiment = experiment
        self.execution_mode = execution_mode
        self._session_id: Optional[str] = None  # Internal, not exposed to agent

        if auto_register:
            self._register_session()

    def _headers(self) -> Dict[str, str]:
        """Get headers with session ID (internal)."""
        headers = {"Content-Type": "application/json"}
        if self._session_id:
            headers["X-Session-ID"] = self._session_id
        return headers

    def _get(self, endpoint: str, params: Dict = None) -> Any:
        """Make GET request."""
        url = f"{self.base_url}{endpoint}"
        response = requests.get(url, headers=self._headers(), params=params, timeout=30)
        response.raise_for_status()
        return response.json()

    def _post(self, endpoint: str, data: Dict = None) -> Any:
        """Make POST request."""
        url = f"{self.base_url}{endpoint}"
        response = requests.post(url, headers=self._headers(), json=data or {}, timeout=30)
        response.raise_for_status()
        return response.json()

    def _register_session(self) -> Dict[str, Any]:
        """Register a new agent session (internal, called automatically)."""
        payload = {
            "model_name": self.model_name,
            "agent_name": self.agent_name,
            "execution_mode": self.execution_mode,
        }
        if self.experiment:
            payload["experiment"] = self.experiment
        result = self._post("/api/agent/register", payload)
        self._session_id = result.get("session_id")
        return result

    # ============================================================
    # Status and Data
    # ============================================================

    def get_status(self) -> Dict[str, Any]:
        """
        Get current mission status.

        Returns:
            Dict with mission state including:
            - stage: Current stage (1 or 2)
            - drones_remaining: Available drones for exploration
            - deployments_remaining: Remaining deploy calls
            - victory_threshold: Target survival rate
        """
        return self._get("/api/agent/status")

    def get_action_space(self) -> Dict[str, Any]:
        """
        Get action space configuration for the current experiment.

        Returns:
            Action space config including:
            - numerical: DEF parameters with min/max/default
            - discrete: Equipment options (e.g., enhancement_module choices)
            - boolean: Toggle options
            - constraints: Budget limits (e.g., total_def_budget)
        """
        return self._get("/api/v2/action_space")

    def get_history(self) -> List[Dict[str, Any]]:
        """
        Get historical flight data.

        Returns:
            List of flight records with survival status, hit_count, environment data
        """
        return self._get("/api/agent/history")

    # ============================================================
    # Environment Queries
    # ============================================================

    def get_all_environments(self) -> Dict[str, Dict[str, Any]]:
        """
        Get all environment data for past missions.

        Returns:
            Dict mapping flight_id to environment data
        """
        history = self.get_history()
        environments = {}
        for record in history:
            if "environment" in record:
                flight_id = record.get("flight_id", record.get("id", "unknown"))
                environments[flight_id] = record["environment"]
        return environments

    def query_environment(self, query: str) -> Dict[str, Any]:
        """
        Query the environment interpreter to discover hidden variables.

        Use this to ask about environmental factors that may affect drone survival.
        Newly discovered variables become visible in get_all_environments().

        Args:
            query: Natural language query about environment
                   Examples:
                   - "What measurements are being tracked?"
                   - "What are the deployment zone characteristics?"
                   - "Are there any hidden atmospheric conditions?"

        Returns:
            Interpreter response with discovered variables
        """
        try:
            return self._post("/api/agent/query_environment", {"query": query})
        except Exception:
            return {
                "status": "not_available",
                "success": False,
                "message": "Environment query not available in this experiment. Use deploy_drone to test hypotheses directly instead.",
            }

    # ============================================================
    # Drone Deployment
    # ============================================================

    def deploy_drone(
        self,
        design: Dict[str, int],
        count: int = 1,
        equipment: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Deploy drones with the specified design.

        Args:
            design: Component DEF values, e.g.:
                    {"engine_def": 15, "cockpit_def": 15, "wing_def": 10, ...}
            count: Number of drones to deploy (default: 1)
            equipment: Optional equipment choices, e.g.:
                       {"enhancement_module": "signal_filter"}

        Returns:
            Deployment results with survival status for each drone
        """
        payload = {
            "design": design,
            "count": count,
        }
        if equipment:
            payload["equipment"] = equipment
        return self._post("/api/agent/deploy", payload)

    # ============================================================
    # Final Submission
    # ============================================================

    def submit_final_design(
        self,
        design: Dict[str, int],
        equipment: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Submit final design for Stage 2 evaluation.

        WARNING: This can only be called ONCE! Make sure your design is ready.

        Args:
            design: Final component DEF values
            equipment: Optional equipment choices

        Returns:
            Evaluation results including:
            - survival_rate: Final survival percentage
            - victory: Whether the threshold was met
            - final_score: Overall score
        """
        payload = {"design": design}
        if equipment:
            payload["equipment"] = equipment
        result = self._post("/api/agent/submit", payload)
        result["status"] = "EVALUATION_COMPLETE"
        return result

    # ============================================================
    # Utility Methods
    # ============================================================

    def reset(self) -> Dict[str, Any]:
        """Reset the current session to start over."""
        return self._post("/api/agent/reset")

    def log_message(self, message: str, level: str = "info") -> Dict[str, Any]:
        """
        Log a message for debugging/tracking.

        Args:
            message: Log message
            level: Log level (info, warning, error)
        """
        return self._post("/api/agent/log", {
            "message": message,
            "level": level,
        })

    def report_error(self, error: str, error_type: Optional[str] = None, fatal: bool = True) -> Dict[str, Any]:
        """
        Report an error to the backend.

        Use this to mark the session as failed due to an actual error
        (API error, LLM error, timeout, etc.).

        Args:
            error: Error message
            error_type: Optional error type (e.g., 'api_error', 'llm_error', 'timeout')
            fatal: Whether this error ends the session (default: True)
        """
        return self._post("/api/agent/report_error", {
            "error": error,
            "error_type": error_type,
            "fatal": fatal,
        })

    def update_token_usage(self, input_tokens: int, output_tokens: int) -> Dict[str, Any]:
        """
        Update token usage statistics for this session.

        Args:
            input_tokens: Number of input tokens used
            output_tokens: Number of output tokens used
        """
        return self._post("/api/agent/token_usage", {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        })

    def update_session_config(
        self,
        max_turns: Optional[int] = None,
        current_turn: Optional[int] = None,
        final_turn: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Update session configuration (max_turns, current_turn, final_turn).

        Args:
            max_turns: Maximum turns for this session
            current_turn: Current turn number
            final_turn: Turn when final design was submitted (excludes reflection)
        """
        payload = {}
        if max_turns is not None:
            payload["max_turns"] = max_turns
        if current_turn is not None:
            payload["current_turn"] = current_turn
        if final_turn is not None:
            payload["final_turn"] = final_turn
        return self._post("/api/agent/session_config", payload)

    def export_records(self) -> Dict[str, Any]:
        """
        Export session records (flight history, logs, etc.) to a file.

        Returns:
            Dict with filepath of exported records, or empty dict if not available
        """
        try:
            return self._post("/api/agent/export")
        except Exception:
            # Export endpoint may not be implemented
            return {"status": "not_available", "message": "Export not available"}

    def save_conversation_history(self, history: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        Save conversation history to backend for resume support.

        Args:
            history: List of message dicts with role and content
        """
        return self._post("/api/agent/conversation_history", {"conversation_history": history})

    def get_conversation_history(self) -> Dict[str, Any]:
        """
        Get saved conversation history from backend.

        Returns:
            Dict with conversation_history list
        """
        return self._get("/api/agent/conversation_history")
