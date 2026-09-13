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
  running server if any step fails, so a bad update leaves the old version running.

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

## Backup & Restore

**Build now (Phase 1)** — Schema & Planning Addendum #4.

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

### SQLite WAL mode and backup safety (2026-09-13 code review)

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

---

