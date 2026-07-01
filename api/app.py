"""
CausalGame v2.0 - FastAPI Application Entry Point.

This is a minimal entry point that:
1. Creates the FastAPI application
2. Loads experiment configuration
3. Initializes session manager
4. Includes all routers

Architecture:
- middleware/: DroneSheet, DroneState, visibility control
- modules/agent/: Agent action space and endpoints
- modules/environment/: SCM implementations
- modules/game/: Pure judgment functions
- admin/: Admin/frontend endpoints
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from .routers import setup_routers
from .modules.agent.session import SessionManager
from .modules.agent.endpoints import set_session_manager
from .modules.environment.scm_registry import get_scm_for_experiment
from .security import ensure_admin_token_in_env

# Load .env before touching any os.environ lookups below.
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except ImportError:
    pass


# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================
# Configuration Loading
# ============================================================

def get_experiment_name() -> str:
    """Get experiment name from environment variable."""
    return os.environ.get("CAUSALGAME_EXPERIMENT", "antenna_trap")


def load_experiment_config(experiment_name: str) -> Dict[str, Any]:
    """
    Load experiment configuration from experiments/<name>/game.json.
    """
    # Try multiple possible locations
    possible_paths = [
        Path(__file__).parent.parent / "experiments" / experiment_name / "game.json",
        Path("experiments") / experiment_name / "game.json",
        Path("/app/experiments") / experiment_name / "game.json",
    ]

    for config_path in possible_paths:
        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    config = json.load(f)
                    config['experiment'] = {'name': experiment_name}
                    logger.info(f"Loaded config from {config_path}")
                    return config
            except Exception as e:
                logger.warning(f"Failed to load {config_path}: {e}")

    # Return default config if no file found
    logger.warning(f"No config found for experiment '{experiment_name}', using defaults")
    return {
        'experiment': {'name': experiment_name},
        'resources': {
            'total_drone_budget': 200,
            'stage2_fleet_size': 1000,
            'victory_threshold': 0.55,
        },
        'agility_system': {
            'base_agility': 1.0,
            'linear_coefficient': 0.002,
            'exponential_decay_scale': 200.0,
            'min_agility': 0.1,
        }
    }


# ============================================================
# Application State
# ============================================================

class AppState:
    """Global application state."""

    def __init__(self):
        self.config: Dict[str, Any] = {}
        self.session_manager: Optional[SessionManager] = None
        self.experiment_name: str = ""

    def initialize(self, experiment_name: str) -> None:
        """Initialize application state."""
        self.experiment_name = experiment_name
        self.config = load_experiment_config(experiment_name)
        self.session_manager = SessionManager(self.config)

        # Set session manager for agent endpoints
        set_session_manager(self.session_manager)

        logger.info(f"Initialized app state for experiment: {experiment_name}")


# Global app state
app_state = AppState()


# ============================================================
# Lifespan Management
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan management.

    Handles startup and shutdown events.
    """
    # Startup
    ensure_admin_token_in_env()
    experiment_name = get_experiment_name()
    app_state.initialize(experiment_name)
    logger.info(f"CausalGame v2.0 starting with experiment: {experiment_name}")

    yield

    # Shutdown
    logger.info("CausalGame v2.0 shutting down")


# ============================================================
# Application Factory
# ============================================================

def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.

    Returns:
        Configured FastAPI application
    """
    app = FastAPI(
        title="CausalGame v2.0",
        description="AI Agent Causal Reasoning Testbed",
        version="2.0.0",
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Setup routers
    setup_routers(app)

    # Static files (for frontend)
    # NOTE: Only mount static files in production (Docker).
    # In development, use Vite dev server (npm run dev) for frontend.
    # Mounting to "/" would override API routes, so we only do this in Docker
    # where the app is the only server running.
    import os
    if os.environ.get("CAUSALGAME_SERVE_STATIC", "").lower() == "true":
        possible_static_paths = [
            Path(__file__).parent.parent / "dist",  # Local development
            Path("/app/dist"),  # Docker container
        ]
        for static_path in possible_static_paths:
            if static_path.exists():
                app.mount("/", StaticFiles(directory=str(static_path), html=True), name="static")
                logger.info(f"Mounted static files from {static_path}")
                break

    return app


# ============================================================
# Application Instance
# ============================================================

# Create the application
app = create_app()


# ============================================================
# Utility Functions
# ============================================================

def get_app_state() -> AppState:
    """Get global application state."""
    return app_state


def get_config() -> Dict[str, Any]:
    """Get current experiment configuration."""
    return app_state.config


def get_session_manager() -> SessionManager:
    """Get session manager."""
    if app_state.session_manager is None:
        raise RuntimeError("Application not initialized")
    return app_state.session_manager
