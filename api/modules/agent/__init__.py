"""
Agent module - Agent action space and endpoints.

This module provides:
- AgentActionSpace: What actions agent can perform
- Agent-specific API endpoints (separate from admin)
- Agent session management

Key principle: Agent endpoints return filtered data.
HP, agility, and internal details are hidden.
"""

from .action_space import (
    AgentActionSpace,
    ActionType,
    AgentAction,
    DeployAction,
    SubmitAction,
)
from .session import (
    AgentSession,
    SessionManager,
)

__all__ = [
    # Action Space
    'AgentActionSpace',
    'ActionType',
    'AgentAction',
    'DeployAction',
    'SubmitAction',
    # Session
    'AgentSession',
    'SessionManager',
]
