# Step 8 Spec: V1 Release & Degradation

Status: in progress 2026-09-07. Automated degradation checks and a real Codex read-only task have passed; the final macOS/Windows launcher and real microphone permission checks still need manual device validation.

## Goal

Before treating DeskMate as a V1 release candidate, verify that the local service and desktop shell can start, and that missing cloud keys, unavailable Codex, failed LLM calls, missing microphones, or full user data never take down the core text/memory workflow.

## Non-goals

- Do not add cloud deployment or remote synchronization.
- Do not implement every catalog executor adapter in Step 8.
- Do not replace the real microphone with mock audio in production.
- Do not collect or upload API keys, conversation content, task content, or run logs.

## Automated Acceptance

| Area | Expected behavior | Covered by |
| --- | --- | --- |
| Service health | `GET /api/health` returns 200 with text/memory/voice flags and an executor summary, without API keys or file content | `tests/test_health.py` |
| LLM failure degradation | `/api/chat/stream` still emits `error` and `done`; the failed turn is persisted as `（模型调用失败：...）` so chat can continue | `tests/test_chat.py` |
| Voice disabled | `/api/voice/status.enabled=false`; recognize/synthesize return 503 with a supplier reason while text chat remains independent | `tests/test_voice_api.py` |
| Voice provider failure | Provider `SpeechUnavailable` maps to clean 503 and does not expose stack traces | `tests/test_voice_api.py` |
| Codex unavailable | Executor cards show the real status; routed tasks remain listable/queued; execute returns a clear `当前不可执行（not_installed）：...` error | `tests/test_agents_api.py`, `tests/test_agent_runtime.py` |
| Frontend degradation | When the preferred executor is unavailable, the task remains visible and a “执行器不可用” banner is shown instead of silently hiding run controls | Web typecheck and manual UI check |
| Runtime data boundary | `.env`, `data/run`, `settings.local.json`, audio and runtime dirs stay ignored; health/agent status APIs do not echo secret config | `.gitignore`, health tests |

## Privacy Boundary

The repository must not contain:

- `.env` or provider credentials
- `data/settings.local.json`
- transient STT WAV files under `data/run`
- `data/agent_runs`, `data/conversations`, `data/tasks`, `data/run_logs`
- user voice samples under `data/voice_samples`
- local memory/cache files under `data/memory`

If any of these paths is needed for debugging, use a separate local export and do not stage it.

## Manual Release Checklist

Run on macOS before marking Step 8 complete:

1. Start `apps/desktop` with `npm run tauri dev`; confirm launcher finds `.venv`, starts uvicorn on `127.0.0.1:8736`, and health becomes normal.
2. Open the browser UI; grant microphone access when requested.
3. Without a microphone, or after denying access, confirm the UI does not crash and text chat still works.
4. Remove/rename local Codex CLI temporarily and confirm:
   - `/api/agents` shows `codex` as `not_installed`;
   - a routed backend task stays visible and queued;
   - the UI shows the unavailable-executor banner instead of a generic failure.
5. Close the launcher and confirm the child ai-service process exits.
6. Windows is a manual follow-up on a Windows machine; keep the same checklist.

Detailed macOS/Windows permission and source-copy steps are in `docs/CROSS-PLATFORM-TESTING.md`.

## Real Executor Record

- 2026-09-07: Codex provider/model switched from `agnes-2.5-flash` to `deepseek-v4-flash` in `~/.codex/config.toml`.
- DeskMate `read-only` real ACP run completed: task `task_eff6a657ae`, run `run_c560a3ca9c`.
- Codex returned a useful project-doc review despite a non-fatal metadata fallback warning for `deepseek-v4-flash`.

## Verification

```bash
./scripts/check.sh
```

Then open `http://127.0.0.1:8736/` and run the manual items above.
