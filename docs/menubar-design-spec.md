# Cooldown 菜单栏设计规格 — Coolant

> Your Mac, read like a cockpit — one ring tells the truth, and you reach into it to fire.

> 由 4 设计 agent 提案 + 设计总监综合而成（Coolant 仪表盘骨架 + Triage 行动层 + MONOSPHERE 里程表数字 + Aurora 克制脉冲）。


## 设计取舍 (rationale)

I am taking Coolant's instrument-cluster discipline as the spine, because it is the only one of the four whose restraint reads as "pro-grade tool" rather than "colorful toy dashboard" — and the brief explicitly forbids cute. From Coolant I keep: the single dominant health ring as hero, the near-monochrome graphite base with color held strictly in reserve as a warning channel, tabular SF Mono numerals, and the "spin to inspect" scrub as the genuinely distinctive interaction. That scrub is the best signature of the four: it lives inside the hero element, requires no new chrome, and answers "which subsystem is dragging the score" by sweeping — pure instrument feel.

But Coolant alone is too passive for our narrative. The product premise is "your Mac is being cooked by runaway AI processes and you want to ACT." So I graft on Triage's action-forward backbone: a prominent primary "Reap idle AI" capsule with a live reapable count in the header (the surface tells you when there is something to do), inline reveal-on-hover Kill/Reap verbs on process rows, and — critically — Triage's "lock target, then fire" Option-key gesture as a SECOND signature for the keyboard-driven pro. Two signatures coexist cleanly because they live in different layers (hero ring = diagnose; process rows = act) and never compete. I am routing every destructive action through cool's safety/dry-run layer and a confirm chip; the UI never SIGKILLs on first click. That is non-negotiable.

From MONOSPHERE I take exactly one thing, and it is load-bearing: the per-digit odometer roll on refresh ("decimal scrub"), where only the digits that actually changed animate while the tabular columns stay rock-still. This IS Coolant's "numbers count, they don't snap" principle, executed with more precision, and it doubles as the calm heartbeat of the surface — data refreshing as a faint mechanical ripple, no color flashing. I also adopt MONOSPHERE's "why the score" micro-legend (the top-3 penalty contributors computed from the CLI's own weights), surfaced inside the hero on scrub — it makes the diagnosis honest instead of a vibe. I REJECT MONOSPHERE's all-text, zero-gauge editorial layout: it is beautiful but it throws away the ring, which is a locked decision, and four vitals + two tables of pure type at 400pt reads as a wall.

From Aurora I take almost nothing structurally — the breathing-tempo-encodes-stress idea is the most distinctive concept in the set but also the riskiest for a tool literally about saving CPU, and continuous animation on a thermal monitor is self-defeating. I REJECT the mesh-gradient "weather" and the continuous breath. What I salvage from Aurora is narrower and earned: (1) the critical-state ring does ONE breathing pulse per state entry only (not continuous), so a sick Mac is noticed once, not nagged; (2) the single rare ember-spark / heat-haze reserved exclusively for a single-core >=80% "on fire" row, as the only literal flame cue; (3) the "calm is a reward you can watch" payoff — after you reap, you SEE the ring sweep back to green and freed RSS animate off the total. Aurora's KIND_COLORS dots for AI families are kept because they come straight from the codebase (claude=magenta, codex=green, etc.) and give cross-tool identity at a glance — the one place saturation is allowed below the hero.

Net: Coolant's calm instrument face + Triage's act-now control surface + MONOSPHERE's odometer precision + Aurora's earned single-pulse/ember restraint. One hero ring you diagnose by scrubbing; one process battlefield you act on by hovering or by holding Option. Monochrome until something is wrong; then exactly enough color, exactly where the data earns it.


## 评分

| 概念 | 美学 | 独特 | 可行 | 契合 | 结论 |
|---|---|---|---|---|---|
| Coolant | 9 | 8 | 8 | 8 | The strongest spine. Instrument-cluster restraint is the most credible 'pro tool' read of the four and the 'spin to inspect' scrub is the best signature — it lives inside the hero, needs no new chrome, and turns the composite score into something you interrogate. Weaknesses: it is a passive monitor when our narrative demands action, the dial motif gets forced onto inherently list-like AI/hot-proc data, and near-monochrome risks reading 'unfinished' to users primed by iStat/stats. We adopt the spine, borrow Triage's action layer to fix the passivity, and accept the monochrome bet because the hero ring + rich Liquid Glass carry it. |
| Triage | 7 | 8 | 7 | 9 | Best fit to the actual product narrative — 'see the fire, kill it in one keystroke' is exactly the cooked-by-AI story. The 'lock target then fire' Option gesture is a delightful pro affordance and the live Reap count in the header is smart (the surface tells you when there's nothing to do). Risks: action-forward UIs are dangerous (one-click SIGKILL of something load-bearing), Target Mode is invisible to novices, and 'incident console' framing can feel alarmist when the Mac is fine. We take the entire action backbone and the Option gesture, gate every kill through cool's dry-run/safety layer + confirm chip, and let Coolant's calm hero keep it from feeling like a war room when green. |
| MONOSPHERE | 8 | 7 | 6 | 6 | Gorgeous typographic discipline and the per-digit odometer roll is the single most tactile micro-interaction proposed — we steal it wholesale as the refresh motion. The 'why the score' penalty legend is also excellent and we adopt it. But the concept rejects gauges entirely, which collides with the LOCKED health-ring decision, and an all-text broadsheet of 4 vitals + 2 tables at 400pt reads as dense and cold for a glanceable menu-bar popover. Feasibility dinged because true tab-stop tabular alignment + per-digit DigitRoller everywhere is high-effort and brittle. Take the odometer and the legend; leave the no-ring layout. |
| Aurora | 8 | 9 | 5 | 6 | Most distinctive concept and the 'breath tempo IS the telemetry / calm is a reward you watch' idea is genuinely poetic. But it is the wrong bet for THIS product: continuous breathing + animated mesh gradients on a tool whose entire pitch is saving CPU/thermals is self-defeating, MeshGradient-through-material washes out in light mode, and 'alive' tips toward the toy register the brief explicitly bans. Feasibility is the lowest (continuous period interpolation, particle system, gradient smoothing all need careful taming). We salvage the disciplined parts only: ONE pulse per critical state-entry (not continuous), a rare single ember for >=80% 'on fire', the post-reap 'watch it cool' payoff, and the codebase KIND_COLORS dots. |

## 常驻信号 (menu bar)

A custom-drawn 22pt health ring sized to the menu bar (Canvas/ImageRenderer), a thin 2.25pt arc filling clockwise from 12 o'clock to health_score/100 over a faint 8% trough, with the hottest credible temperature as a compact tabular SF Mono integer trailing it (battery.temp_c if present, else cool thermal CPU temp) — e.g. a near-full mint arc and '48'. No degree glyph in the bar to stay narrow (~46pt total). Color is the ONLY thing that changes between states; the geometry is rock-still so it never twitches at the edge of vision. Thresholds mirror the CLI exactly (health_score bands 80/55).

- **NORMAL — health_score >= 80 AND memory.pressure_level == 'normal' AND no hot_proc single-core (cpu_percent * cpu_count_logical) >= 80** → Hairline mint-green arc (#34C759) on an 8%-label trough; temperature in .secondaryLabel. Deliberately boring — it disappears into the menu bar like a clock. Fully static, no animation, redraw throttled to 1Hz to spare CPU.
- **WARN — health_score 55–79 OR memory.pressure_level == 'warn' OR system.cpu_percent >= 60** → Arc color crossfades green->amber (#FF9F0A) over 600ms; the temperature number adopts full-opacity .label in amber; a single 1.5pt tick index appears at the arc's current value like a needle. No pulsing.
- **CRITICAL — health_score < 55 OR memory.pressure_level == 'critical' OR thermal.thermal_warning != 'none' OR battery.temp_c >= 45 OR any hot_proc single-core >= 80 ('on fire' overrides 'merely warm')** → Arc goes red (#FF453A); temperature turns red. The whole ring does exactly ONE 1.2s ease-in-out breathing pulse (scale 1.0->1.035->1.0, opacity 1->0.82->1) on state RE-ENTRY only, then holds steady — a heartbeat alarm, never a continuous strobe. If the trigger is specifically a single-core >=80% 'on fire' proc, a 10pt SF Symbol 'flame.fill' badge is notched at the ring's 6 o'clock gap (the only literal flame in the bar, earned by data).
- **Reduce-motion OR no temperature data available** → All pulses/crossfades become an instant color swap; the critical pulse becomes a static filled dot at the ring center plus the static flame badge. If temp is null, show the ring alone — never a '--' placeholder in the bar.

## 标志性交互

- PRIMARY — 'Spin to inspect': hovering the master health ring turns it into a live scrubbable gauge. A hairline needle snaps to wherever the cursor sits on the rim, and the bore number crossfades from the composite health_score to whichever single contributing metric that angle maps to — 12 o'clock = thermal, 3 = CPU, 6 = memory, 9 = AI-process load — each with a one-word verdict ('THERMAL · tight') and the live value. Alongside, the top-3 penalty contributors (computed from the CLI's own health-score weights: thermal_warning −20, pressure critical −25 / warn −12, cpu>=80 −15, swap>50% −15, battery temp tiers −3/−10/−20) surface as a tiny mono legend so the diagnosis is honest, not a vibe. Releasing the hover eases the needle back to the true composite with one critically-damped spring. It feels exactly like raking a chronograph bezel: the whole diagnosis lives in one dial, interrogated by sweeping not by clicking tabs.

- SECONDARY — 'Lock target, then fire': hold Option (⌥) anywhere over the popover and the surface enters TARGET MODE — every killable thing (each hot-process row, each AI family row) surfaces its Kill/Reap verb, gets a faint 8%-red crosshair underlay and a 1–9 number badge, and the footer shows '⌥ release to fire · 1–9 to lock'. Pressing a number (or releasing over a row) arms it: a 120ms recoil (scale 0.98->1.0) and a confirm chip slides in carrying cool's dry-run preview — 'Kill PID 17923 (node)? ⏎'. Return fires, routed through cool's safety/self-protection layer; the row then collapses with a 220ms height+opacity removal and its freed RSS animates off the inventory total — you watch the memory come back. This is the menu-bar analog of pressing k in cool watch.

- TERTIARY — 'Watch it cool': after a successful reap/purge, the master ring sweeps from its old value up to the new health_score over ~700ms (critically-damped, no overshoot) and recolors red->amber->green as it climbs — the 'calm is a reward you can see' payoff, the only place the ring animates its fill on demand.


## 视觉系统

### lightPalette
Near-monochrome graphite on white-tinted Liquid Glass. Popover base .regularMaterial over a white-90% scrim; instrument faces and tiles on .ultraThinMaterial. Arcs/strokes #1C1C1E at full, troughs #1C1C1E @ 8%. Text uses system .label (#000 @ ~85%), .secondaryLabel (#3C3C43 @ 60%), .tertiaryLabel (#3C3C43 @ 30%). Hairline bezels #000 @ 12%, separators .separator. >85% of pixels are grayscale at all times.

### darkPalette
Arcs/strokes #EBEBF0 on .ultraThinMaterial over near-black (#1C1C1E base). Popover .regularMaterial over a black-80% scrim with a subtle top-edge specular highlight. Text .label (#FFF @ ~90%), .secondaryLabel (#EBEBF5 @ 60%), .tertiaryLabel (#EBEBF5 @ 30%). Hairline bezels #FFF @ 14%. Dark uses slightly higher-chroma state accents so they don't muddy on glass.

### statusColors
Exactly three state accents, matching the CLI bands (80/55): calm mint-green #34C759, warn amber #FF9F0A, critical red #FF453A. Plus one reserved cool-cyan #64D2FF used EXCLUSIVELY for thermal-headroom/cooling semantics (the right satellite dial, the brand 'cool' read). Battery temp uses the same green/amber/red at 35/40/45°C. AI-family dots use the codebase KIND_COLORS mapped to native equivalents — claude #FF6FD8 (bright magenta), codex #30D158 (bright green), droid #0A84FF (bright blue), gemini #5E9EFF (blue), copilot #FFD60A (bright yellow), cursor-agent #64D2FF (cyan), aider/crush/opencode #FF453A (red), mux kinds desaturated @ 40%. Color is a signal, never a finish.

### accent
Cool-cyan #64D2FF for non-state interactive elements (links, refresh tick, the thermal-headroom dial). State colors are never used for mere decoration — only to report a value crossing its own threshold.

### typography
SF Mono (tabular, .monospacedDigit) for EVERY numeral and gauge value so digits never jitter on refresh — sizes 52 (hero score) / 24 (satellite + tile primaries) / 15 (tile secondaries, process cpu%) / 13 (mono table body) / 11 (units, /100) / 10 (uppercase engraved labels, tracked +0.6) / 10 (footer provenance). SF Pro Text for prose status lines and labels; SF Pro Rounded Semibold reserved for the one-word verdict only. No bold anywhere except the hero score (Semibold) and a single-core 'on fire' cpu% cell.

### materials
Liquid Glass throughout (Tahoe). Popover background .regularMaterial with a subtle top-edge specular highlight; each tile/card on .ultraThinMaterial with a 0.5pt hairline bezel at 12–14% label opacity. The master ring's trough is a faint inner shadow (milled recess). Primary Reap capsule uses .glassEffect()/bordered-prominent. Vibrancy picks up the desktop behind it like instrument glass; a fallback opaque face engages when contrast over a busy wallpaper drops below threshold.

### cornerRadius
Popover follows system (16pt), tiles/cards 12pt, primary capsule fully rounded, secondary buttons 8pt — all continuous curvature. Gauges are perfect circles.

### spacing
380pt wide. 16pt outer padding, 10pt inter-tile gutters, 6pt intra-row. 8pt vertical rhythm baseline so every numeral baseline aligns to a grid like a real cluster. The 2x2 vitals grid is mathematically symmetric. Process/family rows 30pt tall, aligned to a 16pt left gutter so Kill/Reap verbs form a clean right-edge column.

### iconography
SF Symbols only, hierarchical rendering, thin weight to match hairline arcs, 13–15pt at .secondaryLabel unless reflecting state: cpu, memorychip, thermometer.medium, battery.100, bolt.fill (charging), key.fill (sudo), flame.fill (data-earned: bar + on-fire rows only), xmark.octagon (kill), arrow.3.trianglepath (reap), waveform.path.ecg (open watch), arrow.clockwise (refresh). Never multicolor — keeps it pro.


## Popover 结构（宽 380pt）

### Master cluster (hero) `#masterCluster`
- **用途**: The instrument face. One glance answers 'is my Mac okay?', and on scrub it answers 'which subsystem is dragging the score?'
- **内容**: Centered 128pt health ring (2.5pt arc + faint 8% trough reading as a milled recess via inner shadow, with faint 10-unit tick marks around the rim and a thin needle-index at the current value). In the bore: health_score as 52pt SF Mono Semibold tabular (e.g. '82'), tinted by state, with a 11pt '/100' in .tertiaryLabel trailing, and a 10pt uppercase 'HEALTH' label tracked +0.6 beneath. Flanking at 4 and 8 o'clock, two 26pt satellite micro-dials: left = CPU load (system.cpu_percent), right = thermal headroom (derived from cpu_power_status/thermal_warning as a 0–100 'cool' arc in cyan #64D2FF). One quiet SF Pro status line below: 'Running cool · 14 AI processes · normal pressure.' On hover the ring becomes a scrubbable gauge (see signature interaction).
- **布局**: Dominant block, ~150pt tall, fully symmetric and centered. Occupies the top ~30% of the popover. Largest element by far; everything below is set quieter so this reads first.

### Quad vitals `#quadVitals`
- **用途**: CPU / Memory / Thermal / Battery as four restrained instrument tiles — details on demand, calm by default
- **内容**: 2x2 grid of identical .ultraThinMaterial tiles, each = a 16pt mini radial gauge on the left + a two-line tabular readout on the right. CPU: cpu_percent + load_1, an 8-bar per_cpu sparkstrip (each bar tinted green/amber/red by the CLI's _pct_color), '8P+2E' topology badge. MEMORY: used_percent ring + 'used/total GB' + a pressure_level dot (normal/warn/critical) + swap_used as a secondary tick. THERMAL: a 'sky' state (clear -> storm from thermal_warning/cpu_power_status) + low_power_mode/ac_power glyphs + CPU temp °C. BATTERY: percent ring + charging bolt + temp_c°C + cycle_count/health_percent in fine print. Each tile tints amber/red ONLY if its OWN metric crosses threshold — so 'memory is the problem' reads spatially. Null data shows an em-dash '—' in the dial, never a broken zero.
- **布局**: Uniform 2x2, 10pt gutters, each tile 12pt radius. Secondary tier, equal weight. ~140pt tall.

### On Fire — Hot Processes `#onFireHot`
- **用途**: The crisis headline: find the runaway PID and kill it now
- **内容**: Top 3 of hot_procs[] sorted by cpu_percent desc (expandable to 5). Each 30pt row: rank tick, shortened cmdline via the CLI's shorten_cmd (preserves the script-path tail so it matches cool watch), a horizontal CPU% meter bar (red fill when single-core cpu_percent*cpu_count_logical >= 80, amber 40–79, neutral graphite below), cpu_percent in tabular SF Mono, then rss + age as .tertiary metadata. Any 'on fire' (>=80% single-core) row gets a trailing 10pt 'flame.fill' and a barely-visible heat-haze shimmer behind its text — the only literal flame in the popover. Hover/focus reveals a flush-right red 'Kill' button (xmark.octagon); the card gets a 6pt red->clear top-edge bleed when any row is on fire. Empty state: 'nothing burning CPU right now.'
- **布局**: The single largest panel below the hero, directly under the vitals. ~120pt, collapsible to a one-line disclosure when nothing is hot so a calm Mac shows a calm popover.

### AI Sessions `#aiInventory`
- **用途**: Attribute the heat to AI CLI / MCP families and reap the idle ones — the domain payoff
- **内容**: procs[] grouped by kind into family rows: a KIND_COLORS dot (claude=magenta, codex=green, droid=blue, etc.), kind name, count badge, summed RSS, summed CPU%, and a thin idle gauge per row showing max idle_seconds as a draining bar tinted by the CLI's idle_color thresholds (>=1800s = red 'reapable'). Header stat line: 'AI SESSIONS · 6 families · 102 procs · 4.1 GB' (the gut-punch number from the README). Rows whose max idle >= 1800s get a faint amber left-edge and reveal an inline 'Reap' verb on hover (reaps just that family); expanding a row lists individual pids with rss/age/idle and a per-pid kill. Defaults collapsed to the 3 heaviest families.
- **布局**: Tertiary, dense logbook with monospaced figures column-aligned. Max ~4 rows visible then scrolls. ~110pt.

### Action footer + provenance `#actionFooter`
- **用途**: Quick reversible control + console-style trust line
- **内容**: A hairline-topped row: primary capsule 'Reap idle AI' with a live reapable count badge (count of procs where kind in AI_KINDS and idle_seconds > 1800), disabled+dimmed showing '0' when nothing qualifies; then icon buttons 'Purge memory' (memorychip + key.fill sudo shield), 'Open cool watch' (waveform.path.ecg), 'Refresh' (arrow.clockwise). Destructive actions show a dry-run count on hover ('would reap 6'). Below, a 10pt SF Mono .tertiary provenance line: host.machine + ' · macOS ' + host.macos + ' · ' + topology + ' · sampled 2s ago', with a tiny live-refresh tick. Last action echoes here transiently: 'reaped 31 procs · freed 1.2 GB'.
- **布局**: Footer, lowest visual weight, full width, ~44pt action row + ~16pt provenance line. Always visible.


## 数据映射

- `Bar item ring fill + bore color + all state thresholds` ← health_score (bands >=80 green / >=55 amber / <55 red, matching cooldown/ui/dashboard.py health_score)
- `Bar item trailing temperature number` ← battery.temp_c when present, else cool thermal CPU temp; null -> ring alone
- `Bar 'on fire' flame badge + critical pulse override` ← any hot_procs[].cpu_percent * system.cpu_count_logical >= 80, OR thermal.thermal_warning != 'none', OR memory.pressure_level == 'critical', OR battery.temp_c >= 45
- `Hero ring fill + bore score + 'HEALTH /100' + status line` ← health_score; system.total_processes + procs[] count + memory.pressure_level for the prose line
- `Hero scrub legend (top-3 'why' penalties)` ← recomputed from CLI weights: thermal_warning −20, pressure critical −25 / warn −12 (else used_percent>=90 −25 / >=80 −12), swap_used/swap_total>0.5 −15, cpu_percent>=80 −15 / >=60 −6, sleep_prevented+display_sleep==0 −5, battery.temp_c>=45 −20 / >=40 −10 / >=35 −3
- `Left satellite dial (CPU load)` ← system.cpu_percent (+ load_1 as label)
- `Right satellite dial (thermal headroom, cyan)` ← derived 0–100 from thermal.cpu_power_status + thermal_warning
- `CPU vitals tile` ← system.cpu_percent, load_1, per_cpu[] (sparkstrip via _pct_color), topology ('8P+2E' badge; omitted on Intel)
- `MEMORY vitals tile + whole-tile tint` ← memory.used_percent, used, total, swap_used, pressure_level (the field allowed to tint the tile)
- `THERMAL vitals tile` ← thermal.thermal_warning, cpu_power_status, low_power_mode, ac_power, sleep_prevented + CPU temp
- `BATTERY vitals tile (hidden if battery null, grid re-centers to 3-up)` ← battery.percent, charging, temp_c (35/40/45°C tiers), cycle_count, health_percent
- `On Fire — Hot Processes rows (meter color, flame, haze)` ← hot_procs[] sorted by cpu_percent desc; per-core = cpu_percent * cpu_count_logical (>=80 red+flame, 40–79 amber); cmdline via shorten_cmd(name, cmdline); rss; age
- `Per-row Kill action` ← hot_procs[].pid -> routed through cool's SIGTERM+grace+SIGKILL safety layer with dry-run preview
- `AI Sessions family rows (dot, counts, idle gauge, amber edge)` ← procs[] grouped by kind; KIND_COLORS dot; Σrss; Σcpu_percent; max idle_seconds via idle_color (>=1800s red/reapable)
- `AI Sessions header stat line` ← len(procs), distinct kinds, Σrss (e.g. '6 families · 102 procs · 4.1 GB')
- `Footer 'Reap idle AI' capsule + count badge` ← count of procs where kind in AI_KINDS and idle_seconds > 1800 -> `cool reap`; '0' disables the button
- `Footer Purge / Open watch buttons` ← `sudo purge` (key.fill sudo shield) / `cool watch`
- `Footer provenance line` ← host.machine, host.macos, system.topology, sample age
- `Graceful degradation` ← Intel: drop topology badge + collapse per_cpu to one aggregate spark. Null temps -> '—' in dials. Null battery -> hide tile, re-center grid. Empty hot_procs/procs -> 'all quiet' empty states.

## 动效

- Numbers count, they don't snap — per-digit odometer roll (from MONOSPHERE): on each ~2s refresh, only the SF Mono digits that actually changed roll vertically in place (~180ms ease-out, ~12ms stagger per position so a multi-digit change cascades left-to-right) while the tabular columns stay perfectly still. The hero score does the same at 52pt. macOS 26 .contentTransition(.numericText()) gives most of this for free.
- Arcs ease, never jump — every gauge fill animates with a critically-damped spring (response 0.5, damping 1.0) so a rising CPU arc sweeps up like a tachometer with no overshoot.
- State transitions are color-only crossfades (600ms) — geometry never moves between states. The critical-state breathing pulse fires exactly ONCE per state entry (1.2s, scale 1.0->1.035->1.0 + opacity dip), then holds.
- Hover scrub tracks the cursor 1:1 with a light interactive spring; release eases back to the true composite with one critically-damped spring.
- Target Mode crosshairs/badges fade in 100ms on Option-down; armed-row recoil is 120ms (scale 0.98->1.0); confirm chip slides in 160ms; kill/reap success collapses the row 220ms (height+opacity) and animates freed RSS off the total.
- 'On fire' ember: a single particle rises and fades over 0.9s, at most once every ~6s, only behind a >=80% single-core row — the rarest, most earned motion in the UI.
- 'Watch it cool': after reap/purge, the ring sweeps to the new health_score over ~700ms and recolors red->amber->green as it climbs.
- Reduce-motion: all springs/rolls become instant value sets; the odometer becomes a hard cut; the critical pulse becomes a static state dot + flame badge; the hover-scrub needle steps discretely between the four cardinal metrics instead of sweeping; Target Mode shows verbs+badges instantly with no recoil/slide; embers disabled. Fully usable, just stepped. Bar-item animation is suppressed entirely in the calm state and only animates on warn/critical, gated by accessibilityReduceMotion and low_power_mode.

## 组件清单

- HealthRing (Canvas: trim-arc + trough + tick marks + optional needle/flame badge; reused at 22pt bar / 128pt hero / 16pt tile / 26pt satellite via a size param)
- RadialGauge (one reusable Canvas gauge powering every dial — strokeArc .round caps, AngularGradient only for state tint, tick loop)
- OdometerNumber (per-digit DigitRoller in tabular SF Mono; only changed digits animate; reduce-motion -> instant)
- VitalTile (.ultraThinMaterial card = mini RadialGauge + two-line tabular readout + own-metric state tint + em-dash null handling)
- PerCoreSparkStrip (HStack of capsules, height/color per per_cpu[] via _pct_color, P/E split label)
- ProcessRow (rank tick + shorten_cmd text + CPUMeterBar + tabular cpu% + rss/age + reveal-on-hover Kill verb + on-fire flame/haze + Target-Mode crosshair/badge)
- CPUMeterBar (horizontal fill, red>=80 single-core / amber / neutral)
- AIFamilyRow (KIND_COLORS dot + name + count + Σrss + Σcpu% + IdleGauge + reveal-on-hover Reap verb + expandable per-pid list)
- IdleGauge (draining bar tinted by idle_color thresholds)
- StateAccent (single source of truth mapping value+threshold -> {green/amber/red}, used everywhere so color stays a pure signal)
- PrimaryActionCapsule (.glassEffect Reap button with live count badge, disabled-at-0 state)
- IconActionButton (Purge / Watch / Refresh, SF Symbol, dry-run hover label)
- ConfirmChip (slides in with cool's dry-run preview; ⏎ to fire)
- ProvenanceLine (10pt SF Mono tertiary host/sample status bar)
- ScrubLegend (top-3 penalty contributors surfaced on hero hover)
- TargetModeOverlay (Option-driven crosshair underlays + 1–9 badges + footer hint)
- SectionDisclosure (collapses On-Fire/AI sections when calm)

## SwiftUI 架构

- App entry: CoolantApp.swift — MenuBarExtra('Coolant', ...) { PopoverRootView() }.menuBarExtraStyle(.window). Bar label is a custom view (BarRingLabel) drawn with Canvas, not Text.
- BarRingLabel.swift — renders the 22pt HealthRing + trailing tabular temp via Canvas/ImageRenderer; recomputed each ~1Hz tick; suppresses animation entirely in calm state, animates only on warn/critical, gated by accessibilityReduceMotion and thermal.low_power_mode.
- PopoverRootView.swift — fixed-width 380pt VStack(spacing:0) hosting MasterClusterView, QuadVitalsView, OnFireView, AIInventoryView, ActionFooterView; owns the @StateObject StatusStore.
- StatusStore.swift (ObservableObject) — async Process shelling `cool status --json` on a 2s Timer off the main actor; decodes into Codable models; publishes @Published Status. All fields optional to survive missing temps/Intel/desktop (no battery).
- Models.swift — Codable structs mirroring the contract exactly: Status{health_score, host, system, memory, thermal, battery?, procs:[Proc], hot_procs:[HotProc]}; plus a HealthBreakdown computed locally from the same penalty weights as cooldown/ui/dashboard.py health_score for the scrub legend.
- HealthRing.swift — reusable Canvas view: trim-arc + trough + tick loop + optional needle + optional flame badge; size-parameterized for bar(22)/hero(128)/tile(16)/satellite(26).
- RadialGauge.swift — generic gauge for the satellites + vital tiles (strokeArc .round, AngularGradient state tint).
- MasterClusterView.swift — hero ring + bore OdometerNumber + satellites + status line; hosts the scrub gesture via .onContinuousHover -> atan2 angle -> metric mapping -> @State needleValue driven by .spring; gated off under reduce-motion (stepped). Reads health_score, system, memory, thermal + HealthBreakdown.
- OdometerNumber.swift — per-character DigitRoller (VStack 0–9 offset by -value*height inside .frame().clipped(), .animation(.easeOut)); or .contentTransition(.numericText()) on macOS 26; reduce-motion -> instant.
- QuadVitalsView.swift + VitalTile.swift — 2x2 grid; each tile reads its slice (system / memory / thermal / battery) and applies own-metric StateAccent; PerCoreSparkStrip reads system.per_cpu via the _pct_color port; null -> em-dash.
- OnFireView.swift + ProcessRow.swift — reads hot_procs; per-core = cpu_percent * system.cpu_count_logical; CPUMeterBar color thresholds; reveal-on-hover Kill -> ActionRunner; flame/haze on >=80%.
- AIInventoryView.swift + AIFamilyRow.swift — groups procs by kind, sums rss/cpu, max idle; KIND_COLORS + idle_color ports; reveal-on-hover Reap (scoped); expandable per-pid list.
- ActionFooterView.swift — PrimaryActionCapsule (.glassEffect) with reapable count badge (procs where kind in AI_KINDS && idle_seconds>1800), IconActionButtons, ProvenanceLine.
- ActionRunner.swift — shells `cool reap` (optionally scoped), `sudo purge` (privileged helper or osascript auth), `open` cool watch in Terminal. ALWAYS routes kills through cool's --dry-run/safety/self-protection path and surfaces the dry-run preview in ConfirmChip before firing.
- TargetMode.swift — NSEvent.addLocalMonitorForEvents(matching:.flagsChanged) detects Option -> @State targetMode; .onKeyPress (1–9, Return) arms/fires; ConfirmChip carries the dry-run preview.
- Theme.swift — StateAccent single source of truth (value+threshold -> color), KIND_COLORS map to native Color, _pct_color/idle_color ports, light/dark Color assets, material constants. Everything reads from here so color stays a pure signal.
- Ports of CLI logic to keep parity: health_score weights, _pct_color, idle_color, KIND_COLORS, AI_KINDS, shorten_cmd — ideally validated against the same fixtures used in tests/ (test_hot_procs.py, test_procs.py, test_util.py) so the app and `cool watch` never disagree.

## 待澄清问题（实现前需定）

- Two signature interactions (hero scrub + Option Target Mode) — is that one too many for a menu-bar popover, or do they coexist because they live in different layers (diagnose vs. act)? Recommendation: ship both but make Target Mode strictly opt-in/keyboard, with the scrub as the marketed signature.
- Does `cool status --json` already expose CPU/GPU temp inline, or must the app make a second `cool thermal` call per refresh? If two calls, confirm the combined latency stays under the 2s sample budget; otherwise request temp be folded into status --json.
- cpu_power_status / thermal_warning string vocabularies aren't enumerated in the contract — need the full set of possible values to map the THERMAL tile 'sky' states and the cyan headroom dial deterministically.
- sudo purge auth path: privileged helper (SMJobBless) vs. osascript admin prompt vs. routing through a `cool purge` that itself escalates — which does the CLI prefer, and can the menu-bar app reuse it without re-implementing privilege escalation?
- Should the bar item draw ANY animation in calm state, or stay fully static until warn/critical? Leaning fully static (a thermal tool animating the menu bar invites the obvious criticism) — needs a real Instruments/energy profile on the 1Hz Canvas redraw to decide.
- macOS 26 'Tahoe' material API surface: confirm .glassEffect() and MeshGradient-free Liquid Glass behaviors are stable for a MenuBarExtra(.window) child, and that vibrancy over busy wallpapers degrades to the opaque-face fallback cleanly.
- Per-pid Kill vs. family-scoped Reap safety: confirm the exact self-protection / Apple-exempt list `cool reap` enforces so the UI's confirm chip shows an accurate dry-run and never offers to kill something the CLI would itself refuse.
- Reapable-count badge semantics: should it count individual procs (matches `cool reap` behavior) or families (matches the inventory grouping)? They differ a lot (6 vs 74) and the badge must mean exactly what the button will do.

## Prototype Brief（用于 open-design 高保真原型）

Build a high-fidelity, interactive HTML/CSS mockup of the 'Coolant' menu-bar popover anchored under a fake macOS menu bar. Show DARK MODE as primary (also note the light values). Render it as a floating card 380pt wide (use 1pt = 1px), with system popover corner radius 16px, on a translucent dark Liquid-Glass surface: background rgba(28,28,30,0.72) with backdrop-filter blur(40px) saturate(1.6), a 0.5px top-edge specular highlight (inset 0 1px 0 rgba(255,255,255,0.12)), and a soft drop shadow (0 20px 60px rgba(0,0,0,0.5)). Outer padding 16px. >85% of the surface must read grayscale; color appears only where a value crosses its threshold.

TYPE: SF Mono for every number (tabular, font-variant-numeric: tabular-nums), SF Pro Text for prose/labels, SF Pro Rounded Semibold for the one verdict word. Sizes: hero score 52px Semibold, '/100' 11px, 'HEALTH' label 10px uppercase letter-spacing 0.6px, satellite/tile primary 24px, tile secondary 15px, process cpu% 15px, table body 13px, units 11px, footer 10px. Text colors dark: primary #FFFFFF@90%, secondary #EBEBF5@60%, tertiary #EBEBF5@30%. (Light mode: primary #000@85%, secondary #3C3C43@60%, tertiary #3C3C43@30%; faces on white-tinted glass.) State accents: green #34C759, amber #FF9F0A, red #FF453A, cool-cyan #64D2FF. KIND dots: claude #FF6FD8, codex #30D158, node/droid #0A84FF.

LAYOUT top→bottom:
1) FAKE MENU BAR strip (full width, 24px tall, dark) with the bar item at right: a 22px mint ring ~82% filled + '48' in SF Mono secondary.
2) MASTER CLUSTER (~150px tall, centered): a 128px health ring — 2.5px arc stroke in green #34C759 filled to 82%, on a trough rgba(235,235,240,0.08), faint 10-unit ticks around the rim, a thin needle-index at 82%. Inside the bore: '82' at 52px green Semibold, '/100' 11px tertiary, 'HEALTH' 10px uppercase tertiary beneath. At 4 o'clock a 26px CPU-load mini dial ('38%'), at 8 o'clock a 26px cyan #64D2FF thermal-headroom dial ('cool'). Below the ring: 'Running cool · 14 AI processes · normal pressure.' in 13px SF Pro secondary, centered.
3) QUAD VITALS: 2x2 grid, 10px gutter, each tile .ultraThinMaterial = rgba(255,255,255,0.06) with 0.5px border rgba(255,255,255,0.14), 12px radius, ~64px tall. CPU: 16px ring '41%' + 'load 1.84' + an 8-bar per-core sparkstrip (6 green, 1 amber, 1 red) + '8P+2E' badge. MEMORY: 16px ring '76%' + '24.1/32 GB' + amber pressure dot + 'swap 2.1' — tint this whole tile a faint amber wash (rgba(255,159,10,0.08)) to show 'memory is the problem'. THERMAL: 16px ring + 'normal' + bolt/ac glyphs + '—' temp (null demo). BATTERY: 16px ring '93%' + charging bolt + '34.2°C' (amber, since >=35) + 'cyc 312'.
4) ON FIRE — HOT PROCESSES: card header 'ON FIRE · 3 shown · 187% total' 10px uppercase, card has a 6px red→clear top bleed. Three 30px rows, each: rank tick, shortened cmd (use shorten_cmd style preserving script tail), a horizontal CPU meter bar, cpu% in mono, rss+age tertiary. Sample rows: 'node …/mcp-server/index.js' 142.0% RED bar + 🔥 flame.fill + faint heat-haze behind text (rgba(255,69,58,0.10)); 'Python …/torch/train.py' 88.0% RED+flame; 'WindowServer' 22.0% neutral bar. Show a red 'Kill' (xmark.octagon) button revealed on the top row (hover state).
5) AI SESSIONS: header 'AI SESSIONS · 6 families · 102 procs · 4.1 GB'. Three family rows: ● claude (#FF6FD8) '4 procs · 1.8 GB · 12% · idle 2m' green idle gauge; ● node (#0A84FF) '74 procs · 1.4 GB · 31% · idle 41m' RED idle gauge + faint amber left-edge + reveal 'Reap' verb; ● codex (#30D158) '3 procs · 0.6 GB · 4% · idle 38m' RED idle gauge.
6) ACTION FOOTER: hairline-topped row. Primary capsule 'Reap idle AI' (.glassEffect look, subtle border) with a red count badge '6'. Then three 28px icon buttons: Purge memory (memorychip + tiny key shield), Open cool watch (waveform.path.ecg), Refresh (arrow.clockwise). On hover the Reap capsule shows a tertiary tooltip 'would reap 6'. Below, a 10px SF Mono tertiary line: 'arm64 · macOS 26.2 · 8P+2E · sampled 2s ago' with a small pulsing live dot.

SIGNATURE INTERACTION to demonstrate (make it real, not a static note): hovering the 128px hero ring enters scrub mode — a hairline needle follows the cursor angle around the rim, the bore number crossfades from '82' to the metric at that angle (12 o'clock→THERMAL, 3→CPU, 6→MEM, 9→AI), showing the live value + a one-word verdict (e.g. at 6 o'clock: bore reads '76%', label 'MEMORY · tight' in amber), and a tiny 3-line legend appears listing the top penalty contributors ('THERMAL  ok', 'MEM  −12', 'CPU  −0'). On mouse-leave the needle springs back to 82 and the bore returns to the composite. Wire this with JS + a smooth (cubic-bezier ease) transition; on prefers-reduced-motion, step the needle discretely between the four cardinal metrics instead. Also demo Target Mode statically: an inset panel showing the same hot/AI rows with red 8%-opacity crosshair underlays, 1–9 number badges, all Kill/Reap verbs visible, and a footer hint '⌥ release to fire · 1–9 to lock', plus one ConfirmChip 'Kill PID 17923 (node)? ⏎'. Keep every numeral tabular so nothing reflows.
