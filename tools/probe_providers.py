"""Reproducible subscription-CLI contract checks; no application tools or API keys.

Metadata probes are the default. --live performs small inference/resume checks.
Reports contain observations, not credentials or raw provider transcripts.
"""
import argparse
import collections
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from urllib.parse import urlparse


PINNED = {"codex": "0.166.0", "claude": "2.1.295"}
MODELS = {"builder": ("gpt-6.1-sol", "medium"),
          "verifier": ("gpt-6-astra", "low"),
          "planner": ("claude-opus-5-5", "medium")}
API_ENV = ("OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL",
           "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
           "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY", "CLAUDE_CODE_EFFORT_LEVEL")


class ContractError(RuntimeError):
    pass


def validate_codex_route(config):
    if config.get("model_provider") not in (None, "openai"):
        raise ContractError("Custom model provider is outside the subscription probe contract")
    if (config.get("model_providers") or {}).get("openai"):
        raise ContractError("Custom first-party provider configuration requires separate review")
    for key in ("chatgpt_base_url", "openai_base_url"):
        value = config.get(key)
        if value:
            parsed = urlparse(value)
            expected = "chatgpt.com" if key == "chatgpt_base_url" else "api.openai.com"
            if parsed.scheme != "https" or parsed.netloc != expected or parsed.query or parsed.fragment:
                raise ContractError("Custom provider endpoint requires separate review")


def validate_version(provider, observed):
    parts = observed.split()
    token = parts[1] if provider == "codex" and len(parts) > 1 else parts[0] if parts else ""
    if token != PINNED[provider] or (provider == "codex" and parts[0] != "codex-cli"):
        raise ContractError(f"Unsupported version: {observed}")


def subscription_env():
    env = dict(os.environ)
    for name in API_ENV:
        env.pop(name, None)
    return env


def error_kind(value):
    """Classification is diagnostic; it never authorizes automatic replay."""
    text = json.dumps(value).lower()
    if any(word in text for word in ("rate_limit", "rate limit", "usage limit", "quota", "429")):
        return "waiting_for_quota"
    if any(word in text for word in ("unauthorized", "authentication", "not logged in", "401", "token expired")):
        return "waiting_for_auth"
    if any(word in text for word in ("unsupported model", "model_not_found", "not supported", "invalid model")):
        return "incompatible_provider"
    return "needs_attention"


def command(args, *, timeout=30, cwd=None):
    executable = shutil.which(args[0])
    if not executable:
        raise ContractError(f"Missing executable: {args[0]}")
    return subprocess.run([executable, *args[1:]], env=subscription_env(), cwd=cwd,
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, creationflags=0x08000000 if os.name == "nt" else 0)


class Rpc:
    def __init__(self, args, *, cwd=None, timeout=30):
        self.timeout, self.serial = timeout, 0
        self.pending = collections.deque()
        self.queue = queue.Queue(maxsize=4096)
        self.errors = collections.deque(maxlen=32)
        self.proc = subprocess.Popen(args, cwd=cwd, env=subscription_env(), stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                     encoding="utf-8", errors="replace", bufsize=1,
                                     creationflags=0x08000000 if os.name == "nt" else 0)
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._stderr, daemon=True).start()

    def _read(self):
        try:
            for line in self.proc.stdout:
                if line.strip():
                    try:
                        self.queue.put(json.loads(line))
                    except json.JSONDecodeError:
                        self.queue.put(ContractError("Non-JSON provider stdout"))
        finally:
            self.queue.put(EOFError("Provider stream closed"))

    def _stderr(self):
        for line in self.proc.stderr:
            self.errors.append(line[-1000:])

    def send(self, value):
        self.proc.stdin.write(json.dumps(value) + "\n")
        self.proc.stdin.flush()

    def receive(self, deadline):
        remaining = deadline-time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Provider response deadline expired")
        try:
            value = self.queue.get(timeout=remaining)
        except queue.Empty as exc:
            raise TimeoutError("Provider response deadline expired") from exc
        if isinstance(value, Exception):
            raise value
        if not isinstance(value, dict):
            raise ContractError("Provider message must be an object")
        if "method" in value and "id" in value:
            # No tools, permissions or credential prompts are approved by this probe.
            self.send({"id": value["id"], "error": {"code": -32000, "message": "Contract probe denies server requests"}})
        return value

    def retain(self, value):
        if len(self.pending) >= 4096:
            raise ContractError("Too many unrelated provider events")
        self.pending.append(value)

    def request(self, method, params):
        self.serial += 1
        request_id = self.serial
        self.send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + self.timeout
        while True:
            value = self.receive(deadline)
            if value.get("id") == request_id and "method" not in value:
                if "error" in value:
                    raise ContractError(json.dumps(value["error"]))
                return value.get("result")
            self.retain(value)

    def notification(self, method, predicate=lambda _: True, *, timeout=None):
        deadline = time.monotonic() + (timeout or self.timeout)
        while True:
            for index, value in enumerate(self.pending):
                if value.get("method") == method and predicate(value.get("params", {})):
                    del self.pending[index]
                    return value["params"]
            value = self.receive(deadline)
            self.retain(value)

    def close(self):
        if self.proc.stdin:
            try:
                self.proc.stdin.close()
            except OSError:
                pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        self.proc.stdout.close()
        self.proc.stderr.close()


def codex_rpc(cwd):
    rpc = Rpc([shutil.which("codex"), "app-server", "--stdio"], cwd=cwd)
    try:
        rpc.request("initialize", {"clientInfo": {"name": "turnpike_probe", "version": "0.1"},
                                   "capabilities": {"experimentalApi": False}})
        rpc.send({"method": "initialized", "params": {}})
        return rpc
    except BaseException:
        rpc.close()
        raise


def inspect_turn(rpc, thread_id, turn_id):
    # Hydrate completed/interrupted items through the supported API, not private files.
    thread = rpc.request("thread/read", {"threadId": thread_id, "includeTurns": True})["thread"]
    items = next(t for t in thread["turns"] if t["id"] == turn_id)["items"]
    if any(item.get("type") not in ("agentMessage", "reasoning", "userMessage", "contextCompaction") for item in items):
        raise ContractError("Unexpected tool activity observed in the inference-only probe")
    return "\n".join(item.get("text", "") for item in items if item.get("type") == "agentMessage")


def wait_turn(rpc, thread_id, turn_id):
    terminal = rpc.notification("turn/completed", lambda p: p.get("threadId") == thread_id and p.get("turn", {}).get("id") == turn_id, timeout=90)
    turn = terminal["turn"]
    if turn.get("status") != "completed":
        raise ContractError(f"Turn status: {turn.get('status')}; {turn.get('error')}")
    return inspect_turn(rpc, thread_id, turn_id)


def start_turn(rpc, observations, params):
    observations["inflight"] = {"operation": "turn/start", "thread_id": params["threadId"], "outcome": "unknown"}
    turn = rpc.request("turn/start", params)["turn"]
    observations["inflight"]["turn_id"] = turn["id"]
    return turn


def probe_codex(live, cwd):
    rpc = codex_rpc(cwd)
    result = {"checks": {}, "live": live}
    try:
        account = rpc.request("account/read", {"refreshToken": False}).get("account") or {}
        result["auth_type"] = account.get("type")
        if result["auth_type"] != "chatgpt":
            raise ContractError("Expected ChatGPT subscription authentication")
        result["checks"]["initialize_and_subscription_auth"] = "passed"
        validate_codex_route(rpc.request("config/read", {"includeLayers": False})["config"])
        result["checks"]["first_party_route_configuration"] = "passed"
        models, cursor = [], None
        while True:
            page = rpc.request("model/list", {"includeHidden": True, "limit": 100, "cursor": cursor})
            models.extend(page["data"])
            cursor = page.get("nextCursor")
            if not cursor:
                break
        result["models"] = {}
        for role in ("builder", "verifier"):
            name, effort = MODELS[role]
            found = next((m for m in models if m.get("model") == name or m.get("id") == name), None)
            if not found:
                raise ContractError(f"Requested model absent from catalog: {name}")
            efforts = [e["reasoningEffort"] for e in found.get("supportedReasoningEfforts", [])]
            if effort not in efforts:
                raise ContractError(f"Requested effort absent: {name}/{effort}")
            result["models"][role] = {"model": name, "effort": effort, "catalog_confirmed": True}
        if not live:
            return result
        for role in ("builder", "verifier"):
            model, effort = MODELS[role]
            started = rpc.request("thread/start", {"model": model, "modelProvider": "openai", "cwd": cwd, "approvalPolicy": "never", "sandbox": "read-only",
                                                    "developerInstructions": "Connectivity test only. Do not call tools or spawn agents. Reply only to the supplied test instruction."})
            if started.get("model") != model or started.get("modelProvider") != "openai":
                raise ContractError(f"Provider substituted requested model {model}")
            tid = started["thread"]["id"]
            result["models"][role]["thread_id"] = tid
            nonce = "TP_" + uuid.uuid4().hex[:12]
            turn = start_turn(rpc, result, {"threadId": tid, "effort": effort,
                                              "clientUserMessageId": str(uuid.uuid4()),
                                              "input": [{"type": "text", "text": "Reply exactly " + nonce}]})
            text = wait_turn(rpc, tid, turn["id"])
            if text.strip() != nonce:
                raise ContractError("Exact-response check failed")
            result["checks"][role + "_exact_model_turn"] = "passed"
            result.pop("inflight", None)
            if role == "builder":
                builder_nonce = nonce
        # Close and recreate the provider process before resuming the builder thread.
        tid = result["models"]["builder"]["thread_id"]
        rpc.close()
        rpc = codex_rpc(cwd)
        resumed = rpc.request("thread/resume", {"threadId": tid, "model": MODELS["builder"][0], "modelProvider": "openai", "cwd": cwd,
                                                "approvalPolicy": "never", "sandbox": "read-only"})
        if resumed["thread"]["id"] != tid or resumed.get("model") != MODELS["builder"][0] or resumed.get("modelProvider") != "openai":
            raise ContractError("Resume changed the thread identity")
        result["checks"]["restart_and_resume_identity"] = "passed"
        turn = start_turn(rpc, result, {"threadId": tid, "effort": "medium", "input": [{"type": "text", "text": "Reply with only the TP_ nonce from my earlier exact-response request."}]})
        if wait_turn(rpc, tid, turn["id"]).strip() != builder_nonce:
            raise ContractError("Resumed Codex thread did not retain earlier context")
        result["checks"]["restart_and_resume_context"] = "passed"
        result.pop("inflight", None)
        # Interrupt a read-only inference turn; never use an application tool as a probe.
        turn = start_turn(rpc, result, {"threadId": tid, "effort": "medium", "input": [{"type": "text", "text": "Without tools, list the numbers from 1 to 10000."}]})
        rpc.notification("turn/started", lambda p: p.get("threadId") == tid and p.get("turn", {}).get("id") == turn["id"])
        result["inflight"]["operation"] = "turn/interrupt"
        try:
            rpc.request("turn/interrupt", {"threadId": tid, "turnId": turn["id"]})
        except ContractError:
            terminal = rpc.notification("turn/completed", lambda p: p.get("threadId") == tid and p.get("turn", {}).get("id") == turn["id"], timeout=5)
            raise ContractError(f"Interrupt raced a terminal turn: {terminal['turn'].get('status')}; error: {terminal['turn'].get('error')}")
        terminal = rpc.notification("turn/completed", lambda p: p.get("threadId") == tid and p.get("turn", {}).get("id") == turn["id"], timeout=30)
        if terminal["turn"]["status"] != "interrupted":
            raise ContractError("Interrupt did not produce an interrupted terminal turn")
        inspect_turn(rpc, tid, turn["id"])
        result.pop("inflight", None)
        result["checks"]["turn_interrupt"] = "passed"
        result["checks"]["no_tool_activity_observed"] = "passed"
        return result
    except (ContractError, OSError, ValueError, TimeoutError, subprocess.TimeoutExpired, EOFError) as exc:
        exc.observations = result
        raise
    finally:
        rpc.close()


def claude_turn(cwd, prompt, session=None):
    model, effort = MODELS["planner"]
    args = ["claude", "--safe-mode", "-p", "--model", model, "--effort", effort,
            "--tools", "", "--permission-prompts", "none", "--output-format", "stream-json", "--verbose"]
    if session:
        args += ["--resume", session]
    args += [prompt]
    try:
        run = command(args, cwd=cwd, timeout=120)
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout or ""
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", errors="replace")
        sid = session
        for line in partial.splitlines():
            try:
                sid = json.loads(line).get("session_id") or sid
            except (ValueError, AttributeError):
                pass
        failure = ContractError("Claude deadline expired after possible submission; do not replay automatically")
        failure.observations = {"inflight": {"operation": "claude/resume" if session else "claude/start", "session_id": sid, "outcome": "unknown"}}
        raise failure from exc
    messages = [json.loads(line) for line in run.stdout.splitlines() if line.strip()]
    initialized, final = validate_claude_stream(messages, model)
    if run.returncode or final.get("is_error") or not final:
        raise ContractError(json.dumps({"exit": run.returncode, "result": final.get("result"), "errors": final.get("errors")}))
    return initialized, final


def validate_claude_stream(messages, model):
    init = [m for m in messages if m.get("type") == "system" and m.get("subtype") == "init"]
    results = [m for m in messages if m.get("type") == "result"]
    if len(init) != 1 or len(results) != 1 or messages[-1] is not results[0]:
        raise ContractError("Expected one initialization and one terminal result")
    initialized, final = init[0], results[0]
    sid = initialized.get("session_id")
    if not sid or any(m.get("session_id", sid) != sid for m in messages):
        raise ContractError("Conflicting Claude stream session identities")
    if initialized.get("model") != model or any(name != model for name in final.get("modelUsage", {})):
        raise ContractError("Claude substituted the requested model")
    if initialized.get("apiKeySource") != "none":
        raise ContractError("Claude inference reported an API key source")
    if initialized.get("tools"):
        raise ContractError("Claude inference-only probe exposed tools")
    return initialized, final


def probe_claude(live, cwd):
    auth = command(["claude", "auth", "status"])
    account = json.loads(auth.stdout)
    if auth.returncode or not account.get("loggedIn") or account.get("authMethod") != "claude.ai":
        raise ContractError("Expected Claude subscription authentication")
    result = {"auth_type": account["authMethod"], "subscription_type": account.get("subscriptionType"),
              "live": live, "checks": {"subscription_auth": "passed"},
              "model": dict(zip(("model", "effort"), MODELS["planner"]))}
    if not live:
        return result
    try:
        nonce = "TP_" + uuid.uuid4().hex[:12]
        result["inflight"] = {"operation": "claude/start", "outcome": "unknown"}
        init, final = claude_turn(cwd, "Reply exactly " + nonce + ". Do not use tools.")
        sid = final.get("session_id") or init.get("session_id")
        result["session_id"] = sid
        if final.get("result", "").strip() != nonce:
            raise ContractError("Claude exact-response check failed")
        if not sid:
            raise ContractError("Claude omitted durable session identity")
        result["checks"]["exact_model_stream_and_result"] = "passed"
        result["inflight"] = {"operation": "claude/resume", "session_id": sid, "outcome": "unknown"}
        _, resumed = claude_turn(cwd, "Reply with only the exact TP_ nonce from my previous message.", sid)
        if resumed.get("session_id") != sid or resumed.get("result", "").strip() != nonce:
            raise ContractError("Claude session resume did not retain identity/context")
        result["checks"]["restart_and_resume_context"] = "passed"
        result.pop("inflight", None)
        return result
    except (ContractError, OSError, ValueError, TimeoutError, subprocess.TimeoutExpired) as exc:
        result.update(getattr(exc, "observations", {}))
        exc.observations = result
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="consume small subscription inference for model/resume/interrupt probes")
    parser.add_argument("--provider", choices=("all", "codex", "claude"), default="all")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = {"observed_at": datetime.now(timezone.utc).isoformat(), "pinned_versions": PINNED, "live": args.live, "providers": {},
              "unverified": ["real quota exhaustion", "real credential expiry", "Windows logout/reboot recovery", "OS-enforced process containment", "Claude graceful turn interrupt"],
              "tool_policy": "Claude exposes no tools. Codex is instructed to use none, uses a read-only sandbox, and fails if completed items show tool activity; this is not an OS security boundary."}
    with tempfile.TemporaryDirectory(prefix="turnpike-probe-") as cwd:
        for name in ("codex", "claude"):
            if args.provider not in ("all", name):
                continue
            try:
                version = command([name, "--version"])
                observed = version.stdout.strip()
                if version.returncode:
                    raise ContractError(f"Unsupported version: {observed}")
                validate_version(name, observed)
                details = (probe_codex if name == "codex" else probe_claude)(args.live, cwd)
                report["providers"][name] = {"status": "passed", "version": observed, **details}
            except (ContractError, OSError, ValueError, TimeoutError, subprocess.TimeoutExpired, EOFError) as exc:
                report["providers"][name] = {"status": "failed", "classification": error_kind(str(exc)), "error": str(exc),
                                             "observations": getattr(exc, "observations", {})}
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"provider": name, **report["providers"][name]}), flush=True)
    return int(any(p["status"] != "passed" for p in report["providers"].values()))


if __name__ == "__main__":
    raise SystemExit(main())
