"""
Agent Session Management.

This module provides:
- AgentSession: Single agent session state
- SessionManager: Multi-session management

Sessions track:
- Agent identity
- Resource usage
- Flight history
- Game state
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from datetime import datetime
import uuid
import logging
import json
import os
from pathlib import Path

from api.utils.timezone import now, now_iso
from .action_space import AgentActionSpace
from ..environment.scm_base import CausalSCM
from ..environment.scm_registry import get_scm_for_experiment
from ..environment.generator import EnvironmentGenerator
from ..environment.interpreter import EnvironmentInterpreter


def load_experiment_config(experiment_name: str) -> Dict[str, Any]:
    """
    Load experiment-specific configuration from experiments/<name>/game.json.

    Args:
        experiment_name: Name of the experiment

    Returns:
        Experiment configuration dict
    """
    possible_paths = [
        Path(__file__).parent.parent.parent.parent / "experiments" / experiment_name / "game.json",
        Path("experiments") / experiment_name / "game.json",
        Path("/app/experiments") / experiment_name / "game.json",
    ]

    for config_path in possible_paths:
        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    config = json.load(f)
                    config['experiment'] = {'name': experiment_name}
                    logging.getLogger(__name__).info(f"Loaded experiment config from {config_path}")
                    return config
            except Exception as e:
                logging.getLogger(__name__).warning(f"Failed to load {config_path}: {e}")

    # Return default config
    logging.getLogger(__name__).warning(f"No config found for experiment '{experiment_name}', using defaults")
    return {
        'experiment': {'name': experiment_name},
        'resources': {
            'total_drone_budget': 200,
            'stage2_fleet_size': 1000,
            'victory_threshold': 0.55,
            'env_query_budget': 10,
        }
    }

logger = logging.getLogger(__name__)


@dataclass
class AgentSession:
    """
    Single agent session.

    Tracks all state for one agent's game session.
    """
    session_id: str
    agent_name: Optional[str] = None
    model_name: Optional[str] = None
    execution_mode: str = "legacy"  # "legacy" or "hybrid"

    # Timestamps (timezone-aware)
    created_at: datetime = field(default_factory=now)
    last_activity: datetime = field(default_factory=now)

    # Health status
    status_message: Optional[str] = None  # Optional status message from agent

    # Game state
    experiment_name: str = "default"
    stage: int = 1  # 1 = exploration, 2 = evaluation
    game_over: bool = False
    error: Optional[str] = None  # Error message if session failed/timed out

    # Resource tracking
    drones_used: int = 0
    total_drone_budget: int = 200
    deployments_used: int = 0
    stage1_deployment_budget: Optional[int] = None
    env_queries_used: int = 0
    env_query_budget: int = 10

    # Turn tracking
    max_turns: Optional[int] = None
    current_turn: int = 0
    final_turn: Optional[int] = None  # Turn when final design was submitted (excludes reflection)

    # History
    flight_history: List[Dict[str, Any]] = field(default_factory=list)
    query_history: List[Dict[str, Any]] = field(default_factory=list)
    logs: List[Dict[str, Any]] = field(default_factory=list)

    # Final evaluation result
    final_result: Optional[Dict[str, Any]] = None

    # Token usage tracking
    token_usage: Dict[str, int] = field(default_factory=lambda: {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
    })

    # LLM conversation history for resume support
    conversation_history: List[Dict[str, str]] = field(default_factory=list)

    def update_activity(self) -> None:
        """Update last activity timestamp."""
        self.last_activity = now()

    def add_log(
        self,
        message: Optional[str] = None,
        level: str = "info",
        log_type: Optional[str] = None,
        content: Optional[str] = None,
        timestamp: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Add a log entry.

        Supports two formats:
        1. Simple: add_log(message, level)
        2. Agent format: add_log(log_type=..., content=..., metadata=...)
        """
        # Use agent format if type/content provided, otherwise use simple format
        if log_type or content:
            self.logs.append({
                'timestamp': timestamp or now_iso(),
                'type': log_type or 'INFO',
                'content': content or message or '',
                'metadata': metadata or {},
            })
        else:
            # Simple format - convert to agent format for consistency
            self.logs.append({
                'timestamp': now_iso(),
                'type': level.upper(),
                'content': message or '',
                'metadata': {},
            })

    def add_flight(self, result: Dict[str, Any]) -> None:
        """Add flight to history."""
        self.flight_history.append({
            'timestamp': now_iso(),
            **result,
        })
        self.update_activity()

    def delete_test_flights(self) -> int:
        """
        Delete all test flights from history.

        Returns:
            Number of test flights deleted
        """
        original_count = len(self.flight_history)
        self.flight_history = [f for f in self.flight_history if not f.get('is_test', False)]
        deleted_count = original_count - len(self.flight_history)

        # Also remove test logs
        self.logs = [log for log in self.logs if not log.get('metadata', {}).get('is_test', False)]

        return deleted_count

    def get_test_flight_count(self) -> int:
        """Get the number of test flights in history."""
        return sum(1 for f in self.flight_history if f.get('is_test', False))

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            'session_id': self.session_id,
            'agent_name': self.agent_name,
            'model_name': self.model_name,
            'execution_mode': self.execution_mode,
            'created_at': self.created_at.isoformat(),
            'last_activity': self.last_activity.isoformat(),
            'status_message': self.status_message,
            'experiment_name': self.experiment_name,
            'stage': self.stage,
            'game_over': self.game_over,
            'error': self.error,
            'drones_used': self.drones_used,
            'total_drone_budget': self.total_drone_budget,
            'drones_remaining': self.total_drone_budget - self.drones_used,
            'deployments_used': self.deployments_used,
            'stage1_deployment_budget': self.stage1_deployment_budget,
            'deployments_remaining': (self.stage1_deployment_budget - self.deployments_used) if self.stage1_deployment_budget is not None else None,
            'env_queries_used': self.env_queries_used,
            'env_query_budget': self.env_query_budget,
            'query_history': self.query_history,
            'history_count': len(self.flight_history),
            'survivors': sum(1 for f in self.flight_history if f.get('status') == 'RETURNED'),
            'final_result': self.final_result,
            'token_usage': self.token_usage,
            'conversation_history': self.conversation_history,
            'max_turns': self.max_turns,
            'current_turn': self.current_turn,
            'final_turn': self.final_turn,
        }

    def to_persistent_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for persistence (includes all data)."""
        return {
            'session_id': self.session_id,
            'agent_name': self.agent_name,
            'model_name': self.model_name,
            'execution_mode': self.execution_mode,
            'created_at': self.created_at.isoformat(),
            'last_activity': self.last_activity.isoformat(),
            'status_message': self.status_message,
            'experiment_name': self.experiment_name,
            'stage': self.stage,
            'game_over': self.game_over,
            'error': self.error,
            'drones_used': self.drones_used,
            'total_drone_budget': self.total_drone_budget,
            'deployments_used': self.deployments_used,
            'stage1_deployment_budget': self.stage1_deployment_budget,
            'env_queries_used': self.env_queries_used,
            'env_query_budget': self.env_query_budget,
            'flight_history': self.flight_history,
            'query_history': self.query_history,
            'logs': self.logs,
            'final_result': self.final_result,
            'token_usage': self.token_usage,
            'conversation_history': self.conversation_history,
            'max_turns': self.max_turns,
            'current_turn': self.current_turn,
            'final_turn': self.final_turn,
        }

    @classmethod
    def from_persistent_dict(cls, data: Dict[str, Any]) -> 'AgentSession':
        """Create session from persisted dictionary."""
        session = cls(
            session_id=data['session_id'],
            agent_name=data.get('agent_name'),
            model_name=data.get('model_name'),
            execution_mode=data.get('execution_mode', 'legacy'),
            experiment_name=data.get('experiment_name', 'default'),
            stage=data.get('stage', 1),
            game_over=data.get('game_over', False),
            error=data.get('error'),
            drones_used=data.get('drones_used', 0),
            total_drone_budget=data.get('total_drone_budget', 200),
            deployments_used=data.get('deployments_used', 0),
            stage1_deployment_budget=data.get('stage1_deployment_budget'),
            env_queries_used=data.get('env_queries_used', 0),
            env_query_budget=data.get('env_query_budget', 10),
        )
        # Parse timestamps
        if 'created_at' in data:
            session.created_at = datetime.fromisoformat(data['created_at'])
        if 'last_activity' in data:
            session.last_activity = datetime.fromisoformat(data['last_activity'])
        # Restore health status
        session.status_message = data.get('status_message')
        # Restore history
        session.flight_history = data.get('flight_history', [])
        session.query_history = data.get('query_history', [])
        session.logs = data.get('logs', [])
        session.final_result = data.get('final_result')
        # Restore token usage
        session.token_usage = data.get('token_usage', {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        })
        # Restore conversation history for resume support
        session.conversation_history = data.get('conversation_history', [])
        return session


class SessionManager:
    """
    Manages multiple agent sessions.

    Provides:
    - Session creation and lookup
    - Session cleanup
    - Global statistics
    - Session persistence (one file per session)
    """

    # Persistence settings
    SESSIONS_DIR = "sessions"  # Subdirectory for individual session files
    PERSISTENCE_DIR = "/app/agent_records"  # Docker mount point

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize SessionManager.

        Args:
            config: Global configuration
        """
        self.config = config or {}
        self._sessions: Dict[str, AgentSession] = {}
        self._action_spaces: Dict[str, AgentActionSpace] = {}
        self._scms: Dict[str, CausalSCM] = {}
        self._interpreters: Dict[str, EnvironmentInterpreter] = {}
        self._experiment_configs: Dict[str, Dict[str, Any]] = {}  # Cache for experiment configs

        # Default experiment
        self.default_experiment = self.config.get('experiment', {}).get('name', 'default')

        # Load persisted sessions on startup
        self._load_sessions()

    def _get_experiment_config(self, experiment_name: str) -> Dict[str, Any]:
        """Get experiment config, loading and caching if necessary."""
        if experiment_name not in self._experiment_configs:
            self._experiment_configs[experiment_name] = load_experiment_config(experiment_name)
        return self._experiment_configs[experiment_name]

    def create_session(
        self,
        agent_name: Optional[str] = None,
        model_name: Optional[str] = None,
        experiment_name: Optional[str] = None,
        execution_mode: str = "legacy"
    ) -> AgentSession:
        """
        Create a new agent session.

        Args:
            agent_name: Optional agent identifier
            model_name: Optional model name (e.g., "gpt-4")
            experiment_name: Experiment to use (default from config)
            execution_mode: Execution mode - "legacy" or "hybrid"

        Returns:
            New AgentSession
        """
        session_id = str(uuid.uuid4())[:8]
        experiment = experiment_name or self.default_experiment

        # Load experiment-specific config
        exp_config = self._get_experiment_config(experiment)

        # Get or create SCM for experiment
        if experiment not in self._scms:
            try:
                self._scms[experiment] = get_scm_for_experiment(
                    experiment,
                    exp_config
                )
            except ValueError:
                # Use default SCM
                self._scms[experiment] = get_scm_for_experiment(
                    'base',
                    exp_config
                )

        # Create session with experiment-specific config
        session = AgentSession(
            session_id=session_id,
            agent_name=agent_name,
            model_name=model_name,
            execution_mode=execution_mode,
            experiment_name=experiment,
            total_drone_budget=exp_config.get('resources', {}).get('total_drone_budget', 200),
            stage1_deployment_budget=exp_config.get('resources', {}).get('stage1_deployment_budget'),
            env_query_budget=exp_config.get('resources', {}).get('env_query_budget', 10),
        )

        # Create action space for session with experiment config
        action_space = AgentActionSpace(
            self._scms[experiment],
            exp_config
        )

        # Generate initial observations
        initial_obs_count = exp_config.get('resources', {}).get('initial_observations', 50)
        if initial_obs_count > 0:
            action_space.generate_initial_observations(initial_obs_count)
            logger.info(f"Generated {initial_obs_count} initial observations for session {session_id}")

        # Create environment interpreter for variable discovery
        try:
            generator = EnvironmentGenerator(experiment_name=experiment)
            interpreter = EnvironmentInterpreter(generator)
            self._interpreters[session_id] = interpreter
            logger.info(f"Created interpreter for session {session_id}")
        except Exception as e:
            logger.warning(f"Could not create interpreter for session {session_id}: {e}")
            # Interpreter is optional, session can work without it

        self._sessions[session_id] = session
        self._action_spaces[session_id] = action_space

        logger.info(f"Created session {session_id} for experiment {experiment}")

        # Auto-save this session
        self._save_session(session_id)

        return session

    def get_session(self, session_id: str) -> Optional[AgentSession]:
        """Get session by ID."""
        return self._sessions.get(session_id)

    def get_action_space(self, session_id: str) -> Optional[AgentActionSpace]:
        """Get action space for session."""
        return self._action_spaces.get(session_id)

    def get_interpreter(self, session_id: str) -> Optional[EnvironmentInterpreter]:
        """Get environment interpreter for session."""
        return self._interpreters.get(session_id)

    def delete_session(self, session_id: str) -> bool:
        """Delete a session and its persistence file."""
        if session_id in self._sessions:
            del self._sessions[session_id]
            if session_id in self._action_spaces:
                del self._action_spaces[session_id]
            if session_id in self._interpreters:
                del self._interpreters[session_id]
            # Delete the session file
            self._delete_session_file(session_id)
            return True
        return False

    def delete_test_flights(self, session_id: str) -> int:
        """
        Delete all test flights from a session.

        Args:
            session_id: Session ID to clean test data from

        Returns:
            Number of test flights deleted
        """
        session = self._sessions.get(session_id)
        if session is None:
            return 0

        deleted_count = session.delete_test_flights()

        # Also update action_space history
        action_space = self._action_spaces.get(session_id)
        if action_space:
            action_space._history = [f for f in action_space._history if not f.get('is_test', False)]

        # Save session after deletion
        self._save_session(session_id)

        return deleted_count

    def get_test_flight_count(self, session_id: str) -> int:
        """Get the number of test flights in a session."""
        session = self._sessions.get(session_id)
        if session is None:
            return 0
        return session.get_test_flight_count()

    def list_sessions(self, include_default: bool = False) -> List[Dict[str, Any]]:
        """
        List all active sessions.

        Args:
            include_default: If False (default), excludes the internal 'default' session
                           used for backward compatibility.
        """
        sessions = self._sessions.values()
        if not include_default:
            sessions = [s for s in sessions if s.session_id != "default"]
        return [s.to_dict() for s in sessions]

    def get_or_create_default_session(self) -> AgentSession:
        """
        Get or create a default session.

        For backward compatibility with single-session mode.
        """
        default_id = "default"

        if default_id not in self._sessions:
            session = AgentSession(
                session_id=default_id,
                experiment_name=self.default_experiment,
                total_drone_budget=self.config.get('resources', {}).get('total_drone_budget', 200),
                stage1_deployment_budget=self.config.get('resources', {}).get('stage1_deployment_budget'),
                env_query_budget=self.config.get('resources', {}).get('env_query_budget', 10),
            )

            # Get SCM
            if self.default_experiment not in self._scms:
                try:
                    self._scms[self.default_experiment] = get_scm_for_experiment(
                        self.default_experiment,
                        self.config
                    )
                except ValueError:
                    self._scms[self.default_experiment] = get_scm_for_experiment(
                        'base',
                        self.config
                    )

            action_space = AgentActionSpace(
                self._scms[self.default_experiment],
                self.config
            )

            # Generate initial observations
            initial_obs_count = self.config.get('resources', {}).get('initial_observations', 50)
            if initial_obs_count > 0:
                action_space.generate_initial_observations(initial_obs_count)
                logger.info(f"Generated {initial_obs_count} initial observations for default session")

            # Create environment interpreter
            try:
                generator = EnvironmentGenerator(experiment_name=self.default_experiment)
                interpreter = EnvironmentInterpreter(generator)
                self._interpreters[default_id] = interpreter
                logger.info(f"Created interpreter for default session")
            except Exception as e:
                logger.warning(f"Could not create interpreter for default session: {e}")

            self._sessions[default_id] = session
            self._action_spaces[default_id] = action_space

        return self._sessions[default_id]

    def reset_session(self, session_id: str) -> bool:
        """Reset a session to initial state."""
        session = self._sessions.get(session_id)
        action_space = self._action_spaces.get(session_id)

        if session and action_space:
            session.drones_used = 0
            session.deployments_used = 0
            session.env_queries_used = 0
            session.stage = 1
            session.game_over = False
            session.flight_history.clear()
            session.query_history.clear()
            session.logs.clear()
            session.final_result = None
            action_space.reset()

            # Regenerate initial observations
            initial_obs_count = self.config.get('resources', {}).get('initial_observations', 50)
            if initial_obs_count > 0:
                action_space.generate_initial_observations(initial_obs_count)
                logger.info(f"Regenerated {initial_obs_count} initial observations for session {session_id}")

            # Reset interpreter if exists
            interpreter = self._interpreters.get(session_id)
            if interpreter:
                interpreter.reset()
                logger.info(f"Reset interpreter for session {session_id}")

            # Save reset state
            self._save_session(session_id)

            return True

        return False

    def switch_experiment(self, experiment_name: str, config: Dict[str, Any]) -> None:
        """
        Switch the default experiment with new config.

        Updates the manager-level default experiment used by future default-session
        operations. Caches a new SCM under the new experiment name. Does NOT touch
        already-existing sessions — explicit sessions registered via create_session()
        are scoped to their own experiment and must be left alone, especially under
        concurrent sweeps where another worker may have just started a session for a
        different experiment. Resetting them here previously caused massive
        cross-experiment contamination of benchmark results.

        Args:
            experiment_name: Name of the new default experiment
            config: New experiment configuration
        """
        # Update manager-level defaults
        self.config = config
        self.default_experiment = experiment_name

        # Cache an SCM for the new default experiment (do not clear other cached SCMs;
        # other sessions still reference them via their own action_spaces).
        try:
            self._scms[experiment_name] = get_scm_for_experiment(experiment_name, config)
            logger.info(f"Created SCM for default experiment: {experiment_name}")
        except Exception as e:
            logger.warning(f"Failed to create SCM for {experiment_name}: {e}, using base")
            self._scms[experiment_name] = get_scm_for_experiment('base', config)

        # Reset only the legacy "default" session if present; do NOT touch explicit
        # sessions created via create_session() — they're scoped to their own
        # experiment and may be in the middle of a benchmark run.
        default_session = self._sessions.get('default')
        if default_session is not None and not default_session.game_over:
            default_session.experiment_name = experiment_name
            action_space = AgentActionSpace(self._scms[experiment_name], config)
            initial_obs_count = config.get('resources', {}).get('initial_observations', 50)
            if initial_obs_count > 0:
                action_space.generate_initial_observations(initial_obs_count)
            self._action_spaces['default'] = action_space
            default_session.drones_used = 0
            default_session.deployments_used = 0
            default_session.env_queries_used = 0
            default_session.stage = 1
            default_session.game_over = False
            default_session.flight_history.clear()
            default_session.query_history.clear()
            default_session.logs.clear()
            default_session.final_result = None
            try:
                from ..environment.generator import EnvironmentGenerator
                from ..environment.interpreter import EnvironmentInterpreter
                generator = EnvironmentGenerator(experiment_name=experiment_name)
                self._interpreters['default'] = EnvironmentInterpreter(generator)
            except Exception as e:
                logger.warning(f"Could not recreate interpreter: {e}")
            logger.info(f"Switched default session to experiment {experiment_name}")

    def cleanup_inactive(self, max_age_seconds: int = 3600) -> int:
        """
        Remove inactive sessions.

        Args:
            max_age_seconds: Maximum inactivity before cleanup

        Returns:
            Number of sessions removed
        """
        now = now()
        to_remove = []

        for session_id, session in self._sessions.items():
            age = (now - session.last_activity).total_seconds()
            if age > max_age_seconds and session_id != "default":
                to_remove.append(session_id)

        for session_id in to_remove:
            self.delete_session(session_id)

        return len(to_remove)

    def get_statistics(self) -> Dict[str, Any]:
        """Get global statistics across all sessions."""
        total_drones = sum(s.drones_used for s in self._sessions.values())
        total_flights = sum(len(s.flight_history) for s in self._sessions.values())
        total_survivors = sum(
            sum(1 for f in s.flight_history if f.get('status') == 'RETURNED')
            for s in self._sessions.values()
        )

        return {
            'active_sessions': len(self._sessions),
            'total_drones_deployed': total_drones,
            'total_flights': total_flights,
            'total_survivors': total_survivors,
            'overall_survival_rate': total_survivors / total_flights if total_flights > 0 else 0,
        }

    # ============================================================
    # Persistence Methods (one file per session)
    # ============================================================

    def _get_sessions_dir(self) -> Path:
        """Get the directory for session persistence files."""
        # Try Docker mount first, fallback to local
        if os.path.isdir(self.PERSISTENCE_DIR):
            return Path(self.PERSISTENCE_DIR) / self.SESSIONS_DIR
        # Fallback to project root
        return Path(__file__).parent.parent.parent.parent / "agent_records" / self.SESSIONS_DIR

    def _get_session_file(self, session_id: str) -> Path:
        """Get the file path for a specific session."""
        return self._get_sessions_dir() / f"{session_id}.json"

    def _load_sessions(self) -> None:
        """Load all persisted sessions from disk."""
        sessions_dir = self._get_sessions_dir()
        if not sessions_dir.exists():
            logger.info(f"No sessions directory found at {sessions_dir}")
            return

        loaded_count = 0
        for session_file in sessions_dir.glob("*.json"):
            try:
                session_id = session_file.stem
                # Skip default session
                if session_id == 'default':
                    continue

                with open(session_file, 'r') as f:
                    session_data = json.load(f)

                # Restore session
                session = AgentSession.from_persistent_dict(session_data)
                logger.debug(f"Loaded session {session_id}: game_over={session.game_over}, final_result={session.final_result is not None}")
                self._sessions[session_id] = session

                # Recreate action space (without initial observations since we have history)
                experiment = session.experiment_name
                if experiment not in self._scms:
                    try:
                        self._scms[experiment] = get_scm_for_experiment(experiment, self.config)
                    except ValueError:
                        self._scms[experiment] = get_scm_for_experiment('base', self.config)

                action_space = AgentActionSpace(self._scms[experiment], self.config)
                # Restore state to action space
                action_space._history = session.flight_history.copy()
                action_space._drones_used = session.drones_used
                action_space._deployments_used = session.deployments_used  # Restore deployment count
                self._action_spaces[session_id] = action_space

                # Recreate interpreter
                try:
                    generator = EnvironmentGenerator(experiment_name=experiment)
                    interpreter = EnvironmentInterpreter(generator)
                    self._interpreters[session_id] = interpreter
                except Exception:
                    pass

                loaded_count += 1
                logger.info(f"Restored session {session_id}")
            except Exception as e:
                logger.warning(f"Failed to restore session from {session_file}: {e}")

        logger.info(f"Loaded {loaded_count} sessions from {sessions_dir}")

    def _save_session(self, session_id: str) -> bool:
        """Save a single session to disk."""
        if session_id == 'default':
            return True  # Don't persist default session

        session = self._sessions.get(session_id)
        if not session:
            return False

        session_file = self._get_session_file(session_id)

        try:
            # Ensure directory exists
            session_file.parent.mkdir(parents=True, exist_ok=True)

            data = session.to_persistent_dict()
            data['saved_at'] = now_iso()

            with open(session_file, 'w') as f:
                json.dump(data, f, indent=2)

            logger.debug(f"Saved session {session_id} to {session_file}")
            return True
        except Exception as e:
            logger.error(f"Failed to save session {session_id}: {e}")
            return False

    def _delete_session_file(self, session_id: str) -> bool:
        """Delete a session's persistence file."""
        session_file = self._get_session_file(session_id)
        if session_file.exists():
            try:
                session_file.unlink()
                logger.debug(f"Deleted session file {session_file}")
                return True
            except Exception as e:
                logger.error(f"Failed to delete session file {session_file}: {e}")
                return False
        return True

    def save_sessions(self) -> bool:
        """Save all sessions to disk (for backward compatibility)."""
        success = True
        for session_id in self._sessions:
            if session_id != 'default':
                if not self._save_session(session_id):
                    success = False
        return success

    def delete_all_sessions(self) -> int:
        """
        Delete all sessions (except default).

        Returns:
            Number of sessions deleted
        """
        to_delete = [sid for sid in self._sessions.keys() if sid != 'default']
        count = len(to_delete)

        for session_id in to_delete:
            self.delete_session(session_id)

        logger.info(f"Deleted all {count} sessions")
        return count
