# CausalGame API Reference

Backend API documentation for CausalGame drone simulation.

**Base URL**: `http://localhost:8000`

---

## Agent API (`/api/agent/`)

Agent endpoints return **filtered data** - HP values, agility, and internal state are hidden.

### POST `/api/agent/register`

Register an agent and create a session.

**Request Body:**
```json
{
  "model_name": "gpt-4",
  "agent_name": "my-agent",
  "experiment": "antenna_trap",
  "execution_mode": "hybrid"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `model_name` | string | No | Name of the AI model |
| `agent_name` | string | No | Agent identifier |
| `experiment` | string | No | Experiment name (uses server default if not specified) |
| `execution_mode` | string | No | `"legacy"` (code execution) or `"hybrid"` (tool calling) |

**Response:**
```json
{
  "status": "registered",
  "session_id": "abc12345",
  "experiment": "mission",
  "initial_status": { ... }
}
```

---

### GET `/api/agent/status`

Get current mission status.

**Headers:**
- `X-Session-ID`: Session ID (optional, uses default if not provided)

**Response:**
```json
{
  "drones_remaining": 150,
  "drones_used": 50,
  "total_drones": 200,
  "history_count": 50,
  "victory_threshold": 0.75,
  "stage2_fleet_size": 1000,
  "experiment": {"name": "mission", "display_name": "Canyon Mission"},
  "game_over": false,
  "final_evaluation": null,
  "deployments_used": 5,
  "deployments_remaining": 5,
  "stage1_deployment_budget": 10,
  "env_queries_used": 2,
  "env_queries_remaining": 8,
  "env_query_budget": 10,
  "token_usage": {"input_tokens": 10000, "output_tokens": 500, "total_tokens": 10500}
}
```

---

### POST `/api/agent/deploy`

Deploy drones with specified design.

**Headers:**
- `X-Session-ID`: Session ID (optional)

**Request Body:**
```json
{
  "design": {
    "engine_def": 20,
    "cockpit_def": 20,
    "wing_def": 15,
    "body_def": 10,
    "antenna_def": 10,
    "camera_def": 5,
    "gun_def": 5,
    "shield_def": 0
  },
  "count": 10,
  "equipment": {
    "signal_processing": "noise_reduction",
    "power_mode": "balanced"
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `design` | object | Yes | DEF values for each component |
| `count` | int | No | Number of drones (1-50, default: 1) |
| `equipment` | object | No | Equipment choices for action space slots |

**Response:**
```json
{
  "status": "BATCH_COMPLETE",
  "deployed": 10,
  "survived": 7,
  "destroyed": 3,
  "average_hit_count": 2.5,
  "drones_remaining": 140,
  "results": [
    {
      "id": "SESSION_abc_001",
      "status": "RETURNED",
      "hit_count": 2,
      "design": { ... }
    }
  ],
  "environment": {
    "weather": "clear",
    "wind_speed": 25.3
  }
}
```

**Note:** Agent only sees RETURNED drones. DESTROYED/LOST drones are filtered out.

---

### POST `/api/agent/submit`

Submit final design for Stage 2 evaluation. **One-time only!**

**Headers:**
- `X-Session-ID`: Session ID (optional)

**Request Body:**
```json
{
  "design": {
    "engine_def": 25,
    "cockpit_def": 20,
    "wing_def": 15,
    "body_def": 10,
    "antenna_def": 5,
    "camera_def": 5,
    "gun_def": 5,
    "shield_def": 0
  },
  "equipment": { ... }
}
```

**Response:**
```json
{
  "status": "EVALUATION_COMPLETE",
  "fleet_size": 1000,
  "survived": 750,
  "survival_rate": "75.0%",
  "final_score": "75.0%",
  "victory": true,
  "victory_threshold": "75.0%",
  "message": "VICTORY! Mission accomplished!"
}
```

---

### GET `/api/agent/history`

Get flight history (agent view, filtered).

**Headers:**
- `X-Session-ID`: Session ID (optional)

**Response:**
```json
[
  {
    "id": "SESSION_abc_001",
    "status": "RETURNED",
    "hit_count": 2,
    "design": { ... },
    "environment": { ... }
  }
]
```

---

### POST `/api/agent/log`

Add a log entry from agent.

**Headers:**
- `X-Session-ID`: Session ID (optional)

**Request Body (Agent format):**
```json
{
  "type": "THOUGHT",
  "content": "Analyzing deployment results...",
  "timestamp": "2024-01-28T12:00:00Z",
  "metadata": {"model": "gpt-4"}
}
```

**Request Body (Simple format):**
```json
{
  "message": "Starting exploration",
  "level": "info"
}
```

---

### POST `/api/agent/token_usage`

Update token usage for the session.

**Headers:**
- `X-Session-ID`: Session ID (optional)

**Request Body:**
```json
{
  "input_tokens": 50000,
  "output_tokens": 5000
}
```

---

### POST `/api/agent/session_config`

Update session configuration (max_turns, current_turn).

**Request Body:**
```json
{
  "max_turns": 20,
  "current_turn": 5,
  "final_turn": null
}
```

---

### POST `/api/agent/conversation_history`

Save LLM conversation history for resume support.

**Request Body:**
```json
{
  "conversation_history": [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ]
}
```

---

### GET `/api/agent/conversation_history`

Get saved conversation history for resuming.

---

### POST `/api/agent/report_error`

Report an error from the agent.

**Headers:**
- `X-Session-ID`: Required

**Request Body:**
```json
{
  "error": "API timeout after 30 seconds",
  "error_type": "timeout",
  "fatal": true
}
```

---

### POST `/api/agent/reset`

Reset the current session.

**Headers:**
- `X-Session-ID`: Session ID (optional)

---

## Admin API (`/api/admin/`)

Admin endpoints return **complete data** including hidden values.

### GET `/api/admin/mission_status`

Get full mission status with hidden values.

**Response:**
```json
{
  "api_version": "v2",
  "experiment_name": "antenna_trap",
  "experiment_type": "def_based",
  "drones_remaining": 150,
  "drones_used": 50,
  "total_drones": 200,
  "deployments_used": 5,
  "deployments_remaining": 5,
  "stage1_deployment_budget": 10,
  "env_queries_used": 2,
  "env_queries_remaining": 8,
  "env_query_budget": 10,
  "hidden_hp_values": {
    "engine": 80,
    "cockpit": 60,
    "wing": 40
  },
  "agility_config": { ... },
  "stage": 1,
  "game_over": false,
  "history_count": 50,
  "survivors": 35,
  "victory_threshold": 0.75,
  "stage2_fleet_size": 1000,
  "final_evaluation": null
}
```

---

### GET `/api/admin/experiments`

List all available experiments.

**Response:**
```json
[
  {
    "name": "antenna_trap",
    "display_name": "Antenna Trap",
    "description": "Weather confounds antenna detection",
    "version": "1.0",
    "scm_class": "AntennaTrapSCM",
    "path": "/experiments/antenna_trap/game.json",
    "is_default": true,
    "tags": ["causal", "medium"]
  }
]
```

---

### GET `/api/admin/experiment/current`

Get currently active experiment info.

**Response:**
```json
{
  "name": "antenna_trap",
  "display_name": "Antenna Trap",
  "scm_class": "AntennaTrapSCM",
  "architecture": {
    "mode": "flat",
    "is_layered": false
  }
}
```

---

### POST `/api/admin/experiment/switch?experiment_name=weather_defense`

Switch to a different experiment. Resets the session.

---

### GET `/api/admin/sessions`

List all active sessions.

**Response:**
```json
[
  {
    "session_id": "abc12345",
    "agent_name": "agent-gpt-4",
    "model_name": "gpt-4",
    "created_at": "2024-01-28T12:00:00Z",
    "last_activity": "2024-01-28T12:30:00Z",
    "experiment_name": "antenna_trap",
    "stage": 1,
    "game_over": false,
    "drones_used": 50,
    "deployments_used": 5,
    "final_result": null,
    "token_usage": { ... }
  }
]
```

---

### GET `/api/admin/sessions/{session_id}`

Get detailed session information.

---

### DELETE `/api/admin/sessions/{session_id}`

Delete a specific session.

---

### DELETE `/api/admin/sessions`

Delete all sessions.

---

### POST `/api/admin/test-deploy`

Admin test deployment (does NOT consume budget).

**Request Body:**
```json
{
  "design": {"engine_def": 20, "antenna_def": 25},
  "count": 10,
  "equipment": {},
  "session_id": "abc12345"
}
```

**Response:**
```json
{
  "status": "TEST_COMPLETE",
  "deployed": 10,
  "survived": 7,
  "destroyed": 3,
  "survival_rate": "70.0%",
  "is_test": true,
  "note": "Test deployment - does not consume budget, can be deleted"
}
```

---

### GET `/api/admin/sessions/{session_id}/test-data/count`

Get count of test flights in a session.

---

### DELETE `/api/admin/sessions/{session_id}/test-data`

Delete all test flights from a session (preserves real agent data).

---

### POST `/api/admin/sessions/{session_id}/clear-error`

Clear error state to allow resuming a failed session.

---

### GET `/api/admin/scm_model`

Get SCM structure for frontend visualization.

**Response:**
```json
{
  "variables": [
    {
      "name": "weather",
      "is_exogenous": true,
      "description": "Weather condition",
      "parents": []
    }
  ],
  "equations": [
    {
      "target": "detection",
      "description": "Detection probability calculation",
      "source_code": "..."
    }
  ],
  "game_parameters": {
    "standard_design": { ... },
    "total_drone_budget": 200,
    "critical_components": ["engine", "cockpit"]
  },
  "causal_graph_text": "..."
}
```

---

### GET `/api/admin/config`

Get current experiment configuration.

---

### GET `/api/admin/config/game`

Get game.json for current experiment.

---

### PUT `/api/admin/config/game`

Update game.json (requires game reset to apply).

---

### GET `/api/admin/config/environment_variables`

Get environment_variables.json for current experiment.

---

### PUT `/api/admin/config/environment_variables`

Update environment_variables.json.

---

### GET `/api/admin/config/status`

Check if config can be modified (game over or no flights yet).

---

### GET `/api/admin/statistics`

Get global statistics across all sessions.

---

### GET `/api/admin/agent/logs?session_id=abc`

Get agent logs for a session.

---

### GET `/api/admin/flight_history`

Get complete flight history with all details (including HP).

---

### PUT `/api/admin/visibility`

Update field visibility settings.

**Request Body:**
```json
{
  "field": "hp",
  "visibility": "admin"
}
```

---

### POST `/api/admin/reset`

Admin reset - clears all sessions.

---

### POST `/api/admin/sessions/cleanup?max_age_seconds=3600`

Clean up inactive sessions older than specified age.

---

### GET `/api/admin/server_config`

Get server configuration (timezone, etc).

**Response:**
```json
{
  "timezone": "Asia/Dubai",
  "server_time": "2024-01-28T12:00:00+04:00"
}
```

---

## Legacy API (`/api/`)

For backward compatibility.

### GET `/api/mission_data?session_id=abc`

Get flight history (supports session filtering).

### GET `/api/session_history?session_id=abc`

Alias for `/api/mission_data`.

### GET `/api/status?session_id=abc`

Get mission status.

---

## Headers

| Header | Description |
|--------|-------------|
| `X-Session-ID` | Session identifier for multi-agent support |
| `Content-Type` | `application/json` for POST/PUT requests |

---

## Error Responses

All endpoints return errors in this format:

```json
{
  "detail": "Error message here"
}
```

Common HTTP status codes:
- `400` - Bad Request (invalid parameters)
- `404` - Not Found (session/resource not found)
- `500` - Internal Server Error

---

## Design Keys

Valid component DEF keys:
- `engine_def`
- `cockpit_def`
- `wing_def`
- `body_def`
- `antenna_def`
- `camera_def`
- `gun_def`
- `shield_def`
