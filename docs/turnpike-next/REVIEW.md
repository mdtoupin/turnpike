# Fable review of the Turnpike Next plan (2026-08-12)

Reviewer: claude (Fable), at the owner's request. Method: read the full estate (PLAN.md,
five audits, UX-IA.md), then verify every load-bearing technical claim against what is
actually installed on this machine and against the live npm registry, rather than trusting
the audit text. Result: the plan is sound and unusually well-grounded; I made four targeted
amendments (marked [F1]..[F4] in PLAN.md) and verified most of gate #112 early.

## Verification results

Every checked claim from the audits was CONFIRMED against the real artifacts:

| Claim (from audits) | Check performed | Result |
|---|---|---|
| Claude Code CLI 2.1.220 installed | `claude --version` | Confirmed, exactly 2.1.220 |
| Codex CLI 0.145.0 installed | `codex --version` | Confirmed, exactly 0.145.0 |
| `claude agents --json --all` agent view CLI | `claude agents --help` | Confirmed, incl. `--json`, `--all`, dispatch options |
| `codex app-server` exists, experimental | `codex app-server --help` | Confirmed, labeled experimental |
| Bindings can be generated per pinned version | same | Confirmed: `generate-ts` and `generate-json-schema` subcommands exist |
| Agent SDK current version 0.3.228 | `npm view` | Confirmed |
| SDK API surface: forkSession, rewindFiles, listSubagents, getSubagentMessages, getSessionMessages, listSessions, getSessionInfo, getContextUsage, renameSession, tagSession, spawnClaudeCodeProcess, enableFileCheckpointing, forwardSubagentText, includeHookEvents, allowDangerouslySkipPermissions, stopTask, backgroundTasks, setPermissionMode, setModel, interrupt, PreCompact/PostCompact | `npm pack` 0.3.228, grep of shipped `.d.ts` | ALL present |
| Signature shapes | read `.d.ts` | Confirmed: `forkSession(sessionId, {upToMessageId})`, `Query.rewindFiles(userMessageId, {dryRun})`, `spawnClaudeCodeProcess({command, args, cwd, env, signal})` match the audit exactly |
| Node available for the TS bridge | `node --version` | v24.14.0 installed |

Codex's audits were accurate on every point I could test locally. This materially raises
confidence in the parts I could not test from here (app-server protocol behavior at
runtime, which remains in gate #112).

## Amendments made

**[F1] Added Phase 0: stopgap session restore (the biggest change).**
The original pain was "my PC restarts and I lose eight sessions". The grand plan defers
actual restore relief behind the Rust core, terminals, and adapters (phases 2-4). But
codex's very first recommendation in the planning session, before the scope grew, was a
small CLI: `turnpike session-bind / sessions / restore` that records provider thread IDs
per task and reopens Windows Terminal tabs running `codex resume <id>` / `claude --resume`.
That fits the existing Python CLI and SQLite schema (one new table), needs no Core, and
solves the reboot pain within days, not months. It also produces real-world resume data
that will inform the adapter design. The full app then replaces it; the schema is designed
so Phase 2 imports these bindings as first-class sessions.

**[F2] Named the Node runtime dependency honestly.**
The Claude adapter is a TypeScript SDK bridge, which means Node is a runtime dependency of
Core (the plan's "Node is not part of the running UI" is true but incomplete). v1 uses the
system Node with an engine check at Core startup (>=18 required; v24.14.0 present); pin the
SDK version exactly. A Rust-native adapter speaking the CLI's bidirectional stream-json
wire protocol directly could remove the Node dependency later; that is recorded as an
optional post-v1 optimization, not attempted in v1, because the typed SDK surface is
documented, verified, and moving fast.

**[F3] Compat CLI must fail open to direct SQLite.**
The plan routes `turnpike.py` through Core once Core exists. Amendment: if Core is
unreachable (crashed, not yet started, mid-upgrade), the compat CLI falls back to direct
database access in the legacy code path with a stderr warning, rather than erroring. The
bus is the coordination lifeline for every agent on this machine; Core must never become a
single point of failure for posting a message or claiming a task. Core's single-writer
ownership is the steady state, not a hard gate.

**[F4] Re-scoped verification gate #112.**
The Claude half of the gate is substantially closed by this review at the API-surface level
(names and signatures verified against the shipped 0.3.228 typings). What remains before
Phase 4 design freeze: behavioral contract tests (streaming, interrupt semantics, subagent
forwarding, checkpoint dispatch under kill) for Claude, and generated-bindings plus a live
protocol smoke test for the codex app-server on the pinned CLI version.

## Reviewed and deliberately unchanged

- Rust Core + named-pipe RPC + Tauri Deck evolution: right shape for the machine and the
  existing estate; no Electron.
- Job Object governor and adaptive pressure policy: the underlying Win32 research is
  correct, including the sharp edges (weight-based CPU over hard caps, no I/O rate control,
  suspend is not a safe pause, KILL_ON_JOB_CLOSE off).
- Checkpoint/module data model, recovery state machine, and never-blind-replay rule.
- The UX-IA spec, including hotkeys, module registry, and restore states.
- CodeWhale bounded gate; migration strategy with golden tests; performance acceptance
  numbers (ambitious but achievable with virtualization and a native core).
- SolidJS choice: acceptable; noted as a Phase 5 implementation detail that must not block
  earlier phases, not an architectural commitment.

## Residual risks (accepted, with mitigations already in the plan)

1. The codex app-server is explicitly experimental and may churn between CLI versions.
   Mitigation: pinned versions, generated bindings, capability gating, native-TUI fallback.
2. Scope: this is a real product build. Mitigation: Phase 0 delivers the original ask
   immediately; each phase has its own acceptance gates; phases map to bus tasks.
3. Unattended Full Access agents resuming at login is powerful by design. The reconciliation
   turn and the startup digest ("7 restored, 1 needs attention") are the guardrails the
   owner chose; nothing further added.
