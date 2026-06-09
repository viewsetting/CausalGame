/**
 * SSE Bridge: Real-time sync of OpenCode thoughts to game backend logs.
 *
 * Connects to OpenCode's SSE event stream and forwards:
 *   - reasoning parts → THOUGHT logs
 *   - text parts       → THOUGHT logs
 *   - tool error parts → ERROR logs
 *
 * ACTION logs are handled by the MCP server, so we skip tool parts here.
 *
 * Reads session config from /workspace/.session.json as fallback for env vars.
 */

import { readFileSync } from "fs";

const OPENCODE_URL = process.env.OPENCODE_URL || "http://localhost:4096";
const SESSION_FILE = "/opt/system/.session.json";

function getConfig() {
  let config = { session_id: "", model_name: "opencode-agent", game_api: "http://game-backend:80" };
  try {
    config = JSON.parse(readFileSync(SESSION_FILE, "utf-8"));
  } catch {}
  // .session.json takes priority (updated dynamically by run-mission.py)
  return {
    gameApi: config.game_api || process.env.GAME_API || "http://game-backend:80",
    sessionId: config.session_id || process.env.SESSION_ID || "",
    modelName: config.model_name || process.env.MODEL_NAME || "opencode-agent",
  };
}

// Track which parts we've already logged (by content hash) to avoid duplicates
const loggedHashes = new Set<string>();

function contentHash(s: string): string {
  // Simple hash to deduplicate — same content from SSE and poll won't double-post
  let h = 0;
  for (let i = 0; i < Math.min(s.length, 200); i++) {
    h = ((h << 5) - h + s.charCodeAt(i)) | 0;
  }
  return String(h);
}

async function postLog(type: string, content: string, metadata?: any): Promise<void> {
  const hash = contentHash(content);
  if (loggedHashes.has(hash)) return;
  loggedHashes.add(hash);

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
        metadata: { model: modelName, source: "sse-bridge", ...metadata },
      }),
    });
    // Print full content, preserving newlines for readability
    console.log(`\n[bridge] ${type}:\n${content}\n`);
  } catch {
    // Non-critical
  }
}

function processEvent(eventType: string, data: any): void {
  try {
    // OpenCode SSE event structure: {"type":"message.part.updated","properties":{"part":{...}}}
    const partData = data?.properties?.part || data?.properties?.data || data?.data || data;
    if (!partData) return;

    const partType = partData?.type;

    if (partType === "reasoning" && partData.text) {
      postLog("THOUGHT", partData.text, { part_type: "reasoning" });
    } else if (partType === "text" && (partData.content || partData.text)) {
      postLog("THOUGHT", partData.content || partData.text, { part_type: "text" });
    } else if (partType === "tool" && partData.state?.status === "error") {
      const errorMsg = partData.state.error || "Unknown tool error";
      postLog("ERROR", `Tool ${partData.tool} failed: ${errorMsg}`, {
        part_type: "tool_error",
        tool: partData.tool,
      });
    }
  } catch {
    // Silently ignore parse errors
  }
}

async function connectSSE(): Promise<void> {
  const cfg = getConfig();
  console.log(`[bridge] Config: OPENCODE=${OPENCODE_URL} GAME=${cfg.gameApi} SESSION=${cfg.sessionId}`);

  while (true) {
    try {
      const response = await fetch(`${OPENCODE_URL}/event`, {
        headers: { Accept: "text/event-stream" },
      });

      if (!response.ok) {
        await Bun.sleep(5000);
        continue;
      }

      console.log("[bridge] SSE connected, listening...");

      const reader = response.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let currentEventType = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("event: ")) {
            currentEventType = line.slice(7).trim();
          } else if (line.startsWith("data: ")) {
            try {
              const data = JSON.parse(line.slice(6));
              processEvent(currentEventType, data);
            } catch {}
          } else if (line === "") {
            currentEventType = "";
          }
        }
      }
    } catch {}

    await Bun.sleep(5000);
  }
}

// Polling fallback: catches anything SSE misses
async function pollMessages(): Promise<void> {
  // Wait for serve to be ready
  await Bun.sleep(15000);

  let processedParts = new Set<string>();

  while (true) {
    await Bun.sleep(8000);

    try {
      const sessionsRes = await fetch(`${OPENCODE_URL}/session`);
      if (!sessionsRes.ok) continue;

      const sessions: any[] = await sessionsRes.json();
      if (!sessions.length) continue;

      // Check all recent sessions (not just the first)
      for (const session of sessions.slice(0, 3)) {
        const msgsRes = await fetch(`${OPENCODE_URL}/session/${session.id}/message`);
        if (!msgsRes.ok) continue;

        const messages: any[] = await msgsRes.json();

        for (const msg of messages) {
          for (const part of msg.parts || []) {
            const partId = part.id || "";
            if (partId && processedParts.has(partId)) continue;
            if (partId) processedParts.add(partId);

            if (part.type === "reasoning" && part.text) {
              await postLog("THOUGHT", part.text, { part_type: "reasoning" });
            } else if (part.type === "text" && (part.content || part.text)) {
              await postLog("THOUGHT", part.content || part.text, { part_type: "text" });
            }
          }
        }
      }
    } catch {}
  }
}

console.log("[bridge] Starting SSE Bridge...");
Promise.all([connectSSE(), pollMessages()]);
