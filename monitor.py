#!/usr/bin/env python3
"""Monitor web app for turnpike.

Serves a single-page UI + JSON API over the shared SQLite bus.
Read-only except: posting directives/messages as 'user' and editing tasks.

Run:  python monitor.py            (default http://127.0.0.1:8642)
      python monitor.py --port N
"""

import argparse
import json
import sqlite3
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import turnpike
import turnpike_notes as notes

ROOT = Path(__file__).resolve().parent
UI = ROOT / "ui" / "index.html"

# Data-bridge fact: how each agent CLI is launched. The flags put every summoned
# session in skip-permissions / bypass / full-access mode, matching the user's
# clauded / codexd / seekd shell aliases. Single owner for these argv facts.
SUMMON_AGENTS = {
    "claude":   ["claude", "--dangerously-skip-permissions"],
    "codex":    ["codex", "--dangerously-bypass-approvals-and-sandbox"],
    "deepseek": ["codewhale", "--approval-policy", "never",
                 "--sandbox-mode", "danger-full-access"],
}


def provision_worktree(workdir: str, agent: str, slug: str):
    """If workdir is a git repo, give this agent its own worktree + parking branch.

    Returns (effective_workdir, note). Falls back to workdir untouched for
    non-git projects; refuses to fall back silently on a git failure.
    """
    repo = Path(workdir)
    if not (repo / ".git").exists():
        return workdir, ""
    wt = repo.parent / f"{repo.name}-agents" / f"{agent}-{slug}"
    branch = f"agent/{agent}/{slug}"
    if wt.is_dir():
        return str(wt), f"reusing worktree {wt}"

    def git(*args):
        return subprocess.run(["git", "-C", str(repo)] + list(args),
                              capture_output=True, text=True)

    wt.parent.mkdir(parents=True, exist_ok=True)
    branch_exists = git("rev-parse", "--verify", "--quiet", branch).returncode == 0
    r = (git("worktree", "add", str(wt), branch) if branch_exists
         else git("worktree", "add", "-b", branch, str(wt)))
    if r.returncode != 0:
        raise RuntimeError(f"worktree provisioning failed: {r.stderr.strip()}")
    return str(wt), f"created worktree {wt} on branch {branch}"


def run_git(path, *args, timeout=10):
    try:
        r = subprocess.run(["git", "-C", str(path)] + list(args),
                           capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


def git_state(workdir):
    """Commits across all local branches + per-worktree branch health."""
    if not workdir:
        return {"is_git": False}
    repo = Path(workdir)
    if not (repo / ".git").exists():
        return {"is_git": False}
    commits = []
    out = run_git(repo, "log", "--branches", "--date-order", "-n", "60",
                  "--pretty=format:%H%x1f%h%x1f%an%x1f%aI%x1f%s%x1f%D")
    for line in out.splitlines():
        f = line.split("\x1f")
        if len(f) == 6:
            commits.append({"hash": f[0], "short": f[1], "author": f[2],
                            "date": f[3], "subject": f[4], "refs": f[5]})
    default = next((b for b in ("main", "master")
                    if run_git(repo, "rev-parse", "--verify", "--quiet", b)), "")
    worktrees, cur = [], {}
    for ln in run_git(repo, "worktree", "list", "--porcelain").splitlines() + [""]:
        if ln.startswith("worktree "):
            cur = {"path": ln[9:]}
        elif ln.startswith("branch "):
            cur["branch"] = ln[7:].replace("refs/heads/", "")
        elif ln == "" and cur:
            worktrees.append(cur)
            cur = {}
    for w in worktrees:
        w["dirty"] = len([l for l in run_git(w["path"], "status", "--porcelain").splitlines() if l.strip()])
        b = w.get("branch", "")
        w["ahead"] = w["behind"] = 0
        if default and b and b != default:
            cnt = run_git(repo, "rev-list", "--left-right", "--count", f"{default}...{b}").split()
            if len(cnt) == 2:
                w["behind"], w["ahead"] = int(cnt[0]), int(cnt[1])
    return {"is_git": True, "default_branch": default,
            "commits": commits, "worktrees": worktrees}


def db_version(con):
    version = tuple(con.execute("""
        SELECT (SELECT IFNULL(MAX(id),0)  FROM messages),
               (SELECT IFNULL(MAX(updated_at),'') FROM tasks),
               (SELECT IFNULL(MAX(updated_at),'') FROM projects),
               (SELECT COUNT(*) FROM tasks),
               (SELECT IFNULL(MAX(last_seen),'') FROM agents)""").fetchone())
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='note_jobs'").fetchone():
        version += tuple(con.execute("SELECT COUNT(*),IFNULL(SUM(revision),0) FROM note_jobs").fetchone())
    return version


def q(con, sql, vals=()):
    return [dict(r) for r in con.execute(sql, vals).fetchall()]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # quiet

    def send_json(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        n = int(self.headers.get("Content-Length", 0))
        if not 0 <= n <= 12 * 1024 * 1024:
            raise ValueError("Request body exceeds 12 MiB")
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        u = urlparse(self.path)
        con = turnpike.connect()
        try:
            if u.path in ("/", "/index.html"):
                body = UI.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif u.path == "/icon.svg":
                body = (ROOT / "ui" / "icon.svg").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/svg+xml")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif u.path == "/api/attachment":
                aid = parse_qs(u.query).get("id", [""])[0]
                con.executescript(notes.SCHEMA)
                asset = con.execute("SELECT mime,data FROM note_assets WHERE id=?", (aid,)).fetchone()
                if not asset:
                    self.send_json({"error": "Attachment not found"}, 404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", asset["mime"])
                self.send_header("Content-Length", str(len(asset["data"])))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Cache-Control", "private, max-age=86400")
                self.end_headers()
                self.wfile.write(asset["data"])
            elif u.path == "/api/projects":
                self.send_json({
                    "projects": q(con, """
                        SELECT p.*,
                          (SELECT COUNT(*) FROM tasks t WHERE t.project_id=p.id AND t.status IN ('todo','doing','blocked')) AS open_tasks,
                          (SELECT COUNT(*) FROM tasks t WHERE t.project_id=p.id AND t.status != 'dropped') AS total_tasks,
                          (SELECT COUNT(*) FROM tasks t WHERE t.project_id=p.id AND t.status = 'done') AS done_tasks,
                          (SELECT COUNT(*) FROM messages m WHERE m.project_id=p.id) AS msg_count
                        FROM projects p ORDER BY p.updated_at DESC"""),
                    "agents": q(con, "SELECT * FROM agents ORDER BY name"),
                    "now": turnpike.now(),
                })
            elif u.path == "/api/attention":
                # Read-only counts the existing endpoints cannot express: message ids are
                # global so id arithmetic across projects is invalid, and /api/activity is
                # hard-capped at 40 rows. `marks` is the human's client-local read marks,
                # "slug:id,slug:id"; anything missing counts from 0.
                marks = {}
                for pair in parse_qs(u.query).get("marks", [""])[0].split(","):
                    s, sep, i = pair.partition(":")
                    if sep and i.isdigit():
                        marks[s] = int(i)
                rows = q(con, """
                    SELECT p.slug, p.id AS pid,
                      (SELECT IFNULL(MAX(m.id),0) FROM messages m WHERE m.project_id=p.id) AS last_msg_id,
                      (SELECT COUNT(*) FROM messages m WHERE m.project_id=p.id AND m.author<>'user'
                         AND m.kind IN ('blocker','question')
                         AND m.id > IFNULL((SELECT MAX(u.id) FROM messages u
                                            WHERE u.project_id=p.id AND u.author='user'),0)) AS needs,
                      (SELECT COUNT(*) FROM tasks t WHERE t.project_id=p.id AND t.status='blocked')
                         AS blocked_tasks
                    FROM projects p""")
                for r in rows:
                    r["unread"] = con.execute(
                        "SELECT COUNT(*) FROM messages WHERE project_id=? AND id>? AND author<>'user'",
                        (r.pop("pid"), marks.get(r["slug"], 0))).fetchone()[0]
                items = q(con, """
                    SELECT m.id, p.slug, m.author, m.kind, m.created_at,
                           substr(m.body,1,240) AS excerpt
                    FROM messages m JOIN projects p ON p.id=m.project_id
                    WHERE m.author<>'user' AND m.kind IN ('blocker','question')
                      AND m.id > IFNULL((SELECT MAX(u.id) FROM messages u
                                         WHERE u.project_id=m.project_id AND u.author='user'),0)
                    ORDER BY m.id DESC LIMIT 50""")
                self.send_json({"projects": rows, "items": items, "now": turnpike.now()})
            elif u.path == "/api/activity":
                self.send_json(notes.attach_metadata(con, q(con, """
                    SELECT m.*, p.slug FROM messages m JOIN projects p ON p.id=m.project_id
                    ORDER BY m.id DESC LIMIT 40""")))
            elif u.path == "/api/events":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                last = None
                try:
                    while True:
                        ver = db_version(con)
                        if ver != last:
                            last = ver
                            self.wfile.write(b"data: changed\n\n")
                            self.wfile.flush()
                        time.sleep(0.6)
                except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, OSError):
                    pass
            elif u.path == "/api/project":
                params = parse_qs(u.query)
                slug = params.get("slug", [""])[0]
                since = int(params.get("since", ["0"])[0])
                p = q(con, "SELECT * FROM projects WHERE slug=?", (slug,))
                if not p:
                    self.send_json({"error": "no such project"}, 404)
                    return
                pid = p[0]["id"]
                msgs = q(con, "SELECT * FROM (SELECT * FROM messages WHERE project_id=? ORDER BY id DESC LIMIT 300) ORDER BY id", (pid,))
                self.send_json({
                    "project": p[0],
                    "messages": notes.attach_metadata(con, msgs),
                    "tasks": q(con, "SELECT * FROM tasks WHERE project_id=? ORDER BY id", (pid,)),
                    "cursors": q(con, "SELECT * FROM cursors WHERE project_id=?", (pid,)),
                    "agents": q(con, "SELECT * FROM agents ORDER BY name"),
                    "git": git_state(p[0]["workdir"]),
                    "now": turnpike.now(),
                })
            else:
                self.send_json({"error": "not found"}, 404)
        finally:
            con.close()

    def do_POST(self):
        u = urlparse(self.path)
        con = turnpike.connect()
        try:
            data = self.read_body()
            if u.path == "/api/post":
                kind = data.get("kind", "directive")
                import uuid
                result = notes.post_user_message(data["slug"], kind, data.get("body", ""), data.get("attachments", []), data.get("client_id") or str(uuid.uuid4()))
                if result["response"]:
                    try:
                        notes.ensure_worker()
                    except OSError:
                        result["worker_warning"] = "Note is saved and queued; the responder could not be started"
                self.send_json(result)
            elif u.path == "/api/attachment":
                self.send_json({"ok": True, "attachment": notes.store_asset(data["slug"], data["mime"], data["data"])})
            elif u.path == "/api/task":
                # {id, status?} update or {slug, title, detail?} create
                if "id" in data:
                    t = q(con, "SELECT * FROM tasks WHERE id=?", (data["id"],))
                    con.execute("UPDATE tasks SET status=?, updated_at=? WHERE id=?",
                                (data["status"], turnpike.now(), data["id"]))
                    turnpike.apply_task_status(con, data["id"], data["status"])
                    if t and t[0]["status"] != data["status"]:
                        turnpike.post_task_event(con, t[0]["project_id"], "user",
                            f"task #{data['id']} \"{t[0]['title']}\": {t[0]['status']} -> {data['status']}")
                else:
                    p = q(con, "SELECT * FROM projects WHERE slug=?", (data["slug"],))
                    if not p:
                        self.send_json({"error": "no such project"}, 404)
                        return
                    ts = turnpike.now()
                    cur = con.execute("""INSERT INTO tasks (project_id, title, detail, assignee, created_by, created_at, updated_at)
                                   VALUES (?,?,?,?,?,?,?)""",
                                (p[0]["id"], data["title"], data.get("detail", ""),
                                 data.get("assignee", ""), "user", ts, ts))
                    turnpike.post_task_event(con, p[0]["id"], "user",
                        f"created task #{cur.lastrowid} \"{data['title']}\""
                        + (f" (assigned to {data['assignee']})" if data.get("assignee") else ""))
                con.commit()
                self.send_json({"ok": True})
            elif u.path == "/api/workdir":
                p = q(con, "SELECT * FROM projects WHERE slug=?", (data["slug"],))
                if not p:
                    self.send_json({"error": "no such project"}, 404)
                    return
                con.execute("UPDATE projects SET workdir=?, updated_at=? WHERE id=?",
                            (data.get("workdir", ""), turnpike.now(), p[0]["id"]))
                con.commit()
                self.send_json({"ok": True})
            elif u.path == "/api/summon":
                agent = data.get("agent")
                if agent not in SUMMON_AGENTS:
                    self.send_json({"error": "unknown agent; known: " + ", ".join(
                        f"{k} ({' '.join(v)})" for k, v in SUMMON_AGENTS.items())}, 400)
                    return
                p = q(con, "SELECT * FROM projects WHERE slug=?", (data["slug"],))
                if not p:
                    self.send_json({"error": "no such project"}, 404)
                    return
                workdir = p[0]["workdir"]
                if not workdir or not Path(workdir).is_dir():
                    workdir = str(ROOT)
                try:
                    workdir, note = provision_worktree(workdir, agent, p[0]["slug"])
                except RuntimeError as e:
                    self.send_json({"error": str(e)}, 500)
                    return
                prompt = (f"Read {ROOT}\\PROTOCOL.md. Then pull turnpike project "
                          f"{p[0]['slug']} as {agent} and act on unread messages and open "
                          f"tasks. Post plain-language updates to turnpike as you go."
                          + (f" You are in your own git worktree ({workdir}); follow the "
                             f"protocol's git rules — cut a task branch before real work."
                             if note else ""))
                subprocess.Popen(["cmd", "/k"] + SUMMON_AGENTS[agent] + [prompt],
                                 cwd=workdir,
                                 creationflags=subprocess.CREATE_NEW_CONSOLE)
                self.send_json({"ok": True, "workdir": workdir, "note": note})
            elif u.path == "/api/create-project":
                ts = turnpike.now()
                try:
                    con.execute("INSERT INTO projects (slug, name, goal, workdir, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                                (data["slug"], data.get("name") or data["slug"], data.get("goal", ""),
                                 data.get("workdir", ""), ts, ts))
                    con.commit()
                    self.send_json({"ok": True})
                except sqlite3.IntegrityError:
                    self.send_json({"error": "slug exists"}, 409)
            else:
                self.send_json({"error": "not found"}, 404)
        except (KeyError, ValueError, TypeError) as e:
            self.send_json({"error": f"bad request: {e}"}, 400)
        finally:
            con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8642)
    a = ap.parse_args()
    con = notes.connect()
    pending = con.execute("SELECT 1 FROM note_jobs WHERE state IN ('queued','running','waiting_for_auth','waiting_for_quota') LIMIT 1").fetchone()
    con.close()
    if pending:
        try:
            notes.ensure_worker()
        except OSError:
            print("Notes are queued; responder startup failed", file=sys.stderr)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    srv.daemon_threads = True
    print(f"turnpike monitor on http://127.0.0.1:{a.port}  (db: {turnpike.DB_PATH})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
