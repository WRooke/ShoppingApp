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
  verifies the working tree is clean and current, tags the commit, pushes `develop` + the
  tag to the private GitHub repo, then fast-forwards the remote `production` branch to
  match.
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

---

