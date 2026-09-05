# DEPLOY.md — dev PC → NUC deployment

How code gets from the dev PC, where you write and test it, onto the NUC, where it
actually runs. Read this once to set it up; day to day it's two commands
(`deploy.bat` then `update.bat`).

**How it works:** the transport is git, not a copy/zip step. The dev PC and the NUC are
two clones of the same private GitHub repo. `deploy.bat` (dev PC) commits/tags/pushes.
`update.bat` (NUC) pulls and restarts. This is also the exact repo `backup.bat` already
pushes weekly database backups to (see [CLAUDE.md > Backup & Restore](CLAUDE.md#backup--restore))
— one repo, two jobs. Restarting the server on the NUC stays a manual step (running
`update.bat` there) rather than being triggered remotely from the dev PC — deliberately,
to keep this from needing WinRM/SSH set up on the NUC.

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
git branch -M main
git remote add origin https://github.com/<you>/shoppingapp.git
git add .
git commit -m "Initial commit"
git push -u origin main
```

If `git config --global user.name` / `user.email` aren't already set (check with those two
commands), set them first — any commit needs an identity:

```
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

### 3. Clone the repo onto the NUC

Once Python is installed on the NUC (SETUP.md step 1), also install **Git for Windows**
from <https://git-scm.com/download/win> (default options are fine). Then, instead of
copying files by hand:

```
cd C:\Apps
git clone https://github.com/<you>/shoppingapp.git ShoppingApp
cd ShoppingApp
copy .env.example .env
notepad .env
```

Fill in `.env` with the real values for the NUC (same as SETUP.md step 3). This replaces
the old "copy the folder" step — everything else in SETUP.md (steps 4 onward: first start,
static IP, firewall, Task Scheduler, backups) is unchanged.

---

## Day to day: shipping a change

**On the dev PC**, once your change is committed to git as normal (`git add` / `git commit`
— `deploy.bat` doesn't do this for you, on purpose, so you always know exactly what you're
about to ship):

```
deploy.bat
```

This checks your working tree is clean and not behind `origin/main`, tags the commit
(`release-<UTC timestamp>`), and pushes the branch and tag. It refuses to run — with a
clear reason — if there are uncommitted changes or you're behind origin.

**On the NUC**, to actually deploy it:

```
update.bat
```

This pulls the new commit (fast-forward only — it will never merge or force anything),
reinstalls dependencies in case `requirements.txt` changed, then stops and restarts the
server. If any of that fails, it stops before touching the running server, so a bad update
leaves the *old* version running rather than the app down. Run it directly at the NUC's
keyboard or over Remote Desktop.

---

## Rollback

Every deploy is a tag, so rolling back is a normal git operation on the NUC:

```
git log --oneline --decorate -10          REM find the release tag to go back to
git checkout release-20260901-120000Z     REM detach to that exact commit
stop.bat
start.bat
```

To resume normal deploys afterwards, get back on the branch tip: `git checkout main`, then
next `update.bat` will fast-forward from wherever `main` currently is.

---

## Things that can go wrong

| Symptom | What's happening | Fix |
|---|---|---|
| `deploy.bat` says "uncommitted changes" | You have unstaged/uncommitted edits | `git add` / `git commit` them, or discard, then re-run |
| `deploy.bat` says "behind origin" | Something else (rare — this repo is normally dev-PC-only for code) pushed to main | `git pull --ff-only`, then re-run |
| `update.bat` says "uncommitted or local changes" on the NUC | Someone edited a file directly on the NUC, or a backup commit is sitting there unpushed | Check `git status` on the NUC; commit/push or discard as appropriate, then re-run |
| `update.bat` says "git pull --ff-only failed - diverged" | The NUC's `main` has commits `origin` doesn't (shouldn't normally happen — backups commit to the same branch but `backup.py` now rebases onto origin before pushing, precisely to avoid this) | Look at `git log --oneline --all --graph` on the NUC and resolve by hand; don't force-push over it without understanding why first |
| `update.bat` says "pip install failed" | A new/changed dependency couldn't install (e.g. no internet on the NUC right then) | Fix connectivity or the dependency, re-run `update.bat` — the old server is still running until this step succeeds |
| Weekly backup push fails after a deploy | Backup ran before you deployed and its push raced with yours, or vice versa | Not fatal — the backup is still saved locally in `backups/`; `backup.py` will rebase and push cleanly next week. Check `logs/app.log` if it keeps happening |

---

## Why not X

- **Docker** — ruled out project-wide (see CLAUDE.md > Tech Stack): Will is unfamiliar with
  it and it adds a moving part this single-machine deployment doesn't need.
- **Remote restart from the dev PC (WinRM/SSH)** — would make `deploy.bat` fully
  hands-off, but requires enabling and maintaining remoting/SSH on the NUC. Revisit if the
  manual `update.bat` step on the NUC becomes annoying in practice.
- **Zip + network copy** — works fine on a LAN but re-invents versioning, rollback, and
  "what's actually running" that git already gives for free, and this repo already exists
  for backups (see CLAUDE.md > Backup & Restore) so there's no new infrastructure to add.
