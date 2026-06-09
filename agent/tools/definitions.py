"""
Tool definitions for CausalGame agent.

This module defines the unified tool schema that can be converted to
provider-specific formats (OpenAI, Gemini, Anthropic).
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Any, Optional


class ToolCategory(Enum):
    """Categories of tools for organization and filtering."""
    READ = "read"           # Data retrieval (get_status, get_history)
    DISCOVERY = "discovery"  # Environment exploration (query_environment)
    ACTION = "action"        # State-changing operations (deploy_drone, submit_final_design)
    ANALYSIS = "analysis"    # Data analysis (reserved for future use)


@dataclass
class ToolParameter:
    """Definition of a single tool parameter."""
    name: str
    type: str  # "string", "integer", "number", "boolean", "object", "array"
    description: str
    required: bool = True
    default: Any = None
    properties: Optional[Dict[str, Any]] = None  # For object types
    items: Optional[Dict[str, Any]] = None  # For array types
    enum: Optional[List[Any]] = None  # For enum constraints


@dataclass
class ToolDefinition:
    """
    Unified tool definition that can be converted to various provider formats.

    This provides a single source of truth for tool schemas across all LLM providers.
    """
    name: str
    description: str
    category: ToolCategory
    parameters: List[ToolParameter] = field(default_factory=list)

    def to_json_schema(self) -> Dict[str, Any]:
        """Convert parameters to JSON Schema format."""
        if not self.parameters:
            return {"type": "object", "properties": {}, "required": []}

        properties = {}
        required = []

        for param in self.parameters:
            prop = {"type": param.type, "description": param.description}

            if param.properties:
                prop["properties"] = param.properties
            if param.items:
                prop["items"] = param.items
            if param.enum:
                prop["enum"] = param.enum
            if param.default is not None:
                prop["default"] = param.default

            properties[param.name] = prop

            if param.required:
                required.append(param.name)

        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }

    def to_openai_function(self) -> Dict[str, Any]:
        """Convert to OpenAI function calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.to_json_schema(),
            }
        }

    def to_openai_tool(self) -> Dict[str, Any]:
        """Alias for to_openai_function (OpenAI uses 'tools' parameter)."""
        return self.to_openai_function()

    def to_gemini_tool(self) -> Dict[str, Any]:
        """Convert to Google Gemini tool format."""
        # Gemini uses a similar format to OpenAI
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.to_json_schema(),
        }

    def to_anthropic_tool(self) -> Dict[str, Any]:
        """Convert to Anthropic Claude tool format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.to_json_schema(),
        }


# =============================================================================
# Tool Definitions for CausalGame
# =============================================================================

CANYON_TOOLS: List[ToolDefinition] = [
    # READ Tools
    ToolDefinition(
        name="get_status",
        description="Get current mission status including drones remaining, deployments remaining, stage, and victory threshold. Use this to check available resources before deploying.",
        category=ToolCategory.READ,
        parameters=[],
    ),

    ToolDefinition(
        name="get_history",
        description="Get all historical flight records including design, survival status, hit_count, and environment data. Use this to analyze patterns and correlations.",
        category=ToolCategory.READ,
        parameters=[],
    ),

    ToolDefinition(
        name="get_action_space",
        description="Get the action space configuration showing valid parameter ranges for drone design (DEF values) and available equipment options.",
        category=ToolCategory.READ,
        parameters=[],
    ),

    # DISCOVERY Tools
    ToolDefinition(
        name="query_environment",
        description="Query the environment interpreter to discover hidden variables that may affect drone survival. Ask about weather, atmospheric conditions, or any environmental factors.",
        category=ToolCategory.DISCOVERY,
        parameters=[
            ToolParameter(
                name="query",
                type="string",
                description="Natural language query about environment. Examples: 'What weather data is available?', 'Are there any hidden atmospheric conditions?'",
                required=True,
            ),
        ],
    ),

    # ACTION Tools
    ToolDefinition(
        name="deploy_drone",
        description="Deploy drones with specified design to test survival. Returns deployment results with survival status for each drone.",
        category=ToolCategory.ACTION,
        parameters=[
            ToolParameter(
                name="design",
                type="object",
                description="Component DEF values. Example: {'engine_def': 15, 'cockpit_def': 15, 'wing_def': 10, 'body_def': 10, 'antenna_def': 10, 'camera_def': 10, 'gun_def': 10}",
                required=True,
                properties={
                    "engine_def": {"type": "integer", "description": "Engine defense value"},
                    "cockpit_def": {"type": "integer", "description": "Cockpit defense value"},
                    "wing_def": {"type": "integer", "description": "Wing defense value"},
                    "body_def": {"type": "integer", "description": "Body defense value"},
                    "antenna_def": {"type": "integer", "description": "Antenna defense value"},
                    "camera_def": {"type": "integer", "description": "Camera defense value"},
                    "gun_def": {"type": "integer", "description": "Gun defense value"},
                },
            ),
            ToolParameter(
                name="count",
                type="integer",
                description="Number of drones to deploy (default: 1)",
                required=False,
                default=1,
            ),
            ToolParameter(
                name="equipment",
                type="object",
                description="Optional equipment choices. Example: {'enhancement_module': 'signal_filter'}",
                required=False,
            ),
        ],
    ),

    ToolDefinition(
        name="submit_final_design",
        description="Submit final drone design for Stage 2 evaluation. WARNING: This can only be called ONCE and is irreversible! Only call when you are confident in your design.",
        category=ToolCategory.ACTION,
        parameters=[
            ToolParameter(
                name="design",
                type="object",
                description="Final component DEF values for evaluation",
                required=True,
                properties={
                    "engine_def": {"type": "integer", "description": "Engine defense value"},
                    "cockpit_def": {"type": "integer", "description": "Cockpit defense value"},
                    "wing_def": {"type": "integer", "description": "Wing defense value"},
                    "body_def": {"type": "integer", "description": "Body defense value"},
                    "antenna_def": {"type": "integer", "description": "Antenna defense value"},
                    "camera_def": {"type": "integer", "description": "Camera defense value"},
                    "gun_def": {"type": "integer", "description": "Gun defense value"},
                },
            ),
            ToolParameter(
                name="equipment",
                type="object",
                description="Optional equipment choices for final design",
                required=False,
            ),
        ],
    ),
]


def get_tools_by_category(category: ToolCategory) -> List[ToolDefinition]:
    """Get all tools in a specific category."""
    return [t for t in CANYON_TOOLS if t.category == category]


def get_tool_by_name(name: str) -> Optional[ToolDefinition]:
    """Get a tool definition by name."""
    for tool in CANYON_TOOLS:
        if tool.name == name:
            return tool
    return None


def get_all_openai_tools() -> List[Dict[str, Any]]:
    """Get all tools in OpenAI format."""
    return [t.to_openai_function() for t in CANYON_TOOLS]


def get_all_gemini_tools() -> List[Dict[str, Any]]:
    """Get all tools in Gemini format."""
    return [t.to_gemini_tool() for t in CANYON_TOOLS]


def get_all_anthropic_tools() -> List[Dict[str, Any]]:
    """Get all tools in Anthropic format."""
    return [t.to_anthropic_tool() for t in CANYON_TOOLS]
