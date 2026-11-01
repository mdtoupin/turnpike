"""CLI-owned JSON board protocol. SSH supplies account authentication, not a sandbox.

Every mutation and its retry receipt commit in the same bus database transaction.
This endpoint does not launch model processes or accept arbitrary shell commands.
"""
import getpass
import hashlib
import json
import sqlite3
import sys
import uuid

import turnpike as bus

MAX_REQUEST = 1024 * 1024
SCHEMA = """
CREATE TABLE IF NOT EXISTS rpc_requests (
    actor TEXT NOT NULL,
    request_id TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (actor, request_id)
);
CREATE TABLE IF NOT EXISTS worker_inboxes (
    project_id INTEGER NOT NULL REFERENCES projects(id),
    actor TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    delivered_id INTEGER NOT NULL DEFAULT 0,
    acknowledged_id INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (project_id, actor, worker_id)
);
CREATE TABLE IF NOT EXISTS task_rpc_revisions (
    task_id INTEGER PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO task_rpc_revisions (task_id, revision) SELECT id, 0 FROM tasks;
CREATE TRIGGER IF NOT EXISTS task_rpc_revision_insert AFTER INSERT ON tasks BEGIN
    INSERT INTO task_rpc_revisions (task_id,revision) VALUES (NEW.id,1);
END;
CREATE TRIGGER IF NOT EXISTS task_rpc_revision_update AFTER UPDATE ON tasks BEGIN
    INSERT INTO task_rpc_revisions (task_id,revision) VALUES (NEW.id,1)
    ON CONFLICT(task_id) DO UPDATE SET revision=revision+1;
END;
"""

FIELDS = {
    "capabilities": set(),
    "projects": {"include_archived"},
    "board": {"project", "include_dropped"},
    "messages": {"project", "after_id", "limit"},
    "inbox": {"project", "worker_id", "limit"},
    "ack": {"project", "worker_id", "through_id"},
    "post": {"project", "kind", "body"},
    "task.create": {"project", "title", "detail"},
    "task.update": {"task_id", "expected_revision", "changes"},
}


class RequestError(Exception):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def text(params, key, *, default=None, maximum=100000):
    value = params.get(key, default)
    if not isinstance(value, str) or len(value) > maximum or "\x00" in value:
        raise RequestError("invalid_params", f"{key} must be a string of at most {maximum} characters")
    return value


def integer(params, key, *, default=None, minimum=0, maximum=2**63-1):
    value = params.get(key, default)
    if type(value) is not int or not minimum <= value <= maximum:
        raise RequestError("invalid_params", f"{key} must be an integer between {minimum} and {maximum}")
    return value


def flag(params, key, default=False):
    value = params.get(key, default)
    if type(value) is not bool:
        raise RequestError("invalid_params", f"{key} must be a boolean")
    return value


def project(con, selector):
    if type(selector) is int:
        if not 1 <= selector <= 2**63-1:
            raise RequestError("invalid_params", "Project ID is outside the supported range")
        rows = con.execute("SELECT * FROM projects WHERE id=?", (selector,)).fetchall()
    elif isinstance(selector, str) and 0 < len(selector) <= 256:
        rows = con.execute("SELECT * FROM projects WHERE slug=?", (selector,)).fetchall()
        if not rows:
            rows = con.execute("SELECT * FROM projects WHERE name=? COLLATE NOCASE", (selector,)).fetchall()
    else:
        raise RequestError("invalid_params", "project must be a stable ID, slug or display name")
    if not rows:
        raise RequestError("not_found", "Project not found")
    if len(rows) != 1:
        raise RequestError("ambiguous_project", "Display name is ambiguous; use a slug or ID")
    return rows[0]


def card(con, row):
    value = dict(row)
    revision = con.execute("SELECT revision FROM task_rpc_revisions WHERE task_id=?", (row["id"],)).fetchone()[0]
    value["revision"] = f"{revision}:" + digest(value)
    return value


def message(con, project_id, actor, kind, body):
    if kind not in bus.MESSAGE_KINDS or kind in ("directive", "task"):
        raise RequestError("invalid_params", "Agent posts cannot use directive or task kinds")
    if not body.strip():
        raise RequestError("invalid_params", "Message body must not be blank")
    cur = con.execute("INSERT INTO messages (project_id,author,kind,body,created_at) VALUES (?,?,?,?,?)",
                      (project_id, actor, kind, body, bus.now()))
    bus.touch_project(con, project_id)
    # Posting never acknowledges other messages, including legacy agent cursors.
    return cur.lastrowid


def worker(params):
    value = text(params, "worker_id", maximum=128)
    if not value.strip():
        raise RequestError("invalid_params", "worker_id must not be blank")
    return value


def dispatch(con, actor, operation, params):
    if operation == "capabilities":
        return {"protocol_version": 1, "operations": sorted(FIELDS),
                "atomic_retry_receipts": True, "explicit_inbox_ack": True,
                "model_execution": False, "attachments": False,
                "task_ownership": "cooperative actor ownership with optimistic revisions; process fencing is not implemented"}
    if operation == "projects":
        include = flag(params, "include_archived", True)
        rows = con.execute("SELECT * FROM projects ORDER BY updated_at DESC,id").fetchall()
        return {"projects": [dict(p) for p in rows if include or p["status"] not in ("archived", "done")]}
    if operation == "task.update":
        task_id = integer(params, "task_id", minimum=1)
        old = con.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if old is None:
            raise RequestError("not_found", "Task not found")
        if text(params, "expected_revision", maximum=128) != card(con, old)["revision"]:
            raise RequestError("revision_conflict", "Task changed; read the current board before retrying")
        if old["status"] == "doing" and old["assignee"] not in ("", actor):
            raise RequestError("task_owned", "Another agent is working on this task")
        changes = params.get("changes")
        if not isinstance(changes, dict) or not changes or set(changes)-{"status", "title", "detail", "assignee"}:
            raise RequestError("invalid_params", "changes must contain supported task fields")
        for key in changes:
            text(changes, key)
        if "status" in changes and changes["status"] not in bus.TASK_STATUSES:
            raise RequestError("invalid_params", "Unsupported task status")
        if "title" in changes and not changes["title"].strip():
            raise RequestError("invalid_params", "Task title must not be blank")
        if changes.get("status") == "doing" and changes.get("assignee", old["assignee"]) not in ("", actor):
            raise RequestError("task_owned", "Cannot start work assigned to another agent")
        if changes.get("status") == "doing" and not changes.get("assignee", old["assignee"]):
            changes = {**changes, "assignee": actor}
        fields = [f"{key}=?" for key in changes]
        con.execute("UPDATE tasks SET " + ",".join(fields) + ",updated_at=? WHERE id=?",
                    (*changes.values(), bus.now(), task_id))
        if "status" in changes:
            bus.apply_task_status(con, task_id, changes["status"])
        message(con, old["project_id"], actor, "update", f"Updated task #{task_id}: " + ", ".join(changes))
        return {"task": card(con, con.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())}
    p = project(con, params.get("project"))
    pid = p["id"]
    if operation == "board":
        include = flag(params, "include_dropped")
        tasks = con.execute("SELECT * FROM tasks WHERE project_id=? ORDER BY id", (pid,)).fetchall()
        return {"project": dict(p), "tasks": [card(con, t) for t in tasks if include or t["status"] != "dropped"]}
    if operation in ("messages", "inbox"):
        limit = integer(params, "limit", default=50, minimum=1, maximum=200)
        if operation == "inbox":
            wid = worker(params)
            con.execute("INSERT OR IGNORE INTO worker_inboxes (project_id,actor,worker_id) VALUES (?,?,?)", (pid, actor, wid))
            inbox = con.execute("SELECT * FROM worker_inboxes WHERE project_id=? AND actor=? AND worker_id=?", (pid, actor, wid)).fetchone()
            after = inbox["acknowledged_id"]
        else:
            after = integer(params, "after_id") if "after_id" in params else None
        if after is None:
            rows = list(reversed(con.execute("SELECT * FROM messages WHERE project_id=? ORDER BY id DESC LIMIT ?", (pid, limit)).fetchall()))
        else:
            rows = con.execute("SELECT * FROM messages WHERE project_id=? AND id>? ORDER BY id LIMIT ?", (pid, after, limit)).fetchall()
        result = {"project_id": pid, "messages": [dict(m) for m in rows], "last_message_id": rows[-1]["id"] if rows else after}
        if operation == "inbox":
            delivered = max(inbox["delivered_id"], result["last_message_id"] or 0)
            con.execute("UPDATE worker_inboxes SET delivered_id=? WHERE project_id=? AND actor=? AND worker_id=?", (delivered, pid, actor, wid))
            result.update(worker_id=wid, acknowledged_id=inbox["acknowledged_id"], delivered_id=delivered)
        return result
    if operation == "ack":
        wid, through = worker(params), integer(params, "through_id")
        inbox = con.execute("SELECT * FROM worker_inboxes WHERE project_id=? AND actor=? AND worker_id=?", (pid, actor, wid)).fetchone()
        if inbox is None or through > inbox["delivered_id"]:
            raise RequestError("invalid_ack", "Cannot acknowledge messages this worker has not been offered")
        if through and con.execute("SELECT 1 FROM messages WHERE project_id=? AND id=?", (pid, through)).fetchone() is None:
            raise RequestError("invalid_ack", "Acknowledgment must name a message in this room")
        through = max(through, inbox["acknowledged_id"])
        con.execute("UPDATE worker_inboxes SET acknowledged_id=? WHERE project_id=? AND actor=? AND worker_id=?", (through, pid, actor, wid))
        return {"project_id": pid, "worker_id": wid, "acknowledged_id": through}
    if operation == "post":
        mid = message(con, pid, actor, text(params, "kind", default="note", maximum=32), text(params, "body"))
        return {"message_id": mid, "project_id": pid}
    if operation == "task.create":
        title, detail = text(params, "title", maximum=1000), text(params, "detail", default="")
        if not title.strip():
            raise RequestError("invalid_params", "Task title must not be blank")
        stamp = bus.now()
        cur = con.execute("INSERT INTO tasks (project_id,title,detail,status,assignee,created_by,created_at,updated_at) VALUES (?,?,?,'todo','',?,?,?)",
                          (pid, title, detail, actor, stamp, stamp))
        message(con, pid, actor, "update", f"Created task #{cur.lastrowid}: {title}")
        return {"task": card(con, con.execute("SELECT * FROM tasks WHERE id=?", (cur.lastrowid,)).fetchone())}
    raise RequestError("unknown_operation", "Unsupported operation")


def execute(request, actor):
    request_id = request.get("request_id") if isinstance(request, dict) else None
    base = {"version": 1, "request_id": request_id}
    con = None
    try:
        if actor not in ("codex", "claude", "deepseek"):
            raise RequestError("invalid_actor", "Use the agent identity assigned to this SSH entry point")
        if not isinstance(request, dict) or set(request)-{"version", "request_id", "operation", "params"}:
            raise RequestError("invalid_request", "Expected a versioned request object")
        if type(request.get("version")) is not int or request["version"] != 1:
            raise RequestError("unsupported_version", "Protocol version 1 is required")
        try:
            canonical_id = str(uuid.UUID(request_id))
        except (ValueError, TypeError, AttributeError):
            raise RequestError("invalid_request_id", "request_id must be a UUID")
        if canonical_id != request_id:
            raise RequestError("invalid_request_id", "Use a canonical lowercase UUID")
        operation, params = request.get("operation"), request.get("params", {})
        if not isinstance(operation, str) or operation not in FIELDS:
            raise RequestError("unknown_operation", "Unsupported operation")
        if not isinstance(params, dict) or set(params)-FIELDS[operation]:
            raise RequestError("invalid_params", "Unexpected operation parameters")
        if len(json.dumps(request).encode("utf-8")) > MAX_REQUEST:
            raise RequestError("request_too_large", "Request exceeds the byte limit")
        request_hash = digest(request)
        con = bus.connect()
        con.executescript(SCHEMA)
        con.execute("BEGIN IMMEDIATE")
        prior = con.execute("SELECT * FROM rpc_requests WHERE actor=? AND request_id=?", (actor, request_id)).fetchone()
        if prior:
            if prior["request_hash"] != request_hash:
                raise RequestError("idempotency_conflict", "Request ID already used with different content")
            con.rollback()
            return json.loads(prior["response_json"])
        result = dispatch(con, actor, operation, params)
        response = {**base, "ok": True, "actor": actor, "account": getpass.getuser(), "result": result}
        con.execute("INSERT INTO rpc_requests (actor,request_id,request_hash,response_json,created_at) VALUES (?,?,?,?,?)",
                    (actor, request_id, request_hash, json.dumps(response, ensure_ascii=False), bus.now()))
        con.commit()
        return response
    except RequestError as exc:
        if con:
            con.rollback()
        return {**base, "ok": False, "error": {"code": exc.code, "message": str(exc), "retryable": False}}
    except sqlite3.Error:
        if con:
            con.rollback()
        return {**base, "ok": False, "error": {"code": "database_error", "message": "Database operation failed; retry the same request ID", "retryable": True}}
    finally:
        if con:
            con.close()


def serve(actor):
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    while True:
        line = sys.stdin.readline(MAX_REQUEST + 2)
        if not line:
            break
        if len(line.encode("utf-8")) > MAX_REQUEST:
            response = {"version": 1, "request_id": None, "ok": False, "error": {"code": "request_too_large", "message": "Request exceeds the byte limit", "retryable": False}}
            print(json.dumps(response), flush=True)
            break
        try:
            request = json.loads(line)
        except ValueError:
            response = {"version": 1, "request_id": None, "ok": False, "error": {"code": "invalid_json", "message": "Expected one JSON object per line", "retryable": False}}
        else:
            response = execute(request, actor)
        print(json.dumps(response, ensure_ascii=False), flush=True)
