# SETUP.md — First-run setup on the NUC

This covers getting ShoppingApp running on the always-on Windows 10 NUC and reachable from
phones on the home WiFi. Do this once. For shipping updates afterwards, see
[DEPLOY.md](DEPLOY.md).

---

## Quick path: run setup_nuc.bat

Steps 1–4 below (install Python + Git, clone the repo, scaffold `.env`, add the firewall
rule) plus a first start + health check are automated by `setup_nuc.bat`. It's re-run safe
— every step checks current state first and skips what's already done.

**Getting the script onto the NUC is the one unavoidable manual bit** — the NUC has nothing
on it yet, so nothing can pull the script for you. Copy these two files from the dev PC
to anywhere on the NUC (USB stick, a network share, OneDrive, email — whatever's easiest;
they don't need to be in any particular folder):
```
setup_nuc.bat
scripts\bootstrap_nuc.ps1
```
Then on the NUC, double-click `setup_nuc.bat`. It will prompt for admin (UAC) once — needed
for installing Python/Git machine-wide and adding the firewall rule — and pause partway
through for you to sign in to GitHub (cloning a private repo) and to fill in `.env` in
Notepad. Everything else runs unattended.

**Still manual after it finishes, on purpose** — see [Deployment Environment > Startup
in CLAUDE.md](CLAUDE.md#deployment-environment) for why:
- **Step 5** (static IP / router DHCP reservation) — no script has access to your router's
  admin UI.
- **Steps 8–9** (Task Scheduler: auto-start on boot, weekly backup) — kept as manual GUI
  steps rather than scripted, since scripting the "run whether logged on or not" boot
  trigger needs the account password handled non-interactively.

The rest of this file is the manual walkthrough of what the script automates — useful as
reference, if the script fails partway, if winget isn't available on this NUC, or if you'd
rather just see each step. Skip to [step 5](#5-give-the-nuc-a-fixed-local-ip-address) if
you ran the script.

---

## 1. Install Python and Git on the NUC

The NUC has a bare Windows 10 install (plus Plex) and neither yet.

1. On the NUC, download Python 3.11 or newer from <https://www.python.org/downloads/windows/>.
   (Developed and tested against Python 3.14.)
2. Run the installer. **Tick "Add python.exe to PATH"** on the first screen.
3. Choose "Install Now".
4. Verify in a new Command Prompt:
   ```
   python --version
   py -3 --version
   ```
   Both should print the version you installed.
5. Also install **Git for Windows** from <https://git-scm.com/download/win> (default
   options are fine) — the app itself doesn't need it, but deploying updates does (see
   step 2 and [DEPLOY.md](DEPLOY.md)).

---

## 2. Get the project onto the NUC

The project ships as a git clone, not a manual file copy — this is also how you'll pull
every future update (see [DEPLOY.md](DEPLOY.md) for the one-time GitHub setup this depends
on, done once from the dev PC first).

```
cd C:\Apps
git clone https://github.com/<you>/shoppingapp.git ShoppingApp
```

(`C:\Apps\ShoppingApp` is stable and avoids `C:\Program Files` (permissions) and the user
Desktop (clutter / roaming) — used throughout the rest of this guide.)

**If Git warns `LF will be replaced by CRLF the next time Git touches it`:** this repo's own
`.gitattributes` (`text=auto eol=crlf` — see [CLAUDE.md > Project Directory
Structure](CLAUDE.md#project-directory-structure)) deliberately forces CRLF in the working
tree, independent of the machine's `core.autocrlf` setting — the warning is just Git telling
you a (harmless, intended) conversion is pending, not a real problem. It's noisy rather than
useful here, so silence it once, scoped to this repo only:
```
cd C:\Apps\ShoppingApp
git config core.safecrlf false
```

---

## 3. Create the configuration file

1. In the project folder, copy `.env.example` to `.env`.
2. Open `.env` in Notepad. For Phase 1 you only need:
   ```
   PORT=8080
   LOG_LEVEL=INFO
   ```
   Leave `ANTHROPIC_API_KEY` and the `ANYLIST_*` values as placeholders — they are not used
   until Phase 3 and Phase 5 respectively.

---

## 4. First start

Double-click `start.bat` (or run it from a Command Prompt in the project folder).

On first run it will:
- create a virtual environment in `.venv`
- install dependencies
- create `.env` from the example if you skipped step 3
- start the server and open a browser to `http://localhost:8080/`

You should see the app load. Open the **Diagnostics** tab — the database indicator should be
green and the log tail should show startup messages.

Health check (from any browser on the NUC): <http://localhost:8080/api/v1/health>

To stop the server: press `Ctrl+C` in its window, or run `stop.bat`.

---

## 5. Give the NUC a fixed local IP address

So the phones can always reach it at the same address, the NUC needs a stable IP. The robust
way is a **DHCP reservation** in the router (preferred), with a **static IP on the NUC** as
an alternative.

### Find the NUC's current network details

Open Command Prompt on the NUC and run:
```
ipconfig /all
```
Note, for the active adapter (Ethernet or Wi-Fi):
- **IPv4 Address** (e.g. `192.168.1.42`)
- **Subnet Mask** (usually `255.255.255.0`)
- **Default Gateway** (your router, e.g. `192.168.1.1`)
- **Physical Address** (the MAC, e.g. `AA-BB-CC-DD-EE-FF`)
- **DNS Servers**

### Option A — DHCP reservation in the router (preferred)

1. Browse to the router admin page (the Default Gateway address) and log in.
2. Find **LAN / DHCP settings** → **DHCP Reservation** / **Address Reservation** /
   **Static Leases** (wording varies by brand).
3. Add a reservation mapping the NUC's **MAC address** to a chosen IP that is **inside the
   subnet but outside the DHCP pool** if possible (e.g. `192.168.1.10`). If you can't see the
   pool range, reserving its current IP is fine.
4. Save and reboot the NUC (or run `ipconfig /release` then `ipconfig /renew`).
5. Confirm with `ipconfig` that the NUC now has the reserved address.

This keeps DHCP on the NUC, so DNS and gateway stay correct automatically.

### Option B — Static IP configured on the NUC

Only if the router has no reservation feature.

1. **Settings → Network & Internet → Ethernet** (or Wi-Fi) → click the connection →
   **IP settings → Edit**.
2. Switch to **Manual**, turn on **IPv4**, and enter:
   - **IP address**: a free address in the subnet, outside the DHCP pool (e.g. `192.168.1.10`)
   - **Subnet prefix length**: `24` (for a `255.255.255.0` mask)
   - **Gateway**: the Default Gateway from `ipconfig /all`
   - **Preferred DNS**: your router's IP, or `1.1.1.1` / `8.8.8.8`
3. Save. Re-run `ipconfig /all` to confirm.
4. Test internet access from the NUC (Plex updates, etc. still need to work).

> Pick an address you know nothing else uses. If two devices claim the same IP you'll get
> intermittent connection failures that are annoying to diagnose.

### Once the NUC's address is fixed: update `ALLOWED_ORIGINS`

The app only accepts cross-origin browser requests from origins listed in `ALLOWED_ORIGINS`
in `.env` (see [CLAUDE.md > Security §4](CLAUDE.md#security) — this replaces an earlier
wide-open `allow_origins=["*"]` CORS setting). Add the NUC's new address to it:

```
ALLOWED_ORIGINS=http://localhost:8080,http://127.0.0.1:8080,http://192.168.1.10:8080
```

(substituting the NUC's actual address). Restart the server (`stop.bat` / `start.bat`) for
this to take effect. Skipping this step doesn't break phones reaching the app normally — it
only matters for cross-origin *browser JS* calls, which the phones' own use of the app
doesn't do — but it's the cheap half of keeping other devices on the WiFi from being able to
read/write the API via script, so do it while you're already touching `.env` in step 3/6.

---

## 6. Allow the port through Windows Firewall

The first time uvicorn binds the port, Windows may pop a firewall prompt — tick **Private
networks only** (not Public/Domain) and allow it.

If you missed the prompt, add the rule manually in an **elevated** Command Prompt, scoped to
the home LAN subnet rather than left open to any network (see [CLAUDE.md > Security](CLAUDE.md#security) —
this is a `[Phase 1 fix]` item, not optional hardening):

```
netsh advfirewall firewall add rule name="ShoppingApp 8080" dir=in action=allow protocol=TCP localport=8080 profile=private remoteip=192.168.1.0/24
```

Replace `192.168.1.0/24` with your actual home subnet (from `ipconfig /all` in step 5 — the
IPv4 address and subnet mask tell you the range, e.g. a `255.255.255.0` mask on `192.168.1.42`
means `192.168.1.0/24`). Match the port to `PORT` in `.env` if you changed it.

If a broad rule (any network, no `remoteip`) already got created via the popup, tighten it:
```
netsh advfirewall firewall set rule name="ShoppingApp 8080" new profile=private remoteip=192.168.1.0/24
```

---

## 7. Reach it from a phone

On a phone connected to the same WiFi, browse to:

```
http://<NUC-IP>:8080/
```

e.g. `http://192.168.1.10:8080/`. Add a home-screen shortcut/bookmark. (No PWA install — a
browser shortcut is all that's needed.)

---

## 8. Auto-start on boot (Task Scheduler)

A batch script for this is deliberately not provided — Task Scheduler is more reliable for
"run at boot" and is easy to inspect. Set it up once:

1. Start menu → **Task Scheduler** → **Create Task…** (not "Basic Task").
2. **General** tab:
   - Name: `ShoppingApp`
   - Select **Run whether user is logged on or not**.
   - **Leave "Run with highest privileges" UNTICKED.** This is a `[Phase 1 fix]` item (see
     [CLAUDE.md > Security](CLAUDE.md#security)) — the app doesn't need admin rights to run, and running it elevated
     needlessly increases the blast radius if a dependency ever has a vulnerability. It does not
     need elevation to bind port 8080 (only ports below 1024 need that) or to write to its own
     project folder.
   - Configure for: **Windows 10**.
3. **Triggers** tab → **New…**:
   - Begin the task: **At startup**.
   - Optionally set **Delay task for: 1 minute** so the network is up first.
4. **Actions** tab → **New…**:
   - Action: **Start a program**
   - Program/script: `C:\Apps\ShoppingApp\start.bat`
   - **Start in**: `C:\Apps\ShoppingApp`
5. **Conditions** tab:
   - Untick **Start the task only if the computer is on AC power** (NUC may report as such).
6. **Settings** tab:
   - Tick **If the task fails, restart every: 1 minute**, up to 3 times.
   - Untick **Stop the task if it runs longer than…** (it's a long-running server).
7. Click **OK**, enter the Windows account password when prompted.
8. Reboot the NUC and confirm the app is reachable from a phone without anyone logging in.

> `start.bat` opens a browser via `start ""`. When run headless by Task Scheduler that call
> simply does nothing — the server still starts. That's fine.

To update the app later, don't replace files by hand — run `update.bat` (see
[DEPLOY.md](DEPLOY.md)). It pulls the latest deployed release via git, reinstalls
dependencies if needed, and restarts the server. `.env`, `data/`, `images/`, and `logs/`
are gitignored so a pull never touches them.

---

## 9. Weekly automated backup (Task Scheduler)

See [CLAUDE.md > Backup & Restore](CLAUDE.md#backup--restore) for what gets backed up and why.
`backup.bat` does the work; this just schedules it weekly. Since step 2 already cloned the
project from GitHub, backups get committed and pushed automatically as part of each run —
into the same repo `update.bat` pulls code from (see [DEPLOY.md](DEPLOY.md)).

1. Start menu → **Task Scheduler** → **Create Task…**.
2. **General** tab:
   - Name: `ShoppingApp Backup`
   - Select **Run whether user is logged on or not**.
   - Leave **Run with highest privileges** unticked (same reasoning as step 8).
3. **Triggers** tab → **New…**:
   - Begin the task: **On a schedule** → **Weekly**, pick a day/time (e.g. Sunday 3am).
4. **Actions** tab → **New…**:
   - Action: **Start a program**
   - Program/script: `C:\Apps\ShoppingApp\backup.bat`
   - **Start in**: `C:\Apps\ShoppingApp`
5. **Settings** tab: tick **If the task fails, restart every: 15 minutes**, up to 2 times.
6. Click **OK**. Right-click the task → **Run** once to test it, then check `backups\` for a new
   `mealplanner_<timestamp>.db` / `.json` pair and `logs\app.log` for a "Backup: complete" line.

**Test the restore path too, now, not when you actually need it** (per CLAUDE.md — a restore
script that's never been run is not a real backup plan):
```
restore.bat                 REM lists what's available
restore.bat latest          REM dry run — shows what it would do
restore.bat latest --yes    REM actually restores; saves a pre-restore safety copy first
```

## 10. GitHub remote — already connected

Step 2 cloned the project from GitHub, so `origin` is already configured on the NUC —
there's nothing left to do here. That one repo now serves two jobs: `update.bat` pulls
code changes from it, and `backup.bat` pushes weekly database backups to it. `.env` stays
out of it either way — it's in `.gitignore`.

(If you're reading this because `backup.bat` logged "no origin remote configured" — that
means step 2 was skipped and the project was copied by hand instead. Fix it with
`git remote add origin https://github.com/<you>/shoppingapp.git` from the project folder.)

---

## Troubleshooting

| Symptom | Check |
|---|---|
| `start.bat` closes instantly | Run it from a Command Prompt so you can read the error. Usually Python not on PATH. |
| Browser can't reach it from the NUC itself | Is the server window still open? Check `http://localhost:8080/api/v1/health`. |
| Phone can't reach it, NUC can | Firewall rule (step 6), and phone is on the same WiFi (not guest network). |
| Works then stops after a reboot | Task Scheduler task (step 8) — check its **Last Run Result** in Task Scheduler. |
| Database indicator red on Diagnostics | Check `logs/app.log`. The `data/` folder must be writable. |
| Port already in use | Something else took 8080 — change `PORT` in `.env` and the firewall rule. |
| Backup task ran but nothing pushed | Check `git remote get-url origin` works from the project folder (see step 10). Backups are still saved locally either way. |
| `update.bat` fails or won't restart the server | See [DEPLOY.md > Things that can go wrong](DEPLOY.md#things-that-can-go-wrong). |
| Git warns `LF will be replaced by CRLF the next time Git touches it` | Harmless — this repo's `.gitattributes` intentionally forces CRLF. Run `git config core.safecrlf false` from inside the project folder to silence it — see step 2. |
