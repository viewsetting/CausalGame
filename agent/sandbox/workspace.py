"""Session-isolated workspace for file operations."""

from pathlib import Path
from typing import List, Any, Callable
import functools


class SessionWorkspace:
    """
    Session-isolated file system sandbox.

    Agent can only access the session-specific working directory,
    preventing reads/writes to other file system locations.
    """

    def __init__(
        self,
        session_id: str,
        base_dir: str = "agent_workspaces",
    ):
        """
        Initialize the workspace for a session.

        Args:
            session_id: Unique session identifier (used as directory name)
            base_dir: Root directory for all session workspaces
        """
        self.session_id = session_id
        self.root = Path(base_dir).resolve() / session_id
        self.root.mkdir(parents=True, exist_ok=True)

    def _validate_path(self, path: str) -> Path:
        """
        Validate that path is within workspace, preventing path traversal attacks.

        Args:
            path: Relative path to validate

        Returns:
            Resolved absolute path within workspace

        Raises:
            PermissionError: If path is absolute or escapes workspace
        """
        # Reject absolute paths
        if Path(path).is_absolute():
            raise PermissionError(f"Absolute paths not allowed: {path}")

        resolved = (self.root / path).resolve()

        # Check if resolved path is within workspace
        if not resolved.is_relative_to(self.root):
            raise PermissionError(f"Path escapes workspace: {path}")

        return resolved

    def safe_open(self, path: str, mode: str = 'r'):
        """
        Safe open() replacement that only allows access to workspace files.

        Args:
            path: Relative path within workspace
            mode: File open mode ('r', 'w', 'a', etc.)

        Returns:
            File handle

        Raises:
            PermissionError: If path is not within workspace
        """
        resolved = self._validate_path(path)

        # Create parent directories if writing
        if 'w' in mode or 'a' in mode:
            resolved.parent.mkdir(parents=True, exist_ok=True)

        return open(resolved, mode)

    def list_files(self, subdir: str = ".") -> List[str]:
        """
        List files in a workspace subdirectory.

        Args:
            subdir: Subdirectory to list (default: workspace root)

        Returns:
            List of file/directory names
        """
        resolved = self._validate_path(subdir)
        if not resolved.is_dir():
            return []
        return [f.name for f in resolved.iterdir()]

    def exists(self, path: str) -> bool:
        """
        Check if a file exists within the workspace.

        Args:
            path: Relative path to check

        Returns:
            True if file exists, False otherwise (including invalid paths)
        """
        try:
            resolved = self._validate_path(path)
            return resolved.exists()
        except PermissionError:
            return False

    def get_workspace_path(self) -> str:
        """
        Get the workspace root directory path.

        Returns:
            Absolute path to workspace root (read-only information)
        """
        return str(self.root)

    def resolve_path(self, path: str) -> str:
        """
        Resolve a relative path to absolute path within workspace.

        Args:
            path: Relative path to resolve

        Returns:
            Absolute path string within workspace

        Raises:
            PermissionError: If path escapes workspace
        """
        resolved = self._validate_path(path)
        # Create parent directories if needed
        resolved.parent.mkdir(parents=True, exist_ok=True)
        return str(resolved)

    def wrap_pandas(self, pd_module: Any) -> "SandboxedPandas":
        """
        Create a sandboxed pandas wrapper.

        Args:
            pd_module: The pandas module

        Returns:
            SandboxedPandas wrapper that restricts file operations
        """
        return SandboxedPandas(pd_module, self)

    def wrap_numpy(self, np_module: Any) -> "SandboxedNumpy":
        """
        Create a sandboxed numpy wrapper.

        Args:
            np_module: The numpy module

        Returns:
            SandboxedNumpy wrapper that restricts file operations
        """
        return SandboxedNumpy(np_module, self)


class SandboxedPandas:
    """
    Pandas wrapper that restricts file I/O to workspace.

    Intercepts file-related methods and validates paths.
    All other methods are passed through to the real pandas module.
    """

    # Methods that take a file path as first argument
    _READ_METHODS = {
        'read_csv', 'read_excel', 'read_json', 'read_parquet',
        'read_pickle', 'read_feather', 'read_hdf', 'read_html',
        'read_xml', 'read_stata', 'read_sas', 'read_spss',
        'read_orc', 'read_table', 'read_fwf',
    }

    def __init__(self, pd_module: Any, workspace: SessionWorkspace):
        self._pd = pd_module
        self._workspace = workspace

    def __getattr__(self, name: str) -> Any:
        """Intercept attribute access to wrap file operations."""
        attr = getattr(self._pd, name)

        if name in self._READ_METHODS:
            return self._wrap_read_method(attr, name)

        return attr

    def _wrap_read_method(self, method: Callable, name: str) -> Callable:
        """Wrap a pandas read method to validate file paths."""
        @functools.wraps(method)
        def wrapper(filepath_or_buffer, *args, **kwargs):
            # If it's a string path, validate it
            if isinstance(filepath_or_buffer, str):
                filepath_or_buffer = self._workspace.resolve_path(filepath_or_buffer)
            return method(filepath_or_buffer, *args, **kwargs)
        return wrapper

    # DataFrame methods are handled via DataFrame wrapper
    # But we need to ensure DataFrames created have sandboxed to_* methods
    def DataFrame(self, *args, **kwargs):
        """Create a DataFrame with sandboxed I/O methods."""
        df = self._pd.DataFrame(*args, **kwargs)
        return SandboxedDataFrame(df, self._workspace)

    def read_csv(self, filepath_or_buffer, *args, **kwargs):
        """Sandboxed read_csv."""
        if isinstance(filepath_or_buffer, str):
            filepath_or_buffer = self._workspace.resolve_path(filepath_or_buffer)
        df = self._pd.read_csv(filepath_or_buffer, *args, **kwargs)
        return SandboxedDataFrame(df, self._workspace)

    def read_json(self, path_or_buf, *args, **kwargs):
        """Sandboxed read_json."""
        if isinstance(path_or_buf, str):
            path_or_buf = self._workspace.resolve_path(path_or_buf)
        df = self._pd.read_json(path_or_buf, *args, **kwargs)
        return SandboxedDataFrame(df, self._workspace)

    def read_excel(self, io, *args, **kwargs):
        """Sandboxed read_excel."""
        if isinstance(io, str):
            io = self._workspace.resolve_path(io)
        df = self._pd.read_excel(io, *args, **kwargs)
        return SandboxedDataFrame(df, self._workspace)

    def read_parquet(self, path, *args, **kwargs):
        """Sandboxed read_parquet."""
        if isinstance(path, str):
            path = self._workspace.resolve_path(path)
        df = self._pd.read_parquet(path, *args, **kwargs)
        return SandboxedDataFrame(df, self._workspace)

    def read_pickle(self, filepath_or_buffer, *args, **kwargs):
        """Sandboxed read_pickle."""
        if isinstance(filepath_or_buffer, str):
            filepath_or_buffer = self._workspace.resolve_path(filepath_or_buffer)
        df = self._pd.read_pickle(filepath_or_buffer, *args, **kwargs)
        return SandboxedDataFrame(df, self._workspace)


class SandboxedDataFrame:
    """
    DataFrame wrapper that restricts file I/O to workspace.

    Intercepts to_* methods and validates paths.
    All other methods are passed through to the real DataFrame.
    """

    _WRITE_METHODS = {
        'to_csv', 'to_excel', 'to_json', 'to_parquet',
        'to_pickle', 'to_feather', 'to_hdf', 'to_html',
        'to_xml', 'to_stata', 'to_orc', 'to_latex',
        'to_markdown',
    }

    def __init__(self, df: Any, workspace: SessionWorkspace):
        self._df = df
        self._workspace = workspace

    def __getattr__(self, name: str) -> Any:
        """Intercept attribute access to wrap file operations."""
        attr = getattr(self._df, name)

        if name in self._WRITE_METHODS:
            return self._wrap_write_method(attr, name)

        # Wrap methods that return DataFrames
        if callable(attr):
            @functools.wraps(attr)
            def wrapper(*args, **kwargs):
                result = attr(*args, **kwargs)
                # If result is a DataFrame, wrap it
                if type(result).__name__ == 'DataFrame':
                    return SandboxedDataFrame(result, self._workspace)
                return result
            return wrapper

        return attr

    def _wrap_write_method(self, method: Callable, name: str) -> Callable:
        """Wrap a DataFrame write method to validate file paths."""
        @functools.wraps(method)
        def wrapper(path_or_buf=None, *args, **kwargs):
            if path_or_buf is not None and isinstance(path_or_buf, str):
                path_or_buf = self._workspace.resolve_path(path_or_buf)
            return method(path_or_buf, *args, **kwargs)
        return wrapper

    def __repr__(self):
        return repr(self._df)

    def __str__(self):
        return str(self._df)

    def __len__(self):
        return len(self._df)

    def __iter__(self):
        return iter(self._df)

    def __getitem__(self, key):
        result = self._df[key]
        if type(result).__name__ == 'DataFrame':
            return SandboxedDataFrame(result, self._workspace)
        return result

    def __setitem__(self, key, value):
        self._df[key] = value

    @property
    def columns(self):
        return self._df.columns

    @property
    def index(self):
        return self._df.index

    @property
    def values(self):
        return self._df.values

    @property
    def shape(self):
        return self._df.shape

    @property
    def dtypes(self):
        return self._df.dtypes

    @property
    def loc(self):
        return self._df.loc

    @property
    def iloc(self):
        return self._df.iloc


class SandboxedNumpy:
    """
    Numpy wrapper that restricts file I/O to workspace.

    Intercepts file-related methods and validates paths.
    All other methods are passed through to the real numpy module.
    """

    _FILE_METHODS = {
        'save', 'savez', 'savez_compressed', 'savetxt',
        'load', 'loadtxt', 'genfromtxt', 'fromfile',
    }

    def __init__(self, np_module: Any, workspace: SessionWorkspace):
        self._np = np_module
        self._workspace = workspace

    def __getattr__(self, name: str) -> Any:
        """Intercept attribute access to wrap file operations."""
        attr = getattr(self._np, name)

        if name in self._FILE_METHODS:
            return self._wrap_file_method(attr, name)

        return attr

    def _wrap_file_method(self, method: Callable, name: str) -> Callable:
        """Wrap a numpy file method to validate file paths."""
        @functools.wraps(method)
        def wrapper(file, *args, **kwargs):
            if isinstance(file, str):
                file = self._workspace.resolve_path(file)
            return method(file, *args, **kwargs)
        return wrapper

    def save(self, file, arr, *args, **kwargs):
        """Sandboxed save."""
        if isinstance(file, str):
            file = self._workspace.resolve_path(file)
        return self._np.save(file, arr, *args, **kwargs)

    def savez(self, file, *args, **kwargs):
        """Sandboxed savez."""
        if isinstance(file, str):
            file = self._workspace.resolve_path(file)
        return self._np.savez(file, *args, **kwargs)

    def savez_compressed(self, file, *args, **kwargs):
        """Sandboxed savez_compressed."""
        if isinstance(file, str):
            file = self._workspace.resolve_path(file)
        return self._np.savez_compressed(file, *args, **kwargs)

    def savetxt(self, fname, X, *args, **kwargs):
        """Sandboxed savetxt."""
        if isinstance(fname, str):
            fname = self._workspace.resolve_path(fname)
        return self._np.savetxt(fname, X, *args, **kwargs)

    def load(self, file, *args, **kwargs):
        """Sandboxed load."""
        if isinstance(file, str):
            file = self._workspace.resolve_path(file)
        return self._np.load(file, *args, **kwargs)

    def loadtxt(self, fname, *args, **kwargs):
        """Sandboxed loadtxt."""
        if isinstance(fname, str):
            fname = self._workspace.resolve_path(fname)
        return self._np.loadtxt(fname, *args, **kwargs)

    def genfromtxt(self, fname, *args, **kwargs):
        """Sandboxed genfromtxt."""
        if isinstance(fname, str):
            fname = self._workspace.resolve_path(fname)
        return self._np.genfromtxt(fname, *args, **kwargs)

    def fromfile(self, file, *args, **kwargs):
        """Sandboxed fromfile."""
        if isinstance(file, str):
            file = self._workspace.resolve_path(file)
        return self._np.fromfile(file, *args, **kwargs)
