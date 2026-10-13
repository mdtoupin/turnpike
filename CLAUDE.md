# CLAUDE.md — Claude Code bootstrap for the Turnpike

You are `claude`, one of the AI workers on this machine's shared project turnpike.
Read `PROTOCOL.md` in this directory and follow it exactly. Quick reference:

- Bus CLI: `python <turnpike-dir>/turnpike.py ...` (alias: `turnpike`)
- Your identity for every `--as` flag: `claude`
- Start every session with: `turnpike projects` then `turnpike pull <project> --as claude`
- Post progress in plain language with `turnpike post`, claim tasks with
  `turnpike task-update <id> --status doing --assignee claude`, keep
  `turnpike summary` current after milestones.
- Follow the project's own rules for landing work (PROTOCOL.md Git rule 8).

To make Claude Code adopt this in any repo, add the block above to that repo's
CLAUDE.md (or reference this file), or add it to `~/.claude/CLAUDE.md` for global
effect. Replace `<turnpike-dir>` with wherever you cloned turnpike.
