<!-- Provenance: final proposed plan authored by codex, delivered 2026-08-12T02:38Z
     in a Codex session (verbatim, tags stripped).
     Recovered and committed by claude 2026-08-12.
     v1.1: amended by claude (Fable) 2026-08-12 after review; amendments are marked [F1]..[F4]
     with rationale in REVIEW.md. The unamended codex original is preserved at commit 82d0f40. -->

# Turnpike Next: Persistent Agent Workspace

## Summary

Evolve the existing 5.4 MB Tauri Deck into a lightweight, local Windows control center for Codex, Claude, and—when practical—CodeWhale. Turnpike will replace scattered terminal windows with Slack-style project rooms, structured prompt checkpoints, explorable subagent conversations, real PowerShell terminals, reboot recovery, and adaptive resource protection.

Success means:

- Eight or more projects restore automatically after login.
- Every user prompt becomes an immutable, branchable checkpoint.
- Agent activity appears as compact modules—not transcript dumps.
- Root agents, subagents, forks, tools, tests, diffs, and context compactions remain individually explorable.
- Full-access execution remains the visible default.
- Agents may burst into unused CPU/RAM, while an elastic scheduler protects desktop responsiveness.
- The Turnpike UI remains under 200 MB private memory, below 0.5% idle CPU, and switches warm conversations within 100 ms p95.
- No Electron or OpenAI desktop-app dependency; local Windows only.

```text
Turnpike Core
├─ Project rooms
│  ├─ Root Codex/Claude/CodeWhale sessions
│  │  ├─ Prompt checkpoints
│  │  ├─ Modules
│  │  └─ Subagent/fork trees
│  └─ Tasks, summaries, coordination bus, Git/worktrees
├─ Provider adapters
├─ ConPTY PowerShell terminals
├─ Job Objects and resource governor
└─ SQLite event/read model
        ↑
    named-pipe RPC
        ↓
Turnpike Deck + compatible turnpike CLI
```

## Architecture and Public Interfaces

### Native core and UI

- Retain Tauri/WebView2, replacing the Python HTTP monitor with a persistent Rust `TurnpikeCore.exe`.
- Build the UI in TypeScript with SolidJS, list virtualization, and xterm.js. Bundle static assets; Node is not part of the running UI.
- Core exclusively owns SQLite, processes, provider streams, terminals, resource policy, recovery, and notifications.
- Deck connects through a versioned, length-prefixed JSON-RPC named pipe secured to the current Windows user SID. Remove state-changing loopback HTTP from the final path.
- Closing the window hides it to the tray. Core, sessions, resource controls, and notifications continue running.
- Register Core for per-user startup. At login it restores cached UI state immediately, then rehydrates runtimes through the elastic queue.
- Do not use `KILL_ON_JOB_CLOSE`; a Core crash must not silently kill tools. Surviving processes that cannot be reattached become clearly labeled `Orphaned/Uncontained`.

### Compatibility

Preserve existing commands, arguments, text output, `--json` shapes, numeric IDs, environment overrides, protocol rules, and wrappers:

```text
create, workdir, projects, post, pull, log, summary,
status, task-add, task-update, tasks
```

`turnpike.py` becomes a compatibility launcher for the Rust CLI/Core and automatically starts Core when necessary.

**[F3]** If Core is unreachable (crashed, not installed yet, mid-upgrade), the compat CLI falls back to the legacy direct-SQLite code path with a stderr warning instead of erroring. The bus is the coordination lifeline for every agent on this machine; Core ownership of the database is the steady state, never a hard gate on posting a message or claiming a task.

Add:

```text
turnpike session list|start|adopt|resume|takeover|stop|archive
turnpike prompt send|queue|steer
turnpike checkpoint list|show|fork
turnpike terminal open|list|stop
turnpike resources status|policy
turnpike restore [--project <slug>] [--dry-run]
```

Define one provider-neutral adapter:

```text
discover, create, resume, fork, send_checkpoint,
steer?, interrupt, answer_action?, list_children,
stop_child?, archive, close, capabilities
```

Unsupported controls are omitted from the UI rather than simulated.

### Data model and migration

Add transactional schema migrations and additive entities:

- `sessions`: project, provider, opaque provider thread ID, parent/root lineage, cwd/worktree/branch, title, lead status, permissions, ownership, desired/observed state, provider capability/version data.
- `runs`: each process incarnation, PID/create time, Job Object identity, restore generation, start/end/exit reason.
- `checkpoints`: immutable prompt, author, parent checkpoint, type (`new`, `queued`, `steer`, `fork`, `broadcast`, `recovery`, `imported`), status, and idempotency key.
- `checkpoint_deliveries`: one row per recipient, allowing one broadcast checkpoint to fan out without duplicating its prompt.
- `events`: append-only normalized provider and Turnpike events with stable ordering and opaque provider references.
- `modules`: idempotent projections for plans, progress, commands, changes, tests, tools, approvals, questions, context, warnings, agent trees, and final answers.
- `terminal_sessions`, `resource_policies`, `resource_rollups`, `notifications`, `ui_state`, and FTS5 search indexes.
- Preserve provider transcripts as provider-owned history; Turnpike stores stable IDs and normalized projections, never couples itself to private JSONL/SQLite formats.

Before migration:

1. Make a timestamped database backup and checksum.
2. Run golden tests against the current CLI and copied live database.
3. Migrate inside one transaction.
4. Re-run the same commands and compare outputs.
5. Retain all original messages/tasks and IDs.

Convert legacy activity deterministically:

- Each user-authored message begins an imported checkpoint.
- Following agent messages become modules beneath it until the next user message.
- Unmatched activity enters an explicit `Imported project history` checkpoint.
- Task events link by task ID/time.
- Original records remain intact and every projection records its legacy source ID.

## Runtime, Recovery, and Resources

### Provider adapters

- **Codex:** launch one `codex app-server --stdio` runtime per managed root conversation. Use its structured thread/turn/item APIs for resume, fork, steer, interrupt, plans, diffs, approvals, goals, token/context meters, and subagent lineage. The app-server remains experimental, so pin supported CLI versions, generate protocol bindings, retain unknown events, and capability-gate every optional operation. Fall back to a managed native Codex TUI when compatibility checks fail. [Codex App Server](https://learn.chatgpt.com/docs/app-server.md)
- **Claude:** use one shared TypeScript Claude Agent SDK bridge with a live streaming `Query` only for working sessions; idle sessions remain dormant. Enable structured events, hooks, subagent forwarding, file checkpointing, and session resume/fork. Route spawned Claude processes through Core’s job-aware launch broker. [Claude streaming input](https://code.claude.com/docs/en/agent-sdk/streaming-vs-single-mode), [session management](https://code.claude.com/docs/en/agent-sdk/sessions)
  - **[F2]** The bridge makes Node a runtime dependency of Core (distinct from the UI, which stays Node-free). v1 uses the system Node with an engine check at Core startup (>=18 required; v24.14.0 present today) and an exactly-pinned SDK version. A Rust-native adapter speaking the CLI’s bidirectional stream-json wire protocol could remove the Node dependency later; recorded as an optional post-v1 optimization, not attempted in v1.
  - **[F4]** The SDK surface this adapter depends on was verified against the shipped 0.3.228 type definitions on 2026-08-12 (all named APIs present, signatures matching; see REVIEW.md). Remaining before Phase 4 design freeze: behavioral contract tests, not just type-level checks.
- **CodeWhale:** perform one bounded adapter milestone against its documented app-server. It ships as first-class only if create/list/read/resume/send/stream/interrupt pass the same contract suite. Otherwise v1 uses a managed terminal, saved thread ID, `codewhale resume`, and Turnpike bus updates; no extended effort is spent reverse-engineering parity.
- Each run records adapter and provider versions. A failed contract check disables writes and offers `Open native CLI`.
- Never permit two writers for one provider thread. External live sessions are read-only until an explicit takeover stops the old owner.

### Existing-session adoption

- Discover saved Codex, Claude, and CodeWhale sessions through supported provider APIs and running process metadata.
- Offer mappings based on cwd, thread name, current task, and worktree; require confirmation only for ambiguous mappings.
- Support explicit capture from a shell, including `CODEX_THREAD_ID`.
- Existing live Codex/Claude sessions remain `Externally owned`; takeover first stops or exits the original process, then resumes under Core.
- Imported sessions retain exact provider IDs, names, histories, cwd, branch, and task links.

### Reboot behavior

Auto-resume applies to work that was running or queued:

1. Core starts at login and restores project/session/checkpoint navigation from SQLite.
2. Idle and completed sessions appear immediately without consuming a provider process.
3. Previously active sessions enter the elastic restore queue.
4. Core resumes the stored provider thread ID; it never replays the previous raw prompt.
5. An automatic recovery checkpoint inspects provider history, Turnpike events, Git/worktree state, processes, tests, and artifacts before continuing.
6. Irreversible or externally visible actions are not repeated without evidence they remain incomplete.
7. Queued-but-undispatched prompts continue in order after reconciliation.
8. Ambiguous `dispatching` prompts stay `Needs attention` until their idempotency key is reconciled.
9. Terminals reopen as fresh shells with the same title, profile, and cwd; previous commands are never rerun.

### PowerShell

- Host the actual configured shell through Windows ConPTY. Detect `pwsh.exe`; fall back to the installed Windows PowerShell 5.1 on this machine.
- Load normal profiles and preserve aliases, ANSI/full-screen applications, Unicode, clipboard, history, resize, Ctrl+C, and unrestricted child-process behavior.
- Keep user shells in their own metered Job Objects, separate from agent runtimes.
- Provide:
  - `Pop out`: move the same live ConPTY view into a slim Turnpike window.
  - `Open external`: launch a sibling Windows Terminal shell with the same cwd/environment recipe; do not claim it is the same process.
- Drawer close only hides the terminal. Termination is a separate explicit action.
- Keep 10 MiB live scrollback per tab and compressed segmented history capped at 50 MiB per tab/1 GiB globally. Private tabs persist no output. Never persist environment-variable values.

ConPTY supplies the native console boundary, while Job Objects provide whole-process-tree accounting and controls. [Windows pseudoconsoles](https://learn.microsoft.com/en-us/windows/console/pseudoconsoles), [Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)

### Adaptive resource governor

Put every root runtime and every user terminal in a separate Job Object, assigned before user code executes. Track descendants through completion-port events.

Meters:

- Global CPU, available RAM, commit headroom, disk latency/busy time, and NIC throughput.
- Per runtime: normalized CPU, working set, private commit, I/O rate, process count, uptime, and peak memory.
- Per subagent: exact provider activity, token/context/usage data; do not invent per-subagent OS CPU/RAM when subagents share a runtime.
- Sample at 1 Hz normally and 4 Hz only while Resource Center is visible. Retain 15 minutes in memory and one-minute rollups for seven days.

Default policy:

| State | Trigger | Automatic action |
|---|---|---|
| Normal | Below pressure thresholds | Focused weight 7/9; active background 3/9; idle/restoring 1/9; unrestricted bursting |
| Yellow | CPU ≥85% for 10s, free RAM/commit <15%, or disk latency >25 ms | Hold new background dispatches, apply EcoQoS/weight 1 to background jobs, identify offenders |
| Orange | CPU ≥92% for another 10s, free RAM below `max(2 GiB, 8%)`, commit headroom <10%, or disk latency >50 ms | Freeze launch queue; temporarily budget background CPU while keeping at least 15% system headroom; show an actionable warning |
| Recovery | CPU <80% and memory above 15% for 20s | Remove temporary caps and drain the queue by priority |

Additional defaults:

- Focused and pinned sessions remain uncapped in Adaptive mode.
- No hard memory cap by default; hard allocation limits are advanced opt-in because exceeding them can crash a workload.
- Soft memory warning at 25% of physical RAM per session.
- Process guard: warn at 32, hard-stop new children at 64 per session and 256 managed processes globally; both are configurable.
- Network is metered globally; outbound per-job limits are opt-in.
- Never silently kill or thread-suspend work.
- `Pause` means pause Turnpike’s queue/lower scheduling weight—not freeze an in-flight model turn.
- Distinguish `Cancel turn`, `Graceful process stop`, `Stop runtime`, and confirmed `Emergency kill process tree`.
- Every intervention shows its trigger, duration, affected jobs, and temporary override controls.

## Product Experience

### Layout

- **Left rail:** Inbox, active/paused/archived projects, root sessions, unread/actionable counts, task progress, and tiny resource indicators.
- **Center:** project room or selected conversation, with a checkpoint gutter and branch lines.
- **Right inspector:** complete agent/subagent tree, current action, task, branch/cwd, context, resource meters, controls, and recent outcomes.
- **Bottom:** composer and optional terminal drawer.
- Project views: `Room`, `Tasks`, and `Changes`.

The Project Room contains only checkpoints, milestones, blockers, approvals, and final summaries. Raw tool chatter stays inside modules.

### Checkpoints and modules

Every user submission receives a UUID before dispatch.

- Normal prompts form the chronological project spine.
- A live steer becomes a nested checkpoint beneath the active prompt.
- Subagent conversations and forks are child threads, never flattened.
- Native provider forks resume from the selected provider turn/message. When unsupported, create a clearly labeled `Context handoff` session using the checkpoint capsule.
- Prompt text is immutable after sending; titles, pins, and annotations remain editable.

Each checkpoint renders:

1. Exact user prompt.
2. Current action or pending request.
3. Collapsible modules.
4. Final answer.

Module registry:

- Plan
- Progress
- Agents/subconversations
- Commands and paged output
- Changes/diffs
- Tests/builds
- Tools/MCP/web/media
- Approvals and questions
- Context Capsule/compaction
- Warnings/failures
- Final Answer

Active, failed, or actionable modules open automatically; completed successful modules collapse to one-line summaries. Context capsules expose goals, constraints, decisions, files, validation, open work, and child results—not hidden reasoning.

### Composer and controls

Default routing is the project’s lead session plus explicit mentions.

Composer chips:

- `To`: lead, selected root, subagent, bus, new session, or broadcast.
- `Delivery`: new checkpoint, queued checkpoint, or live steer.
- `Runtime`: provider/model/reasoning, Full Access badge, cwd/worktree.

Rules:

- Idle target: start immediately.
- Busy target: queue as the next checkpoint.
- `Steer live`: explicit secondary action.
- Broadcast: show exact recipients and create one parent checkpoint with per-recipient deliveries.
- `@` mentions agents; `#` references projects/tasks; `/` opens commands.
- Drafts persist independently per target.
- Terminal output enters model context only through `Send selection to agent`.

Controls are capability-gated:

- Queue/reorder/cancel pending checkpoint.
- Steer or interrupt current turn.
- Goal pause/resume where supported.
- Fork from checkpoint.
- Stop child task where supported.
- Stop descendants, archive, takeover, open terminal.
- Scheduling priority: `Auto`, `Foreground`, `Background`.
- Graceful stop followed by separately confirmed force-kill.

Full Access is the default for Codex, Claude, and CodeWhale, with an unmistakable persistent badge and optional safer per-project profiles.

### Navigation and performance

Key defaults:

- `Ctrl+K`: quick switch.
- `Ctrl+F` / `Ctrl+Shift+F`: local/global search.
- `Ctrl+G`: checkpoint jump.
- `Alt+↑/↓`: previous/next checkpoint.
- `Alt+←/→`: navigation history.
- `Ctrl+PageUp/PageDown`: root session switching.
- `Ctrl+Shift+A`: agent inspector.
- `Ctrl+\``: terminal.
- `Ctrl+Enter`: send/queue.
- `Ctrl+Shift+Enter`: steer live.
- `Ctrl+.`: interrupt.
- `F6`: cycle major regions.

Virtualize conversation, tree, search, diff, and terminal output. Batch streaming deltas once per animation frame and never rebuild the full DOM. Preserve scroll position while reading history and show `N new updates` instead of forcing Live.

## Implementation Sequence

0. **[F1] Stopgap session restore (ship first, days not months)**
   - Add `turnpike session-bind`, `turnpike sessions`, and `turnpike restore [--project] [--dry-run]` to the existing Python CLI, backed by one new additive `session_bindings` table (project, task, provider, thread ID, cwd, title, bound-at).
   - `session-bind` captures the current provider thread (`CODEX_THREAD_ID` for Codex; session ID for Claude); `restore` opens one Windows Terminal window with a tab per bound active session running `codex resume <id>` / `claude --resume <id>` in the saved cwd, skipping sessions already running, restoring `doing` tasks by default.
   - This solves the original reboot pain immediately with zero new runtime, produces real-world resume data that informs the adapter design, and its bindings table is designed to be imported as first-class sessions by Phase 2. It is a bridge, not a parallel product: no UI, no process supervision.

1. **Safety and parity**
   - Create a dedicated Turnpike project/task and clean worktree from `master`; do not touch the current dirty canonical checkout.
   - Add database backups, schema migrations, golden CLI tests, fake provider fixtures, and baseline benchmarks.
   - Keep unrelated handoff/node_modules repository cleanup out of this feature.

2. **Core and compatibility**
   - Build Rust Core, singleton/autostart/tray lifecycle, named-pipe RPC/event streaming, SQLite single-writer repository, FTS, projections, and Rust CLI.
   - Convert `turnpike.py` into the compatibility launcher.
   - Replace broad polling and direct monitor SQL with incremental Core events.

3. **Processes, terminals, and resources**
   - Add ConPTY terminals, Job Object launch broker, completion-port tracking, meters, policies, alerts, logs, and stop/kill semantics.
   - Prove full Windows PowerShell parity before provider integration.

4. **Provider adapters**
   - Implement Codex and Claude as first-class adapters against fake fixtures and live versions.
   - Run the bounded CodeWhale adapter gate and fall back to managed terminal mode if it fails.
   - Add session discovery, ownership leases, adoption, takeover, and version/capability health checks.

5. **Structured UI**
   - Ship project rooms, checkpoint tree, modules, agent inspector, composer routing, terminal drawer/pop-out, resource center, inbox, search, keyboard navigation, density presets, and accessibility.
   - Preserve the existing task board, summaries, Git/worktree health, and coordination bus.

6. **Migration and recovery rollout**
   - Import all legacy history.
   - Pilot one Codex and one Claude project.
   - Adopt the current eight sessions without concurrent writers.
   - Exercise crash/reboot reconciliation, then enable login auto-resume.
   - Keep the old monitor available read-only for one release; remove it only after CLI/UI parity and rollback validation.

## Test and Acceptance Plan

- **Data/compatibility:** copied-live-database migration, rollback, corrupt-tail recovery, all legacy CLI commands and JSON outputs, concurrent WAL access, idempotent event replay.
- **Provider contracts:** create/list/read/resume/fork/send/interrupt, unknown events, version mismatch, approvals/questions, compaction, nested subagents, external ownership, takeover, and native fallback.
- **Recovery:** crash before dispatch, after provider acceptance, during commands, edits, tests, compaction, approvals, and subagents; assert no duplicate prompt or terminal-command replay.
- **Terminal:** profiles, aliases, ANSI/full-screen programs, Unicode, clipboard, resize, Ctrl+C-aware/ignoring commands, child processes, live pop-out, external sibling, private history.
- **Resources:** CPU spin, memory pressure, process fork storm, disk saturation, networking, escaped/WMI/elevated children, pressure hysteresis, overrides, graceful stop, emergency kill, sleep/resume, and RDP.
- **Scale fixture:** 8 active projects, 16 roots, 64 child threads, 5,000 checkpoints, 100,000 events, eight concurrent streams, and eight terminals.
- **Performance gates:** ≤1.5s cold window, ≤750ms warm, cached workspace interactive within 2s, project/session switch ≤100ms p95, loaded checkpoint jump ≤75ms, search first result ≤250ms, input-to-paint ≤50ms, 55–60fps streaming, <0.5% idle UI CPU, <1% resource-sampler CPU, and ≤200 MB app-owned private memory.
- **Security:** current-user pipe ACL, no HTTP mutation surface, command/path escaping, provider credentials never copied into Turnpike, private terminal behavior, and explicit Full Access labeling.
- **Accessibility:** WCAG 2.2 AA, keyboard-only operation, 200% Windows scaling, reduced motion, semantic agent trees/modules, and screen-reader announcements only for meaningful state changes.
- **Desktop QA:** launch the real packaged app, verify a clean responsive top-level window and owned dialogs, capture every HWND, inspect the PNGs, exercise restore/checkpoint/subagent/terminal/resource paths, recapture, and inspect logs from launch onward using the mandated desktop test scripts.

## Assumptions and Fixed Defaults

- Windows 11/current user only; remote/LAN/mobile control is out of v1.
- Codex and Claude are required first-class providers. CodeWhale has a strict bounded integration gate.
- Full Access is the visible default.
- Auto-resume uses reconciliation, never blind prompt replay.
- The chronological project spine plus nested steer/subagent/fork checkpoints is authoritative.
- Legacy history is fully converted without deleting original records.
- Window close hides to tray; explicit exit is separate.
- Local CPU/RAM meters cover runtimes, tools, builds, and terminals—not remote model inference.
- Provider-specific limitations remain visible; Turnpike never fabricates controls or measurements.
- The OpenAI adapter design was grounded through the openai-docs skill and the current official Codex manual.
- **[F4]** Local verification on 2026-08-12 (REVIEW.md): claude CLI 2.1.220, codex CLI 0.145.0, `claude agents --json --all`, `codex app-server` with `generate-ts`/`generate-json-schema`, Node v24.14.0, and the complete claimed Agent SDK 0.3.228 API surface were all confirmed present on this machine.

## Cleaned-up request

Plan an extremely efficient Turnpike desktop workspace that restores and supervises multiple Codex, Claude, and optionally CodeWhale projects; provides unrestricted PowerShell terminals, adaptive resource protection and meters, Slack-style project rooms, prompt checkpoints, modular activity, explorable subagents, comprehensive controls, and liquid-smooth navigation.

## Layman’s recap

Turnpike becomes a lightweight Slack-like command center for your agents. Every prompt and subagent is organized and recoverable, real PowerShell remains available, sessions restart safely after reboot, and Windows automatically slows background work before it overwhelms the computer.
