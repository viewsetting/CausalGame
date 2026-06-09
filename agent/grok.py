"""
Grok Handler - xAI Grok model support.

Uses OpenAI-compatible API format with xAI base URL.
"""

import json
from typing import List, Dict, Any, Union, TYPE_CHECKING

from .base import BaseHandler

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

if TYPE_CHECKING:
    from agent.tools.definitions import ToolDefinition


class GrokHandler(BaseHandler):
    """Handler for xAI Grok models using OpenAI-compatible API."""

    # xAI API base URL
    XAI_BASE_URL = "https://api.x.ai/v1"

    def __init__(
        self,
        api_key: str,
        model_name: str = "grok-4-1-fast",
        base_url: str = "http://localhost:8000",
        system_instruction: str = None,
    ):
        """
        Initialize Grok handler.

        Args:
            api_key: xAI API key (XAI_API_KEY)
            model_name: Grok model name (e.g., grok-4-1-fast, grok-4, grok-4-fast)
            base_url: Backend server URL for logging
            system_instruction: System prompt for the model
        """
        super().__init__(api_key, model_name, base_url)

        if OpenAI is None:
            raise ImportError(
                "OpenAI package is not installed. "
                "Please install it with `pip install openai`."
            )

        # Initialize OpenAI client with xAI base URL
        self.client = OpenAI(
            api_key=api_key,
            base_url=self.XAI_BASE_URL,
        )
        self.system_instruction = system_instruction
        self.history = []

        # Add system instruction to history
        if system_instruction:
            self.history.append({"role": "system", "content": system_instruction})

    def send_message(self, message: str) -> str:
        """
        Send message to Grok model.

        Args:
            message: User message

        Returns:
            Model response text
        """
        self.history.append({"role": "user", "content": message})

        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=self.history,
            )
            content = response.choices[0].message.content
            self.history.append({"role": "assistant", "content": content})

            # Track token usage
            if hasattr(response, 'usage') and response.usage:
                self.total_input_tokens += response.usage.prompt_tokens or 0
                self.total_output_tokens += response.usage.completion_tokens or 0

            return content
        except Exception as e:
            # Clean up the user message if the call failed
            self.history.pop()
            raise e

    def supports_tool_calling(self) -> bool:
        """Check if this model supports tool calling."""
        # Grok models support function calling via OpenAI-compatible API
        return True

    def _cleanup_dangling_tool_calls(self):
        """Clean up any dangling tool_calls in history."""
        if not self.history:
            return

        last_assistant_idx = None
        for i in range(len(self.history) - 1, -1, -1):
            if self.history[i].get("role") == "assistant" and self.history[i].get("tool_calls"):
                last_assistant_idx = i
                break

        if last_assistant_idx is None:
            return

        tool_call_ids = set()
        for tc in self.history[last_assistant_idx].get("tool_calls", []):
            tool_call_ids.add(tc.get("id"))

        for i in range(last_assistant_idx + 1, len(self.history)):
            msg = self.history[i]
            if msg.get("role") == "tool":
                tool_call_ids.discard(msg.get("tool_call_id"))

        for missing_id in tool_call_ids:
            self.history.append({
                "role": "tool",
                "tool_call_id": missing_id,
                "content": "[Error: Tool execution was interrupted. Please try again.]"
            })

    def send_message_with_tools(
        self,
        message: str,
        tools: List["ToolDefinition"],
    ) -> Union[str, Dict[str, Any]]:
        """
        Send message with tool calling support.

        Args:
            message: The message to send (can be empty to continue after tool results)
            tools: List of ToolDefinition objects

        Returns:
            Dict with "content" and "tool_calls" if tools were called,
            otherwise plain string response
        """
        # Clean up any dangling tool_calls from previous interrupted calls
        self._cleanup_dangling_tool_calls()

        # Convert tools to OpenAI format
        openai_tools = [t.to_openai_function() for t in tools]

        # Only add user message if not empty
        added_user_message = False
        if message.strip():
            self.history.append({"role": "user", "content": message})
            added_user_message = True

        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=self.history,
                tools=openai_tools,
                tool_choice="auto",
            )

            choice = response.choices[0]
            assistant_message = choice.message

            # Track token usage
            if hasattr(response, 'usage') and response.usage:
                self.total_input_tokens += response.usage.prompt_tokens or 0
                self.total_output_tokens += response.usage.completion_tokens or 0

            # Check if there are tool calls
            if assistant_message.tool_calls:
                # Add assistant message with tool calls to history
                self.history.append({
                    "role": "assistant",
                    "content": assistant_message.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            }
                        }
                        for tc in assistant_message.tool_calls
                    ]
                })

                # Parse tool calls
                parsed_calls = []
                for tc in assistant_message.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        args = {}

                    parsed_calls.append({
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": args,
                        },
                        "name": tc.function.name,
                        "arguments": args,
                    })

                return {
                    "content": assistant_message.content or "",
                    "tool_calls": parsed_calls,
                }

            else:
                # No tool calls, just content
                content = assistant_message.content or ""
                self.history.append({"role": "assistant", "content": content})
                return content

        except Exception as e:
            if added_user_message:
                self.history.pop()
            raise e

    def add_tool_result(self, tool_call_id: str, result: str):
        """
        Add a tool result to the conversation history.

        Args:
            tool_call_id: The ID of the tool call this result is for
            result: The result string from tool execution
        """
        self.history.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": result,
        })
