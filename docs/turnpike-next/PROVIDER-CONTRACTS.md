# Installed provider contract checkpoint

Task 515, observed 2026-11-01. This is a compatibility checkpoint for the local
job-runner work, not a certification of unattended production orchestration.

| Provider | Exact version | Requested role | Live observations |
| --- | --- | --- | --- |
| Codex | 0.166.0 | `gpt-6.1-sol`, Medium | ChatGPT account; first-party route configuration; catalog model/effort; exact model response; process restart and context recall; turn interrupt |
| Codex | 0.166.0 | `gpt-6-astra`, Low | Catalog model/effort; exact model response |
| Claude | 2.1.295 | `claude-opus-5-5`, Medium | claude.ai Max account; no API-key source in the inference stream; exact model response; separate-process resume retaining session and context |

The CLI effort is requested explicitly. Codex also exposes supported effort values
in its model catalog. The Claude stream does not independently report the resolved
effort value, so it is not claimed as independently observed.

## Reproduce

From the task worktree, using the machine's existing subscription logins:

```powershell
python tools/probe_providers.py --output metadata.json
python tools/probe_providers.py --live --output live.json
python -m unittest discover -s tests -v
```

The default probe performs metadata requests only. `--live` performs small
inference/resume tests and consumes subscription allowance. It creates its own
temporary working directory and new provider sessions; it does not adopt or send
input to an existing application-development session. Reports exclude account
email, tokens and raw transcripts. Schema/evidence output belongs outside Git.

Paid API/provider environment overrides are removed for probe processes. Custom
Codex routes are rejected; thread creation/resume explicitly selects `openai` and
checks the returned provider. Claude uses safe mode, an empty tool list, and
checks its stream's API-key source. **Do not replace safe mode with bare mode:**
Claude's documented bare mode does not use subscription credentials.

Codex's read-only sandbox and instructions are not an OS-enforced no-tool boundary.
The test instructs the model to call no tools and rejects tool activity found in
both completed and interrupted turn items. Claude's initialization must expose
an empty tool list. Server permission requests are denied by the probe.

## Remaining gates

- Actual quota exhaustion and credential expiry were not induced. Classification
  uses fixtures; a production adapter must retain the original error and wait.
- Windows process-tree containment, logout/reboot behavior and orphan recovery
  remain unverified. Killing one CLI process is not proof that children stopped.
- Claude graceful interrupt requires a controlled streaming bridge or SDK
  contract check; the one-shot probe does not certify it.
- Unknown submission outcomes retain known IDs and must be reconciled. They are
  not permission to automatically replay a model turn or its tools.
- These checks do not prove multi-worker ownership, deployment authorization,
  concurrent integration, SSH submission or desktop-session availability.

The probe preserves opaque provider events while awaiting responses, rejects
malformed stdout, bounds retained unrelated events, and enforces absolute
deadlines even under a continuous event stream. Offline tests cover these failure
conditions, hostile route configuration, substituted models, session conflicts,
duplicate results, tool activity, version suffix collisions and uncertain resume.

Live evidence is under
`C:/Users/Matthew/Desktop/turnpike-evidence/provider-515/` on this workstation.

Sources: [Codex app-server](https://learn.chatgpt.com/docs/app-server),
[Claude programmatic mode](https://code.claude.com/docs/en/headless), and
[Claude model configuration](https://code.claude.com/docs/en/model-config).
