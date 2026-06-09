"""
Tool definitions and executor for CausalGame agent.

This package provides:
- ToolDefinition: Unified tool schema with provider converters
- APIToolExecutor: Executes tool calls against CanyonClient
- CANYON_TOOLS: List of available tools
"""

from .definitions import (
    ToolDefinition,
    ToolParameter,
    ToolCategory,
    CANYON_TOOLS,
    get_tool_by_name,
    get_tools_by_category,
    get_all_openai_tools,
    get_all_gemini_tools,
    get_all_anthropic_tools,
)

from .executor import (
    APIToolExecutor,
    ToolResult,
    ToolResultStatus,
)

__all__ = [
    # Definitions
    "ToolDefinition",
    "ToolParameter",
    "ToolCategory",
    "CANYON_TOOLS",
    "get_tool_by_name",
    "get_tools_by_category",
    "get_all_openai_tools",
    "get_all_gemini_tools",
    "get_all_anthropic_tools",
    # Executor
    "APIToolExecutor",
    "ToolResult",
    "ToolResultStatus",
]
