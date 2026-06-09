"""
Unified Agent Runner with Configuration Support

This script uses the centralized config.json for all settings.

The main entry points are:
- main(): CLI entry point for running a single agent session
- run_agent_session(): Programmatic entry point for async runners
"""

import os
import sys
import time
import traceback
import requests
from typing import Dict, Any, Optional

# Load environment variables (optional)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not required if env vars are set directly

# Add paths for imports
sys.path.append(os.path.join(os.path.dirname(__file__), 'api'))
sys.path.append(os.path.dirname(__file__))

# Import configuration
from config import config
from agent.gemini import GeminiHandler
from agent.openai import OpenAIHandler
from agent.anthropic import AnthropicHandler
from agent.grok import GrokHandler
from agent.aimlapi import AIMLAPIHandler
from agent.openrouter import OpenRouterHandler
from agent.base import Colors
from agent.client import CanyonClient
from agent.prompt_loader import load_prompt_with_fallback
from agent.orchestrator import AgentOrchestrator, ExecutionMode


def _load_experiment_standard_design(experiment_name: str) -> Optional[Dict[str, int]]:
    """
    Load standard_design from the experiment's game.json.

    Scopes the design to the actual experiment instead of whatever the
    backend's global default happens to be — e.g. antenna_trap has no
    shield_def but deployment_zone_trap does.
    """
    import json as _json
    path = os.path.join(os.path.dirname(__file__), "experiments", experiment_name, "game.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            game = _json.load(f)
        components = game.get("drone", {}).get("components", {})
        design = {}
        for comp_name, cfg in components.items():
            def_val = cfg.get("default_def", cfg.get("def", 0)) if isinstance(cfg, dict) else cfg
            design[f"{comp_name}_def"] = def_val
        return design or None
    except Exception:
        return None


def _load_experiment_action_space(experiment_name: str) -> Optional[Dict[str, Any]]:
    """
    Load action_space for the given experiment directly from its config.

    Bypasses the /api/v2/action_space HTTP endpoint which uses the backend's
    global default_experiment — unsafe under parallel sweeps where different
    agents are running different experiments concurrently.
    """
    try:
        from api.modules.action_space import get_action_space
        cfg = get_action_space(experiment_name)
        return cfg.get_agent_view()
    except Exception:
        return None


def get_model_config(model_name: str):
    """Get model configuration from config."""
    models = config.agent.models.available.to_dict()
    if model_name not in models:
        raise ValueError(f"Model '{model_name}' not found in config. Available: {list(models.keys())}")
    return models[model_name]

def create_agent_handler(model_name: str, system_instruction: str, enable_thinking: bool = True):
    """Create appropriate agent handler based on model provider."""
    model_config = get_model_config(model_name)
    provider = model_config['provider']
    # Use model_id if specified, otherwise use the config key as the model name
    actual_model_name = model_config.get('model_id', model_name)
    # Display name is the user-selected model name (e.g., "gpt-5.2-high")
    display_name = model_name

    handler = None

    if provider == 'google':
        # Gemini models
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable not set")

        handler = GeminiHandler(
            api_key=api_key,
            model_name=actual_model_name,
            base_url=config.server.api.base_url,
            system_instruction=system_instruction,
            enable_thinking=enable_thinking
        )

    elif provider == 'openai':
        # OpenAI models and OpenAI-compatible APIs (e.g., DeepSeek)
        # Check if this is a DeepSeek model
        if model_config.get('base_url', '').startswith('https://api.deepseek.com'):
            api_key = os.environ.get("DEEPSEEK_API_KEY")
            if not api_key:
                raise ValueError("DEEPSEEK_API_KEY environment variable not set")
            api_base_url = model_config.get('base_url')
        else:
            # Standard OpenAI models
            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY environment variable not set")
            api_base_url = None

        handler = OpenAIHandler(
            api_key=api_key,
            model_name=actual_model_name,
            base_url=config.server.api.base_url,
            system_instruction=system_instruction,
            api_base_url=api_base_url,
            reasoning_effort=model_config.get('reasoning_effort'),
            enable_thinking=enable_thinking,
        )

    elif provider == 'anthropic':
        # Anthropic Claude models
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable not set")

        handler = AnthropicHandler(
            api_key=api_key,
            model_name=actual_model_name,
            base_url=config.server.api.base_url,
            system_instruction=system_instruction,
            enable_thinking=enable_thinking,
            thinking_budget=10000,
        )

    elif provider == 'xai':
        # xAI Grok models
        api_key = os.environ.get("XAI_API_KEY")
        if not api_key:
            raise ValueError("XAI_API_KEY environment variable not set")

        handler = GrokHandler(
            api_key=api_key,
            model_name=actual_model_name,
            base_url=config.server.api.base_url,
            system_instruction=system_instruction
        )

    elif provider == 'aimlapi':
        # AIMLAPI models (DeepSeek, Qwen, etc.)
        api_key = os.environ.get("AIMLAPI_API_KEY")
        if not api_key:
            raise ValueError("AIMLAPI_API_KEY environment variable not set")

        handler = AIMLAPIHandler(
            api_key=api_key,
            model_name=actual_model_name,
            base_url=config.server.api.base_url,
            system_instruction=system_instruction
        )

    elif provider == 'openrouter':
        # OpenRouter models (open-source models via OpenRouter API)
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY environment variable not set")

        handler = OpenRouterHandler(
            api_key=api_key,
            model_name=actual_model_name,
            base_url=config.server.api.base_url,
            system_instruction=system_instruction,
            site_url=model_config.get('site_url'),
            site_name=model_config.get('site_name', 'CausalGame'),
            enable_thinking=model_config.get('enable_thinking', False),
        )

    else:
        raise ValueError(f"Unknown provider: {provider}")

    # Set display name for logs (user-selected name, not API model ID)
    handler.display_name = display_name
    return handler


def run_agent_session(
    model_name: str,
    experiment: Optional[str] = None,
    max_turns: int = 100,
    base_url: str = "http://localhost:8000",
    enable_thinking: bool = True,
    verbose: bool = False,
    execution_mode: str = "legacy",
) -> Dict[str, Any]:
    """
    Run a single agent session programmatically.

    This function is designed to be called from async runners or other scripts.
    It runs the full agent loop and returns structured results.

    Args:
        model_name: Model to use (e.g., 'gpt-5.2', 'gemini-2.5-flash')
        experiment: Experiment name (if None, uses server default)
        max_turns: Maximum turns before auto-submission
        base_url: Backend API URL
        enable_thinking: Enable thinking/reasoning for supported models
        verbose: Print detailed output (default: False for async usage)
        execution_mode: "hybrid" for tool calling + analysis, "legacy" for code execution

    Returns:
        Dict with:
            success: bool - Whether session completed without errors
            victory: Optional[bool] - Whether agent achieved victory threshold
            survival_rate: Optional[float] - Final survival rate (e.g., 0.75)
            error: Optional[str] - Error message if failed
            session_id: str - Session ID for tracking
            turns: int - Number of turns used
            drones_used: int - Number of drones deployed
    """

    def log(msg: str):
        if verbose:
            print(msg)

    result = {
        'success': False,
        'victory': None,
        'survival_rate': None,
        'error': None,
        'session_id': None,
        'turns': 0,
        'drones_used': 0,
    }

    try:
        model_config = get_model_config(model_name)
    except ValueError as e:
        result['error'] = str(e)
        return result

    log(f"{Colors.CYAN}=== run_agent_session ==={Colors.RESET}")
    log(f"Model: {model_name} ({model_config['provider']})")
    log(f"Experiment: {experiment or 'server default'}")
    log(f"Max Turns: {max_turns}")

    # Reset Simulation first
    log(f"{Colors.YELLOW}[SYSTEM] Resetting Simulation...{Colors.RESET}")
    try:
        reset_url = f"{base_url}/api/agent/reset"
        response = requests.post(reset_url, timeout=5)
        log(f"{Colors.GREEN}[SYSTEM] {response.json().get('message', 'Reset complete')}{Colors.RESET}")
    except Exception as e:
        log(f"{Colors.RED}[ERROR] Failed to reset simulation: {e}{Colors.RESET}")

    # Get game config from API
    api_version = "v1"
    experiment_name = experiment or os.environ.get('CAUSALGAME_EXPERIMENT', 'base')

    try:
        status_url = f"{base_url}/api/v1/mission_status"
        status_response = requests.get(status_url, timeout=5).json()
        api_standard_design = status_response.get('standard_design', {})
        api_hp_per_drone = status_response.get('hp_per_drone', 600)
        api_total_drones = status_response.get('total_drones', 50)
        api_total_hp = status_response.get('total_hp', 30000)
        api_stage2_fleet_size = status_response.get('stage2_fleet_size', 50)
        api_victory_threshold = status_response.get('victory_threshold', 0.55)

        # Check if V2 API
        api_deployment_budget = None
        try:
            v2_status = requests.get(f"{base_url}/api/v2/mission_status", timeout=5).json()
            if v2_status.get('api_version') == 'v2':
                api_version = "v2"
                api_standard_design = v2_status.get('standard_design', {})
                api_total_drones = v2_status.get('total_drone_budget', 200)
                api_stage2_fleet_size = v2_status.get('stage2_fleet_size', 1000)
                api_victory_threshold = v2_status.get('victory_threshold', 0.55)
                api_deployment_budget = v2_status.get('stage1_deployment_budget')
                # Do NOT overwrite experiment_name with the backend's global default —
                # under parallel sweeps the backend's default may differ from this session's
                # experiment. Trust the CLI/env value set above.
                log(f"{Colors.CYAN}[SYSTEM] Detected V2 API - Experiment: {experiment_name}{Colors.RESET}")
        except Exception:
            pass

        if api_deployment_budget is None:
            api_deployment_budget = config.game.resources.to_dict().get('stage1_deployment_budget') if hasattr(config.game.resources, 'to_dict') else None

        log(f"{Colors.GREEN}[SYSTEM] Loaded experiment config (API Version: {api_version}){Colors.RESET}")

    except Exception as e:
        log(f"{Colors.YELLOW}[WARNING] Failed to get config from API: {e}{Colors.RESET}")
        api_standard_design = config.game.drone.standard_design.to_dict()
        api_hp_per_drone = config.game.resources.hp_per_drone
        api_total_drones = config.game.resources.total_drone_budget
        api_total_hp = api_total_drones * api_hp_per_drone
        api_stage2_fleet_size = 50
        api_victory_threshold = 0.55

    # Load experiment-specific prompt
    api_config = {
        'total_drones': api_total_drones,
        'stage2_fleet_size': api_stage2_fleet_size,
        'victory_threshold': api_victory_threshold,
        'deployment_budget': api_deployment_budget,
        'standard_design': api_standard_design,
        'hp_per_drone': api_hp_per_drone if api_version == "v1" else None,
        'total_hp': api_total_hp if api_version == "v1" else None,
    }

    # Get action space configuration — load scoped to the session's experiment
    # (NOT from /api/v2/action_space, which returns the backend's global default
    # and thus leaks the wrong action_space under parallel sweeps).
    action_space = None
    if api_version == "v2":
        action_space = _load_experiment_action_space(experiment_name)

    if api_version == "v2":
        # Load appropriate prompt based on execution mode
        prompt_mode = "hybrid" if execution_mode == "hybrid" else "legacy"
        system_instruction = load_prompt_with_fallback(experiment_name, api_config, action_space=action_space, mode=prompt_mode)
    else:
        # V1: Use legacy hardcoded prompt
        system_instruction = f"""
You are an advanced Drone Designer.
Your goal is to test a simulation environment and optimize drone designs for survival.
The simulation is a "black box" - you do not know the rules, but you can learn them through observation and experimentation.

- OBSERVE: Look for patterns in what remains and what is broken.
- DISCOVER: **Not all environmental data is initially visible!**
  - Ask about weather, atmospheric conditions, or any environmental factors.
  - Newly discovered variables become accessible through the API.
- CORRELATE: **Query environmental data** for past missions.
  - EFFICIENCY TIP: Use `client.get_all_environments()` to fetch ALL environmental data at once.
  - Initially visible: Wind Speed, Humidity, Temperature, UV Index
  - More measurements may exist - ask the archivist to find them!
- HYPOTHESIZE: Why did specific parts break? Was it random, or environmental?
- TEST: Use `client.deploy_drone` to test your theories.
- **GOAL**: Design a drone that can survive the Canyon.

GAME FLOW:
1. **STAGE 1 (Exploration)**: Use `client.deploy_drone` to test hypotheses. You have {api_total_drones} drones to learn the rules.
2. **STAGE 2 (Validation)**: When you have found the optimal design, call `client.submit_final_design(design)`.
   - This will run {api_stage2_fleet_size} final simulations and give you the final survival rate.
   - **WARNING**: You can only submit ONCE. This is an irreversible decision.
   - **CRITICAL**: You MUST submit a final design before the mission ends. Do NOT exceed the turn limit without submitting.
   - This is the WIN CONDITION. Analyze data thoroughly, then submit your best design.

IMPORTANT: RESOURCE CONSTRAINTS
- You have a **DRONE BUDGET** ({api_total_drones} Max) and an **HP BUDGET** ({api_total_hp} Max).
- **COST MODEL**: The HP Budget uses **ABSOLUTE HP** (sum of all component HP values).
  - Each drone costs: engine + cockpit + wing + body + antenna + camera + gun HP
  - Reference Design: {', '.join(f'{k}={v}' for k, v in api_standard_design.items())} (Total: {sum(api_standard_design.values())} HP)
  - Average HP per drone: {api_hp_per_drone}

You have access to a **PYTHON REPL**.
- Use `print()` to see results.
- `client` is pre-defined (canyon_client instance).
- `pd` (pandas) and `np` (numpy) are available.

AVAILABLE METHODS:
- `client.get_history() -> List[Dict]`: Historical flight logs
- `client.get_mission_environment(mission_id: str) -> Dict`: Single environment (only visible variables)
- `client.get_all_environments() -> Dict[str, Dict]`: All environments at once (only visible variables)
- `client.get_discovery_stats() -> Dict`: Check discovery progress and statistics
- `client.deploy_drone(design: Dict[str, int], count: int) -> Dict`: Deploy drones
- `client.get_status() -> Dict`: Current budget status
- `client.submit_final_design(design: Dict) -> Dict`: **FINAL STEP** (one-time only)

FORMAT:
Explain your thinking, then provide a single ```python code block``` to execute.
"""

    # Initialize Agent
    try:
        agent = create_agent_handler(model_name, system_instruction, enable_thinking)
        log(f"{Colors.GREEN}[SYSTEM] Agent initialized successfully.{Colors.RESET}")
    except Exception as e:
        result['error'] = f"Failed to initialize agent: {e}"
        return result

    # Create Client with session registration
    try:
        client = CanyonClient(
            base_url=base_url,
            model_name=model_name,
            agent_name=f"agent-{model_name}",
            experiment=experiment,
            execution_mode=execution_mode,
            auto_register=True
        )
        result['session_id'] = client._session_id
        log(f"{Colors.GREEN}[SYSTEM] Session registered: {client._session_id}{Colors.RESET}")

        # Refresh victory_threshold from the actual session (not default experiment)
        try:
            session_status = client.get_status()
            api_victory_threshold = session_status.get('victory_threshold', api_victory_threshold)
            log(f"{Colors.GREEN}[SYSTEM] Victory threshold: {api_victory_threshold * 100:.0f}%{Colors.RESET}")
        except Exception as e:
            log(f"{Colors.YELLOW}[WARNING] Could not refresh victory threshold: {e}{Colors.RESET}")

        # Load standard_design scoped to this session's experiment (fixes cross-experiment
        # contamination like submitting shield_def into antenna_trap).
        exp_for_design = experiment or experiment_name
        scoped_design = _load_experiment_standard_design(exp_for_design)
        if scoped_design:
            api_standard_design = scoped_design
            api_config['standard_design'] = scoped_design
    except Exception as e:
        result['error'] = f"Failed to register session: {e}"
        return result

    # Setup execution mode
    mode = ExecutionMode.HYBRID if execution_mode == "hybrid" else ExecutionMode.LEGACY

    # Create orchestrator with explicit client (no hidden injection)
    # Pass session_id for workspace isolation in HYBRID mode
    # Use provided max_turns or let orchestrator use its defaults
    orchestrator = AgentOrchestrator(
        handler=agent,
        client=client,
        mode=mode,
        session_id=client._session_id,
        max_turns=max_turns if max_turns != 100 else None,  # None = use mode defaults
        deployment_budget=api_deployment_budget,
    )

    # Inject client into agent's locals for logging (needed in both modes)
    # Also allows run_code to work with `client` variable in legacy mode
    agent.locals['client'] = client

    # Use orchestrator's max_turns (may differ from input if using defaults)
    effective_max_turns = orchestrator.max_turns

    log(f"{Colors.CYAN}[SYSTEM] Execution mode: {execution_mode}{Colors.RESET}")
    log(f"{Colors.CYAN}[SYSTEM] Max turns: {effective_max_turns}{Colors.RESET}")
    if api_deployment_budget:
        log(f"{Colors.CYAN}[SYSTEM] Deployment budget: {api_deployment_budget} calls{Colors.RESET}")
    if mode == ExecutionMode.HYBRID and orchestrator.workspace:
        log(f"{Colors.CYAN}[SYSTEM] Workspace: {orchestrator.workspace.get_workspace_path()}{Colors.RESET}")

    # Sync max_turns to backend for tracking
    try:
        client.update_session_config(max_turns=effective_max_turns)
    except Exception:
        pass  # Non-critical

    # Create step function that uses orchestrator or agent based on mode
    def do_step(prompt: str, log_type: str = "THOUGHT"):
        """Execute a step using orchestrator (hybrid) or agent (legacy)."""
        if mode == ExecutionMode.HYBRID:
            step_result = orchestrator.step(prompt, log_type)
            # Check mission complete
            if step_result.mission_complete:
                agent.mission_complete = True
            return step_result
        else:
            # Legacy mode uses agent.step directly
            agent.step(prompt, log_type=log_type)
            return None

    # Initial Analysis
    log(f"{Colors.BLUE}[SYSTEM] Accessing Historical Archives...{Colors.RESET}")
    try:
        initial_data = client.get_history()
        survivors = [d for d in initial_data if d['status'] in ("RETURNED", "SURVIVED")] if isinstance(initial_data, list) else []
        total_records = len(initial_data) if isinstance(initial_data, list) else 0
        initial_survival_rate = (len(survivors) / total_records * 100) if total_records > 0 else 0

        log(f"{Colors.BLUE}[SYSTEM] Found {total_records} historical records.{Colors.RESET}")
        log(f"{Colors.BLUE}[SYSTEM] Historical Survival Rate: {initial_survival_rate:.1f}%{Colors.RESET}")

        # Build mode-specific initial prompt
        if mode == ExecutionMode.HYBRID:
            initial_prompt = f"""
MISSION START.
Reviewing Historical Archives...
Found {total_records} prior flight logs.
Global Survival Rate: {initial_survival_rate:.1f}% ({len(survivors)}/{total_records})

Your goal is to IMPROVE this survival rate by finding the optimal drone design.

**EXECUTION MODE: HYBRID (Tool Calling + Code Analysis)**
- Use TOOLS for API operations: `get_history`, `deploy_drone`, `submit_final_design`, etc.
- Use Python code blocks ONLY for data analysis with pandas/numpy
- Do NOT use `client.xxx()` in code - use the corresponding TOOL instead!

**IMPORTANT WORKFLOW:**
1. **EXPLORE FIRST**: Use `get_history` tool to get data, then analyze with pandas in code
3. **TEST HYPOTHESES**: Use `deploy_drone` tool to test different designs (you have many drones!)
4. **ITERATE**: Analyze results and refine your design
5. **SUBMIT ONLY AFTER EXPLORATION**: Use `submit_final_design` tool ONLY when you have gathered enough data

**WARNING**: Do NOT call `submit_final_design` until you have:
- Analyzed historical data
- Discovered environmental factors
- Tested multiple drone designs with `deploy_drone`

Start by using the `get_history` TOOL to retrieve historical data.
"""
        else:
            initial_prompt = f"""
MISSION START.
Reviewing Historical Archives...
Found {total_records} prior flight logs.
Global Survival Rate: {initial_survival_rate:.1f}% ({len(survivors)}/{total_records})

Your goal is to improve this.
Start by analyzing the provided historical data using `client.get_history()` to understand why previous drones failed (or survived).
"""
        do_step(initial_prompt)
    except Exception as e:
        log(f"{Colors.RED}[ERROR] Failed to fetch initial intelligence: {e}{Colors.RESET}")
        do_step("Starting mission. Fetch mission data first.")

    # Main Loop
    drones_used = 0
    total_drones = api_total_drones
    grace_turns_used = 0  # Track turns after resources exhausted
    max_grace_turns = 3   # Give agent 3 turns to submit after resources exhausted
    resources_exhausted = False
    idle_turns = 0  # Track consecutive turns without deploy or submit
    max_idle_turns = 10  # Force-submit after 10 idle turns
    last_deployments = 0  # Track deployments at start of each turn
    error_cycle_count = 0  # Track consecutive action cycles ending in error
    max_error_cycles = 5  # Force-submit after 5 consecutive failed cycles

    log(f"\n{Colors.GREEN}[SYSTEM] Starting Exploration Phase...{Colors.RESET}\n")

    while orchestrator.current_turn < effective_max_turns or (resources_exhausted and grace_turns_used < max_grace_turns):
        try:
            status = client.get_status()
            remaining = status['drones_remaining']
            drones_used = total_drones - remaining
            result['drones_used'] = drones_used
            result['turns'] = orchestrator.current_turn + 1  # Will be incremented in step()
            has_submitted = status.get('final_evaluation') is not None

            # Check if agent already submitted
            if has_submitted:
                log(f"{Colors.GREEN}[SYSTEM] Final design submitted.{Colors.RESET}")
                break

            # Check if resources exhausted (drones or turns)
            turns_at_limit = orchestrator.current_turn >= effective_max_turns
            if (remaining <= 0 or turns_at_limit) and not resources_exhausted:
                resources_exhausted = True
                if remaining <= 0:
                    log(f"{Colors.YELLOW}[SYSTEM] All drones deployed. Agent has {max_grace_turns} turns to submit final design.{Colors.RESET}")
                else:
                    log(f"{Colors.YELLOW}[SYSTEM] Turn limit reached. Agent has {max_grace_turns} turns to submit final design.{Colors.RESET}")

            # If in grace period, count turns and prompt urgently
            if resources_exhausted:
                grace_turns_used += 1
                # Sync grace period state to orchestrator
                orchestrator.resources_exhausted = True
                orchestrator.grace_turns_used = grace_turns_used
                if grace_turns_used > max_grace_turns:
                    log(f"{Colors.RED}[SYSTEM] Grace period expired. Forcing submission.{Colors.RESET}")
                    break

            # Build context (turn info and warnings are added by orchestrator)
            # Calculate turns remaining for instruction adjustment
            turns_remaining = effective_max_turns - orchestrator.current_turn

            if api_version == "v2":
                if mode == ExecutionMode.HYBRID:
                    # Adjust instruction based on urgency
                    if resources_exhausted:
                        # Grace period - urgent submission required
                        grace_remaining = max_grace_turns - grace_turns_used + 1
                        instruction = f"""🚨🚨🚨 CRITICAL: RESOURCES EXHAUSTED! 🚨🚨🚨
You have used all available resources (drones or turns).
You have {grace_remaining} turn(s) remaining to submit your final design.

INSTRUCTION:
- Call `submit_final_design` IMMEDIATELY with your best design!
- Do NOT attempt to deploy more drones - you have none left!
- Analyze your deployment history and submit the design with the highest survival rate.
- If you do not submit within {grace_remaining} turn(s), the system will auto-submit for you."""
                    elif turns_remaining <= 1:
                        instruction = """INSTRUCTION:
🚨 FINAL TURN! You MUST call `submit_final_design` NOW with your best design!
- Do NOT deploy more drones - submit immediately!
- Use your analysis to choose the best DEF values."""
                    elif turns_remaining <= 3:
                        instruction = """INSTRUCTION:
⚠️ TIME CRITICAL: Finalize your design and prepare to submit!
- You may do ONE more deployment to confirm, then SUBMIT.
- Call `submit_final_design` before you run out of turns!"""
                    else:
                        instruction = """INSTRUCTION:
- Continue exploring with `deploy_drone` to gather more data.
- Analyze patterns before optimizing your design.
- Only submit when you have sufficient evidence for your design choices."""

                    context = f"""STATUS UPDATE:
- Drones Remaining: {remaining}
- Final Design Submitted: {"YES ✓" if has_submitted else "NO (submit only after thorough exploration!)"}

{instruction}
"""
                else:
                    context = f"""STATUS UPDATE:
- Drones Remaining: {remaining}
- Final Design Submitted: {"YES ✓" if has_submitted else "NO (REQUIRED!)"}

INSTRUCTION:
- Use tools to deploy drones and analyze results.
- Submit your final design before running out of turns.
"""
            else:
                context = f"""STATUS UPDATE:
- Drones Remaining: {remaining}
- HP Budget Remaining: {status['hp_remaining']}
- Final Design Submitted: {"YES ✓" if has_submitted else "NO (REQUIRED!)"}

INSTRUCTION:
- You MUST use all {total_drones} drones to gather maximum data.
- Do NOT stop until Drones Remaining is 0 or you submit your final design.
"""
            do_step(context)

            # Detect idle spinning: no deploy or submit action this turn
            try:
                current_status = client.get_status()
                current_deployments = current_status.get('deployments_used', 0)
                current_submitted = current_status.get('final_evaluation') is not None
                if current_deployments == last_deployments and not current_submitted:
                    idle_turns += 1
                    if idle_turns >= max_idle_turns:
                        log(f"{Colors.RED}[SYSTEM] Agent idle for {idle_turns} consecutive turns (no deploy/submit). Forcing submission.{Colors.RESET}")
                        break
                else:
                    idle_turns = 0
                last_deployments = current_deployments
            except Exception:
                pass  # Non-critical

            # Detect error loop: consecutive THOUGHT→ACTION→ERROR cycles (legacy mode)
            try:
                agent_logs = getattr(agent, 'logs', None) or getattr(orchestrator, 'logs', None) or []
                if agent_logs and len(agent_logs) >= 1:
                    last_type = agent_logs[-1].get('type', '')
                    if last_type == 'ERROR':
                        error_cycle_count += 1
                    elif last_type in ('ACTION',) and current_deployments > last_deployments:
                        error_cycle_count = 0  # Successful deploy resets
                    if error_cycle_count >= max_error_cycles:
                        log(f"{Colors.RED}[SYSTEM] {error_cycle_count} consecutive failed action cycles. Forcing submission.{Colors.RESET}")
                        break
            except Exception:
                pass  # Non-critical

            # Update token usage periodically (every step)
            try:
                token_usage = agent.get_token_usage()
                client.update_token_usage(
                    input_tokens=token_usage["input_tokens"],
                    output_tokens=token_usage["output_tokens"]
                )
            except Exception:
                pass  # Non-critical, don't break the loop

            if agent.mission_complete or orchestrator.mission_complete:
                log(f"{Colors.CYAN}[SYSTEM] Agent signaled mission complete.{Colors.RESET}")
                break

        except KeyboardInterrupt:
            log(f"\n{Colors.YELLOW}[SYSTEM] Interrupted by user.{Colors.RESET}")
            try:
                client.report_error("Interrupted by user", error_type="user_interrupt", fatal=True)
            except Exception:
                pass
            result['error'] = "Interrupted by user"
            return result
        except Exception as e:
            error_msg = str(e)
            log(f"{Colors.RED}[ERROR] Loop failed: {error_msg}{Colors.RESET}")
            try:
                client.report_error(error_msg, error_type="agent_error", fatal=True)
            except Exception:
                pass
            result['error'] = error_msg
            return result

    # Force submission if not submitted
    try:
        final_status = client.get_status()
        if final_status.get('final_evaluation') is None:
            log(f"\n{Colors.RED}[SYSTEM] ⚠️  NO FINAL DESIGN SUBMITTED — recording as N/A.{Colors.RESET}")
            log(f"{Colors.YELLOW}[SYSTEM] The agent did not call submit_final_design successfully. "
                f"Under the current evaluation policy, this run is not scored (no fallback design is submitted).{Colors.RESET}")
    except Exception as e:
        log(f"{Colors.RED}[ERROR] Failed to check final status: {e}{Colors.RESET}")

    # Get final results and request reflection
    try:
        final_status = client.get_status()
        final_eval = final_status.get('final_evaluation')

        # Only proceed if we have actual survival data (not just truthy but empty)
        if final_eval and final_eval.get('survived') is not None:
            result['success'] = True
            result['victory'] = final_eval.get('victory', False)

            # Parse survival_rate (could be string like "75.0%" or float)
            survival_rate = final_eval.get('survival_rate')
            if isinstance(survival_rate, str):
                survival_rate = float(survival_rate.rstrip('%')) / 100.0
            result['survival_rate'] = survival_rate

            log(f"{Colors.GREEN}=== MISSION COMPLETE ==={Colors.RESET}")
            log(f"Victory: {result['victory']}")
            log(f"Survival Rate: {result['survival_rate']}")

            # Build final report for reflection
            if api_version == "v2":
                final_report = f"""
MISSION REPORT:
OFFICIAL RESULT (Stage 2):
- Survival Rate: {final_eval.get('survival_rate', 'N/A')}
- Survivors: {final_eval.get('survived', 'N/A')}/{final_eval.get('fleet_size', api_stage2_fleet_size)}
- Victory: {'YES' if final_eval.get('victory') else 'NO'}
Exploration: {drones_used} drones used in Stage 1.
"""
            else:
                final_report = f"""
MISSION REPORT:
OFFICIAL RESULT (Stage 2): {final_eval.get('survival_rate', 'N/A')} Survival ({final_eval.get('survived', 'N/A')}/50)
Design Cost: {final_eval.get('cost_used', final_eval.get('cost_per_drone', 'N/A'))}
Exploration Efficiency: {drones_used} drones used to find solution.
"""

            # Request final reflection from agent
            log(f"{Colors.CYAN}[SYSTEM] Requesting Final Agent Reflection...{Colors.RESET}")
            victory_threshold_pct = final_status.get('victory_threshold', api_victory_threshold) * 100
            reflection_prompt = f"""
{final_report}

[INSTRUCTION]
Analyze the Mission Report above. DO NOT call any tools - just provide your analysis in plain text.
1. Did you solve the task? (Survival Rate > {victory_threshold_pct:.0f}% is considered a success).
2. What was the key to survival?
3. Why did some drones fail?
4. Final Conclusion.
"""
            agent.mission_complete = False  # Allow reflection
            orchestrator.mission_complete = False
            do_step(reflection_prompt, log_type="REPORT")

        else:
            result['success'] = False
            result['error'] = "No final evaluation received"

    except Exception as e:
        result['error'] = f"Failed to get final status: {e}"

    # Report token usage
    try:
        token_usage = agent.get_token_usage()
        client.update_token_usage(
            input_tokens=token_usage["input_tokens"],
            output_tokens=token_usage["output_tokens"]
        )
    except Exception:
        pass

    # Export records
    try:
        client.export_records()
    except Exception:
        pass

    log(f"{Colors.GREEN}[SYSTEM] Agent session ended.{Colors.RESET}")
    return result


def main():
    """Run the agent with configuration-driven settings."""

    # Parse command line arguments for model selection
    import argparse
    parser = argparse.ArgumentParser(description='Run CausalGame Agent')
    parser.add_argument('--model', type=str, default=None,
                      help=f'Model to use (overrides AGENT_MODEL env var and config default)')
    parser.add_argument('--list-models', action='store_true',
                      help='List available models and exit')
    parser.add_argument('--thinking', action='store_true', default=True,
                      help='Enable thinking/reasoning for Gemini 3 models (default: True)')
    parser.add_argument('--no-thinking', action='store_true',
                      help='Disable thinking/reasoning for Gemini 3 models')
    parser.add_argument('--resume', type=str, default=None,
                      help='Resume an interrupted session by session ID')
    parser.add_argument('--experiment', type=str, default=None,
                      help='Experiment name (if not specified, uses server default)')
    parser.add_argument('--mode', type=str, choices=['hybrid', 'legacy'], default='legacy',
                      help='Execution mode: "hybrid" for tool calling + analysis, "legacy" for code execution (default: legacy)')
    args = parser.parse_args()

    # Handle thinking flag
    enable_thinking = args.thinking and not args.no_thinking

    # Handle execution mode
    execution_mode = args.mode

    # List models if requested
    if args.list_models:
        print(f"{Colors.CYAN}=== Available Models ==={Colors.RESET}")
        models_dict = config.agent.models.available.to_dict()
        for name, cfg in models_dict.items():
            is_default = " (default)" if name == config.agent.models.default else ""
            print(f"  {Colors.GREEN}{name}{Colors.RESET}{is_default}")
            print(f"    Provider: {cfg['provider']}")
            print(f"    Description: {cfg['description']}")
            print(f"    Recommended for: {cfg['recommended_for']}")
            print()
        return

    # Select model with priority: CLI arg > ENV var > config default
    model_name = args.model or os.environ.get('AGENT_MODEL') or config.agent.models.default
    model_config = get_model_config(model_name)

    # Show model source
    model_source = "CLI argument" if args.model else ("AGENT_MODEL env" if os.environ.get('AGENT_MODEL') else "config default")

    print(f"{Colors.CYAN}=== CausalGame Agent Runner ==={Colors.RESET}")
    print(f"Backend: {config.server.api.base_url}")
    print(f"Model: {model_name} ({model_config['provider']}) [{model_source}]")
    print(f"Description: {model_config['description']}")
    print(f"Execution Mode: {execution_mode}")
    if "gemini-3" in model_name:
        thinking_status = "enabled" if enable_thinking else "disabled"
        print(f"Thinking: {thinking_status} (use --no-thinking to disable)")
    # Note: Actual max_turns is calculated later based on deployment_budget and mode
    print()

    # Reset Simulation first to get current experiment config (skip if resuming)
    resume_session_id = args.resume
    if not resume_session_id:
        print(f"{Colors.YELLOW}[SYSTEM] Resetting Simulation...{Colors.RESET}")
        try:
            reset_url = config.get_api_url('reset')
            response = requests.post(reset_url, timeout=5)
            print(f"{Colors.GREEN}[SYSTEM] {response.json().get('message', 'Reset complete')}{Colors.RESET}")
        except Exception as e:
            print(f"{Colors.RED}[ERROR] Failed to reset simulation: {e}{Colors.RESET}")
    else:
        print(f"{Colors.CYAN}[SYSTEM] Resuming session: {resume_session_id}{Colors.RESET}")

    # Determine experiment name EARLY so it's used consistently throughout setup
    # (standard_design, action_space, prompt). Priority: CLI arg > env var > 'base'.
    experiment_name = args.experiment or os.environ.get('CAUSALGAME_EXPERIMENT', 'base')

    # Get game config from API (uses current experiment's settings)
    api_version = "v1"  # Default to V1
    try:
        status_url = config.get_api_url('mission_status')
        status_response = requests.get(status_url, timeout=5).json()
        api_standard_design = status_response.get('standard_design', {})
        api_hp_per_drone = status_response.get('hp_per_drone', 600)
        api_total_drones = status_response.get('total_drones', 50)
        api_total_hp = status_response.get('total_hp', 30000)
        api_stage2_fleet_size = status_response.get('stage2_fleet_size', 50)
        api_victory_threshold = status_response.get('victory_threshold', 0.55)

        # Check if V2 API by trying V2 endpoint
        api_deployment_budget = None  # Optional deployment call limit
        # experiment_name already set above from CLI/env — do NOT re-derive here.
        try:
            v2_status = requests.get(f"{config.server.api.base_url}/api/v2/mission_status", timeout=5).json()
            if v2_status.get('api_version') == 'v2':
                api_version = "v2"
                api_standard_design = v2_status.get('standard_design', {})
                api_total_drones = v2_status.get('total_drone_budget', 200)
                api_stage2_fleet_size = v2_status.get('stage2_fleet_size', 1000)
                api_victory_threshold = v2_status.get('victory_threshold', 0.55)
                api_deployment_budget = v2_status.get('stage1_deployment_budget')
                # Do NOT overwrite experiment_name with backend's global default.
                print(f"{Colors.CYAN}[SYSTEM] Detected V2 API - Experiment: {experiment_name}{Colors.RESET}")
        except Exception:
            pass  # Not a V2 experiment

        # Override standard_design with the experiment-scoped value (fixes shield_def etc.)
        scoped_design = _load_experiment_standard_design(experiment_name)
        if scoped_design:
            api_standard_design = scoped_design

        # Try to get deployment budget from game config if not from API
        if api_deployment_budget is None:
            api_deployment_budget = config.game.resources.to_dict().get('stage1_deployment_budget') if hasattr(config.game.resources, 'to_dict') else None

        print(f"{Colors.GREEN}[SYSTEM] Loaded experiment config from API (API Version: {api_version}){Colors.RESET}")
        if api_version == "v2":
            print(f"  Standard Design (DEF): {api_standard_design}")
            print(f"  Stage 1 drones: {api_total_drones}, Stage 2 fleet: {api_stage2_fleet_size}")
            print(f"  Victory threshold: {api_victory_threshold * 100:.0f}%")
            if api_deployment_budget is not None:
                print(f"  Deployment budget: {api_deployment_budget} calls")
        else:
            print(f"  Standard Design: {api_standard_design}")
            print(f"  HP per drone: {api_hp_per_drone}, Total HP: {api_total_hp}")
            print(f"  Stage 1 drones: {api_total_drones}, Stage 2 fleet: {api_stage2_fleet_size}")
    except Exception as e:
        print(f"{Colors.YELLOW}[WARNING] Failed to get config from API, using local config: {e}{Colors.RESET}")
        api_standard_design = config.game.drone.standard_design.to_dict()
        api_hp_per_drone = config.game.resources.hp_per_drone
        api_total_drones = config.game.resources.total_drone_budget
        api_total_hp = api_total_drones * api_hp_per_drone
        api_stage2_fleet_size = 50
        api_victory_threshold = 0.55

    # Load experiment-specific prompt
    api_config = {
        'total_drones': api_total_drones,
        'stage2_fleet_size': api_stage2_fleet_size,
        'victory_threshold': api_victory_threshold,
        'deployment_budget': api_deployment_budget,
        'standard_design': api_standard_design,
        'hp_per_drone': api_hp_per_drone if api_version == "v1" else None,
        'total_hp': api_total_hp if api_version == "v1" else None,
    }

    print(f"{Colors.BLUE}[SYSTEM] Loading prompt for experiment: {experiment_name}{Colors.RESET}")

    # Get action space configuration — load scoped to this session's experiment
    # to avoid the global-state bug in /api/v2/action_space under parallel sweeps.
    action_space = None
    if api_version == "v2":
        action_space = _load_experiment_action_space(experiment_name)
        if action_space and action_space.get('discrete'):
            print(f"{Colors.GREEN}[SYSTEM] Action space loaded with equipment options{Colors.RESET}")

    if api_version == "v2":
        # V2: Load experiment-specific prompt from experiments/<name>/prompt.md
        # Use mode-specific prompt (hybrid uses no_tool_def_prompt.md)
        prompt_mode = "hybrid" if execution_mode == "hybrid" else "legacy"
        system_instruction = load_prompt_with_fallback(experiment_name, api_config, action_space=action_space, mode=prompt_mode)
        print(f"{Colors.GREEN}[SYSTEM] Loaded experiment prompt: {experiment_name} (mode: {prompt_mode}){Colors.RESET}")
    else:
        # V1: Use legacy hardcoded prompt (for backward compatibility)
        system_instruction = f"""
You are an advanced Drone Designer.
Your goal is to test a simulation environment and optimize drone designs for survival.
The simulation is a "black box" - you do not know the rules, but you can learn them through observation and experimentation.

- OBSERVE: Look for patterns in what remains and what is broken.
- DISCOVER: **Not all environmental data is initially visible!**
  - Ask about weather, atmospheric conditions, or any environmental factors.
  - Newly discovered variables become accessible through the API.
- CORRELATE: **Query environmental data** for past missions.
  - EFFICIENCY TIP: Use `client.get_all_environments()` to fetch ALL environmental data at once.
  - Initially visible: Wind Speed, Humidity, Temperature, UV Index
  - More measurements may exist - ask the archivist to find them!
- HYPOTHESIZE: Why did specific parts break? Was it random, or environmental?
- TEST: Use `client.deploy_drone` to test your theories.
- **GOAL**: Design a drone that can survive the Canyon.

GAME FLOW:
1. **STAGE 1 (Exploration)**: Use `client.deploy_drone` to test hypotheses. You have {api_total_drones} drones to learn the rules.
2. **STAGE 2 (Validation)**: When you have found the optimal design, call `client.submit_final_design(design)`.
   - This will run {api_stage2_fleet_size} final simulations and give you the final survival rate.
   - **WARNING**: You can only submit ONCE. This is an irreversible decision.
   - **CRITICAL**: You MUST submit a final design before the mission ends. Do NOT exceed the turn limit without submitting.
   - This is the WIN CONDITION. Analyze data thoroughly, then submit your best design.

IMPORTANT: RESOURCE CONSTRAINTS
- You have a **DRONE BUDGET** ({api_total_drones} Max) and an **HP BUDGET** ({api_total_hp} Max).
- **COST MODEL**: The HP Budget uses **ABSOLUTE HP** (sum of all component HP values).
  - Each drone costs: engine + cockpit + wing + body + antenna + camera + gun HP
  - Reference Design: {', '.join(f'{k}={v}' for k, v in api_standard_design.items())} (Total: {sum(api_standard_design.values())} HP)
  - Average HP per drone: {api_hp_per_drone}

You have access to a **PYTHON REPL**.
- Use `print()` to see results.
- `client` is pre-defined (canyon_client instance).
- `pd` (pandas) and `np` (numpy) are available.

AVAILABLE METHODS:
- `client.get_history() -> List[Dict]`: Historical flight logs
- `client.get_mission_environment(mission_id: str) -> Dict`: Single environment (only visible variables)
- `client.get_all_environments() -> Dict[str, Dict]`: All environments at once (only visible variables)
- `client.get_discovery_stats() -> Dict`: Check discovery progress and statistics
- `client.deploy_drone(design: Dict[str, int], count: int) -> Dict`: Deploy drones
- `client.get_status() -> Dict`: Current budget status
- `client.submit_final_design(design: Dict) -> Dict`: **FINAL STEP** (one-time only)

FORMAT:
Explain your thinking, then provide a single ```python code block``` to execute.
"""

    # Initialize Agent
    try:
        agent = create_agent_handler(model_name, system_instruction, enable_thinking)
        print(f"{Colors.GREEN}[SYSTEM] Agent initialized successfully.{Colors.RESET}")
    except Exception as e:
        print(f"{Colors.RED}[ERROR] Failed to initialize agent: {e}{Colors.RESET}")
        print(f"{Colors.YELLOW}[TIP] Make sure the appropriate API key is set:{Colors.RESET}")
        print(f"  - For Google models: export GEMINI_API_KEY=your_key")
        print(f"  - For OpenAI models: export OPENAI_API_KEY=your_key")
        return

    # Create Client with session registration (or resume existing session)
    if resume_session_id:
        print(f"{Colors.BLUE}[SYSTEM] Resuming session {resume_session_id}...{Colors.RESET}")
        try:
            client = CanyonClient(
                base_url=config.server.api.base_url,
                model_name=model_name,
                agent_name=f"agent-{model_name}",
                auto_register=False
            )
            client._session_id = resume_session_id
            print(f"{Colors.GREEN}[SYSTEM] Session resumed: {client._session_id}{Colors.RESET}")

            # Refresh victory_threshold from the actual session
            try:
                session_status = client.get_status()
                api_victory_threshold = session_status.get('victory_threshold', api_victory_threshold)
                print(f"{Colors.GREEN}[SYSTEM] Victory threshold: {api_victory_threshold * 100:.0f}%{Colors.RESET}")
            except Exception as e:
                print(f"{Colors.YELLOW}[WARNING] Could not refresh victory threshold: {e}{Colors.RESET}")
        except Exception as e:
            print(f"{Colors.RED}[ERROR] Failed to resume session: {e}{Colors.RESET}")
            return
    else:
        experiment_name = args.experiment
        if experiment_name:
            print(f"{Colors.BLUE}[SYSTEM] Registering agent session for experiment: {experiment_name}...{Colors.RESET}")
        else:
            print(f"{Colors.BLUE}[SYSTEM] Registering agent session...{Colors.RESET}")
        try:
            client = CanyonClient(
                base_url=config.server.api.base_url,
                model_name=model_name,
                agent_name=f"agent-{model_name}",
                experiment=experiment_name,
                execution_mode=execution_mode,
                auto_register=True
            )
            print(f"{Colors.GREEN}[SYSTEM] Session registered: {client._session_id}{Colors.RESET}")

            # Refresh victory_threshold from the actual session (not default experiment)
            try:
                session_status = client.get_status()
                api_victory_threshold = session_status.get('victory_threshold', api_victory_threshold)
                print(f"{Colors.GREEN}[SYSTEM] Victory threshold: {api_victory_threshold * 100:.0f}%{Colors.RESET}")
            except Exception as e:
                print(f"{Colors.YELLOW}[WARNING] Could not refresh victory threshold: {e}{Colors.RESET}")

            # Load standard_design scoped to this session's experiment
            scoped_design = _load_experiment_standard_design(experiment_name)
            if scoped_design:
                api_standard_design = scoped_design
        except Exception as e:
            print(f"{Colors.RED}[ERROR] Failed to register session: {e}{Colors.RESET}")
            print(f"{Colors.YELLOW}[TIP] Make sure the backend is running at {config.server.api.base_url}{Colors.RESET}")
            return

    # Setup execution mode
    mode = ExecutionMode.HYBRID if execution_mode == "hybrid" else ExecutionMode.LEGACY

    # Create orchestrator with explicit client (no hidden injection)
    # Pass session_id for workspace isolation in HYBRID mode
    # Let orchestrator use its default max_turns based on mode
    orchestrator = AgentOrchestrator(
        handler=agent,
        client=client,
        mode=mode,
        session_id=client._session_id,
        deployment_budget=api_deployment_budget,
    )

    # Inject client into agent's locals for logging (needed in both modes)
    # Also allows run_code to work with `client` variable in legacy mode
    agent.locals['client'] = client

    print(f"{Colors.CYAN}[SYSTEM] Execution mode: {execution_mode}{Colors.RESET}")
    print(f"{Colors.CYAN}[SYSTEM] Max turns: {orchestrator.max_turns}{Colors.RESET}")
    if api_deployment_budget:
        print(f"{Colors.CYAN}[SYSTEM] Deployment budget: {api_deployment_budget} calls{Colors.RESET}")
    if mode == ExecutionMode.HYBRID and orchestrator.workspace:
        print(f"{Colors.CYAN}[SYSTEM] Workspace: {orchestrator.workspace.get_workspace_path()}{Colors.RESET}")

    # Sync max_turns to backend for tracking
    try:
        client.update_session_config(max_turns=orchestrator.max_turns)
    except Exception:
        pass  # Non-critical

    # Create step function that uses orchestrator (hybrid) or agent (legacy)
    def do_step(prompt: str, log_type: str = "THOUGHT"):
        """Execute a step using orchestrator (hybrid) or agent (legacy)."""
        if mode == ExecutionMode.HYBRID:
            step_result = orchestrator.step(prompt, log_type)
            if step_result.mission_complete:
                agent.mission_complete = True
            return step_result
        else:
            agent.step(prompt, log_type=log_type)
            return None

    # Load conversation history and token usage if resuming
    if resume_session_id:
        print(f"{Colors.BLUE}[SYSTEM] Loading conversation history...{Colors.RESET}")
        if agent.load_conversation_from_backend():
            print(f"{Colors.GREEN}[SYSTEM] Conversation history loaded, resuming from last state{Colors.RESET}")
        else:
            print(f"{Colors.YELLOW}[WARN] No conversation history found, starting fresh{Colors.RESET}")

        # Load previous token usage so we continue from the right counts
        try:
            status = client.get_status()
            prev_token_usage = status.get('token_usage', {})
            if prev_token_usage:
                agent.total_input_tokens = prev_token_usage.get('input_tokens', 0)
                agent.total_output_tokens = prev_token_usage.get('output_tokens', 0)
                print(f"{Colors.GREEN}[SYSTEM] Restored token usage: {agent.total_input_tokens:,} input, {agent.total_output_tokens:,} output{Colors.RESET}")
        except Exception as e:
            print(f"{Colors.YELLOW}[WARN] Could not load previous token usage: {e}{Colors.RESET}")

    # Initial Analysis (skip if resuming)
    if not resume_session_id:
        print(f"{Colors.BLUE}[SYSTEM] Accessing Historical Archives...{Colors.RESET}")
        try:
            initial_data = client.get_history()
            survivors = [d for d in initial_data if d['status'] in ("RETURNED", "SURVIVED")] if isinstance(initial_data, list) else []
            total_records = len(initial_data) if isinstance(initial_data, list) else 0
            initial_survival_rate = (len(survivors) / total_records * 100) if total_records > 0 else 0

            print(f"{Colors.BLUE}[SYSTEM] Found {total_records} historical records.{Colors.RESET}")
            print(f"{Colors.BLUE}[SYSTEM] Historical Survival Rate: {initial_survival_rate:.1f}%{Colors.RESET}")

            # Build mode-specific initial prompt
            if mode == ExecutionMode.HYBRID:
                initial_prompt = f"""
MISSION START.
Reviewing Historical Archives...
Found {total_records} prior flight logs.
Global Survival Rate: {initial_survival_rate:.1f}% ({len(survivors)}/{total_records})

Your goal is to IMPROVE this survival rate by finding the optimal drone design.

**EXECUTION MODE: HYBRID (Tool Calling + Code Analysis)**
- Use TOOLS for API operations: `get_history`, `deploy_drone`, `submit_final_design`, etc.
- Use Python code blocks ONLY for data analysis with pandas/numpy
- Do NOT use `client.xxx()` in code - use the corresponding TOOL instead!

**IMPORTANT WORKFLOW:**
1. **EXPLORE FIRST**: Use `get_history` tool to get data, then analyze with pandas in code
3. **TEST HYPOTHESES**: Use `deploy_drone` tool to test different designs (you have many drones!)
4. **ITERATE**: Analyze results and refine your design
5. **SUBMIT ONLY AFTER EXPLORATION**: Use `submit_final_design` tool ONLY when you have gathered enough data

**WARNING**: Do NOT call `submit_final_design` until you have:
- Analyzed historical data
- Discovered environmental factors
- Tested multiple drone designs with `deploy_drone`

Start by using the `get_history` TOOL to retrieve historical data.
"""
            else:
                initial_prompt = f"""
MISSION START.
Reviewing Historical Archives...
Found {total_records} prior flight logs.
Global Survival Rate: {initial_survival_rate:.1f}% ({len(survivors)}/{total_records})

Your goal is to improve this.
Start by analyzing the provided historical data using `client.get_history()` to understand why previous drones failed (or survived).
"""
            do_step(initial_prompt)
        except Exception as e:
            print(f"{Colors.RED}[ERROR] Failed to fetch initial intelligence: {e}{Colors.RESET}")
            do_step("Starting mission. Fetch mission data first.")
    else:
        # Resuming - send a resume prompt
        print(f"{Colors.BLUE}[SYSTEM] Sending resume prompt...{Colors.RESET}")
        try:
            status = client.get_status()
            remaining = status['drones_remaining']
            resume_prompt = f"""
[RESUMING SESSION]
Session was interrupted. Continuing from where you left off.
Current status:
- Drones Remaining: {remaining}
- Session ID: {resume_session_id}

Please continue your analysis and experimentation.
"""
            do_step(resume_prompt)
        except Exception as e:
            print(f"{Colors.RED}[ERROR] Failed to send resume prompt: {e}{Colors.RESET}")
            do_step("Session resumed. Continue your previous work.")

    # Main Loop
    drones_used = 0
    total_drones = api_total_drones

    print(f"\n{Colors.GREEN}[SYSTEM] Starting Exploration Phase...{Colors.RESET}\n")

    while orchestrator.current_turn < orchestrator.max_turns:
        try:
            status = client.get_status()
            remaining = status['drones_remaining']
            drones_used = total_drones - remaining
            has_submitted = status.get('final_evaluation') is not None

            if remaining <= 0:
                print(f"{Colors.YELLOW}[SYSTEM] All drones deployed.{Colors.RESET}")
                break

            # Build context (turn info and warnings are added by orchestrator)
            # Calculate turns remaining for instruction adjustment
            turns_remaining = orchestrator.max_turns - orchestrator.current_turn

            if api_version == "v2":
                if mode == ExecutionMode.HYBRID:
                    # Adjust instruction based on urgency
                    if turns_remaining <= 1:
                        instruction = """INSTRUCTION:
🚨 FINAL TURN! You MUST call `submit_final_design` NOW with your best design!
- Do NOT deploy more drones - submit immediately!
- Use your analysis to choose the best DEF values."""
                    elif turns_remaining <= 3:
                        instruction = """INSTRUCTION:
⚠️ TIME CRITICAL: Finalize your design and prepare to submit!
- You may do ONE more deployment to confirm, then SUBMIT.
- Call `submit_final_design` before you run out of turns!"""
                    else:
                        instruction = """INSTRUCTION:
- Continue exploring with `deploy_drone` to gather more data.
- Analyze patterns before optimizing your design.
- Only submit when you have sufficient evidence for your design choices."""

                    context = f"""STATUS UPDATE:
- Drones Remaining: {remaining}
- Final Design Submitted: {"YES ✓" if has_submitted else "NO (submit only after thorough exploration!)"}

{instruction}
"""
                else:
                    context = f"""STATUS UPDATE:
- Drones Remaining: {remaining}
- Final Design Submitted: {"YES ✓" if has_submitted else "NO (REQUIRED!)"}

INSTRUCTION:
- Use tools to deploy drones and analyze results.
- Submit your final design before running out of turns.
"""
            else:
                context = f"""STATUS UPDATE:
- Drones Remaining: {remaining}
- HP Budget Remaining: {status['hp_remaining']}
- Final Design Submitted: {"YES ✓" if has_submitted else "NO (REQUIRED!)"}

INSTRUCTION:
- You MUST use all {total_drones} drones to gather maximum data.
- Do NOT stop until Drones Remaining is 0 or you submit your final design.
"""
            do_step(context)

            # Detect idle spinning: no deploy or submit action this turn
            try:
                current_status = client.get_status()
                current_deployments = current_status.get('deployments_used', 0)
                current_submitted = current_status.get('final_evaluation') is not None
                if current_deployments == last_deployments and not current_submitted:
                    idle_turns += 1
                    if idle_turns >= max_idle_turns:
                        log(f"{Colors.RED}[SYSTEM] Agent idle for {idle_turns} consecutive turns (no deploy/submit). Forcing submission.{Colors.RESET}")
                        break
                else:
                    idle_turns = 0
                last_deployments = current_deployments
            except Exception:
                pass  # Non-critical

            # Detect error loop: consecutive THOUGHT→ACTION→ERROR cycles (legacy mode)
            try:
                agent_logs = getattr(agent, 'logs', None) or getattr(orchestrator, 'logs', None) or []
                if agent_logs and len(agent_logs) >= 1:
                    last_type = agent_logs[-1].get('type', '')
                    if last_type == 'ERROR':
                        error_cycle_count += 1
                    elif last_type in ('ACTION',) and current_deployments > last_deployments:
                        error_cycle_count = 0  # Successful deploy resets
                    if error_cycle_count >= max_error_cycles:
                        log(f"{Colors.RED}[SYSTEM] {error_cycle_count} consecutive failed action cycles. Forcing submission.{Colors.RESET}")
                        break
            except Exception:
                pass  # Non-critical

            # Update token usage periodically (every step)
            try:
                token_usage = agent.get_token_usage()
                client.update_token_usage(
                    input_tokens=token_usage["input_tokens"],
                    output_tokens=token_usage["output_tokens"]
                )
            except Exception:
                pass  # Non-critical, don't break the loop

            if agent.mission_complete or orchestrator.mission_complete:
                print(f"{Colors.CYAN}[SYSTEM] Agent signaled mission complete.{Colors.RESET}")
                break

        except KeyboardInterrupt:
            print(f"\n{Colors.YELLOW}[SYSTEM] Interrupted by user.{Colors.RESET}")
            try:
                client.report_error("Interrupted by user", error_type="user_interrupt", fatal=True)
            except Exception:
                pass
            break
        except Exception as e:
            error_msg = str(e)
            print(f"{Colors.RED}[ERROR] Loop failed: {error_msg}{Colors.RESET}")
            # Report error to backend
            try:
                client.report_error(error_msg, error_type="agent_error", fatal=True)
                print(f"{Colors.YELLOW}[SYSTEM] Error reported to backend.{Colors.RESET}")
            except Exception as report_err:
                print(f"{Colors.RED}[ERROR] Failed to report error: {report_err}{Colors.RESET}")
            break

    # Report but do NOT force-submit if the agent never submitted.
    # Under the current policy, runs with no final submission are recorded as N/A
    # and excluded from survival-rate averages.
    try:
        final_status = client.get_status()
        if final_status.get('final_evaluation') is None:
            print(f"\n{Colors.RED}[SYSTEM] ⚠️  NO FINAL DESIGN SUBMITTED — recording as N/A.{Colors.RESET}")
            print(f"{Colors.YELLOW}[SYSTEM] The agent did not call submit_final_design successfully. "
                  f"No fallback design will be submitted.{Colors.RESET}")
    except Exception as e:
        print(f"{Colors.RED}[ERROR] Failed to check final status: {e}{Colors.RESET}")

    # Final Report
    print(f"\n{Colors.BOLD}{Colors.GREEN}=== MISSION COMPLETE ==={Colors.RESET}\n")

    try:
        final_status = client.get_status()

        final_eval = final_status.get('final_evaluation')

        # Only proceed if we have actual survival data (not just truthy but empty)
        if final_eval and final_eval.get('survived') is not None:
            if api_version == "v2":
                # V2: Show survival rate (Final Score/DEF Efficiency are for internal analysis only)
                print(f"{Colors.YELLOW}>> OFFICIAL STAGE 2 RESULT (V2) <<{Colors.RESET}")
                print(f"Survival Rate: {Colors.BOLD}{final_eval.get('survival_rate', 'N/A')}{Colors.RESET}")
                print(f"Survivors: {final_eval.get('survived', 'N/A')}/{final_eval.get('fleet_size', api_stage2_fleet_size)}")
                print(f"Victory: {Colors.GREEN if final_eval.get('victory') else Colors.RED}{'YES ✓' if final_eval.get('victory') else 'NO ✗'}{Colors.RESET}")
                print(f"Exploration: {drones_used} drones used in Stage 1")
                # Internal metrics (not shown to agent)
                print(f"{Colors.CYAN}[Internal] Final Score: {final_eval.get('final_score', 'N/A')}, DEF Efficiency: {final_eval.get('def_efficiency', 'N/A')}, Total DEF: {final_eval.get('total_def', 'N/A')}{Colors.RESET}")

                # Report for agent (without Final Score / DEF Efficiency)
                final_report = f"""
MISSION REPORT:
OFFICIAL RESULT (Stage 2):
- Survival Rate: {final_eval.get('survival_rate', 'N/A')}
- Survivors: {final_eval.get('survived', 'N/A')}/{final_eval.get('fleet_size', api_stage2_fleet_size)}
- Victory: {'YES' if final_eval.get('victory') else 'NO'}
Exploration: {drones_used} drones used in Stage 1.
"""
            else:
                # V1: Original report format
                hp_used = api_total_hp - final_status.get('hp_remaining', 0)
                print(f"{Colors.YELLOW}>> OFFICIAL STAGE 2 RESULT <<{Colors.RESET}")
                print(f"Survival Rate: {Colors.BOLD}{final_eval['survival_rate']}{Colors.RESET}")
                print(f"Survivors: {final_eval['survived']}/50")
                print(f"Design Cost: {final_eval.get('cost_used', final_eval.get('cost_per_drone', 'N/A'))}")
                print(f"Exploration: {drones_used} drones used in Stage 1")

                final_report = f"""
MISSION REPORT:
OFFICIAL RESULT (Stage 2): {final_eval['survival_rate']} Survival ({final_eval['survived']}/50)
Design Cost: {final_eval.get('cost_used', final_eval.get('cost_per_drone', 'N/A'))}
Exploration Efficiency: {drones_used} drones used to find solution.
"""
        else:
            # No final submission
            print(f"{Colors.RED}WARNING: No Final Design Submitted.{Colors.RESET}")
            print(f"Total Drones Deployed: {drones_used}/{total_drones}")

            if api_version != "v2":
                hp_used = api_total_hp - final_status.get('hp_remaining', 0)
                print(f"Total HP Budget Used: {hp_used}")

            # Calculate Stage 1 stats
            data = client.get_history()
            session_drones = [d for d in data if str(d.get('id', '')).startswith('SESSION')]
            session_survivors = [d for d in session_drones if d['status'] in ('RETURNED', 'SURVIVED')]
            stage1_rate = (len(session_survivors) / len(session_drones) * 100) if session_drones else 0

            print(f"Exploration Survival Rate: {stage1_rate:.1f}%")

            final_report = f"""
MISSION REPORT:
RESULT: FAILED (No Final Design Submitted)
Stage 1 Stats: {drones_used}/{total_drones} deployed
Exploration Survival Rate: {stage1_rate:.1f}%
"""

        # Request Reflection
        print(f"\n{Colors.CYAN}[SYSTEM] Requesting Final Agent Reflection...{Colors.RESET}\n")

        victory_threshold_pct = final_status.get('victory_threshold', api_victory_threshold) * 100
        reflection_prompt = f"""
{final_report}

[INSTRUCTION]
Analyze the Mission Report above. DO NOT call any tools - just provide your analysis in plain text.
1. Did you solve the task? (Survival Rate > {victory_threshold_pct:.0f}% is considered a success).
2. What was the key to survival?
3. Why did some drones fail?
4. Final Conclusion.
"""
        agent.mission_complete = False  # Allow reflection
        orchestrator.mission_complete = False
        do_step(reflection_prompt, log_type="REPORT")

    except Exception as e:
        print(f"{Colors.RED}[ERROR] Failed to generate final report: {e}{Colors.RESET}")

    # Report token usage to backend
    print(f"{Colors.YELLOW}[SYSTEM] Reporting token usage...{Colors.RESET}")
    try:
        token_usage = agent.get_token_usage()
        client.update_token_usage(
            input_tokens=token_usage["input_tokens"],
            output_tokens=token_usage["output_tokens"]
        )
        print(f"{Colors.GREEN}[SYSTEM] Token usage: {token_usage['input_tokens']:,} input, {token_usage['output_tokens']:,} output, {token_usage['total_tokens']:,} total{Colors.RESET}")
    except Exception as e:
        print(f"{Colors.RED}[ERROR] Failed to report token usage: {e}{Colors.RESET}")

    # Export agent records
    print(f"{Colors.YELLOW}[SYSTEM] Exporting agent records...{Colors.RESET}")
    try:
        export_result = client.export_records()
        if export_result and 'filepath' in export_result:
            print(f"{Colors.GREEN}[SYSTEM] Records saved to: {export_result['filepath']}{Colors.RESET}")
        else:
            print(f"{Colors.YELLOW}[SYSTEM] No records exported: {export_result}{Colors.RESET}")
    except Exception as e:
        print(f"{Colors.RED}[ERROR] Failed to export records: {e}{Colors.RESET}")

    print(f"\n{Colors.GREEN}[SYSTEM] Agent session ended.{Colors.RESET}")


if __name__ == "__main__":
    main()
