#!/usr/bin/env python3
"""
Send mission prompt via OpenCode serve API and wait for completion.

Each invocation:
  1. Registers a FRESH game session (clean slate, no prior data)
  2. Updates .session.json + opencode.json with new session ID
  3. Creates OpenCode session via serve API
  4. Sends the mission prompt
  5. Polls until completion

SSE bridge captures THOUGHT logs, MCP server captures ACTION logs.

Usage:
  python3 run-mission.py [prompt]
"""

import sys
import os
import time
import json
import urllib.request
import urllib.error

# Force unbuffered output so prints show up immediately in docker exec
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

OPENCODE_URL = "http://localhost:4096"
SYSTEM_DIR = "/opt/system"
WORKSPACE_DIR = "/workspace"
POLL_INTERVAL = 5
MAX_WAIT = 600

# Files that should survive workspace cleanup
KEEP_FILES = {"MISSION.md", "opencode.json", "agent_records", ".gitkeep"}


def clean_workspace():
    """Remove agent-created files from previous runs."""
    count = 0
    for item in os.listdir(WORKSPACE_DIR):
        if item in KEEP_FILES or item.startswith("."):
            continue
        path = os.path.join(WORKSPACE_DIR, item)
        if os.path.isfile(path):
            os.remove(path)
            count += 1
        elif os.path.isdir(path) and item != "agent_records":
            import shutil
            shutil.rmtree(path)
            count += 1
    if count:
        print(f"[run-mission] Cleaned {count} leftover files from workspace")


def archive_workspace(session_id):
    """Copy agent-created files to /opt/system/agent_workspaces/<session_id>/ (agent can't see)."""
    import shutil
    archive_dir = os.path.join(SYSTEM_DIR, "agent_workspaces", session_id)
    os.makedirs(archive_dir, exist_ok=True)

    count = 0
    for item in os.listdir(WORKSPACE_DIR):
        if item in KEEP_FILES or item.startswith(".") or item in ("agent_workspaces",):
            continue
        src = os.path.join(WORKSPACE_DIR, item)
        dst = os.path.join(archive_dir, item)
        if os.path.isfile(src):
            shutil.copy2(src, dst)
            count += 1
        elif os.path.isdir(src) and item not in ("agent_records", "agent_workspaces"):
            shutil.copytree(src, dst, dirs_exist_ok=True)
            count += 1

    if count:
        print(f"[run-mission] Archived {count} files to agent_workspaces/{session_id}/")


def api(method, path, body=None, base_url=OPENCODE_URL):
    url = f"{base_url}{path}"
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json"} if body else {}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status == 204:
                return None
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode() if e.fp else ""
        print(f"[run-mission] API error {e.code}: {body_text[:200]}", file=sys.stderr)
        return None


def register_fresh_session():
    """Register a new game session and update all config files."""
    # Read current config
    session_file = f"{SYSTEM_DIR}/.session.json"
    with open(session_file) as f:
        config = json.load(f)

    game_api = config["game_api"]
    model_name = config["model_name"]
    experiment = config["experiment"]

    # Register fresh session
    print(f"[run-mission] Registering fresh game session (experiment: {experiment})...")
    result = api("POST", "/api/agent/register", {
        "agent_name": f"opencode-{model_name}",
        "model_name": model_name,
        "execution_mode": "opencode",
    }, base_url=game_api)

    if not result or "session_id" not in result:
        print(f"[run-mission] ERROR: Failed to register session: {result}", file=sys.stderr)
        sys.exit(1)

    new_session_id = result["session_id"]
    print(f"[run-mission] New session: {new_session_id}")

    # Update .session.json
    config["session_id"] = new_session_id
    with open(session_file, "w") as f:
        json.dump(config, f)

    # Update MISSION.md with new session ID (agent uses curl with this header)
    mission_file = f"{WORKSPACE_DIR}/MISSION.md"
    if os.path.exists(mission_file):
        with open(mission_file) as f:
            content = f.read()
        # Replace old session ID with new one
        import re
        content = re.sub(r'X-Session-ID: [a-f0-9]+', f'X-Session-ID: {new_session_id}', content)
        with open(mission_file, "w") as f:
            f.write(content)

    return new_session_id


def main():
    prompt = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else (
        "Read MISSION.md and complete the drone optimization mission. "
        "Use the MCP tools to analyze flight data, deploy drones with different designs, "
        "and submit your final optimized design."
    )

    # 0. Clean workspace (remove agent-created files from previous runs)
    clean_workspace()

    # 1. Register fresh game session
    new_session_id = register_fresh_session()

    # 2. Check serve is up
    print("[run-mission] Connecting to OpenCode serve...")
    for i in range(30):
        try:
            urllib.request.urlopen(f"{OPENCODE_URL}/session", timeout=5)
            break
        except Exception:
            if i == 29:
                print("[run-mission] ERROR: Cannot connect to OpenCode serve", file=sys.stderr)
                sys.exit(1)
            time.sleep(2)

    # 3. Create OpenCode session
    print("[run-mission] Creating OpenCode session...")
    session = api("POST", "/session", {})
    if not session or "id" not in session:
        print(f"[run-mission] ERROR: Failed to create session: {session}", file=sys.stderr)
        sys.exit(1)

    oc_session_id = session["id"]
    print(f"[run-mission] OpenCode session: {oc_session_id}")
    print(f"[run-mission] Game session: {new_session_id}")

    # 4. Send prompt (async)
    print(f"[run-mission] Sending prompt ({len(prompt)} chars)...")
    api("POST", f"/session/{oc_session_id}/prompt_async", {
        "parts": [{"type": "text", "text": prompt}]
    })
    print("[run-mission] Mission started. Use --watch in another terminal to follow progress.")

    # 5. Poll until idle
    elapsed = 0
    last_status = ""
    while elapsed < MAX_WAIT:
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

        status_resp = api("GET", "/session/status")
        if status_resp is None:
            continue

        # When session is active: {"ses_xxx": {"type": "busy"}}
        # When session is done: {} (session removed from active list)
        if oc_session_id not in status_resp:
            # Session no longer in active list = completed
            if last_status == "busy":
                print(f"[run-mission] Status: completed ({elapsed}s elapsed)")
            break

        session_info = status_resp[oc_session_id]
        current_status = session_info.get("type", "unknown") if isinstance(session_info, dict) else str(session_info)

        if current_status != last_status:
            print(f"[run-mission] Status: {current_status} ({elapsed}s elapsed)")
            last_status = current_status

        if current_status in ("idle", "error"):
            break

    if elapsed >= MAX_WAIT:
        print("[run-mission] WARNING: Timed out", file=sys.stderr)

    # 6. Archive workspace files to agent_workspaces/<session_id>/
    archive_workspace(new_session_id)

    # 7. Print summary
    print(f"\n[run-mission] Complete. Game session: {new_session_id}")

    # Check game results
    session_file = f"{WORKSPACE_DIR}/agent_records/sessions/{new_session_id}.json"
    try:
        with open(session_file) as f:
            data = json.load(f)
        from collections import Counter
        logs = data.get("logs", [])
        types = Counter(l.get("type") for l in logs)
        print(f"  Deployments: {data.get('deployments_used')}")
        print(f"  Flights:     {len(data.get('flight_history', []))}")
        print(f"  Logs:        {len(logs)} ({', '.join(f'{t}:{c}' for t,c in sorted(types.items()))})")
        if data.get("final_result"):
            fr = data["final_result"]
            print(f"  Survival:    {fr.get('survival_rate')}")
            print(f"  Victory:     {fr.get('victory')}")
    except Exception:
        print("  (session file not found or not readable)")


if __name__ == "__main__":
    main()
