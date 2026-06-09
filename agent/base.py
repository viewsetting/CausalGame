import os
import sys
import re
import io
import contextlib
import traceback
import time
import ast
import requests
from datetime import datetime
from typing import List, Dict, Optional, Any, Union, TYPE_CHECKING

if TYPE_CHECKING:
    from agent.tools.definitions import ToolDefinition

# Colors for terminal output
class Colors:
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

class BaseHandler:
    def __init__(self, api_key: str, model_name: str, base_url: str = "http://localhost:17830", display_name: str = None):
        self.api_key = api_key
        self.model_name = model_name
        self.display_name = display_name or model_name  # User-facing name for logs
        self.base_url = base_url
        self.log_url = f"{base_url}/api/agent/log"
        self.mission_complete = False

        # Token usage tracking
        self.total_input_tokens = 0
        self.total_output_tokens = 0

        # Thinking/reasoning content (for models that support it)
        self.last_thoughts: str = ""
        
        # Initialize the execution environment
        # Note: canyon_client needs to be imported or passed in. 
        # For now, we'll assume the client is passed or imported in the subclass or main script, 
        # but to keep it self-contained as requested, we'll import it here if possible or define locals in a setup method.
        # The user wants specific "Base Handler" logic.
        # I will initialize basic locals here, but the specific client might need to be injected.
        # Let's import canyon_client here to replicate original behavior.
        
        # Import client from agent.client module
        try:
            from agent.client import CanyonClient
            self.client_class = CanyonClient
        except ImportError:
            try:
                from .client import CanyonClient
                self.client_class = CanyonClient
            except ImportError:
                print(f"{Colors.RED}[WARN] Could not import CanyonClient. 'client' must be injected manually.{Colors.RESET}")
                self.client_class = None

        self.locals = {
            "pd": __import__("pandas"),
            "np": __import__("numpy"),
            "print": print,
            "time": time
        }

        # Note: Client should be injected by run_agent.py with session registration
        # This is a fallback for standalone usage
        if self.client_class:
            self.locals["client"] = self.client_class(base_url, auto_register=False)

        print(f"{Colors.GREEN}[SYSTEM] Agent initialized. Client connected to {base_url}{Colors.RESET}")
        
    def log(self, type: str, content: str, metadata: Dict = None):
        try:
            payload = {
                "timestamp": datetime.now().isoformat(),
                "type": type,
                "content": content,
                "metadata": metadata or {}
            }
            # Get session_id from injected client if available (internal attribute)
            headers = {"Content-Type": "application/json"}
            client = self.locals.get("client")
            if client and hasattr(client, "_session_id") and client._session_id:
                headers["X-Session-ID"] = client._session_id
            requests.post(self.log_url, json=payload, headers=headers, timeout=10)
        except Exception as e:
            # Log failures to console for debugging
            print(f"{Colors.RED}[LOG ERROR] Failed to send log: {e}{Colors.RESET}")

    def run_code(self, code: str) -> str:
        """Executes python code and returns stdout/stderr."""
        if not code.strip():
            return "No code to execute."
        
        # Log Action
        self.log("ACTION", code)
        
        # Detect Deployments for special UI Event
        if "client.deploy_drone" in code:
            self.log("DEPLOYMENT", "Deploying Drones...", {"code": code})
            
        stdout = io.StringIO()
        stderr = io.StringIO()
        
        print(f"{Colors.YELLOW}[EXECUTING]{Colors.RESET}\n{code}")
        
        try:
            # Parse the code to check for valid syntax
            tree = ast.parse(code)
            last_stmt = tree.body[-1] if tree.body else None
            
            # If the last statement is an expression, we want to print its result
            if isinstance(last_stmt, ast.Expr):
                # Remove the last statement from the tree so we can exec the rest
                tree.body.pop()
                # Compile the rest
                exec_code = compile(tree, "<string>", "exec")
                # Compile the last expression as 'eval'
                eval_code = compile(ast.Expression(last_stmt.value), "<string>", "eval")
                
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    exec(exec_code, self.locals, self.locals) # Use self.locals for globals and locals
                    result = eval(eval_code, self.locals, self.locals) # Use self.locals for globals and locals
                    if result is not None:
                        print(result)
            else:
                # Normal execution
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    exec(code, self.locals, self.locals) # Use self.locals for globals and locals
                    
            output = stdout.getvalue()
            error = stderr.getvalue()
        except Exception:
            output = stdout.getvalue()
            error = traceback.format_exc()
            self.log("ERROR", error)
            
        result_msg = ""
        if output:
            result_msg += f"OUTPUT:\n{output}\n"
        if error:
            result_msg += f"ERRORS:\n{error}\n"
        if not result_msg:
            result_msg = "Code executed successfully (no output)."
            
        print(f"{Colors.CYAN}[RESULT]{Colors.RESET}\n{result_msg.strip()}")
        return result_msg

    def strip_thinking_tags(self, text: str) -> str:
        """Remove <think>...</think> tags from model output.

        Some models (e.g., MiniMax M2) output thinking process in these tags,
        which can interfere with code extraction.
        """
        # Remove <think>...</think> blocks (including nested content)
        cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
        return cleaned.strip()

    def extract_code(self, text: str) -> str:
        """Extracts the last python code block from the response."""
        matches = re.findall(r"```python\s*(.*?)```", text, re.DOTALL)
        if matches:
            return matches[-1].strip() # Return the last block
        return None

    def send_message(self, message: str) -> str:
        """Abstract method to send message to LLM."""
        raise NotImplementedError("Subclasses must implement send_message")

    def send_message_with_tools(
        self,
        message: str,
        tools: List["ToolDefinition"],
    ) -> Union[str, Dict[str, Any]]:
        """
        Send message with tool definitions and handle tool calls.

        This method is optional - subclasses that support function/tool calling
        should override this. The default implementation falls back to send_message.

        Args:
            message: The message to send
            tools: List of ToolDefinition objects available for the LLM to use

        Returns:
            Either a plain string response, or a dict containing:
            - "content": The text response
            - "tool_calls": List of tool call requests from the LLM
        """
        # Default: fall back to regular send_message (no tool calling)
        return self.send_message(message)

    def supports_tool_calling(self) -> bool:
        """
        Check if this handler supports native tool/function calling.

        Subclasses that implement send_message_with_tools should override
        this to return True.

        Returns:
            True if native tool calling is supported, False otherwise
        """
        return False

    def get_token_usage(self) -> Dict[str, int]:
        """Get token usage statistics."""
        return {
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "total_tokens": self.total_input_tokens + self.total_output_tokens,
        }

    def export_conversation_history(self) -> List[Dict[str, str]]:
        """Export conversation history in a standard JSON-serializable format.

        Returns:
            List of {"role": "user"|"assistant"|"system", "content": "..."}
        """
        # Default implementation for handlers that use standard dict format
        if hasattr(self, 'history') and isinstance(self.history, list):
            return [
                {"role": msg.get("role", "user"), "content": msg.get("content", "")}
                for msg in self.history
                if isinstance(msg, dict)
            ]
        return []

    def import_conversation_history(self, history: List[Dict[str, str]]) -> None:
        """Import conversation history from saved format.

        Args:
            history: List of {"role": "user"|"assistant"|"system", "content": "..."}
        """
        # Default implementation for handlers that use standard dict format
        if hasattr(self, 'history'):
            self.history = [
                {"role": msg["role"], "content": msg["content"]}
                for msg in history
            ]

    def save_conversation_to_backend(self) -> bool:
        """Save current conversation history to backend for resume support.

        Returns:
            True if save successful, False otherwise
        """
        try:
            client = self.locals.get("client")
            if client and hasattr(client, "save_conversation_history"):
                history = self.export_conversation_history()
                client.save_conversation_history(history)
                return True
        except Exception as e:
            print(f"{Colors.RED}[WARN] Failed to save conversation history: {e}{Colors.RESET}")
        return False

    def load_conversation_from_backend(self) -> bool:
        """Load conversation history from backend for resume.

        Returns:
            True if load successful, False otherwise
        """
        try:
            client = self.locals.get("client")
            if client and hasattr(client, "get_conversation_history"):
                result = client.get_conversation_history()
                history = result.get("conversation_history", [])
                if history:
                    self.import_conversation_history(history)
                    print(f"{Colors.GREEN}[SYSTEM] Loaded {len(history)} messages from saved conversation{Colors.RESET}")
                    return True
        except Exception as e:
            print(f"{Colors.RED}[WARN] Failed to load conversation history: {e}{Colors.RESET}")
        return False

    def report_token_usage(self) -> bool:
        """Report current token usage to backend for real-time display.

        Returns:
            True if report successful, False otherwise
        """
        try:
            client = self.locals.get("client")
            if client and hasattr(client, "update_token_usage"):
                client.update_token_usage(
                    input_tokens=self.total_input_tokens,
                    output_tokens=self.total_output_tokens
                )
                return True
        except Exception as e:
            # Don't log every failure to avoid cluttering output
            pass
        return False

    def step(self, user_input: str = None, depth: int = 0, log_type: str = "THOUGHT"):
        """Single step in the conversation loop with Retry Logic.

        Args:
            user_input: Input message to send to the model
            depth: Recursion depth counter
            log_type: Type of log entry to create (THOUGHT or REPORT)
        """
        if depth > 50:
            print(f"{Colors.RED}[WARN] Max recursion depth reached. Stopping conversation chain.{Colors.RESET}")
            return

        if self.mission_complete:
            print(f"{Colors.GREEN}[SYSTEM] Mission Accomplished. Halting Agent.{Colors.RESET}")
            return

        msg = user_input if user_input else "Proceed."

        while True:
            # Smart delay handling: 5, 10, 20, 40, 80, 80...
            if not hasattr(self, 'current_delay'):
                self.current_delay = 5
            
            try:
                content = self.send_message(msg)
                # Reset delay on success
                self.current_delay = 5

                print(f"\n{Colors.BOLD}[{self.display_name}]{Colors.RESET}\n{content}")
                
                # Get UTC+4 Time
                from datetime import timedelta
                utc_plus_4 = datetime.utcnow() + timedelta(hours=4)
                time_str = utc_plus_4.strftime("%H:%M:%S")
                
                # Log with Timestamp and Model Metadata
                # Append time to content as requested
                log_content = f"{content} [{time_str} UTC+4]"
                self.log(log_type, log_content, metadata={"model": self.display_name})
                
                cleaned_content = self.strip_thinking_tags(content)
                code = self.extract_code(cleaned_content)
                if code:
                    execution_result = self.run_code(code)
                    
                    # Check for successful submission in variables
                    for val in self.locals.values():
                        if isinstance(val, dict) and val.get("status") == "EVALUATION_COMPLETE":
                            self.mission_complete = True
                            break
                            
                    # Fallback: Check output for success status string
                    if "EVALUATION_COMPLETE" in execution_result:
                        self.mission_complete = True

                    # Auto-feed result back to the model (Recursive step)
                    if not self.mission_complete:
                        self.step(user_input=f"Execution Result:\n{execution_result}", depth=depth+1)

                # Save conversation history and report token usage after each successful step
                if depth == 0:  # Only at top level to avoid excessive API calls
                    self.save_conversation_to_backend()
                    self.report_token_usage()

                return # Success
                
            except Exception as e:
                is_rate_limit = "429" in str(e) or "ResourceExhausted" in str(e)
                if is_rate_limit:
                    print(f"{Colors.RED}[WARN] Rate Limit Hit. Waiting {self.current_delay}s...{Colors.RESET}")
                    time.sleep(self.current_delay)
                    self.current_delay = min(self.current_delay * 2, 80)
                else:
                    print(f"{Colors.RED}[ERROR] API Call failed: {e}{Colors.RESET}")
                    # Allow break on fatal error to avoid infinite loop
                    return
