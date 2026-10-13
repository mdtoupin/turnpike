<!-- Provenance: Windows resource governance research (Job Objects / ConPTY / telemetry); codex subagent deliverable 2026-08-11/12,
     a Codex session -->

Recommendation: build a native Win32/C++ “agent supervisor” with one job object per managed agent/session, a lightweight dashboard, and ConPTY-backed terminal tabs only for sessions it launches. This gives broad PowerShell capability—run ordinary `pwsh.exe` with no script sandbox—while retaining reliable containment and one-click cleanup.

Architecture

- Native host: C++/Win32 + Direct2D/DirectWrite (or WinUI 3 only if development speed outweighs a modest footprint). Avoid Electron and polling-heavy WMI.
- Session launcher:
  - Create a Job Object per agent.
  - Apply limits before launch.
  - Launch PowerShell/agent through `CreateProcessW` with `PROC_THREAD_ATTRIBUTE_JOB_LIST` (Windows 10+) so membership is established at creation; alternatively create suspended, assign it to the job, then resume. This closes the child-process escape race. [Process attributes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute)
  - Do not enable either breakaway flag. Normal `CreateProcess` descendants join the job automatically; explicitly-created breakaways remain a limitation. [Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
  - Associate every job with an I/O completion port and use event-driven process start/exit and limit-notification handling.
- Terminal:
  - Use ConPTY (`CreatePseudoConsole` plus pipe pairs) for terminals owned by the app. It provides UTF-8 VT input/output and has no OS-owned console window. [Pseudoconsoles](https://learn.microsoft.com/en-us/windows/console/pseudoconsoles), [CreatePseudoConsole](https://learn.microsoft.com/en-us/windows/console/createpseudoconsole)
  - Keep an in-memory, bounded scrollback ring (e.g., 5–20 MiB/tab) and parse/render only dirty rows. Avoid logging all terminal output by default.
  - ConPTY is for console programs, not a general GUI-process host; retain a “launch externally” option for GUI tools.
- Telemetry service (one background thread/timer, publish immutable snapshots to UI):
  - 500 ms direct low-cost sampling: `GetSystemTimes`, `GetProcessTimes`, `GlobalMemoryStatusEx`/`GetPerformanceInfo`, `GetProcessMemoryInfo`, `GetProcessIoCounters`, and `QueryInformationJobObject` accounting.
  - 1 s PDH sampling for disk latency/queue and network-interface totals. Microsoft explicitly says performance counters are unsuitable above once per second; direct APIs are preferable for lower-overhead collection. [Performance counters](https://learn.microsoft.com/en-us/windows/win32/perfctrs/about-performance-counters)
  - Use `Process V2` counters on Windows 11 when using PDH: it fixes process-instance reuse issues; CPU calculations need two samples and per-process CPU can exceed 100% before normalizing by logical processors. [Collecting Performance Data](https://learn.microsoft.com/en-us/windows/win32/perfctrs/collecting-performance-data)
  - ETW is optional “diagnostic mode” only—for per-process network attribution and investigations. Do not run a broad kernel ETW session continuously; it adds complexity/overhead.
  - Dashboard: system CPU, available RAM/commit headroom, disk read/write latency and busy time, aggregate NIC RX/TX, followed by per-session CPU, private commit, working set, I/O bytes/sec, and child-process count. Job accounting is the authoritative aggregate for a managed tree.

Resource controls and recommended defaults

| Control | Default | Rationale |
|---|---:|---|
| Per-session CPU | Weight-based 3/9 normal; 1/9 paused/background; 7/9 focused | Fairness without the stutter of fixed CPU quotas |
| Global CPU reserve | Policy starts at sustained 85% total CPU; escalate at 92% | Leaves the desktop and supervisor responsive |
| Emergency CPU | Temporarily hard-cap the noisiest background jobs, floor 5% each | Only during pressure; hard caps cause bursty/throttled agent behavior |
| Per-session memory | Soft notification at min(25% RAM, configurable); no hard default cap | Agents can be spiky; warnings preserve usability |
| Aggregate managed memory | Alert when free physical RAM < 15% or commit headroom < 10–15%; throttle first | Protects against paging collapse |
| Hard memory limit | Opt-in per task, e.g. 2–6 GiB depending on machine | Job committed-memory excess makes allocations fail, which can crash a workload |
| Process count | 32/session default, user-adjustable | Prevents accidental fork storms |
| Disk | Alert on sustained latency >25 ms; emergency at >50 ms | Microsoft’s troubleshooting guidance uses those warning/critical thresholds; do not use obsolete job I/O control |
| Network | Meter always; outgoing job cap opt-in | Avoid silently breaking downloads/API calls |

Job Object capabilities are the primary guardrail:

- `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` limits process fan-out.
- `JOB_OBJECT_LIMIT_PROCESS_MEMORY` and `JOB_OBJECT_LIMIT_JOB_MEMORY` limit committed virtual memory—not merely working set. Exceeding them fails allocations. Use notification limits as an early warning, then let the user choose a hard cap. [Extended limits](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information), [Basic limits](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_limit_information)
- CPU policy: prefer weight-based CPU allocation normally. A hard cap is exact (rate is 1/100th percent units), but once a job consumes its interval budget, its threads do not run until the next interval—noticeably bad for interactive shells. [CPU rate control](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_cpu_rate_control_information)
- Apply `EcoQoS` to unfocused/background helper processes as a hint, not as an enforcement mechanism. `SetProcessInformation(ProcessPowerThrottling)` can label processes EcoQoS/HighQoS; it is scheduler/power behavior, not a dependable quota. [Quality of Service](https://learn.microsoft.com/en-us/windows/win32/procthread/quality-of-service)
- Native job network rate control is available on Windows 10+ for outgoing job traffic, plus DSCP tagging. Use it only where a cap is explicitly chosen; it does not solve inbound traffic and only one job in a nested hierarchy may hold the network-rate policy. [Job network rate control](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_net_rate_control_information)
- Do not rely on `SetIoRateControlInformationJobObject`: Microsoft marks it unsupported from Windows 10 version 1607 onward. Use telemetry, scheduling/CPU pressure, and user-facing disk warnings instead. [I/O rate-control structure](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/ns-jobapi2-jobobject_io_rate_control_information)

Adaptive policy

1. Normal: each active task gets normal CPU weight, no hard memory cap unless configured; background/unfocused tasks get EcoQoS + low weight.
2. Yellow pressure (three consecutive samples): reduce background weights, turn on EcoQoS, pause new-agent launches, surface the top CPU/memory/disk contributors.
3. Orange pressure (about 10 seconds or lower safety thresholds): apply temporary hard CPU caps to background jobs, block launches unless the user overrides, recommend stopping specific sessions.
4. Red pressure (very low available memory/commit or severe sustained disk latency): freeze launch queue, retain an always-visible “resume normal scheduling” control, and offer “graceful stop top offenders.” Never silently kill work.
5. Recovery hysteresis: require 15–30 seconds under threshold before relaxing policy. This prevents oscillation.

Controls that should be explicit in the UI

- Per session: focus/boost, background, CPU weight/cap, memory warning/hard limit, process-count cap, outbound-network cap, stop, kill, detach/open externally.
- Global: maximum concurrent agents, “reserve N logical CPUs / X GiB,” pressure policy selector (`Observe`, `Protect desktop`, `Strict`), auto-cleanup on app exit, launch queue, and emergency “stop all managed agents.”
- Show why an intervention occurred, the exact trigger, and a countdown/action history. Let users override a policy temporarily but never hide an active hard cap.

Stop/pause semantics and caveats

- “Graceful stop” should first send Ctrl+C via the managed console/process group where compatible, wait a configurable timeout, then offer force termination.
- “Kill session” maps to `TerminateJobObject`: it terminates all current job processes and they cannot postpone or handle it, effectively like `TerminateProcess` per member. [TerminateJobObject](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-terminatejobobject)
- Do not market Suspend/Resume as a safe pause. The documented APIs are per-thread; Microsoft says `SuspendThread` is primarily for debuggers and not synchronization. It can deadlock a process that holds locks, races new threads, and interacts badly with other suspend owners. [Suspending thread execution](https://learn.microsoft.com/en-us/windows/win32/procthread/suspending-thread-execution), [ResumeThread semantics](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-resumethread)
- Make “hard freeze” an advanced, warning-labeled best-effort feature, while the default “pause” means background/EcoQoS plus a low CPU weight or temporary 5% cap.
- `KILL_ON_JOB_CLOSE` is useful for ephemeral agent tasks but should be opt-in or clearly signposted: closing the last job handle terminates all its processes. A dashboard crash must not unexpectedly destroy persistent user shells unless that mode was selected. [Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
- Managed ancestry is not universal. Children created via WMI `Win32_Process.Create`, explicit breakaway, services, scheduled tasks, containers/WSL, elevation boundaries, or a process already in an incompatible job can evade/join differently. Record such processes as “uncontained,” do not claim their resource totals are enforceable.

Test strategy

- Unit-test CPU/memory threshold state machine, hysteresis, limits serialization, VT parser, and process-tree attribution using synthetic counter traces.
- Integration-test with deliberately hostile workloads: CPU spin; alloc/free and committed-memory pressure; process fork storm; massive file I/O; download/upload; Ctrl+C-aware and Ctrl+C-ignoring PowerShell; background children; explicit breakaway; WMI-created child.
- Assert: job assignment happens before user code executes; descendants inherit membership; process-count and memory limits produce the documented effects; job kill clears descendants; recovery returns caps/weights to normal.
- Run 1, 8, 32, and 100 concurrent sessions on 8/16/32+ logical-core machines, on AC and battery, and record dashboard CPU/memory overhead. Set a target such as <1% CPU idle and <100 MiB private bytes without terminal history.
- Stress app failure/restart, sleep/resume, fast user switching, UAC/elevated child launch, Windows Terminal/ConPTY resize, and Remote Desktop. CPU rate control has an RDS/DFSS limitation. [CPU rate control](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_cpu_rate_control_information)
- Manual UI test: verify stop/kill confirmation copy, impossible-to-miss active restrictions, and no false “paused” claim when only a best-effort pause took effect.

Cleaned-up request: Research a very efficient Windows 11 desktop supervisor for many concurrent AI-agent and terminal processes, covering monitoring, PowerShell freedom, resource guardrails, Windows APIs, architecture, adaptive defaults, controls, constraints, and tests—without editing files.

Layman's recap: Use Windows’ built-in job groups to keep each agent and its children together, measure the machine cheaply, slow background work only when the computer is under strain, and reserve force-kill for an explicit last resort.
