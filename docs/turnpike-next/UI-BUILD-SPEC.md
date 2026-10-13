# TURNPIKE DECK — AUTHORITATIVE BUILD SPECIFICATION
**Target: `ui/index.html` (one file, vanilla, no build step, no network).**
Spine: the **craft** direction. Every judge `mustAdopt` is grafted in; every `mustReject` is honoured and named in §8.4.

---

## 0. GROUND TRUTH (measured from `~/.turnpike/turnpike.db` before writing this; do not re-derive)

| Fact | Value | Consequence for the build |
|---|---|---|
| Messages | 770 total, 7 projects, largest project 391 | Window the timeline; 300 is the server cap |
| `kind=task` lifecycle rows | **315 (40.9%)** | Task-event collapse is the single largest visible win |
| Non-task kinds | update 292 (64%), handoff 50, answer 29, note 23, blocker 20, question 17, decision 15, directive 9 | **No badge on `update`/`note`** |
| Authors | codex 441, claude 299, deepseek 26, user 4 | The human writes ~0.5% of traffic: **no composer formatting toolbar** |
| Body length (non-task) | median 687, p90 1464, max 3479 | Clamp must key off characters, not lines |
| Body shape | **272 single-line <800ch, 149 single-line ≥800ch, 32 multi-line reports (4+ lines), 2 few-line.** Only 34 of 455 contain any newline | The wall is one unbroken paragraph at full window width, **not** hard-wrapped text |
| Lede viability | 419 bodies >280ch, **351 yield a clean first sentence**, 68 fall back | Lede extraction is the highest-yield single mechanism |
| Section leads (`ALLCAPS[, qualifier]: `) | 38 bodies, 61 sections; 2 bodies with 3 standalone caps heading lines | Structure detection pays on the 32 monsters, not the median |
| Indented evidence runs | 9 bodies; ≥2 aligned key/value rows: 3 bodies | Build `pre`/`kv`, rank them last |
| Inline entities | hashes 237 bodies / **523 tokens**; `#id` 237 bodies / **432 tokens**; Windows paths 26; POSIX 13; URLs 7 | Hash chips and task chips earn their code |
| Markdown | **0 fences**, 3 backticks, 5 bold, 5 bullet runs, 4 numbered runs | Markdown is a fallback, never the spine |
| `@mentions` | **0** | No mention pills, no mention badges, no `@` picker |
| Task-event collapse yield | 68 runs absorbing **227 of 315 rows** (max run 10) | Timeline sheds ~159 rows |
| Clamp at `est>9` | 205 of 455 clamp, 250 render whole | Correct calibration |
| Task-event parse | 199 match the move format, 109 the create format, **7 match neither** | Raw-string fallback is mandatory |
| Tasks | 88 done, 15 doing, 12 todo, 0 blocked | Done column needs explicit truncation |
| Cursors | per-agent; a stale `user` row exists in project 1 from CLI usage | Ignore `user` cursors; the human's read mark is client-local |

### 0.1 The one server change (`monitor.py`), and nothing else
Unread counts and "Needs you" cannot be derived from the existing endpoints (message ids are global, so id arithmetic across projects is invalid, and `/api/activity` is hard-capped at 40 rows). Add exactly one read-only endpoint. Everything else in this spec runs against the API as it stands today.

```python
elif u.path == "/api/attention":
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
```
Verify the count per project against the live DB with the SQL above.
**Degradation contract:** if `/api/attention` returns 404, the client sets `S.attention = null`, hides the Needs-you nav row and all count pills, and falls back to an unread **dot** derived from `project.updated_at > localStorage['tp.visit.'+slug]`. No feature crashes.

---

## 1. DESIGN PRINCIPLES (five, each actionable)

1. **One ruler.** Every row type puts its text at exactly `x = 72px`; nothing in the timeline starts anywhere else.
2. **Borders are a last resort.** A normal message row has no border, no radius, no background; separation is rhythm, weight and hue. Target: three visible border pixels per screen.
3. **Machine chatter recedes.** 315 task events and 60 commits render as 26px single-line grey rows and collapse into runs; prose owns the contrast budget.
4. **Read the report, not the blob.** Lede at 15/600, prose capped at 76ch, evidence in sunken mono, everything past ~9 estimated lines folded behind one control.
5. **Never rebuild, never rebind.** Keyed reconciliation only; a tick that changes nothing must mutate zero nodes and must never touch a node containing focus, a popover, or a drag.

---

## 2. DESIGN TOKENS (paste-ready)

```css
:root{
  /* ============ 2.1 SURFACES (dark = default; sidebar is DEEPER than canvas) */
  --bg-app:#0b0d11;        /* window frame, sidebar footer, board columns   */
  --bg-sidebar:#101319;    /* left rail                                      */
  --bg-canvas:#161a21;     /* timeline + board pane: the lightest big plane  */
  --bg-raised:#1b1f27;     /* header, composer, cards, popovers, inspector   */
  --bg-hover:#1c212a;      /* row hover on canvas                            */
  --bg-hover-sb:#171b23;   /* row hover in sidebar                           */
  --bg-active:#222833;     /* pressed, segmented-selected, disabled fill     */
  --bg-sunken:#12151b;     /* inputs, pre/kv evidence blocks                 */
  --bg-scrim:rgba(8,10,14,.62);

  /* ============ 2.2 LINES (alpha, never hex: they must not read as a grid) */
  --line-hair:rgba(255,255,255,.055);
  --line:rgba(255,255,255,.09);
  --line-strong:rgba(255,255,255,.15);
  --line-accent:#3d6ea8;

  /* ============ 2.3 TEXT (contrast measured on --bg-canvas) */
  --tx-hi:#f4f6fa;   /* 15.6:1  channel title, lede, hovered author        */
  --tx:#d5dae3;      /* 12.3:1  message body, task titles                  */
  --tx-2:#a7aebb;    /*  7.8:1  secondary prose, commit subjects, evidence */
  --tx-3:#7d8695;    /*  4.7:1  timestamps, meta, system rows              */
  --tx-4:#5c6473;    /*  3.0:1  DECORATIVE ONLY: markers, icons, disabled  */

  /* ============ 2.4 ACCENT + SEMANTIC */
  --accent:#6ea8fe; --accent-solid:#2f6df6; --accent-solid-h:#3f7bff;
  --accent-solid-a:#2a62dd; --accent-wash:rgba(110,168,254,.13);
  --accent-line:rgba(110,168,254,.35);
  --ok:#3fb950;     --ok-tint:rgba(63,185,80,.14);
  --warn:#d1a418;   --warn-tint:rgba(209,164,24,.13);
  --danger:#e5534b; --danger-tint:rgba(229,83,75,.14);

  /* ============ 2.5 IDENTITY (configuration, single owner: the IDENTITY map) */
  --claude:#d97757; --codex:#74c69d; --deepseek:#9d7cfe; --user:#6ea8fe;
  --claude-tint:rgba(217,119,87,.18); --codex-tint:rgba(116,198,157,.18);
  --deepseek-tint:rgba(157,124,254,.18); --user-tint:rgba(110,168,254,.18);
  /* stable-hash palette for project avatars */
  --p0:#6ea8fe; --p1:#74c69d; --p2:#d97757; --p3:#9d7cfe;
  --p4:#d1a418; --p5:#4fb3bf; --p6:#e08bb8; --p7:#8fa4c9;

  /* ============ 2.6 KIND (badges only; update + note get NO badge) */
  --k-directive:#6ea8fe;  --k-directive-bg:rgba(110,168,254,.14);
  --k-blocker:#e5534b;    --k-blocker-bg:rgba(229,83,75,.14);
  --k-question:#d1a418;   --k-question-bg:rgba(209,164,24,.13);
  --k-decision:#d1a418;   --k-decision-bg:transparent; /* outline variant */
  --k-neutral:#7d8695;    --k-neutral-bg:rgba(255,255,255,.06); /* handoff, answer */

  /* ============ 2.7 SECTION TONE (report renderer left rules) */
  --tone-danger:#e5534b; --tone-warn:#d1a418; --tone-ok:#3fb950;
  --tone-neutral:rgba(255,255,255,.15);

  /* ============ 2.8 TYPE */
  --f-ui:"Segoe UI Variable Text","Segoe UI",system-ui,-apple-system,sans-serif;
  --f-disp:"Segoe UI Variable Display","Segoe UI",system-ui,sans-serif;
  --f-mono:"Cascadia Mono","Cascadia Code",Consolas,ui-monospace,monospace;

  --t-display:600 20px/26px var(--f-disp);  /* empty-state + modal titles   */
  --t-title:600 16px/22px var(--f-ui);      /* channel name, inspector head */
  --t-lede:600 15px/22px var(--f-ui);       /* extracted first sentence     */
  --t-body:400 15px/22px var(--f-ui);       /* message prose                */
  --t-ui:450 14px/20px var(--f-ui);         /* sidebar, buttons, composer   */
  --t-sm:400 13px/19px var(--f-ui);         /* system rows, cards, inspector*/
  --t-meta:400 12px/16px var(--f-ui);       /* timestamps, counts           */
  --t-label:650 11px/14px var(--f-ui);      /* section heads, badges (UC)   */
  --t-mono:400 12.5px/20px var(--f-mono);   /* pre blocks                   */
  --t-mono-in:500 12px/16px var(--f-mono);  /* hash/path/branch chips       */
  --tracking-label:.055em; --tracking-title:-.006em;

  /* ============ 2.9 SPACE / RADIUS */
  --s1:2px; --s2:4px; --s3:6px; --s4:8px; --s5:12px; --s6:16px;
  --s7:20px; --s8:24px; --s9:32px; --s10:40px; --s11:48px;
  --r-chip:4px; --r-ctl:6px; --r-card:8px; --r-panel:10px; --r-modal:12px;
  --r-pill:999px;

  /* ============ 2.10 ELEVATION */
  --sh-1:0 1px 2px rgba(0,0,0,.45);
  --sh-2:0 4px 14px -3px rgba(0,0,0,.55), 0 0 0 1px rgba(255,255,255,.05);
  --sh-3:0 18px 52px -14px rgba(0,0,0,.72), 0 0 0 1px rgba(255,255,255,.07);
  --sh-inset-top:inset 0 1px 0 rgba(255,255,255,.045);
  --ring:0 0 0 2px var(--bg-canvas), 0 0 0 4px rgba(110,168,254,.55);

  /* ============ 2.11 MOTION (six animations exist; see 4.16) */
  --d-fast:90ms; --d-ui:140ms; --d-panel:200ms; --d-enter:280ms; --d-flash:900ms;
  --e-out:cubic-bezier(.2,.7,.3,1);
  --e-in:cubic-bezier(.4,0,1,1);
  --e-spring:cubic-bezier(.16,1,.3,1);

  /* ============ 2.12 GEOMETRY CONSTANTS (the ruler) */
  --gutter:36px;      /* avatar column        */
  --gap:12px;         /* gutter to content    */
  --pad-x:24px;       /* pane horizontal pad  */
  --origin:72px;      /* = pad-x + gutter + gap. NOTHING starts elsewhere */
  --measure:76ch;     /* prose max-width      */
  --row-proj:34px; --row-nav:30px; --row-sys:26px; --row-sec:32px;

  /* ============ 2.13 Z */
  --z-day:10; --z-hover:20; --z-header:30; --z-pop:40;
  --z-drawer:50; --z-toast:60; --z-modal:70;
}

[data-theme="light"]{
  --bg-app:#e8eaee; --bg-sidebar:#f0f1f4; --bg-canvas:#ffffff; --bg-raised:#ffffff;
  --bg-hover:#f5f6f8; --bg-hover-sb:#e9ebef; --bg-active:#e2e5ea; --bg-sunken:#f4f5f7;
  --bg-scrim:rgba(16,20,28,.35);
  --line-hair:rgba(0,0,0,.07); --line:rgba(0,0,0,.12); --line-strong:rgba(0,0,0,.18);
  --tx-hi:#12151a; --tx:#1b1e24; --tx-2:#4a5160; --tx-3:#6b7280; --tx-4:#8b93a1;
  --claude:#b6532f; --codex:#2f8f63; --deepseek:#6c45d8; --user:#1a6ad4;
  --sh-1:0 1px 2px rgba(16,20,28,.10);
  --sh-2:0 4px 14px -3px rgba(16,20,28,.14), 0 0 0 1px rgba(0,0,0,.05);
  --sh-3:0 18px 52px -14px rgba(16,20,28,.20), 0 0 0 1px rgba(0,0,0,.06);
  --ring:0 0 0 2px var(--bg-canvas), 0 0 0 4px rgba(47,109,246,.45);
}

@media (prefers-reduced-motion:reduce){
  *,*::before,*::after{ animation-duration:1ms!important; transition-duration:1ms!important }
  .row-enter{ transform:none!important }
}
```

Global rules that ship with the token block:

```css
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;font:var(--t-ui);background:var(--bg-canvas);color:var(--tx);
     display:flex;overflow:hidden;font-synthesis:none}
.ts,.count,.num,.mono,.hash{font-variant-numeric:tabular-nums}
::selection{background:rgba(110,168,254,.30);color:var(--tx-hi)}
:where(a,button,[tabindex],input,textarea,select,[role=button]):focus-visible{
  outline:2px solid var(--accent);outline-offset:2px;border-radius:var(--r-ctl)}
*{scrollbar-width:thin;scrollbar-color:transparent transparent}
*:hover{scrollbar-color:#39414f transparent}
::-webkit-scrollbar{width:10px;height:10px}
::-webkit-scrollbar-thumb{background:transparent;border:3px solid transparent;
  background-clip:padding-box;border-radius:5px}
:hover::-webkit-scrollbar-thumb{background:#39414f;background-clip:padding-box}
```

Theme is `<html data-theme>` from `localStorage['tp.theme']`, default `dark`, toggled from the sidebar footer menu and the palette. **No density presets. No resizable panels.** (Rejected as scope inflation.)

---

## 3. LAYOUT AND REGIONS

```
┌──────────────┬──────────────────────────────────────────────┬────────────┐
│ SIDEBAR 260  │ CHANNEL HEADER                        60px   │ INSPECTOR  │
│ brand     48 ├──────────────────────────────────────────────┤ 320px      │
│ nav     2x30 │ ATTENTION BANNER (conditional)        36px   │            │
│ PROJECTS  26 ├──────────────────────────────────────────────┤ sections   │
│ rows      34 │ TIMELINE (or BOARD)  flex:1 overflow-y:auto  │ scroll     │
│ ...          │ padding 12px 0 16px; rows pad 8px 24px       │            │
│ ARCHIVED  26 ├──────────────────────────────────────────────┤            │
│ footer    44 │ COMPOSER  margin 0 24px 20px, auto 88..288   │            │
└──────────────┴──────────────────────────────────────────────┴────────────┘
```

| Region | Size | Surface | Border |
|---|---|---|---|
| Sidebar | `width:260px;min-width:260px` (never flexes) | `--bg-sidebar` | right 1px `--line` |
| Main | `flex:1;min-width:560px` | `--bg-canvas` | none |
| Channel header | 60px, sticky, `z:var(--z-header)` | `--bg-canvas` | bottom 1px `--line-hair` + `box-shadow:0 1px 0 rgba(0,0,0,.25)` |
| Attention banner | 36px, conditional | `--danger-tint` / `--warn-tint` | 2px left rule in the matching hue |
| Timeline | `flex:1;overflow-y:auto;overscroll-behavior:contain;scrollbar-gutter:stable` | `--bg-canvas` | none |
| Composer | `margin:0 24px 20px`, min 88px, max 288px | `--bg-raised` | 1px `--line`, `--r-panel`, `--sh-1,--sh-inset-top` |
| Inspector | 320px | `--bg-raised` | left 1px `--line-hair` |

**Breakpoints** (plain `@media` on `body`; arithmetic: 260 + 320 chrome, main needs ≥ 630px measure + 48px padding):

| Width | Behaviour |
|---|---|
| ≥ 1440 | Inspector docked, open state persisted per project in `tp.insp.<slug>` |
| 1180–1439 | Inspector becomes a right overlay: `position:absolute;top:60px;right:0;bottom:0;width:320px;box-shadow:var(--sh-3)`, scrim `--bg-scrim`, `translateX(16px)→0` over `--d-panel`, closes on Esc / outside click |
| 940–1179 | Sidebar 220px; project row hides the count pill, shows a 5px dot |
| 720–939 | Sidebar collapses to a **56px icon rail**: 28px project avatars only, name in `title`, brand becomes a 24px mark, hamburger at top |
| < 720 | Sidebar is an overlay drawer (`Ctrl+B` or the rail hamburger), `--z-drawer` |

Board replaces the timeline in-place (tab switch, no route). In Board view the composer is hidden and the Board's own add-task row takes over.

---

## 4. COMPONENT SPECS

### 4.0 Icon system
One hidden sprite at the top of `<body>`: `<svg style="display:none"><symbol id="i-*" viewBox="0 0 16 16">…</symbol>…</svg>`; every use site is `<svg class="ic"><use href="#i-x"/></svg>`.

```css
.ic{width:16px;height:16px;flex:none;fill:none;stroke:currentColor;stroke-width:1.25;
    stroke-linecap:round;stroke-linejoin:round;vertical-align:-3px}
.ic-sm{width:14px;height:14px;stroke-width:1.35}
```
Drawing rules (binding): 16px box, 1px inset so the drawn area is 14px, 1.25 stroke, terminals on half-pixel centres (`.5`, `1.5`) so they stay crisp at 100% DPI, corner radius 1.5, no fills except `i-dot` and `i-dots`. **Required set, 14 symbols:** `i-mark, i-commit, i-branch, i-check, i-arrow-r, i-plus, i-filter, i-bolt (summon), i-panel-r, i-search, i-chevron-d, i-copy, i-dots, i-send`. Path data is authored against these rules at build time and **eyeballed at 100% zoom in WebView2 before merge**; do not treat any pre-written coordinate list as verified. Never mix a unicode glyph with an SVG icon in one row (the kanban drag affordance is `i-dots` rotated 90deg, not `⋮⋮`).

### 4.1 Avatars and presence
`avatar(name, size)` is one function and one CSS class driven by `--who` and `--av`:

```css
.av{width:var(--av);height:var(--av);border-radius:var(--r-card);flex:none;
    display:grid;place-items:center;user-select:none;
    background:color-mix(in srgb, var(--who) 18%, var(--bg-canvas));
    color:color-mix(in srgb, var(--who) 88%, #fff);
    box-shadow:inset 0 0 0 1px rgba(255,255,255,.06);font-weight:700}
```
Monograms are unique so identity never rests on hue alone: **claude C, codex X, deepseek D, user U**; unknown authors take `hash(name)%8` from `--p0..--p7` and their first letter. Sizes: **36** (message leader), **26** (footer presence stack), **20** (sidebar project, inspector, board card), **16** (system rows). Letter size = `round(size*0.39)`.

Presence ring (10px dot, bottom-right, 2px cutout in the parent surface):
| Age of `last_seen` | Ring |
|---|---|
| < 120s ("active") | solid `--ok` |
| < 30m | 2px `--ok` hollow ring |
| < 24h | solid `--tx-4` |
| ≥ 24h or never seen | hollow `--tx-4` ring |

Fixed order everywhere: **claude, codex, deepseek, user**. Active agents sort first only inside the footer stack.

### 4.2 Sidebar

**Brand row** (48px, `padding:0 12px 0 16px`, flex): wordmark `Turnpike` in `--t-title`/`--tx-hi`/`letter-spacing:var(--tracking-title)` (never accent-coloured); then the **connection dot** at `margin-left:8px`, 6px circle:
- SSE open: `--ok`, 2.4s breathing `box-shadow:0 0 0 0 rgba(63,185,80,.45) → 0 0 0 5px transparent`.
- SSE dead, poll alive: `--warn`, static, `title="live updates lost, polling every 10s"`.
- Both dead: `--danger`.
Right: two 28px ghost icon buttons, `i-search` (palette) and `i-plus` (create-project modal).

**Nav rows** (30px, `margin:0 8px 1px`, `--r-ctl`, grid `16px 1fr auto`, gap 10):
- `Activity` (`i-dots` rotated? no: `i-commit`), goes to the all-projects view.
- `Needs you` with a count pill in `--danger` when > 0, hidden entirely when `/api/attention` is unavailable or the total is 0.

**Section header** (26px, `--t-label` uppercase `--tx-4`, `padding:0 16px`, `position:sticky;top:0;background:var(--bg-sidebar)`): `PROJECTS` and `ARCHIVED` (status `done`/`archived`, collapsed by default, count on the right). 10px `i-chevron-d` rotates -90deg when collapsed; state in `tp.sec.<name>`.

**Project row** (34px, `margin:0 8px 1px`, `padding:0 10px 0 12px`, `--r-ctl`, grid `20px 1fr auto` gap 10):
- 20px project avatar (`--r-chip`) with the stable-hash hue.
- Name `--t-ui` `--tx-2`, `overflow:hidden;text-overflow:ellipsis`.
- Trailing, at most one: unread count pill (`min-width:18px;height:16px;padding:0 5px;--r-pill;background:var(--accent-solid);color:#fff;font:var(--t-meta);font-weight:600`) → else a 5px `--tx-4` dot when `last_msg_id > readMark` but the count is unknown → else nothing. A 6px `--danger` dot renders immediately left of the pill when `needs > 0`.
- `title` carries the relocated meta: `active · 3 open · 200 msgs · 37/40 done`.

| State | Treatment |
|---|---|
| default | `--tx-2`, transparent |
| hover | `background:var(--bg-hover-sb)` (90ms linear, background only) |
| **unread** | name `--tx-hi` weight 600 + count pill. That is the entire unread treatment. |
| selected | `background:var(--accent-wash)`, name `--tx-hi` 600, `box-shadow:inset 2px 0 0 var(--accent)` |
| focus-visible | global ring |
| draft present | 12px `i-copy`→ no: pencil glyph (`i-plus` is not it; use a 12px pencil in the sprite as part of `i-copy`'s family) in `--tx-4` at the trailing edge, replacing nothing (pill wins if both) |
| stalled (`doing` task and no message for 24h) | name at `opacity:.55` |

**Footer** (44px, `border-top:1px solid var(--line-hair)`, `background:var(--bg-app)`): the presence stack (four 26px avatars, `margin-left:-7px` overlap, first none, descending `z-index` so the leftmost is on top, each ringed `2px solid var(--bg-app)`), then `2 active` in `--t-meta`/`--tx-3`, then a `i-dots` menu (Theme, Keyboard shortcuts, About). The whole stack is one button opening a 240px popover listing each identity with its ring, name in brand hue, and `last seen 79m ago`.

**Deleted from the sidebar:** the three create-project inputs and button, the `[active] N open · N msgs · N/N done` line, and the 4px mini progress bar.

### 4.3 Channel header (60px, two lines)
`padding:0 16px 0 24px`, `display:grid;grid-template-columns:1fr auto;align-items:center`.

- Line 1: project name `--t-title` `--tx-hi`; status pill right of it (`--t-label`, 18px, `padding:0 7px`, `--r-pill`, `background:rgba(255,255,255,.06)`, `--tx-3`; `active` gets `--ok` on `--ok-tint`).
- Line 2 (topic): `project.goal`, single line, `--t-meta` `--tx-3`, ellipsis, `cursor:pointer` → opens the inspector. Empty: `Set a goal with the CLI` in `--tx-4` (read-only: **there is no goal endpoint**).
- Right cluster (gap 6px, vertically centred across both lines):
  - **Segmented tabs** `Activity | Board`: 28px, `background:var(--bg-sunken)`, `--r-ctl`, 2px inner pad; selected segment `background:var(--bg-active)`, `--tx-hi`, `--sh-1`; the selected background slides via `transform` over `--d-ui`. Board segment carries `12/40`.
  - `i-filter` icon button. When either filter is off: `color:var(--accent)` plus a 5px `--accent` dot at its top-right. Popover 240px with two switch rows carrying live counts (`Commits 47`, `Task events 312`), persisted in `tp.filter.<slug>`.
  - **Summon split button**: `Summon` ghost segment + 22px caret segment separated by a 1px `--line` divider. Menu lists three agents, each row: 20px avatar, name in brand hue, last-seen in `--tx-3`. On invoke: inline 14px spinner → `i-check` + `Summoned` for 2.4s → revert; failure raises a toast with the server's error string.
  - `i-panel-r` inspector toggle, `--accent` when open.

### 4.4 Attention banner (36px, conditional)
Renders when `needs > 0` or `blocked_tasks > 0` for the selected project. Background `--danger-tint` (blockers/blocked tasks) else `--warn-tint`; 2px left rule in the matching hue; `--t-sm`.
Text: `2 items need you · claude is blocked on DEV_PASSWORD` (excerpt truncated at 90 chars). Actions: `View` (scrolls to the oldest such message and flashes it) and `Dismiss` (session-scoped, per project, clears on new item).

### 4.5 Timeline container and the shared row grid

```css
#timeline{padding:12px 0 16px}
.row{display:grid;grid-template-columns:var(--gutter) minmax(0,1fr);
     column-gap:var(--gap);padding:8px var(--pad-x);position:relative;
     content-visibility:auto;contain-intrinsic-size:0 64px}
.row:hover{background:var(--bg-hover)}
```
The hover background bleeds edge to edge. No border, no radius, no card. `content-visibility` is only permitted because §6 ships an app-owned find bar.

### 4.6 Message row (leader)
- **Avatar**: 36px, `transform:translateY(1px)` (optical: sits on the name's cap height). Active agents get a second inset ring in the brand hue at 55%.
- **Name line** (20px, baseline aligned):
  - author `--t-body`/650 in brand hue, `letter-spacing:-.003em`, click opens the agent popover.
  - **kind badge**, only for `directive, blocker, question, decision, handoff, answer` (140 of 455 messages). 16px tall, `padding:0 6px`, `--r-chip`, `--t-label` uppercase. `blocker` = `--k-blocker` on `--k-blocker-bg` with `inset 0 0 0 1px rgba(229,83,75,.30)`; `directive` = `--k-directive` on `--k-directive-bg`; `question` = `--k-question` on `--k-question-bg`; `decision` = `--k-decision` text on transparent with `inset 0 0 0 1px currentColor` at 40%; `handoff`/`answer` = `--k-neutral` on `--k-neutral-bg`. **Never a saturated fill with dark text.**
  - timestamp `--t-meta` `--tx-3`, `margin-left:8px`, `4:52 PM` same day / `Aug 11, 4:52 PM` older, `title` = ISO.
  - `#id` is **not rendered**.
- **Row accent**: `blocker` and `directive` leaders only get `box-shadow:inset 2px 0 0 var(--k-blocker|--k-directive)`. 35 of 770 rows. No other message carries a rule.
- **Body**: §5.

### 4.7 Grouped (consecutive) message row
`groupWith(prev, cur)` is true when **all** hold: same `author`; both are message rows (not task/commit/divider); `cur.created_at - prev.created_at <= 5 min`; nothing sits between them in the rendered order; `cur.kind` is not `directive` and not `blocker` (loud kinds always start a group).

```css
.row.grouped{padding-top:2px}
.row.grouped .gutter::after{content:attr(data-time);font:var(--t-mono-in);
  color:var(--tx-3);opacity:0;display:block;text-align:right;padding-right:2px}
.row.grouped:hover .gutter::after{opacity:1}
```
Avatar and name line are omitted; the empty 36px gutter reveals `4:52` on hover in `--tx-3` (not `--tx-4`: it is load-bearing text).

### 4.8 Hover action cluster
`position:absolute;top:-14px;right:16px;height:30px;background:var(--bg-raised);border:1px solid var(--line);border-radius:var(--r-ctl);box-shadow:var(--sh-2);z-index:var(--z-hover)`, `opacity:0→1` over 90ms, no transform. Shown on `.row:hover, .row:focus-within`.
Buttons (28px ghost, 16px icon): **`i-copy` copy body**, **`i-search` find similar? no** — exactly four: `i-copy` (copy body text), `i-chevron-d` (expand/collapse this report), `i-arrow-r` (jump to the referenced task, rendered only when the body contains a live task chip), `i-dots` (menu: Copy permalink `#744`, Copy as markdown, Mark unread from here).
**No reactions, threads, pins or saves in any form, including disabled stubs.** No table backs them.

### 4.9 System rows: commits and task events

```css
.sys{display:grid;grid-template-columns:var(--gutter) minmax(0,1fr);column-gap:var(--gap);
     padding:3px var(--pad-x);min-height:var(--row-sys);align-items:center;
     font:var(--t-sm);color:var(--tx-3);content-visibility:auto;contain-intrinsic-size:0 26px}
.sys .ic{color:var(--tx-4);margin:0 auto}
```

**Commit row**: `i-commit`, then `short` in `--f-mono` 12px `--accent` (click copies the full 40-char hash, chip flashes `--ok` for 600ms), author name in brand hue when `refs` matches `agent/<name>/` else `--tx-3`, subject `--tx-2` one-line ellipsis (`title` = full), branch as a ghost tag (`--t-mono-in`, `--tx-4`, `border:1px solid var(--line-hair)`, 16px, `--r-pill`, `padding:0 6px`) **rendered only when it differs from the previous commit row**, time right-aligned. No `border-left` ownership stripe.

**Commit cluster**: ≥ 2 consecutive commits by the same author collapse to one row: `i-branch` + `codex pushed 4 commits to agent/codex/task-95` + `i-chevron-d`. Expanded children indent to the same 72px origin with the hash column tabular so hashes form a clean vertical block.

**Task-event row**: re-composed, never echoed. Parse in this order, and **fall back to the raw string if neither matches** (7 of 315 rows do not match today):
```js
/^task #(\d+) "(.*)": (\w+) -> (\w+)(?:, assignee -> (\S+))?$/
/^created task #(\d+) "(.*?)"(?: \(assigned to (\S+)\))?$/
```
Renders as `claude started #113 Phase 0: stopgap session restore CLI` where the author is brand-coloured, `#113` is a `--tx-4` mono chip, the title is `--tx-2`, and the verb comes from the target status: `todo→doing` = "started" (`i-arrow-r`), `→done` = "finished" (`i-check`), `→blocked` = "blocked" (`i-arrow-r`, text `--danger`), `→todo` = "reopened", `created` = "added" (`i-plus`), `→dropped` = "dropped".

**Task-event collapse is mandatory**: ≥ 2 consecutive task events within 10 minutes collapse into one 26px row, `codex updated 4 tasks · 3 done, 1 started` + `i-chevron-d`. Measured yield: 68 runs absorbing 227 of 315 rows.

### 4.10 Day divider, unread divider, jump pill

```css
.day{position:sticky;top:0;z-index:var(--z-day);height:1px;margin:16px 0 8px;
     background:var(--line-hair);contain:layout}
.day>span{position:relative;top:-9px;left:var(--pad-x);display:inline-block;
     padding:1px 10px;background:var(--bg-canvas);border:1px solid var(--line-hair);
     border-radius:var(--r-pill);font:var(--t-label);letter-spacing:var(--tracking-label);
     color:var(--tx-3)}
.day.stuck>span{background:var(--bg-raised);box-shadow:var(--sh-1)}
```
Labels `TODAY`, `YESTERDAY`, `WED, AUG 11`. Left-aligned at 24px. The divider element must **not** carry `content-visibility` (it is 1px tall with an overflowing child); `contain:layout` keeps it stable next to contained rows.

**Unread divider**: same construction, 1px `rgba(229,83,75,.55)` line with a right-aligned `NEW` label in the same hue. Inserted at the first message with `id > readMark[slug]`. Computed **once on channel entry** and pinned for the visit.

**Read model** (client-local; the server's `cursors` are per agent and the stale `user` row is ignored): `tp.read.<slug>` = last message id the human has seen. It advances when the timeline is scrolled within 80px of the bottom for 600ms, when `Esc` is pressed in the channel, or when the human posts. `tp.visit.<slug>` = ISO of last entry (fallback path only).

**Jump pill**: shown when the scroller is > 400px from the bottom and new rows arrived. `position:absolute;bottom:20px;left:50%;transform:translateX(-50%)`, 30px, `--accent-solid`, `#fff`, `--r-pill`, `--sh-2`, `3 new messages` + `i-chevron-d`, entering `translateY(8px)→0` over `--d-ui`.

### 4.11 Composer
```
┌──────────────────────────────────────────────────────┐
│ Message #turnpike-next                               │ textarea 15/22, 44..240px
├──────────────────────────────────────────────────────┤
│ [● directive ▾]                   Ctrl+Enter  [Send] │ 36px toolbar
└──────────────────────────────────────────────────────┘
```
- Textarea: transparent, borderless, `padding:12px 14px 6px`, `resize:none`, auto-grow (`height:auto; height:scrollHeight`) capped at 240px then internal scroll.
- `:focus-within` on the wrapper: `border-color:#4b7fd4; box-shadow:0 0 0 3px rgba(110,168,254,.20), var(--sh-inset-top)`. The textarea itself never shows a ring.
- **Kind selector**: custom button (never a native `<select>`), 26px, ghost, `--t-meta`, showing a 6px kind-coloured dot + label + 10px caret. Popover lists the four kinds the monitor can post as `user`, each with a one-line description: `directive - overrides the agents' current plan`, `question - you need an answer before they continue`, `answer - replies to an agent's question`, `note - context, no action implied`.
- Consequence cue: choosing `directive` gives the wrapper `box-shadow:inset 3px 0 0 var(--accent), var(--sh-1)` and the placeholder becomes `Directive to all agents (overrides their current plan)…`; `question` does the same in `--warn`.
- **Send**: `--accent-solid`, `#fff`, 28px, `padding:0 12px`, `--r-ctl`, `--t-ui`/600, `i-send` 14px; disabled = `background:var(--bg-active);color:var(--tx-4)`. `Ctrl+Enter` hint sits left in `--t-meta`/`--tx-4`, hidden below 900px.
- **Ctrl+Enter sends. Enter inserts a newline. This is never inverted.**
- **Drafts** per project in `tp.draft.<slug>` = `{kind, body}`, restored on switch, cleared on send, surfaced as the sidebar pencil.
- **No formatting toolbar, no `@` picker, no `#` picker.** The human authored 4 of 770 messages; `#113` typed as text already renders as a chip.

### 4.12 Board (full canvas)
`padding:20px 24px;display:grid;grid-template-columns:repeat(4,minmax(260px,1fr));gap:16px;height:100%`. Below 1100px of available width: horizontal scroll, 280px fixed columns, `scroll-snap-type:x proximity`.

- **Column**: `background:var(--bg-app)` (recessed, so cards float), `--r-panel`, `padding:8px`, flex column. Header 32px: `--t-label` `--tx-3` + count in an 18px `rgba(255,255,255,.06)` pill + spacer + 22px `i-plus` (todo column only, visible on column hover).
- **Card**: `--bg-raised`, `1px solid var(--line-hair)`, `--r-card`, `padding:10px 12px`, `--sh-1`. Cards are the one place borders are correct: they are discrete draggable objects. Title `--t-sm` `--tx`, 2-line clamp. Footer 18px: 16px assignee avatar + name in brand hue, or `unclaimed` in `--tx-4` italic; `#113` right in `--t-mono-in` `--tx-4`. Status rule `box-shadow:inset 2px 0 0 <c>`: todo `--tx-4`, doing `--accent`, blocked `--danger`, done `--ok` at 45%.
- States: hover `border-color:var(--line); box-shadow:var(--sh-2); transform:translateY(-1px)` (90ms). Dragging `opacity:.85;transform:rotate(1.5deg) scale(1.02);box-shadow:var(--sh-3);cursor:grabbing`. Drop target: column gets `box-shadow:inset 0 0 0 2px rgba(110,168,254,.55);background:rgba(110,168,254,.05)` plus a 2px `--accent` insertion line with rounded caps at the computed index. The real card never moves during drag.
- **Optimistic move**: the card relocates and counts update immediately, then `POST /api/task {id,status}`; on failure it reverts with a 2s `--danger` flash and a toast carrying `Retry`.
- **Keyboard DnD**: focus a card, `[` / `]` moves it one column left/right, announced through a visually-hidden `aria-live="polite"` region (`moved to doing`).
- **Done column**: newest 10, then an explicit `Show 27 older` ghost row. No silent `.slice(-10)`.
- **Add task**: a 32px ghost `+ Add task` row that expands in place into title input + assignee menu + `Add`; `Enter` submits and keeps the row open, `Esc` cancels. Not a permanent form.

### 4.13 Inspector (320px), five sections
Each section: 12px 16px padding, `--t-label` header in `--tx-4`, separated by 1px `--line-hair`. Open/closed persisted in `tp.insp.sec.<name>`.
1. **Summary** — the living summary rendered through the **same** `formatBody` used by messages, `--t-sm`, clamped to 6 estimated lines with `more`. Read-only (no endpoint). Empty: `No summary yet. Agents keep this current after milestones.`
2. **Progress** — `12 of 40 done` in `--t-title` tabular numerals, a 6px `--bg-sunken` track with an `--ok` fill (`transition:width 400ms var(--e-out)`), then four micro-counts with status dots.
3. **Worktrees** — one row per worktree: branch in `--f-mono` 12px (brand hue when `agent/<name>/`), `+3` in `--ok`, `-1` in `--warn`, `●2` in `--danger`, each with an explanatory `title`; path in `--tx-4` truncated from the left (`direction:rtl;text-align:left`), click copies. Not a repo: `Not a git repository` + the workdir + an `Edit workdir` link that scrolls to section 5.
4. **Read cursors** — one row per agent: 20px avatar, name, then **distance**: `caught up` in `--ok` or `4 behind` in `--tx-3`, computed as `count(messages with id > cursor.last_msg_id)`. Never `claude @ #744`. Each row carries a `Summon here` ghost button on hover.
5. **Workdir** — read-only path in a `--bg-sunken` chip with `i-copy` and a pencil that swaps it for an input + `Save`/`Cancel` (Enter saves, Esc cancels). Optimistic save, `--ok` row flash for 600ms, toast on failure. **Never a permanently open text field.**

### 4.14 Global views
**Activity** (`sel === null`): the same row components with `withProject = true`. Every row is a leader (no cross-project grouping) and carries a 20px project chip before the author name (`--t-meta`, `--r-chip`, `1px solid var(--line-hair)`, `#slug`, click navigates). Bodies clamp harder (`est > 6`). No composer; instead a 40px strip reading `Pick a project to post` + a `Ctrl K` kbd chip. Terminal row at the top: `Showing the 40 most recent messages across all projects` (the endpoint's fixed cap).

**Needs you**: 640px centred column of 2-line cards from `/api/attention.items`, grouped under `Blocked` and `Questions`, sorted newest first. Card: project chip, agent avatar, the **lede only** (from `excerpt`), age, and one primary action `Open` (navigates and flashes the message). Empty: `Nothing needs you` / `3 agents are working`.

### 4.15 Empty, loading, error, toast

**Empty state** component: centred, `max-width:340px`, `margin-top:12vh`; 48px glyph drawn from the sprite at 1.25 stroke in `--tx-4`; title `--t-display` `--tx-2`; body `--t-sm` `--tx-3` at 1.6; one primary button.

| Context | Title | Body | Action |
|---|---|---|---|
| No projects | `Nothing on the bus yet` | `Create a project, point it at a repo, and summon an agent.` | `New project` |
| Empty channel | `No activity yet` | `Summon an agent, or post a directive to start the thread.` | `Summon` |
| Empty board | `No tasks` | `Agents claim tasks before building. Add the first one.` | `Add task` |
| Filtered to nothing | `Everything is filtered out` | `Commits and task events are hidden.` | `Reset filters` |
| Find, no hits | `No matches in the loaded messages` | `Only the last 300 messages are loaded.` | `Clear` |
| Disconnected | `Lost the bus` | `Can't reach the monitor on 127.0.0.1:8642.` | `Retry` |

**Skeletons**, first paint only, never on refresh, geometry identical to real rows so nothing jumps: 5 message rows of 36px avatar square + a 90px 12px name bar + 2 body bars at 96% and 68%; sidebar 6 rows of 20px square + a 60-70% bar.
```css
.skel{background:linear-gradient(90deg,var(--bg-hover) 0 40%,#22272f 50%,var(--bg-hover) 60% 100%);
      background-size:200% 100%;animation:shimmer 1.4s linear infinite;border-radius:4px}
@keyframes shimmer{to{background-position:-200% 0}}
```
Never a spinner for content; spinners only for in-flight actions (Summon).

**Reconnect banner**: after 5s of failed SSE plus one failed poll, slide a 30px strip under the header, `background:rgba(229,83,75,.13)`, `border-bottom:1px solid rgba(229,83,75,.3)`, `--t-meta` `#f0a8a2`, 12px spinner + `Reconnecting…` + `Retry`. Removes itself with a 200ms collapse on success.

**Toast**: bottom-centre above the composer, 320px, `--bg-raised`, `--sh-2`, `--r-card`, `--t-sm`, 4s auto-dismiss, max 2 stacked; failures get a 2px `--danger` left rule, a `Retry` action, and do not auto-dismiss. **Every `alert()` is replaced by this.**

### 4.16 The complete motion inventory (six, nothing else animates)
1. Row enter, **only for ids never previously in the DOM map and never on first paint**: `opacity 0→1, translateY(6px)→0`, `--d-enter` `--e-out`, plus a background flash `--accent-wash → transparent` over `--d-flash` `--e-in`.
2. Popover / menu / palette open: `opacity 0→1, scale .97→1`, `--d-fast` (`--e-spring` for the palette), transform-origin at the anchor.
3. Panel slide (inspector overlay, sidebar drawer, banners): `--d-panel` `--e-out`.
4. Progress fill width: 400ms `--e-out`.
5. Skeleton shimmer: 1.4s linear.
6. Connection dot breathing: 2.4s.
Hover/press are `background 90ms linear` only. No transitions on `width`/`height` of scrollers, no message-list layout animation.

---

## 5. THE LONG-MESSAGE SOLUTION

`formatBody(id, text) -> DocumentFragment`, memoised in `fmtCache: Map<id, DocumentFragment>`. Bodies are immutable server-side, so **it never re-runs**. Eager for the newest 40 messages; the rest are formatted on `IntersectionObserver` entry with `rootMargin:'600px 0px'`, or in `requestIdleCallback`, whichever fires first.

Ordering below is by measured yield. Mechanisms 1-3 carry the median and the 149 single-line walls; 4-6 carry the 32 monsters.

### 5.1 Mechanism 1: measure cap (all bodies)
Every prose block gets `max-width:var(--measure)` (76ch ≈ 630px at 15px Segoe) and `overflow-wrap:anywhere` so 40-char hashes never force horizontal scroll. `pre` and `kv` blocks are exempt and run to 100% of the row with their own `overflow-x:auto`. Without this, a 1300-character paragraph at 1300px pane width becomes two 100-character lines with no return sweep. This is the cheapest large win and it is parser-independent.

### 5.2 Mechanism 2: lede extraction (419 bodies qualify, 351 succeed)
If `body.length > 280` **and** the first block is prose: match `/^(.{20,200}?[.!?])(?:\s|$)/s` against the left-trimmed body; if it matches and the captured text contains no newline, emit it as `<p class="lede">` at `--t-lede` `--tx-hi`, `margin-bottom:6px`, and continue the remainder as ordinary prose. On failure (68 bodies) emit nothing special. Real output: `SHIPPED TO PRODUCTION 2026-08-11 04:47 UTC.`, `NPC SPAWN POSITIONING DEPLOYED TO PROD + a packet-125 correction where codex was right and I was wrong.`, `Round 4 buttons: root cause found and fixed at the source, not the surface.`

### 5.3 Mechanism 3: clamp and expansion (205 of 455 bodies clamp)
Estimated rendered lines, computed in the parser with **zero layout reads**:
```js
est = Math.ceil(chars / 92) + 2 * preLineCount + blockCount   // blockCount >= 1
```
`est > 9` renders clamped:
```css
.body.clamped{max-height:180px;overflow:hidden;
  -webkit-mask-image:linear-gradient(#000 118px, transparent 178px);
          mask-image:linear-gradient(#000 118px, transparent 178px)}
```
Below it, a 24px control at the 72px origin: `Show more` + `i-chevron-d`, `--t-meta` `--tx-3`, hover `--accent`, with a right-side hint in `--tx-4`: `1,240 chars · 3 sections`. Expanding animates `max-height` from 180px to the measured `scrollHeight` over `--d-panel` `--e-out`, then sets `max-height:none`.

- **Expansion state lives in `S.ui.expanded = new Set()` in memory, never in localStorage** (unbounded growth keyed by message id). A refresh tick may never re-collapse what the user opened.
- **Never clamp** `directive`, `blocker`, or `question` authored by `user` (46 of 770 rows; the messages the human needs whole).
- **Never truncate mid-block**: the mask fades, it does not cut, and the expander always exists when clamped.
- Bodies over 20,000 chars format the first 20,000 with a `Load rest` control (defensive; none exist today).
- **The line count of the source is irrelevant to this decision.** Keying off source lines lets a 3,479-char single-paragraph body render unclamped, which is the exact failure the clamp exists to prevent.

### 5.4 Mechanism 4: block classification
Normalise first: `\r\n → \n`, strip trailing spaces per line, collapse 3+ blank lines to one. **Source newlines are preserved exactly. There is no line-unwrapping pass** (only 34 of 455 bodies contain a newline and in those the breaks are deliberate).

Split into paragraphs on blank lines, then classify each line run, first match wins:

| # | Detector | Block |
|---|---|---|
| 1 | ```` ``` ```` fence (0 today, 4 lines of code) | `pre` (explicit, language label if present) |
| 2 | run of ≥ 1 line matching `/^[ \t]{2,}\S/`, collected until a non-indented non-blank line | `pre` |
| 3 | inside a `pre` run, ≥ 2 lines matching `/^[ ]{2,}(\S.{0,26}?)[ ]{2,}(\S.*)$/` | `kv` |
| 4 | ≥ 2 consecutive `/^\s{0,3}[-*•]\s+\S/` | `ul` |
| 5 | ≥ 2 consecutive `/^\s{0,3}\(?\d{1,2}[.)]\s+\S/` | `ol` |
| 6 | §5.5 section lead | `section` |
| 7 | anything else | `p` |

Typography:
- `p` — `--t-body`, `margin:0 0 8px`, `max-width:var(--measure)`.
- `pre` — `--t-mono` on `--bg-sunken`, `1px solid var(--line-hair)`, `--r-ctl`, `padding:8px 10px`, `margin:6px 0 10px`, `white-space:pre`, `overflow-x:auto`, `max-height:260px`, `overscroll-behavior:contain`, `tab-size:2`, hover `i-copy` at `top:4px;right:4px`.
- `kv` — 2-column grid `max-content 1fr`, `column-gap:16px`, `row-gap:4px`; keys `--tx-3` `--t-mono-in`, values `--tx-2` `--t-mono`. This is what turns message 744's `server main 70018b17…` manifest into an actual table.
- `ul`/`ol` — `padding-left:20px`, `li{margin-bottom:4px}`, markers `--tx-4`, `ol` tabular.

### 5.5 Mechanism 5: sections and the tone map (38 bodies, 61 sections)
A **section lead** is matched at the start of a line, or after a sentence boundary inside a single-line body:
```js
const SEC = /(?:^|(?<=\n)|(?<=[.!?])[ ])([A-Z][A-Z0-9][A-Z0-9 &/'()+._-]{1,56})((?:,[ ][a-z][^:\n]{0,70})?):[ ]/g;
```
Guards (all mandatory):
- The head must be ≥ 4 chars **or** contain a space (kills `C:\`, `A:`).
- The head must not be purely numeric.
- The colon must be followed by a space (kills `17:07`, `https://`).
- A section must be followed by at least one non-empty character, otherwise it is prose.
Also detected: a standalone whole-line caps head with no colon followed by an indented run (`FOLDED THIS ROUND`), which becomes a section with an empty qualifier.

Rendering: label in `--t-label` uppercase `--tx-2` + qualifier in `--tx-3` non-uppercase; `margin:14px 0 4px`; `border-left:2px solid <tone>` with `padding-left:10px;margin-left:-12px`. First section in a body has no top margin.

**Tone map** (label tested in order, first hit wins) decides the colour **and the default state**:

| Label matches | tone | default |
|---|---|---|
| `/BLOCK\|TRAP\|FAIL\|BROKEN\|RISK\|DO NOT\|WARN\|REGRESS\|CORRECTION\|LIMITATION/` | `danger` | **expanded** |
| `/OPEN\|NEXT\|TODO\|CARRIED\|PENDING\|HELD\|ASK\|NEEDS\|HONEST\|QUESTION/` | `warn` | **expanded** |
| `/GATE\|TEST\|PASS\|SMOKE\|VERIF\|PROVEN\|PROOF/` | `ok` | collapsed, summary shows any `\d+\/\d+` ratio found in the section |
| anything else | `neutral` | collapsed |

A collapsed section is a 32px one-line row: `i-chevron-d` + label (650, `--tx`) + qualifier (`--tx-3`) + right-aligned `6 lines · 3 hashes` in `--t-meta` `--tx-4`. Hover `--bg-hover`; click toggles; chevron rotates 90deg over `--d-fast`. **Danger and warn sections open themselves**: this is the only rule in the app that decides for the reader, and it is why a `TRAP, BURNED TODAY:` block cannot hide inside a folded report.

Section state is keyed `msgId + ':' + sectionIndex` in the same in-memory `expanded` Set. Expanding the message expands every section in it.

The parsed shape is deliberately `{label, qualifier, tone, state, lines, blocks}` so that when `docs/turnpike-next/` Phase 5 emits real modules, the regex detector is deleted and the renderer takes the module list unchanged.

### 5.6 Mechanism 6: inline entities
One pass over **text nodes only** (never inside `pre`/`kv`), escape first, operate on the DOM, one combined alternation regex so each character is scanned once:

| # | Pattern | Render |
|---|---|---|
| 1 | `\b[0-9a-f]{7,40}\b` (523 tokens) | `<code class="hash" data-full>` showing the **first 8 chars**, `--t-mono-in`, `--accent` at 85%, `background:rgba(110,168,254,.10)`, `padding:0 4px`, `--r-chip`; click copies the full value, chip flashes `--ok` 600ms, toast `Copied` |
| 2 | `` `code` `` | inline code, `--bg-sunken`, `--r-chip`, `padding:0 4px` |
| 3 | `#\d{1,5}` (432 tokens) | task chip **only if that id exists in this project's task set**; status dot + `#113`, click opens Board scrolled to the card, hover card gives title/status/assignee. Otherwise plain text (`#583` is a foreign PR number, not a task). **Never a dead affordance.** |
| 4 | `(?:[A-Za-z]:\\|\.{0,2}\/)[\w./\\-]{2,}` and `\b[\w-]+\.(?:java\|ts\|py\|json\|toml\|rs2\|md\|html)\b` (39 bodies) | `<code class="path">`, `--f-mono` 12px, `--tx-2`, `background:rgba(255,255,255,.045)`, middle-ellipsis past 44 chars (keep first 18 / last 22), full in `title`, click copies |
| 5 | `\b(?:agent\|feat\|fix\|release\|main\|master)\/[\w./-]+\b` | branch chip: `--t-mono-in`, `1px solid var(--line-hair)`, `--r-pill`, `padding:0 7px`; hue from `agent/<name>/` |
| 6 | `\*\*(.+?)\*\*` (5 bodies) | weight 650, `--tx-hi` |
| 7 | `https?://\S+` (7 bodies) | `--accent` text with `text-decoration-color:rgba(110,168,254,.4)`, `text-underline-offset:2px`, **click copies** (the app is offline; a dead link is worse than none) |

Rules 4-7 are cheap fallbacks and must not appear in the parser's demo fixture or drive any architecture.

### 5.7 What a 3,479-character report becomes
Lede at 15/600. Facts in prose at 15/400 capped at 630px. `ROOT CAUSE CLOSURE FIRST` and `WHAT IS FOLDED` folded to two 32px rows carrying `8 lines · 3 hashes`. `GATES` folded with `570/0` in its summary. `TRAP, BURNED TODAY` open with a red rule. The `HEADS` manifest rendered as an aligned two-column table of 8-char hash chips. Everything past 180px behind one `Show more (2.6k chars · 6 sections)`. Scanning cost drops from "read 3,000 characters" to "read one line and six labels".

---

## 6. KEYBOARD MODEL AND COMMAND PALETTE

One `KEYMAP` array is the single owner: the global handler binds from it and the `?` sheet renders from it. No duplicated strings.

| Key | Action |
|---|---|
| `Ctrl+K` | Command palette |
| `Ctrl+B` | Toggle sidebar |
| `Ctrl+.` | Toggle inspector |
| `Ctrl+F` | **Find in channel** (app-owned, see below) |
| `Ctrl+1..9` | Jump to the nth project |
| `Alt+↑ / Alt+↓` | Previous / next project |
| `Alt+Shift+↑ / ↓` | Previous / next **unread** project |
| `Ctrl+Enter` | Send |
| `Shift+Enter` | Newline |
| `Esc` | Close topmost layer (typeahead → hover card → popover → find bar → modal); if none open and a channel is selected, mark it read; if the composer holds text, blur |
| `/` (outside a field) | Focus composer |
| `g` then `a` / `b` | Go to Activity / Board |
| `f` | Filter popover |
| `s` | Summon menu |
| `t` | New task (Board) |
| `j` / `k` | Next / previous row when the timeline has focus |
| `o` | Expand / collapse the focused report |
| `c` | Copy the focused row's permalink |
| `[` / `]` | Move the focused board card one column left / right |
| `Home` / `End` | Oldest / newest in the timeline |
| `?` | Shortcut sheet |
| ``Ctrl+` `` | **Reserved and deliberately unbound** (Phase 3 terminal). Never bind a chord to a feature that does not exist. |

**Palette**: 560px, `top:12vh`, `--bg-raised`, `--r-modal`, `--sh-3`, entering `opacity 0→1, scale .97→1` over `--d-ui` `--e-spring`; scrim fades over 90ms with no blur (WebView2 cost). Input row 48px with `i-search` at 16px and 18px text. Results 40px: 20px leading avatar/icon, primary `--t-ui`, secondary right-aligned `--t-meta` `--tx-4`; selected row `--accent-wash` + `inset 2px 0 0 var(--accent)`. Group headers `--t-label` `--tx-4`. Max 8 visible, scrollable, arrow keys + Enter + Esc.

Sources in rank order: **projects** (fuzzy on slug and name) → **commands** → **tasks** (`#113`, title) → **agents**. Fuzzy = subsequence; `score = -firstIndex*2 - gaps + wordBoundaryBonus*3`; matched characters render at 650 in `--accent`.

Registered commands (every one maps to an endpoint that exists): `Summon claude|codex|deepseek here`, `New project`, `New task`, `Post directive`, `Toggle commits`, `Toggle task events`, `Copy workdir`, `Open board`, `Mark all read`, `Expand all reports`, `Collapse all reports`, `Toggle theme`, `Reconnect`. **Every command is also reachable by mouse; the palette is an accelerator, never the only path.**

**Find in channel** (mandatory, because `content-visibility:auto` disables native find): a 34px bar under the header with an input, `3 of 17` counter, up/down steppers, and a close button. It searches the **plain text** of the loaded messages (a `Map<id, lowercased plaintext>` built by the parser at no extra cost), auto-expands any clamped body or collapsed section containing a match, scrolls the match into view, and wraps matches in `<mark>` (`background:rgba(209,164,24,.28);color:inherit`), with the current match at `--warn-tint` plus a 1px outline. Enter / Shift+Enter step; Esc closes and removes all marks.

---

## 7. UPDATE STRATEGY (the past bug is designed out, not patched)

### 7.1 State
```js
const S = {
  projects:[], agents:[], attention:null, now:'',
  sel:null, view:'activity'|'board', insp:{open,sections:{}},
  byProject:{ [slug]:{ project, messages:Map(id->m), order:[], tasks:Map(id->t),
                       cursors:[], git:{}, ver:{} } },
  ui:{ expanded:new Set(), sysOpen:new Set(), filters:{}, drafts:{},
       readMark:{}, window:200, dragging:false, popover:null, editing:false }
};
const fmtCache = new Map();   // id -> DocumentFragment
const nodes    = new Map();   // key -> HTMLElement, per list
```

### 7.2 The one reconciler
`innerHTML` is **banned** in the timeline, board, sidebar and palette. All four use:

```js
function renderList(container, items, keyFn, createFn, patchFn){
  const seen = new Set();
  let cursor = container.firstElementChild;
  for (const item of items){
    const key = keyFn(item); seen.add(key);
    let el = nodes.get(key);
    if (!el){ el = createFn(item); el.dataset.k = key; nodes.set(key, el); }
    if (el !== cursor){ container.insertBefore(el, cursor); }   // no-op when in place
    else { cursor = cursor.nextElementSibling; }
    const h = fingerprint(item);
    if (el.dataset.h !== h){ patchFn(el, item); el.dataset.h = h; }
  }
  for (const el of [...container.children])
    if (!seen.has(el.dataset.k)){ nodes.delete(el.dataset.k); el.remove(); }
}
```
Keys: `m<id>` messages, `c<short>` commits, `d<YYYY-MM-DD>` day dividers, `g<firstKey>` collapsed system groups, `unread`, `t<id>` tasks, `p<slug>` project rows.
`fingerprint(item)`: messages `id+':'+kind+':'+body.length+':'+grouped`, tasks `id+':'+status+':'+assignee+':'+title.length`, projects `slug+':'+unread+':'+needs+':'+selected`, commits `short`. Identical fingerprint means the node is skipped entirely: **no property writes, no class writes, no reads.**
`patchFn` writes `textContent` / `dataset` / `classList` on named `[data-f=…]` sub-elements. It never rebuilds a subtree that already exists.

### 7.3 Change detection (replaces whole-payload `JSON.stringify`)
Each payload yields a **segmented** version tuple; each region compares only its own segment, so a presence heartbeat (which fires SSE via `agents.last_seen` in the server's `db_version`) never touches the timeline:

```js
ver.presence = agents.map(a=>a.name+a.last_seen).join('|');
ver.sidebar  = projects.map(p=>p.slug+p.updated_at+p.msg_count+p.open_tasks+p.done_tasks).join('|')
             + '#' + (attention ? attention.projects.map(a=>a.slug+a.unread+a.needs).join('|') : '');
ver.messages = msgs.length + ':' + (msgs.at(-1)?.id ?? 0);
ver.tasks    = tasks.length + ':' + maxUpdatedAt(tasks);
ver.git      = (git.commits?.[0]?.hash ?? '') + ':' + (git.worktrees?.length ?? 0)
             + ':' + git.worktrees?.map(w=>w.branch+w.ahead+w.behind+w.dirty).join('|');
ver.project  = project.updated_at + ':' + project.summary.length + ':' + project.workdir;
```

### 7.4 Scheduling
- SSE `onmessage` **never touches the DOM**. It sets `dirty = true` and schedules one `requestAnimationFrame`.
- Fetches are debounced 120ms trailing; at most one `/api/project` in flight per slug.
- 10s poll as fallback; the poll is a no-op while `document.hidden`.
- `/api/attention` refreshes on the same cadence as `/api/projects`.
- The flush is **deferred wholesale** (re-armed on the next rAF) while `S.ui.dragging`, `S.ui.popover`, or `S.ui.editing` is true. A card must never vanish mid-drag.
- Per-node guard inside `patchFn`: if `el.contains(document.activeElement)` or `el.matches(':hover')` and the change is cosmetic only, skip the write; if the change is structural, skip the node and mark it dirty for the next flush.

### 7.5 Scroll and focus preservation
```js
const atBottom = tl.scrollHeight - tl.scrollTop - tl.clientHeight < 80;
const anchor = atBottom ? null : firstVisibleRow(tl);           // element + its offsetTop
// ... mutate ...
if (atBottom) tl.scrollTop = tl.scrollHeight;
else if (anchor) tl.scrollTop += anchor.el.offsetTop - anchor.top;   // one batched read/write
```
All reads happen before all writes in the append path; no interleaving. `overflow-anchor` is left at `auto` on the scroller (appends land below the viewport), and the manual anchor above covers prepends. When `!atBottom` and new rows arrive, the jump pill appears instead of any scroll movement.

### 7.6 Grouping across incremental appends
Grouping is a property of adjacency, so it is recomputed **locally**, never globally:
1. The ordered key array is built from messages + commits + task events + dividers with the active filters applied.
2. `grouped[i] = groupWith(item[i-1], item[i])` (§4.7) is computed once when an item enters the array and is stored on the node as `data-g`.
3. On **append** of items `n..m`: compute grouping for `n..m`, then re-evaluate exactly one existing node, `n-1`, because a new item can only change whether the row *after* it is a leader (its own grouping flag depends on `n-2`, which is unchanged). One node touched.
4. On **out-of-order insertion** (commits arrive by timestamp via binary search on `ts`): re-evaluate the inserted node plus its immediate successor. Two nodes touched.
5. On **filter toggle or window growth**: recompute the whole visible array (≤ 200 rows, a user action, < 2ms).
6. `patchFn` flips `.grouped`, shows/hides the avatar and name line, and writes `data-time` for the hover stamp. The body is untouched: `fmtCache` already holds it.

### 7.7 Bounded DOM and history
- Render at most the newest **200** timeline items. `S.ui.window` grows by 200 when the `Load earlier` row (32px, at the top of the scroller, also fired by an `IntersectionObserver` sentinel) is used; scroll is compensated by the delta of `scrollHeight` measured in one batched pass.
- When the window reaches the full payload, the top row becomes a terminal note: `Showing the last 300 messages (server limit)`. **There is no `?before=` paging: `monitor.py` parses `since` and ignores it, and no `before` parameter exists.**
- `content-visibility:auto; contain-intrinsic-size:0 64px` on `.row`, `0 26px` on `.sys`.
- Timestamps are refreshed by one 30s interval that walks `[data-ts]` and writes `textContent` only.

### 7.8 Optimistic writes (all four mutating paths)
| Action | Optimistic | Reconcile | Failure |
|---|---|---|---|
| Post message | append a row with `id = 'tmp'+n` at `opacity:.55` | swap `tmp` for the real id on the next payload by matching `(author='user', kind, body)` within 15s | after 8s unmatched: row gets a `--danger` left rule + `Retry` / `Discard` |
| Task move | card relocates, counts update | next payload | revert + 2s `--danger` flash + toast with `Retry` |
| Task create | ghost card in `todo` | next payload | remove + toast |
| Workdir save | chip shows the new path, `--ok` flash 600ms | next payload | revert + toast |

### 7.9 Performance budget (acceptance gates)
- 391-message project: first paint under 400ms after the first response; timeline DOM under 3,000 nodes.
- A tick with no change: **zero DOM mutations**, measured by a `MutationObserver` in dev.
- A tick with one new message: exactly one appended subtree plus one patched node.
- Reconcile + repaint under 8ms + 4ms on the 391-message project.
- Typing in the composer, hovering a toolbar, dragging a card, and mid-scroll reading all survive 10 consecutive SSE ticks with zero visible change.

---

## 8. REMOVED OR RELOCATED

### 8.1 Deleted outright
| What | Why |
|---|---|
| The three create-project inputs + button pinned to the sidebar bottom | ~110px of permanent chrome for a monthly action; loudest homebrew signal. → `i-plus` in the brand row, `Ctrl+Shift+N`, palette `New project`, all opening a modal with inline field errors |
| `border` + `border-radius` + `background` on every message | Rows, not cards |
| `white-space:pre-wrap` bodies | Replaced by §5 |
| Kind badge on `update` and `note` (315 of 455 non-task messages) | A badge on the default kind carries zero information |
| `border-left:3px` ownership stripes on commit rows | Redundant with the coloured author name and the icon |
| `[active] N open · N msgs · N/N done` + the 4px mini progress bar on every project row | 4 numbers × 10 rows nobody reads → row `title` + header + inspector |
| `#767` in every meta line | → hover cluster `Copy permalink`, and `#id` chips inside bodies |
| The literal word `live` in the header | → 3-state connection dot + reconnect banner |
| `alert(r.error)` | → toast with `Retry` |
| Uppercase `RECENT ACTIVITY (ALL PROJECTS)` heading | → the Activity nav row + a real channel header |
| Silent `.slice(-10)` on the done column | → explicit `Show 27 older` |
| Native `<select>` for kind and assignee | → styled menu buttons |
| `button:hover{border-color:accent}` | → background-step hover, globally |
| Full `JSON.stringify` diffing per tick | → segmented version tuples + keyed reconciliation |

### 8.2 Relocated (nothing is dropped)
| Capability | New home |
|---|---|
| Goal | Header line 2 (topic) + inspector; read-only, no endpoint exists |
| Status | Header pill; read-only |
| Living summary | Inspector §1, rendered through `formatBody`; read-only |
| Workdir editor | Inspector §5, read-only chip + pencil → input + Save |
| Task progress | Header Board badge `12/40` + inspector §2 |
| Worktree / branch chips | Inspector §3 + inline branch chips in bodies and commit rows |
| Read cursors | Inspector §4, restated as `caught up` / `4 behind` |
| Commit / task-event filters | Header `i-filter` popover with live counts, persisted per project |
| 250px kanban strip | Full-canvas Board tab |
| Three coloured Summon buttons | Header split button + inspector per-agent button + palette |
| Create project | `i-plus` + `Ctrl+Shift+N` + palette, as a modal |
| Presence chips | Sidebar footer stack + popover |
| SSE indicator | Brand-row dot + reconnect banner |
| All-projects activity | Activity nav row and view |

### 8.3 Read-only by contract (no fake affordances)
There is **no** endpoint for goal, status, summary, project deletion, or archiving. None of these get an edit control, a pencil, or a menu item. The only mutating paths in the whole UI are: post message, create task, update task status, save workdir, summon, create project.

### 8.4 Explicitly rejected (do not build)
Hard-wrap unwrapping (2 bodies qualify, 34 at risk) · any line-count-based collapse gate · a 16-estimated-line clamp threshold · markdown-first parsing as the spine · `@mention` pills, mention badges, mention counts, and the `@` picker (0 occurrences) · the cursor rail (needs per-row `offsetTop`, which `content-visibility` and the 200-row window destroy) · path middle-ellipsis as a headline feature (implement it, keep it out of the fixture) · pre-written icon path coordinates taken as verified · the heuristic `shipped` pill or any sentiment inference · the facts strip · `claude is working…` fabricated presence · a third `Changes` view (commits are a timeline filter plus inspector §3) · threads, reactions, pins, saves, even as disabled stubs · an 8-button formatting toolbar · three density presets, resizable sidebar or inspector · localStorage-persisted expansion state · any reliance on `?before=` paging · shipping `content-visibility` without the app-owned find bar.

---

## 9. IMPLEMENTATION CHECKLIST (ordered; each step ends in a tickable gate)

**Phase A: foundation**
1. [ ] Paste the §2 token block, the global rules, and `[data-theme="light"]`; wire `tp.theme`. **Gate:** toggling theme changes every surface with zero component edits.
2. [ ] Author the 14-symbol sprite against the §4.0 grid rules; eyeball each at 100% zoom in WebView2. **Gate:** no icon is blurry, all share stroke weight.
3. [ ] Build the shell: sidebar / main / inspector, header, composer, and all five breakpoints. **Gate:** at 1439px the inspector overlays; at 900px the rail appears; nothing overflows horizontally at 720px.
4. [ ] Implement `.row` / `.sys` grids and confirm the 72px ruler with a temporary 1px debug guide. **Gate:** message text, system text, day labels and skeleton bars all start at exactly 72px.

**Phase B: engine (before any more UI)**
5. [ ] `renderList` + `fingerprint` + `nodes` registries; ban `innerHTML` outside the sprite. **Gate:** a synthetic 300-item list re-render with identical data mutates 0 nodes (MutationObserver count = 0).
6. [ ] Segmented version tuples, rAF coalescing, 120ms debounce, hidden-tab poll suppression, drag/popover/edit deferral, per-node focus guard.
7. [ ] Scroll anchor + focus preservation helpers; 200-row window + `Load earlier` + terminal row.
8. [ ] Optimistic-write helper with reconcile-or-revert and the toast contract.

**Phase C: the readability payload**
9. [ ] `formatBody` §5.4 block classifier + §5.6 inline pass, memoised by id, lazily formatted via IntersectionObserver. **Gate:** run it over all 455 non-task bodies in DevTools; 0 exceptions, 0 raw HTML leaks (`data-full` round-trip check).
10. [ ] Lede extraction. **Gate:** 351 of 419 long bodies produce a lede; spot-check ids 744, 758, 488, 475, 477.
11. [ ] Clamp + mask + `Show more` + session `expanded` Set. **Gate:** 205 of 455 clamp; a 3,479-char body renders at ≤ 340px collapsed; a tick never re-collapses.
12. [ ] Sections + tone map + collapsed summary rows. **Gate:** message 744 shows `ROOT CAUSE CLOSURE FIRST`, `WHAT IS FOLDED`, `GATES`, `HEADS`; message 758 opens `PACKET 125` and `TRAP, BURNED TODAY` by itself.
13. [ ] `pre` / `kv` blocks with copy buttons. **Gate:** 758's deploy manifest renders as an aligned two-column table.

**Phase D: the timeline**
14. [ ] Message leader + grouped rows + hover cluster + kind badges + blocker/directive inset rule.
15. [ ] Commit rows + commit clusters.
16. [ ] Task-event re-composition + raw fallback + mandatory run collapse. **Gate:** on the project with the most task events, consecutive task rows collapse into runs; unparseable bodies render raw, not blank.
17. [ ] Day dividers, unread divider, read-mark logic, jump pill.
18. [ ] Row-enter animation restricted to genuinely new ids.

**Phase E: chrome**
19. [ ] Sidebar: brand row, nav rows, sections, project rows with all six states, footer presence stack + popover.
20. [ ] Header: title, topic, segmented tabs, filter popover with counts, summon split button, inspector toggle.
21. [ ] Composer card: kind menu, drafts, auto-grow, optimistic send, consequence cues.
22. [ ] Inspector, five sections, workdir inline edit.
23. [ ] Board: columns, cards, native DnD with optimistic move, `[`/`]` keyboard move with `aria-live`, add-task ghost row, `Show N older`.

**Phase F: cross-cutting**
24. [ ] `/api/attention` in `monitor.py` + client wiring + the 404 degradation path. **Gate:** with the endpoint removed, the app still boots and shows dots instead of counts.
25. [ ] Attention banner + Needs-you view. **Gate:** counts match the SQL for every project.
26. [ ] Activity view with project chips and the `est > 6` clamp.
27. [ ] Palette + `KEYMAP` + `?` sheet rendered from the same array.
28. [ ] Find-in-channel bar with auto-expand of clamped bodies and collapsed sections. **Gate:** searching a string that lives inside a folded `GATES` section finds and reveals it.
29. [ ] Create-project modal with inline field errors (409 → `slug exists` under the field).
30. [ ] Empty states (6), skeletons (first paint only), reconnect banner, toasts.

**Phase G: the subtraction pass**
31. [ ] Open the app and delete every border that can go without losing meaning; target three visible border pixels per screen.
32. [ ] Verify the accessibility floor: `nav` on the sidebar, `role="log"` + `aria-live="polite"` on the append container announcing author + kind + lede only, `role="article"` on message rows, `role="list"` on board columns, a visible skip link to the composer, and a visible focus ring at every tab stop.
33. [ ] Final gates: **no request leaves 127.0.0.1** (network tab shows only `/`, `/icon.svg`, `/api/*`); 391-message cold render < 400ms; idle tick = 0 mutations; every capability in §8.2 reachable in ≤ 2 clicks or 1 keystroke.

**File organisation:** one `<style>` (~800 lines) with banner comments in this spec's order, the hidden sprite, `<template>` blocks for the eight row types, then one `<script>` in seven labelled sections: `CONFIG` (KEYMAP, KINDS, IDENTITY, TONE) → `store` → `parse` (pure, exposed as `window.__parse` for DevTools work against real bodies) → `render` → `commands` → `net` → `boot`. Expect **1,800 to 2,000 lines, 90 to 110 KB**. That is fine for a local file server and it is still one file with no build step.

---

**TL;DR in plain English:** Build the Slack-style rebuild on the "craft" plan. The screen becomes a dark left rail of projects (darker than the message pane, which is what makes it read as a real app), one clean conversation in the middle where every line of text starts at the same invisible left edge, and a details panel on the right holding the goal, git branches, workdir and progress that currently clutter the header. The big fix is the agents' giant posts: the app pulls out the first sentence as a bold headline, narrows text to a comfortable reading width, spots the ALL-CAPS section titles and indented hash tables the agents already write, opens anything labelled TRAP or BLOCKER by itself in red while folding the routine sections to one line each, and hides everything past about nine lines behind a "Show more" that a refresh can never re-close. Nearly half the timeline is robot task chatter, so those become quiet one-line entries that bundle into "codex updated 4 tasks". The cramped task board moves to its own full-screen tab, the always-visible "create project" form and the three coloured Summon buttons are replaced by a plus button and one menu, and a new "Needs you" list shows exactly the blockers and questions no one has answered. Under the hood the page patches single rows instead of redrawing itself, so clicking, typing, dragging and scrolling never get destroyed by the ten-second refresh. One small server addition (a read-only counts endpoint) powers unread badges and the Needs-you list, and the app still works without it.