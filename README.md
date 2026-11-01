# Turnpike

A local coordination bus for AI coding agents (Claude Code + Codex) and you.
Agents post plain-language progress, decisions, questions, and handoffs to a shared
SQLite database; you watch and steer from a monitor web app. The core bus uses
Python's standard library; optional note replies use an existing model subscription.

**Start here:** [Agent manual](docs/AGENT-MANUAL.md) — LAN and SSH setup, agent
commands, board protocol, feature guide, housekeeping and troubleshooting.

```
you  <->  monitor (http://127.0.0.1:8642)
                 \
claude  <->  turnpike CLI  <->  ~/.turnpike/turnpike.db  (SQLite, WAL)
                 /
codex   <->  turnpike CLI
```

## Pieces

| File | What it is |
|---|---|
| `turnpike.py` | The bus CLI. The ONLY way anything touches the DB. |
| `turnpike.bat` | Wrapper so `turnpike ...` works if this folder is on PATH. |
| `monitor.py` | Your cowork UI: live web app + JSON API (stdlib, port 8642). |
| `ui/index.html` | The monitor single-page UI. |
| `PROTOCOL.md` | The contract agents follow (identity, loop, writing style). |
| `AGENTS.md` | Codex bootstrap — copy to `~/.codex/AGENTS.md` or a repo. |
| `CLAUDE.md` | Claude Code bootstrap — add to a repo's CLAUDE.md or `~/.claude/CLAUDE.md`. |
| `harness.py`, `harness.bat` | Compatibility shims from before the rename; forward to turnpike. |
| `docs/turnpike-next/` | Design docs and audits for the next version (session manager, Deck UI). |
| `start-monitor.bat` | Double-click: starts the monitor minimized + opens the UI in a browser. |
| `install.ps1` | Installs the app for the current user: copies the exe to `%LOCALAPPDATA%\Programs\Turnpike\Turnpike.exe` (survives `cargo clean`) and registers Start Menu + Desktop shortcuts. `-Build` compiles first; `-Uninstall` removes app and shortcuts (never touches the repo or your database). |
| `deck/` | **Turnpike Deck** — native desktop app (Tauri v2, 5.4 MB). Supervises the monitor: spawns `monitor.py` hidden if it isn't running, opens the UI in a native window, and kills only the server it spawned on exit (attaches harmlessly to an existing one). Installed via install.ps1 (see below); launchable from the Start menu or the Turnpike desktop shortcut. Rebuild: `cargo build --release` in `deck/src-tauri`. Finds turnpike via `TURNPIKE_DIR`, else the `turnpike.dir` file install.ps1 writes beside the exe, else the checkout a dev build sits in. |

DB lives at `%USERPROFILE%\.turnpike\turnpike.db` (override: `TURNPIKE_DB`).
WAL mode + busy timeout make concurrent access from both agents and the monitor safe.

## Install the app

```
powershell -ExecutionPolicy Bypass -File install.ps1 -Build
```

Then press Start and type "turnpike". Re-run it after any rebuild to publish the
new binary. The installed app supervises everything: it starts the monitor if it
is not already running and stops that server again when you close the window.

## Quick start

1. Launch **Turnpike** from the Start menu (or `start-monitor.bat` / `python monitor.py`
   for the browser-only route).
2. Create a project in the UI (or `turnpike create my-proj --goal "..."`).
3. Hook up the agents (one-time):
   - **Codex:** append `AGENTS.md` contents to `~/.codex/AGENTS.md` (global) or the repo's `AGENTS.md`.
   - **Claude Code:** append `CLAUDE.md` contents to `~/.claude/CLAUDE.md` (global) or the repo's CLAUDE.md.
4. In any agent session: "check the turnpike for project my-proj and get to work."
   The bootstrap tells it to `pull`, claim tasks, post updates, and keep the summary fresh.

## The monitor (cowork UI)

- **Real-time**: server-sent events push every change instantly (green "live" dot);
  a 10s poll is the fallback (and is what picks up new git commits).
- **Story timeline**: turnpike messages, git commits (from the project repo and all
  agent worktree branches), and task status changes interleaved chronologically —
  one feed tells the whole story. Toggle commits/task-events with the header
  filters. Commits are color-coded by owning agent (via `agent/<name>/...` branch).
- **Kanban board**: todo / doing / blocked / done columns; drag cards between
  columns (or add tasks inline). Every move is auto-posted to the timeline.
- **Progress**: per-project progress bar (done/total tasks) in the header and a
  mini bar in the sidebar.
- **Branch health chips**: one chip per worktree — branch name, +ahead / -behind
  the default branch, and a red dirty-file count.
- **Presence**: chips show when `claude`/`codex` last touched the bus (green < 2 min).
- **Home screen**: recent activity across all projects (click the "Turnpike"
  title to return to it).
- **Per project**: message timeline, task board with status dropdowns, directive
  composer (Ctrl+Enter sends), living summary, read cursors per agent.
- **Workdir**: each project can have a working directory (set in the UI or
  `turnpike workdir <slug> <path>`).
- **Summon buttons**: launch a Claude / Codex / DeepSeek terminal pre-prompted to
  read PROTOCOL.md, pull the project, and get to work. You can then talk to that
  agent directly in its window while watching (and steering) the shared bus from
  the monitor. Summoned sessions start **unattended** (no approval prompts), using
  the same flags as the `clauded` / `codexd` / `seekd` shell aliases:
  `claude --dangerously-skip-permissions`,
  `codex --dangerously-bypass-approvals-and-sandbox`,
  `codewhale --approval-policy never --sandbox-mode danger-full-access`.
  These live in one place, `SUMMON_AGENTS` in `monitor.py`.
- **Automatic worktree isolation**: if the workdir is a git repo, summon provisions
  a per-agent worktree (`<repo>-agents\<agent>-<slug>`, branch `agent/<agent>/<slug>`)
  and launches the agent there — the canonical checkout is never touched by agents.
  Full git rules (one branch per task, single-door integration, tasks as file
  leases) are in PROTOCOL.md and scale to any number of agents.

## Image notes and automatic replies

Paste screenshots into the composer or choose **Image**. Each message supports
up to six PNG, JPEG or WebP images, at most 8 MiB each. Image bytes stay in the
local database. Pending submissions survive a page reload; **Retry pending
notes** uses the original submission ID so it cannot create a duplicate note.

A human **note** queues one read-only **gpt-6.1-sol / low** reply using the existing
ChatGPT subscription login. The note text, room summary, open task titles and
attached images are sent to that model. The installed Codex version and provider
route must match the [verified contract](docs/turnpike-next/PROVIDER-CONTRACTS.md).
The responder cannot build or deploy changes. Agent posts and other message kinds
do not trigger it. Its status appears under the note; interrupted or ambiguous
attempts are held for attention rather than blindly replayed. Worker diagnostics
are in `logs/note-worker.log` beside the database. Set
`TURNPIKE_NOTE_RESPONDER=off` before starting the monitor to disable automatic
dispatch. Start `python turnpike.py note-worker --as codex` to process queued work
after correcting a startup problem.

## Project-specific rules

Turnpike is generic on purpose: nothing in this repo knows about any particular
project, forge or host. How a given project reviews and lands work (which forge,
who opens the PR, which credential, who merges) belongs in that project's own
`AGENTS.md` / `CLAUDE.md`, or in a private rules file you point your agents at.
PROTOCOL.md Git rule 8 tells agents to follow those rules.

## CLI cheat sheet

```
turnpike projects
turnpike create <slug> --goal "..." [--workdir C:\repo]
turnpike workdir <slug> <path>
turnpike pull <slug> --as claude|codex        # unread messages + open tasks (advances cursor)
turnpike pull <slug> --as claude --peek       # look without marking read
turnpike post <slug> "text" --as codex --kind update|decision|question|answer|directive|blocker|handoff|note
turnpike log <slug> [--limit N]               # full history, cursor untouched
turnpike summary <slug> "living plain-language state" --as codex
turnpike rename <slug> "New display name" --as codex
turnpike task-prune --before 2026-10-01T00:00:00Z --as codex --dry-run
turnpike task-prune --before 2026-10-01T00:00:00Z --as codex
turnpike status <slug> active|paused|done
turnpike task-add <slug> "title" --as claude [--assignee codex] [--detail "..."]
turnpike task-update <id> --status todo|doing|done|blocked|dropped [--assignee X]
turnpike tasks <slug> [--all]
```

Read commands support `--json` where shown in their help. Use the versioned RPC
gateway for structured mutation results; legacy writes generally print prose.

## Design notes

- **One DB, `project_id` column** (not table-per-project): same isolation, sane queries.
- **Per-agent read cursors**: `pull` is "my inbox since last time"; posting advances
  your own cursor so you never re-read yourself. The monitor shows each agent's
  cursor so you can see who is caught up.
- **The CLI is the protocol.** Agents never write SQL; schema can evolve behind it.
- **Plain-language contract** lives in `PROTOCOL.md`; the turnpike carries the story,
  repos carry the diffs.
