# ShoppingApp

Household meal planning and shopping list app. Runs as a local web server; household members
use it from their phones over the home WiFi. It consolidates recipe ingredients into
a single shopping list and (from Phase 5) pushes that list to AnyList.

See [CLAUDE.md](CLAUDE.md) for the full specification, [SETUP.md](SETUP.md) for first-run
setup on the NUC, and [DEPLOY.md](DEPLOY.md) for shipping updates to it afterwards.

---

## Status

**Phase 1 — Foundation (complete).** FastAPI app scaffold, SQLite database with all tables,
logging to file + in-memory ring buffer, and a working Diagnostics page.

Later phases: recipe library (2), AI recipe capture (3), planning engine (4), checklist +
AnyList (5), polish (6).

---

## Quick start (Windows)

```bat
start.bat
```

First run creates a `.venv`, installs dependencies from `requirements.txt`, copies
`.env.example` to `.env` if needed, then starts the server and opens a browser to
`http://localhost:8080/`.

To stop: press `Ctrl+C` in the server window, or run `stop.bat`.

### Backup / restore

```bat
backup.bat                    REM copies the DB + a JSON dump into backups/, commits+pushes if git is set up
restore.bat                   REM lists available backups
restore.bat latest            REM dry run — shows what it would do
restore.bat latest --yes      REM actually restores (saves a pre-restore safety copy first)
```

See [CLAUDE.md > Backup & Restore](CLAUDE.md#backup--restore) and `SETUP.md` step 9 for the
weekly Task Scheduler entry.

### First-time NUC setup

```bat
setup_nuc.bat                 REM NUC, once: installs Python+Git, clones the repo, .env,
                               REM firewall rule, first start + health check
```

See [SETUP.md](SETUP.md) for what that automates vs. what stays manual (static IP, Task
Scheduler).

### Deploying updates to the NUC

```bat
deploy.bat                    REM dev PC: commit/tag/push the release (after your own git commit)
update.bat                    REM NUC: pull it down, reinstall deps if needed, restart
```

See [DEPLOY.md](DEPLOY.md) for the one-time git/GitHub setup and how rollback works.

### Manual start (for development)

```bat
py -3 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m app.main
```

or with autoreload:

```bat
uvicorn app.main:app --reload --port 8080
```

---

## Configuration

All configuration is in `.env` (gitignored). Copy `.env.example` and edit.

| Key | Used from | Notes |
|---|---|---|
| `PORT` | Phase 1 | Default 8080. |
| `LOG_LEVEL` | Phase 1 | `DEBUG` / `INFO` / `WARNING` / `ERROR`. |
| `DATABASE_PATH` | Phase 1 | Relative to project root. |
| `IMAGES_PATH` | Phase 3 | Uploaded recipe photos. |
| `LOGS_PATH` | Phase 1 | Rotating daily, 14 days kept. |
| `ANTHROPIC_API_KEY` | Phase 3 | Recipe extraction. Placeholder is fine until then. |
| `ANYLIST_EMAIL` / `ANYLIST_PASSWORD` | Phase 5 | AnyList sync. Placeholder is fine until then. |

---

## Key URLs

| URL | What |
|---|---|
| `/` | App (single page, hash-routed). |
| `/#/diagnostics` | Component status, recent errors, live log tail. |
| `/api/v1/health` | JSON health check (DB status + config summary). |
| `/api/v1/diagnostics/logs` | Log tail JSON. |
| `/api/v1/diagnostics/status` | Component status JSON. |
| `/docs` | FastAPI interactive API docs. |

---

## Project layout

```
app/
  main.py            FastAPI app, error envelope, router wiring, static mount
  config.py          .env loader -> settings object
  database.py        SQLAlchemy engine, session factory, Base, init_db()
  log_config.py      file + console + ring-buffer logging
  seed_data.py       staples + product_units + section vocabulary starter data (wired in Phase 2)
  models/            ORM models, one module per table group (includes store.py: stores/store_sections/product_sections)
  routers/           health + diagnostics live; recipes/sessions/checklist/anylist/settings are stubs
  services/          business logic (Phase 3+)
scripts/             backup.py + restore.py + deploy.py + update.py + git_utils.py
                     (run as `python -m scripts.<name>`), see backup.bat/restore.bat/deploy.bat/update.bat
static/              vanilla HTML/CSS/JS frontend, no build step
data/ images/ logs/  runtime data (gitignored)
backups/             weekly DB + JSON dump pairs (NOT gitignored)
```

---

## Logs

- File: `logs/app.log`, rotated at midnight, 14 days retained.
- Format: `%(asctime)s [%(levelname)s] %(name)s: %(message)s`
- Last ~1000 entries are also held in memory and shown on the Diagnostics page.
