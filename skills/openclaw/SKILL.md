# SKILL.md — Crucible × OpenClaw Integration

**Purpose:** Invoke Crucible from within OpenClaw to run validated, multi-step software builds via sub-agents.

**Surface:** `crucible` command exposed to the LLM as a tool.

## Mental model: build vs verify

Crucible separates two responsibilities:

- **Build** is whatever produces the artifacts (a coding agent like Codex / Claude Code, or an OpenClaw sub-agent running such an agent). This is out of Crucible's scope as a verifier — Crucible just trusts the artifacts exist on disk.
- **Verify** is Crucible's job. For every criterion in the plan, Crucible executes the `verification_command` against the produced artifacts via a real shell and checks `expected_output` against the command's stdout. If the command fails or the output doesn't match, the criterion (and the task) FAIL.

In the standalone CLI, the default backend is `LocalShellAdapter` — it ONLY runs verification commands locally. It does NOT build anything. The expectation is that the build has already happened (or will happen alongside verification via a real build agent driven through the OpenClaw bridge).

To wire a real build path, embedders use `crucible.runtime.openclaw_bridge.SessionsSpawnBridge` to attach OpenClaw sub-agents as a backend. The OpenClaw wrapper (`src/crucible/runtime/openclaw_tool.py`) can drive this path directly when the embedder supplies bridge callables (`openclaw_spawn_callable` + `openclaw_wait_callable`) or an `adapter_factory`; otherwise it falls back to the CLI's local verification-only path. See `src/crucible/runtime/openclaw_bridge.py` for the contract.

---

## When to Use This Skill

Use Crucible when:
- The user wants a **large, multi-step implementation** (not just "fix this bug" or "write one file")
- The task involves **test-driven validation** with explicit pass/fail criteria
- You need **durability** — the run survives gateway restarts, produces audit artifacts, and can be resumed

Do NOT use Crucible for:
- Simple one-off edits (just use Codex/Claude Code directly)
- Q&A or research tasks
- Single-file changes with obvious solutions

---

## Prerequisites

1. **Crucible installed:** `pip install -e crucible` (or `uv pip install -e crucible`)
2. **OpenClaw has the tool:** `crucible` tool should be registered in your OpenClaw config
3. **Optional:** Set `CRUCIBLE_RUNS_DIR` env var to a persistent path (default: `./runs` in cwd)

---

## Tool Interface

### `crucible`

**Input (JSON):**
```json
{
  "plan": {
    "spec": "...",
    "project_id": "...",
    "build_id": "...",
    "tasks": [
      {
        "task_id": "...",
        "description": "...",
        "criteria": [
          {
            "criterion_id": "...",
            "criterion_class": "must_pass|informational",
            "triple": {
              "build_target": "...",
              "verification_command": "...",
              "expected_output": "..."
            }
          }
        ],
        "role": "builder|reviewer|debugger|researcher|integrator|salvage",
        "intensity_hint": "S|M|L"
      }
    ]
  },
  "mode": "run|lint|status|watch|resume",
  "run_id": "optional, for status/watch/resume",
  "detach": false,
  "embedding_surface": "openclaw",
  "embedding_session_ref": "current-session-id"
}
```

**Output (JSON):**
```json
{
  "status": "ok|error|lint_failed|running|terminal",
  "exit_code": 0,
  "run_id": "run-...",
  "run_root": "/path/to/runs/run-...",
  "terminal_status": "complete|failed|blocked|partial",
  "message": "..."
}
```

---

## Workflows

### 1. Start a New Run

```
User: Build a complete authentication system with tests, DB migrations, and API endpoints.
```

1. **Draft a plan** (use the templates below)
2. **Call `crucible` with `mode: "run"`**
3. **Interpret the response:**
   - `exit_code == 0` → run started, monitor with `watch`
   - `exit_code == 2` → lint failed, fix the plan
   - `exit_code == 1` → usage error (bad plan format)
   - `exit_code == 5` → internal error

### 2. Monitor a Running Run

```
crucible({ mode: "watch", run_id: "run-..." })
```

Returns incremental events. Watch for:
- `task_dispatched` → sub-agent spawned
- `task_completed` → all criteria passed
- `task_failed` → criteria failed
- `run_terminal` → final state

### 3. Resume After Interruption

If the gateway restarts or the user returns later:

```
crucible({ mode: "resume", run_id: "run-..." })
```

This reconciles any in-flight attempts and continues execution.

---

## Plan Templates

### Template 1: Build Feature

```json
{
  "spec": "Implement user authentication with JWT, bcrypt password hashing, and session management.",
  "project_id": "auth-system",
  "build_id": "feature/jwt-auth",
  "tasks": [
    {
      "task_id": "implement-auth-service",
      "description": "Implement src/auth/service.py with JWT issue/verify and password hashing using bcrypt",
      "criteria": [
        {
          "criterion_id": "c1",
          "criterion_class": "must_pass",
          "triple": {
            "build_target": "src/auth/service.py",
            "verification_command": "python -c 'from src.auth.service import AuthService; s=AuthService(); token=s.issue(\"user\"); print(\"OK\" if s.verify(token) else \"FAIL\")'",
            "expected_output": "OK"
          }
        }
      ],
      "role": "builder",
      "intensity_hint": "M"
    },
    {
      "task_id": "write-auth-tests",
      "description": "Write tests/tests/test_auth_service.py covering issue, verify, password hashing, and expiry",
      "criteria": [
        {
          "criterion_id": "c1",
          "criterion_class": "must_pass",
          "triple": {
            "build_target": "tests/test_auth_service.py",
            "verification_command": "pytest tests/test_auth_service.py -v",
            "expected_output": "PASSED"
          }
        }
      ],
      "role": "builder",
      "intensity_hint": "S"
    },
    {
      "task_id": "integrate-auth",
      "description": "Integrate auth service into src/api/main.py with /login and /me endpoints",
      "criteria": [
        {
          "criterion_id": "c1",
          "criterion_class": "must_pass",
          "triple": {
            "build_target": "src/api/main.py",
            "verification_command": "python -c 'from src.api.main import app; print(\"OK\")'",
            "expected_output": "OK"
          }
        }
      ],
      "role": "integrator",
      "intensity_hint": "S"
    }
  ]
}
```

### Template 2: Fix Bug

```json
{
  "spec": "Fix the race condition in the cache invalidation logic.",
  "project_id": "cache-lib",
  "build_id": "fix/race-condition",
  "tasks": [
    {
      "task_id": "reproduce-bug",
      "description": "Write tests/tests/test_cache_race.py that reproduces the race condition with concurrent invalidate calls",
      "criteria": [
        {
          "criterion_id": "c1",
          "criterion_class": "must_pass",
          "triple": {
            "build_target": "tests/test_cache_race.py",
            "verification_command": "pytest tests/test_cache_race.py -v",
            "expected_output": "FAILED"
          }
        }
      ],
      "role": "debugger",
      "intensity_hint": "S"
    },
    {
      "task_id": "fix-race-condition",
      "description": "Fix src/cache/invalidator.py by adding locking around the invalidate method",
      "criteria": [
        {
          "criterion_id": "c1",
          "criterion_class": "must_pass",
          "triple": {
            "build_target": "src/cache/invalidator.py",
            "verification_command": "pytest tests/test_cache_race.py -v",
            "expected_output": "PASSED"
          }
        }
      ],
      "role": "builder",
      "intensity_hint": "M"
    }
  ]
}
```

### Template 3: Refactor

```json
{
  "spec": "Refactor the legacy DataManager class into smaller, testable components.",
  "project_id": "data-pipeline",
  "build_id": "refactor/datamanager",
  "tasks": [
    {
      "task_id": "extract-validator",
      "description": "Extract validation logic from src/data/manager.py into src/data/validator.py with existing tests passing",
      "criteria": [
        {
          "criterion_id": "c1",
          "criterion_class": "must_pass",
          "triple": {
            "build_target": "src/data/validator.py",
            "verification_command": "pytest tests/test_data_validator.py -v",
            "expected_output": "PASSED"
          }
        }
      ],
      "role": "builder",
      "intensity_hint": "M"
    },
    {
      "task_id": "refactor-manager",
      "description": "Refactor src/data/manager.py to use the new validator module, preserving all existing behavior",
      "criteria": [
        {
          "criterion_id": "c1",
          "criterion_class": "must_pass",
          "triple": {
            "build_target": "src/data/manager.py",
            "verification_command": "pytest tests/ -v --ignore=tests/test_data_validator.py",
            "expected_output": "PASSED"
          }
        }
      ],
      "role": "builder",
      "intensity_hint": "L"
    }
  ]
}
```

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success (run completed, or valid lint) |
| 1 | Usage error (bad arguments) |
| 2 | Lint failure (invalid plan) |
| 3 | Run blocked / failed / partial |
| 4 | Unknown run_id |
| 5 | Internal error |

---

## Troubleshooting

**"plan failed preflight validation"**
- Your plan has vague descriptions or generic triples
- Edit the plan to use specific file paths, measurable conditions

**"unknown run_id"**
- The run directory was deleted or never created
- Check `CRUCIBLE_RUNS_DIR` points to the right location

**Run hangs**
- Use `crucible({ mode: "watch", run_id: "..." })` to see what's happening
- If a sub-agent is stuck, the orchestrator will eventually mark it as `timed_out`

**Gateway restarts mid-run**
- Crucible state is persisted on disk — use `crucible({ mode: "resume", run_id: "..." })` to continue