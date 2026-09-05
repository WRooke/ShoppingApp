# DEPLOY.md — dev PC → NUC deployment

How code gets from the dev PC, where you write and test it, onto the NUC, where it
actually runs. Read this once to set it up; day to day it's two commands
(`deploy.bat` then `update.bat`).

**How it works:** the transport is git, not a copy/zip step. The dev PC and the NUC are
two clones of the same private GitHub repo, checked out on different branches:

- **`develop`** — the dev PC. Everything is committed here, phase by phase, as normal.
- **`production`** — the NUC. Only ever advances by being fast-forwarded from `develop`
  via `deploy.bat`; nothing is committed to it directly except the NUC's own weekly backup
  commits (see below).

`deploy.bat` (dev PC, run from `develop`) commits/tags/pushes `develop`, then fast-forwards
the remote `production` branch to match. `update.bat` (NUC, run from `production`) pulls
that and restarts. Two branches, one repo — this is also the exact repo `backup.bat`
already pushes weekly database backups to (see
[CLAUDE.md > Backup & Restore](CLAUDE.md#backup--restore)), landing on `production` since
that's what the NUC is checked out on. See
[CLAUDE.md > Deferred Decisions > Git branching strategy](CLAUDE.md#deferred-decisions) for
why this replaced the original single-`main` setup, decided at the Phase 2 review.

Restarting the server on the NUC stays a manual step (running `update.bat` there) rather
than being triggered remotely from the dev PC — deliberately, to keep this from needing
WinRM/SSH set up on the NUC.

Because `.env`, `data/`, `images/`, `logs/`, and `.venv/` are all gitignored, a `git pull`
never touches your credentials, database, uploaded photos, or logs — only the code changes.
No manual "keep these folders" copying is needed the way an ad-hoc file copy would need.

---

## One-time setup

### 1. Create the private GitHub repo

On [github.com](https://github.com/new), create a new **private** repository (no README,
no `.gitignore`, no license — this project already has all three). Note its URL, e.g.
`https://github.com/<you>/shoppingapp.git`.

### 2. Initialise the repo on the dev PC

From the project root (`F:\_code\ShoppingApp`):

```
git init
git checkout -b develop
git remote add origin https://github.com/<you>/shoppingapp.git
git add .
git commit -m "Initial commit"
git push -u origin develop
git branch production develop
git push -u origin production
```

`develop` and `production` start out identical — they only diverge once the first real
deploy happens. If `git config --global user.name` / `user.email` aren't already set (check
with those two commands), set them first — any commit needs an identity:

```
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

> **Migrating an existing single-`main` clone to this model** (this repo's actual history —
> everything through the Phase 2 review — was pushed to `origin/main` before this branch
> split was decided): on the dev PC, `git branch -m main develop` then `git push -u origin
> develop`; `git branch production develop` then `git push -u origin production`. On
> GitHub, change the repo's default branch to `develop` (Settings → Branches), then delete
> the now-unused `main` from the remote (`git push origin --delete main`) once you're happy
> `develop`/`production` both look right. None of this happens automatically — Claude Code
> creates commits but never pushes or touches GitHub settings (see CLAUDE.md > Commits), so
> this step is yours to run by hand.

### 3. Get the repo onto the NUC

Run `setup_nuc.bat` (see [SETUP.md > Quick path](SETUP.md#quick-path-run-setup_nucbat)) —
it installs Python + Git, clones the repo, scaffolds `.env`, and adds the firewall rule in
one pass. Or do it by hand — **note the NUC checks out `production`, not the repo's
default branch**:

```
cd C:\Apps
git clone https://github.com/<you>/shoppingapp.git ShoppingApp
cd ShoppingApp
git checkout production
copy .env.example .env
notepad .env
```

Fill in `.env` with the real values for the NUC (same as SETUP.md step 3). Either way,
everything else in SETUP.md (static IP, Task Scheduler, backups) is unchanged.

---

## Day to day: shipping a change

**On the dev PC**, on `develop`, once your change is committed to git as normal (`git add`
/ `git commit` — `deploy.bat` doesn't do this for you, on purpose, so you always know
exactly what you're about to ship):

```
deploy.bat
```

This checks you're on `develop`, your working tree is clean and not behind
`origin/develop`, tags the commit (`release-<UTC timestamp>`), pushes the branch and tag,
then fast-forwards `origin/production` to match. It refuses to run — with a clear reason —
if there are uncommitted changes, you're behind origin, you're on the wrong branch, or the
production fast-forward isn't possible (see the troubleshooting table below).

**On the NUC**, on `production`, to actually deploy it:

```
update.bat
```

This pulls the new commit on `production` (fast-forward only — it will never merge or
force anything), reinstalls dependencies in case `requirements.txt` changed, then stops and
restarts the server. If any of that fails, it stops before touching the running server, so
a bad update leaves the *old* version running rather than the app down. Run it directly at
the NUC's keyboard or over Remote Desktop.

---

## Rollback

Every deploy is a tag, so rolling back is a normal git operation on the NUC:

```
git log --oneline --decorate -10          REM find the release tag to go back to
git checkout release-20260901-120000Z     REM detach to that exact commit
stop.bat
start.bat
```

To resume normal deploys afterwards, get back on the branch tip: `git checkout production`,
then next `update.bat` will fast-forward from wherever `production` currently is.

---

## Things that can go wrong

| Symptom | What's happening | Fix |
|---|---|---|
| `deploy.bat` says "uncommitted changes" | You have unstaged/uncommitted edits | `git add` / `git commit` them, or discard, then re-run |
| `deploy.bat` says "On branch '...', not 'develop'" | You're on a feature branch, `production`, or detached HEAD | `git checkout develop`, then re-run |
| `deploy.bat` says "behind origin" | Something else (rare — this repo is normally dev-PC-only for code) pushed to `develop` | `git pull --ff-only`, then re-run |
| `deploy.bat` says "fast-forwarding production... failed" | `origin/production` has commits `develop` doesn't — almost always an unmerged NUC backup commit | `git fetch origin && git merge origin/production` on the dev PC to bring the backup commit into `develop`, then re-run `deploy.bat`. `develop` and the tag are already pushed at this point — only the `production` fast-forward is retried. The NUC keeps running whatever it was already on until this succeeds, so it isn't left broken |
| `update.bat` says "On branch '...', not 'production'" | The NUC checkout has drifted (e.g. mid-rollback and not resumed) | `git checkout production`, then re-run |
| `update.bat` says "uncommitted or local changes" on the NUC | Someone edited a file directly on the NUC, or a backup commit is sitting there unpushed | Check `git status` on the NUC; commit/push or discard as appropriate, then re-run |
| `update.bat` says "git pull --ff-only failed - diverged" | The NUC's `production` has commits `origin` doesn't (shouldn't normally happen — backups commit to the same branch but `backup.py` now rebases onto origin before pushing, precisely to avoid this) | Look at `git log --oneline --all --graph` on the NUC and resolve by hand; don't force-push over it without understanding why first |
| `update.bat` says "pip install failed" | A new/changed dependency couldn't install (e.g. no internet on the NUC right then) | Fix connectivity or the dependency, re-run `update.bat` — the old server is still running until this step succeeds |
| Weekly backup push fails after a deploy | Backup ran before you deployed and its push raced with yours, or vice versa | Not fatal — the backup is still saved locally in `backups/`; `backup.py` will rebase and push cleanly next week. Check `logs/app.log` if it keeps happening |

---

## Why not X

- **Docker** — ruled out project-wide (see CLAUDE.md > Tech Stack): the primary user is
  unfamiliar with it and it adds a moving part this single-machine deployment doesn't need.
- **Remote restart from the dev PC (WinRM/SSH)** — would make `deploy.bat` fully
  hands-off, but requires enabling and maintaining remoting/SSH on the NUC. Revisit if the
  manual `update.bat` step on the NUC becomes annoying in practice.
- **Zip + network copy** — works fine on a LAN but re-invents versioning, rollback, and
  "what's actually running" that git already gives for free, and this repo already exists
  for backups (see CLAUDE.md > Backup & Restore) so there's no new infrastructure to add.
