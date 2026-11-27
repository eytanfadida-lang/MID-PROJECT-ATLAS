# Project Reorganization Plan

Goal: turn 48 flat modules in the repo root into a navigable package — **without the live site
going down once.** Sequencing matters more than the final shape, so the safety analysis comes
first.

---

## 1. What the current tree actually is

Measured, not guessed (`git ls-files` + AST import graph over every module):

| | |
|---|---|
| Python modules | **48**, all but 5 in the repo root |
| Flat root files total | 60+ including templates/, static/, docs |
| CWD-relative path references | **24** (secrets, DB, debug dumps) |
| Entry points | `app.py`, `rest_app.py`, `seed_users.py`, `arbox_run_sync.py`, `arbox_push_sync.py`, `arbox_discover_locations.py` |
| Automated tests | 3 files — **not runnable, pytest not installed** |
| CI that checks the code | **none** (workflows only run the Arbox sync and Meta poll) |

### 1.1 There is a dead CLI application still shipped

`rest_app.py` is the original pre-Flask CLI. It pulls in `menu.py`, `lead_menu.py`,
`customer_menu.py`, `login_service.py` and the `LeadInput` / `AppointmentInput` /
`CustomerInput` classes. Nothing imports `rest_app.py`; the web app never touches it.

**But it cannot simply be deleted**, because the web app reaches into those CLI modules for
domain constants:

```
app.py                  → lead_input.CHANNELS
blueprints/leads.py     → lead_input.CHANNELS, appointment_input.BRANCHES,
                          lead_menu.LEAD_UPDATABLE_FIELDS, lead_menu.CONVERTED_STATUS
blueprints/appointments → appointment_input.BRANCHES
blueprints/customers.py → customer_input.MEMBERSHIP_PLANS
```

So `blueprints/leads.py` imports `lead_menu`, which imports `lead_input` **and**
`appointment_input`, dragging the whole CLI class hierarchy into the web process to obtain two
constants.

### 1.2 That coupling has already produced a live bug 🐛

```python
lead_menu.py:16      CONVERTED_STATUS = "Became a client"     # ← used by blueprints/leads.py
arbox_sync.py:3      ARBOX_CONVERTED_STATUS = "הפך ללקוח"     # ← the real one
```

The actual `lead_statuses` table contains:
`בטיפול · הפך ללקוח · חדש · לא מעוניין · לא רלוונטי · ליד כפול · קיבל מידע על VIP · קיבל מידע על ההדרכות`

`"Became a client"` **is not among them.** Converting a lead to a customer therefore writes a
status that no filter matches and no colour maps to. It is an English leftover from the CLI era
that survived because the constant lives in a module nobody thinks of as live code. Extracting
constants (Phase 2) fixes this as a side effect.

### 1.3 The real constraint: 24 CWD-relative paths

Every secret, the database, and every debug dump is opened by a **bare relative path**:

```python
auth.py           Path(".flask_secret")
whatsapp_bot.py   Path(".whatsapp_access_token")     # ×4 files
meta_leads.py     Path(".meta_app_secret")           # ×6 files
db.py             DB_FILE = os.environ.get("DB_FILE", "appointments.db")   # ×4 near-identical modules
app.py            Path(".last_meta_payload.json")    # ×3 dumps
```

These resolve against the **current working directory**, not the module. They work today only
because PythonAnywhere happens to run with the project as CWD. This has already bitten once —
`arbox_run_sync.py:6` carries the scar:

```python
os.chdir(os.path.dirname(os.path.abspath(__file__)))   # added after a cron run failed
```

**These files are gitignored and live only on the server.** Git cannot move them. Any plan that
relocates them requires a manual `mv` of ~20 invisible dotfiles on a live server, where missing
one produces a silent `403` on a single integration days later. That risk shapes the whole
sequence below.

### 1.4 There is no safety net

`pytest` is not installed, so the 3 test files have never run in this environment, and no CI
workflow imports the app. This is not theoretical: **the entire site went down** earlier in this
project with `ModuleNotFoundError: No module named 'anthropic'`, because `app.py` imports
`crm_assistant` at module level and the package was installed into the wrong virtualenv. A
one-line `python -c "import app"` check in CI would have caught it before deploy.

➡️ **Therefore Phase 0 builds the safety net before a single file moves.**

---

## 2. What must not break

| # | Constraint | How the plan honours it |
|---|---|---|
| C1 | PythonAnywhere WSGI does `from app import app as application` | **`app.py` stays at the root as a 3-line shim.** Zero server-side edits, ever. |
| C2 | 24 CWD-relative paths to gitignored files | `paths.py` anchors on `__file__`; legacy root locations keep working via fallback |
| C3 | GitHub Actions runs `python arbox_push_sync.py` from root | Root shim kept, or workflow updated + `workflow_dispatch` tested before merge |
| C4 | Flask finds `templates/`+`static/` beside the app module | Explicit `template_folder=` / `static_folder=` when the package moves |
| C5 | Tests use flat imports | Updated in the same commit as each move |
| C6 | Secrets and DB exist only on the server | Not moved until Phase 5, and only with a fallback in place |

**C1 is the single most important decision.** Keeping `app.py` as a valid import target means
the server's WSGI file is never edited, and any phase can be rolled back with `git revert`
without touching PythonAnywhere configuration.

---

## 3. Target structure

```
MID-PROJECT-ATLAS/
├── app.py                      ← 3-line shim. PythonAnywhere keeps importing this. Never moves.
├── manage.py                   ← one CLI: seed-users | arbox-sync | discover-locations
├── requirements.txt
├── pyproject.toml              ← pytest config
│
├── atlas/                              the application package
│   ├── __init__.py                     create_app() factory
│   ├── paths.py                        PROJECT_ROOT anchor + secret/data resolution
│   ├── settings.py                     CHANNELS, BRANCHES, STATUSES, MEMBERSHIP_PLANS,
│   │                                     LEAD_UPDATABLE_FIELDS, CONVERTED_STATUS
│   ├── core/
│   │   auth.py · roles.py · password_hashing.py · view_utils.py
│   ├── data/
│   │   ├── connection.py               merges db.py + lead_db.py + customer_db.py + user_db.py
│   │   ├── context.py                  (db_context.py)
│   │   └── repositories/
│   │       appointments.py · leads.py · customers.py · users.py
│   │       invoices.py · lead_statuses.py · id_sequence.py
│   ├── services/
│   │   availability.py · lead_import.py · phone_utils.py
│   ├── integrations/
│   │   ├── arbox/      client.py · sync.py · cache.py
│   │   ├── meta/       lead_ads.py
│   │   ├── google/     lead_forms.py
│   │   ├── whatsapp/   bot.py · admin_assistant.py · customer_assistant.py · llm_client.py
│   │   └── landing_page.py
│   └── web/
│       ├── blueprints/  dashboard · auth · leads · appointments · customers · users
│       ├── webhooks.py                 the six /tasks/* endpoints, out of app.py
│       ├── templates/                  moved
│       └── static/                     moved
│
├── bot_content/                business_info.md · system_prompt.md
├── docs/                       PROJECT_CONTEXT.md · the two plans · the research report
├── scripts/                    arbox_push_sync.py (CI) · one-off utilities
├── tests/
└── ── gitignored, server-side, untouched until Phase 5 ──
    appointments.db · .flask_secret · .meta_* · .whatsapp_* · .arbox_* · .anthropic_api_key
```

**Why `atlas/` and not `src/`:** a named package makes imports self-documenting
(`from atlas.integrations.whatsapp import bot`) and makes the "is this ours or a library?"
question answerable at a glance.

**Deletions in Phase 2:** `rest_app.py`, `menu.py`, `lead_menu.py`, `customer_menu.py`,
`login_service.py`, plus the `*Input` classes — 7 files, ~600 lines of dead CLI.

---

## 4. Phased sequence

Each phase is **one commit, independently deployable, independently revertible.** The site is
working at the end of every phase.

### Phase 0 — Safety net (no files move)
- Add `pytest` to `requirements.txt`; add `pyproject.toml` with test config.
- Fix the 3 test files so they actually run.
- **New CI workflow** `.github/workflows/ci.yml`: install deps → `python -c "import app"` →
  `pytest`. This is the check that would have prevented the site outage.
- ✅ *Verify:* CI green on an unmodified tree. Nothing deployed.

### Phase 1 — `paths.py`, end CWD dependence (no files move)
- Add `paths.py`: `PROJECT_ROOT = Path(__file__).resolve().parent`, plus `secret(name)` and
  `data(name)` helpers that resolve against it.
- Route all 24 relative paths through it. **Filenames and locations stay identical**, so the
  server needs no changes at all.
- Delete the `os.chdir` hack from `arbox_run_sync.py`.
- ✅ *Verify:* run every entry point **from a different working directory** (`cd / && python
  /path/to/arbox_run_sync.py`) and confirm secrets still load. This is the specific bug class
  being eliminated.
- 🚀 Deploy: pull + Reload. Highest value, lowest risk phase.

### Phase 2 — Rescue constants, delete the dead CLI
- Create `settings.py` with the six constants; **fix `CONVERTED_STATUS` → `"הפך ללקוח"`** (§1.2).
- Repoint the 6 web imports.
- Delete the 7 CLI files.
- ✅ *Verify:* `grep -rn "lead_menu\|customer_menu\|login_service\|rest_app"` returns nothing;
  CI green; convert a test lead and confirm the status now matches a real one.
- 🚀 Deploy: pull + Reload.

### Phase 3 — Create the package, move modules
- `mkdir atlas/…`; move everything with **`git mv`** so history follows the files.
- `atlas/__init__.py` gains `create_app()` with explicit
  `Flask(__name__, template_folder="web/templates", static_folder="web/static")`.
- `app.py` becomes:
  ```python
  from atlas import create_app
  app = create_app()          # PythonAnywhere's `from app import app` still works
  ```
- Update test imports; update the Actions workflow if `arbox_push_sync.py` moves to `scripts/`
  (test with `workflow_dispatch` **before** merging).
- ✅ *Verify:* CI green → local `python -c "import app"` → browse every page locally.
- 🚀 Deploy: pull + Reload → run the smoke list (§5).

### Phase 4 — Split webhooks out of `app.py`
- Move the six `/tasks/*` endpoints into `atlas/web/webhooks.py` as a blueprint.
- ✅ *Verify:* each endpoint answers — an unauthenticated `403` is a valid signal that the route
  is registered.
- 🚀 Deploy: pull + Reload.

### Phase 5 — *(optional, later)* relocate secrets and DB
- Move to `secrets/` and `data/` **only** with `paths.py` checking the new location first and
  falling back to the legacy root path. That makes the server-side `mv` reversible and
  zero-downtime — if a file is missed, the fallback still finds it.
- Recommendation: **defer indefinitely.** The gain is cosmetic; the risk is a silent 403 on one
  integration days later. Phase 1 already removed the real fragility.

---

## 5. Deploy smoke test (run after every deployed phase)

1. `git pull` on PythonAnywhere → **Web tab → Reload** (never skip the Reload)
2. Site loads; log in
3. `/leads/` renders with pagination, statuses coloured
4. `/appointments/` and `/customers/` render
5. `curl "…/tasks/meta-leads-poll?token=…"` → JSON, not a traceback
6. Send "בדיקה" to the WhatsApp bot → reply arrives
7. Check the error log for new exceptions

**Rollback at any point:** `git revert <commit>` → pull → Reload. Because `app.py` remains a
valid entry point in every phase, rollback never requires touching the server's WSGI
configuration.

---

## 6. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Broken import takes the site down | medium | Phase 0 CI import check; deploy one phase at a time |
| A secret path silently breaks an integration | medium | Phase 1 keeps filenames identical; Phase 5 deferred |
| GitHub Actions breaks when a script moves | low | `workflow_dispatch` test before merging |
| `git mv` loses file history | low | `git mv` preserves it; avoid delete-then-add |
| Repository-layer changes break admin pages | medium | Phase 2 and 3 kept separate; smoke list after each |
| Refactor drifts into rewriting logic | **high** | Hard rule: **moves and renames only.** The one exception is the `CONVERTED_STATUS` fix, called out explicitly. |

That last row is the real danger. Every phase should be reviewable as "this file moved, its
imports changed, nothing else."

---

## 7. Recommendation

Phases **0, 1 and 2 are worth doing regardless** of whether the full restructure happens — they
add a safety net, remove a whole class of path bugs, delete 600 lines of dead code and fix a
live bug, and none of them move a single file into a new directory.

Phase 3 is the actual reorganization and is best done **before** the customer WhatsApp bot adds
another 5–6 modules to the root, not after.

Phase 5 is not recommended.
