import json
from typing import List, Dict, Any, Union, TYPE_CHECKING
from google import genai
from google.genai import types
from .base import BaseHandler

if TYPE_CHECKING:
    from agent.tools.definitions import ToolDefinition


class GeminiHandler(BaseHandler):
    def __init__(
        self,
        api_key: str,
        model_name: str = "gemini-2.0-flash",
        base_url: str = "http://localhost:17830",
        system_instruction: str = None,
        enable_thinking: bool = True,
    ):
        super().__init__(api_key, model_name, base_url)

        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name
        self.system_instruction = system_instruction

        # Check if this is a Gemini 3 thinking model
        self.is_thinking_model = "gemini-3" in model_name
        self.enable_thinking = enable_thinking and self.is_thinking_model
        self.last_thoughts: str = ""  # Store last thinking content for logging/display

        # For thinking models with thinking enabled, we manage history manually
        # to avoid "Corrupted thought signature" errors
        if self.is_thinking_model and self.enable_thinking:
            # Manual history management mode
            self.history = []
            self.chat = None  # Don't use chat API
            self._init_config_with_thinking()
        else:
            # Standard chat mode
            self.history = None
            self._init_chat(system_instruction)

    def _init_config_with_thinking(self):
        """Initialize config for thinking mode with manual history management."""
        config_kwargs = {}
        if self.system_instruction:
            config_kwargs["system_instruction"] = self.system_instruction

        # Enable thinking
        config_kwargs["thinking_config"] = types.ThinkingConfig(
            include_thoughts=True
        )

        self.config = types.GenerateContentConfig(**config_kwargs)

    def _init_chat(self, system_instruction: str = None):
        """Initialize standard chat mode."""
        config_kwargs = {}
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction

        # For Gemini 3 without thinking, explicitly disable thoughts
        if self.is_thinking_model:
            config_kwargs["thinking_config"] = types.ThinkingConfig(
                include_thoughts=False
            )

        self.config = types.GenerateContentConfig(**config_kwargs) if config_kwargs else None

        self.chat = self.client.chats.create(
            model=self.model_name,
            config=self.config
        )

    def send_message(self, message: str) -> str:
        if self.is_thinking_model and self.enable_thinking:
            return self._send_message_with_thinking(message)
        else:
            return self._send_message_chat(message)

    def _send_message_with_thinking(self, message: str) -> str:
        """Send message with thinking enabled, manually managing history."""
        # Add user message to history
        self.history.append(
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=message)]
            )
        )

        # Generate response with full history
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=self.history,
            config=self.config
        )

        # Extract text and thought parts
        text_parts = []
        thought_parts = []

        for part in response.candidates[0].content.parts:
            if hasattr(part, 'thought') and part.thought:
                # This is a thinking part
                if hasattr(part, 'text') and part.text:
                    thought_parts.append(part.text)
            elif hasattr(part, 'text') and part.text:
                # Regular text part
                text_parts.append(part.text)

        # Add ONLY text parts to history (exclude thought parts to avoid signature issues)
        if text_parts:
            self.history.append(
                types.Content(
                    role="model",
                    parts=[types.Part.from_text(text=t) for t in text_parts]
                )
            )

        # Return combined text
        result_text = ''.join(text_parts)

        # Store thoughts for logging/display
        if thought_parts:
            self.last_thoughts = '\n'.join(thought_parts)
            # Log thoughts separately with metadata for frontend display
            self.log("THINKING", self.last_thoughts, metadata={
                "model": self.display_name if hasattr(self, 'display_name') else self.model_name,
                "is_thinking": True,
            })
        else:
            self.last_thoughts = ""

        # Track token usage
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            self.total_input_tokens += getattr(response.usage_metadata, 'prompt_token_count', 0) or 0
            self.total_output_tokens += getattr(response.usage_metadata, 'candidates_token_count', 0) or 0

        return result_text if result_text else response.text

    def _send_message_chat(self, message: str) -> str:
        """Send message using standard chat API."""
        response = self.chat.send_message(message)
        # Extract text parts only, ignoring non-text parts like thought_signature
        text_parts = []
        for part in response.candidates[0].content.parts:
            if hasattr(part, 'text') and part.text:
                text_parts.append(part.text)

        # Track token usage
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            self.total_input_tokens += getattr(response.usage_metadata, 'prompt_token_count', 0) or 0
            self.total_output_tokens += getattr(response.usage_metadata, 'candidates_token_count', 0) or 0

        return ''.join(text_parts) if text_parts else response.text

    def get_thoughts(self) -> list:
        """Get the last response's thinking parts (if thinking is enabled)."""
        # This could be extended to store and return thoughts
        return []

    def export_conversation_history(self) -> List[Dict[str, str]]:
        """Export conversation history in a standard JSON-serializable format.

        Handles Gemini's special Content objects when thinking mode is enabled.

        Returns:
            List of {"role": "user"|"assistant"|"system", "content": "..."}
        """
        if not hasattr(self, 'history') or self.history is None:
            # Using chat API mode - history is managed by chat object
            # Cannot easily export in this case
            return []

        result = []
        for item in self.history:
            if isinstance(item, dict):
                # Standard dict format
                result.append({
                    "role": item.get("role", "user"),
                    "content": item.get("content", "")
                })
            elif hasattr(item, 'role') and hasattr(item, 'parts'):
                # Gemini Content object
                role = "assistant" if item.role == "model" else item.role
                content_parts = []
                for part in item.parts:
                    if hasattr(part, 'text') and part.text:
                        content_parts.append(part.text)
                if content_parts:
                    result.append({
                        "role": role,
                        "content": "\n".join(content_parts)
                    })
        return result

    def import_conversation_history(self, history: List[Dict[str, str]]) -> None:
        """Import conversation history from saved format.

        Recreates Gemini Content objects if in thinking mode.

        Args:
            history: List of {"role": "user"|"assistant"|"system", "content": "..."}
        """
        if self.is_thinking_model and self.enable_thinking:
            # Thinking mode: need to recreate Content objects
            self.history = []
            for msg in history:
                role = "model" if msg["role"] == "assistant" else msg["role"]
                self.history.append(
                    types.Content(
                        role=role,
                        parts=[types.Part.from_text(text=msg["content"])]
                    )
                )
        else:
            # Standard mode - but we use chat API, so we need to recreate the chat
            # with the history. This is tricky for Gemini chat API.
            # For now, we'll skip resume support for non-thinking Gemini models.
            pass

    def supports_tool_calling(self) -> bool:
        """Check if this model supports tool calling."""
        # Most Gemini models support function calling
        return True

    def _cleanup_dangling_function_calls(self):
        """
        Clean up any dangling function_call parts in history.

        If there are pending function_calls without function_responses,
        add dummy responses to keep the history valid.
        """
        # Check if there are pending function calls from last response
        if not hasattr(self, '_last_response_parts') or not self._last_response_parts:
            return

        # Find function_call parts that might need cleanup
        pending_function_calls = []
        for part in self._last_response_parts:
            if hasattr(part, 'function_call') and part.function_call:
                pending_function_calls.append(part.function_call.name)

        if not pending_function_calls:
            return

        # Add dummy function_responses for pending calls
        history_target = self.history if (self.is_thinking_model and self.enable_thinking) else getattr(self, '_tool_history', [])

        for func_name in pending_function_calls:
            function_response = types.Part.from_function_response(
                name=func_name,
                response={"error": "Tool execution was interrupted. Please try again."}
            )

            if self.is_thinking_model and self.enable_thinking:
                self.history.append(
                    types.Content(
                        role="user",
                        parts=[function_response]
                    )
                )
            else:
                if hasattr(self, '_tool_history'):
                    self._tool_history.append(
                        types.Content(
                            role="user",
                            parts=[function_response]
                        )
                    )

        # Clear the pending parts
        self._last_response_parts = None

    def send_message_with_tools(
        self,
        message: str,
        tools: List["ToolDefinition"],
    ) -> Union[str, Dict[str, Any]]:
        """
        Send message with Gemini function calling support.

        Args:
            message: The message to send (can be empty to continue after tool results)
            tools: List of ToolDefinition objects

        Returns:
            Dict with "content" and "tool_calls" if tools were called,
            otherwise plain string response
        """
        # Clean up any dangling function_calls from previous interrupted calls
        self._cleanup_dangling_function_calls()

        # Convert tools to Gemini format
        gemini_tools = []
        for t in tools:
            gemini_tools.append(types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(
                        name=t.name,
                        description=t.description,
                        parameters=t.to_json_schema(),
                    )
                ]
            ))

        # Build contents for the request
        if self.is_thinking_model and self.enable_thinking:
            # Manual history management mode
            if message.strip():
                self.history.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=message)]
                    )
                )

            # Create config with tools
            config_kwargs = {}
            if self.system_instruction:
                config_kwargs["system_instruction"] = self.system_instruction
            config_kwargs["thinking_config"] = types.ThinkingConfig(include_thoughts=True)
            config_kwargs["tools"] = gemini_tools

            config = types.GenerateContentConfig(**config_kwargs)

            response = self.client.models.generate_content(
                model=self.model_name,
                contents=self.history,
                config=config
            )
        else:
            # Standard chat mode - need to use generate_content directly for tools
            # Build history from chat if needed
            if not hasattr(self, '_tool_history'):
                self._tool_history = []
                if self.system_instruction:
                    # System instruction handled in config
                    pass

            if message.strip():
                self._tool_history.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=message)]
                    )
                )

            # Create config with tools
            config_kwargs = {}
            if self.system_instruction:
                config_kwargs["system_instruction"] = self.system_instruction
            if self.is_thinking_model:
                config_kwargs["thinking_config"] = types.ThinkingConfig(include_thoughts=False)
            config_kwargs["tools"] = gemini_tools

            config = types.GenerateContentConfig(**config_kwargs)

            response = self.client.models.generate_content(
                model=self.model_name,
                contents=self._tool_history,
                config=config
            )

        # Track token usage
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            self.total_input_tokens += getattr(response.usage_metadata, 'prompt_token_count', 0) or 0
            self.total_output_tokens += getattr(response.usage_metadata, 'candidates_token_count', 0) or 0

        # Parse response
        text_parts = []
        thought_parts = []
        tool_calls = []

        for part in response.candidates[0].content.parts:
            if hasattr(part, 'function_call') and part.function_call:
                # This is a function call
                fc = part.function_call
                tool_calls.append({
                    "id": fc.name,  # Gemini doesn't have IDs, use name
                    "name": fc.name,
                    "function": {
                        "name": fc.name,
                        "arguments": dict(fc.args) if fc.args else {},
                    },
                    "arguments": dict(fc.args) if fc.args else {},
                })
            elif hasattr(part, 'text') and part.text:
                if hasattr(part, 'thought') and part.thought:
                    # This is a thinking part
                    thought_parts.append(part.text)
                else:
                    # Regular text part
                    text_parts.append(part.text)

        content = ''.join(text_parts)

        # Store and log thoughts
        if thought_parts:
            self.last_thoughts = '\n'.join(thought_parts)
            self.log("THINKING", self.last_thoughts, metadata={
                "model": self.display_name if hasattr(self, 'display_name') else self.model_name,
                "is_thinking": True,
            })
        else:
            self.last_thoughts = ""

        # Add assistant response to history
        if self.is_thinking_model and self.enable_thinking:
            # Store the raw response parts for tool result handling
            self._last_response_parts = response.candidates[0].content.parts
            if text_parts:
                self.history.append(
                    types.Content(
                        role="model",
                        parts=[types.Part.from_text(text=t) for t in text_parts]
                    )
                )
        else:
            self._last_response_parts = response.candidates[0].content.parts
            if text_parts:
                self._tool_history.append(
                    types.Content(
                        role="model",
                        parts=[types.Part.from_text(text=t) for t in text_parts]
                    )
                )

        if tool_calls:
            return {
                "content": content,
                "tool_calls": tool_calls,
            }
        else:
            return content

    def add_tool_result(self, tool_call_id: str, result: str):
        """
        Add a tool result to the conversation history.

        For Gemini, tool_call_id is the function name.

        Args:
            tool_call_id: The function name (Gemini doesn't use IDs)
            result: The result string from tool execution
        """
        # Create function response part
        function_response = types.Part.from_function_response(
            name=tool_call_id,
            response={"result": result}
        )

        if self.is_thinking_model and self.enable_thinking:
            # Add to manual history
            self.history.append(
                types.Content(
                    role="user",
                    parts=[function_response]
                )
            )
        else:
            # Add to tool history
            if not hasattr(self, '_tool_history'):
                self._tool_history = []
            self._tool_history.append(
                types.Content(
                    role="user",
                    parts=[function_response]
                )
            )
