# CausalGame

**Benchmarking Causal Thinking of LLM Agents in Games** — ICML 2026 (**Oral**)

[🌐 Project page & leaderboard](https://causalgame.github.io) ·
[📄 Paper (arXiv coming soon)](https://causalgame.github.io)

CausalGame evaluates the *causal thinking* of LLM agents through interactive games.
The agent acts as a drone designer who must uncover the hidden causal mechanism behind
drone survival through a limited budget of experiments — under observations that are
**censored by survivorship**, **confounded by hidden variables**, and **corrupted by
noise**. Every scenario is governed by an underlying structural causal model (SCM):
the agent can only win by recovering the true causal mechanism rather than fitting
surface-level correlations.

- **14 game scenarios** across three families (Antenna Trap, Deployment Zone Trap,
  Weather), instantiating selection bias, hidden confounders, noisy measurements,
  local optima, and environment shift
- **Two-stage protocol**: exploration (200 drones, ≤10 deployments) → one-shot
  evaluation on a 1,000-drone fleet against a scenario-specific win threshold
- **Multiple execution modes**: Agentic (ReAct tool calling), Prompting (single-turn
  code execution), and an OpenCode coding-agent harness
- **29 frontier LLMs** evaluated in the paper — see the
  [leaderboard](https://causalgame.github.io/leaderboard/)

## Quick start

### 1. Install

```bash
git clone https://github.com/viewsetting/CausalGame.git
cd CausalGame
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in the API keys you need
```

### 2. Start the simulation backend

```bash
uvicorn api.app:app --port 8000
# or with Docker:
# docker build -t causalgame . && docker run -p 8000:8000 causalgame
```

The default scenario is `antenna_trap`; switch via the `CAUSALGAME_EXPERIMENT`
environment variable or the admin API:

```bash
curl -X POST "http://localhost:8000/api/admin/experiment/switch?experiment_name=weather_noise"
```

### 3. Run an agent

```bash
python run_agent.py --list-models                 # see the 29 configured models

# Prompting mode (single-context, agent writes Python against `client`)
python run_agent.py --model gpt-5-mini --experiment antenna_trap --mode legacy

# Agentic mode (multi-turn ReAct tool calling)
python run_agent.py --model gpt-5-mini --experiment antenna_trap --mode hybrid
```

> Mode naming: `--mode hybrid` is the paper's **Agentic (ReAct)** mode and
> `--mode legacy` is the paper's **Prompting** mode.

### OpenCode mode (optional)

The coding-agent harness used for the paper's OpenCode comparison runs the game
backend and an [OpenCode](https://opencode.ai) agent in Docker:

```bash
./run_opencode.sh -e antenna_trap -m openrouter/moonshotai/kimi-k2.5 --run
```

## The 14 scenarios

| Scenario | Selection bias | Hidden confounder | Threshold |
|---|:---:|:---:|---:|
| `antenna_trap` | ✓ | — | 75% |
| `antenna_trap_high_def` | ✓ | ✓ | 75% |
| `antenna_trap_local_optima` | ✓ | — | 75% |
| `antenna_trap_no_history` | ✓ | — | 75% |
| `antenna_trap_no_selection_bias` | — | — | 75% |
| `antenna_trap_simpsons_paradox` | ✓ | ✓ | 75% |
| `deployment_zone_trap_categorical` | ✓ | — | 75% |
| `deployment_zone_trap_categorical_high_def` | ✓ | ✓ | 75% |
| `deployment_zone_trap_categorical_local_optima` | ✓ | — | 75% |
| `deployment_zone_trap_categorical_no_history` | ✓ | — | 75% |
| `deployment_zone_trap_categorical_no_selection_bias` | — | — | 75% |
| `deployment_zone_trap_categorical_simpsons_paradox` | ✓ | ✓ | 75% |
| `deployment_zone_trap_env_shift` | ✓ | — | 75% |
| `weather_noise` | ✓ | — | 55% |

Scenario configs live in `experiments/<name>/` (`game.json`, `action_space.json`,
`environment_variables.json`, prompts). Fully specified structural equations for all
scenarios are given in the paper appendix.

## Project structure

```
CausalGame/
├── api/                 # FastAPI simulation engine
│   ├── middleware/      #   DroneSheet (single source of truth), visibility control
│   └── modules/         #   SCM environments, game logic (combat/damage/judge), agent API
├── agent/               # LLM agent harness (providers, tools, sandbox, orchestrator)
├── experiments/         # the 14 benchmark scenario configs
├── config/              # agent.json (29 paper models), server.json
├── docs/                # architecture, API reference, adding new SCM scenarios
├── run_agent.py         # single-run entry point (one model × one scenario)
└── run_opencode.sh      # OpenCode coding-agent harness (Docker)
```

## Adding a new scenario

Scenarios are pluggable SCMs registered with the `@register_scm()` decorator —
see [`docs/adding-new-scm.md`](docs/adding-new-scm.md).

## Tests

```bash
python -m unittest discover -s tests
```

## Citation

```bibtex
@inproceedings{chen2026causalgame,
  title     = {CausalGame: Benchmarking Causal Thinking of LLM Agents in Games},
  author    = {Chen, Zhenhao and Chen, Yongqiang and Liu, Chenxi and Yu, Junchi
               and Song, Xiangchen and Li, Zijian and Li, Jialin
               and Torr, Philip and Han, Bo and Zhang, Kun},
  booktitle = {Proceedings of the 43rd International Conference on Machine Learning (ICML)},
  year      = {2026},
  note      = {Oral presentation}
}
```

## License

[MIT](LICENSE)
