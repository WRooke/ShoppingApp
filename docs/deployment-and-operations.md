# Deployment & Operations

## Deployment Environment

- **Host OS:** Windows 10
- **Dev machine:** Windows 11, Python 3.14.6
- **NUC:** bare Windows 10 install + Plex. Python not yet installed.
- **Network:** Local WiFi only. NUC needs a static local IP (reserved DHCP lease in router
  settings). See `SETUP.md`.
- **Access:** Local keyboard/mouse access to NUC and remote network access available.
- **Port:** Run on port 8080 (unlikely to conflict with Plex). Make configurable via .env.

### Startup
Two batch scripts in the project root:
- `start.bat` — creates/activates the venv on first run, installs dependencies, starts uvicorn,
  opens a browser to the app URL
- `stop.bat` — kills the running app process

Two more for the backup system (see [Backup & Restore](#backup--restore)):
- `backup.bat` — runs `scripts/backup.py`
- `restore.bat` — runs `scripts/restore.py`

Two more for deployment from the dev PC to the NUC (added ahead of schedule, alongside this
session's diagnostics/backup work, since getting the pipeline right early is cheap and it
only gets more annoying to retrofit once there's more to ship — see `DEPLOY.md` for the full
walkthrough and one-time git/GitHub setup):
- `deploy.bat` — runs `scripts/deploy.py` on the **dev PC**, from the `develop` branch:
  runs the full test suite first and refuses to tag/push if it fails (this is this project's
  CI — no GitHub Actions or other hosted pipeline; the answer to "would this have been
  caught" is "does `pytest tests/` catch it", and `scripts/validate_develop.py` is the same
  check run by hand before that point), then verifies the working tree is clean and current,
  tags the commit, pushes `develop` + the tag to the private GitHub repo, then fast-forwards
  the remote `production` branch to match.
- `update.bat` — runs `scripts/update.py` on the **NUC**, from the `production` branch:
  pulls the new commit (fast-forward only, never merges), reinstalls dependencies if
  `requirements.txt` changed, then stops and restarts the server. Aborts before touching the
  running server if any step fails, so a bad update leaves the old version running. What a
  phone that already has the app open does afterwards is in [How an open phone learns the NUC was
  updated](#how-an-open-phone-learns-the-nuc-was-updated) below.

Two branches, not one — see [Git branching strategy](./deferred-decisions.md#deferred-decisions), decided at the
Phase 2 review: `develop` is where all work happens (dev PC), `production` is what the NUC
runs and only ever moves via `deploy.bat`. Full rationale, one-time setup (including
migrating this repo's existing `main` history across), and the day-to-day workflow are in
`DEPLOY.md`.

This reuses the same private GitHub repo already planned as the backup push destination
(see [Backup & Restore](#backup--restore)) rather than adding a second piece of
infrastructure — one repo, two jobs (three, counting deploys). `scripts/backup.py`'s
commit-and-push now rebases onto the latest origin first, precisely so its weekly commits
(landing on `production`, since that's what the NUC is checked out on) and dev-PC deploys
fast-forwarding that same branch don't fight each other.

One more, for first-run NUC setup: `setup_nuc.bat` runs `scripts/bootstrap_nuc.ps1`, which
automates everything about SETUP.md steps 1–6 that safely can be (installing Python + Git,
cloning the repo, scaffolding `.env`, adding the firewall rule scoped to the NUC's actual
LAN subnet, first start + health check). **Deliberately still manual, per the existing
"Task Scheduler: not a script — too brittle" call below**: the router-side static IP
(no script has access to the router's admin UI) and the two Task Scheduler entries
(auto-start-on-boot and weekly backup) — scripting the "run whether logged on or not" boot
trigger would need the NUC account's Windows password handled non-interactively, which
trades one kind of fragility for another. See `SETUP.md` for the full breakdown of what's
automated vs. still manual, and why.

Windows Task Scheduler instructions (not a script — too brittle) for auto-start on boot and for
the weekly backup are in `SETUP.md`.

---

## How an open phone learns the NUC was updated

*(Rewritten 2026-10-06, Chunk 6.7 — the first version of the banner never fired in practice. The
UI side is in [UI/UX > Client auto-update notification](./ui-ux.md#client-auto-update-notification).)*

**The chain, end to end.** `update.bat` pulls new code and restarts the server → the server starts
with a new **build id** → an open page notices its own build id differs from the server's → it shows
"Update available" → the user taps → the browser fetches a fresh page whose scripts and styles are
fetched fresh too. Every link below has a way to fail; each one now has a guard and a test.

| Link | How it works now | Why it used to fail |
|---|---|---|
| **What a "build" is** | `build_id` = a 12-hex hash of every file under `app/` and `static/` (`app/services/version.py`). Changes exactly when the code changes; a docs/tests-only pull does not change it (no nagging for nothing). Needs no git. The git description (`release-…`) is only a human label. | It was `git describe` run once inside the server process, falling back to a constant `"dev"`. The server started by Task Scheduler (unelevated, different environment) may not have git on its PATH or may be refused by git's "dubious ownership" check, so every build said `"dev"` and nothing ever differed. |
| **What the page remembers** | The server writes the build id into the page it serves (`<meta name="app-build">`, `app/main.py > index()`); that is the page's baseline, known with no network call. | The baseline used to be "whatever /health answered on first load". A tab restored from cache *after* the server updated adopted the NEW build as its baseline and never noticed it was old — the common phone case. |
| **When it checks** | On load, when the tab becomes visible, on `pageshow` (back/forward cache), when the network returns, on focus, on navigation (≥30 s apart), and every 90 s while visible. A check that fails (the server is down ~10 s mid-restart) is retried at 5/10/20 s. Checks are coalesced (≥5 s apart). | A single 5-minute timer, which phones freeze when the tab is backgrounded; a check landing in the restart gap failed silently until the next tick. |
| **What the tap does** | Navigates to `/?b=<new build>#<same route>`: a fresh document request (`index.html` is `no-cache`) whose asset URLs all carry `?v=<new build>`, so every script/style is a new URL. If the page still isn't the new build afterwards it says **"Update didn't load — tap to try again"** instead of looping. | `location.reload()` revalidates only the HTML; `StaticFiles` sent no `Cache-Control`, so a phone could keep using "old enough" JS/CSS for hours — new HTML running old scripts. |
| **Cache policy** | `/` → `no-cache`; `/static/*` → `no-cache` (always revalidate; an unchanged file is a cheap 304); `/api/v1/health` → `no-store`. | none set |
| **Restarting** | `update.bat` → `stop.bat` → `scripts/stop_server.ps1` stops every `app.main`/`uvicorn` process **and whatever still listens on the port**, reports anything it could not stop, waits for the port to be free and exits non-zero if it isn't; → `start.bat` refuses to start if the port is still held (`scripts/verify_server.py port-free`), and once the server answers it confirms **the running build equals the code on disk** (`verify_server.py serving`, printed in the window and logged to `logs/app.log`). | `stop.bat` swallowed kill failures and always printed "Done."; a stale old server kept serving old code while the new process died on "address already in use". |

**Why `update.bat` itself was not changed.** `cmd.exe` re-reads a running batch file from disk by
byte offset, and `update.bat` runs `git pull` — which replaces `update.bat` — and then keeps
executing. Editing it risks garbage execution in the very update that deploys the edit (a likely
cause of the earlier "update.bat bricked" episodes). All restart behaviour therefore lives in
`stop.bat`, `start.bat` and `scripts/`, which `update.bat` merely `call`s — read fresh, after the pull.
A test (`tests/test_verify_server.py`) fails if `update.bat` starts referencing the new scripts.
Because `stop.bat`/`start.bat` are `call`ed *after* the pull, even the very first update that
delivers this change already uses the new versions.

**One-time thing for phones:** a tab that was loaded *before* this change has the old banner code,
so it will not show the new banner until it has been reloaded once. After that it is self-maintaining.

**Process model, for reference.** Normally the server is started at boot by Task Scheduler
(`SETUP.md` step 8, Auto-start on boot, unelevated, "restart every 1 minute up to 3 times if it fails"), and `update.bat`
stops it and starts a new one in the window you ran it from — **closing that window stops the
server** (leave it open, or reboot to hand it back to Task Scheduler). When `update.bat` kills the
Task Scheduler instance, the task sees a failure and retries in a minute; the retry finds the port
busy and exits (that is now reported plainly by `start.bat` rather than mysteriously).

**Checking it by hand.**
- `http://<nuc>:8080/api/v1/health` → `data.build_id` (compare with the Status page and with
  what the phone shows), `version` (label), `boot_id`/`started_at` (which process, since when).
- `logs/app.log`: `Build: id=… label=… boot_id=…` at every start; `Verify: OK …` or `Verify: PROBLEM …`
  after `start.bat`.
- On a phone: after an update, with the app open, the banner should appear within seconds of
  bringing the tab to the front.

**Tests.** `tests/services/test_version.py` (the hash and the label), `tests/routers/test_health.py`
and `test_static_serving.py` (headers, stamp, every asset URL versioned),
`tests/test_verify_server.py` (the checks and the scripts' structure),
`tests/frontend/test_update_banner.py` (the client in a real browser) and
`tests/frontend/test_update_banner_e2e.py` (a real server restart on changed code, a real tap, and
proof the new code is what runs — with every file dated 2000 so any heuristic caching would show).
The restart scripts were also run on a throwaway copy of the repo on a scratch port: start, refuse
a second start, simulate an update (build id changed), stop.

---

## Backup & Restore

Built in Phase 1.

- **Frequency:** weekly, via Windows Task Scheduler (`SETUP.md` step 9) — same mechanism as the
  auto-start task, no new infra.
- **What's backed up:** the SQLite `.db` file, copied verbatim with a timestamp, plus a
  plain-text JSON dump of every table alongside it (`scripts/backup.py`, `dump_db_to_json`).
  The JSON dump is what makes diffs meaningful in git — the raw `.db` file is an unreadable
  binary blob there.
- **Images:** excluded from the backup. Not versioned, not copied. Treated as
  lower-priority/regenerable.
- **Retention:** the 12 most recent backup pairs are kept locally; older ones are trimmed
  automatically on each run.
- **Destination:** a `backups/` folder in the project root (not gitignored). If the project is
  a git repository with an `origin` remote configured, `scripts/backup.py` also commits and
  pushes `backups/` automatically — this is the offsite copy. If there's no repo yet, or no
  remote, it logs a warning and stops there rather than failing the backup. See `SETUP.md`
  step 10 for connecting the private GitHub repo.
- **Credentials:** `.env` stays gitignored, never included in the backup or repo.
- **Restore path:** `scripts/restore.py` / `restore.bat`. Never overwrites without an explicit
  `--yes`; always saves a pre-restore copy of the current database first. **Actually tested
  during Phase 1** — run once end-to-end (list → dry run → `--yes` restore) rather than assumed
  to work when it's needed under pressure.

### SQLite WAL mode and backup safety

*(2026-09-13 code review)*

- **WAL (write-ahead log) mode is on**, set via a `PRAGMA journal_mode=WAL` in
  `app/database.py`'s connect-event listener (alongside the existing `PRAGMA foreign_keys=ON`).
  Two reasons: readers no longer block behind a writer or vice versa (matters once more than
  one household member's phone can be editing a checklist at the same time), and it de-risks
  backup — WAL keeps in-flight changes in a separate `-wal` file the main `.db` is never
  touched by until a checkpoint, closing the narrow window where a plain file copy under the
  old rollback-journal mode could catch a commit half-done.
- **Checked against the deploy workflow before enabling:** `data/` is already gitignored, so
  the new `-wal`/`-shm` sidecar files never interact with the git-based deploy/backup-push
  flow. The NUC's DB lives on local disk (not a network share), so WAL's shared-memory file
  works fine. No `start.bat`/`stop.bat`/`update.bat` changes were needed.
- **`scripts/backup.py` uses SQLite's own online backup API**
  (`sqlite3.connect(db_path).backup(sqlite3.connect(dest_db))`) instead of a raw
  `shutil.copy2` — safe against a concurrent writer under either journal mode, and folds any
  WAL content into one consistent output file (no `-wal`/`-shm` sidecars in the backup
  itself). A `PRAGMA integrity_check` runs against the copy immediately after; a bad result
  raises (failing the Task Scheduler run visibly) and deletes the bad copy, rather than
  discovering corruption later at restore time.
- **`scripts/restore.py`** removes any stale `mealplanner.db-wal` / `mealplanner.db-shm` next
  to the live path before copying a backup over it, so a leftover WAL from the pre-restore
  state can never be replayed against the freshly-restored file. The pre-restore safety copy
  still only needs to cover the main `.db` file, since the backup mechanism above never
  leaves anything durable in a sidecar file.
- **`scripts/update.py`'s migration step runs before the server is stopped** — see
  [Code Architecture & Maintainability > Migrations](./code-architecture.md#migrations) for
  the trade-off and why that ordering is deliberate, not an oversight.
- **Data loss on the NUC's prod DB from a deployed change is never acceptable** — see
  [Code Architecture & Maintainability > Data loss on prod is never
  acceptable](./code-architecture.md#data-loss-on-prod-is-never-acceptable). Every migration
  that reaches `update.bat` must be backwards compatible with the real prod data it will run
  against, not just with a fresh dev DB. The pre-restore safety copy and tested restore path
  above are the backstop for the unexpected, not a substitute for shipping a migration that's
  safe in the first place.

---

