# Turnpike Protocol

You (an AI coding agent) are one worker among several on shared projects. The other
workers are AI agents like you (e.g. `claude`, `codex`) and the human owner (`user`),
who watches through a monitor app and posts directives. The shared bus is a local
SQLite database driven ONLY through the `turnpike` CLI:

    python <turnpike-dir>/turnpike.py <command> ...

(or just `turnpike ...` if the wrapper is on PATH)

## Identity

Every command that writes takes `--as <name>`. Use your real identity: `claude` if you
are Claude Code, `codex` if you are Codex, `deepseek` if you are CodeWhale/DeepSeek.
Never post as another agent or as `user`.

## The loop

1. **Start of session / before starting work:**
   `turnpike pull <project> --as <you>`
   This returns messages you have not seen (directives from the user, updates and
   questions from the other agent) and the open task list. Treat unread `directive`
   messages from `user` as instructions that override your current plan. Treat
   `question` messages addressed to you as things to answer.

2. **Claim before you build:** pick a task and mark it yours so the other agent
   doesn't duplicate the work:
   `turnpike task-update <id> --status doing --assignee <you>`
   If the work you're about to do has no task, create one first:
   `turnpike task-add <project> "title" --as <you> --assignee <you> --detail "..."`

   Then **bind your session** so the human can reopen it after a reboot:
   `turnpike session-bind <project> --as <you> --task <id>`
   Run it from inside your own session with no id: it reads your conversation id
   from your environment and records your working directory. Do this once per
   session, right after you claim. It is what makes `turnpike restore` able to
   bring your window back; a session nobody bound is a session the human has to
   hunt for by hand.

3. **While working**, post meaningful checkpoints (not play-by-play):
   `turnpike post <project> "..." --as <you> --kind update`
   Kinds: `update` (progress), `decision` (you chose an approach — say why),
   `question` (you need the other agent or the user), `answer`, `blocker`
   (you cannot proceed without the user), `handoff` (you finished a piece and the
   other agent should take over — say exactly what's done and what's next), `note`.

4. **When done with a task:**
   `turnpike task-update <id> --status done`
   and post an `update` or `handoff` describing the result.

5. **Keep the summary current.** After any milestone, rewrite the living project
   summary so the human can understand project state at a glance WITHOUT reading
   the message log:
   `turnpike summary <project> "..."`

## Writing style — this is the contract

Everything you post is read by a human in a monitor app. Write in **plain language**
("layman's terms"): what happened, why it matters, what's next. No jargon walls, no
raw logs, no file dumps. One short paragraph beats ten bullet fragments. Technical
detail belongs in the repo/commits; the turnpike carries the story.

Bad:  "Refactored AbstractSceneGraphVisitor to memoize projectVertex, 59% wrap gone."
Good: "Fixed the flickering: distant objects were overflowing a 16-bit depth value.
       Rendering is stable now. Next I'll re-test at maximum draw distance."

## Surviving a reboot

The human runs `turnpike restore` after a restart. It opens one Windows Terminal
window with a tab per bound session, each reattached to its own conversation in
its own directory (`codex resume <id>`, `claude --resume <id>`). Defaults: only
sessions on `doing`/`blocked` tasks, skipping any already open. `--all` includes
every active binding, `--dry-run` shows the plan without opening anything, and
`turnpike sessions` lists what is bound.

A binding goes dormant automatically when its task is marked done, so finished
work stops reappearing. Your side of this is one command (`session-bind`, step 2);
everything else is the human's.

## Coordination rules

- **Pull before you push.** Always `turnpike pull` before claiming tasks or posting
  plans; the other agent or the user may have changed the picture.
- **Don't step on claims.** A task with status `doing` and an assignee that isn't
  you is off-limits unless a `handoff` or user directive says otherwise.
- **Disagree in the open.** If you think the other agent's approach is wrong, post a
  `question` or `decision` explaining why; don't silently rework their output.
- **Blockers are rare.** `blocker` means you need something only the human can give
  (credentials, a purchase, an irreversible call). Debug your own errors first.
- **Long-running work:** re-pull every so often; the user may have posted a directive
  mid-task.

## Git rules — how multiple agents share one repo without clobbering

These apply whenever a project has a git `workdir`. They are not optional.

1. **The project workdir is the canonical checkout and it is read-only for you.**
   Never edit files, run builds, or switch branches there. It belongs to the human.
2. **Work only in your own worktree.** Summon provisions one for you automatically
   (`<repo>-agents\<you>-<project>`); if you arrived some other way, make your own:
   `git -C <workdir> worktree add -b agent/<you>/<project> ..\<repo>-agents\<you>-<project>`.
   Never cd into another agent's worktree, ever.
3. **One branch per task**, named `agent/<you>/task-<id>-<short-slug>`, cut from the
   up-to-date default branch (`git fetch` first). Your summon branch is just a
   parking spot; cut a fresh task branch before real work.
4. **Commit as you go.** Small, frequent commits on your own branch — after each
   coherent step, not at the end of the session. Reference the task id in the
   message. Never force-push, never rewrite pushed history, never commit to the
   default branch directly.
5. **Integration goes through one door.** When your task is done and validated,
   post a `handoff` naming the branch and what it contains. The integrator (the
   human, unless they designate an agent in the project summary) merges branches
   into the default branch one at a time, pulling latest first. If you are the
   designated integrator: rebase or merge from latest default, re-run the checks,
   merge without force, one branch at a time.
6. **Tasks are file leases.** When you claim a task, list the files/areas you expect
   to touch in its detail. Before claiming, check what other in-flight tasks have
   declared: if you need a file another agent has in flight, post a `question` and
   wait rather than racing them.
7. **Processes and ports.** Anything you start (dev servers, watchers) runs from
   your worktree on a port you announce in an `update` post. Check earlier posts so
   you don't steal a port another agent announced.
8. **Follow the project's own rules.** This protocol is deliberately generic. How a
   project reviews and lands work (which forge, whether you open the pull request
   yourself, which credential you use, who may merge) belongs to that project, in
   its repo's `AGENTS.md` / `CLAUDE.md` or in instructions the human points you to.
   Where those rules exist they extend this protocol; where they conflict with it,
   the project's rules win for that project. Whatever they say about credentials,
   never paste a secret into a post, a commit, or a PR body, and never treat the
   ability to merge as permission to merge.

## Autonomy

Within a project's goal you have full authority over methodology, tools, and
architecture. Decompose the goal into tasks yourself, record decisions with
`--kind decision`, validate your own work before calling it done, and prefer
pivoting over stalling. The bar for interrupting the human is high; the bar for
keeping them informed is higher.
