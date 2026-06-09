"""
API Tool Executor for CausalGame agent.

This module provides the APIToolExecutor class that executes tool calls
against the CanyonClient. The client is explicitly passed in - no hidden injection.
"""

import json
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from agent.client import CanyonClient


class ToolResultStatus(Enum):
    """Status of a tool execution result."""
    SUCCESS = "success"
    ERROR = "error"
    NOT_FOUND = "not_found"


@dataclass
class ToolResult:
    """
    Structured result from a tool execution.

    Attributes:
        status: Execution status (success, error, not_found)
        data: The actual result data (dict, list, etc.)
        error: Error message if status is error
        tool_name: Name of the tool that was executed
    """
    status: ToolResultStatus
    data: Optional[Any] = None
    error: Optional[str] = None
    tool_name: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "status": self.status.value,
            "tool_name": self.tool_name,
        }
        if self.data is not None:
            result["data"] = self.data
        if self.error:
            result["error"] = self.error
        return result

    def to_string(self) -> str:
        """Convert to string representation for LLM consumption."""
        if self.status == ToolResultStatus.ERROR:
            return f"Error executing {self.tool_name}: {self.error}"
        elif self.status == ToolResultStatus.NOT_FOUND:
            return f"Unknown tool: {self.tool_name}"
        else:
            # Format data nicely
            if isinstance(self.data, (dict, list)):
                return json.dumps(self.data, indent=2, default=str)
            return str(self.data)


class APIToolExecutor:
    """
    Executes API tool calls against the Canyon backend.

    The CanyonClient is explicitly passed in during initialization,
    ensuring clear dependency management with no hidden injection.
    """

    def __init__(self, client: "CanyonClient"):
        """
        Initialize the executor with an explicit client reference.

        Args:
            client: The CanyonClient instance to use for API calls
        """
        self._client = client

    @property
    def client(self) -> "CanyonClient":
        """Get the underlying client (read-only access)."""
        return self._client

    def execute(self, tool_name: str, params: Dict[str, Any]) -> ToolResult:
        """
        Execute a tool call and return structured result.

        Args:
            tool_name: Name of the tool to execute
            params: Parameters for the tool call

        Returns:
            ToolResult with status, data, and any errors
        """
        try:
            # Dispatch to appropriate method
            handler = self._get_handler(tool_name)
            if handler is None:
                return ToolResult(
                    status=ToolResultStatus.NOT_FOUND,
                    tool_name=tool_name,
                    error=f"Unknown tool: {tool_name}",
                )

            data = handler(params)
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                data=data,
                tool_name=tool_name,
            )

        except Exception as e:
            return ToolResult(
                status=ToolResultStatus.ERROR,
                tool_name=tool_name,
                error=str(e),
            )

    def _get_handler(self, tool_name: str):
        """Get the handler function for a tool."""
        handlers = {
            "get_status": self._handle_get_status,
            "get_history": self._handle_get_history,
            "get_action_space": self._handle_get_action_space,
            "query_environment": self._handle_query_environment,
            "deploy_drone": self._handle_deploy_drone,
            "submit_final_design": self._handle_submit_final_design,
        }
        return handlers.get(tool_name)

    # =========================================================================
    # Tool Handlers
    # =========================================================================

    def _handle_get_status(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle get_status tool call."""
        return self._client.get_status()

    def _handle_get_history(self, params: Dict[str, Any]) -> Any:
        """Handle get_history tool call."""
        return self._client.get_history()

    def _handle_get_action_space(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle get_action_space tool call."""
        return self._client.get_action_space()

    def _handle_query_environment(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle query_environment tool call."""
        query = params.get("query", "")
        return self._client.query_environment(query)

    def _handle_deploy_drone(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle deploy_drone tool call."""
        design = params.get("design", {})
        count = params.get("count", 1)
        equipment = params.get("equipment")
        return self._client.deploy_drone(design, count, equipment)

    def _handle_submit_final_design(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle submit_final_design tool call."""
        design = params.get("design", {})
        equipment = params.get("equipment")
        return self._client.submit_final_design(design, equipment)
