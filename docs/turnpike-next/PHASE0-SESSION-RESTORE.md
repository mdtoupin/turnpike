# Phase 0: session restore (shipped 2026-08-12)

The stopgap from PLAN.md amendment [F1]. It solves the original problem, "my PC restarts and
I lose eight agent windows", using the existing Python CLI, with no new runtime and no UI.
The full application replaces it later; these bindings import into Phase 2 as first-class
sessions.

## For you (the human)

After a reboot:

```bash
turnpike restore
```

One Windows Terminal window opens with a tab per session, each reattached to its own
conversation in its own directory. Useful flags:

- `--dry-run` shows exactly what would open and changes nothing.
- `--project <slug>` restores one project.
- `--all` includes bindings whose task is not currently `doing`/`blocked`.

To see what is bound: `turnpike sessions` (add `--all` for dormant, `--json` for scripting).
To drop one: `turnpike session-forget <binding-id>`.

## For agents

One command, right after claiming a task, from inside your own session:

```bash
turnpike session-bind <project> --as <you> --task <id>
```

With no `--session-id` it detects the provider and conversation id from your environment and
records your current directory. Re-running it updates the binding instead of duplicating it.
This is now step 2 of the loop in PROTOCOL.md.

## Design notes

- **One provider registry.** `PROVIDERS` in `turnpike.py` is the single owner of
  provider-specific facts: which environment variable carries the conversation id, and what
  argv reattaches to it. Everything else, including all four commands, is provider-agnostic;
  supporting another agent CLI is one dictionary entry, not a new code path.
- **Additive schema.** One `session_bindings` table created by the existing
  `CREATE TABLE IF NOT EXISTS` bootstrap, unique on (provider, thread_id). No existing table,
  command, output shape, or id changed. Verified by running the legacy commands against a
  copy of the live database.
- **Dormancy at the choke point.** Bindings follow their task's status from inside
  `task-update`, the one place task state changes, rather than from a separate sweep.

## What the running-session check can and cannot see

`restore` skips sessions that already have a window, by scanning process command lines for
the conversation id. Be aware of the boundary, which was measured, not assumed:

- **Seen:** any window started by a resume command (`codex resume <id>`,
  `claude --resume <id>`), because the id is on its command line. This is the case that
  matters: running `restore` twice never double-opens a session it opened.
- **Not seen:** a session started fresh, whose id exists only in its environment. A live
  `claude.exe` command line carries `--output-format stream-json ...` and no session id, so
  it reads as not-running and `restore --all` could open a second window for it. Never open
  the same conversation twice on purpose; both windows write one transcript.
- **Unknown:** if the process table cannot be read, nothing is skipped rather than
  pretending nothing is running.

Turnpike's own processes are excluded from the scan, because `session-bind --session-id <id>`
puts that id on its own command line and would otherwise look like a live session.

## Verified

- Auto-detect bind from inside a live Claude session; explicit bind with `--session-id`.
- Running-detection true negative and true positive (a control process carrying a bound id
  flipped the flag), and the self-reference false positive is gone.
- `restore --dry-run` plan, skip-already-running, dedupe, and missing-cwd fallback to the
  project workdir.
- End-to-end launch: Windows Terminal opened with the titled tab, in the right directory,
  running the resume command, with the provider CLI actually starting.
- Task done marks the binding dormant; reopening the task reactivates it.
- All legacy commands and `--json` shapes unchanged on a copy of the live database.
