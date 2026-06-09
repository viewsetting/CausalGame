"""
Environment Variable Generator

Generates environment instances with proper distributions and correlations.
Simulates the scientific discovery process where variables start hidden.
"""

import json
import os
import numpy as np
from typing import Dict, List, Any, Optional, Set
from pathlib import Path


class EnvironmentGenerator:
    """
    Generates environment instances based on variable definitions.

    Handles:
    - Distribution-based sampling (gaussian, uniform, exponential, log_normal)
    - Correlated variables
    - Variable visibility (hidden/visible)
    - Discovery difficulty levels
    """

    def __init__(self, config_path: Optional[str] = None, experiment_name: str = "antenna_trap"):
        """
        Initialize generator with environment variable configuration.

        Args:
            config_path: Path to environment_variables.json
            experiment_name: Name of experiment (used for default path lookup)
        """
        if config_path is None:
            # Try multiple possible paths
            possible_paths = [
                # Development: experiments directory
                Path(__file__).parent.parent.parent.parent / "experiments" / experiment_name / "environment_variables.json",
                # Docker: experiments directory
                Path("/app/experiments") / experiment_name / "environment_variables.json",
                # Current working directory
                Path("experiments") / experiment_name / "environment_variables.json",
            ]

            config_path = None
            for path in possible_paths:
                if path.exists():
                    config_path = path
                    break

            if config_path is None:
                raise FileNotFoundError(
                    f"Could not find environment_variables.json in any of: {[str(p) for p in possible_paths]}"
                )

        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)

        self.variable_categories = self.config['variable_categories']
        self.discovery_difficulty = self.config['discovery_difficulty']
        self.natural_language_mappings = self.config['natural_language_mappings']

        # Track discovered variables per session
        self.discovered_variables: Set[str] = set()

        # Initialize with visible variables
        self._initialize_visibility()

    def _initialize_visibility(self):
        """Initialize discovered variables with those marked as initially_visible."""
        for category_name, category_data in self.variable_categories.items():
            # Skip meta category - meta variables are not part of discovery
            if category_data.get('is_meta', False):
                continue

            # Check each variable's individual initially_visible setting
            for var_name, var_config in category_data.get('variables', {}).items():
                if var_config.get('initially_visible', False):
                    self.discovered_variables.add(var_name)

    def generate_environment(self,
                            seed: Optional[int] = None,
                            include_hidden: bool = True,
                            mission_id: Optional[str] = None,
                            timestamp: Optional[str] = None) -> Dict[str, Any]:
        """
        Generate a complete environment instance.

        Args:
            seed: Random seed for reproducibility
            include_hidden: Whether to generate hidden variables (for backend use)
            mission_id: Mission ID to include in environment (optional)
            timestamp: Timestamp to include in environment (optional)

        Returns:
            Dictionary of variable_name -> value
        """
        if seed is not None:
            np.random.seed(seed)

        environment = {}

        # First pass: Generate independent variables
        for category_name, category_data in self.variable_categories.items():
            # Skip meta category - these are set externally
            if category_name == 'meta':
                continue

            for var_name, var_config in category_data['variables'].items():
                # Skip if hidden and not including hidden vars
                if not include_hidden and var_name not in self.discovered_variables:
                    continue

                # Generate value based on distribution
                value = self._sample_variable(var_config)
                environment[var_name] = value

        # Second pass: Apply correlations
        environment = self._apply_correlations(environment)

        # Add meta variables if provided
        if mission_id is not None:
            environment['mission_id'] = mission_id
        if timestamp is not None:
            environment['timestamp'] = timestamp

        return environment

    def _sample_variable(self, var_config: Dict) -> float:
        """
        Sample a variable based on its distribution.

        Args:
            var_config: Variable configuration with 'distribution' field

        Returns:
            Sampled value
        """
        dist_config = var_config.get('distribution', {})
        dist_type = dist_config.get('type', 'uniform')
        var_range = var_config.get('range', [0, 100])
        var_type = var_config.get('type', 'float')

        # Sample based on distribution type
        if dist_type == 'gaussian':
            mean = dist_config.get('mean', sum(var_range) / 2)
            std = dist_config.get('std', (var_range[1] - var_range[0]) / 6)
            value = np.random.normal(mean, std)
            # Clip to range
            value = np.clip(value, var_range[0], var_range[1])

        elif dist_type == 'uniform':
            min_val = dist_config.get('min', var_range[0])
            max_val = dist_config.get('max', var_range[1])
            value = np.random.uniform(min_val, max_val)

        elif dist_type == 'exponential':
            rate = dist_config.get('rate', 0.2)
            value = np.random.exponential(1 / rate)
            # Clip to range
            value = np.clip(value, var_range[0], var_range[1])

        elif dist_type == 'log_normal':
            mean = dist_config.get('mean', 10)
            std = dist_config.get('std', 5)
            value = np.random.lognormal(np.log(mean), std / mean)
            # Clip to range
            value = np.clip(value, var_range[0], var_range[1])

        else:
            # Default to uniform
            value = np.random.uniform(var_range[0], var_range[1])

        # Convert to appropriate type
        if var_type == 'int':
            value = int(round(value))
        elif var_type == 'string':
            # For meta variables like mission_id, return empty string as placeholder
            # These should be set by the calling code
            value = ""

        return value

    def _apply_correlations(self, environment: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply correlations between variables.

        This is a simplified correlation model. In reality, we should use
        multivariate distributions or structural causal models.

        Args:
            environment: Initial environment values

        Returns:
            Environment with correlated adjustments
        """
        # For now, we'll apply correlations as post-hoc adjustments
        # In a more sophisticated version, this would use Cholesky decomposition
        # or the SCM's causal structure

        for category_name, category_data in self.variable_categories.items():
            for var_name, var_config in category_data['variables'].items():
                correlations = var_config.get('correlation_with', {})

                for correlated_var, correlation_coef in correlations.items():
                    if var_name in environment and correlated_var in environment:
                        # Apply simple correlation adjustment
                        # This is a rough approximation
                        adjustment = correlation_coef * 0.1 * environment[correlated_var]

                        # Get variable range for clipping
                        var_range = var_config.get('range', [0, 100])
                        environment[var_name] = np.clip(
                            environment[var_name] + adjustment,
                            var_range[0],
                            var_range[1]
                        )

        return environment

    def get_visible_environment(self, full_environment: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get only the visible (discovered) portion of an environment.

        Args:
            full_environment: Complete environment with all variables

        Returns:
            Filtered environment with only discovered variables
        """
        return {
            var_name: value
            for var_name, value in full_environment.items()
            if var_name in self.discovered_variables
        }

    def discover_variable(self, var_name: str) -> bool:
        """
        Mark a variable as discovered.

        Args:
            var_name: Name of variable to discover

        Returns:
            True if variable was newly discovered, False if already known
        """
        if var_name in self.discovered_variables:
            return False

        self.discovered_variables.add(var_name)
        return True

    def get_variable_info(self, var_name: str) -> Optional[Dict]:
        """
        Get configuration information for a variable.

        Args:
            var_name: Variable name

        Returns:
            Variable configuration or None if not found
        """
        for category_name, category_data in self.variable_categories.items():
            if var_name in category_data['variables']:
                var_config = category_data['variables'][var_name].copy()
                var_config['category'] = category_name
                var_config['name'] = var_name
                return var_config

        return None

    def find_variables_by_hint(self, hint: str) -> List[str]:
        """
        Find variables that match a discovery hint.

        Args:
            hint: Natural language hint or keyword

        Returns:
            List of matching variable names
        """
        matches = []
        hint_lower = hint.lower()

        # Normalize hint: remove spaces and underscores for fuzzy matching
        hint_normalized = hint_lower.replace(' ', '').replace('_', '').replace('-', '')

        # Check discovery hints
        for category_name, category_data in self.variable_categories.items():
            # Skip meta category
            if category_name == 'meta':
                continue

            for var_name, var_config in category_data['variables'].items():
                # Check 1: Variable name itself (fuzzy match)
                # "wind speed" → "windspeed" matches "wind_speed"
                var_name_normalized = var_name.replace('_', '').replace('-', '')
                if (hint_normalized in var_name_normalized or
                    var_name_normalized in hint_normalized or
                    hint_lower in var_name.replace('_', ' ')):
                    if var_name not in matches:
                        matches.append(var_name)
                        continue

                # Check 2: Discovery hints (Chinese/English)
                discovery_hints = var_config.get('discovery_hints', [])
                for discovery_hint in discovery_hints:
                    if hint_lower in discovery_hint.lower() or discovery_hint.lower() in hint_lower:
                        if var_name not in matches:
                            matches.append(var_name)
                            break

                # Check 3: Description
                description = var_config.get('description', '')
                if hint_lower in description.lower():
                    if var_name not in matches:
                        matches.append(var_name)

        # Check natural language mappings
        for category, var_list in self.natural_language_mappings.items():
            if hint_lower in category.lower() or category.lower() in hint_lower:
                matches.extend([v for v in var_list if v not in matches])

        return matches

    def get_difficulty(self, var_name: str) -> str:
        """
        Get discovery difficulty level for a variable.

        Args:
            var_name: Variable name

        Returns:
            Difficulty level: 'easy', 'medium', 'hard', 'very_hard', or 'unknown'
        """
        for difficulty, var_list in self.discovery_difficulty.items():
            if var_name in var_list:
                return difficulty

        return 'unknown'

    def reset_discoveries(self):
        """Reset discovered variables to initial visible state."""
        self.discovered_variables.clear()
        self._initialize_visibility()

    def get_all_variable_names(self) -> List[str]:
        """Get list of all variable names across all categories."""
        all_vars = []
        for category_data in self.variable_categories.values():
            all_vars.extend(category_data['variables'].keys())
        return all_vars

    def get_discovered_variable_names(self) -> List[str]:
        """Get list of currently discovered variables."""
        return list(self.discovered_variables)

    def get_hidden_variable_names(self) -> List[str]:
        """Get list of currently hidden variables."""
        all_vars = set(self.get_all_variable_names())
        return list(all_vars - self.discovered_variables)

    def get_initially_visible_variables(self) -> Set[str]:
        """
        Get the set of variables that are initially visible (before any discovery).
        This is fixed and does not change with subsequent discoveries.
        Reads each variable's individual 'initially_visible' setting.
        """
        initially_visible = set()
        for category_name, category_data in self.variable_categories.items():
            # Skip meta category
            if category_data.get('is_meta', False):
                continue

            # Check each variable's individual initially_visible setting
            for var_name, var_config in category_data.get('variables', {}).items():
                if var_config.get('initially_visible', False):
                    initially_visible.add(var_name)
        return initially_visible

    def get_initially_visible_environment(self, full_environment: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get environment with only initially visible variables.
        Unlike get_visible_environment, this is not affected by subsequent discoveries.

        Args:
            full_environment: Complete environment with all variables

        Returns:
            Filtered environment with only initially visible variables
        """
        initially_visible = self.get_initially_visible_variables()
        return {
            var_name: value
            for var_name, value in full_environment.items()
            if var_name in initially_visible
        }
