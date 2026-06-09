# CausalGame Architecture

## System Overview

CausalGame is an AI agent testbed for causal reasoning challenges. The system presents a cyberpunk drone mission scenario where agents must discover causal structure (not just correlations) to succeed.

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   AI Agents     │────▶│  FastAPI Backend│────▶│  React Frontend │
│  (Python/LLM)   │◀────│   (Simulation)  │◀────│   (Dashboard)   │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

## Component Architecture

### Backend (FastAPI)

```
api/
├── app.py                 # Application factory
├── routers.py             # Router aggregation
├── middleware/            # Data hub layer
│   ├── drone_sheet.py     # Single source of truth
│   ├── drone_state.py     # Immutable state structures
│   └── visibility.py      # Agent/Admin filtering
└── modules/               # Feature modules
    ├── agent/             # Agent interaction
    ├── environment/       # SCM system
    └── game/              # Judgment logic
```

### Frontend (React + Vite)

```
src/
├── App.tsx                # Main dashboard
├── components/            # UI components
├── context/               # React context providers
├── services/              # API client services
└── types.ts               # Shared type definitions
```

### Agent System

```
agent/
├── base.py                # Abstract handler
├── gemini.py              # Gemini implementation
├── openai.py              # OpenAI implementation
└── reporting.py           # Report generation

run_agent.py               # Entry point
```

## Key Design Patterns

### 1. DroneSheet (Single Source of Truth)

All drone data flows through `DroneSheet`:

```python
sheet = DroneSheet()
sheet.set_def_design(agent_design)    # Agent input
scm.apply_effects(sheet, environment)  # SCM effects
state = sheet.to_drone_state()         # Immutable snapshot
result = sheet.filter_result_for_agent()  # Filtered output
```

### 2. Visibility Control

Two levels of visibility controlled by `VisibilityConfig`:

| Field | Agent | Admin |
|-------|-------|-------|
| DEF | Yes | Yes |
| ATK | Yes | Yes |
| HP | No | Yes |
| Agility | No | Yes |
| Survival | Yes | Yes |

### 3. Pluggable SCM System

Experiments are pluggable via registry pattern:

```python
@register_scm("antenna_trap")
class AntennaTrapSCM(CausalSCM):
    def sample_environment(self) -> dict:
        # Generate causal environment
        pass

    def apply_effects(self, sheet: DroneSheet, env: dict):
        # Apply effects to drone sheet
        pass
```

### 4. Multi-Session Support

`SessionManager` handles concurrent agent sessions:
- Default session for backward compatibility
- Named sessions via `X-Session-ID` header
- Isolated state per session

## Data Flow

### Drone Deployment Flow

```
1. Agent POST /api/agent/deploy {def_design: {...}}
2. ActionSpace validates request
3. DroneSheet.set_def_design(design)
4. SCM.sample_environment() → environment state
5. SCM.apply_effects(sheet, env) → modify HP, agility
6. sheet.to_drone_state() → immutable DroneState
7. full_simulation(state) → detection, combat
8. judge_survival(state) → JudgmentResult
9. sheet.filter_result_for_agent() → hide HP/agility
10. Return filtered result to agent
```

### Experiment Configuration

Experiments defined in `experiments/<name>/game.json`:

```json
{
  "experiment": {
    "name": "Antenna Trap",
    "scm_class": "AntennaTrapSCM"
  },
  "resources": {
    "total_drone_budget": 200,
    "stage2_fleet_size": 1000,
    "victory_threshold": 0.55
  }
}
```

## Deployment

### Development
```bash
# Backend
uvicorn api.app:app --reload --port 8000

# Frontend
npm run dev  # Port 3000, proxies /api to 8000
```

### Production (Docker)
```bash
./build_and_run.sh
# or
docker build -t causalgame .
docker run -d -p 8000:80 \
  -v $(pwd)/agent_records:/app/agent_records \
  -e CAUSALGAME_EXPERIMENT=antenna_trap \
  causalgame
```

## Extension Points

1. **New Experiments**: Create SCM in `api/modules/environment/`, register with decorator
2. **New AI Models**: Extend `BaseHandler` in `agent/`
3. **New Game Mechanics**: Add pure functions in `api/modules/game/`
4. **New Visibility Rules**: Modify `VisibilityConfig` in `api/middleware/visibility.py`
