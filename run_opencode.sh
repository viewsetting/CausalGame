#!/bin/bash
#
# CausalGame - OpenCode Agent Runner
#
# Supports concurrent experiments via Docker Compose project isolation.
# Same experiment can have multiple models running against one game-backend.
# Different experiments get separate game-backends automatically.
#
# Usage:
#   ./run_opencode.sh -m openrouter/moonshotai/kimi-k2.5                    # Start
#   ./run_opencode.sh -m openrouter/moonshotai/kimi-k2.5 --run              # Start + run
#   ./run_opencode.sh -m openrouter/moonshotai/kimi-k2.5 --watch            # Watch thoughts
#   ./run_opencode.sh -e antenna_trap --down                                 # Stop experiment
#   ./run_opencode.sh --down-all                                             # Stop everything
#
# Concurrent example:
#   ./run_opencode.sh -e antenna_trap -m openrouter/moonshotai/kimi-k2.5     # Experiment A, Model 1
#   ./run_opencode.sh -e antenna_trap -m openai/gpt-5.2                      # Experiment A, Model 2 (shares backend)
#   ./run_opencode.sh -e weather_defense -m openai/gpt-5.2                   # Experiment B (separate backend)
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Defaults
EXPERIMENT="${EXPERIMENT:-antenna_trap}"
OPENCODE_MODEL="${OPENCODE_MODEL:-anthropic/claude-sonnet-4-20250514}"
ACTION="start"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --model|-m)
            OPENCODE_MODEL="$2"
            shift 2
            ;;
        --experiment|-e)
            EXPERIMENT="$2"
            shift 2
            ;;
        --run)
            ACTION="run"
            shift
            ;;
        --watch|-w)
            ACTION="watch"
            shift
            ;;
        --down|-d)
            ACTION="down"
            shift
            ;;
        --down-all)
            ACTION="down-all"
            shift
            ;;
        --logs|-l)
            ACTION="logs"
            shift
            ;;
        --rebuild|-r)
            ACTION="rebuild"
            shift
            ;;
        --status|-s)
            ACTION="status"
            shift
            ;;
        --list)
            ACTION="list"
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Lifecycle:"
            echo "  (no flag)                     Start containers for model + experiment"
            echo "  --run                          Auto-run the mission (headless)"
            echo "  --watch, -w                    Real-time view of agent thoughts"
            echo "  --down, -d                     Stop containers for this experiment"
            echo "  --down-all                     Stop ALL running experiments"
            echo "  --rebuild, -r                  Rebuild image and restart"
            echo ""
            echo "Config:"
            echo "  --model, -m MODEL              OpenCode model (provider/model-id)"
            echo "  --experiment, -e NAME           Experiment name (default: antenna_trap)"
            echo ""
            echo "Info:"
            echo "  --status, -s                   Show container and session status"
            echo "  --list                          List all running containers"
            echo "  --logs, -l                     View game backend logs"
            echo ""
            echo "Model examples:"
            echo "  openrouter/moonshotai/kimi-k2.5"
            echo "  anthropic/claude-sonnet-4-20250514"
            echo "  openai/gpt-5.2"
            echo "  google/gemini-2.5-pro"
            echo "  xai/grok-4"
            echo "  deepseek/deepseek-chat"
            echo ""
            echo "Experiments:"
            ls experiments/ 2>/dev/null | sed 's/^/  /'
            exit 0
            ;;
        *)
            echo "Unknown option: $1. Use --help for usage."
            exit 1
            ;;
    esac
done

# Derived values
OPENCODE_MODEL_SLUG=$(echo "$OPENCODE_MODEL" | sed 's|.*/||' | tr '.' '-')
PROJECT_NAME="sc-${EXPERIMENT}"
CONTAINER_NAME="opencode-${OPENCODE_MODEL_SLUG}"

export EXPERIMENT OPENCODE_MODEL OPENCODE_MODEL_SLUG

# Compose command with project isolation per experiment
COMPOSE="docker compose -p ${PROJECT_NAME} -f docker-compose.opencode.yml"

# Helper: find container for current model
find_container() {
    docker ps --filter "name=${CONTAINER_NAME}" --format '{{.Names}}' | head -1
}

# Helper: find all opencode containers
find_all_containers() {
    docker ps --filter "name=opencode-" --format '{{.Names}}'
}

case "$ACTION" in
    start)
        echo "=========================================="
        echo " CausalGame + OpenCode"
        echo "=========================================="
        echo " Experiment:  $EXPERIMENT"
        echo " Model:       $OPENCODE_MODEL"
        echo " Project:     $PROJECT_NAME"
        echo " Container:   $CONTAINER_NAME"
        echo "=========================================="
        echo ""

        mkdir -p agent_records agent_workspaces

        $COMPOSE up -d --build

        echo ""
        echo "Next steps:"
        echo "  $0 -e $EXPERIMENT -m $OPENCODE_MODEL --run      # Run mission"
        echo "  $0 -e $EXPERIMENT -m $OPENCODE_MODEL --watch    # Watch thoughts"
        echo "  $0 -e $EXPERIMENT -m $OPENCODE_MODEL --status   # Check results"
        echo "  $0 -e $EXPERIMENT --down                         # Stop this experiment"
        echo ""
        echo "Frontend: http://localhost:8000"
        ;;

    run)
        CONTAINER=$(find_container)
        if [ -z "$CONTAINER" ]; then
            echo "No container '$CONTAINER_NAME' found. Start with: $0 -e $EXPERIMENT -m $OPENCODE_MODEL"
            exit 1
        fi
        echo "[$EXPERIMENT / $OPENCODE_MODEL_SLUG] Running mission..."
        echo "Watch: $0 -e $EXPERIMENT -m $OPENCODE_MODEL --watch"
        echo ""
        docker exec "$CONTAINER" python3 -u /opt/system/run-mission.py
        ;;

    watch)
        CONTAINER=$(find_container)
        if [ -z "$CONTAINER" ]; then
            echo "No container '$CONTAINER_NAME' found."
            exit 1
        fi
        echo "[$EXPERIMENT / $OPENCODE_MODEL_SLUG] Watching thoughts (Ctrl+C to stop)..."
        echo ""
        docker logs -f --since 0s "$CONTAINER" 2>&1
        ;;

    down)
        echo "Stopping experiment: $EXPERIMENT..."
        $COMPOSE down
        echo "Done."
        ;;

    down-all)
        echo "Stopping all CausalGame experiments..."
        # Find all project names and stop them
        for project in $(docker compose ls --format json 2>/dev/null | python3 -c "
import sys, json
for p in json.load(sys.stdin):
    if p.get('Name','').startswith('sc-'):
        print(p['Name'])
" 2>/dev/null); do
            echo "  Stopping $project..."
            docker compose -p "$project" -f docker-compose.opencode.yml down 2>/dev/null
        done
        echo "Done."
        ;;

    logs)
        $COMPOSE logs -f game-backend
        ;;

    status)
        CONTAINER=$(find_container)
        if [ -z "$CONTAINER" ]; then
            echo "No container '$CONTAINER_NAME' found."
            exit 1
        fi
        echo "Container:  $CONTAINER"
        echo "Experiment: $EXPERIMENT"
        echo "Model:      $OPENCODE_MODEL"
        echo ""

        SESSION_ID=$(docker exec "$CONTAINER" python3 -c "import json;print(json.load(open('/opt/system/.session.json'))['session_id'])" 2>/dev/null)
        echo "Session:    $SESSION_ID"

        SESSION_FILE="agent_records/sessions/${SESSION_ID}.json"
        if [ -f "$SESSION_FILE" ]; then
            python3 -c "
import json
with open('$SESSION_FILE') as f:
    d = json.load(f)
print(f'Stage:      {d.get(\"stage\")}')
print(f'Game over:  {d.get(\"game_over\")}')
print(f'Deploys:    {d.get(\"deployments_used\")}/{d.get(\"stage1_deployment_budget\")}')
print(f'Flights:    {len(d.get(\"flight_history\",[]))}')
logs = d.get('logs', [])
from collections import Counter
types = Counter(l.get('type') for l in logs)
print(f'Logs:       {len(logs)} ({\", \".join(f\"{t}:{c}\" for t,c in sorted(types.items()))})')
if d.get('final_result'):
    print(f'Survival:   {d[\"final_result\"].get(\"survival_rate\")}')
    print(f'Victory:    {d[\"final_result\"].get(\"victory\")}')
"
        else
            echo "No session data yet."
        fi
        ;;

    list)
        echo "Running OpenCode containers:"
        echo ""
        CONTAINERS=$(find_all_containers)
        if [ -z "$CONTAINERS" ]; then
            echo "  (none)"
        else
            for c in $CONTAINERS; do
                SID=$(docker exec "$c" python3 -c "import json;print(json.load(open('/opt/system/.session.json'))['session_id'])" 2>/dev/null || echo "?")
                MODEL=$(docker exec "$c" python3 -c "import json;print(json.load(open('/opt/system/.session.json'))['model_name'])" 2>/dev/null || echo "?")
                EXP=$(docker exec "$c" python3 -c "import json;print(json.load(open('/opt/system/.session.json'))['experiment'])" 2>/dev/null || echo "?")
                echo "  $c  experiment=$EXP  model=$MODEL  session=$SID"
            done
        fi
        ;;

    rebuild)
        echo "Rebuilding $PROJECT_NAME..."
        $COMPOSE down
        $COMPOSE up -d --build
        echo "Done."
        ;;
esac
