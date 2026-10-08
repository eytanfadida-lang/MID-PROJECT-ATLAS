# Project Context — מנהל תורים (Appointment Manager CRM)

This file is a handoff summary for another LLM/agent picking up this project. It covers the
whole system, decisions made along the way (and why), and the task in progress right now.

## What this is

A Hebrew-language (RTL) Flask CRM for a fitness/weight-loss business ("אפרת רוזנברג הרזיה
וחיטוב הגוף"), covering appointments, customers, and leads. Built incrementally over a very
long collaborative session with the business owner (git user "eytan", email
eytanfadida@gmail.com), who is non-technical and needs every external-dashboard step (Meta,
PythonAnywhere, Anthropic Console, etc.) explained precisely, with screenshots reviewed at each
step.

- **Repo**: public GitHub repo `eytanfadida-lang/MID-PROJECT-ATLAS`, branch `main`.
- **Live deployment**: PythonAnywhere free tier, `https://eytan1985.pythonanywhere.com`.
  Deploy flow is always: push to GitHub → on PythonAnywhere `git pull` → **Web tab → Reload**
  (code changes never take effect without an explicit Reload; this is forgotten constantly and
  is usually the first thing to check when "it doesn't work").
- **Note**: something on the user's machine (likely a VS Code Git extension) has repeatedly
  auto-committed and auto-pushed pending changes under generic messages (e.g. "22",
  "CRM_ASSISTANT") *before* the assistant's own `git commit` ran. Always `git status`/`git log`
  before assuming nothing has been pushed yet.

## Architecture

- Flask app (`app.py`), Flask blueprints (`blueprints/auth.py`, `appointments.py`, `leads.py`,
  `customers.py`, `users.py`).
- SQLite (`appointments.db`, gitignored — contains real customer PII) accessed via small
  repository classes (`lead_repository.py`, `customer_repository.py`, `appointment_repository.py`,
  `user_repository.py`), each wrapping a `sqlite3.Connection` with pandas-returning query methods.
  Obtained in request handlers via `db_context.get_repos()`.
- `pandas` is used pervasively for query results (`get_all()` etc. return DataFrames).
- Auth: session-based, password hashing via `password_hashing.py` (hash+salt, not
  werkzeug's), roles (`admin`/`user`) plus a granular `permissions` JSON column on `users`.
  CSRF via `auth.validate_csrf`, applied as `app.before_request`, **skipped for all `/tasks/*`
  routes** (those are the external webhook/cron endpoints, authenticated by their own tokens
  instead of session+CSRF).
- Templates: Jinja2, RTL, `templates/base.html` shell with sidebar/topbar, page-specific CSS
  scoping via a `body.page-*` class pattern (see `body.page-leads-list` in `static/style.css`
  for the fixed/sticky leads-list layout — this page deliberately has `overflow: hidden` around
  the table so it never scrolls except inside `.table-scroll`; **anything meant to be visible
  on this page must live inside a `position: fixed` element or inside `.table-scroll` itself**,
  since normal-flow content placed after the table is silently clipped and invisible — this bit
  us once with pagination and again conceptually with flash messages).

## Secrets pattern

All external-integration secrets are local, gitignored, dotfiles in the project root, read via
tiny `load_*()` helpers (`Path(...).read_text().strip()`) — never in git, never in code. Full
current list (see `.gitignore` for the authoritative one):

- `.flask_secret` — Flask session signing key (rotated once after the repo-exposure incident,
  see Security section)
- `.arbox_api_key`, `.arbox_sync_token`, `arbox_location_map.json`
- `.google_leads_webhook_key`
- `.landing_page_token`, `.last_landing_page_payload.json`
- `.meta_verify_token`, `.meta_app_secret`, `.meta_page_access_token`, `.meta_poll_token`,
  `.meta_last_poll_time`, `.meta_processed_leads.json`, `.last_meta_payload.json`
- `.whatsapp_verify_token`, `.whatsapp_app_secret`, `.whatsapp_access_token`,
  `.whatsapp_allowed_numbers`, `.last_whatsapp_payload.json`, `.whatsapp_conversations.json`
- `.anthropic_api_key`

Whenever a new file like this is added, it must be added to `.gitignore` in the same commit —
this has been missed once or twice and had to be fixed retroactively.

Note the local dev checkout (this Windows machine) and the live PythonAnywhere server each have
**their own independent copies** of these dotfiles — updating one does not update the other.
Every time a secret changes, both places need it (usually only the PythonAnywhere copy matters
for things the live webhook needs, but keep them in sync where practical).

## Security incident (resolved)

Early on, `appointments.db` (real customer PII) and `.flask_secret` were accidentally tracked in
the public repo. Explicit owner decision: **keep the repo public**, stop tracking those files
going forward (`git rm --cached` + `.gitignore`), rotate the Flask secret (invalidates existing
sessions), but **do not rewrite git history** to scrub the old commits. This preference (public
repo is fine, no history rewrites, ever) should be treated as a standing constraint.

## Feature history (leads-focused CRM work)

Roughly in order: status color-coding + a statuses management UI; bulk lead
selection/status-update/assign/delete; WhatsApp click-to-chat icons next to phone numbers;
renamed "משתמש משויך" → "מנהל לקוח" (assigned-user became a dropdown of real users); added a
branch field (מוצקין/טירת כרמל, fixing a "מזכין"→"מוצקין" typo everywhere); CSV/Excel lead
import (`/leads/import`, careful about a pandas `iterrows()` + nullable-string-dtype bug that
turned blank cells into the literal string `"nan"`); sticky/fixed leads-list layout (see the
`overflow: hidden` note above); pagination (50/page, tunable, lives inside the fixed stats
footer — see architecture note); a very subtle cross-table column separator
(`rgba(15,23,42,0.05)`, not a flat gray, applied globally via the base `th/td` rule); compact
leads-table row sizing (tuned twice — first pass was too cramped, second pass restored some
padding); leads-table column reorder (current order: select, created, status, assigned, updated,
channel, name, phone, notes, routings, branch, id, actions); flash messages now auto-fade after
3s and live in a `position: fixed` top-center container (not normal document flow — needed for
the leads-page layout reason above) and are fully Hebrew (all English `flash()` calls across
every blueprint were translated for consistency).

## External lead sources (webhooks under `/tasks/*`)

All follow the same shape: signature/token check → parse payload → write raw payload to a local
debug file (`print()` alone was unreliable in PythonAnywhere's WSGI logs) → extract fields →
create a lead. Established because third-party payload schemas were never fully knowable from
docs alone — always verified against a real captured payload before trusting the parser.

- **Google Ads Lead Form** (`google_leads.py`, `/tasks/google-leads-webhook`): built and unit
  tested with a synthetic payload, but the user pivoted to wanting the Elementor landing-page
  flow instead ("כשאני אומר גוגל אני מתכוון שזה עובר דרך האתר שלי") — this endpoint has **never
  been connected to a real Google Ads account**, field-name assumptions unverified.
- **Landing page / Elementor Pro** (`landing_page_leads.py`, `/tasks/landing-page-lead`):
  **confirmed working end-to-end** with a real submission from efratrosenberg.co.il. Elementor
  sends PHP-array-bracket form-encoded keys (`fields[phone][value]`), not flat JSON — this was
  discovered from a captured real payload, not guessed.
- **Meta Lead Ads** (`meta_leads.py`, `/tasks/meta-leads-webhook` + `/tasks/meta-leads-poll`):
  see below, this was a long saga.
- **Arbox sync** (`arbox_sync.py`, `arbox_client.py`, `/tasks/arbox-sync`,
  `/tasks/arbox-sync-data`): pulls active Arbox clients and updates matching **existing** leads'
  status to `"הפך ללקוח"` by phone match — explicitly does **not** create/import new leads (a
  requirement stated multiple times). PythonAnywhere's free tier blocks outbound requests to
  `arboxserver.arboxapp.com` specifically (proven via a live `ProxyError`/403), so the fetch step
  runs in **GitHub Actions** (`.github/workflows/arbox-sync.yml`, every 15 min, free for public
  repos) via `arbox_push_sync.py`, which POSTs the fetched user list to
  `/tasks/arbox-sync-data` — that endpoint only touches the local DB, no outbound call needed on
  PythonAnywhere's side. This GitHub-Actions-relay pattern is reusable for any future
  integration PythonAnywhere can't reach directly.
- **Manual JSON sync** (`/leads/sync`, `/leads/sync/export`, admin-only): paste-JSON import
  (reuses `apply_arbox_users_to_leads`) and full-leads JSON export, for ad hoc needs.

### Meta Lead Ads saga (context for why polling exists)

Built the standard webhook (GET handshake, POST with signature verification via
`X-Hub-Signature-256` + App Secret, then a separate Graph API call per `leadgen_id` to fetch
`field_data`). Everything checked out — App published to Live, Page correctly `subscribed_apps`'d
to the `leadgen` field, correct callback URL, Facebook's own "Successfully tested" — and it
*still* never delivered real production webhook events, even for the admin's own test leads.
Root cause was never conclusively found (all documented requirements were met). Rather than
keep fighting it, pragmatically added a **polling fallback**: `meta_leads.poll_new_leads()`
enumerates all the Page's lead forms (`/{page_id}/leadgen_forms`) and pulls new leads per form
since the last poll (`since` timestamp + a processed-IDs set for idempotency, both persisted
locally), exposed as `/tasks/meta-leads-poll`, pinged every 5 minutes by
`.github/workflows/meta-leads-poll.yml` (a bare `curl`, no Python needed — PythonAnywhere itself
can reach `graph.facebook.com` directly, unlike Arbox's domain, so no relay is needed here, just
an external trigger since PythonAnywhere's free tier has no Scheduled Tasks). The original
real-time webhook code is left in place (harmless) in case Meta ever starts delivering.
`extract_lead_fields()` also captures any lead-form field beyond name/phone/email as "extra
answers" text appended to the created lead's notes (custom questions on the form).

**Meta app-publishing gotcha** (hit twice, once per app): a freshly created Meta app cannot
receive real webhook data at all — not even for the app's own admin — until: (1) Basic Settings
are fully filled (Privacy Policy URL, Terms of Service URL, Data Deletion URL, App icon,
Category, App Domains — placeholder `facebook.com` values must be replaced with real ones), and
(2) the app is switched from **Development** to **Live** mode (a toggle at the top of the App
Dashboard, or a "Publish" flow in newer/use-case-based app creation UI). Once those are done,
`leads_retrieval` etc. showing "Standard access / Active" (no formal App Review needed) was
sufficient — full App Review was never actually required in practice here.

**Meta token gotcha** (hit repeatedly): tokens generated ad hoc from Graph API Explorer or the
WhatsApp API Setup "Generate access token" button are **short-lived** (hours) and kept expiring
mid-task. The durable fix is a **Business Manager System User** ("crm leads manage"): grant it
asset access (Page / WhatsApp Business Account / App, as needed) plus an App Role
(Admin/Developer) on the specific app, then generate a token scoped to that app with "Never"
expiration. For Page access specifically, note the System User's *own* token
(`/me` → identifies as the System User) is different from the **Page-specific token** nested in
`/me/accounts`'s response `data[].access_token` — the latter is what's actually needed to call
the Graph API *as* the Page. For WhatsApp, the System User's own token works directly as the
Cloud API bearer token (no extraction step needed, unlike Pages).

**Duplicate Meta app**: two Facebook apps ended up both named "מנהל תורים - לידים" (IDs
`1296686125695093` and `2478905525956358`) — the first one is the one actually wired up
everywhere; cleanup of the duplicate was explicitly deferred, never done.

## WhatsApp CRM chatbot (current major arc)

Two conceptually separate bots are planned on two different WhatsApp numbers:

### 1. Internal admin bot — **built and working**

- Separate Meta app "CRM WhaApp Bot" (App ID `4685344731790358`), same Business Portfolio
  ("אפרת רוזנברג רוזאות בריאות וכושר", already verified). Hit the exact same "App type: none
  doesn't offer the WhatsApp product" issue as the Lead Ads app, hence the separate app.
- Currently uses Meta's free **test number** (`+1 555 922 0247`, Phone Number ID
  `986207831253626`) — not the business's real number. Went through the same Basic-Settings +
  Publish dance as the Lead Ads app.
- `whatsapp_bot.py`: signature verification (same HMAC pattern as `meta_leads.py`), a hard
  **allowed-numbers allowlist** (`.whatsapp_allowed_numbers`, currently just the owner's own
  number `972526223432` — this is a deliberate internal-tool-only restriction, not a
  customer-facing bot), `send_text_message()`, `extract_incoming_message()`.
- `crm_assistant.py`: wires Claude (`anthropic` SDK, model id `"claude-sonnet-5"`) into the
  webhook with real tool-calling access to the CRM — `search_leads`, `lead_status_counts`,
  `search_customers`, `search_appointments` (read tools, generous filtering), plus two
  deliberately limited write tools — `update_lead_status` and `assign_lead` — scoped down per
  the owner's explicit requirement ("גם פעולות אבל שיהיה עם מגבלות של פעולות מסוימות"). System
  prompt instructs the model to only take write actions when explicitly asked, and to always use
  the tools rather than guessing/inventing data. Short per-phone-number conversation history
  (final text turns only, not raw tool-use blocks, capped at `MAX_HISTORY_TURNS`) persists in
  `.whatsapp_conversations.json` for follow-up-question context.
- `/tasks/whatsapp-webhook` in `app.py` wires it all together: GET handshake, POST →
  verify signature → extract message → check allowlist → `crm_assistant.answer_question()` →
  `whatsapp_bot.send_text_message()` with the reply.
- **Deployment gotchas hit while building this**:
  - `anthropic` had to be added to `requirements.txt` *and* actually installed on the live
    server — but the site has a **dedicated virtualenv**
    (`/home/eytan1985/.virtualenvs/myenv`), separate from whatever the plain Bash-console
    `pip3.10 install --user` targets. Installing to the wrong place silently broke the *entire*
    site (`ModuleNotFoundError: No module named 'anthropic'` at import time in `app.py`, since
    `import crm_assistant` is a top-level import) — not just the new endpoint. Fix:
    `source /home/eytan1985/.virtualenvs/myenv/bin/activate && pip install anthropic` in the
    *existing* console (PythonAnywhere free tier caps consoles at 2, so don't open a new one —
    just activate the venv in the console already in use).
  - Passing Hebrew text through Windows shell command lines (both raw `curl -d` and even
    `python -c "..."` with an inline Hebrew literal) got silently corrupted into mojibake
    (arrived as a wall of `?` on WhatsApp) — this happens at the Windows command-line layer
    *before* Python/curl ever see it, so `ensure_ascii=False` + explicit UTF-8 file encoding
    doesn't help unless the Hebrew literal is written to a **file via the Write tool** (not typed
    into a shell one-liner) and then executed with a pure-ASCII invocation
    (`python script.py`).
  - The WhatsApp "temporary" tokens from the Quickstart/API-Setup page's "Generate access
    token" button expire fast (sometimes within an hour) — this caused repeated silent
    `403 Forbidden` failures on `send_text_message` (visible only in the error log; the webhook
    itself still returns 200 since the failure happens after payload logging). Solved
    permanently by switching to the System User token (see Meta token gotcha above).
- **Local dev testing**: `crm_assistant.answer_question()` was verified directly (bypassing
  WhatsApp entirely) via `app.app_context()` + `db_context.get_repos()` — a fast, cheap way to
  sanity-check the Claude tool-calling loop against the real local dev DB before touching
  WhatsApp at all. Worth repeating for any future changes to this module.
- Local `.anthropic_api_key` needed the user to manually create the dotfile via VS Code (a
  Notepad-based attempt silently saved to the wrong location the first time — always verify
  with `wc -c <file>` after asking the user to create a secret file by hand).

### 2. Customer-facing bot — **planning stage, blocked on a number decision**

Explicitly a *separate, more restricted* bot from the internal one — different phone number,
different (much smaller) tool set. Owner's requested scope so far: customers can check their own
upcoming appointment, book a new appointment, get general business info (hours/services/prices/
policies — content not yet provided by the owner), and unknown/prospective customers can have a
lead auto-created; owner also wants it to pull live membership/status data from Arbox via its
API. **Hard security requirement** (owner-agreed): every tool this bot gets must scope
automatically to the caller's own phone number (the number the webhook says the message came
from) — it must never be possible for one customer to query another customer's/lead's data by
supplying a different phone number as a parameter. This is a stricter tool design than the
internal bot's (which trusts the single allowlisted owner completely).

**Blocked on**: which phone number to dedicate to this bot. The owner does not want to lose
manual/mobile access to any of their existing real numbers. Key finding from this session:
standard Meta Cloud API "Add phone number" (tried directly through our own app's WhatsApp
Manager) has **no coexistence option** — it's the plain exclusive-migration flow (add number →
business profile → done, no QR/keep-the-app choice ever appeared). A **third-party paid tool the
owner already uses, "Upgrade 360"**, showed a QR-code-based "keep full app access" connection
option during its own onboarding flow (its screens look like an official Meta OAuth flow —
Facebook Login consent, business portfolio picker, WhatsApp Business account linking — this is
almost certainly Meta's real **"coexistence"** feature, which apparently is only exposed through
certified Tech Providers/BSPs rather than self-serve via a generic developer app). Whether
Upgrade 360 exposes its own API/webhook that this project could hook a custom Claude bot into is
**unknown and needs to be checked with Upgrade 360 support/docs** — this was the last thing asked
of the owner before this handoff. A from-scratch DIY alternative (unofficial "linked device"
libraries like Baileys/whatsapp-web.js, Node.js-based) was explained and explicitly
**recommended against for any real/primary business number** — real risk of WhatsApp banning
the number for automated behavior via unofficial channels, plus it'd require an unfamiliar
Node.js stack rather than the existing Python one. Options left on the table, in the owner's
own words/preference order not yet resolved: (1) a genuinely new dedicated number, (2) keep
developing against Meta's free test number for now and decide later, (3) accept losing mobile
app access on an existing real number, (4) resolve the Upgrade 360 API question and possibly
integrate through them instead of Meta directly.

The user's phone number list in WhatsApp Manager currently has a few stray/unverified entries
from testing this (`+972 55-256-3370` pending review, `+972 53-628-0080` mid-onboarding,
`+972 50-306-6767` not connected) that likely need cleaning up once the number decision is made.

## Open items / natural next steps

1. Resolve the customer-bot phone-number decision (see above) — this is the current blocker.
2. If proceeding with a dedicated/new number: repeat the same WhatsApp Cloud API setup dance
   (Basic Settings, Publish, System User token) for it, then design and build the restricted
   customer tool set (own-appointment lookup, booking, business-info Q&A, lead creation, Arbox
   membership lookup) as a new module analogous to `crm_assistant.py` but far more locked down.
3. Gather actual business content (hours, services, prices, cancellation policy, etc.) from the
   owner to embed in the customer bot's system prompt / a small knowledge tool.
4. Design the Arbox-lookup-by-phone tool (reuse `arbox_client.py`'s API key loader).
5. Deferred/never done: delete the duplicate Facebook app; verify Google Ads webhook against a
   real payload (or decide it's permanently superseded by the landing-page flow); clean up stray
   WhatsApp Manager phone-number entries from testing.
