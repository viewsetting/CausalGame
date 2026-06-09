"""
Analysis Sandbox for CausalGame agent.

This module provides an isolated execution environment for data analysis code.
The sandbox has access to pandas/numpy and data, but NOT direct API access.
"""

import io
import ast
import contextlib
import traceback
from dataclasses import dataclass, field
from typing import Dict, Any, Callable, Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from .workspace import SessionWorkspace


class ClientStub:
    """
    Stub client that provides helpful error messages in hybrid mode.

    In hybrid mode, API operations should be done via tool calling,
    not Python code execution. This stub catches attempts to use
    client.xxx() and returns informative error messages.
    """

    def __getattr__(self, name: str):
        """Intercept any attribute access and raise helpful error."""
        tool_mapping = {
            "get_history": "get_history",
            "get_status": "get_status",
            "get_all_environments": "get_all_environments",
            "get_mission_environment": "get_all_environments",
            "query_environment": "query_environment",
            "deploy_drone": "deploy_drone",
            "submit_final_design": "submit_final_design",
            "get_action_space": "get_action_space",
        }

        if name in tool_mapping:
            tool_name = tool_mapping[name]
            raise RuntimeError(
                f"[HYBRID MODE] Cannot use 'client.{name}()' in code blocks!\n"
                f"In hybrid mode, use the '{tool_name}' TOOL instead.\n"
                f"Example: Call the '{tool_name}' tool with appropriate parameters.\n"
                f"Code blocks are only for data analysis with pandas/numpy."
            )
        else:
            raise AttributeError(
                f"'client' object has no attribute '{name}'. "
                f"In hybrid mode, use TOOLS for API operations, not code."
            )


@dataclass
class AnalysisResult:
    """
    Result from executing analysis code in the sandbox.

    Attributes:
        success: Whether execution completed without errors
        output: Captured stdout from the execution
        error: Error message/traceback if execution failed
        variables: Variables that were created/modified during execution
    """
    success: bool
    output: str = ""
    error: Optional[str] = None
    variables: Dict[str, Any] = field(default_factory=dict)

    def to_string(self) -> str:
        """Convert to string for LLM consumption."""
        parts = []
        if self.output:
            parts.append(f"OUTPUT:\n{self.output}")
        if self.error:
            parts.append(f"ERROR:\n{self.error}")
        if not parts:
            return "Code executed successfully (no output)."
        return "\n".join(parts)


class AnalysisContext:
    """
    Isolated execution environment for data analysis.

    This sandbox provides:
    - pandas and numpy for data manipulation
    - A data_provider function to get current data (history, status)
    - Safe print function that captures output
    - NO direct API access (client is not injected)

    Usage:
        context = AnalysisContext(
            data_provider=lambda: {
                "history": client.get_history(),
                "status": client.get_status()
            }
        )
        result = context.execute('''
            df = pd.DataFrame(data["history"])
            print(df.describe())
        ''')
    """

    def __init__(
        self,
        data_provider: Optional[Callable[[], Dict[str, Any]]] = None,
        additional_imports: Optional[Dict[str, Any]] = None,
        workspace: Optional["SessionWorkspace"] = None,
    ):
        """
        Initialize the analysis context.

        Args:
            data_provider: Callable that returns current data snapshot.
                          The returned dict is accessible as `data` in code.
            additional_imports: Additional modules/objects to inject into namespace
            workspace: Optional SessionWorkspace for isolated file operations (HYBRID mode)
        """
        self._data_provider = data_provider
        self._additional_imports = additional_imports or {}
        self._workspace = workspace
        self._output_buffer: List[str] = []

        # Build the base namespace
        self._base_namespace = self._build_namespace()

    def _safe_print(self, *args, **kwargs):
        """Safe print that captures to buffer instead of stdout."""
        output = io.StringIO()
        print(*args, file=output, **kwargs)
        self._output_buffer.append(output.getvalue())

    def _build_namespace(self) -> Dict[str, Any]:
        """Build the execution namespace with allowed imports."""
        import pandas as pd
        import numpy as np
        import time
        from collections import Counter, defaultdict

        # If workspace is available, wrap pandas/numpy to restrict file I/O
        if self._workspace:
            sandboxed_pd = self._workspace.wrap_pandas(pd)
            sandboxed_np = self._workspace.wrap_numpy(np)
        else:
            sandboxed_pd = pd
            sandboxed_np = np

        # Create restricted builtins - only safe functions, no imports or file access
        restricted_builtins = {
            # Safe built-in functions
            "len": len,
            "range": range,
            "enumerate": enumerate,
            "zip": zip,
            "map": map,
            "filter": filter,
            "sorted": sorted,
            "reversed": reversed,
            "sum": sum,
            "min": min,
            "max": max,
            "abs": abs,
            "round": round,
            "int": int,
            "float": float,
            "str": str,
            "bool": bool,
            "list": list,
            "dict": dict,
            "set": set,
            "tuple": tuple,
            "type": type,
            "isinstance": isinstance,
            "hasattr": hasattr,
            "getattr": getattr,
            "setattr": setattr,
            "pow": pow,
            "divmod": divmod,
            "all": all,
            "any": any,
            "repr": repr,
            "format": format,
            "iter": iter,
            "next": next,
            "slice": slice,
            "callable": callable,
            "ord": ord,
            "chr": chr,
            "hex": hex,
            "bin": bin,
            "oct": oct,
            # Exceptions (needed for try/except)
            "Exception": Exception,
            "ValueError": ValueError,
            "TypeError": TypeError,
            "KeyError": KeyError,
            "IndexError": IndexError,
            "AttributeError": AttributeError,
            "RuntimeError": RuntimeError,
            "ZeroDivisionError": ZeroDivisionError,
            "StopIteration": StopIteration,
            # None, True, False are automatically available
            "None": None,
            "True": True,
            "False": False,
        }

        namespace = {
            # Restrict __builtins__ to prevent import and file access bypass
            "__builtins__": restricted_builtins,

            # Data analysis libraries (sandboxed if workspace available)
            "pd": sandboxed_pd,
            "np": sandboxed_np,
            "pandas": sandboxed_pd,
            "numpy": sandboxed_np,

            # Useful standard library modules (pre-imported)
            "Counter": Counter,
            "defaultdict": defaultdict,

            # Utilities
            "time": time,
            "print": self._safe_print,

            # Built-ins also at top level for convenience
            **restricted_builtins,
        }

        # If workspace is available, inject safe file operations
        if self._workspace:
            namespace["open"] = self._workspace.safe_open
            namespace["listdir"] = self._workspace.list_files
            namespace["file_exists"] = self._workspace.exists
            namespace["workspace_path"] = self._workspace.get_workspace_path()
            restricted_builtins["open"] = self._workspace.safe_open
        else:
            # No workspace = no file operations allowed
            def _no_file_ops(*args, **kwargs):
                raise PermissionError("File operations not available without workspace")
            namespace["open"] = _no_file_ops
            restricted_builtins["open"] = _no_file_ops

        # Inject ClientStub to give helpful errors when agent tries to use client in code
        # In hybrid mode, API operations should be done via tool calling, not code
        namespace["client"] = ClientStub()

        # Add any additional imports
        namespace.update(self._additional_imports)

        return namespace

    def execute(self, code: str) -> AnalysisResult:
        """
        Execute analysis code in the isolated sandbox.

        Args:
            code: Python code to execute

        Returns:
            AnalysisResult with output, errors, and created variables
        """
        if not code.strip():
            return AnalysisResult(
                success=True,
                output="No code to execute.",
            )

        # Reset output buffer
        self._output_buffer = []

        # Create fresh namespace from base
        namespace = self._base_namespace.copy()

        # Inject current data if provider is available
        if self._data_provider:
            try:
                namespace["data"] = self._data_provider()
            except Exception as e:
                return AnalysisResult(
                    success=False,
                    error=f"Failed to load data: {e}",
                )

        # Capture stdout for execution
        stdout = io.StringIO()
        stderr = io.StringIO()

        try:
            # Parse the code to check syntax
            tree = ast.parse(code)
            last_stmt = tree.body[-1] if tree.body else None

            # If last statement is an expression, we want to print its result
            if isinstance(last_stmt, ast.Expr):
                tree.body.pop()
                exec_code = compile(tree, "<analysis>", "exec")
                eval_code = compile(ast.Expression(last_stmt.value), "<analysis>", "eval")

                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    exec(exec_code, namespace, namespace)
                    result = eval(eval_code, namespace, namespace)
                    if result is not None:
                        self._safe_print(result)
            else:
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    exec(code, namespace, namespace)

            # Collect output
            output_parts = []
            if self._output_buffer:
                output_parts.extend(self._output_buffer)
            captured_stdout = stdout.getvalue()
            if captured_stdout:
                output_parts.append(captured_stdout)

            output = "".join(output_parts)

            # Check for stderr
            captured_stderr = stderr.getvalue()
            error = captured_stderr if captured_stderr else None

            # Collect user-created variables (exclude builtins and imports)
            user_vars = {}
            base_keys = set(self._base_namespace.keys()) | {"data"}
            for key, value in namespace.items():
                if key not in base_keys and not key.startswith("_"):
                    # Only include serializable types
                    if isinstance(value, (int, float, str, bool, list, dict, type(None))):
                        user_vars[key] = value

            return AnalysisResult(
                success=True,
                output=output.strip(),
                error=error,
                variables=user_vars,
            )

        except SyntaxError as e:
            return AnalysisResult(
                success=False,
                output="".join(self._output_buffer),
                error=f"Syntax error: {e}",
            )
        except Exception:
            return AnalysisResult(
                success=False,
                output="".join(self._output_buffer),
                error=traceback.format_exc(),
            )

    def update_data_provider(self, data_provider: Callable[[], Dict[str, Any]]):
        """Update the data provider function."""
        self._data_provider = data_provider

    def add_to_namespace(self, name: str, value: Any):
        """Add a value to the base namespace."""
        self._base_namespace[name] = value
