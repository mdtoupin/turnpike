# Turnpike Next: Persistent Agent Workspace (planning estate)

This folder is the durable home of the "Turnpike Next" plan: turning Turnpike from a
monitor-plus-summon prototype into a lightweight Windows control center for coding-agent
sessions, with Slack-style project rooms, prompt checkpoints, explorable subagent threads,
real PowerShell terminals, reboot recovery, and an adaptive resource governor.

## Provenance

The plan was authored by codex in an interactive planning session with the owner on
2026-08-11/12 and delivered at 2026-08-12T02:38Z. Until this commit it existed only inside
codex's session logs; claude recovered it on 2026-08-12 (turnpike task #105). Sources, all
under `~/.codex/sessions/2026/08/11/`:

| Doc | Source session | What it is |
|---|---|---|
| [PLAN.md](PLAN.md) | `rollout-...T16-29-45-019ff2f2` | The final proposed plan (verbatim) |
| [AUDIT-ARCHITECTURE.md](AUDIT-ARCHITECTURE.md) | `rollout-...T16-47-17-019ff302` | Current-state Turnpike audit + evolutionary architecture |
| [AUDIT-CODEX-RUNTIME.md](AUDIT-CODEX-RUNTIME.md) | `rollout-...T16-47-21-019ff302` | Codex app-server integration boundary |
| [AUDIT-RESOURCE-GOVERNOR.md](AUDIT-RESOURCE-GOVERNOR.md) | `rollout-...T16-47-26-019ff302` | Windows Job Objects / ConPTY / telemetry research |
| [AUDIT-CLAUDE-RUNTIME.md](AUDIT-CLAUDE-RUNTIME.md) | `rollout-...T20-17-33-019ff3c2` | Claude Agent SDK integration boundary |
| [UX-IA.md](UX-IA.md) | `rollout-...T20-17-40-019ff3c2` | Full interaction-architecture handoff (layout, modules, hotkeys, recovery UX) |

The owner's original ask, condensed: eight or more active agent projects should survive a PC
restart without hunting for windows; the program must be incredibly efficient, keep full
PowerShell freedom, give agents as much CPU/RAM as they need without bombing the system
(with meters), present each project as a Slack-style room where agent work folds into
compact modules rather than info dumps, make every user prompt a navigable checkpoint, and
feel "liquid smooth".

## Decisions locked during the planning session

These were answered by the owner mid-session and are baked into PLAN.md:

- Codex and Claude are first-class providers. CodeWhale gets one bounded adapter attempt
  against the same contract suite, otherwise it ships as a managed terminal.
- Auto-resume restores all previously running work at login, throttled by the elastic
  scheduler so login does not spike eight agents at once.
- Recovery never blindly replays an in-flight prompt (side effects may already have
  happened). A reconciliation turn inspects provider history, git/worktree state, and the
  Turnpike checkpoint before continuing.
- Full Access is the default permission mode, with a persistent, unambiguous badge.
- The conversation model is a chronological project spine of checkpoints with nested
  steer/subagent/fork branches (true branchable history, not a flat list).
- Legacy bus history is converted into imported checkpoints; original records are never
  deleted.
- Evolve the existing 5.4 MB Tauri Deck with a native Rust core underneath; no Electron.

## Status (2026-08-12)

- Plan v1.1: reviewed and amended by claude (Fable) at the owner's request, see
  [REVIEW.md](REVIEW.md). Amendments [F1] Phase 0 stopgap restore CLI, [F2] Node runtime
  dependency named and pinned, [F3] compat CLI fails open to direct SQLite, [F4] provider
  API claims verified locally (all confirmed). PROPOSED to the owner, awaiting approval.
- No code changes exist anywhere for this program; this docs folder is the first commit.
- The canonical `Desktop\turnpike` checkout is parked on a dirty deepseek branch
  (`agent/deepseek/task-11-asset-pipeline`); per protocol, all Turnpike Next work happens in
  per-agent worktrees cut from `master`.
- Bus project: `turnpike-next` (created 2026-08-12 by claude, with phase tasks mirroring
  PLAN.md's implementation sequence).

## Known verification gaps (do before Phase 4 design freeze)

Both provider audits cite version-specific, partly experimental surfaces that must be
re-verified against pinned versions at build time, not trusted from the audit text:

- Codex app-server: audited against CLI 0.145.0 (updater offered 0.147.0). The app-server
  is explicitly experimental; regenerate protocol bindings per pinned version and
  capability-gate everything optional.
- Claude Agent SDK: audited against system CLI 2.1.220 / SDK 0.3.228. The named APIs
  (forkSession, rewindFiles, listSubagents, getSessionMessages, spawnClaudeCodeProcess,
  agent-view CLI, etc.) need a contract test against the exact pinned SDK version before the
  adapter design is frozen; the SDK moves fast and some surfaces are new or experimental.
- Distribution constraint from the Claude audit: a distributable Turnpike must not offer
  claude.ai subscription login without Anthropic approval; personal local use with the
  owner's existing auth is fine.
