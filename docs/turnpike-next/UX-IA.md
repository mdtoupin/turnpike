<!-- Provenance: UX / interaction-architecture handoff; codex subagent deliverable 2026-08-12T02:25Z,
     a Codex session -->

## UX/IA handoff

Grounding: Turnpike is currently a lightweight Tauri 2 wrapper around the Python monitor and a single-page timeline/kanban UI. It has no durable Codex-session, checkpoint, subagent, terminal, or resource-management layer. The new experience should replace the timeline view while preserving projects, tasks, bus messages, workdirs, worktrees, and agent identities.

### Core information model

Use this hierarchy consistently:

```text
Turnpike
└─ Project
   ├─ Project room
   └─ Root session
      ├─ Checkpoint: one submitted user prompt
      │  └─ Modules: plan, commands, changes, tests, agents, context, final
      └─ Child thread
         ├─ Subagent
         └─ Fork from checkpoint
```

- A project is the Slack-style room.
- A root session is one resumable Codex/Claude/DeepSeek conversation.
- Every submitted prompt receives an immutable checkpoint ID before dispatch. A queued prompt and a live steer are still checkpoint types, so every user submission remains navigable.
- Subagents and forks are distinct child-thread types. Never flatten either into the parent transcript.
- Ordinals such as “Checkpoint 12” are display labels, not identifiers.
- Raw events remain durable and searchable; modules are projections, never lossy replacements.

### Desktop layout

```text
┌ Back/forward ─ breadcrumb ─ Ctrl+K search ─ actionable ─ CPU/RAM ─ bell ┐
├ Project/session rail ────── Conversation + checkpoint gutter ─ Agent dock ┤
│ Active projects             Sticky checkpoint header          Agent tree  │
│   root sessions             Prompt                             Resources   │
│ Paused/archived             Compact modules                   Controls    │
│                              Final answer                                  │
├──────────────────────────── Composer routing + mode + permissions ────────┤
└──────────────────────────── Terminal drawer, when open ───────────────────┘
```

- Left rail: 216–240 px, resizable. Show Inbox, Active Projects, Paused, Archived. Project rows contain active-agent count, actionable badge, progress, and a tiny aggregate resource indicator. The selected project expands only its root sessions.
- Center: flat Slack-style message rows rather than nested card walls. A 28 px checkpoint gutter shows numbered nodes and fork lines. The sticky checkpoint header shows title, routing target, state, elapsed time, model/mode, cwd/branch, and context usage.
- Right dock: 300–340 px, collapsible. It contains the selected root’s complete agent tree, selected-agent inspector, resources, and controls.
- At widths below 1100 px, the inspector becomes an overlay. Below 900 px, the left rail also becomes an overlay. Conversation and composer always retain priority.
- Project Room is a compact cross-session feed of user checkpoints, milestones, blockers, approvals, and final summaries—not interleaved tool output. Selecting any entry opens its source session/checkpoint.
- Preserve the current task board as a project-level `Tasks` view; keep `Room` as the default and add `Changes` as the third project view.

### Checkpoints and modules

Each checkpoint renders in this order:

1. Exact user prompt, always open.
2. Current action or actionable request, open while active.
3. Completed work modules, collapsed to one-line summaries.
4. Final answer, always open when available.

Module registry:

- `Plan`: structured steps and current step.
- `Progress`: coalesced commentary/status updates; never stream token-by-token into separate messages.
- `Agents`: child thread tree, status, result summary, and “Open subconversation.”
- `Commands`: command, cwd, state, duration, exit code, and virtualized output.
- `Changes`: files, additions/deletions, and diff viewer.
- `Tests`: detected test/build checks and outcomes.
- `Tools`: MCP, web, image, and other structured calls.
- `Approvals & Questions`: pinned above other modules until resolved.
- `Context Capsule`: goal, constraints, decisions, open work, files, validation, and child-result summaries.
- `Warnings/Failures`: open by default.
- `Final Answer`: the agent’s actual user-facing response.

Rules:

- Active, failed, or actionable modules expand automatically; successful completed modules collapse.
- “Expand all” is scoped to one checkpoint.
- Large output is paged/virtualized and loaded only on expansion.
- A Codex compaction event creates a visible “Codex compacted context” marker. Turnpike’s deterministic Context Capsule is separately labeled so the UI never implies knowledge of hidden model context.
- Historical transcript remains explorable after compaction.
- Do not expose private chain-of-thought. Only documented reasoning summaries may appear.
- When output arrives while the user is reading history, preserve scroll position and show “N new updates”; auto-follow only when already pinned to Live.

### Agent and subagent inspector

Each tree row shows:

- Agent/type icon and human-readable task title.
- `Starting`, `Thinking`, `Running tool`, `Waiting approval`, `Waiting user`, `Idle`, `Completed`, `Failed`, `Interrupted`, `Restoring`, or `Orphaned`.
- Latest action, elapsed time, CPU, RAM, and context percentage.
- Unread/actionable indicator.

Selecting a row opens:

- Goal/task, parent and children, model/reasoning, permission mode, cwd/worktree/branch.
- Current tool or command.
- CPU/RAM history, process count, context/token usage, and peak memory.
- Recent checkpoints, changes, test outcome, and terminal processes.

Capability-gated controls:

- Send follow-up / steer active turn.
- Queue next checkpoint.
- Interrupt current turn.
- Resume idle session.
- Fork from selected checkpoint.
- Stop all active descendants.
- Archive completed thread.
- Open terminal.
- Set local priority: `Auto`, `Foreground`, `Background`.
- Pause queue; explicitly label that this does not suspend an in-flight model response.
- Graceful process stop, then separately confirmed force-kill.

Bus-only agents must show only supported controls, such as post directive and open external terminal. Never render a control that cannot be executed reliably.

### Composer routing

The composer has three visible chips beneath it:

- `To`: selected session, selected subagent, project bus, new session, or broadcast.
- `Delivery`: new checkpoint, queued checkpoint, or steer live turn.
- `Runtime`: model/reasoning, permissions, cwd/worktree.

Behavior:

- Idle target: Send starts a new checkpoint.
- Active target: default is Queue as next checkpoint.
- `Steer live` is an explicit secondary action and creates a nested steer checkpoint.
- `Interrupt and replace` requires confirmation.
- Broadcast shows the exact fan-out list and warns about duplicate work.
- `@` completes agents, `#` completes projects/tasks, and `/` opens commands.
- Drafts persist independently per route.
- Sent prompt text is immutable; users may rename, pin, or annotate its checkpoint.
- Terminal output enters model context only through an explicit “Send selection to agent” action.

### Terminal experience

Provide a real PowerShell PTY, not a simulated command box:

- Docked drawer by default, toggled with `Ctrl+\``.
- Pop out into a Turnpike-owned native window.
- Open externally in Windows Terminal/PowerShell.
- Preserve PowerShell profiles, aliases, ANSI, clipboard, command history, resize, Ctrl+C, and working directory.
- User terminals carry a permanent `User shell · full system access` label. Agent sandbox/permission controls remain separate.
- Closing the drawer never stops its process. Closing an active tab offers `Hide`, `Detach`, `Terminate`.
- Terminal tabs are bound to project/session/cwd and can be manually attached to a checkpoint.
- After reboot, restore tab title, cwd, shell profile, and history, but never rerun the previous command automatically.
- External terminals restore from a saved launch recipe and resumable agent thread; Turnpike must not claim their previous native process survived.

### Resource Center

Keep local compute and model usage visually separate:

- Global header meter: total CPU, used/total RAM, running local workloads, actionable pressure state.
- Project row: aggregate descendant CPU/RAM.
- Agent row: current CPU, RSS, peak RSS, process count, 60-second sparkline.
- Context/token and account quota meters live in a separate “Model” section.
- Missing telemetry displays `Unavailable`, never `0`.

Default `Adaptive` policy:

- No hard CPU or RAM cap per agent; workloads may consume all spare capacity.
- Foreground/user terminal processes remain Normal priority. Background process groups use Below Normal/EcoQoS and still consume idle CPU.
- CPU pressure at ≥95% for 15 seconds defers starting new background local workloads; resume below 85% for 10 seconds.
- Memory safety gate activates when available RAM is below `max(2 GiB, 8%)`; resume above `max(3 GiB, 12%)`.
- The gate holds new agent/tool dispatches. It never automatically kills, suspends, or corrupts running work.
- Provide `Run anyway once`, `Pin foreground`, and configurable thresholds.
- Distinguish `Interrupt agent turn`, `Stop command`, and `Force-kill process tree`.
- Track the complete local descendant process tree. Detached/unattributed processes appear separately with PID and limited controls.
- Sample at 1 Hz normally and up to 4 Hz only while Resource Center is open.

Agent inference is remote; these meters and controls govern Turnpike, app-server, shells, builds, tests, and tool subprocesses—not OpenAI’s model CPU.

### Notifications and recovery

Inbox categories:

- Action required: approvals, user questions, blockers.
- Failures: crashed session, failed command/test, restore failure.
- Completed: root completion and rolled-up child completion.
- Informational: warnings and resource pressure.

Defaults:

- Taskbar badge counts actionable items only.
- Progress is silent.
- Windows notifications appear for actionable events and long-running completion only when Turnpike is unfocused.
- Child completions roll up under their parent to avoid toast storms.
- Clicking a notification restores the exact project, session, checkpoint, module, and pending request.
- No sound by default. Per-project mute, quiet hours, and lock-screen privacy are supported.

Recovery state machine:

```text
Saved → Restoring → Active | Idle | Needs attention | Orphaned | Externally owned
```

Persist atomically:

- Window geometry and pane widths.
- Selected project/session/checkpoint and scroll anchor.
- Expanded modules.
- Drafts and queued prompts.
- Thread IDs and lineage.
- Terminal metadata, not process claims.
- Resource policy and notifications.

Startup rules:

- Show the cached shell immediately and restore sessions asynchronously.
- Never resubmit a `dispatching` prompt or rerun a terminal command after a crash.
- Undispatched queued prompts remain paused until restoration succeeds; auto-continue defaults off.
- An interrupted checkpoint offers `Continue`, `Fork here`, or `Archive`.
- Missing cwd offers `Locate`, `Use current`, or `Archive`; never silently resume in the wrong repo.
- Missing session log becomes Orphaned with options to search/relink or archive.
- Required MCP/auth/model failures become Needs attention with exact remediation.
- If another client owns an active thread, attach read-only and offer an explicit takeover; never double-dispatch.
- Startup ends with a compact result such as `7 restored · 1 needs attention`.

### Navigation, accessibility, and density

Hotkeys, all rebindable:

| Action | Shortcut |
|---|---|
| Quick switch project/session/agent/task/file | `Ctrl+K` |
| Current conversation search | `Ctrl+F` |
| Global search | `Ctrl+Shift+F` |
| Go to checkpoint | `Ctrl+G` |
| Previous/next checkpoint | `Alt+↑ / Alt+↓` |
| Back/forward view history | `Alt+← / Alt+→` |
| Previous/next root session | `Ctrl+PageUp / Ctrl+PageDown` |
| Toggle agent inspector | `Ctrl+Shift+A` |
| Toggle terminal | `Ctrl+\`` |
| Send/queue | `Ctrl+Enter` |
| Steer live turn | `Ctrl+Shift+Enter` |
| Interrupt selected turn | `Ctrl+.` |
| Command palette | `Ctrl+Shift+P` |
| Cycle major regions | `F6 / Shift+F6` |

When a terminal is focused, all chords except terminal toggle, command palette, and F6 pass through unchanged.

Accessibility requirements:

- Compact is default: 13 px body text, 28–32 px rows, minimum 24 px pointer targets.
- Comfortable and Large density presets; usable at 200% Windows scaling.
- WCAG 2.2 AA contrast, visible focus, semantic trees/lists/buttons, and no color-only state.
- Screen readers receive checkpoint/module completion and actionable events, not streaming deltas.
- Reduced motion removes pulses and scrolling animations.
- Pane resizing is keyboard accessible.
- At 200% zoom and 1280×720, overlays replace side panels without hiding the composer or active approval.

### Performance acceptance

Test fixture: 8 active projects, 16 root sessions, 64 child threads, 5,000 checkpoints/100,000 raw events, eight concurrent streams, and eight terminal tabs.

- Window visible: ≤750 ms warm, ≤1.5 s cold on the owner’s workstation.
- Cached workspace interactive: ≤2 seconds while sessions reconnect in the background.
- Warm project/session switch: ≤100 ms p95.
- Loaded checkpoint jump: ≤75 ms; paged jump ≤250 ms.
- Global search first results: ≤250 ms.
- Input-to-paint: ≤50 ms p95.
- Scrolling/streaming: 55–60 fps with no main-thread task over 50 ms.
- Idle app CPU: <0.5% average; resource collection <1%.
- App-owned private memory, excluding agent/terminal descendants: ≤200 MiB with the reference fixture.
- Virtualize transcript, tree, search, and terminal output; cap mounted transcript DOM around 2,000 nodes.
- Batch stream deltas per animation frame and apply backpressure without dropping durable events.
- Keep only bounded terminal scrollback in memory; page older output from disk.
- A forced restart during prompt dispatch, subagent execution, approval, compaction, and terminal output must produce no duplicate prompt or automatic command replay.

### Critical edge cases

- One thread linked from multiple projects: retain one canonical project and show shortcuts elsewhere.
- Parent ends before descendants: move children into a visible Detached Children group.
- Deep subagent nesting: cap visual indentation, retain breadcrumb and full tree semantics.
- Stale approval resolved elsewhere: remove actions and show who/what resolved it.
- Interrupt during file mutation: mark outcome unknown and recommend verification before continuing.
- Branch or cwd changes outside Turnpike: show drift before the next prompt.
- Malformed ANSI/binary output: sanitize transcript rendering while preserving raw bytes in terminal storage.
- Secret-bearing environment/history: never persist environment values; offer private terminal tabs with no saved history.
- Telemetry permission failure: continue operation with unavailable meters.
- Snapshot/database corruption: rebuild navigation from Codex thread listings and Turnpike data, retain the corrupt file for recovery, and show a non-blocking warning.

Current official Codex behavior supports this shape through app-server thread resume/fork/read/list, turn steer/interrupt, status and token events, structured plan/diff/tool/command/collaboration items, and context-compaction markers. Child filtering and process/background-terminal control are partly experimental, so the UI must negotiate capabilities and retain native PTY/process fallbacks.

### Cleaned-up request

Define the interaction architecture for a compact, smooth Turnpike desktop app with project rooms, prompt checkpoints, modular agent activity, explorable subagents, full terminal access, resource controls, navigation, accessibility, notifications, and reliable restart recovery.

### Layman’s recap

Turnpike should feel like Slack for coding agents: every project and prompt is easy to find, noisy work folds into useful modules, subagents remain inspectable and controllable, terminals retain full PowerShell freedom, and all sessions restore safely without overwhelming the PC.
