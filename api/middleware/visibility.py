"""
Visibility control for DroneSheet.

This module defines what fields are visible to different consumers:
- Agent: Limited view (DEF, ATK, some derived values)
- Admin/Frontend: Full view (HP, Agility, all internal state)
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Set, Any, Optional


class Visibility(Enum):
    """Visibility levels for drone attributes."""
    AGENT = "agent"           # Agent can see and modify
    AGENT_READONLY = "agent_readonly"  # Agent can see but not modify
    ADMIN = "admin"           # Only admin/frontend can see
    HIDDEN = "hidden"         # Internal only, not exposed


@dataclass
class FieldVisibility:
    """Visibility configuration for a single field."""
    name: str
    visibility: Visibility
    description: str = ""


# Default visibility configuration
DEFAULT_VISIBILITY: Dict[str, Visibility] = {
    # === Agent writable ===
    "engine_def": Visibility.AGENT,
    "cockpit_def": Visibility.AGENT,
    "wing_def": Visibility.AGENT,
    "body_def": Visibility.AGENT,
    "antenna_def": Visibility.AGENT,
    "camera_def": Visibility.AGENT,
    "gun_def": Visibility.AGENT,

    # === Agent readable (derived) ===
    "total_def": Visibility.AGENT_READONLY,
    "gun_atk": Visibility.AGENT_READONLY,

    # === Admin only (hidden from agent) ===
    "engine_hp": Visibility.ADMIN,
    "cockpit_hp": Visibility.ADMIN,
    "wing_hp": Visibility.ADMIN,
    "body_hp": Visibility.ADMIN,
    "antenna_hp": Visibility.ADMIN,
    "camera_hp": Visibility.ADMIN,
    "gun_hp": Visibility.ADMIN,
    "total_hp": Visibility.ADMIN,
    "agility": Visibility.ADMIN,
    "detection_probability": Visibility.ADMIN,
    "signal_strength": Visibility.ADMIN,
    "stealth_rating": Visibility.ADMIN,

    # === Internal only ===
    "hit_probability_modifier": Visibility.HIDDEN,
    "combat_rounds_base": Visibility.HIDDEN,
}


@dataclass
class VisibilityConfig:
    """
    Visibility configuration manager.

    Admin can modify visibility rules at runtime to change
    what the agent can see (for different experiments).
    """

    # Field visibility mappings
    field_visibility: Dict[str, Visibility] = field(default_factory=dict)

    # Override sets (for dynamic configuration)
    agent_visible_override: Set[str] = field(default_factory=set)
    agent_hidden_override: Set[str] = field(default_factory=set)

    def __post_init__(self):
        """Initialize with default visibility if not provided."""
        if not self.field_visibility:
            self.field_visibility = DEFAULT_VISIBILITY.copy()

    def is_agent_visible(self, field_name: str) -> bool:
        """Check if field is visible to agent."""
        # Check overrides first
        if field_name in self.agent_hidden_override:
            return False
        if field_name in self.agent_visible_override:
            return True

        # Check default visibility
        vis = self.field_visibility.get(field_name, Visibility.HIDDEN)
        return vis in (Visibility.AGENT, Visibility.AGENT_READONLY)

    def is_agent_writable(self, field_name: str) -> bool:
        """Check if agent can modify this field."""
        vis = self.field_visibility.get(field_name, Visibility.HIDDEN)
        return vis == Visibility.AGENT

    def is_admin_visible(self, field_name: str) -> bool:
        """Check if field is visible to admin."""
        vis = self.field_visibility.get(field_name, Visibility.HIDDEN)
        return vis != Visibility.HIDDEN

    def set_visibility(self, field_name: str, visibility: Visibility) -> None:
        """Admin can change field visibility."""
        self.field_visibility[field_name] = visibility

    def show_to_agent(self, field_name: str) -> None:
        """Make a field visible to agent (admin action)."""
        self.agent_visible_override.add(field_name)
        self.agent_hidden_override.discard(field_name)

    def hide_from_agent(self, field_name: str) -> None:
        """Hide a field from agent (admin action)."""
        self.agent_hidden_override.add(field_name)
        self.agent_visible_override.discard(field_name)

    def reset_overrides(self) -> None:
        """Reset all overrides to default visibility."""
        self.agent_visible_override.clear()
        self.agent_hidden_override.clear()

    def get_agent_visible_fields(self) -> Set[str]:
        """Get all fields visible to agent."""
        visible = set()
        for field_name, vis in self.field_visibility.items():
            if self.is_agent_visible(field_name):
                visible.add(field_name)
        return visible

    def filter_for_agent(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Filter a data dict to only agent-visible fields."""
        return {k: v for k, v in data.items() if self.is_agent_visible(k)}

    def filter_for_admin(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Filter a data dict to admin-visible fields."""
        return {k: v for k, v in data.items() if self.is_admin_visible(k)}

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> 'VisibilityConfig':
        """Create VisibilityConfig from experiment configuration."""
        visibility_config = config.get('visibility', {})

        # Parse field visibility from config
        field_vis = DEFAULT_VISIBILITY.copy()
        for field_name, vis_str in visibility_config.get('fields', {}).items():
            try:
                field_vis[field_name] = Visibility(vis_str)
            except ValueError:
                pass  # Use default if invalid

        # Parse override lists
        agent_visible = set(visibility_config.get('agent_visible_override', []))
        agent_hidden = set(visibility_config.get('agent_hidden_override', []))

        # Handle special flag: show_def_remaining
        # This makes current DEF values visible as "def_remaining" in results
        if visibility_config.get('show_def_remaining', False):
            # Add all DEF fields to agent_visible_override
            # They will be included in results as "def_remaining"
            def_fields = ['engine_def', 'cockpit_def', 'wing_def', 'body_def',
                         'antenna_def', 'camera_def', 'gun_def']
            agent_visible.update(def_fields)

        return cls(
            field_visibility=field_vis,
            agent_visible_override=agent_visible,
            agent_hidden_override=agent_hidden,
        )
