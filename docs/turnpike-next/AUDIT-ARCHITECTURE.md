<!-- Provenance: Turnpike current-state architecture audit; codex subagent deliverable 2026-08-11/12,
     a Codex session -->

## Turnpike audit

### Current architecture

- `turnpike.py`: dependency-free Python CLI and SQLite bootstrap. Database is `%USERPROFILE%\.turnpike\turnpike.db`, with legacy environment/path fallbacks, WAL, foreign keys, and a 15-second busy timeout.
- `monitor.py`: stdlib threaded HTTP server on fixed loopback port `8642`. It imports Turnpike but also reads/writes SQL directly, duplicating CLI business rules.
- `ui/index.html`: one 450-line HTML/CSS/JavaScript SPA.
- Deck: a 5.69 MB installed Tauri v2 executable. It attaches to anything listening on port 8642 or starts `monitor.py` hidden, embeds its URL, and kills only the Python child it spawned.
- There is no managed terminal, pseudoconsole, agent process tree, session identity, transcript index, resume workflow, resource telemetry, or crash restoration.

### Data schema and public CLI

Current tables:

- `projects`: slug, name, goal, status, summary, timestamps, plus `workdir` added through one ad hoc migration.
- `messages`: project, author, kind, plain-text body, timestamp.
- `tasks`: project, title/detail, status, assignee, creator, timestamps.
- `cursors`: last message read per agent/project.
- `agents`: one global `last_seen` timestamp per agent name.

Public commands that must remain compatible:

```text
create, workdir, projects, post, pull, log, summary, status,
task-add, task-update, tasks
```

Compatibility also includes `--json` shapes, `TURNPIKE_DB`, `AGENT_HARNESS_DB`, `harness.py/.bat`, existing numeric IDs, current database contents, worktree naming, and the agent protocol. Notably, `pull --peek` still writes `agents.last_seen`; it is not fully read-only.

### Existing Deck/UI capabilities

- Project sidebar, all-project activity, presence, summaries, read cursors.
- Four-column drag/drop task board and project progress.
- Unified messages, task events, and Git commits.
- Worktree branch/ahead/behind/dirty chips.
- Directive composer and project creation/workdir editing.
- Summon Claude, Codex, or DeepSeek in separate `cmd /k` windows, with automatic parking worktrees.
- SSE change notification plus ten-second polling.

### Main technical debt

- Every refresh returns up to 300 messages, every task, 60 Git commits, and scans every worktree; the parsed `since` parameter is ignored. The client stringifies and rebuilds the complete timeline DOM.
- SSE polls SQLite every 600 ms per browser connection. Any heartbeat can trigger broad refetches.
- `monitor.py` bypasses the “CLI-only database” contract. Validation and cursor/project-touch behavior differ between API and CLI.
- No schema version table, transactional migration framework, optimistic concurrency, enum constraints, API schema, export/backup workflow, or first-party tests.
- Summon has no PID/run tracking, deduplication, exit status, output capture, resume ID, attachment, interrupt semantics, or restoration.
- Port attachment checks only “something accepted TCP,” not that it is Turnpike. Paths and port are hard-coded; the Tauri app is an unbundled shell.
- Worktree detection requires `.git` to be a directory, so an existing Git worktree can be misclassified.
- Security relies solely on loopback; local web pages/processes can reach state-changing HTTP endpoints.
- The repository mixes Turnpike with large handoff projects: 8,250 tracked files, roughly 7,757 tracked `node_modules` files, and a 42.5 MiB Git pack.

### Recommended evolutionary architecture

Keep the small Tauri shell and SQLite, but introduce a native Rust background `Turnpike Core`:

- Core owns SQLite, provider adapters, Windows ConPTY terminals, process lifecycles, Job Objects, metrics, and restoration. Deck becomes an attachable UI; closing Deck does not stop agents.
- Use a current-user ACL-protected named pipe for versioned RPC/events. Retain port 8642 temporarily as a compatibility gateway.
- Preserve `turnpike.py` as the existing command surface, initially delegating to Core with an automatic-start/fallback path.
- Host real `pwsh.exe`/agent CLIs through ConPTY and xterm.js. This retains PowerShell’s exact input, VT output, Ctrl+C, child-process, environment, and working-directory behavior.
- Wrap every agent and descendant process in one Windows Job Object. Meter CPU, private/working memory, I/O, process count, and uptime for the entire tree.
- Default to elastic scheduling: no fixed CPU cap; foreground sessions receive normal priority, background sessions lower weight, and all may burst when capacity is free. Maintain configurable system memory headroom, warn/deprioritize under pressure, and pause the least-recently-used unpinned background run before critical pressure. Never auto-kill; hard per-session caps are opt-in.
- Keep high-frequency metrics in bounded in-memory rings and persist only coarse rollups.

Add versioned migrations and additive tables for:

- `sessions`: project/provider, opaque external conversation ID, cwd, title, parent session, policy, desired and observed state.
- `runs`: each concrete process launch/resume, PID/job metadata, start/end/exit reason.
- `turns`: immutable checkpoint created for every user prompt, including transcript/event offsets.
- `events/modules`: typed, versioned modules linked to project/session/turn/parent run.
- `resource_rollups` and `ui_state`.

Keep terminal scrollback in compressed append-only segment files with DB offsets rather than storing large blobs. Treat provider transcripts as source material and index stable IDs; avoid coupling the database to private Codex transcript formats.

The UI should become a typed, virtualized component app inside Tauri:

- Left: Slack-style projects/channels with unread, active-session, task, and resource badges.
- Center: prompt checkpoints with instant previous/next navigation. Each turn contains collapsed modules for response, plan, files/diffs, tests, terminal/tool output, decisions, context compaction, and errors.
- Right: hierarchical agent/subagent inspector showing current action, task, branch, cwd, context state, CPU/RAM, and pause/resume/interrupt/restart/terminate controls.
- Bottom drawer: full ConPTY terminal for the selected session.
- Child runs use `parent_session_id`/`parent_event_id`, so subagent conversations expand as nested threads rather than being dumped into the main feed.
- Apply keyset pagination, incremental event patches, list virtualization, and persistent selection/layout state.

Suggested delivery sequence:

1. Freeze legacy behavior with migration, CLI, API, and copied-live-database tests.
2. Add Core, named-pipe RPC, session/run storage, ConPTY, Job Objects, and resource meters while retaining the old UI.
3. Add provider adapters and one-click eight-session reboot restoration using opaque resume IDs.
4. Introduce checkpoints/modules/subagent hierarchy and the virtualized Slack-style UI.
5. Add elastic pressure control, startup recovery, performance gates, and retire direct SQL/legacy HTTP paths.

Acceptance should include eight concurrent projects, nested subagents, interactive PowerShell parity, exact conversation restoration after reboot, no duplicate resumes, full child-tree metering, UI responsiveness during CPU saturation, safe behavior under memory pressure, and migration of the current 594 KB database without changing existing CLI results.

### Repository/worktree warning

The canonical checkout is currently on `agent/deepseek/task-11-asset-pipeline`, not `master`, with unrelated modified and untracked handoff files. Core Turnpike files match `master`, but implementation must not occur there. Create a dedicated Turnpike bus project/task and a fresh agent worktree/branch from the agreed integration base. There is no configured Git remote, and repository cleanup or handoff extraction should be a separate task from this product work.

No repository files were changed during this audit.

### Cleaned-up request

Audit Turnpike’s current implementation and recommend a compatible, efficient architecture for a persistent Slack-style agent/session manager with native PowerShell freedom, checkpoints, subagent threads, restoration, controls, and resource protection.

### Layman’s recap

Turnpike already has a very small desktop shell and useful project board, so it does not need a bulky replacement. It needs a durable native engine underneath it to own real terminals, remember conversations, display agents as organized threads, restore work after reboot, and keep the computer responsive.
