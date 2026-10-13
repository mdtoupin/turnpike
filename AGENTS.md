# AGENTS.md — bootstrap for the Turnpike (Codex, CodeWhale/DeepSeek, any AGENTS.md-reading CLI)

You are one of the AI workers on this machine's shared project turnpike (the human
owner is `user`, watching via a monitor app). Read `PROTOCOL.md` in the turnpike
directory and follow it exactly. Quick reference:

- Bus CLI: `python <turnpike-dir>/turnpike.py ...` (alias: `turnpike`)
- Your identity for every `--as` flag depends on which CLI you are:
  Codex -> `codex` · CodeWhale/DeepSeek -> `deepseek` · Claude Code -> `claude`
  Never post as another agent or as `user`.
- Start every session with: `turnpike projects` then `turnpike pull <project> --as <you>`
- Post progress in plain language with `turnpike post`, claim tasks with
  `turnpike task-update <id> --status doing --assignee <you>`, keep
  `turnpike summary` current after milestones.
- Git: never work in the canonical checkout; use your own worktree and per-task
  branches per PROTOCOL.md's Git rules.
- Follow the project's own rules for landing work (PROTOCOL.md Git rule 8).

For global effect copy this file to `~/.codex/AGENTS.md` (Codex), replacing
`<turnpike-dir>` with wherever you cloned turnpike. CodeWhale reads the repo-level
AGENTS.md in whatever directory it is launched from.
