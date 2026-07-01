#!/bin/bash
set -e

# All system files live in /opt/system/ — agent workspace is /workspace/ (clean)
SYSTEM_DIR="/opt/system"

# ── Configuration ──
EXPERIMENT="${EXPERIMENT:-antenna_trap}"
GAME_API="${GAME_API:-http://game-backend:80}"
MODEL="${OPENCODE_MODEL:-anthropic/claude-sonnet-4-20250514}"

echo "================================================"
echo " CausalGame - OpenCode Agent Environment"
echo "================================================"
echo " Experiment:  $EXPERIMENT"
echo " Model:       $MODEL"
echo " Game API:    $GAME_API"
echo "================================================"

# ── Map API key names for OpenCode ──
export GOOGLE_GENERATIVE_AI_API_KEY="${GEMINI_API_KEY:-$GOOGLE_GENERATIVE_AI_API_KEY}"

# ── Network isolation: only allow LLM APIs + game backend ──
echo "[setup] Configuring network whitelist..."
set +e  # Don't exit on iptables errors
if command -v iptables > /dev/null 2>&1; then
    # Allow loopback and established connections
    iptables -A OUTPUT -o lo -j ACCEPT
    iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
    # Allow DNS
    iptables -A OUTPUT -p udp --dport 53 -j ACCEPT
    iptables -A OUTPUT -p tcp --dport 53 -j ACCEPT
    # Allow Docker internal network (game backend)
    iptables -A OUTPUT -d 172.16.0.0/12 -j ACCEPT
    iptables -A OUTPUT -d 10.0.0.0/8 -j ACCEPT
    iptables -A OUTPUT -d 192.168.0.0/16 -j ACCEPT
    # Allow LLM API endpoints (resolve IPv4 only at startup)
    LLM_DOMAINS="openrouter.ai api.anthropic.com api.openai.com generativelanguage.googleapis.com api.x.ai api.deepseek.com api.groq.com api.mistral.ai api.together.xyz api.cohere.com"
    for domain in $LLM_DOMAINS; do
        for ip in $(getent ahostsv4 "$domain" 2>/dev/null | awk '{print $1}' | sort -u); do
            iptables -A OUTPUT -d "$ip" -j ACCEPT 2>/dev/null
        done
    done
    # Block everything else
    iptables -A OUTPUT -j DROP
    echo "[setup] Network whitelist applied (LLM APIs + game backend only)"
else
    echo "[setup] WARNING: iptables not available, network not restricted"
fi
set -e  # Restore strict mode

# ── Admin token: bootstrap only, then scrub from env before opencode starts ──
# The operator injects ADMIN_TOKEN via docker run -e; entrypoint uses it here
# for legitimate switch/health calls, then unsets it so the LLM shell cannot
# read it via `env` or `printenv` and hit /api/admin/* on its own.
ADMIN_HDR=()
if [ -n "${ADMIN_TOKEN:-}" ]; then
    ADMIN_HDR=(-H "X-Admin-Token: ${ADMIN_TOKEN}")
fi

# ── Wait for game backend ──
echo "[setup] Waiting for game backend..."
for i in $(seq 1 30); do
    if curl -sf "${ADMIN_HDR[@]}" "${GAME_API}/api/admin/experiments" > /dev/null 2>&1; then
        echo "[setup] Game backend is ready."
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "[setup] WARNING: Game backend not responding, continuing anyway."
    fi
    sleep 2
done

# ── Switch experiment on backend ──
echo "[setup] Switching backend to experiment: ${EXPERIMENT}"
curl -sf -X POST "${ADMIN_HDR[@]}" "${GAME_API}/api/admin/experiment/switch?experiment_name=${EXPERIMENT}" > /dev/null 2>&1 || true

# ── Pre-register game session ──
echo "[setup] Registering game session..."
MODEL_SHORT=$(echo "$MODEL" | sed 's|.*/||')
REGISTER_RESULT=$(curl -sf -X POST "${GAME_API}/api/agent/register" \
    -H "Content-Type: application/json" \
    -d "{\"agent_name\": \"opencode-${MODEL_SHORT}\", \"model_name\": \"${MODEL_SHORT}\", \"execution_mode\": \"opencode\"}" 2>/dev/null || echo "{}")

SESSION_ID=$(echo "$REGISTER_RESULT" | jq -r '.session_id // empty')
if [ -z "$SESSION_ID" ]; then
    echo "[setup] WARNING: Failed to register session."
    SESSION_ID="default"
fi
echo "[setup] Session ID: ${SESSION_ID}"

export SESSION_ID
export MODEL_NAME="$MODEL_SHORT"

# ── Read experiment config from system dir (agent never sees this) ──
GAME_JSON="${SYSTEM_DIR}/experiments/${EXPERIMENT}/game.json"
if [ -f "$GAME_JSON" ]; then
    TOTAL_DRONES=$(jq -r '.resources.total_drone_budget // 200' "$GAME_JSON")
    STAGE2_FLEET=$(jq -r '.resources.stage2_fleet_size // 1000' "$GAME_JSON")
    VICTORY_THRESHOLD=$(jq -r '.resources.victory_threshold // 0.75' "$GAME_JSON")
    DEPLOY_BUDGET=$(jq -r '.resources.stage1_deployment_budget // 10' "$GAME_JSON")
    ENV_QUERY_BUDGET=$(jq -r '.resources.env_query_budget // 10' "$GAME_JSON")
    DISPLAY_NAME=$(jq -r '.experiment.display_name // "Unknown"' "$GAME_JSON")
    COMPONENT_DETAILS=$(jq -r '.drone.components | to_entries | map("  - \(.key)_def (default: \(.value.default_def))") | join("\n")' "$GAME_JSON")
    echo "[setup] Loaded config: ${DISPLAY_NAME}"
else
    echo "[setup] WARNING: No game.json found for experiment '${EXPERIMENT}'"
    TOTAL_DRONES=200; STAGE2_FLEET=1000; VICTORY_THRESHOLD=0.75
    DEPLOY_BUDGET=10; ENV_QUERY_BUDGET=10; DISPLAY_NAME="$EXPERIMENT"
    COMPONENT_DETAILS="  - engine_def (default: 20)\n  - cockpit_def (default: 20)\n  - wing_def (default: 15)\n  - body_def (default: 15)\n  - antenna_def (default: 10)\n  - camera_def (default: 5)\n  - gun_def (default: 5)"
fi

VICTORY_PCT=$(echo "${VICTORY_THRESHOLD} * 100" | bc 2>/dev/null || echo "75")

# ── Generate opencode.json (no MCP, direct API via bash) ──
STEPS="${OPENCODE_STEPS:-30}"

cat > /workspace/opencode.json << HEREDOC
{
  "\$schema": "https://opencode.ai/config.json",
  "model": "${MODEL}",
  "permission": {
    "*": "allow"
  },
  "agent": {
    "build": {
      "steps": ${STEPS}
    }
  },
  "tools": {
    "websearch": false,
    "webfetch": false,
    "codesearch": false
  },
  "instructions": ["MISSION.md"]
}
HEREDOC

echo "[setup] Generated opencode.json (model: ${MODEL}, steps: ${STEPS})"

# ── Generate MISSION.md (direct API, experiment-neutral, no leaks) ──
cat > /workspace/MISSION.md << HEREDOC
# Drone Optimization Mission

You are a Drone Designer. Your goal is to optimize drone designs for maximum survival
in a hostile environment. The simulation is a BLACK BOX — you must discover the rules
through observation and experimentation.

## API

Interact with the game via HTTP API. The session is pre-registered.

**Base URL**: \`${GAME_API}\`
**Session Header**: \`X-Session-ID: ${SESSION_ID}\`

### Check Mission Status
\`\`\`bash
curl -s ${GAME_API}/api/agent/status -H "X-Session-ID: ${SESSION_ID}" | python -m json.tool
\`\`\`

### Get Flight History
\`\`\`bash
curl -s ${GAME_API}/api/agent/history -H "X-Session-ID: ${SESSION_ID}" | python -m json.tool
\`\`\`

### Deploy Drones
\`\`\`bash
curl -s -X POST ${GAME_API}/api/agent/deploy \\
  -H "Content-Type: application/json" \\
  -H "X-Session-ID: ${SESSION_ID}" \\
  -d '{"design": {"engine_def": 20, "antenna_def": 10, "wing_def": 15}, "count": 10}' | python -m json.tool
\`\`\`

### Query Environment (discover hidden variables)
\`\`\`bash
curl -s -X POST ${GAME_API}/api/agent/query-environment \\
  -H "Content-Type: application/json" \\
  -H "X-Session-ID: ${SESSION_ID}" \\
  -d '{"query": "what hidden factors affect drone survival?"}' | python -m json.tool
\`\`\`

### Submit Final Design (ONE CHANCE ONLY!)
\`\`\`bash
curl -s -X POST ${GAME_API}/api/agent/submit \\
  -H "Content-Type: application/json" \\
  -H "X-Session-ID: ${SESSION_ID}" \\
  -d '{"design": {"engine_def": 20, "antenna_def": 0}}' | python -m json.tool
\`\`\`

## Resources
- **Drone budget**: ${TOTAL_DRONES} drones for Stage 1 exploration
- **Deploy calls**: ${DEPLOY_BUDGET} maximum deployments in Stage 1
- **Environment queries**: ${ENV_QUERY_BUDGET} (use wisely — cannot be refilled)
- **Stage 2 fleet**: ${STAGE2_FLEET} drones will be deployed with your final design
- **Victory threshold**: ${VICTORY_PCT}% survival rate required

## Design Parameters
You set DEF (defense/armor) values for each component:
${COMPONENT_DETAILS}

Omitted components use their default DEF value.

## What You Know
- You control DEF values only. HP is fixed and hidden.
- You only see **surviving** drones in results — destroyed drones are hidden.
- Environmental conditions vary and may affect outcomes.
- Not all relevant variables are directly observable.

## What You Don't Know
- The true relationship between design choices and survival.
- Which environmental factors matter and how.
- Whether there are hidden confounders or non-obvious interactions.

**Your job is to figure this out through experimentation.**

## Game Flow
1. **Stage 1 — Exploration**: Deploy drones, observe results, form hypotheses, test them.
2. **Stage 2 — Evaluation**: Submit ONE final design. ${STAGE2_FLEET} drones are deployed automatically. You cannot change your design after submission.

## Analysis
Write Python scripts for data analysis. **Only numpy and pandas are available.**
Use \`curl\` for API calls and \`python\` for analysis.
HEREDOC

echo "[setup] Generated MISSION.md (direct API mode)"

# ── Write session info to system dir (agent can't see it) ──
cat > ${SYSTEM_DIR}/.session.json << HEREDOC
{
  "session_id": "${SESSION_ID}",
  "model_name": "${MODEL_SHORT}",
  "experiment": "${EXPERIMENT}",
  "game_api": "${GAME_API}"
}
HEREDOC

echo "[setup] Setup complete."
echo ""

# ── Scrub ADMIN_TOKEN before handing control to opencode/LLM ──
unset ADMIN_TOKEN
ADMIN_HDR=()

# ── Start ──
case "${1:-serve}" in
    serve)
        echo "[start] Starting SSE bridge in background..."
        bun run ${SYSTEM_DIR}/sse-bridge.ts > /proc/1/fd/1 2>/proc/1/fd/2 &
        SSE_PID=$!
        echo "[start] SSE bridge PID: $SSE_PID"

        echo "[start] Starting OpenCode serve (port 4096)"
        echo ""
        echo "  Run:     docker exec <container> python3 /opt/system/run-mission.py"
        echo ""
        exec opencode serve --port 4096
        ;;
    tui)
        echo "[start] Starting SSE bridge in background..."
        bun run ${SYSTEM_DIR}/sse-bridge.ts &

        echo "[start] Starting OpenCode TUI"
        exec opencode
        ;;
    idle)
        echo "[start] Container idle. Attach with: docker exec -it <container> opencode"
        exec tail -f /dev/null
        ;;
    *)
        exec "$@"
        ;;
esac
