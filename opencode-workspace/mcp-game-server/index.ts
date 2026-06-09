/**
 * CausalGame MCP Game Server
 *
 * Wraps the game backend API as MCP tools so OpenCode can call them natively.
 * Also auto-logs every action to POST /api/agent/log for session recording.
 *
 * Environment:
 *   GAME_API    - Game backend URL (default: http://game-backend:80)
 *   SESSION_ID  - Pre-registered game session ID
 *   MODEL_NAME  - Model name for log metadata
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

import { readFileSync } from "fs";

// Read config dynamically — session ID may change between runs
const SESSION_FILE = "/opt/system/.session.json";

function getConfig() {
  let config = { session_id: "", model_name: "opencode-agent", game_api: "http://game-backend:80" };
  try {
    config = JSON.parse(readFileSync(SESSION_FILE, "utf-8"));
  } catch {}
  // .session.json takes priority (updated dynamically by run-mission.py)
  // env vars are fallback (set once at MCP server startup, may be stale)
  return {
    gameApi: config.game_api || process.env.GAME_API || "http://game-backend:80",
    sessionId: config.session_id || process.env.SESSION_ID || "",
    modelName: config.model_name || process.env.MODEL_NAME || "opencode-agent",
  };
}

// Log initial config to stderr (stdout is MCP protocol)
const initConfig = getConfig();
console.error(`[mcp-game-server] Initial: API=${initConfig.gameApi} SESSION=${initConfig.sessionId} MODEL=${initConfig.modelName}`);

// ── HTTP helpers ──

async function gameRequest(method: string, path: string, body?: any): Promise<any> {
  const { gameApi, sessionId } = getConfig();
  const res = await fetch(`${gameApi}${path}`, {
    method,
    headers: {
      "Content-Type": "application/json",
      "X-Session-ID": sessionId,
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  return res.json();
}

async function postLog(type: string, content: string, metadata?: any): Promise<void> {
  const { gameApi, sessionId, modelName } = getConfig();
  try {
    await fetch(`${gameApi}/api/agent/log`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Session-ID": sessionId,
      },
      body: JSON.stringify({
        type,
        content,
        timestamp: new Date().toISOString(),
        metadata: { model: modelName, source: "mcp", ...metadata },
      }),
    });
  } catch {
    // Non-critical
  }
}

// ── MCP Server ──

const server = new McpServer({
  name: "causalgame",
  version: "1.0.0",
});

// Tool: get_mission_status
server.tool(
  "get_mission_status",
  "Get current mission state: stage, drones remaining, survival rate, etc.",
  {},
  async () => {
    const result = await gameRequest("GET", "/api/agent/status");
    await postLog("ACTION", "get_mission_status()", { tool: "get_mission_status" });
    return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
  }
);

// Tool: get_flight_history
server.tool(
  "get_flight_history",
  "Retrieve all past deployment results including survival status, hit count, and environment data.",
  {},
  async () => {
    const result = await gameRequest("GET", "/api/agent/history");
    await postLog("ACTION", "get_flight_history()", { tool: "get_flight_history" });
    return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
  }
);

// Tool: deploy_drone
server.tool(
  "deploy_drone",
  "Deploy drones with a specific DEF (armor) design. Returns survival results for each drone.",
  {
    design: z.record(z.string(), z.number()).describe(
      "DEF allocation for components, e.g. {\"engine_def\": 20, \"antenna_def\": 0, \"wing_def\": 15}"
    ),
    count: z.number().min(1).max(50).default(10).describe(
      "Number of drones to deploy (1-50, default: 10)"
    ),
  },
  async ({ design, count }) => {
    const result = await gameRequest("POST", "/api/agent/deploy", { design, count });
    await postLog(
      "ACTION",
      `deploy_drone(design=${JSON.stringify(design)}, count=${count})`,
      { tool: "deploy_drone", design, count, result_summary: {
        deployed: result.deployed,
        survived: result.survived,
        survival_rate: result.survival_rate,
      }}
    );
    return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
  }
);

// Tool: query_environment
server.tool(
  "query_environment",
  "Query hidden environmental variables using natural language. Limited budget - use wisely!",
  {
    query: z.string().describe(
      "Natural language query about the environment, e.g. 'what is the weather like?'"
    ),
  },
  async ({ query }) => {
    const result = await gameRequest("POST", "/api/agent/query-environment", { query });
    await postLog(
      "ACTION",
      `query_environment("${query}")`,
      { tool: "query_environment", query }
    );
    return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
  }
);

// Tool: submit_final_design
server.tool(
  "submit_final_design",
  "Submit your final drone design for Stage 2 evaluation. THIS IS IRREVERSIBLE - you only get ONE chance!",
  {
    design: z.record(z.string(), z.number()).describe(
      "Final DEF allocation, e.g. {\"engine_def\": 20, \"antenna_def\": 0, \"wing_def\": 15}"
    ),
  },
  async ({ design }) => {
    const result = await gameRequest("POST", "/api/agent/submit", { design });
    await postLog(
      "ACTION",
      `submit_final_design(design=${JSON.stringify(design)})`,
      { tool: "submit_final_design", design, result }
    );
    return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
  }
);

// ── Start ──

const transport = new StdioServerTransport();
await server.connect(transport);
