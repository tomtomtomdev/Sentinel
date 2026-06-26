# Handoff: Sentinel — API Monitoring (Onboarding + Dashboard)

## Overview
Sentinel is an API uptime/health-monitoring web app. This handoff covers two flows:

1. **Add a monitor** — onboard an API endpoint by (a) pasting a raw cURL command, (b) importing a collection file (Postman / OpenAPI / generic JSON), or (c) filling out a manual form. Every path ends with a shared "Monitoring rules" config (check interval, expected status, response assertions).
2. **Monitor dashboard** — a card grid of all monitors with live status, uptime, latency, a 24h sparkline, and last-check time, plus summary stat cards.

The product is a clean developer-tool aesthetic (Linear / Vercel / Stripe lineage): neutral grays, a single indigo accent, near-black primary buttons, monospace for code/URLs, generous whitespace, subtle 1px borders.

## About the Design Files
The file in this bundle (`Sentinel.dc.html`) is a **design reference created in HTML** — a clickable prototype showing intended look and behavior. It is **not production code to copy directly.** It is authored as a "Design Component" (a custom streaming-template format) and will not drop into a normal codebase as-is.

The task is to **recreate this design in the target codebase's existing environment** (React, Vue, Svelte, etc.) using its established patterns, component library, and styling system. If no frontend environment exists yet, choose the most appropriate framework for the project and implement there. Treat the HTML as the source of truth for layout, spacing, color, type, copy, and interaction — not the literal markup.

## Fidelity
**High-fidelity (hifi).** Final colors, typography, spacing, and interactions are specified. Recreate the UI faithfully using the codebase's existing libraries and patterns. Exact hex values, sizes, and copy are listed below.

---

## Global Layout & Shell

**App frame:** full-viewport flex row.
- **Sidebar** — fixed `240px` wide, `background #fafafa`, right border `1px #ededed`, vertical flex, padding `18px 14px`.
- **Main** — `flex:1`, scrolls vertically, `background #ffffff`.

Base font size `14px`. Body font **Hanken Grotesk** (weights 400/450/500/600/700). Monospace **JetBrains Mono** (400/500/600) for URLs, methods, code, body/headers, and numeric metrics. Both loaded from Google Fonts. Text antialiased. Base text color `#18181b`.

### Sidebar
- **Brand row:** 28×28 rounded-square (`border-radius 8px`, `background #18181b`) holding a white shield-check icon, next to wordmark "Sentinel" (15.5px, weight 700, letter-spacing −0.02em).
- **Nav items** (icon 16px + label, padding `8px 10px`, radius `8px`, gap 10px):
  - **Monitors** — active state: `background #ffffff`, border `1px #ececec`, shadow `0 1px 2px rgba(0,0,0,0.03)`, text `#18181b` weight 600. (activity / pulse-line icon)
  - **Incidents** — idle text `#71717a` weight 500; hover `background #f2f2f3`, text `#3f3f46`. Trailing red count pill: text `#b91c1c`, `background #fee2e2`, radius 20px, "1". (alert-triangle icon)
  - **Alerts** — same idle/hover. (bell icon)
  - **Status pages** — same. (globe icon)
  - **Settings** — same. (gear icon)
- **Account card** (pinned to bottom, top border `1px #ededed`, padding 8px): 30×30 avatar `border-radius 8px`, `background #4f46e5`, white "AC" (weight 600, 12px); name "Acme Inc" (13px, weight 600), subtitle "Pro · 8 monitors" (11.5px, `#a1a1aa`).

---

## Screen 1: Monitor Dashboard

**Purpose:** at-a-glance health of all monitored endpoints; entry point to add a monitor.

**Layout:** centered column `max-width 1080px`, padding `30px 36px 64px`.

### Header row (flex, space-between)
- **Left:** `<h1>` "Monitors" (24px, weight 700, letter-spacing −0.02em). Below it a live indicator row: 7px green dot (`#22c55e`) with a `sntPulse` animation (2.2s infinite expanding box-shadow), text "Live · checking every 30s" (13px, `#71717a`).
- **Right:** search field + Add monitor button.
  - **Search:** 240px wide, `background #f4f4f5`, border `1px #ececec`, radius 9px, padding `8px 12px`, magnifier icon (15px, `#a1a1aa`), placeholder "Search monitors" (13px).
  - **Add monitor button:** `background #18181b`, white text 13px weight 600, padding `9px 14px`, radius 9px, shadow `0 1px 2px rgba(0,0,0,0.12)`, leading plus icon. Hover `background #000`. **Navigates to the Add-monitor screen.**

### Summary stat cards (4-up grid, gap 14px, margin `24px 0 22px`)
Each card: border `1px #ececec`, radius 12px, padding `16px 18px`, white bg.
- Label row (12.5px, weight 500, `#71717a`) with leading 8px status dot; big number below (30px, weight 700, letter-spacing −0.02em).
- Cards: **Operational** (green dot `#22c55e`, value = count up) · **Degraded** (amber `#f59e0b`) · **Down** (red `#ef4444`) · **Avg uptime · 24h** (leading indigo trend-up icon `#4f46e5`, value = mean uptime %).

### Monitors grid
`display:grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap:14px;` → 1 column narrow, 2–3 columns wide.

**Monitor card** — border `1px #ececec`, radius 14px, white bg, padding `16px 18px`, flex column, `cursor:pointer`, entrance animation `sntIn .35s ease`. Hover: border `#d4d4d8` + shadow `0 4px 14px rgba(0,0,0,0.05)`.
1. **Header (flex, align-start, space-between):**
   - Left block (`min-width:0; flex:1`):
     - Title line: 8px status dot (color per status) + monitor name (14.5px, weight 600, letter-spacing −0.01em, truncate with ellipsis) + optional **NEW** pill (10px, weight 700, text `#4f46e5`, `background #eef2ff`, radius 5px) shown for just-created monitors.
     - Method+URL line (margin-top 8px): **method chip** (mono 10.5px, weight 600, padding `2px 6px`, radius 5px, colored per method — see tokens) + URL (mono 12px, `#a1a1aa`, protocol stripped, truncate).
   - Right: **status pill** (11px, weight 600, padding `3px 9px`, radius 20px) — text/bg per status: Operational `#15803d`/`#f0fdf4`, Degraded `#b45309`/`#fffbeb`, Down `#b91c1c`/`#fef2f2`.
2. **Sparkline (margin-top 18px):** 26 bars, flex row align-end, gap 2px, container height 30px. Each bar `flex:1; min-width:2px; border-radius 1.5px`, individual height 4–16px, color green/amber/red reflecting that check's result. (Up monitors mostly green; degraded mix amber; down ends in red.)
3. **Footer (margin-top 14px, top border `1px #f4f4f5`, padding-top 14px, flex, gap 22px):**
   - **Uptime** value (15px, weight 700, colored per status) + label "Uptime · 24h" (11px, `#a1a1aa`).
   - **Latency** value (15px, weight 700, mono, `#3f3f46`; "—" when down) + label "Latency".
   - Right-aligned (`margin-left:auto`): last-check time (12px, `#71717a`) + label "Last check" (11px, `#a1a1aa`).

**Seed data (8 monitors)** used in the prototype:
- Stripe Checkout · POST · api.stripe.com/v1/checkout/sessions · up · 99.99% · 142ms
- Auth — Login · POST · api.acme.io/v1/auth/login · up · 99.97% · 96ms
- User Profile · GET · api.acme.io/v1/users/me · up · 100% · 54ms
- Search Index · GET · api.acme.io/v1/search · degraded · 98.42% · 812ms
- Payments Webhook · POST · hooks.acme.io/payments · up · 99.91% · 210ms
- Inventory Sync · PUT · api.acme.io/v1/inventory/sync · down · 91.20% · — (0)
- Email Service · GET · api.acme.io/v1/health · up · 99.95% · 73ms
- CDN Assets · GET · cdn.acme.io/status · up · 100% · 38ms

---

## Screen 2: Add a Monitor

**Purpose:** create one or many monitors via cURL, collection import, or manual entry.

**Layout:** centered column `max-width 740px`, padding `30px 36px 80px`.

- **Back link:** "← Back to monitors" (arrow-left icon + text, 13px, weight 500, `#71717a`; hover `#18181b`). Returns to dashboard.
- **`<h1>`** "Add a monitor" (24px, weight 700). Sub-paragraph (14px, `#71717a`): "Import an existing request or set one up by hand. Sentinel starts watching it immediately."
- **Segmented tab control** (flex, gap 4px, `background #f4f4f5`, border `1px #ececec`, padding 4px, radius 11px, margin-bottom 24px). Three equal tabs, each flex-center icon+label 13px weight 600, padding `9px 12px`, radius 8px:
  - **Active tab:** `background #fff`, border `1px #e7e7ea`, shadow `0 1px 2px rgba(0,0,0,0.05)`, text `#18181b`.
  - **Idle tab:** transparent, text `#71717a`.
  - Tabs: **Paste cURL** (terminal icon), **Import collection** (upload icon), **Manual setup** (edit/pen icon).

### Tab A — Paste cURL
- Label row: "cURL command" (13px weight 600) + "Use example" link (12.5px, weight 600, `#4f46e5`, hover underline) that fills the textarea with a sample POST cURL.
- **Textarea:** full width, min-height 140px, vertical resize, `background #fafafa`, border `1px #e4e4e7`, radius 11px, padding `14px 16px`, mono 12.5px, line-height 1.6. Placeholder shows an example cURL.
- **Parse request button:** secondary (`background #fff`, border `1px #d4d4d8`, text 13px weight 600, radius 9px, refresh icon; hover `background #fafafa`, border `#a1a1aa`). On click, parses the cURL.
- **On successful parse → "Detected request" card** appears (border `1px #ececec`, radius 12px, entrance `sntIn .3s`):
  - Header strip (`background #fafafa`, uppercase 11.5px `#a1a1aa`) with green check icon + "Detected request".
  - Body: method chip + URL (mono, word-break). If headers present: "HEADERS" group, each as `key:` (mono, `#7c3aed`) + value (mono, `#52525b`). If body present: "BODY" group in a `<pre>` (`background #fafafa`, border `1px #ededed`, radius 8px, mono 12px, pre-wrap).
  - **Monitoring rules** section (see shared block) + footer with **Cancel** (secondary) and **Create monitor** (primary black) buttons.
- If parsing fails: toast "Could not detect a request — check the cURL".

**cURL parser behavior to replicate:**
- Strip line continuations (`\` + newline) and newlines; tokenize respecting single/double quotes.
- `-X` / `--request` → method. `-H` / `--header` → split on first `:` into key/value. `-d` / `--data` / `--data-raw` / `--data-binary` / `--data-urlencode` → body. `--url` → URL. Skip value-consuming flags `-u/--user`, `-A/--user-agent`, `-e/--referer`. First bare token that looks like a URL (`https?://` or contains a dot) → URL.
- Default method: `POST` if a body was found, else `GET`. Method uppercased. Return null if no URL.

### Tab B — Import collection
- **Dropzone:** dashed border (`1.5px`, idle `#d4d4d8` / dragging `#4f46e5`), radius 13px, padding `36px 24px`, centered, idle `background #fafafa` / dragging `#f5f3ff`, `cursor:pointer`. 46px rounded-square icon tile (`background #eef2ff`, indigo upload icon). Title "Drop a Postman collection or JSON file" (14px weight 600). Subtitle "or **browse your computer** · Postman, OpenAPI, generic JSON" (browse word in indigo weight 600). Hidden `<input type=file accept=.json>`; click opens picker, drag-drop accepted.
- Below dropzone, centered link "Load an example collection instead" (`#4f46e5`) loads a built-in sample Postman collection.
- **On file/sample loaded → endpoint list** appears (entrance `sntIn .3s`):
  - Header: green check + source summary (e.g. "Postman · Acme API · 6 requests") + right-aligned "Select all" / "Deselect all" toggle link.
  - **List** (border `1px #ececec`, radius 12px, max-height 300px scroll). Each row is a `<label>` (flex, gap 11px, padding `11px 16px`, bottom border `1px #f4f4f5`, hover `#fafafa`): checkbox (16px, `accent-color #4f46e5`) + fixed-width method chip (52px, centered) + name (13px weight 600, truncate, max 180px) + URL (mono 12px, `#a1a1aa`, truncate).
  - **Interval + Expected status** (2-up grid) applied to all.
  - Footer: **Cancel** + primary **"Create N monitors"** (label reflects selected count; "monitor" singular when 1).

**Parser behavior:**
- **Postman** (`json.info && json.item`): recursively walk `item[]`; for each with `.request`, read `request.method` and URL (`request.url` string or `request.url.raw`); name from `item.name`. Source = "Postman · {info.name}".
- **OpenAPI** (`json.paths`): for each path × method in {get,post,put,patch,delete}, emit endpoint; URL = `servers[0].url` + path; name = `summary` / `operationId` / path. Source = "OpenAPI · {info.title}".
- **Generic** (top-level array, or `{endpoints:[…]}`): map objects of `{method,url,name}`; drop entries with no URL.
- Errors → toasts: "That file is not valid JSON" / "No endpoints found in that file".

### Tab C — Manual setup
- **Monitor name** input (full width, padding `9px 12px`, border `1px #e4e4e7`, radius 9px, 13.5px). Placeholder "e.g. Checkout API".
- **Endpoint** row: method `<select>` (110px, mono weight 600 — GET/POST/PUT/PATCH/DELETE) + URL input (flex, mono). Placeholder "https://api.acme.io/v1/health".
- **Headers:** repeatable rows — key input (`flex:1`, mono) + value input (`flex:1.4`, mono) + remove button (34×34, border `1px #e4e4e7`, radius 9px, `#a1a1aa`; hover `background #fef2f2`, border `#fecaca`, `#ef4444`). "+ Add header" link (`#4f46e5`). Always at least one row remains.
- **Monitoring rules** block + footer (**Cancel** / **Create monitor**). Validation: empty URL → toast "Enter an endpoint URL". Name falls back to a derived name (last 1–2 path segments) when blank.

### Shared "Monitoring rules" block (cURL & Manual tabs; Import shows interval+status only)
- `<h3>` "Monitoring rules" (15px weight 700).
- **2-up grid:**
  - **Check interval** `<select>`: Every 30 seconds / 1 minute (default) / 5 / 10 / 30 minutes. Values `30s|1m|5m|10m|30m`.
  - **Expected status code** input (mono), default `200`.
- **Response assertions:** repeatable rows — type `<select>` (200px: "Body contains" / "JSON path equals" / "Status code equals" / "Response time under (ms)") + value input (mono, placeholder "Expected value") + remove button (same style as header remove). "+ Add assertion" link (`#4f46e5`). Default first assertion: type "Status code equals", value "200".
- Field focus state (all inputs/selects/textarea): border `#a5b4fc`, ring `0 0 0 3px rgba(79,70,229,0.12)`.

---

## Interactions & Behavior
- **Navigation** is in-app view switching (`dashboard` ↔ `add`), not routed pages in the prototype — implement as routes (`/monitors`, `/monitors/new`) in the target app.
- **Create monitor(s):** prepend created monitor(s) to the dashboard list, return to dashboard, mark each `isNew` (shows NEW pill) for 6 seconds, and show a success toast: "Monitor created — now watching" (or "N monitors created — now watching"). New monitors default to status `up`, uptime 100%, random latency 40–220ms, freshly generated sparkline, lastCheck "just now".
- **Toast:** fixed, bottom-center, `background #18181b`, white 13px, padding `11px 18px`, radius 11px, shadow `0 8px 24px rgba(0,0,0,0.18)`, green check icon, auto-dismiss ~3s via `sntToast` keyframes (fade/slide in then out). Re-triggering resets the timer.
- **Hover states:** nav items, monitor cards, buttons, list rows, remove buttons — all specified above.
- **Animations:** `sntIn` (opacity + 6px translateY, .3–.35s ease) for cards/panels on appear; `sntPulse` (2.2s infinite) on the live dot; `sntToast` (3s) on the toast.
- **Responsive:** monitor grid reflows via `auto-fill minmax(300px,1fr)`. Sidebar is fixed-width (consider a collapse pattern on small screens in the real app).

## State Management
- `view`: `'dashboard' | 'add'`.
- `addTab`: `'curl' | 'import' | 'manual'`.
- `monitors[]`: `{ id, name, method, url, status('up'|'degraded'|'down'), uptime(number), latency(number, 0=down), lastCheck(string), bars[26]({h,color}), isNew(bool) }`.
- cURL: `curlText`, `parsed` (`{method,url,headers[],body}` | null).
- Import: `importEndpoints[]` (`{selected,name,method,url}`), `importSource`, `dragging`.
- Manual: `manual` (`{name,method,url,headers[{k,v}],body}`).
- Rules (shared draft): `rules` (`{interval, expectedStatus, assertions[{type,value}]}`).
- `toastMsg`, `showToast`, `newIds[]`.
- Derived for UI: status/method → color tokens; uptime formatted (`100%` or 2-dp `%`); latency (`{n}ms` or `—`); summary counts; avg uptime; selected-count label.

In a real app, replace seed data + client-side parsing/creation with API calls; keep the cURL/collection parsers client-side (they're pure functions).

## Design Tokens
**Colors**
- Text: primary `#18181b`, secondary `#52525b` / `#71717a`, muted `#a1a1aa`, faint `#d4d4d8`.
- Surfaces: white `#ffffff`, sidebar/subtle `#fafafa`, fill `#f4f4f5`.
- Borders: `#ededed`, `#ececec`, `#e4e4e7`, `#f4f4f5` (faint dividers).
- Primary action: `#18181b` (hover `#000`).
- Accent (indigo): `#4f46e5`; tints `#eef2ff`, `#f5f3ff`; focus ring `rgba(79,70,229,0.12)`, focus border `#a5b4fc`.
- Status — Up/green: dot `#22c55e`, text `#15803d`, bg `#f0fdf4`. Degraded/amber: dot `#f59e0b`, text `#b45309`, bg `#fffbeb`. Down/red: dot `#ef4444`, text `#b91c1c`, bg `#fef2f2`.
- Method chips (text / bg): GET `#15803d`/`#dcfce7`, POST `#1d4ed8`/`#dbeafe`, PUT `#b45309`/`#fef3c7`, PATCH `#6d28d9`/`#ede9fe`, DELETE `#b91c1c`/`#fee2e2`, other `#52525b`/`#f4f4f5`.
- Sparkline bars: green `#22c55e`, amber `#f59e0b`, red `#ef4444`.

**Typography** — UI: Hanken Grotesk (400/450/500/600/700). Mono: JetBrains Mono (400/500/600). Sizes used: 30 (stat), 24 (h1), 15.5 (wordmark), 15 (h3 / card metric), 14.5 (card title), 14 (body), 13.5, 13, 12.5, 12, 11.5, 11, 10.5, 10. Headings use letter-spacing −0.01 to −0.02em.

**Radius:** 5, 8, 9, 11, 12, 13, 14px; pills 20px; dots/avatars 50%/8px.

**Shadows:** button `0 1px 2px rgba(0,0,0,0.12)`; active nav `0 1px 2px rgba(0,0,0,0.03)`; card hover `0 4px 14px rgba(0,0,0,0.05)`; toast `0 8px 24px rgba(0,0,0,0.18)`.

**Spacing:** common gaps 2/4/7/8/9/10/14/16/18/22px; page padding `30px 36px`; card padding `16px 18px`.

## Assets
- **Icons:** inline SVGs in the Lucide style (stroke 2–2.4, round caps/joins) — shield-check (brand), activity/pulse, alert-triangle, bell, globe, gear, search, plus, arrow-left, chevron-right, terminal, upload, edit/pen, refresh, check, x, trend-up. Use the codebase's icon set (e.g. `lucide-react`) for equivalents.
- **Fonts:** Hanken Grotesk + JetBrains Mono (Google Fonts). Swap for the codebase's installed equivalents if these aren't available.
- No raster images or logos. "Sentinel" / "Acme Inc" are placeholder brand text.

## Files
- `Sentinel.dc.html` — the full prototype (both screens, all three import tabs, parsers, dashboard). Open in a browser to interact. The markup is a streaming-template format; read it for exact structure/values but reimplement in the target framework.
