"""
CausalSCM - Abstract base class for Structural Causal Models.

Each experiment implements its own SCM subclass that defines:
- Environment variable sampling
- Causal relationships
- Effect computation

Key principle: SCM writes effects into DroneSheet middleware.
This is the ONLY way SCM affects the game.

Enhanced features:
- Explicit causal variable and structure equation registration
- do-intervention support
- Automatic sampling with topological ordering
- Multi-format export (text, graph, DOT, JSON Schema)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Tuple, Callable, Set
import random
import copy

# Handle both development (api.middleware) and Docker (middleware) imports
try:
    from ...middleware.drone_state import EnvironmentEffects
    from ...middleware.drone_sheet import DroneSheet
except ImportError:
    from middleware.drone_state import EnvironmentEffects
    from middleware.drone_sheet import DroneSheet


# ============================================================
# Core Data Structures for Explicit Causal Structure
# ============================================================

@dataclass
class CausalVariable:
    """
    Represents a variable in the causal model.

    Attributes:
        name: Unique identifier for the variable
        var_type: One of 'exogenous', 'latent', 'observed', 'derived'
        parents: List of parent variable names
        description: Human-readable description
        domain: Optional (min, max) range for the variable
    """
    name: str
    var_type: str = 'observed'  # 'exogenous', 'latent', 'observed', 'derived'
    parents: List[str] = field(default_factory=list)
    description: str = ''
    domain: Optional[Tuple[float, float]] = None


@dataclass
class StructuralEquation:
    """
    Represents a structural equation in the causal model.

    The function takes a dict of parent values and returns the variable value.

    Attributes:
        target: Name of the variable this equation computes
        function: Callable that takes parent values dict and returns computed value
        description: Human-readable description of the equation
    """
    target: str
    function: Callable[[Dict[str, Any]], Any]
    description: str = ''


@dataclass
class EnvironmentState:
    """
    Complete environment state from SCM sampling.

    Separates visible and latent (hidden) variables.
    """
    # Variables visible to agent
    visible: Dict[str, float] = field(default_factory=dict)

    # Latent variables (hidden from agent)
    latent: Dict[str, float] = field(default_factory=dict)

    # Derived variables (computed from visible/latent)
    derived: Dict[str, float] = field(default_factory=dict)

    def get(self, key: str, default: float = 0.0) -> float:
        """Get any variable by name."""
        if key in self.visible:
            return self.visible[key]
        if key in self.latent:
            return self.latent[key]
        if key in self.derived:
            return self.derived[key]
        return default

    def all_variables(self) -> Dict[str, float]:
        """Get all variables (for logging)."""
        result = {}
        result.update(self.visible)
        result.update(self.latent)
        result.update(self.derived)
        return result

    @property
    def weather_pattern(self) -> float:
        """Convenience accessor for common latent variable."""
        return self.latent.get('weather_pattern', 0.5)


class CausalSCM(ABC):
    """
    Abstract base class for Structural Causal Models.

    Each SCM defines:
    1. What environment variables exist
    2. How they are sampled (causal structure)
    3. How they affect the drone (effects)

    Subclasses implement:
    - sample_environment(): Generate environment state
    - apply_effects(): Write effects to DroneSheet

    Enhanced features:
    - Explicit variable and equation registration via CausalVariable/StructuralEquation
    - do-intervention support for causal reasoning
    - Automatic sampling with topological ordering
    - Multi-format export (text, graph, DOT, JSON Schema)

    Usage:
        scm = MyExperimentSCM(config)
        env = scm.sample_environment()
        scm.apply_effects(drone_sheet, env)
        # DroneSheet now has effects applied

        # do-intervention
        intervened_scm = scm.do('weather_pattern', 0.9)
        env = intervened_scm.sample()
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize SCM with experiment configuration.

        Args:
            config: Experiment configuration dict
        """
        self.config = config
        # Legacy storage (for backward compatibility)
        self._variables: Dict[str, Dict[str, Any]] = {}
        self._causal_edges: List[Tuple[str, str]] = []
        # New enhanced storage
        self._causal_variables: Dict[str, CausalVariable] = {}
        self._equations: Dict[str, StructuralEquation] = {}
        self._interventions: Dict[str, Any] = {}
        self._topological_order: Optional[List[str]] = None

        # Parse SCM config section
        scm_config = config.get('scm', {})
        self._exogenous_config: Dict[str, Dict[str, Any]] = scm_config.get(
            'exogenous_variables', {}
        )
        self._scm_parameters: Dict[str, Any] = scm_config.get('parameters', {})

    # ============================================================
    # Variable and Equation Registration
    # ============================================================

    def register_variable(self, var: CausalVariable) -> None:
        """
        Register a causal variable in the SCM.

        Args:
            var: CausalVariable to register
        """
        self._causal_variables[var.name] = var
        # Also update legacy storage for backward compatibility
        self._variables[var.name] = {
            'name': var.name,
            'type': var.var_type,
            'description': var.description,
            'domain': var.domain,
            'parents': var.parents,
        }
        # Add causal edges from parents
        for parent in var.parents:
            edge = (parent, var.name)
            if edge not in self._causal_edges:
                self._causal_edges.append(edge)
        # Invalidate cached topological order
        self._topological_order = None

    def register_equation(self, eq: StructuralEquation) -> None:
        """
        Register a structural equation in the SCM.

        Args:
            eq: StructuralEquation to register
        """
        self._equations[eq.target] = eq

    def add_variable(
        self,
        name: str,
        var_type: str = 'observed',
        description: str = '',
        **kwargs
    ) -> None:
        """
        Register a variable in the SCM (legacy method).

        For new code, prefer register_variable() with CausalVariable.

        Args:
            name: Variable name
            var_type: 'latent', 'observed', or 'derived'
            description: Human-readable description
            **kwargs: Additional variable properties (parents, domain)
        """
        parents = kwargs.pop('parents', [])
        domain = kwargs.pop('domain', None)
        var = CausalVariable(
            name=name,
            var_type=var_type,
            parents=parents,
            description=description,
            domain=domain,
        )
        self.register_variable(var)

    def add_causal_edge(self, cause: str, effect: str) -> None:
        """
        Add a causal edge to the graph.

        Args:
            cause: Cause variable name
            effect: Effect variable name
        """
        edge = (cause, effect)
        if edge not in self._causal_edges:
            self._causal_edges.append(edge)
        self._topological_order = None

    # ============================================================
    # do-Intervention Support
    # ============================================================

    def do(self, var_name: str, value: Any) -> 'CausalSCM':
        """
        Perform do-intervention: do(X = x).

        Returns a new SCM instance with the intervention applied.
        When sampling, the intervened variable will be fixed to the given value.

        Args:
            var_name: Variable name to intervene on
            value: Value to set the variable to

        Returns:
            New CausalSCM instance with intervention applied
        """
        # Create a deep copy to avoid modifying the original
        intervened = copy.copy(self)
        intervened._interventions = dict(self._interventions)
        intervened._interventions[var_name] = value
        return intervened

    def clear_interventions(self) -> None:
        """Clear all interventions."""
        self._interventions = {}

    def get_interventions(self) -> Dict[str, Any]:
        """Get current interventions."""
        return dict(self._interventions)

    # ============================================================
    # Topological Ordering
    # ============================================================

    def _compute_topological_order(self) -> List[str]:
        """
        Compute topological ordering of variables using Kahn's algorithm.

        Returns:
            List of variable names in topological order
        """
        if self._topological_order is not None:
            return self._topological_order

        # Build adjacency list and in-degree count
        in_degree: Dict[str, int] = {}
        children: Dict[str, List[str]] = {}

        all_vars = set(self._causal_variables.keys())
        for var_name in all_vars:
            in_degree[var_name] = 0
            children[var_name] = []

        for cause, effect in self._causal_edges:
            if cause in all_vars and effect in all_vars:
                children[cause].append(effect)
                in_degree[effect] += 1

        # Find all nodes with no incoming edges
        queue = [v for v in all_vars if in_degree[v] == 0]
        result = []

        while queue:
            node = queue.pop(0)
            result.append(node)
            for child in children.get(node, []):
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

        # Check for cycles
        if len(result) != len(all_vars):
            missing = all_vars - set(result)
            raise ValueError(f"Cycle detected in causal graph. Remaining nodes: {missing}")

        self._topological_order = result
        return result

    # ============================================================
    # Automatic Sampling
    # ============================================================

    def sample(self, exogenous_values: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Sample all variables according to the causal structure.

        Executes structural equations in topological order.
        Respects any active interventions.

        Args:
            exogenous_values: Optional dict of exogenous variable values.
                              If not provided, _sample_exogenous() is called.

        Returns:
            Dict mapping variable names to sampled values
        """
        if not self._causal_variables:
            # Fall back to sample_environment for backward compatibility
            env = self.sample_environment()
            return env.all_variables()

        values: Dict[str, Any] = {}
        exogenous = exogenous_values or {}

        for var_name in self._compute_topological_order():
            var = self._causal_variables[var_name]

            # Check for intervention
            if var_name in self._interventions:
                values[var_name] = self._interventions[var_name]
                continue

            # Check for provided exogenous value
            if var_name in exogenous:
                values[var_name] = exogenous[var_name]
                continue

            # Sample exogenous variables
            if var.var_type == 'exogenous' or not var.parents:
                values[var_name] = self._sample_exogenous(var_name, var)
                continue

            # Execute structural equation
            if var_name in self._equations:
                eq = self._equations[var_name]
                parent_values = {p: values.get(p) for p in var.parents}
                values[var_name] = eq.function(parent_values)
            else:
                # No equation registered, use default sampling
                values[var_name] = self._sample_exogenous(var_name, var)

        return values

    def _sample_exogenous(self, var_name: str, var: CausalVariable) -> Any:
        """
        Sample an exogenous variable.

        First checks config for distribution specification, then falls back
        to domain-based uniform sampling.

        Args:
            var_name: Variable name
            var: CausalVariable definition

        Returns:
            Sampled value
        """
        # Check if config specifies distribution for this variable
        if var_name in self._exogenous_config:
            return self._sample_from_config(var_name, self._exogenous_config[var_name])

        # Fall back to domain-based sampling
        if var.domain is not None:
            return random.uniform(var.domain[0], var.domain[1])
        return random.random()

    def _sample_from_config(self, var_name: str, var_config: Dict[str, Any]) -> Any:
        """
        Sample a variable based on config specification.

        Supported distributions:
        - uniform: params {low, high}
        - normal: params {mean, std}
        - bernoulli: params {p}
        - constant: params {value}

        Args:
            var_name: Variable name (for error messages)
            var_config: Config dict with 'distribution' and 'params'

        Returns:
            Sampled value
        """
        dist = var_config.get('distribution', 'uniform')
        params = var_config.get('params', {})

        if dist == 'uniform':
            low = params.get('low', 0.0)
            high = params.get('high', 1.0)
            return random.uniform(low, high)
        elif dist == 'normal':
            mean = params.get('mean', 0.0)
            std = params.get('std', 1.0)
            return random.gauss(mean, std)
        elif dist == 'bernoulli':
            p = params.get('p', 0.5)
            return 1.0 if random.random() < p else 0.0
        elif dist == 'constant':
            return params.get('value', 0.0)
        else:
            raise ValueError(f"Unknown distribution '{dist}' for variable '{var_name}'")

    def get_parameter(self, name: str, default: Any = None) -> Any:
        """
        Get a parameter from SCM config.

        Checks scm.parameters first, then falls back to top-level config.

        Args:
            name: Parameter name
            default: Default value if not found

        Returns:
            Parameter value
        """
        if name in self._scm_parameters:
            return self._scm_parameters[name]
        return self.config.get(name, default)

    # ============================================================
    # Export Methods
    # ============================================================

    def describe(self) -> str:
        """
        Return human-readable description of SCM.

        Groups variables by type and shows causal structure.
        """
        lines = [
            f"SCM: {self.__class__.__name__}",
            f"Variables: {len(self._causal_variables) or len(self._variables)}",
            f"Causal edges: {len(self._causal_edges)}",
            "",
        ]

        # Group variables by type
        by_type: Dict[str, List[CausalVariable]] = {
            'exogenous': [],
            'latent': [],
            'observed': [],
            'derived': [],
        }

        if self._causal_variables:
            for var in self._causal_variables.values():
                if var.var_type in by_type:
                    by_type[var.var_type].append(var)
                else:
                    by_type['observed'].append(var)

            for var_type, vars_list in by_type.items():
                if vars_list:
                    lines.append(f"{var_type.title()} Variables:")
                    for var in vars_list:
                        domain_str = f" [{var.domain[0]}, {var.domain[1]}]" if var.domain else ""
                        lines.append(f"  - {var.name}{domain_str}: {var.description}")
                        if var.parents:
                            lines.append(f"    Parents: {', '.join(var.parents)}")
                    lines.append("")
        else:
            # Legacy format
            lines.append("Variables:")
            for name, info in self._variables.items():
                var_type = info.get('type', 'unknown')
                desc = info.get('description', '')
                lines.append(f"  - {name} ({var_type}): {desc}")
            lines.append("")

        lines.append("Causal Structure:")
        for cause, effect in self._causal_edges:
            lines.append(f"  {cause} -> {effect}")

        return "\n".join(lines)

    def get_causal_graph(self) -> Dict[str, Any]:
        """
        Return causal graph structure for visualization.

        Returns:
            Dict with 'nodes', 'edges', 'variables', and 'metadata'
        """
        if self._causal_variables:
            nodes = [
                {
                    'name': var.name,
                    'type': var.var_type,
                    'description': var.description,
                    'domain': var.domain,
                    'parents': var.parents,
                }
                for var in self._causal_variables.values()
            ]
        else:
            nodes = [
                {'name': name, **info}
                for name, info in self._variables.items()
            ]

        edges = [
            {'from': cause, 'to': effect}
            for cause, effect in self._causal_edges
        ]

        return {
            'nodes': nodes,
            'edges': edges,
            'metadata': {
                'scm_name': self.__class__.__name__,
                'num_variables': len(nodes),
                'num_edges': len(edges),
            }
        }

    def to_dot(self) -> str:
        """
        Export causal graph in DOT/Graphviz format.

        Returns:
            DOT format string
        """
        lines = [
            f"digraph {self.__class__.__name__} {{",
            "    rankdir=TB;",
            "    node [shape=ellipse];",
            "",
        ]

        # Add nodes with styling based on type
        if self._causal_variables:
            latent_vars = []
            observed_vars = []
            derived_vars = []

            for var in self._causal_variables.values():
                if var.var_type in ('latent', 'exogenous'):
                    latent_vars.append(var)
                elif var.var_type == 'derived':
                    derived_vars.append(var)
                else:
                    observed_vars.append(var)

            if latent_vars:
                lines.append("    // Latent/Exogenous variables (dashed)")
                for var in latent_vars:
                    label = f"{var.name}\\n({var.var_type})"
                    lines.append(f'    {var.name} [label="{label}", style=dashed];')
                lines.append("")

            if observed_vars:
                lines.append("    // Observed variables")
                for var in observed_vars:
                    lines.append(f'    {var.name} [label="{var.name}"];')
                lines.append("")

            if derived_vars:
                lines.append("    // Derived variables (filled)")
                for var in derived_vars:
                    lines.append(f'    {var.name} [label="{var.name}", style=filled, fillcolor=lightgray];')
                lines.append("")
        else:
            for name in self._variables.keys():
                lines.append(f'    {name};')
            lines.append("")

        # Add edges
        lines.append("    // Edges")
        for cause, effect in self._causal_edges:
            lines.append(f"    {cause} -> {effect};")

        lines.append("}")
        return "\n".join(lines)

    def to_json_schema(self) -> Dict[str, Any]:
        """
        Export SCM as JSON Schema format.

        Returns:
            Dict with full SCM specification
        """
        variables = {}

        if self._causal_variables:
            for var in self._causal_variables.values():
                var_spec = {
                    'type': var.var_type,
                    'exogenous': var.var_type == 'exogenous' or not var.parents,
                    'description': var.description,
                    'parents': var.parents,
                }
                if var.domain:
                    var_spec['domain'] = list(var.domain)
                if var.name in self._equations:
                    var_spec['equation'] = self._equations[var.name].description
                variables[var.name] = var_spec
        else:
            for name, info in self._variables.items():
                variables[name] = {
                    'type': info.get('type', 'observed'),
                    'exogenous': not info.get('parents', []),
                    'description': info.get('description', ''),
                    'parents': info.get('parents', []),
                }
                if info.get('domain'):
                    variables[name]['domain'] = list(info['domain'])

        return {
            'name': self.__class__.__name__,
            'variables': variables,
            'edges': [
                [cause, effect]
                for cause, effect in self._causal_edges
            ],
        }

    # ============================================================
    # Abstract Methods (must be implemented by subclasses)
    # ============================================================

    @abstractmethod
    def sample_environment(self, equipment: dict = None) -> EnvironmentState:
        """
        Sample environment state according to causal structure.

        This method should:
        1. Sample latent variables first
        2. Sample visible variables conditioned on latent
        3. Compute derived variables

        Args:
            equipment: Optional equipment choices from agent (e.g., flight_profile).
                       SCMs can use this to let agent influence environment variables.

        Returns:
            EnvironmentState with all variables
        """
        pass

    @abstractmethod
    def apply_effects(
        self,
        sheet: DroneSheet,
        env: EnvironmentState
    ) -> None:
        """
        Apply environment effects to DroneSheet.

        This is the ONLY way SCM affects the game!

        Implementation should:
        1. Compute effects from environment state
        2. Call sheet.apply_environment_effects(effects)

        Args:
            sheet: DroneSheet middleware to write to
            env: EnvironmentState from sample_environment()
        """
        pass


class BaseSCM(CausalSCM):
    """
    Base SCM implementation with minimal common functionality.

    Provides:
    - apply_effects() that delegates to abstract _compute_effects()
    - Helper method for linear interpolation

    Subclasses MUST implement:
    - sample_environment(): Define how to sample environment state
    - _compute_effects(): Define the specific causal mechanism

    This base class is intentionally minimal. All experiment-specific
    logic (latent variables, causal structure, etc.) belongs in subclasses.
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

    def apply_effects(
        self,
        sheet: DroneSheet,
        env: EnvironmentState
    ) -> None:
        """
        Apply effects by delegating to _compute_effects().

        This is the standard flow - subclasses implement _compute_effects().
        """
        effects = self._compute_effects(sheet, env)
        sheet.apply_environment_effects(effects)

    @abstractmethod
    def _compute_effects(
        self,
        sheet: DroneSheet,
        env: EnvironmentState
    ) -> EnvironmentEffects:
        """
        Compute environment effects for this specific causal mechanism.

        This is where each experiment defines its unique causal structure.
        Subclasses MUST implement this method.

        Args:
            sheet: DroneSheet to read drone state from (if needed)
            env: EnvironmentState with visible/latent/derived variables

        Returns:
            EnvironmentEffects to be applied to DroneSheet
        """
        pass

    # ========== Helper methods for subclasses ==========

    @staticmethod
    def _interpolate(
        t: float,
        value_at_0: float,
        value_at_1: float
    ) -> float:
        """
        Linear interpolation helper.

        Args:
            t: Interpolation parameter (0 to 1)
            value_at_0: Value when t=0
            value_at_1: Value when t=1

        Returns:
            Interpolated value
        """
        return value_at_0 * (1 - t) + value_at_1 * t
