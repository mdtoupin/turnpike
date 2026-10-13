<!-- Provenance: Claude Agent SDK runtime audit; codex subagent deliverable 2026-08-12T02:31Z,
     a Codex session -->

## Claude runtime audit

The right integration boundary is the official TypeScript Claude Agent SDK behind a thin Turnpike provider bridge. Do not build the primary integration around terminal scraping, `claude -p` JSON, or direct `.claude/**/*.jsonl` parsing.

### Recommended architecture

- Run one shared TypeScript Claude bridge under Turnpike’s persistent Rust supervisor.
- Pin an exact `@anthropic-ai/claude-agent-sdk` version and use its bundled Claude executable for managed sessions. At audit time:
  - Installed system CLI: `2.1.220`
  - Current SDK package: `0.3.228`, bundling Claude Code `2.1.228`
- Keep one SDK `Query` per hot/working session. Idle sessions remain dormant and resume lazily, avoiding eight unnecessary Claude processes.
- Use streaming input and expose the SDK’s initialization capabilities instead of version-sniffing.
- Preserve normal Claude behavior with:
  - Claude Code system-prompt preset
  - Claude Code tools preset
  - `settingSources: ['user', 'project', 'local']`
  - `enableFileCheckpointing: true`
  - `includePartialMessages: true`
  - `includeHookEvents: true`
  - `forwardSubagentText: true`
- Full-access default maps to `permissionMode: 'bypassPermissions'` plus `allowDangerouslySkipPermissions: true`. Show a persistent, unmistakable Full Access indicator and allow live switching to Auto, Default, or Plan.

The SDK exposes a `spawnClaudeCodeProcess` callback. Use it to register each Claude child PID with Rust and place its process tree into the correct Windows Job Object before releasing that session’s prompt gate. A native job-aware spawn shim can later make assignment pre-execution and race-free. If containment fails, block dispatch and label the session uncontained rather than silently losing resource control.

### Checkpoints and prompt delivery

Turnpike should own the queue rather than filling Claude’s internal asynchronous queue.

1. Persist the checkpoint and UUID transactionally before sending.
2. Send an SDK user message stamped with that UUID.
3. Group all subsequent root, tool, task, and subagent events beneath it.
4. Treat `session_state: idle` as the authoritative end boundary, not merely the first result event.
5. Reconcile the UUID against `getSessionMessages` after failures; never blindly resend a checkpoint in an ambiguous `dispatching` state.

For an active session:

- Default Send: retain locally as the next checkpoint, where it can be reordered or cancelled.
- Steer live: capability-gate a UUID-stamped `priority: 'now'` message and test its semantics.
- Fallback: label the action “Interrupt and steer,” call `Query.interrupt()`, drain the interrupted result, then dispatch the new checkpoint.
- Do not call the SDK’s private queued-message cancellation protocol.

This makes every user submission navigable while avoiding invisible provider-side prompts that Turnpike cannot reliably reorder.

### Structured module mapping

Use the SDK event stream as the durable source for Turnpike projections:

- Assistant messages and partials → response/progress modules.
- Structured tool-use and tool-result blocks → Commands, Changes, Tests, MCP, and Tool modules.
- `TaskStarted`, `TaskProgress`, `TaskUpdated`, and `TaskNotification` → subagent/task rows with usage, duration, state, and result.
- `parent_tool_use_id`, `task_id`, `tool_use_id`, and `agent_id` → nested agent lineage.
- `forwardSubagentText` → full child conversations; current events also carry subagent type and task description.
- `listSubagents` and `getSubagentMessages` → historical child-thread restoration.
- `PreCompact` and `PostCompact` hooks → a collapsible Context Compacted module; `PostCompact.compact_summary` is the compacted capsule.
- Permission, elicitation, and `AskUserQuestion` callbacks → actionable modules.
- `getContextUsage()` → context meter.
- result `modelUsage` and estimated cost → whole-tree model meters; top-level usage alone omits subagent consumption.

Store an append-only normalized event journal and rebuild modules idempotently. Preserve unknown provider events as debug records so an SDK update cannot crash or silently discard history.

### Supported controls

| Turnpike control | Claude boundary |
|---|---|
| Interrupt root turn | `Query.interrupt()` |
| Change permissions | `setPermissionMode()` |
| Change model | `setModel()` |
| Stop background child/task | `stopTask(taskId)` |
| Inspect background work | `backgroundTasks()` |
| Resume session | `resume: sessionId` |
| Fork at checkpoint | `forkSession(sessionId, { upToMessageId })` |
| Preview/restore files | `rewindFiles(userMessageId, { dryRun })` |
| Rename/tag | `renameSession`, `tagSession` |
| MCP health/control | status, reconnect, toggle, and set APIs |
| Gracefully unload idle runtime | `close()`, then resume later |

Do not expose unsupported controls:

- There is no stable direct “steer this running subagent” API. Route a redirection through its parent.
- There is no safe general pause API. “Pause” should pause Turnpike’s launch queue or lower OS priority, not claim the model/tool is suspended.
- Agent Teams remain experimental and lack direct teammate-control APIs. Render observable team nodes as experimental/external rather than depending on them in v1.

### Existing-session discovery and adoption

Use supported APIs:

- `listSessions({ includeProgrammatic: true, includeWorktrees: true })`
- `getSessionInfo`
- paginated `getSessionMessages`
- `listSubagents` and `getSubagentMessages`

Do not parse raw JSONL. Anthropic explicitly says its format changes between versions, and this machine already has transcripts around 69 MB, making direct eager parsing both brittle and inefficient. [Claude session documentation](https://code.claude.com/docs/en/sessions)

For live external Claude processes, poll the scriptable `claude agents --json --all` interface at a modest cadence. It exposes `cwd`, kind, start time, background ID/state, PID/status, wait reason, session ID, and name. Official external controls include `attach`, `logs`, `stop`, and `respawn`. [Claude agent view](https://code.claude.com/docs/en/agent-view)

Ownership rules:

- Offline session: import and resume normally.
- External background session: show External Owner. Explicit takeover may call `claude stop <id>`, wait for stopped state, then resume its session ID through Turnpike.
- External foreground session: read-only. Ask the user to background it with `←` or exit it before takeover.
- Safe alternative: fork from a selected checkpoint, preferably into an isolated worktree.
- Never open the same session concurrently: Claude documents that messages from both processes will interleave into one transcript.
- Do not trust `.claude/sessions/<pid>.json` for process control; stale entries were present locally.

`claude attach <id>` can be opened in Turnpike’s ConPTY terminal for the native Claude TUI, but Turnpike must not simultaneously resume that transcript through the SDK.

### Restart and reconciliation

Turnpike can fully restore navigation, transcripts, queued prompts, context modules, and idle sessions. It cannot guarantee exact continuation of an SDK-managed model/tool turn across a Windows reboot.

Recovery states:

- Idle/completed: restore immediately; resume lazily on the next prompt.
- Running with a surviving Turnpike supervisor: reconnect the UI to the existing bridge.
- Recorded running but process dead: import the persisted tail, mark Interrupted by restart, and offer Continue or Fork.
- Ambiguous dispatch UUID found in Claude history: never resend.
- Ambiguous dispatch UUID absent: keep Needs attention until reconciliation completes.
- Missing cwd/auth/MCP: do not resume in a different directory; show exact remediation.

Automatic UI/session restoration is safe. Automatic replay of an in-flight prompt is not, because a tool side effect may have occurred before the crash. If optional auto-continue is added, its prompt must tell Claude to inspect current files/processes and continue without repeating completed effects.

Claude’s own background agent-view supervisor can restart interrupted background sessions after shutdown, but it does not provide the SDK’s rich structured stream. Treat it as an external compatibility mode, not Turnpike’s core runtime.

### PowerShell and resources

Claude’s built-in command tool uses Git Bash on native Windows. The requested PowerShell freedom therefore belongs in a separate ConPTY-backed `pwsh.exe` terminal module, not inside the Claude event adapter.

SDK controls do not allocate CPU or memory. Rust/Windows Job Objects govern the local Claude process, tools, builds, and descendants. Keep model usage/context/cost meters separate from local CPU/RAM meters.

A shared bridge plus dormant idle sessions minimizes overhead. Active Claude subprocesses may consume available resources, while the global Turnpike governor holds new launches under memory/CPU pressure rather than killing active work.

### Required tests

- Exhaustive fixtures for every documented SDK message and an unknown event.
- Idempotent replay, duplicated/out-of-order task events, and three-level subagent trees.
- UUID checkpoint dispatch, crash-before-send, crash-after-send, and no duplicate replay.
- Create, list, resume, rename, tag, fork, dry-run rewind, and restore.
- Foreground/background subagent start, progress, completion, failure, and `stopTask`.
- Compaction before/after hooks and context-meter updates.
- Full-access, Auto, Default, and Plan transitions.
- User questions, permission requests, UI restart while a callback is pending.
- External foreground detection, background takeover, native attach, stale PID records, and same-session collision refusal.
- App kill and Windows reboot during tool execution, subagent execution, compaction, and result/idle transition.
- Large transcript paging and eight concurrent sessions with bounded bridge memory.
- SDK upgrade contract test before changing the pinned package.
- Live tests against the installed system CLI and bundled CLI, with API cost limits.

One distribution constraint must be called out early: Anthropic says third-party products may not offer claude.ai login or subscription rate limits without prior approval. A distributable Turnpike should use API-key authentication or obtain approval; personal local use should not silently become a public login integration. Branding should say “Claude” or “Claude Agent,” not “Claude Code Agent.” [Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview)

Claude checkpoints align naturally with Turnpike’s prompt model: every user prompt creates one, with the latest 100 file snapshots retained. Rewind warnings must state that Bash changes, most subagent edits, external changes, and linked files are not reliably restored. [Claude checkpointing](https://code.claude.com/docs/en/checkpointing)

No files or runtime state were modified during this audit.

### Cleaned-up request

Audit Claude Code’s supported runtime interfaces and produce a safe, efficient integration plan for Turnpike sessions, checkpoints, subagents, controls, recovery, full access, resource accounting, and PowerShell.

### Layman’s recap

Turnpike should manage Claude through its official programming interface, keep prompts and subagents structured and searchable, safely adopt old sessions without double-opening them, and restore everything after restart without blindly repeating possibly destructive work.
