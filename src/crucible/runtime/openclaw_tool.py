"""OpenClaw tool wrapper for Crucible.

This module exposes `crucible` as an OpenClaw tool, allowing the LLM
to invoke validated multi-step software builds.

Usage in OpenClaw config:

```yaml
tools:
  - name: crucible
    type: function
    description: "Run validated multi-step software builds with Crucible"
    input_schema:
      type: object
      properties:
        plan:
          type: object
          description: "Crucible task plan (see SKILL.md for schema)"
        mode:
          type: string
          enum: [run, lint, status, watch, resume]
          default: run
        run_id:
          type: string
          description: "Run ID for status/watch/resume modes"
        detach:
          type: boolean
          default: false
        embedding_surface:
          type: string
          default: openclaw
        embedding_session_ref:
          type: string
          description: "Current OpenClaw session key"
      required: [mode]
    module: crucible.runtime.openclaw_tool
```

Environment:
- `CRUCIBLE_RUNS_DIR`: override default runs/ directory
- `CRUCIBLE_CLI_PATH`: path to crucible CLI (default: search PATH)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any


TOOL_NAME = "crucible"
TOOL_VERSION = "0.1.0"


def _run_cli(args: list[str], timeout: int = 300) -> dict[str, Any]:
    """Invoke the crucible CLI and return parsed JSON result."""
    cli_path = os.environ.get("CRUCIBLE_CLI_PATH", "crucible")
    
    env = os.environ.copy()
    # Pass through vault credentials if needed
    if "GMAIL_APP_PASSWORD" in env:
        del env["GMAIL_APP_PASSWORD"]  # Don't leak to subprocess
    
    try:
        result = subprocess.run(
            [cli_path] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except FileNotFoundError:
        return {
            "status": "error",
            "exit_code": 5,
            "message": f"crucible CLI not found at '{cli_path}'. Install: pip install -e crucible",
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "exit_code": 5,
            "message": f"crucible CLI timed out after {timeout}s",
        }
    
    # Parse JSONL output (first line is event)
    lines = result.stdout.strip().split("\n") if result.stdout else []
    output: dict[str, Any] = {}
    
    for line in lines:
        if not line:
            continue
        try:
            obj = json.loads(line)
            if obj.get("event") in {"run_started", "run_pending_orchestrator"}:
                output["run_id"] = obj.get("run_id", "")
                output["run_root"] = obj.get("run_root", "")
                output["status"] = "running"
            elif obj.get("event") == "lint_failed":
                output["status"] = "lint_failed"
                output["findings"] = obj.get("result", {}).get("findings", [])
            elif obj.get("event") in {"resumed", "detached"}:
                output["run_id"] = obj.get("run_id", "")
                output["status"] = "running"
            elif "event_id" in obj:
                # Event stream line — skip in structured output
                continue
            else:
                # Fallback: treat as raw output
                output["raw"] = line
        except json.JSONDecodeError:
            output["raw"] = line
    
    # If no structured output found, use exit code
    if not output:
        output["stdout"] = result.stdout
        output["stderr"] = result.stderr
    
    output["exit_code"] = result.returncode
    
    # Map exit code to status
    if result.returncode == 0:
        output.setdefault("status", "ok")
    elif result.returncode == 1:
        output["status"] = "error"
        output.setdefault("message", "usage error")
    elif result.returncode == 2:
        output.setdefault("status", "lint_failed")
    elif result.returncode == 3:
        output["status"] = "terminal"
        output["terminal_status"] = "failed"
    elif result.returncode == 4:
        output["status"] = "error"
        output["message"] = "unknown run_id"
    
    return output


def execute(input_json: dict[str, Any]) -> dict[str, Any]:
    """Execute the crucible tool.
    
    Expected input:
    {
        plan: {...},
        mode: "run|lint|status|watch|resume",
        run_id: "...",
        detach: false,
        embedding_surface: "openclaw",
        embedding_session_ref: "..."
    }
    """
    mode = input_json.get("mode", "run")
    runs_dir = os.environ.get("CRUCIBLE_RUNS_DIR")
    
    # Build CLI args
    args = []
    if runs_dir:
        args.extend(["--runs-dir", runs_dir])
    
    if mode == "lint":
        # plan required
        plan = input_json.get("plan")
        if not plan:
            return {"status": "error", "exit_code": 1, "message": "plan required for lint mode"}
        
        # Write plan to temp file
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(plan, f)
            plan_path = f.name
        args.extend(["lint-plan", plan_path])
        try:
            result = _run_cli(args)
        finally:
            os.unlink(plan_path)
        return result
    
    elif mode == "run":
        plan = input_json.get("plan")
        if not plan:
            return {"status": "error", "exit_code": 1, "message": "plan required for run mode"}
        
        # Write plan to temp file
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(plan, f)
            plan_path = f.name
        args.extend(["run", plan_path])
        
        if input_json.get("detach"):
            args.append("--detach")
        if input_json.get("embedding_surface"):
            args.extend(["--embedding", input_json["embedding_surface"]])
        
        try:
            result = _run_cli(args)
        finally:
            os.unlink(plan_path)
        return result
    
    elif mode == "status":
        run_id = input_json.get("run_id")
        if not run_id:
            return {"status": "error", "exit_code": 1, "message": "run_id required for status mode"}
        args.extend(["status", run_id])
        return _run_cli(args)
    
    elif mode == "watch":
        run_id = input_json.get("run_id")
        if not run_id:
            return {"status": "error", "exit_code": 1, "message": "run_id required for watch mode"}
        args.extend(["watch", run_id, "--jsonl", "--from", "0"])
        
        # Watch returns streaming events — return as collected
        cli_path = os.environ.get("CRUCIBLE_CLI_PATH", "crucible")
        env = os.environ.copy()
        if "GMAIL_APP_PASSWORD" in env:
            del env["GMAIL_APP_PASSWORD"]
        
        try:
            proc = subprocess.Popen(
                [cli_path] + args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            events = []
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
            proc.wait(timeout=30)
            
            return {
                "status": "ok",
                "exit_code": proc.returncode,
                "events": events,
                "run_id": run_id,
            }
        except subprocess.TimeoutExpired:
            proc.kill()
            return {"status": "error", "exit_code": 5, "message": "watch timed out"}
    
    elif mode == "resume":
        run_id = input_json.get("run_id")
        if not run_id:
            return {"status": "error", "exit_code": 1, "message": "run_id required for resume mode"}
        args.extend(["resume", run_id])
        return _run_cli(args)
    
    else:
        return {"status": "error", "exit_code": 1, f"unknown mode: {mode}"}


# OpenClaw tool contract
TOOL_SCHEMA = {
    "name": TOOL_NAME,
    "description": "Run validated multi-step software builds with Crucible",
    "input_schema": {
        "type": "object",
        "properties": {
            "plan": {
                "type": "object",
                "description": "Crucible task plan (see SKILL.md for schema)",
            },
            "mode": {
                "type": "string",
                "enum": ["run", "lint", "status", "watch", "resume"],
                "default": "run",
            },
            "run_id": {
                "type": "string",
                "description": "Run ID for status/watch/resume modes",
            },
            "detach": {
                "type": "boolean",
                "default": False,
            },
            "embedding_surface": {
                "type": "string",
                "default": "openclaw",
            },
            "embedding_session_ref": {
                "type": "string",
                "description": "Current OpenClaw session key",
            },
        },
        "required": ["mode"],
    },
}