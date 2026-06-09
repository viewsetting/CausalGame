# Adding New SCM Environments

This guide explains how to add new Structural Causal Model (SCM) environments to CausalGame.

## Overview

SCMs define the causal structure of an experiment - how environment variables are generated and how they affect drone outcomes. Each experiment has its own SCM that creates causal reasoning challenges for AI agents.

## Quick Start

To add a new experiment called `my_experiment`:

1. Create experiment directory: `experiments/my_experiment/`
2. Create config file: `experiments/my_experiment/game.json`
3. Create SCM class: `api/modules/environment/my_experiment_scm.py`
4. Register with `@register_scm("my_experiment")`

## Directory Structure

```
CausalGame/
├── api/modules/environment/
│   ├── my_experiment_scm.py      # Your SCM implementation
│   └── ...
└── experiments/
    └── my_experiment/
        ├── game.json                     # Experiment configuration
        └── environment_variables.json    # Variable documentation (optional)
```

## SCM Implementation

### Required Imports

```python
import random
from typing import Any, Dict

from api.middleware.drone_sheet import DroneSheet
from api.middleware.drone_state import EnvironmentEffects
from api.modules.environment.scm_base import BaseSCM, EnvironmentState
from api.modules.environment.scm_registry import register_scm
```

### Base Class

Extend `BaseSCM` and implement two required methods:

```python
@register_scm("my_experiment")
class MyExperimentSCM(BaseSCM):

    def __init__(self, config: Dict[str, Any]):
        """Initialize with experiment config from game.json."""
        super().__init__(config)
        # Load SCM-specific parameters
        self.my_param = config.get('my_param', 0.5)

    def sample_environment(self) -> EnvironmentState:
        """Generate environment state for each mission."""
        # Implement sampling logic
        pass

    def _compute_effects(
        self,
        sheet: DroneSheet,
        env: EnvironmentState
    ) -> EnvironmentEffects:
        """Compute effects to apply to DroneSheet."""
        # Implement effect calculation
        pass
```

### EnvironmentState Structure

Environment variables are organized into three categories:

```python
EnvironmentState(
    visible={       # Agent can observe these
        'wind_speed': 25.0,
        'humidity': 60.0,
    },
    latent={        # Hidden from agent (confounders)
        'weather_pattern': 0.8,
    },
    derived={       # Computed from other variables
        'is_storm': 1.0,
    }
)
```

### EnvironmentEffects Structure

Effects are how the SCM influences the game:

```python
EnvironmentEffects(
    # Component damage by name
    component_damage={'engine': 15, 'antenna': 10},

    # Combat modifiers (multipliers)
    detection_modifier=0.3,
    combat_rounds_modifier=1.5,
    combat_damage_modifier=1.0,
    combat_accuracy_modifier=1.0,

    # Component effectiveness (multipliers)
    camera_effectiveness=1.0,
    gun_effectiveness=1.0,
    antenna_effectiveness=0.8,

    # Metadata
    weather_pattern=0.5,
    raw_environment={'wind_speed': 25.0},
    damage_log=['Wind damage: 15 to engine'],
)
```

## Complete Example

```python
import random
from typing import Any, Dict

from api.middleware.drone_sheet import DroneSheet
from api.middleware.drone_state import EnvironmentEffects
from api.modules.environment.scm_base import BaseSCM, EnvironmentState
from api.modules.environment.scm_registry import register_scm


@register_scm("weather_trap")
class WeatherTrapSCM(BaseSCM):
    """
    Weather Trap SCM: Demonstrates a confounding pattern where
    a hidden weather variable affects both visibility and damage.
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.storm_probability = config.get('storm_probability', 0.6)
        self.base_detection = config.get('base_detection', 0.2)

    def sample_environment(self) -> EnvironmentState:
        # 1. Sample latent confounder first
        weather_pattern = random.random()
        is_storm = weather_pattern > (1 - self.storm_probability)

        # 2. Visible variables conditioned on latent
        if is_storm:
            wind_speed = random.uniform(40, 80)
            visibility = random.uniform(0.1, 0.3)
        else:
            wind_speed = random.uniform(5, 25)
            visibility = random.uniform(0.6, 1.0)

        humidity = random.uniform(30, 90)
        temperature = random.uniform(10, 35)

        return EnvironmentState(
            visible={
                'wind_speed': wind_speed,
                'humidity': humidity,
                'temperature': temperature,
                'visibility': visibility,
            },
            latent={
                'weather_pattern': weather_pattern,
            },
            derived={
                'is_storm': float(is_storm),
            }
        )

    def _compute_effects(
        self,
        sheet: DroneSheet,
        env: EnvironmentState
    ) -> EnvironmentEffects:
        # Read environment
        wind_speed = env.visible.get('wind_speed', 20)
        visibility = env.visible.get('visibility', 0.5)
        is_storm = env.derived.get('is_storm', 0)

        # Read agent's design choices
        engine_def = sheet._def.get('engine', 10)

        # Compute component damage
        component_damage = {}
        damage_log = []

        if wind_speed > 30:
            base_damage = int((wind_speed - 30) * 2)
            mitigation = int(engine_def * 0.3)
            actual_damage = max(0, base_damage - mitigation)
            component_damage['engine'] = actual_damage
            damage_log.append(
                f"Wind damage: {base_damage} - {mitigation} mitigation = {actual_damage}"
            )

        # Detection based on visibility (the trap: low visibility = low detection)
        detection_modifier = self.base_detection + (1 - visibility) * 0.5

        # Combat intensity higher in storms
        combat_rounds = 1.0 + is_storm * 2.0

        return EnvironmentEffects(
            component_damage=component_damage,
            detection_modifier=detection_modifier,
            combat_rounds_modifier=combat_rounds,
            weather_pattern=env.latent.get('weather_pattern', 0.5),
            raw_environment=env.all_variables(),
            damage_log=damage_log,
        )
```

## Configuration File (game.json)

Create `experiments/my_experiment/game.json`:

```json
{
  "experiment": {
    "name": "my_experiment",
    "display_name": "My Experiment",
    "description": "Description of the causal challenge",
    "version": "1.0",
    "author": "Your Name"
  },

  "resources": {
    "total_drone_budget": 200,
    "stage2_fleet_size": 1000,
    "victory_threshold": 0.55,
    "env_query_budget": 10,
    "initial_observations": 50
  },

  "scm_parameters": {
    "storm_probability": 0.6,
    "base_detection": 0.2
  },

  "drone": {
    "components": {
      "engine": {"hp": 100, "default_def": 20, "is_critical": true},
      "camera": {"hp": 50, "default_def": 15, "is_critical": false},
      "gun": {"hp": 60, "default_def": 20, "is_critical": false},
      "antenna": {"hp": 50, "default_def": 10, "is_critical": false},
      "frame": {"hp": 80, "default_def": 25, "is_critical": true}
    },
    "total_default_def": 90
  },

  "visibility": {
    "fields": {
      "hp": "hidden",
      "def_values": "visible",
      "status": "visible",
      "hit_count": "visible",
      "detection_probability": "hidden"
    }
  },

  "side_information": {
    "mission_briefing": "Briefing text for the agent...",
    "hints": ["Hint 1", "Hint 2"]
  }
}
```

## Running Your Experiment

Set the environment variable and start the server:

```bash
export CAUSALGAME_EXPERIMENT=my_experiment
uvicorn api.app:app --reload --port 8000
```

Or use Docker:

```bash
docker run -e CAUSALGAME_EXPERIMENT=my_experiment ...
```

## Design Patterns

### Pattern 1: Latent Confounders

Create causal traps with hidden variables:

```python
def sample_environment(self) -> EnvironmentState:
    # Latent cause affects multiple observed variables
    latent_cause = random.random()

    observed_1 = latent_cause * 0.8 + random.gauss(0, 0.1)
    observed_2 = latent_cause * 0.6 + random.gauss(0, 0.1)

    return EnvironmentState(
        visible={'observed_1': observed_1, 'observed_2': observed_2},
        latent={'latent_cause': latent_cause},
        derived={},
    )
```

### Pattern 2: Design-Dependent Effects

Make effects conditional on agent's choices:

```python
def _compute_effects(self, sheet: DroneSheet, env: EnvironmentState):
    # Agent's design choice affects outcome
    antenna_def = sheet._def.get('antenna', 10)

    # High DEF protects but may have side effects
    if antenna_def > 20:
        # Protected antenna survives -> emits signal -> detected
        detection_modifier = 0.8
    else:
        detection_modifier = 0.2

    return EnvironmentEffects(detection_modifier=detection_modifier, ...)
```

### Pattern 3: Interpolation Helper

Use the built-in interpolation for smooth transitions:

```python
def _compute_effects(self, sheet: DroneSheet, env: EnvironmentState):
    weather = env.latent.get('weather_pattern', 0.5)

    # Interpolate between clear (0) and storm (1) values
    detection = self._interpolate(
        weather,
        value_at_0=0.2,   # Clear weather
        value_at_1=0.05,  # Storm (low detection)
    )

    return EnvironmentEffects(detection_modifier=detection, ...)
```

## Testing Your SCM

Create a test file `tests/test_my_experiment_scm.py`:

```python
import unittest
from api.modules.environment.my_experiment_scm import MyExperimentSCM


class TestMyExperimentSCM(unittest.TestCase):

    def setUp(self):
        self.config = {
            'storm_probability': 0.5,
            'base_detection': 0.2,
        }
        self.scm = MyExperimentSCM(self.config)

    def test_sample_environment_structure(self):
        env = self.scm.sample_environment()
        self.assertIn('wind_speed', env.visible)
        self.assertIn('weather_pattern', env.latent)

    def test_effects_range(self):
        env = self.scm.sample_environment()
        # Create mock sheet
        from api.middleware.drone_sheet import DroneSheet
        sheet = DroneSheet(self.config)

        effects = self.scm._compute_effects(sheet, env)
        self.assertGreaterEqual(effects.detection_modifier, 0)
        self.assertLessEqual(effects.detection_modifier, 1)


if __name__ == '__main__':
    unittest.main()
```

Run tests:

```bash
python -m unittest tests/test_my_experiment_scm.py
```

## Checklist

Before submitting a new SCM:

- [ ] SCM class registered with `@register_scm("experiment_name")`
- [ ] `sample_environment()` returns valid `EnvironmentState`
- [ ] `_compute_effects()` returns valid `EnvironmentEffects`
- [ ] `game.json` created with all required sections
- [ ] Config parameters have sensible defaults
- [ ] Causal mechanism documented in code comments
- [ ] Unit tests written and passing
- [ ] Tested locally with `CAUSALGAME_EXPERIMENT=experiment_name`

## Reference

| File | Purpose |
|------|---------|
| `api/modules/environment/scm_base.py` | Base classes and data structures |
| `api/modules/environment/scm_registry.py` | Registration decorator |
| `api/middleware/drone_state.py` | `EnvironmentEffects` definition |
| `api/middleware/drone_sheet.py` | DroneSheet interface |
| `api/modules/environment/antenna_trap_scm.py` | Reference implementation |
| `experiments/antenna_trap/game.json` | Reference configuration |
