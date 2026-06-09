import json
from typing import List, Dict, Any, Union, TYPE_CHECKING

from .base import BaseHandler

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

if TYPE_CHECKING:
    from agent.tools.definitions import ToolDefinition

# Models that use Responses API instead of Chat Completions
# NOTE: Responses API does NOT support tool calling yet, so only use for models
# that specifically require it (like codex). Other models should use Chat Completions.
RESPONSES_API_MODELS = ["gpt-5.2-codex", "codex"]

# Models that support function/tool calling
TOOL_CALLING_MODELS = [
    "gpt-4", "gpt-4o", "gpt-4o-mini", "gpt-4-turbo",
    "gpt-3.5-turbo", "gpt-5", "gpt-5.1", "gpt-5.2", "gpt-5-mini",
    "gpt-5.2-codex", "codex",  # Responses API models also support tools
]


class OpenAIHandler(BaseHandler):
    def __init__(
        self,
        api_key: str,
        model_name: str = "gpt-4",
        base_url: str = "http://localhost:17830",
        system_instruction: str = None,
        api_base_url: str = None,
        reasoning_effort: str = None,
        enable_thinking: bool = False,
    ):
        super().__init__(api_key, model_name, base_url)
        if OpenAI is None:
            raise ImportError("OpenAI package is not installed. Please install it with `pip install openai`.")

        # Use api_base_url if provided (for DeepSeek and other OpenAI-compatible APIs)
        client_kwargs = {"api_key": api_key}
        if api_base_url:
            client_kwargs["base_url"] = api_base_url

        self.client = OpenAI(**client_kwargs)
        self.system_instruction = system_instruction
        self.history = []

        # Reasoning effort: use explicit value, or default to "medium" if thinking enabled
        if reasoning_effort:
            self.reasoning_effort = reasoning_effort
        elif enable_thinking:
            self.reasoning_effort = "medium"  # Default reasoning effort when thinking enabled
        else:
            self.reasoning_effort = None

        self.enable_thinking = enable_thinking
        self.last_thoughts: str = ""  # Store reasoning content for logging/display

        # Check if this model uses Responses API
        self.use_responses_api = any(m in model_name.lower() for m in RESPONSES_API_MODELS)

        if not self.use_responses_api:
            # Chat models use message history with system prompt
            if system_instruction:
                self.history.append({"role": "system", "content": system_instruction})

    def send_message(self, message: str) -> str:
        if self.use_responses_api:
            return self._send_responses_api(message)
        else:
            return self._send_chat(message)

    def _send_chat(self, message: str) -> str:
        """Send message using chat completions API."""
        self.history.append({"role": "user", "content": message})

        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=self.history
            )
            msg = response.choices[0].message
            content = msg.content
            reasoning_content = getattr(msg, "reasoning_content", None)
            hist_entry = {"role": "assistant", "content": content}
            if reasoning_content:
                hist_entry["reasoning_content"] = reasoning_content
            self.history.append(hist_entry)

            # Track token usage
            if hasattr(response, 'usage') and response.usage:
                self.total_input_tokens += response.usage.prompt_tokens or 0
                self.total_output_tokens += response.usage.completion_tokens or 0

            return content
        except Exception as e:
            # Clean up the user message if the call failed
            self.history.pop()
            raise e

    def _send_responses_api(self, message: str) -> str:
        """Send message using Responses API (for newer models like GPT-5.2-Codex)."""
        # Build input with conversation history
        input_messages = []

        # Add system instruction as first message if present
        if self.system_instruction and not self.history:
            input_messages.append({
                "role": "system",
                "content": self.system_instruction
            })

        # Add conversation history
        for entry in self.history:
            input_messages.append({
                "role": entry["role"],
                "content": entry["content"]
            })

        # Add current user message
        input_messages.append({
            "role": "user",
            "content": message
        })

        try:
            # Build API call kwargs
            api_kwargs = {
                "model": self.model_name,
                "input": input_messages,
            }

            # Add reasoning effort if specified (enables reasoning output)
            if self.reasoning_effort:
                # Note: "summary": "auto" requires organization verification
                # Only use basic reasoning effort for now
                api_kwargs["reasoning"] = {"effort": self.reasoning_effort}

            response = self.client.responses.create(**api_kwargs)

            # Extract reasoning and output from response
            reasoning_text = ""
            output_text = ""

            # Response.output is a list of items (reasoning, message, etc.)
            if hasattr(response, 'output') and response.output:
                for item in response.output:
                    if hasattr(item, 'type'):
                        if item.type == 'reasoning' and hasattr(item, 'summary'):
                            # Extract reasoning summary text
                            for summary_item in item.summary:
                                if hasattr(summary_item, 'text'):
                                    reasoning_text += summary_item.text + "\n"
                                elif isinstance(summary_item, dict) and 'text' in summary_item:
                                    reasoning_text += summary_item['text'] + "\n"
                        elif item.type == 'message' and hasattr(item, 'content'):
                            # Extract message content
                            for content_item in item.content:
                                if hasattr(content_item, 'text'):
                                    output_text += content_item.text
                                elif isinstance(content_item, dict) and 'text' in content_item:
                                    output_text += content_item['text']

            # Fallback to output_text if available
            if not output_text and hasattr(response, 'output_text'):
                output_text = response.output_text

            # Store and log reasoning if captured
            if reasoning_text.strip():
                self.last_thoughts = reasoning_text.strip()
                self.log("THINKING", self.last_thoughts, metadata={
                    "model": self.display_name if hasattr(self, 'display_name') else self.model_name,
                    "is_thinking": True,
                    "reasoning_effort": self.reasoning_effort,
                })
            else:
                self.last_thoughts = ""

            content = output_text or ""

            # Store in history for context
            self.history.append({"role": "user", "content": message})
            self.history.append({"role": "assistant", "content": content})

            # Track token usage (if available in responses API)
            if hasattr(response, 'usage') and response.usage:
                self.total_input_tokens += getattr(response.usage, 'input_tokens', 0) or 0
                self.total_output_tokens += getattr(response.usage, 'output_tokens', 0) or 0

            return content
        except Exception as e:
            raise e

    def _send_responses_api_with_tools(
        self,
        message: str,
        tools: List["ToolDefinition"],
    ) -> Union[str, Dict[str, Any]]:
        """Send message with tools using Responses API (for gpt-5.2-codex)."""
        # Build input with conversation history
        input_messages = []

        # Add system instruction as first message if present
        if self.system_instruction and not self.history:
            input_messages.append({
                "role": "system",
                "content": self.system_instruction
            })

        # Add conversation history
        for entry in self.history:
            role = entry.get("role")
            if role == "tool":
                # Convert tool results to Responses API format
                input_messages.append({
                    "type": "function_call_output",
                    "call_id": entry.get("tool_call_id"),
                    "output": entry.get("content", "")
                })
            elif role == "assistant":
                # Check for function calls in assistant message
                if entry.get("tool_calls"):
                    # Add text content if present
                    if entry.get("content"):
                        input_messages.append({
                            "role": "assistant",
                            "content": entry["content"]
                        })
                    # Add function calls
                    for tc in entry.get("tool_calls", []):
                        func = tc.get("function", {})
                        input_messages.append({
                            "type": "function_call",
                            "call_id": tc.get("id"),
                            "name": func.get("name"),
                            "arguments": func.get("arguments") if isinstance(func.get("arguments"), str) else json.dumps(func.get("arguments", {}))
                        })
                else:
                    input_messages.append({
                        "role": "assistant",
                        "content": entry.get("content", "")
                    })
            else:
                input_messages.append({
                    "role": entry["role"],
                    "content": entry.get("content", "")
                })

        # Add current user message if not empty
        added_user_message = False
        if message.strip():
            input_messages.append({
                "role": "user",
                "content": message
            })
            added_user_message = True

        # Convert tools to OpenAI function format
        openai_tools = []
        for t in tools:
            tool_def = t.to_openai_function()
            # Responses API uses a slightly different format
            openai_tools.append({
                "type": "function",
                "name": tool_def["function"]["name"],
                "description": tool_def["function"].get("description", ""),
                "parameters": tool_def["function"].get("parameters", {"type": "object", "properties": {}})
            })

        try:
            # Build API call kwargs
            api_kwargs = {
                "model": self.model_name,
                "input": input_messages,
                "tools": openai_tools,
            }

            # Add reasoning effort if specified
            if self.reasoning_effort:
                api_kwargs["reasoning"] = {"effort": self.reasoning_effort}

            response = self.client.responses.create(**api_kwargs)

            # Track token usage
            if hasattr(response, 'usage') and response.usage:
                self.total_input_tokens += getattr(response.usage, 'input_tokens', 0) or 0
                self.total_output_tokens += getattr(response.usage, 'output_tokens', 0) or 0

            # Extract reasoning, content, and function calls from response
            reasoning_text = ""
            output_text = ""
            function_calls = []

            if hasattr(response, 'output') and response.output:
                for item in response.output:
                    if hasattr(item, 'type'):
                        if item.type == 'reasoning' and hasattr(item, 'summary'):
                            # Extract reasoning summary
                            for summary_item in item.summary:
                                if hasattr(summary_item, 'text'):
                                    reasoning_text += summary_item.text + "\n"
                                elif isinstance(summary_item, dict) and 'text' in summary_item:
                                    reasoning_text += summary_item['text'] + "\n"
                        elif item.type == 'message' and hasattr(item, 'content'):
                            # Extract message content
                            for content_item in item.content:
                                if hasattr(content_item, 'text'):
                                    output_text += content_item.text
                                elif isinstance(content_item, dict) and 'text' in content_item:
                                    output_text += content_item['text']
                        elif item.type == 'function_call':
                            # Extract function call
                            call_id = getattr(item, 'call_id', None) or getattr(item, 'id', None)
                            name = getattr(item, 'name', '')
                            arguments = getattr(item, 'arguments', '{}')

                            # Parse arguments
                            try:
                                if isinstance(arguments, str):
                                    args = json.loads(arguments)
                                else:
                                    args = arguments
                            except json.JSONDecodeError:
                                args = {}

                            function_calls.append({
                                "id": call_id,
                                "name": name,
                                "function": {
                                    "name": name,
                                    "arguments": args,
                                },
                                "arguments": args,
                            })

            # Fallback to output_text if available
            if not output_text and hasattr(response, 'output_text'):
                output_text = response.output_text

            # Store and log reasoning if captured
            if reasoning_text.strip():
                self.last_thoughts = reasoning_text.strip()
                self.log("THINKING", self.last_thoughts, metadata={
                    "model": self.display_name if hasattr(self, 'display_name') else self.model_name,
                    "is_thinking": True,
                    "reasoning_effort": self.reasoning_effort,
                })
            else:
                self.last_thoughts = ""

            content = output_text or ""

            # Update history
            if added_user_message:
                self.history.append({"role": "user", "content": message})

            if function_calls:
                # Store assistant message with tool calls
                self.history.append({
                    "role": "assistant",
                    "content": content,
                    "tool_calls": [
                        {
                            "id": fc["id"],
                            "type": "function",
                            "function": {
                                "name": fc["name"],
                                "arguments": json.dumps(fc["arguments"]) if isinstance(fc["arguments"], dict) else fc["arguments"],
                            }
                        }
                        for fc in function_calls
                    ]
                })

                return {
                    "content": content,
                    "tool_calls": function_calls,
                }
            else:
                # No function calls, just content
                self.history.append({"role": "assistant", "content": content})
                return content

        except Exception as e:
            raise e

    def supports_tool_calling(self) -> bool:
        """Check if this model supports function/tool calling."""
        # Check if model name contains any of the tool-calling model identifiers
        model_lower = self.model_name.lower()
        return any(m in model_lower for m in TOOL_CALLING_MODELS)

    def _cleanup_dangling_tool_calls(self):
        """
        Clean up any dangling tool_calls in history.

        OpenAI requires every tool_call to have a corresponding tool result message.
        If the last assistant message has tool_calls without matching tool results,
        we need to add dummy tool results to keep the history valid.
        """
        if not self.history:
            return

        # Find the last assistant message with tool_calls
        last_assistant_idx = None
        for i in range(len(self.history) - 1, -1, -1):
            if self.history[i].get("role") == "assistant" and self.history[i].get("tool_calls"):
                last_assistant_idx = i
                break

        if last_assistant_idx is None:
            return

        # Get all tool_call IDs from that message
        tool_call_ids = set()
        for tc in self.history[last_assistant_idx].get("tool_calls", []):
            tool_call_ids.add(tc.get("id"))

        # Check which tool_call IDs have results in subsequent messages
        for i in range(last_assistant_idx + 1, len(self.history)):
            msg = self.history[i]
            if msg.get("role") == "tool":
                tool_call_ids.discard(msg.get("tool_call_id"))

        # Add dummy results for any missing tool_call IDs
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
        Send message with OpenAI function calling support.

        Args:
            message: The message to send (can be empty to continue after tool results)
            tools: List of ToolDefinition objects

        Returns:
            Dict with "content" and "tool_calls" if tools were called,
            otherwise plain string response
        """
        if self.use_responses_api:
            # Use Responses API with tool calling support
            return self._send_responses_api_with_tools(message, tools)

        # Clean up any dangling tool_calls from previous interrupted calls
        self._cleanup_dangling_tool_calls()

        # Convert tools to OpenAI format
        openai_tools = [t.to_openai_function() for t in tools]

        # Only add user message if not empty (empty = continuing after tool results)
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

            # Extract reasoning_content for thinking-mode models (e.g. DeepSeek V4)
            # The API requires it to be echoed back on subsequent requests.
            reasoning_content = getattr(assistant_message, "reasoning_content", None)

            # Check if there are tool calls
            if assistant_message.tool_calls:
                # Add assistant message with tool calls to history
                hist_entry = {
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
                }
                if reasoning_content:
                    hist_entry["reasoning_content"] = reasoning_content
                self.history.append(hist_entry)

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
                hist_entry = {"role": "assistant", "content": content}
                if reasoning_content:
                    hist_entry["reasoning_content"] = reasoning_content
                self.history.append(hist_entry)
                return content

        except Exception as e:
            # Clean up the user message if the call failed and we added one
            if added_user_message:
                self.history.pop()
            raise e

    def add_tool_result(self, tool_call_id: str, result: str):
        """
        Add a tool result to the conversation history.

        This should be called after executing a tool to provide the result
        back to the model.

        Args:
            tool_call_id: The ID of the tool call this result is for
            result: The result string from tool execution
        """
        self.history.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": result,
        })
