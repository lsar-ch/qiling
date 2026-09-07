# Step 7 Phase 2 Spec: Real Executor Runs

Status: implemented 2026-09-07; codex-acp real execution wired and covered by fake-adapter runtime tests.

## Goal

Turn a routed `delegate_backend` task into a real external executor run. Codex is the first real adapter; all other catalog entries remain pending until their adapter is implemented.

## Non-goals

- Do not implement real adapters for every catalog entry in this step.
- Do not build a cloud task platform.
- Do not hard-code Codex-specific concepts in the frontend.
- Do not remove the existing manual task-status controls; add real run controls beside them.

## Backend model

Introduce an internal `AgentRun` persisted under `data/agent_runs/{run_id}.json`:

```json
{
  "run_id": "run_...",
  "task_id": "task_...",
  "executor": "codex",
  "status": "queued|running|awaiting_approval|completed|failed|cancelled",
  "session_id": null,
  "mode": "read-only|agent|agent-full-access",
  "progress": "short progress text",
  "result": null,
  "error": null,
  "created_at": "...",
  "updated_at": "...",
  "finished_at": null
}
```

Keep `AgentRun` as a Python model in `services/ai-service/app/agents/runtime.py`, with a TS API mirror only in `apps/web/src/api.ts` (do not force it into the shared contracts package yet).

## Backend API

- `POST /api/tasks/{task_id}/execute`
  - Body: `{"executor": "codex" | null, "mode": "read-only" | "agent" | "agent-full-access" | null}`.
  - Only allowed for tasks whose `preferred_executor` is null/executor/default and whose category is `delegate_backend` or `request_approval` after user approval.
  - Creates run, marks task running, starts background execution, returns `{"task": ..., "run": ...}`.
- `GET /api/tasks/{task_id}/run`
  - Returns latest `{"run": ...}` for the task, or 404.
- `GET /api/agent-runs?limit=50`
  - Returns `{"items": [...]}` newest first.
- `POST /api/agent-runs/{run_id}/cancel`
  - Cancels ACP session/process, marks run and task cancelled, publishes `task.cancelled`.
- `POST /api/agent-runs/{run_id}/approval`
  - Body: `{"decision": "approved" | "rejected"}`.
  - Resolves a pending ACP permission request. Approved maps to `allow_once` when available; rejected maps to `reject_once`.
  - Publishing `task.approval_required` while waiting is required.

Keep existing `POST /api/tasks/{task_id}/approval` behavior intact for compatibility with the current manual task board.

## ACP client

Implement a minimal line-delimited JSON-RPC 2.0 ACP stdio client in `services/ai-service/app/agents/acp.py`.

- Spawn `codex-acp`.
- Send `initialize`, `session/new`, `session/prompt`, `session/cancel` notifications, `session/close`.
- Send `session/new` with `{"cwd": "...", "mcpServers": []}`.
- Send `session/prompt` with `{"sessionId": "...", "prompt": [{"type": "text", "text": "..."}]}`.
- Handle notifications `session/update`, agent requests `session/request_permission`, and JSON-RPC responses.
- Kill the process if cancel/close hangs.
- Support env `CODEX_PATH`, `NO_BROWSER=1`, `INITIAL_AGENT_MODE`, `APP_SERVER_LOGS`.

Local probe already confirmed `codex-acp` handshake and `session/new` works with `CODEX_PATH=/Users/lxb/.local/bin/codex`.

## Codex adapter changes

Codex adapter should:

- Detect `codex` and `codex-acp`.
- Return `pending`, not `ready`, when `codex-acp` is missing.
- Accept catalog `config` fields instead of hardcoding every command. Add a generic `config` mapping to `AgentCatalogEntry` if needed.
- Implement real `connect/run/cancel/approve` behind the existing `AgentAdapter` abstraction.
- Default mode is `read-only` unless the caller asks for `agent` or `agent-full-access`.
- Never execute pending adapters.

## Event changes

Add `task.cancelled` to:

- `packages/contracts/py/deskmate_contracts/events.py`
- `packages/contracts/ts/src/events.ts`
- Frontend event mapping/state mapping

Do not make this change in more than one place.

## Tests

Backend worker adds tests that do not depend on the real `codex-acp` binary:

- Fake adapter run completes and updates task/run.
- Fake adapter failure marks failed and emits event.
- Duplicate execute on running task is rejected.
- Cancel path sets cancelled.
- Approval route resolves a pending permission.
- Pending executor execute is rejected.
- Event contract sync still passes.

If a fake ACP binary is easy to create in tmp path, prefer that over mocking the whole process layer.

## Frontend changes

The frontend worker should use the API above and:

- Show run state/progress on recent tasks.
- Add an "运行" action for executable backend tasks.
- Add "取消" while running.
- Add "批准/拒绝" for run-level approval when a run is awaiting approval.
- Keep existing four manual status actions for debugging.
- Fetch and auto-refresh run state while a run is active.
- Do not visually break when many executor cards are displayed or later added through `config/agents.yaml`.

## Docs changes

The docs worker updates `docs/AGENT-INTEGRATION.md`, `docs/EXECUTOR-CATALOG.md`, `docs/PROJECT-ROADMAP.md`, `docs/V1-IMPLEMENTATION-PLAN.md`, and `AGENTS.md` to describe Phase 2 progress after implementation. Do not claim every adapter is executable.
