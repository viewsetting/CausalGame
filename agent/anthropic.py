import json
from typing import List, Dict, Any, Union, TYPE_CHECKING
from .base import BaseHandler

try:
    import anthropic
except ImportError:
    anthropic = None

if TYPE_CHECKING:
    from agent.tools.definitions import ToolDefinition


class AnthropicHandler(BaseHandler):
    """Handler for Anthropic Claude models."""

    def __init__(
        self,
        api_key: str,
        model_name: str = "claude-opus-4-5-20251101",
        base_url: str = "http://localhost:17830",
        system_instruction: str = None,
        enable_thinking: bool = False,
        thinking_budget: int = 10000,
    ):
        super().__init__(api_key, model_name, base_url)
        if anthropic is None:
            raise ImportError("Anthropic package is not installed. Please install it with `pip install anthropic`.")

        self.client = anthropic.Anthropic(api_key=api_key)
        self.system_instruction = system_instruction
        self.history = []
        self._pending_tool_use_id = None  # Track tool use for results
        self.enable_thinking = enable_thinking
        self.thinking_budget = thinking_budget
        self.last_thoughts: str = ""  # Store thinking content for logging/display

    def send_message(self, message: str) -> str:
        self.history.append({"role": "user", "content": message})

        try:
            # Build message kwargs
            kwargs = {
                "model": self.model_name,
                "max_tokens": 16000 if self.enable_thinking else 8192,
                "messages": self.history
            }

            # Add system instruction if provided
            if self.system_instruction:
                kwargs["system"] = self.system_instruction

            # Add extended thinking if enabled
            if self.enable_thinking:
                kwargs["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": self.thinking_budget
                }

            response = self.client.messages.create(**kwargs)

            # Extract text and thinking content from response
            content = ""
            thinking_parts = []

            for block in response.content:
                if block.type == "thinking":
                    # Extended thinking block
                    if hasattr(block, 'thinking'):
                        thinking_parts.append(block.thinking)
                elif block.type == "text":
                    content += block.text

            # Store and log thinking if captured
            if thinking_parts:
                self.last_thoughts = '\n'.join(thinking_parts)
                self.log("THINKING", self.last_thoughts, metadata={
                    "model": self.display_name if hasattr(self, 'display_name') else self.model_name,
                    "is_thinking": True,
                    "thinking_budget": self.thinking_budget,
                })
            else:
                self.last_thoughts = ""

            self.history.append({"role": "assistant", "content": content})

            # Track token usage
            if hasattr(response, 'usage') and response.usage:
                self.total_input_tokens += response.usage.input_tokens or 0
                self.total_output_tokens += response.usage.output_tokens or 0

            return content
        except Exception as e:
            # Clean up the user message if the call failed so we can retry properly if needed
            self.history.pop()
            raise e

    def supports_tool_calling(self) -> bool:
        """Check if this model supports tool calling."""
        # All Claude models support tool use
        return True

    def _cleanup_dangling_tool_use(self):
        """
        Clean up any dangling tool_use blocks in history.

        Anthropic requires every tool_use to have a corresponding tool_result.
        If the last assistant message has tool_use without tool_result,
        we need to add dummy tool_results to keep the history valid.
        """
        if not self.history:
            return

        # Check if last message is assistant with tool_use
        last_msg = self.history[-1]
        if last_msg.get("role") != "assistant":
            return

        content = last_msg.get("content", [])
        if not isinstance(content, list):
            return

        # Find tool_use blocks that need results
        tool_use_ids = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                tool_use_ids.append(block.get("id"))

        if not tool_use_ids:
            return

        # Check if next message (if exists) has tool_results for all
        # Since we're at the end of history, there's no next message
        # Add dummy tool_results for all pending tool_use
        dummy_results = []
        for tool_id in tool_use_ids:
            dummy_results.append({
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": "[Error: Tool execution was interrupted. Please try again.]"
            })

        if dummy_results:
            self.history.append({
                "role": "user",
                "content": dummy_results
            })

    def send_message_with_tools(
        self,
        message: str,
        tools: List["ToolDefinition"],
    ) -> Union[str, Dict[str, Any]]:
        """
        Send message with Anthropic tool use support.

        Args:
            message: The message to send (can be empty to continue after tool results)
            tools: List of ToolDefinition objects

        Returns:
            Dict with "content" and "tool_calls" if tools were called,
            otherwise plain string response
        """
        # Clean up any dangling tool_use from previous interrupted calls
        self._cleanup_dangling_tool_use()

        # Convert tools to Anthropic format
        anthropic_tools = [t.to_anthropic_tool() for t in tools]

        # Only add user message if not empty (empty = continuing after tool results)
        added_user_message = False
        if message.strip():
            self.history.append({"role": "user", "content": message})
            added_user_message = True

        try:
            # Build message kwargs
            kwargs = {
                "model": self.model_name,
                "max_tokens": 16000 if self.enable_thinking else 8192,
                "messages": self.history,
                "tools": anthropic_tools,
            }

            # Add system instruction if provided
            if self.system_instruction:
                kwargs["system"] = self.system_instruction

            # Add extended thinking if enabled
            if self.enable_thinking:
                kwargs["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": self.thinking_budget
                }

            response = self.client.messages.create(**kwargs)

            # Track token usage
            if hasattr(response, 'usage') and response.usage:
                self.total_input_tokens += response.usage.input_tokens or 0
                self.total_output_tokens += response.usage.output_tokens or 0

            # Parse response - extract text, thinking, and tool_use blocks
            text_parts = []
            thinking_parts = []
            tool_calls = []
            assistant_content = []  # For history

            for block in response.content:
                if block.type == "thinking":
                    # Extended thinking block
                    if hasattr(block, 'thinking'):
                        thinking_parts.append(block.thinking)
                elif block.type == "text":
                    text_parts.append(block.text)
                    assistant_content.append({
                        "type": "text",
                        "text": block.text
                    })
                elif block.type == "tool_use":
                    tool_calls.append({
                        "id": block.id,
                        "name": block.name,
                        "function": {
                            "name": block.name,
                            "arguments": block.input,
                        },
                        "arguments": block.input,
                    })
                    assistant_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input
                    })

            content = ''.join(text_parts)

            # Store and log thinking if captured
            if thinking_parts:
                self.last_thoughts = '\n'.join(thinking_parts)
                self.log("THINKING", self.last_thoughts, metadata={
                    "model": self.display_name if hasattr(self, 'display_name') else self.model_name,
                    "is_thinking": True,
                    "thinking_budget": self.thinking_budget,
                })
            else:
                self.last_thoughts = ""

            # Add assistant message to history (include tool_use blocks)
            if assistant_content:
                self.history.append({
                    "role": "assistant",
                    "content": assistant_content
                })

            if tool_calls:
                return {
                    "content": content,
                    "tool_calls": tool_calls,
                }
            else:
                return content

        except Exception as e:
            # Clean up the user message if the call failed and we added one
            if added_user_message:
                self.history.pop()
            raise e

    def add_tool_result(self, tool_call_id: str, result: str):
        """
        Add a tool result to the conversation history.

        For Anthropic, this adds a user message with tool_result content.

        Args:
            tool_call_id: The ID of the tool call this result is for
            result: The result string from tool execution
        """
        # Anthropic expects tool results as user messages with tool_result content
        self.history.append({
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_call_id,
                    "content": result
                }
            ]
        })
