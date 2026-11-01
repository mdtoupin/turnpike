#!/usr/bin/env python3
"""turnpike - shared project bus for AI agents (Claude Code, Codex, DeepSeek) and the human monitor.

All state lives in one SQLite database (WAL mode, safe for concurrent CLIs).
Agents never touch SQL directly; this CLI is the only protocol surface.

DB location: %USERPROFILE%/.turnpike/turnpike.db  (override with TURNPIKE_DB;
legacy %USERPROFILE%/.agent-harness/harness.db is used if it still exists)
"""

import argparse
import json
import os
import sqlite3
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path


def _default_db() -> Path:
    env = os.environ.get("TURNPIKE_DB") or os.environ.get("AGENT_HARNESS_DB")
    if env:
        return Path(env)
    new = Path.home() / ".turnpike" / "turnpike.db"
    legacy = Path.home() / ".agent-harness" / "harness.db"
    if not new.exists() and legacy.exists():
        return legacy
    return new


DB_PATH = _default_db()

MESSAGE_KINDS = ("update", "decision", "question", "answer", "directive",
                 "blocker", "handoff", "note", "task")
TASK_STATUSES = ("todo", "doing", "done", "blocked", "dropped")
SESSION_STATUSES = ("active", "dormant")

# The single owner of provider-specific facts. Everything else in this file is
# provider-agnostic: to support a new agent CLI, add one entry here.
#   env    : environment variables a live session of that CLI exports its id in
#   resume : argv that reattaches to a saved conversation
PROVIDERS = {
    "codex": {
        "env": ("CODEX_THREAD_ID",),
        "resume": lambda tid: ["codex", "resume", tid],
    },
    "claude": {
        "env": ("CLAUDE_CODE_SESSION_ID",),
        "resume": lambda tid: ["claude", "--resume", tid],
    },
    "codewhale": {
        "env": ("CODEWHALE_SESSION_ID",),
        "resume": lambda tid: ["codewhale", "resume", tid],
    },
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id         INTEGER PRIMARY KEY,
    slug       TEXT NOT NULL UNIQUE,
    name       TEXT NOT NULL,
    goal       TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'active',   -- active | paused | done | archived
    summary    TEXT NOT NULL DEFAULT '',          -- living layman's-terms state of the project
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    author     TEXT NOT NULL,                     -- claude | codex | user | <anything>
    kind       TEXT NOT NULL DEFAULT 'update',
    body       TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_project ON messages(project_id, id);
CREATE TABLE IF NOT EXISTS tasks (
    id         INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    title      TEXT NOT NULL,
    detail     TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'todo',
    assignee   TEXT NOT NULL DEFAULT '',          -- '' = unclaimed
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id, status);
CREATE TABLE IF NOT EXISTS cursors (
    agent      TEXT NOT NULL,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    last_msg_id INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (agent, project_id)
);
CREATE TABLE IF NOT EXISTS agents (
    name      TEXT PRIMARY KEY,
    last_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS session_bindings (
    id         INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    provider   TEXT NOT NULL,                     -- key into PROVIDERS
    thread_id  TEXT NOT NULL,                     -- the provider's own conversation id
    agent      TEXT NOT NULL DEFAULT '',
    task_id    INTEGER,                           -- optional: the task this session is working
    cwd        TEXT NOT NULL DEFAULT '',
    title      TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'active',    -- active | dormant
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (provider, thread_id)
);
CREATE INDEX IF NOT EXISTS idx_bindings_project ON session_bindings(project_id, status);
"""


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=15000")
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SCHEMA)
    cols = [r[1] for r in con.execute("PRAGMA table_info(projects)")]
    if "workdir" not in cols:
        con.execute("ALTER TABLE projects ADD COLUMN workdir TEXT NOT NULL DEFAULT ''")
        con.commit()
    return con


def get_project(con, slug: str) -> sqlite3.Row:
    row = con.execute("SELECT * FROM projects WHERE slug=?", (slug,)).fetchone()
    if row is None:
        slugs = [r["slug"] for r in con.execute("SELECT slug FROM projects")]
        sys.exit(f"error: no project '{slug}'. Existing: {', '.join(slugs) or '(none)'}")
    return row


def touch_project(con, project_id: int):
    con.execute("UPDATE projects SET updated_at=? WHERE id=?", (now(), project_id))


def post_task_event(con, project_id: int, author: str, body: str):
    """Task lifecycle beats become timeline messages (kind='task')."""
    cur = con.execute(
        "INSERT INTO messages (project_id, author, kind, body, created_at) VALUES (?,?,?,?,?)",
        (project_id, author, "task", body, now()))
    con.execute("""
        INSERT INTO cursors (agent, project_id, last_msg_id) VALUES (?,?,?)
        ON CONFLICT(agent, project_id) DO UPDATE SET last_msg_id=MAX(last_msg_id, excluded.last_msg_id)""",
        (author, project_id, cur.lastrowid))


def apply_task_status(con, task_id: int, status: str):
    """Everything that must follow a task changing status, for every caller.

    The CLI and the monitor both move tasks; this is the one place that owns the
    consequences, so a task finished in the web UI behaves exactly like one
    finished from the command line. Callers still write tasks.status themselves.
    """
    if status in ("done", "dropped"):
        con.execute("UPDATE session_bindings SET status='dormant', updated_at=? WHERE task_id=?",
                    (now(), task_id))
    elif status in ("todo", "doing", "blocked"):
        con.execute("UPDATE session_bindings SET status='active', updated_at=? WHERE task_id=?",
                    (now(), task_id))


def emit(data, as_json: bool, text: str = None):
    if as_json:
        print(json.dumps(data, indent=2))
    elif text is not None:
        print(text)


# ---------------------------------------------------------------- commands

def cmd_create(a):
    con = connect()
    ts = now()
    try:
        con.execute(
            "INSERT INTO projects (slug, name, goal, workdir, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (a.slug, a.name or a.slug, a.goal, a.workdir, ts, ts))
    except sqlite3.IntegrityError:
        sys.exit(f"error: project '{a.slug}' already exists")
    con.commit()
    print(f"created project '{a.slug}'")


def cmd_projects(a):
    con = connect()
    rows = con.execute("""
        SELECT p.*,
               (SELECT COUNT(*) FROM tasks t WHERE t.project_id=p.id AND t.status IN ('todo','doing','blocked')) AS open_tasks,
               (SELECT MAX(id) FROM messages m WHERE m.project_id=p.id) AS last_msg_id
        FROM projects p ORDER BY p.updated_at DESC""").fetchall()
    data = [dict(r) for r in rows]
    if a.json:
        emit(data, True)
        return
    if not rows:
        print("no projects yet. create one: turnpike create <slug> --goal \"...\"")
        return
    for r in rows:
        print(f"{r['slug']:<24} [{r['status']}] open tasks: {r['open_tasks']:<3} updated {r['updated_at']}  - {r['goal'][:70]}")


def cmd_post(a):
    con = connect()
    p = get_project(con, a.project)
    body = a.body if a.body != "-" else sys.stdin.read().strip()
    if not body:
        sys.exit("error: empty message body")
    cur = con.execute(
        "INSERT INTO messages (project_id, author, kind, body, created_at) VALUES (?,?,?,?,?)",
        (p["id"], a.author, a.kind, body, now()))
    # posting also advances your own cursor so you don't re-read yourself
    con.execute("""
        INSERT INTO cursors (agent, project_id, last_msg_id) VALUES (?,?,?)
        ON CONFLICT(agent, project_id) DO UPDATE SET last_msg_id=MAX(last_msg_id, excluded.last_msg_id)""",
        (a.author, p["id"], cur.lastrowid))
    touch_project(con, p["id"])
    con.commit()
    print(f"posted #{cur.lastrowid} ({a.kind}) to '{a.project}' as {a.author}")


def cmd_pull(a):
    """New messages since this agent's cursor, plus current open tasks."""
    con = connect()
    p = get_project(con, a.project)
    row = con.execute("SELECT last_msg_id FROM cursors WHERE agent=? AND project_id=?",
                      (a.author, p["id"])).fetchone()
    since = row["last_msg_id"] if row else 0
    msgs = con.execute(
        "SELECT * FROM messages WHERE project_id=? AND id>? ORDER BY id",
        (p["id"], since)).fetchall()
    tasks = con.execute(
        "SELECT * FROM tasks WHERE project_id=? AND status IN ('todo','doing','blocked') ORDER BY id",
        (p["id"],)).fetchall()
    if msgs and not a.peek:
        con.execute("""
            INSERT INTO cursors (agent, project_id, last_msg_id) VALUES (?,?,?)
            ON CONFLICT(agent, project_id) DO UPDATE SET last_msg_id=excluded.last_msg_id""",
            (a.author, p["id"], msgs[-1]["id"]))
        con.commit()
    data = {"project": dict(p), "new_messages": [dict(m) for m in msgs],
            "open_tasks": [dict(t) for t in tasks]}
    if a.json:
        emit(data, True)
        return
    print(f"== {p['slug']} [{p['status']}] ==\ngoal: {p['goal']}")
    if p["workdir"]:
        print(f"workdir: {p['workdir']}")
    if p["summary"]:
        print(f"summary: {p['summary']}")
    print(f"\n-- new messages for {a.author}: {len(msgs)} --")
    for m in msgs:
        print(f"#{m['id']} {m['created_at']} [{m['kind']}] {m['author']}:")
        print(textwrap.indent(m["body"], "    "))
    print(f"\n-- open tasks: {len(tasks)} --")
    for t in tasks:
        who = t["assignee"] or "unclaimed"
        print(f"#{t['id']} [{t['status']}] ({who}) {t['title']}")
        if t["detail"]:
            print(textwrap.indent(t["detail"], "    "))


def cmd_log(a):
    con = connect()
    p = get_project(con, a.project)
    msgs = con.execute(
        "SELECT * FROM messages WHERE project_id=? ORDER BY id DESC LIMIT ?",
        (p["id"], a.limit)).fetchall()[::-1]
    if a.json:
        emit([dict(m) for m in msgs], True)
        return
    for m in msgs:
        print(f"#{m['id']} {m['created_at']} [{m['kind']}] {m['author']}:")
        print(textwrap.indent(m["body"], "    "))


def cmd_summary(a):
    con = connect()
    p = get_project(con, a.project)
    text = a.text if a.text != "-" else sys.stdin.read().strip()
    con.execute("UPDATE projects SET summary=?, updated_at=? WHERE id=?",
                (text, now(), p["id"]))
    con.commit()
    print(f"summary updated for '{a.project}'")


def cmd_workdir(a):
    con = connect()
    p = get_project(con, a.project)
    con.execute("UPDATE projects SET workdir=?, updated_at=? WHERE id=?",
                (a.path, now(), p["id"]))
    con.commit()
    print(f"workdir for '{a.project}' -> {a.path}")


def cmd_project_status(a):
    con = connect()
    p = get_project(con, a.project)
    con.execute("UPDATE projects SET status=?, updated_at=? WHERE id=?",
                (a.status, now(), p["id"]))
    con.commit()
    print(f"'{a.project}' -> {a.status}")


def cmd_task_add(a):
    con = connect()
    p = get_project(con, a.project)
    ts = now()
    cur = con.execute("""
        INSERT INTO tasks (project_id, title, detail, assignee, created_by, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?)""",
        (p["id"], a.title, a.detail, a.assignee, a.author, ts, ts))
    post_task_event(con, p["id"], a.author,
                    f"created task #{cur.lastrowid} \"{a.title}\""
                    + (f" (assigned to {a.assignee})" if a.assignee else ""))
    touch_project(con, p["id"])
    con.commit()
    print(f"task #{cur.lastrowid} added to '{a.project}'")


def cmd_task_update(a):
    con = connect()
    t = con.execute("SELECT * FROM tasks WHERE id=?", (a.id,)).fetchone()
    if t is None:
        sys.exit(f"error: no task #{a.id}")
    fields, vals = [], []
    if a.status:
        if a.status not in TASK_STATUSES:
            sys.exit(f"error: status must be one of {TASK_STATUSES}")
        fields.append("status=?"); vals.append(a.status)
    if a.assignee is not None:
        fields.append("assignee=?"); vals.append(a.assignee)
    if a.detail is not None:
        fields.append("detail=?"); vals.append(a.detail)
    if not fields:
        sys.exit("error: nothing to update (use --status/--assignee/--detail)")
    fields.append("updated_at=?"); vals.append(now())
    vals.append(a.id)
    con.execute(f"UPDATE tasks SET {', '.join(fields)} WHERE id=?", vals)
    changes = []
    if a.status and a.status != t["status"]:
        changes.append(f"{t['status']} -> {a.status}")
    if a.assignee is not None and a.assignee != t["assignee"]:
        changes.append(f"assignee -> {a.assignee or 'unclaimed'}")
    if changes:
        author = a.author or a.assignee or t["assignee"] or "user"
        post_task_event(con, t["project_id"], author,
                        f"task #{a.id} \"{t['title']}\": " + ", ".join(changes))
    if a.status:
        apply_task_status(con, a.id, a.status)
    touch_project(con, t["project_id"])
    con.commit()
    print(f"task #{a.id} updated")


def cmd_tasks(a):
    con = connect()
    p = get_project(con, a.project)
    q = "SELECT * FROM tasks WHERE project_id=?"
    vals = [p["id"]]
    if not a.all:
        q += " AND status IN ('todo','doing','blocked')"
    rows = con.execute(q + " ORDER BY id", vals).fetchall()
    if a.json:
        emit([dict(r) for r in rows], True)
        return
    for t in rows:
        who = t["assignee"] or "unclaimed"
        print(f"#{t['id']} [{t['status']}] ({who}) {t['title']}")
        if t["detail"]:
            print(textwrap.indent(t["detail"], "    "))


# ------------------------------------------------- sessions (reboot restore)

def detect_session() -> tuple:
    """Which provider am I running inside, and what is this conversation's id?"""
    for name, spec in PROVIDERS.items():
        for var in spec["env"]:
            tid = os.environ.get(var)
            if tid:
                return name, tid
    return None, None


def live_command_lines():
    """Command lines of running processes, minus turnpike's own.

    Restore uses this to avoid reopening a conversation that already has a window.
    What it can see: a window started as `codex resume <id>` / `claude --resume <id>`
    carries the id on its command line, so re-running restore never double-opens one.
    What it cannot see: a session started fresh, whose id lives only in its
    environment. Those are reported as not-running, so restore may open a second
    window for one. Bind them and let restore own them after a reboot.

    Turnpike's own processes are filtered out because `session-bind --session-id <id>`
    puts that id on its own command line, which would otherwise look like a session.

    Returns None (unknown, so skip nothing) when the process table cannot be read,
    rather than claiming nothing is running.
    """
    if os.name != "nt":
        return None
    import subprocess
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Get-CimInstance Win32_Process | Select-Object CommandLine | ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=30)
        procs = json.loads(out.stdout) if out.returncode == 0 and out.stdout.strip() else None
    except Exception:
        return None
    if not procs:
        return None
    if isinstance(procs, dict):
        procs = [procs]
    self_marker = Path(__file__).stem.lower()          # 'turnpike'
    lines = [(p.get("CommandLine") or "").lower() for p in procs]
    return [cl for cl in lines if cl and self_marker not in cl]


def is_running(running, thread_id: str) -> bool:
    if not running:
        return False
    needle = thread_id.lower()
    return any(needle in cl for cl in running)


def binding_title(con, b) -> str:
    if b["title"]:
        return b["title"]
    slug = con.execute("SELECT slug FROM projects WHERE id=?", (b["project_id"],)).fetchone()["slug"]
    if b["task_id"]:
        t = con.execute("SELECT title FROM tasks WHERE id=?", (b["task_id"],)).fetchone()
        if t:
            return f"{slug} #{b['task_id']} {t['title']}"[:60]
    return f"{slug} ({b['provider']})"


def cmd_session_bind(a):
    con = connect()
    p = get_project(con, a.project)
    provider, thread_id = a.provider, a.session_id
    if not thread_id:
        provider, thread_id = detect_session()
        if not thread_id:
            sys.exit("error: no session id given and none found in the environment.\n"
                     "  Run this from inside an agent session, or pass --session-id <id> --provider <name>.\n"
                     f"  Known providers: {', '.join(PROVIDERS)}")
    if not provider:
        sys.exit("error: --provider is required when you pass --session-id")
    if provider not in PROVIDERS:
        sys.exit(f"error: unknown provider '{provider}'. Known: {', '.join(PROVIDERS)}")
    if a.task is not None and not con.execute("SELECT 1 FROM tasks WHERE id=?", (a.task,)).fetchone():
        sys.exit(f"error: no task #{a.task}")
    cwd = a.cwd or os.getcwd()
    ts = now()
    con.execute("""
        INSERT INTO session_bindings (project_id, provider, thread_id, agent, task_id, cwd, title,
                                      status, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,'active',?,?)
        ON CONFLICT(provider, thread_id) DO UPDATE SET
            project_id=excluded.project_id, agent=excluded.agent, task_id=excluded.task_id,
            cwd=excluded.cwd, title=excluded.title, status='active', updated_at=excluded.updated_at""",
        (p["id"], provider, thread_id, a.author, a.task, cwd, a.title, ts, ts))
    touch_project(con, p["id"])
    con.commit()
    print(f"bound {provider} session {thread_id} to '{a.project}'"
          + (f" task #{a.task}" if a.task else "") + f"\n  cwd: {cwd}")


def cmd_sessions(a):
    con = connect()
    q = ("SELECT b.*, p.slug FROM session_bindings b JOIN projects p ON p.id=b.project_id")
    vals, where = [], []
    if a.project:
        where.append("p.slug=?"); vals.append(a.project)
    if not a.all:
        where.append("b.status='active'")
    if where:
        q += " WHERE " + " AND ".join(where)
    rows = con.execute(q + " ORDER BY p.slug, b.id", vals).fetchall()
    if a.json:
        emit([dict(r) for r in rows], True)
        return
    if not rows:
        print("no bound sessions. bind one from inside an agent session: turnpike session-bind <project> --as <you>")
        return
    running = live_command_lines()
    for b in rows:
        live = "" if running is None else ("  [running]" if is_running(running, b["thread_id"]) else "")
        task = f" task #{b['task_id']}" if b["task_id"] else ""
        print(f"[{b['status']}] {b['slug']:<22} {b['provider']:<10} {b['thread_id']}{task}{live}")
        print(f"    {binding_title(con, b)}\n    cwd: {b['cwd'] or '(none)'}")


def cmd_session_forget(a):
    con = connect()
    b = con.execute("SELECT * FROM session_bindings WHERE id=?", (a.id,)).fetchone()
    if b is None:
        sys.exit(f"error: no session binding #{a.id}")
    con.execute("DELETE FROM session_bindings WHERE id=?", (a.id,))
    con.commit()
    print(f"forgot binding #{a.id} ({b['provider']} {b['thread_id']})")


def cmd_restore(a):
    """Reopen one Windows Terminal window with a tab per bound session."""
    con = connect()
    q = ("SELECT b.*, p.slug FROM session_bindings b JOIN projects p ON p.id=b.project_id "
         "WHERE b.status='active'")
    vals = []
    if a.project:
        q += " AND p.slug=?"; vals.append(a.project)
    if not a.all:
        # default: only sessions whose task is actively being worked, plus untasked ones
        q += (" AND (b.task_id IS NULL OR b.task_id IN "
              "(SELECT id FROM tasks WHERE status IN ('doing','blocked')))")
    rows = con.execute(q + " ORDER BY p.slug, b.id", vals).fetchall()

    running = live_command_lines()
    seen, plan, skipped = set(), [], []
    for b in rows:
        key = (b["provider"], b["thread_id"])
        if key in seen:
            skipped.append((b, "duplicate binding for the same conversation"))
            continue
        seen.add(key)
        if is_running(running, b["thread_id"]):
            skipped.append((b, "already running"))
            continue
        cwd = b["cwd"]
        if not cwd or not Path(cwd).is_dir():
            proj = con.execute("SELECT workdir FROM projects WHERE id=?", (b["project_id"],)).fetchone()
            cwd = proj["workdir"] if proj and proj["workdir"] and Path(proj["workdir"]).is_dir() else ""
        if not cwd:
            skipped.append((b, "no usable working directory - re-bind with --cwd"))
            continue
        plan.append((b, cwd, PROVIDERS[b["provider"]]["resume"](b["thread_id"])))

    for b, why in skipped:
        print(f"skip  {b['provider']} {b['thread_id']}  ({why})")
    if not plan:
        print("nothing to restore." + ("" if running is not None else
              "  (could not read the process table, so nothing was skipped as already-running)"))
        return
    for b, cwd, argv in plan:
        print(f"tab   {binding_title(con, b)}\n        {' '.join(argv)}   [{cwd}]")
    if a.dry_run:
        print(f"\n--dry-run: would open {len(plan)} tab(s) in one Windows Terminal window.")
        return

    wt_args = []
    for i, (b, cwd, argv) in enumerate(plan):
        if i:
            wt_args.append(";")
        wt_args += ["new-tab", "--title", binding_title(con, b), "-d", cwd,
                    "powershell.exe", "-NoExit", "-Command", " ".join(argv)]
    import subprocess
    try:
        subprocess.Popen(["wt.exe"] + wt_args, close_fds=True)
    except FileNotFoundError:
        sys.exit("error: wt.exe (Windows Terminal) not found on PATH.")
    print(f"\nrestored {len(plan)} session(s) into one Windows Terminal window.")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="turnpike", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def author_arg(p):
        p.add_argument("--as", dest="author", required=True,
                       help="who you are: claude | codex | user | ...")

    p = sub.add_parser("create", help="create a project")
    p.add_argument("slug")
    p.add_argument("--name", default="")
    p.add_argument("--goal", required=True)
    p.add_argument("--workdir", default="", help="repo/folder agents should work in")
    p.set_defaults(fn=cmd_create)

    p = sub.add_parser("workdir", help="set a project's working directory")
    p.add_argument("project")
    p.add_argument("path")
    p.set_defaults(fn=cmd_workdir)

    p = sub.add_parser("projects", help="list projects")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_projects)

    p = sub.add_parser("post", help="post a message to a project")
    p.add_argument("project")
    p.add_argument("body", help="message text, or '-' to read stdin")
    author_arg(p)
    p.add_argument("--kind", default="update", choices=MESSAGE_KINDS)
    p.set_defaults(fn=cmd_post)

    p = sub.add_parser("pull", help="fetch messages you haven't seen + open tasks (advances your cursor)")
    p.add_argument("project")
    author_arg(p)
    p.add_argument("--peek", action="store_true", help="don't advance the cursor")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_pull)

    p = sub.add_parser("log", help="recent message history (does not touch cursors)")
    p.add_argument("project")
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_log)

    p = sub.add_parser("summary", help="set the living layman's-terms project summary")
    p.add_argument("project")
    p.add_argument("text", help="summary text, or '-' to read stdin")
    p.set_defaults(fn=cmd_summary)

    p = sub.add_parser("status", help="set project status")
    p.add_argument("project")
    p.add_argument("status", choices=("active", "paused", "done", "archived"))
    p.set_defaults(fn=cmd_project_status)

    p = sub.add_parser("task-add", help="add a task")
    p.add_argument("project")
    p.add_argument("title")
    author_arg(p)
    p.add_argument("--detail", default="")
    p.add_argument("--assignee", default="")
    p.set_defaults(fn=cmd_task_add)

    p = sub.add_parser("task-update", help="update a task by id")
    p.add_argument("id", type=int)
    p.add_argument("--as", dest="author", default="",
                   help="who is making this change (falls back to assignee)")
    p.add_argument("--status", choices=TASK_STATUSES)
    p.add_argument("--assignee")
    p.add_argument("--detail")
    p.set_defaults(fn=cmd_task_update)

    p = sub.add_parser("tasks", help="list tasks for a project")
    p.add_argument("project")
    p.add_argument("--all", action="store_true", help="include done/dropped")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_tasks)

    p = sub.add_parser("session-bind", help="remember this agent conversation so it can be reopened after a reboot")
    p.add_argument("project")
    author_arg(p)
    p.add_argument("--session-id", default="", help="provider conversation id (default: read from this session's environment)")
    p.add_argument("--provider", default="", choices=tuple(PROVIDERS) + ("",),
                   help="required only with --session-id")
    p.add_argument("--task", type=int, help="task this session is working on")
    p.add_argument("--cwd", default="", help="directory to reopen in (default: current)")
    p.add_argument("--title", default="", help="tab title (default: derived from project/task)")
    p.set_defaults(fn=cmd_session_bind)

    p = sub.add_parser("sessions", help="list bound sessions")
    p.add_argument("project", nargs="?", default="")
    p.add_argument("--all", action="store_true", help="include dormant")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_sessions)

    p = sub.add_parser("session-forget", help="drop a session binding by id")
    p.add_argument("id", type=int)
    p.set_defaults(fn=cmd_session_forget)

    p = sub.add_parser("restore", help="reopen bound sessions in one Windows Terminal window")
    p.add_argument("--project", default="", help="restore only this project")
    p.add_argument("--all", action="store_true", help="restore every active binding, not just ones on doing/blocked tasks")
    p.add_argument("--dry-run", action="store_true", help="show what would open, change nothing")
    p.set_defaults(fn=cmd_restore)

    a = ap.parse_args(argv)
    author = getattr(a, "author", None)
    if author:
        con = connect()
        con.execute("""INSERT INTO agents (name, last_seen) VALUES (?,?)
                       ON CONFLICT(name) DO UPDATE SET last_seen=excluded.last_seen""",
                    (author, now()))
        con.commit()
        con.close()
    a.fn(a)


if __name__ == "__main__":
    main()
