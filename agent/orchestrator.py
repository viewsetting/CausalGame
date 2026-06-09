"""
Agent Orchestrator for CausalGame.

This module provides the unified orchestrator that manages execution modes:
- HYBRID: Tool Calling for API operations + Code execution for analysis
- LEGACY: Full code execution (backward compatible)

The orchestrator receives the client explicitly - no hidden injection.
"""

import re
import json
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, Optional, List, TYPE_CHECKING

from agent.tools.definitions import CANYON_TOOLS, ToolDefinition, get_all_openai_tools
from agent.tools.executor import APIToolExecutor, ToolResult, ToolResultStatus
from agent.sandbox.context import AnalysisContext, AnalysisResult
from agent.sandbox.workspace import SessionWorkspace
from config import config

if TYPE_CHECKING:
    from agent.base import BaseHandler
    from agent.client import CanyonClient

# ANSI color codes for console output
class Colors:
    BOLD = "\033[1m"
    RESET = "\033[0m"
    GREEN = "\033[92m"
    CYAN = "\033[96m"


class ExecutionMode(Enum):
    """Execution mode for the orchestrator."""
    HYBRID = "hybrid"   # Tool Calling + Analysis sandbox
    LEGACY = "legacy"   # Full code execution (backward compatible)


@dataclass
class ToolCall:
    """Represents a parsed tool call from LLM response."""
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class CodeBlock:
    """Represents a code block extracted from LLM response."""
    code: str
    language: str = "python"


@dataclass
class StepResult:
    """
    Result from a single orchestrator step.

    Attributes:
        response: Raw LLM response text
        tool_calls: List of tool calls made
        tool_results: Results from tool executions
        code_blocks: Code blocks that were executed
        analysis_results: Results from analysis code execution
        mission_complete: Whether the mission is finished
    """
    response: str
    tool_calls: List[ToolCall] = field(default_factory=list)
    tool_results: List[ToolResult] = field(default_factory=list)
    code_blocks: List[CodeBlock] = field(default_factory=list)
    analysis_results: List[AnalysisResult] = field(default_factory=list)
    mission_complete: bool = False

    def get_feedback_message(self) -> str:
        """Generate feedback message for the LLM."""
        parts = []

        # Tool results
        for result in self.tool_results:
            parts.append(f"[{result.tool_name}] {result.to_string()}")

        # Analysis results
        for result in self.analysis_results:
            parts.append(f"[Analysis] {result.to_string()}")

        if not parts:
            return ""

        return "\n\n".join(parts)


class AgentOrchestrator:
    """
    Unified orchestrator for agent execution.

    Manages:
    - Execution mode (HYBRID vs LEGACY)
    - Tool calling via APIToolExecutor
    - Analysis code via AnalysisContext
    - Feedback loop with LLM

    The client is explicitly passed in - no hidden injection.
    """

    # Default max turns for each mode (used when no deployment_budget)
    DEFAULT_MAX_TURNS_HYBRID = 30
    DEFAULT_MAX_TURNS_LEGACY = config.agent.execution.max_turns

    # Extra turns beyond deployment calls for analysis/submission
    EXTRA_TURNS = 10

    def __init__(
        self,
        handler: "BaseHandler",
        client: "CanyonClient",
        mode: ExecutionMode = ExecutionMode.HYBRID,
        session_id: Optional[str] = None,
        max_turns: Optional[int] = None,
        deployment_budget: Optional[int] = None,
    ):
        """
        Initialize the orchestrator.

        Args:
            handler: The LLM handler (BaseHandler subclass)
            client: The CanyonClient for API calls (explicit, not injected)
            mode: Execution mode (HYBRID or LEGACY)
            session_id: Session ID for workspace isolation (HYBRID mode only)
            max_turns: Maximum turns allowed (if None, calculated from deployment_budget)
            deployment_budget: Max deploy calls allowed (stage1_deployment_budget from experiment)
        """
        self.handler = handler
        self.client = client
        self.mode = mode
        self.session_id = session_id
        self.mission_complete = False

        # Deployment budget = max deploy() calls (from experiment config)
        self.deployment_budget = deployment_budget

        # Turn tracking - calculate max_turns based on deployment_budget if not specified
        if max_turns is not None:
            self.max_turns = max_turns
        elif deployment_budget is not None and mode == ExecutionMode.HYBRID:
            # max_turns = deploy calls + extra turns for analysis/submission
            self.max_turns = deployment_budget + self.EXTRA_TURNS
        else:
            self.max_turns = (
                self.DEFAULT_MAX_TURNS_HYBRID
                if mode == ExecutionMode.HYBRID
                else self.DEFAULT_MAX_TURNS_LEGACY
            )
        self.current_turn = 0

        # Track exploration progress for early submission guard
        self.deployments_made = 0

        # Grace period tracking (when resources exhausted, agent gets extra turns to submit)
        self.resources_exhausted = False
        self.grace_turns_used = 0
        self.max_grace_turns = 3

        # Track last successful design for auto-submit fallback
        self.last_successful_design: Optional[Dict[str, int]] = None
        self.last_successful_survival_rate: float = 0.0

        # Create tool executor with explicit client
        self.api_executor = APIToolExecutor(client)

        # Filter tools based on experiment capabilities
        self._available_tools = self._get_available_tools()

        # HYBRID mode: Create workspace sandbox for file isolation
        self.workspace: Optional[SessionWorkspace] = None
        self._workspace_instructions_sent = False
        if mode == ExecutionMode.HYBRID and session_id:
            self.workspace = SessionWorkspace(session_id)

        # Create analysis sandbox with data provider and optional workspace
        self.analysis = AnalysisContext(
            data_provider=lambda: {
                "history": client.get_history(),
                "status": client.get_status(),
            },
            workspace=self.workspace,
        )

        # For legacy mode compatibility
        self._legacy_locals = {
            "pd": __import__("pandas"),
            "np": __import__("numpy"),
            "print": print,
            "time": __import__("time"),
            "client": client,  # Explicit, not hidden
        }

    def step(self, context: str, log_type: str = "THOUGHT") -> StepResult:
        """
        Execute a single step in the agent loop.

        Args:
            context: Context/prompt to send to the LLM
            log_type: Type of log entry (THOUGHT or REPORT)

        Returns:
            StepResult with all execution details
        """
        # Increment turn counter
        self.current_turn += 1

        # Sync current_turn to backend
        try:
            self.client.update_session_config(current_turn=self.current_turn)
        except Exception:
            pass  # Non-critical

        if self.mode == ExecutionMode.LEGACY:
            return self._step_legacy(context, log_type)
        else:
            return self._step_hybrid(context, log_type)

    def _get_turn_info(self) -> str:
        """Generate turn information and warnings for the agent."""
        turns_remaining = self.max_turns - self.current_turn

        # Get actual deployment usage from backend
        try:
            status = self.client.get_status()
            deployments_used = status.get('deployments_used', 0)
            deployments_remaining = status.get('deployments_remaining', self.deployment_budget)
            drones_remaining = status.get('drones_remaining', 0)
        except Exception:
            deployments_used = self.deployments_made
            deployments_remaining = (self.deployment_budget - self.deployments_made) if self.deployment_budget else None
            drones_remaining = None

        # Build info line with deployment budget if available
        if self.deployment_budget is not None:
            info = f"[Turn {self.current_turn}/{self.max_turns} | Deployments: {deployments_used}/{self.deployment_budget} used, {deployments_remaining} remaining]"
        else:
            info = f"[Turn {self.current_turn}/{self.max_turns}]"

        # Check if resources exhausted (grace period)
        if self.resources_exhausted:
            grace_remaining = self.max_grace_turns - self.grace_turns_used
            return (
                f"{info}\n"
                f"🚨🚨🚨 RESOURCES EXHAUSTED! GRACE PERIOD: {grace_remaining} turn(s) remaining!\n"
                f"You MUST call `submit_final_design` NOW or the system will auto-submit for you!"
            )

        # Check if about to exhaust resources
        if drones_remaining is not None and drones_remaining <= 0:
            return f"{info}\n🚨 ALL DRONES DEPLOYED! Submit your final design NOW!"

        if turns_remaining <= 0:
            return f"{info}\n⚠️ FINAL TURN! You MUST submit your final design NOW!"
        elif turns_remaining <= 2:
            return f"{info}\n🚨 CRITICAL: Only {turns_remaining} turn(s) left! Submit your final design IMMEDIATELY!"
        elif turns_remaining <= 5:
            return f"{info}\n⚠️ WARNING: Only {turns_remaining} turns remaining. Prepare to submit your final design."

        return info

    def _get_workspace_instructions(self) -> str:
        """Generate workspace file operation instructions for the agent."""
        if not self.workspace:
            return ""

        return f"""
[WORKSPACE FILE OPERATIONS]
You have access to an isolated workspace directory for file operations.
Workspace path: {self.workspace.get_workspace_path()}

Available functions in your Python code blocks:
- `open(path, mode)` - Read/write files (e.g., `open("analysis.csv", "w")`)
- `listdir(subdir=".")` - List files in directory
- `file_exists(path)` - Check if file exists
- `workspace_path` - String variable with workspace root path

Example usage:
```python
# Save analysis results
with open("results.csv", "w") as f:
    df.to_csv(f, index=False)

# Read saved data
with open("results.csv", "r") as f:
    saved_df = pd.read_csv(f)

# List files
files = listdir()
print(files)  # ['results.csv', ...]
```

Note: Only relative paths within workspace are allowed. Absolute paths or path traversal (../) will be blocked.
"""

    def _step_hybrid(self, context: str, log_type: str) -> StepResult:
        """
        Hybrid mode: Tool Calling for API, Code execution for analysis.

        The LLM can:
        1. Call tools (get_status, deploy_drone, etc.) via function calling
        2. Write Python code for data analysis

        This keeps API operations explicit while allowing flexible analysis.
        """
        result = StepResult(response="")

        # Inject workspace instructions on first call (if workspace is available)
        if self.workspace and not self._workspace_instructions_sent:
            workspace_info = self._get_workspace_instructions()
            context = workspace_info + "\n" + context
            self._workspace_instructions_sent = True

        # Prepend turn information and warnings
        turn_info = self._get_turn_info()
        context = f"{turn_info}\n\n{context}"

        # Add ReAct instruction for tool calling
        react_instruction = (
            "\n\n[IMPORTANT: ReAct Format]\n"
            "Before calling any tool, you MUST first explain your reasoning:\n"
            "1. What did you observe from previous results?\n"
            "2. What is your hypothesis?\n"
            "3. Why are you taking this action?\n"
            "Output your THOUGHT first, then call the tool."
        )
        context = context + react_instruction

        # Check if handler supports tool calling
        if not hasattr(self.handler, 'send_message_with_tools'):
            # Fall back to legacy mode
            return self._step_legacy(context, log_type)

        # Send message with tools and handle tool call loop
        try:
            response = self.handler.send_message_with_tools(
                context,
                tools=self._available_tools,
            )

            # Tool calling loop - keep processing until no more tool calls
            max_tool_iterations = config.agent.execution.max_tool_iterations_per_turn
            iteration = 0

            while iteration < max_tool_iterations:
                iteration += 1

                # Parse response based on handler type
                if isinstance(response, dict):
                    # Structured response from tool-calling handler
                    content = response.get("content", "")
                    raw_tool_calls = response.get("tool_calls", [])

                    # Log any content/thinking from the LLM (like legacy mode)
                    # Use stripped content to avoid invisible unicode chars (e.g., zero-width spaces)
                    stripped_content = content.strip() if content else ""
                    # Also check for visible alphanumeric/punctuation chars (not just whitespace)
                    has_visible = any(c.isalnum() or c in '.,!?;:()[]{}-_+=' for c in stripped_content)

                    if stripped_content and has_visible:
                        result.response = stripped_content
                        # Print to console like legacy mode
                        display_name = getattr(self.handler, 'display_name', 'Agent')
                        print(f"\n{Colors.BOLD}[{display_name}]{Colors.RESET}\n{stripped_content}")
                        # Log with timestamp like legacy mode
                        utc_plus_4 = datetime.utcnow() + timedelta(hours=4)
                        time_str = utc_plus_4.strftime("%H:%M:%S")
                        log_content = f"{stripped_content} [{time_str} UTC+4]"
                        self.handler.log(log_type, log_content, metadata={"model": display_name})
                    elif raw_tool_calls:
                        # Model returned tool calls without explanation text
                        # Generate a synthetic thought based on tool calls
                        display_name = getattr(self.handler, 'display_name', 'Agent')
                        tool_names = [tc.get("function", {}).get("name", tc.get("name", "unknown")) for tc in raw_tool_calls]
                        synthetic_thought = f"Executing: {', '.join(tool_names)}"
                        print(f"\n{Colors.BOLD}[{display_name}]{Colors.RESET}\n{synthetic_thought}")
                        utc_plus_4 = datetime.utcnow() + timedelta(hours=4)
                        time_str = utc_plus_4.strftime("%H:%M:%S")
                        self.handler.log(log_type, f"{synthetic_thought} [{time_str} UTC+4]", metadata={
                            "model": display_name,
                            "synthetic": True,
                        })

                    if not raw_tool_calls:
                        # No more tool calls, we're done
                        break

                    # Process each tool call
                    for tc in raw_tool_calls:
                        tool_call = ToolCall(
                            id=tc.get("id", ""),
                            name=tc.get("function", {}).get("name", tc.get("name", "")),
                            arguments=self._parse_arguments(tc),
                        )
                        result.tool_calls.append(tool_call)

                        # Log tool call as ACTION (for frontend display)
                        self._log_tool_call(tool_call)

                        # Guard against early submission without exploration
                        if tool_call.name == "submit_final_design":
                            if self.deployments_made == 0:
                                # Reject early submission
                                tool_result = ToolResult(
                                    tool_name=tool_call.name,
                                    status=ToolResultStatus.ERROR,
                                    error=(
                                        "Cannot submit final design without exploration! "
                                        "You must first use 'deploy_drone' to test different designs. "
                                        "Analyze the data before submitting."
                                    ),
                                )
                                self.handler.log(
                                    "ERROR",
                                    f"Early submission rejected: No deployments made yet. "
                                    f"Agent must explore before submitting.",
                                    metadata={"reason": "early_submission_guard"}
                                )
                            else:
                                # Allow submission
                                tool_result = self.api_executor.execute(
                                    tool_call.name,
                                    tool_call.arguments,
                                )
                        else:
                            # Execute tool normally
                            tool_result = self.api_executor.execute(
                                tool_call.name,
                                tool_call.arguments,
                            )

                            # Track exploration progress
                            if tool_call.name == "deploy_drone" and tool_result.status == ToolResultStatus.SUCCESS:
                                self.deployments_made += 1

                        result.tool_results.append(tool_result)

                        # Log tool result
                        self._log_tool_result(tool_call, tool_result)

                        # Send tool result back to LLM
                        if hasattr(self.handler, 'add_tool_result'):
                            result_str = tool_result.to_string()

                            # ReAct: Force analysis after deploy_drone
                            if tool_call.name == "deploy_drone" and tool_result.status == ToolResultStatus.SUCCESS:
                                result_str += (
                                    "\n\n[ANALYZE THIS RESULT]"
                                    "\n1. What is the survival rate? Does it match your expectation?"
                                    "\n2. What does this tell you about the design parameters?"
                                    "\n3. What should you test next to validate or refine your hypothesis?"
                                )

                            self.handler.add_tool_result(
                                tool_call.id,
                                result_str
                            )

                        # Check for mission complete
                        if tool_result.status == ToolResultStatus.SUCCESS:
                            if isinstance(tool_result.data, dict):
                                if tool_result.data.get("status") == "EVALUATION_COMPLETE":
                                    result.mission_complete = True
                                    self.mission_complete = True
                                    # Sync final_turn to backend (excludes reflection turns)
                                    try:
                                        self.client.update_session_config(
                                            final_turn=self.current_turn
                                        )
                                    except Exception:
                                        pass  # Non-critical

                    # If we processed tool calls, get the next response from LLM
                    if raw_tool_calls and hasattr(self.handler, 'add_tool_result'):
                        # Check if we're about to exceed max iterations
                        if iteration >= max_tool_iterations:
                            # Don't request more - we'll exit the loop
                            # The tool results are already added, so history is valid
                            self.handler.log(
                                "WARNING",
                                f"Max tool iterations ({max_tool_iterations}) reached. Stopping tool call loop.",
                                metadata={"iteration": iteration}
                            )
                            break

                        # Continue the conversation to get LLM's response after tool results
                        try:
                            response = self.handler.send_message_with_tools(
                                "",  # Empty message - just continue after tool results
                                tools=self._available_tools,
                            )
                        except Exception as e:
                            # If continuation fails, log and break cleanly
                            # History is valid since all previous tool_results were added
                            self.handler.log(
                                "ERROR",
                                f"Failed to continue after tool results: {e}",
                                metadata={"error": str(e)}
                            )
                            break
                    else:
                        break

                else:
                    # Plain text response (no tool calls)
                    content = str(response)
                    stripped_content = content.strip()
                    # Check for visible chars (not just invisible unicode)
                    has_visible = any(c.isalnum() or c in '.,!?;:()[]{}-_+=' for c in stripped_content)

                    if stripped_content and has_visible:
                        result.response = stripped_content
                        # Print and log like the dict case
                        display_name = getattr(self.handler, 'display_name', 'Agent')
                        print(f"\n{Colors.BOLD}[{display_name}]{Colors.RESET}\n{stripped_content}")
                        utc_plus_4 = datetime.utcnow() + timedelta(hours=4)
                        time_str = utc_plus_4.strftime("%H:%M:%S")
                        log_content = f"{stripped_content} [{time_str} UTC+4]"
                        self.handler.log(log_type, log_content, metadata={"model": display_name})
                    break

            # Extract and execute any code blocks for analysis
            code_blocks = self._extract_code_blocks(result.response)
            for code_block in code_blocks:
                result.code_blocks.append(code_block)
                # Log analysis code as ACTION
                self.handler.log("ACTION", code_block.code)
                analysis_result = self.analysis.execute(code_block.code)
                result.analysis_results.append(analysis_result)

                # Log errors from code execution
                if not analysis_result.success and analysis_result.error:
                    self.handler.log("ERROR", f"Code execution failed:\n{analysis_result.error}", metadata={
                        "source": "analysis_sandbox",
                    })

        except Exception as e:
            result.response = f"Error in hybrid step: {e}"
            self.handler.log("ERROR", str(e))

        return result

    def _log_tool_call(self, tool_call: ToolCall):
        """Log a tool call as ACTION for frontend display."""
        # Format tool call as pseudo-code for display
        args_str = json.dumps(tool_call.arguments, indent=2)
        code_repr = f"# Tool Call: {tool_call.name}\nclient.{tool_call.name}({args_str})"
        self.handler.log("ACTION", code_repr, metadata={
            "tool_name": tool_call.name,
            "tool_call_id": tool_call.id,
            "arguments": tool_call.arguments,
        })

    def _log_tool_result(self, tool_call: ToolCall, tool_result: ToolResult):
        """Log tool result, with special handling for deployments and errors."""
        # Handle errors first
        if tool_result.status == ToolResultStatus.ERROR:
            self.handler.log("ERROR", f"Tool '{tool_call.name}' failed: {tool_result.error}", metadata={
                "tool_name": tool_call.name,
                "tool_call_id": tool_call.id,
                "error": tool_result.error,
                "arguments": tool_call.arguments,
            })
            return
        elif tool_result.status == ToolResultStatus.NOT_FOUND:
            self.handler.log("ERROR", f"Unknown tool: {tool_call.name}", metadata={
                "tool_name": tool_call.name,
                "tool_call_id": tool_call.id,
            })
            return

        # Handle successful tool calls
        if tool_call.name == "deploy_drone" and tool_result.status == ToolResultStatus.SUCCESS:
            # Special DEPLOYMENT log for frontend table display
            data = tool_result.data or {}
            design = tool_call.arguments.get("design", {})
            deployed = data.get("deployed", 0)
            survived = data.get("survived", 0)

            self.handler.log("DEPLOYMENT", f"Deployed drones via tool call", metadata={
                "design": design,
                "count": tool_call.arguments.get("count", 1),
                "equipment": tool_call.arguments.get("equipment"),
                "deployed": deployed,
                "survived": survived,
                "destroyed": data.get("destroyed", 0),
                "tool_call": True,
            })

            # Track last successful design (with survivors) for auto-submit fallback
            if survived > 0 and deployed > 0:
                survival_rate = survived / deployed
                # Update if this design has better survival rate
                if survival_rate > self.last_successful_survival_rate:
                    self.last_successful_design = design.copy() if isinstance(design, dict) else design
                    self.last_successful_survival_rate = survival_rate
        elif tool_call.name == "submit_final_design" and tool_result.status == ToolResultStatus.SUCCESS:
            # Log final submission
            data = tool_result.data or {}
            self.handler.log("REPORT", f"Final design submitted", metadata={
                "design": tool_call.arguments.get("design", {}),
                "survival_rate": data.get("survival_rate"),
                "victory": data.get("victory"),
                "tool_call": True,
            })
        else:
            # Log other tool results (get_status, get_history, etc.)
            # Truncate large results for display
            result_str = tool_result.to_string()
            if len(result_str) > 500:
                result_str = result_str[:500] + "... (truncated)"
            self.handler.log("ACTION", f"[{tool_call.name}] Result:\n{result_str}", metadata={
                "tool_name": tool_call.name,
                "tool_call_id": tool_call.id,
                "status": tool_result.status.value,
            })

    def _step_legacy(self, context: str, log_type: str) -> StepResult:
        """
        Legacy mode: Full code execution with injected client.

        This maintains backward compatibility with existing behavior
        where the agent writes Python code that calls client methods.
        """
        result = StepResult(response="")

        try:
            # Send message (standard text response)
            response = self.handler.send_message(context)
            result.response = response

            # Log the response
            self.handler.log(log_type, response)

            # Extract and execute code
            code = self._extract_last_code_block(response)
            if code:
                code_block = CodeBlock(code=code)
                result.code_blocks.append(code_block)

                # Log code as ACTION
                self.handler.log("ACTION", code)

                # Execute in legacy namespace (with client access)
                execution_result = self._execute_legacy(code)
                result.analysis_results.append(execution_result)

                # Log errors from code execution
                if not execution_result.success and execution_result.error:
                    self.handler.log("ERROR", f"Code execution failed:\n{execution_result.error}", metadata={
                        "source": "legacy_execution",
                    })

                # Check for mission complete
                for val in self._legacy_locals.values():
                    if isinstance(val, dict) and val.get("status") == "EVALUATION_COMPLETE":
                        result.mission_complete = True
                        self.mission_complete = True
                        break

        except Exception as e:
            result.response = f"Error in legacy step: {e}"
            self.handler.log("ERROR", str(e))

        return result

    def _execute_legacy(self, code: str) -> AnalysisResult:
        """Execute code in legacy mode (with client access)."""
        import io
        import ast
        import contextlib
        import traceback

        if not code.strip():
            return AnalysisResult(success=True, output="No code to execute.")

        stdout = io.StringIO()
        stderr = io.StringIO()

        try:
            tree = ast.parse(code)
            last_stmt = tree.body[-1] if tree.body else None

            if isinstance(last_stmt, ast.Expr):
                tree.body.pop()
                exec_code = compile(tree, "<string>", "exec")
                eval_code = compile(ast.Expression(last_stmt.value), "<string>", "eval")

                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    exec(exec_code, self._legacy_locals, self._legacy_locals)
                    result_val = eval(eval_code, self._legacy_locals, self._legacy_locals)
                    if result_val is not None:
                        print(result_val)
            else:
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    exec(code, self._legacy_locals, self._legacy_locals)

            output = stdout.getvalue()
            error = stderr.getvalue()

            return AnalysisResult(
                success=not error,
                output=output.strip(),
                error=error if error else None,
            )

        except Exception:
            return AnalysisResult(
                success=False,
                output=stdout.getvalue().strip(),
                error=traceback.format_exc(),
            )

    def _parse_arguments(self, tool_call: Dict[str, Any]) -> Dict[str, Any]:
        """Parse arguments from tool call."""
        args = tool_call.get("function", {}).get("arguments", tool_call.get("arguments", {}))
        if isinstance(args, str):
            try:
                return json.loads(args)
            except json.JSONDecodeError:
                return {}
        return args or {}

    def _extract_code_blocks(self, text: str) -> List[CodeBlock]:
        """Extract all Python code blocks from text."""
        # Remove thinking tags first
        cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)

        blocks = []
        matches = re.findall(r"```python\s*(.*?)```", cleaned, re.DOTALL)
        for code in matches:
            if code.strip():
                blocks.append(CodeBlock(code=code.strip()))
        return blocks

    def _extract_last_code_block(self, text: str) -> Optional[str]:
        """Extract the last Python code block from text."""
        cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
        matches = re.findall(r"```python\s*(.*?)```", cleaned, re.DOTALL)
        if matches:
            return matches[-1].strip()
        return None

    def _get_available_tools(self) -> List[ToolDefinition]:
        """
        Get list of available tools based on experiment capabilities.

        Filters out tools that aren't supported by the current experiment.
        """
        return list(CANYON_TOOLS)

    def get_available_tools(self) -> List[ToolDefinition]:
        """Get list of available tools."""
        return self._available_tools

    def get_openai_tools(self) -> List[Dict[str, Any]]:
        """Get tools in OpenAI format for available tools only."""
        return [t.to_openai_function() for t in self._available_tools]

    def run_until_complete(
        self,
        initial_prompt: str,
        max_turns: int = 100,
        context_generator: Optional[callable] = None,
    ) -> List[StepResult]:
        """
        Run the agent loop until mission complete or max turns reached.

        Args:
            initial_prompt: Initial prompt to start the conversation
            max_turns: Maximum number of turns
            context_generator: Optional function that generates context per turn

        Returns:
            List of all step results
        """
        results = []

        # Initial step
        result = self.step(initial_prompt)
        results.append(result)

        turn = 1
        while turn < max_turns and not self.mission_complete:
            turn += 1

            # Generate context for this turn
            if context_generator:
                context = context_generator(turn, max_turns)
            else:
                # Use feedback from previous step
                feedback = result.get_feedback_message()
                context = feedback if feedback else "Continue."

            result = self.step(context)
            results.append(result)

        return results
