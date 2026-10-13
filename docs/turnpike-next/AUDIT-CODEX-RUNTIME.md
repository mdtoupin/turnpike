<!-- Provenance: Codex app-server runtime integration audit; codex subagent deliverable 2026-08-11/12,
     a Codex session -->

## Codex runtime recommendation

Use a durable Turnpike Core as the exclusive owner of Codex sessions. For each managed root conversation, Core launches:

```text
codex app-server --stdio
```

and communicates through JSON-RPC over redirected stdin/stdout. Spawned subagents remain inside that root runtime. The Deck UI connects to Core through a local named pipe, so closing the UI does not stop work.

Do not integrate by scraping the TUI, tailing rollout JSONL, reading `state_5.sqlite`, or using WebSockets/remote-control. App-server’s default stdio transport is the narrowest and most reliable rich-client boundary.

### Capability map

Core protocol surface available without `experimentalApi`:

- Discover/history: `thread/list`, `thread/read`.
- Lifecycle: `thread/start`, `thread/resume`, `thread/fork`, naming, pinning, archive/unarchive.
- Work: `turn/start`, `turn/steer`, `turn/interrupt`.
- State: thread status, turn status, plans, diffs, items, approvals, warnings, errors.
- Goals: persisted objective, active/paused/blocked/limited/complete status, token budget, tokens used, and elapsed time.
- Usage: per-thread last/total input, cached-input, output, reasoning, and total tokens plus context-window size.
- Subagent records: `parentThreadId`, `sessionId`, nickname, role, source, and `canAcceptDirectInput`.

Experimental capabilities that should live behind a replaceable adapter:

- `thread/turns/list` and `thread/items/list` history pagination.
- Parent/ancestor server-side filters.
- Background-terminal discovery, CPU/RSS/PID reporting, and termination.
- `process/*`, collaboration-mode discovery, environment APIs, WebSockets, and remote control.

App-server itself remains labeled experimental and unsupported for production workloads, even though it defines a non-experimental protocol subset. Turnpike should therefore pin supported CLI versions, generate bindings from each supported CLI, tolerate unknown event fields, and fail closed to “Open in native Codex CLI” on an incompatible version. This machine currently runs `0.145.0`; its local updater advertises `0.147.0`.

### Thread, checkpoint, and subagent semantics

- `thread.id` is the authoritative resume identifier. Store it in Turnpike; names are display metadata only.
- `thread.sessionId` groups a root/fork tree and must be read rather than derived.
- Map every ordinary user send to `turn/start`, setting a Turnpike UUID in `clientUserMessageId`. The returned Codex turn ID becomes the durable prompt checkpoint.
- `turn/steer` deliberately remains inside the active turn and emits no new turn. Present it as an explicit “Steer current work” sub-checkpoint; otherwise queue text for a new checkpoint.
- Build the subagent tree client-side from `parentThreadId` and explicit subagent `sourceKinds`. Installed schemas expose `collabAgentToolCall`, agent-state transitions, and `subAgentActivity` items.
- Directly steer or interrupt a child only when its loaded thread reports that it accepts direct input. Otherwise route the instruction through its parent.
- Display reasoning summaries, plans, commands, diffs, approvals, and results as modules. Do not imply access to hidden chain-of-thought.
- A `contextCompaction` item marks model-context compaction. Visual folding should remain lossless and separate from model-visible compaction.

“Pause” requires precise controls:

- Goal pause/resume: persisted `thread/goal/*` status.
- Cancel work: `turn/interrupt`; the turn becomes `interrupted`.
- Stop runtime: graceful interrupt followed by app-server shutdown.
- Emergency kill: terminate the runtime Job Object.
- There is no supported arbitrary suspension and continuation of an in-flight model turn.

### PowerShell and resource boundary

Use a real `pwsh.exe` hosted through Windows ConPTY for the terminal drawer. This preserves profiles, environment variables, Ctrl+C, ANSI/full-screen programs, working-directory state, and child processes. Keep it distinct from Codex’s protocol stream and sandbox controls.

Avoid using `thread/shellCommand` as the terminal: it is an explicit full-access, conversation-injected command, not a persistent shell. Avoid experimental `process/*`.

Place each root conversation’s app-server and descendants in a Windows Job Object:

- Meter root-session CPU, working/private memory, I/O, process count, and uptime.
- Aggregate all session jobs under a global pressure guard.
- Allow elastic bursts; use scheduler admission, weights, pressure hysteresis, and global reserve before hard limits.
- Do not claim exact per-subagent CPU/RAM. Subagents are logical threads inside the same runtime, and ordinary command events expose no reliable OS PID. Show exact runtime totals and exact per-thread token/context/activity metrics.
- Keep user PowerShell terminals in separately metered jobs so the user retains a recovery shell even if an agent runtime is throttled or stopped.

A freshly initialized app-server measured about 20 MB private memory and 85 MB working set here, making one runtime per active root conversation reasonable. It also provides failure isolation and honest root-session metering.

### Recovery and performance

Turnpike cannot attach app-server controls to currently running standalone Codex TUIs. A separate app-server listed those sessions as `notLoaded`, even while they were active elsewhere. Existing windows need an adoption flow:

1. Register the current session from inside its shell using `CODEX_THREAD_ID`.
2. Bind that ID to the Turnpike project.
3. Finish or stop the existing TUI.
4. Resume it under a Turnpike-owned runtime.

Never allow two processes to write the same thread.

On reboot:

- Restore project/session cards immediately from Turnpike’s materialized read model.
- Restart runtimes lazily or according to the user’s restore policy.
- Call `thread/resume` with the saved ID; never replay the last prompt automatically because its tools may already have caused side effects.
- If no terminal event was persisted, label the checkpoint “interrupted by restart” and offer a new “Continue from here” turn.
- Do not blindly retry `turn/start` after a broken pipe; first inspect persisted history to determine whether the server accepted it.

For a liquid interface:

- Continuously drain app-server stdout independently of UI/database work.
- Coalesce deltas into item snapshots; never drop approvals, failures, or completion events.
- Persist compact final modules and bounded/compressed command logs rather than every rendering delta.
- Use virtualized lists and keyset pagination.
- Use `thread/list(useStateDbOnly: true)` for fast discovery and defer scan-and-repair.
- Use experimental summarized turn pagination for legacy import behind the adapter; prospectively build Turnpike’s own read model from live events.

This matters on the current installation: it contains 222 active and 952 archived rollout files, some around 128 MB, plus roughly 1.5 GB of Codex logs. A stable `thread/read(includeTurns: true)` of every conversation at startup would not be smooth.

Official references: [Codex App Server](https://learn.chatgpt.com/docs/app-server.md), [Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents.md), and [Long-running work](https://learn.chatgpt.com/docs/long-running-work.md).

### Cleaned-up request

Research the safest and most efficient way for Turnpike to discover, resume, monitor, control, and display Codex CLI conversations and subagents, including recovery, resource metering, and full PowerShell access.

### Layman’s recap

Turnpike should own each Codex conversation through Codex’s structured app-server interface, while hosting a genuine PowerShell terminal separately. Conversations survive as saved IDs, prompts become checkpoints, subagents become expandable threads, and Windows process groups provide honest resource meters and safe shutdown controls.
