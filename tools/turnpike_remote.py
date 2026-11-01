"""Send one versioned Turnpike board request through an existing SSH identity.

Only the fixed entry point and agent identity enter the remote command. All board
content travels as JSON on stdin. Host keys must already be trusted or pinned.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import uuid


def ssh_command(args):
    if not re.fullmatch(r"[A-Za-z0-9_.@:\[\]-]+", args.host) or args.host.startswith("-"):
        raise ValueError("Use an SSH host alias or address without shell syntax")
    if not re.fullmatch(r"[A-Za-z]:[\\/][A-Za-z0-9_ .\\/-]+", args.entrypoint):
        raise ValueError("Entry point must be a fixed Windows path without shell syntax")
    command = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
               "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=2"]
    if args.ssh_config:
        command += ["-F", str(args.ssh_config)]
    if args.identity:
        command += ["-o", "IdentitiesOnly=yes", "-i", str(args.identity)]
    if args.known_hosts:
        command += ["-o", "UserKnownHostsFile=" + str(args.known_hosts)]
    if args.port:
        command += ["-p", str(args.port)]
    command += [args.host, '"' + args.entrypoint + '" ' + args.actor]
    return command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--as", dest="actor", required=True, choices=("codex", "claude", "deepseek"))
    parser.add_argument("--entrypoint", default="C:/Users/Matthew/AppData/Local/Programs/Turnpike/cli/turnpike-ssh.cmd")
    parser.add_argument("--request", type=Path, help="JSON file; omit to read stdin")
    parser.add_argument("--request-id", help="reuse this UUID when retrying identical content")
    parser.add_argument("--identity", type=Path)
    parser.add_argument("--known-hosts", type=Path)
    parser.add_argument("--ssh-config", type=Path)
    parser.add_argument("--port", type=int, choices=range(1, 65536), metavar="PORT")
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    request_id = None
    submitted = False
    try:
        if not 0 < args.timeout <= 300:
            raise ValueError("timeout must be between 0 and 300 seconds")
        request = json.loads(args.request.read_text(encoding="utf-8-sig") if args.request else sys.stdin.read(1024*1024+1))
        if not isinstance(request, dict):
            raise ValueError("Expected a request object")
        request.setdefault("version", 1)
        if args.request_id:
            request["request_id"] = str(uuid.UUID(args.request_id))
        request.setdefault("request_id", str(uuid.uuid4()))
        request_id = request["request_id"]
        if not isinstance(request_id, str) or str(uuid.UUID(request_id)) != request_id:
            raise ValueError("request_id must be a canonical lowercase UUID")
        payload = json.dumps(request, ensure_ascii=False) + "\n"
        if len(payload.encode("utf-8")) > 1024*1024:
            raise ValueError("Request exceeds 1 MiB")
        command = ssh_command(args)
        print("Turnpike request ID: " + request_id, file=sys.stderr, flush=True)
        submitted = True
        run = subprocess.run(command, input=payload, capture_output=True, text=True, encoding="utf-8", timeout=args.timeout)
        if run.returncode:
            response = {"version": 1, "request_id": request_id, "ok": False,
                        "error": {"code": "ssh_transport_error", "message": run.stderr.strip()[-4096:],
                                  "retryable": True, "instruction": "Retry identical content with this same request ID; do not generate a new ID for a possibly accepted write"}}
            code = 3
        else:
            response = json.loads(run.stdout)
            if not isinstance(response, dict) or response.get("version") != 1 or response.get("request_id") != request_id or type(response.get("ok")) is not bool:
                raise ValueError("SSH returned an invalid Turnpike response")
            code = 0 if response["ok"] else 2
    except subprocess.TimeoutExpired:
        response = {"version": 1, "request_id": request_id, "ok": False,
                    "error": {"code": "ssh_timeout", "message": "Transport deadline expired; the remote outcome may be unknown",
                              "retryable": True, "instruction": "Retry identical content with the same request ID"}}
        code = 3
    except (ValueError, OSError) as exc:
        response = {"version": 1, "request_id": request_id, "ok": False,
                    "error": {"code": "ssh_unknown_outcome" if submitted else "client_error", "message": str(exc),
                              "retryable": submitted}}
        if submitted:
            response["error"]["instruction"] = "The request may have committed; retry identical content with the same request ID"
        code = 3 if submitted else 1
    print(json.dumps(response, ensure_ascii=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
