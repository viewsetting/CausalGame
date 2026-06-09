"""
Multi-Configuration Loader for CausalGame

Loads configuration from three separate files:
- config/server.json  - 服务器和网络配置
- config/game.json    - 游戏机制和参数配置
- config/agent.json   - Agent 行为配置

Usage:
    from config import config

    # 访问服务器配置
    port = config.server.backend.port
    api_url = config.server.api.base_url

    # 访问游戏配置
    drone_budget = config.game.resources.total_drone_budget
    bias_type = config.game.simulation.causal_model.bias_scenario

    # 访问 Agent 配置
    model = config.agent.models.default
    max_turns = config.agent.execution.max_turns
"""

import json
import os
from typing import Dict, Any, Optional
from pathlib import Path


class ConfigDict:
    """
    Dictionary wrapper that allows accessing keys as attributes.

    Example:
        cfg = ConfigDict({"server": {"port": 8000}})
        print(cfg.server.port)  # 8000
    """

    def __init__(self, data: Dict[str, Any]):
        for key, value in data.items():
            # Skip comments
            if key.startswith('_'):
                continue

            if isinstance(value, dict):
                setattr(self, key, ConfigDict(value))
            else:
                setattr(self, key, value)

    def __getitem__(self, key):
        return getattr(self, key)

    def __repr__(self):
        attrs = {k: v for k, v in self.__dict__.items()}
        return f"ConfigDict({attrs})"

    def to_dict(self) -> Dict[str, Any]:
        """Convert back to a regular dictionary."""
        result = {}
        for key, value in self.__dict__.items():
            if isinstance(value, ConfigDict):
                result[key] = value.to_dict()
            else:
                result[key] = value
        return result


class Config:
    """
    Multi-file configuration manager.

    Loads three configuration files:
    - server.json: 服务器和API配置
    - game.json: 游戏机制和参数
    - agent.json: Agent行为配置
    """

    def __init__(self, config_dir: str = None):
        """
        Load configuration from directory.

        Args:
            config_dir: Directory containing config files.
                       If None, searches in standard locations.
        """
        if config_dir is None:
            config_dir = self._find_config_dir()

        self._config_dir = Path(config_dir)
        self._load_all_configs()

    def _find_config_dir(self) -> str:
        """Find config directory in standard locations."""
        # Check environment variable
        env_path = os.environ.get('CONFIG_DIR')
        if env_path and os.path.isdir(env_path):
            return env_path

        # Check ./config
        if os.path.isdir('config'):
            return 'config'

        # Check relative to this file
        file_dir = Path(__file__).parent
        config_subdir = file_dir / 'config'
        if config_subdir.exists():
            return str(config_subdir)

        # Check parent directory
        parent_config = file_dir.parent / 'config'
        if parent_config.exists():
            return str(parent_config)

        raise FileNotFoundError(
            "config/ directory not found. Please create it or set CONFIG_DIR environment variable."
        )

    def _load_all_configs(self):
        """Load all configuration files."""
        # Load server config
        server_path = self._config_dir / 'server.json'
        self.server = self._load_config_file(server_path, "server")

        # Load agent config
        agent_path = self._config_dir / 'agent.json'
        self.agent = self._load_config_file(agent_path, "agent")

        # Load game config dynamically from experiment directory
        experiment_name = os.environ.get('CAUSALGAME_EXPERIMENT', 'antenna_trap')
        self.experiment_name = experiment_name

        # Try experiment-specific config first
        experiments_dir = Path(__file__).parent / 'experiments'
        experiment_game_path = experiments_dir / experiment_name / 'game.json'

        if experiment_game_path.exists():
            self.game = self._load_config_file(experiment_game_path, "game")
            game_source = f"experiments/{experiment_name}/game.json"
        else:
            # Fallback to config/game.json if exists
            fallback_path = self._config_dir / 'game.json'
            if fallback_path.exists():
                self.game = self._load_config_file(fallback_path, "game")
                game_source = "config/game.json (fallback)"
            else:
                raise FileNotFoundError(
                    f"Game config not found for experiment '{experiment_name}'. "
                    f"Expected: {experiment_game_path}"
                )

        print(f"[CONFIG] Loaded configurations:")
        print(f"  - server.json: {self._config_dir}/server.json ✓")
        print(f"  - agent.json: {self._config_dir}/agent.json ✓")
        print(f"  - game.json: {game_source} ✓")
        print(f"  - Experiment: {experiment_name}")

    def _load_config_file(self, path: Path, name: str) -> ConfigDict:
        """Load a single configuration file."""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return ConfigDict(data)
        except FileNotFoundError:
            raise FileNotFoundError(f"Configuration file not found: {path}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in {name}.json: {e}")

    def reload(self, section: Optional[str] = None):
        """
        Reload configuration from files.

        Args:
            section: Optional section to reload ('server', 'game', 'agent').
                    If None, reloads all sections.
        """
        if section is None:
            self._load_all_configs()
            print("[CONFIG] All configurations reloaded")
        elif section == 'server':
            server_path = self._config_dir / 'server.json'
            self.server = self._load_config_file(server_path, "server")
            print("[CONFIG] Server configuration reloaded")
        elif section == 'game':
            # Reload from experiment directory
            experiment_name = os.environ.get('CAUSALGAME_EXPERIMENT', 'antenna_trap')
            experiments_dir = Path(__file__).parent / 'experiments'
            experiment_game_path = experiments_dir / experiment_name / 'game.json'
            if experiment_game_path.exists():
                self.game = self._load_config_file(experiment_game_path, "game")
            else:
                game_path = self._config_dir / 'game.json'
                self.game = self._load_config_file(game_path, "game")
            print(f"[CONFIG] Game configuration reloaded (experiment: {experiment_name})")
        elif section == 'agent':
            agent_path = self._config_dir / 'agent.json'
            self.agent = self._load_config_file(agent_path, "agent")
            print("[CONFIG] Agent configuration reloaded")
        else:
            raise ValueError(f"Unknown section: {section}")

    def get_api_url(self, endpoint: str = None) -> str:
        """
        Get full API URL.

        Args:
            endpoint: Optional endpoint name (e.g., 'mission_status')
                     If None, returns base URL.

        Returns:
            Full URL string
        """
        base = self.server.api.base_url
        if endpoint is None:
            return base

        if hasattr(self.server.api.endpoints, endpoint):
            path = getattr(self.server.api.endpoints, endpoint)
            return f"{base}{path}"

        raise ValueError(f"Unknown endpoint: {endpoint}")

    def override(self, path: str, value: Any):
        """
        Override a configuration value at runtime.

        Args:
            path: Dot-separated path (e.g., 'server.backend.port' or 'game.resources.total_drone_budget')
            value: New value

        Example:
            config.override('server.backend.port', 9000)
            config.override('game.simulation.causal_model.bias_scenario', 'common_cause')
        """
        parts = path.split('.')
        section = parts[0]

        if section not in ['server', 'game', 'agent']:
            raise ValueError(f"Invalid section: {section}. Must be 'server', 'game', or 'agent'")

        obj = getattr(self, section)
        for key in parts[1:-1]:
            obj = getattr(obj, key)

        setattr(obj, parts[-1], value)
        print(f"[CONFIG] Override: {path} = {value}")

    def get_causal_model_config(self) -> Dict[str, Any]:
        """Get complete causal model configuration."""
        return {
            'type': self.game.simulation.causal_model.type,
            'bias_scenario': self.game.simulation.causal_model.bias_scenario,
            'bias_parameters': self.game.simulation.causal_model.bias_parameters.to_dict(),
            'environment': self.game.environment.to_dict(),
            'damage_mechanics': self.game.simulation.damage_mechanics.to_dict()
        }

    def get_agent_strategy(self, strategy_name: str = None) -> Dict[str, Any]:
        """
        Get agent strategy configuration.

        Args:
            strategy_name: Name of strategy ('exploratory', 'conservative', 'analytical')
                          If None, returns default strategy based on current settings.
        """
        if strategy_name is None:
            # Return current execution settings as strategy
            return {
                'max_turns': self.agent.execution.max_turns,
                'timeout': self.agent.execution.timeout_per_turn_seconds,
                'model': self.agent.models.default
            }

        if hasattr(self.agent.strategies, strategy_name):
            return getattr(self.agent.strategies, strategy_name).to_dict()

        raise ValueError(f"Unknown strategy: {strategy_name}")

    def apply_strategy(self, strategy_name: str):
        """
        Apply a predefined strategy to agent configuration.

        Args:
            strategy_name: Name of strategy to apply
        """
        strategy = self.get_agent_strategy(strategy_name)

        if 'exploration_drones' in strategy:
            print(f"[CONFIG] Applying strategy: {strategy_name}")
            print(f"  Exploration drones: {strategy.get('exploration_drones')}")
            print(f"  Min experiments: {strategy.get('min_experiments_before_submit')}")

    def __repr__(self):
        return f"Config(dir={self._config_dir}, server=✓, game=✓, agent=✓)"


# Global singleton instance
_config_instance = None


def get_config(config_dir: str = None) -> Config:
    """
    Get or create the global configuration instance.

    Args:
        config_dir: Optional path to config directory (only used on first call)

    Returns:
        Global Config instance
    """
    global _config_instance

    if _config_instance is None:
        _config_instance = Config(config_dir)

    return _config_instance


# Convenience alias
config = get_config()


if __name__ == "__main__":
    # Test configuration loading
    print("=" * 70)
    print("CausalGame Configuration Test")
    print("=" * 70)

    cfg = get_config()

    print("\n=== Server Configuration ===")
    print(f"Backend Port: {cfg.server.backend.port}")
    print(f"API Base URL: {cfg.server.api.base_url}")
    print(f"CORS Origins: {cfg.server.backend.cors_origins}")

    print("\n=== Game Configuration ===")
    print(f"Drone Budget: {cfg.game.resources.total_drone_budget}")
    print(f"HP Per Drone: {cfg.game.resources.hp_per_drone}")
    print(f"Total HP Budget: {cfg.game.resources.total_drone_budget * cfg.game.resources.hp_per_drone}")
    print(f"Standard Design: {cfg.game.drone.standard_design.to_dict()}")
    print(f"Causal Model: {cfg.game.simulation.causal_model.type}")
    print(f"Bias Scenario: {cfg.game.simulation.causal_model.bias_scenario}")

    print("\n=== Agent Configuration ===")
    print(f"Default Model: {cfg.agent.models.default}")
    print(f"Max Turns: {cfg.agent.execution.max_turns}")
    print(f"System Instruction Template: {cfg.agent.system_instruction.template}")

    print("\n=== API URLs ===")
    print(f"Mission Status: {cfg.get_api_url('mission_status')}")
    print(f"Deploy Drone: {cfg.get_api_url('deploy_drone')}")

    print("\n=== Override Test ===")
    cfg.override('server.backend.port', 9000)
    print(f"New Backend Port: {cfg.server.backend.port}")

    cfg.override('game.simulation.causal_model.bias_scenario', 'common_cause')
    print(f"New Bias Scenario: {cfg.game.simulation.causal_model.bias_scenario}")

    print("\n=== Causal Model Config ===")
    causal_config = cfg.get_causal_model_config()
    print(f"Type: {causal_config['type']}")
    print(f"Bias: {causal_config['bias_scenario']}")

    print("\n=== Agent Strategy Test ===")
    exploratory = cfg.get_agent_strategy('exploratory')
    print(f"Exploratory Strategy: {exploratory}")

    print("\n" + "=" * 70)
    print("✓ All configuration tests passed!")
    print("=" * 70)
