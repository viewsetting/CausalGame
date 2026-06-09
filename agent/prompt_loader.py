"""
Experiment-specific Prompt Loader

Loads and renders prompt templates from experiments directory.
Supports Mustache-like template syntax with {{variable}} placeholders.
"""

import os
import re
from typing import Dict, Any, Optional
from pathlib import Path

from config import config


def get_experiments_dir() -> Path:
    """Get the experiments directory path."""
    # Try relative to this file first
    agent_dir = Path(__file__).parent
    project_root = agent_dir.parent
    experiments_dir = project_root / "experiments"

    if experiments_dir.exists():
        return experiments_dir

    # Fallback to current working directory
    cwd_experiments = Path.cwd() / "experiments"
    if cwd_experiments.exists():
        return cwd_experiments

    raise FileNotFoundError("Could not find experiments directory")


def get_base_experiment_name(experiment_name: str) -> str:
    """
    Extract base experiment name from variant name.

    Examples:
        'antenna_trap_high_def' -> 'antenna_trap'
        'deployment_zone_trap_categorical_local_optima' -> 'deployment_zone_trap_categorical'
        'deployment_zone_trap_env_shift' -> 'deployment_zone_trap'
        'weather_defense' -> 'weather_defense'
    """
    # Known base experiment names (order matters - longer names first)
    # Note: Only include experiments that have their own no_tool_def_prompt.md
    base_experiments = [
        'deployment_zone_trap_categorical',  # Has its own prompt
        'deployment_zone_trap',               # Parent for env_shift and other variants
        'antenna_trap',                       # Parent for all antenna variants
        'weather_defense',                    # Has its own prompt
        'weather_noise',                      # Has its own prompt
    ]

    for base in base_experiments:
        if experiment_name.startswith(base):
            return base

    # Fallback: return as-is
    return experiment_name


def load_prompt_template(experiment_name: str, mode: str = "legacy") -> str:
    """
    Load the prompt template for a specific experiment.

    Args:
        experiment_name: Name of the experiment (e.g., 'antenna_trap')
        mode: Execution mode - 'legacy' or 'hybrid'
              - legacy: loads prompt.md (with client.xxx() methods)
              - hybrid: loads no_tool_def_prompt.md (tool-call friendly)

    Returns:
        Raw prompt template string

    Raises:
        FileNotFoundError: If no suitable prompt file exists
    """
    experiments_dir = get_experiments_dir()

    # Determine which prompt file to look for
    if mode.lower() == "hybrid":
        prompt_filename = "no_tool_def_prompt.md"
    else:
        prompt_filename = "prompt.md"

    # Try loading paths in order of preference
    paths_to_try = []

    # 1. First try exact experiment path
    paths_to_try.append(experiments_dir / experiment_name / prompt_filename)

    # 2. If hybrid mode and not found, try base experiment's hybrid prompt
    if mode.lower() == "hybrid":
        base_name = get_base_experiment_name(experiment_name)
        if base_name != experiment_name:
            paths_to_try.append(experiments_dir / base_name / prompt_filename)

    # 3. Fallback to legacy prompt.md
    if prompt_filename != "prompt.md":
        paths_to_try.append(experiments_dir / experiment_name / "prompt.md")
        base_name = get_base_experiment_name(experiment_name)
        if base_name != experiment_name:
            paths_to_try.append(experiments_dir / base_name / "prompt.md")

    # Try each path
    for path in paths_to_try:
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()

    # Nothing found
    raise FileNotFoundError(
        f"Prompt template not found for experiment '{experiment_name}' (mode={mode})\n"
        f"Tried: {[str(p) for p in paths_to_try]}\n"
        f"Please create experiments/{experiment_name}/{prompt_filename}"
    )


def render_prompt(
    template: str,
    variables: Dict[str, Any],
    strip_comments: bool = True
) -> str:
    """
    Render a prompt template with variable substitution.

    Supports:
    - {{variable}} - Simple substitution
    - {{#if variable}}...{{/if}} - Conditional blocks
    - {{#unless variable}}...{{/unless}} - Negative conditional blocks

    Args:
        template: Raw template string
        variables: Dict of variable names to values
        strip_comments: If True, remove HTML comments <!-- -->

    Returns:
        Rendered prompt string
    """
    result = template

    # Handle {{#if variable}}...{{/if}} blocks
    if_pattern = r'\{\{#if\s+(\w+)\}\}(.*?)\{\{/if\}\}'

    def replace_if(match):
        var_name = match.group(1)
        content = match.group(2)
        if variables.get(var_name):
            return content
        return ''

    result = re.sub(if_pattern, replace_if, result, flags=re.DOTALL)

    # Handle {{#unless variable}}...{{/unless}} blocks
    unless_pattern = r'\{\{#unless\s+(\w+)\}\}(.*?)\{\{/unless\}\}'

    def replace_unless(match):
        var_name = match.group(1)
        content = match.group(2)
        if not variables.get(var_name):
            return content
        return ''

    result = re.sub(unless_pattern, replace_unless, result, flags=re.DOTALL)

    # Handle simple {{variable}} substitution
    simple_pattern = r'\{\{(\w+)\}\}'

    def replace_simple(match):
        var_name = match.group(1)
        value = variables.get(var_name, '')
        if value is None:
            return ''
        return str(value)

    result = re.sub(simple_pattern, replace_simple, result)

    # Strip HTML comments if requested
    if strip_comments:
        result = re.sub(r'<!--.*?-->', '', result, flags=re.DOTALL)

    # Clean up extra blank lines
    result = re.sub(r'\n{3,}', '\n\n', result)

    return result.strip()


def format_component_list(components: Dict[str, Any]) -> str:
    """
    Format component configuration as a readable list.

    Args:
        components: Dict of component configs from game.json

    Returns:
        Formatted string for prompt
    """
    lines = []
    for name, config in components.items():
        if isinstance(config, dict):
            def_value = config.get('default_def', config.get('def', 'N/A'))
            lines.append(f"  - {name}_def: {def_value}")
        else:
            lines.append(f"  - {name}_def: {config}")
    return '\n'.join(lines)


def format_design_schema(components: Dict[str, Any]) -> str:
    """
    Format design schema for API documentation.

    Args:
        components: Dict of component configs

    Returns:
        JSON-like schema string
    """
    parts = []
    for name in components.keys():
        parts.append(f"'{name}_def': int")
    return '{' + ', '.join(parts) + '}'


def format_action_space(action_space: Dict[str, Any]) -> str:
    """
    Format action space configuration for the prompt.

    Args:
        action_space: Action space from API (get_agent_view output)

    Returns:
        Formatted markdown string describing available actions
    """
    lines = []

    # Numerical actions
    if 'numerical' in action_space:
        lines.append("### Numerical Actions (DEF Values)")
        for name, config in action_space['numerical'].items():
            desc = config.get('description', '')
            min_val = config.get('min', 0)
            max_val = config.get('max', 50)
            default = config.get('default', 10)
            lines.append(f"- **{name}**: Range [{min_val}-{max_val}], Default: {default}")
            if desc:
                lines.append(f"  - {desc}")

    # Discrete actions (equipment)
    if 'discrete' in action_space:
        lines.append("")
        lines.append("### Equipment Options")
        for slot_name, slot_config in action_space['discrete'].items():
            slot_desc = slot_config.get('description', '')
            lines.append(f"- **{slot_name}**: {slot_desc}")
            for opt_id, opt in slot_config.get('options', {}).items():
                opt_name = opt.get('name', opt_id)
                opt_desc = opt.get('description', '')
                cost = opt.get('cost', 0)
                cost_str = f" (cost: {cost})" if cost > 0 else ""
                lines.append(f"  - `{opt_id}`: {opt_name}{cost_str}")
                if opt_desc:
                    lines.append(f"    - {opt_desc}")

    # Boolean actions
    if 'boolean' in action_space:
        lines.append("")
        lines.append("### Toggle Options")
        for name, config in action_space['boolean'].items():
            desc = config.get('description', '')
            default = config.get('default', False)
            lines.append(f"- **{name}**: Default: {'ON' if default else 'OFF'}")
            if desc:
                lines.append(f"  - {desc}")

    # Constraints
    if 'constraints' in action_space:
        lines.append("")
        lines.append("### Constraints")
        constraints = action_space['constraints']
        if 'total_def_budget' in constraints:
            lines.append(f"- Total DEF budget: {constraints['total_def_budget']}")
        if 'total_equipment_slots' in constraints:
            lines.append(f"- Equipment slots: {constraints['total_equipment_slots']}")

    return '\n'.join(lines) if lines else "(Action space not available)"


def format_equipment_schema(action_space: Dict[str, Any]) -> str:
    """
    Format equipment schema for API call documentation.

    Args:
        action_space: Action space from API

    Returns:
        JSON-like schema string for equipment field
    """
    if 'discrete' not in action_space:
        return ""

    parts = []
    for slot_name, slot_config in action_space['discrete'].items():
        options = list(slot_config.get('options', {}).keys())
        if options:
            parts.append(f"'{slot_name}': '{options[0]}'")

    if parts:
        return "equipment={" + ", ".join(parts) + "}"
    return ""


def load_experiment_prompt(
    experiment_name: str,
    api_config: Dict[str, Any],
    game_config: Optional[Dict[str, Any]] = None,
    action_space: Optional[Dict[str, Any]] = None,
    mode: str = "legacy"
) -> str:
    """
    Load and render an experiment's prompt with runtime configuration.

    Args:
        experiment_name: Name of the experiment
        api_config: Runtime config from API (total_drones, victory_threshold, etc.)
        game_config: Optional game.json config for component info
        action_space: Optional action space config from API
        mode: Execution mode - 'legacy' or 'hybrid'

    Returns:
        Fully rendered prompt string ready for the agent
    """
    # Load template (mode determines which file is loaded)
    template = load_prompt_template(experiment_name, mode=mode)

    # Build variables dict
    variables = {
        'experiment_name': experiment_name,
        'total_drones': api_config.get('total_drones', 200),
        'stage2_fleet_size': api_config.get('stage2_fleet_size', 1000),
        'victory_threshold': int(api_config.get('victory_threshold', 0.75) * 100),
        'deployment_budget': api_config.get('deployment_budget'),
        'max_tool_iterations': config.agent.execution.max_tool_iterations_per_turn,
    }

    # Format component list
    if game_config and 'drone' in game_config:
        components = game_config['drone'].get('components', {})
        variables['component_list'] = format_component_list(components)
        variables['design_schema'] = format_design_schema(components)
    elif 'standard_design' in api_config:
        # Fallback to standard_design from API
        design = api_config['standard_design']
        lines = [f"  - {k}: {v}" for k, v in design.items()]
        variables['component_list'] = '\n'.join(lines)
        variables['design_schema'] = str(design)
    else:
        variables['component_list'] = "  (Component list not available)"
        variables['design_schema'] = "{'component_def': int, ...}"

    # Format action space if available
    if action_space:
        variables['action_space'] = format_action_space(action_space)
        variables['equipment_schema'] = format_equipment_schema(action_space)
        variables['has_equipment'] = bool(action_space.get('discrete'))
    else:
        variables['action_space'] = "(Action space not available)"
        variables['equipment_schema'] = ""
        variables['has_equipment'] = False

    # Render and return
    return render_prompt(template, variables)


def get_available_experiments() -> list:
    """
    List all available experiments that have prompt templates.

    Returns:
        List of experiment names
    """
    experiments_dir = get_experiments_dir()
    experiments = []

    for item in experiments_dir.iterdir():
        if item.is_dir():
            prompt_file = item / "prompt.md"
            if prompt_file.exists():
                experiments.append(item.name)

    return sorted(experiments)


# Default fallback prompt (V2 style) for experiments without prompt.md
DEFAULT_PROMPT_TEMPLATE = """
You are an advanced Drone Designer working on a drone optimization project.
Your goal is to optimize drone designs for survival in a hostile environment.

## GAME INFORMATION
- Stage 1 Budget: {{total_drones}} drones for experimentation
- Stage 2 Fleet: {{stage2_fleet_size}} drones for final validation
- Victory Threshold: {{victory_threshold}}% survival rate

## COMPONENTS
{{component_list}}

## AVAILABLE METHODS
- `client.get_mission_data()` - Get flight history
- `client.get_all_environments()` - Get environment data
- `client.query_environment(query)` - Discover hidden variables
- `client.deploy_drone_v2(design, count=1)` - Deploy test drones
- `client.submit_final_design_v2(design)` - Final submission (once only!)

Think step-by-step, then provide a ```python code block``` to execute.
"""


def load_prompt_with_fallback(
    experiment_name: str,
    api_config: Dict[str, Any],
    game_config: Optional[Dict[str, Any]] = None,
    action_space: Optional[Dict[str, Any]] = None,
    mode: str = "legacy"
) -> str:
    """
    Load experiment prompt with fallback to default if not found.

    Args:
        experiment_name: Name of the experiment
        api_config: Runtime config from API
        game_config: Optional game.json config
        action_space: Optional action space config from API
        mode: Execution mode - 'legacy' or 'hybrid'

    Returns:
        Rendered prompt string
    """
    try:
        return load_experiment_prompt(experiment_name, api_config, game_config, action_space, mode=mode)
    except FileNotFoundError:
        # Use default template
        variables = {
            'total_drones': api_config.get('total_drones', 200),
            'stage2_fleet_size': api_config.get('stage2_fleet_size', 1000),
            'victory_threshold': int(api_config.get('victory_threshold', 0.75) * 100),
        }

        if 'standard_design' in api_config:
            design = api_config['standard_design']
            lines = [f"  - {k}: {v}" for k, v in design.items()]
            variables['component_list'] = '\n'.join(lines)
        else:
            variables['component_list'] = "  (See API for component details)"

        # Add action space info to default template
        if action_space:
            variables['action_space'] = format_action_space(action_space)
        else:
            variables['action_space'] = "(Action space not available)"

        return render_prompt(DEFAULT_PROMPT_TEMPLATE, variables)
