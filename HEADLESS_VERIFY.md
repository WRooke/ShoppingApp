# HEADLESS_VERIFY.md — driving the frontend in a headless browser

The manual-verification step for frontend chunks (Phase 2 Chunk 2.4 onward) needs a real
browser rendering the real pages against a real server. This is the **one documented,
working way** to do that. Follow it exactly — the failure modes below are the ones that
have bitten every past attempt.

There is **no Node, no Playwright, no `chromium-cli`** on the dev PC or the NUC. Do **not**
try to install them. The tooling here is Edge (already installed) + `scripts/cdp.py`
(stdlib only, committed, no `pip install` ever).

---

## TL;DR

```bash
# 1. start a throwaway server on a scratch DB in fake mode (never touches data/mealplanner.db)
SCRATCH="$(python -c 'import tempfile,os;print(tempfile.gettempdir())')/sa-verify"
mkdir -p "$SCRATCH"
DATABASE_PATH="$SCRATCH/t.db" LOGS_PATH="$SCRATCH/logs" IMAGES_PATH="$SCRATCH/img" \
  PORT=8099 AI_EXTRACTION_FAKE_MODE=true ALLOWED_ORIGINS="http://127.0.0.1:8099" \
  .venv/Scripts/python.exe -m app.main > "$SCRATCH/server.log" 2>&1 &
sleep 5 && curl -s http://127.0.0.1:8099/api/v1/health   # expect {"ok":true,...}

# 2a. quick check — dump the rendered DOM after JS settles
.venv/Scripts/python.exe -m scripts.cdp "http://127.0.0.1:8099/#/recipes/new"

# 2b. real interaction — write a short driver script (see example below) and run it
.venv/Scripts/python.exe path/to/verify_something.py

# 3. always clean up
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | ? { \$_.CommandLine -like '*app.main*' } | % { Stop-Process -Id \$_.ProcessId -Force }"
```

Put scratch scripts, screenshots, the scratch DB and `server.log` in the session scratchpad
dir, **never** in the repo. Nothing here gets committed except `scripts/cdp.py` itself.

---

## The server

- Run it with `python -m app.main` (the app's own entrypoint), **not** raw
  `uvicorn ... --log-config=...`. `app.main` passes `log_config=None`; passing
  `--log-config=/dev/null` (or `NUL`) to uvicorn makes it try to parse an empty file and
  crash with `RuntimeError: <file> is an empty file`.
- Always override `DATABASE_PATH`, `LOGS_PATH`, `IMAGES_PATH` to a scratch location. The
  default is the real `data/mealplanner.db`.
- `AI_EXTRACTION_FAKE_MODE=true` — capture flows return canned fixtures, zero key, zero cost
  (CLAUDE.md > Security §0c). Never set `AI_EXTRACTION_ENABLED`. (Both were renamed from
  `CLAUDE_API_*` at Phase 3.9 M1 — see CLAUDE.md > AI Provider Migration.)
- Pick a port Plex/other stuff won't have (8099 is fine). Set `ALLOWED_ORIGINS` to match.
- `data/mealplanner.db` is the working dev DB — leave it alone. If a check needs seed
  recipes, create them through the API against the scratch server.

## The browser — `scripts/cdp.py`

A minimal Chrome DevTools Protocol client (works with Edge). **Zero dependencies** — it
speaks the WebSocket protocol itself. Import `Browser` from it:

```python
import sys; sys.path.insert(0, "F:/_code/ShoppingApp")
from scripts.cdp import Browser

with Browser("http://127.0.0.1:8099/#/recipes/new") as b:
    b.wait_for("input")                       # CSS selector present in the DOM
    b.fill("input", "Sunday Roast Chicken", nth=0)   # sets value + fires input/change/blur
    b.fill(".ingredient-edit-row input", "salt", nth=0)
    b.fill(".ingredient-edit-row input", "1", nth=1)
    b.click("button.primary")                 # or b.click("button", contains="Save anyway")
    b.wait_for(".dup-warn")
    print(b.text(".dup-warn-heading"))
    print(b.eval("location.hash"))            # run arbitrary JS, value returned
    b.screenshot(r"C:\path\in\scratchpad\out.png")
    assert not b.console_errors(), b.console_errors()   # JS errors/warnings collected
```

Cross-check anything that matters against the API directly (`curl .../api/v1/recipes/<id>`)
rather than trusting the DOM alone — same discipline as prior chunks.

### Why past attempts failed (all handled by `scripts/cdp.py` now)

| Symptom | Cause | Handled by |
|---|---|---|
| Edge "opens" but nothing happens / hangs | stale/locked `--user-data-dir`, or it reused an already-running Edge | `Browser` always makes a **fresh** temp profile dir |
| `--dump-dom` shows an empty `#view` | dump happened before the SPA's JS/fetch ran | `_settle()` after navigate; `wait_for(selector)` polls |
| Can't click buttons with `--dump-dom` | `--dump-dom` is read-only | CDP `Runtime.evaluate` → `element.click()` |
| `ERR_BLOCKED_BY_CLIENT` / CSP weirdness on assets | none — this app serves its own assets | n/a, local only |
| Needed `websocket-client`, then removed it | ad-hoc each time | `cdp.py` implements RFC6455 framing itself |

### Fixed invocation flags (already in `cdp.py`)

`--headless=new --disable-gpu --no-sandbox --no-first-run --disable-extensions
--remote-debugging-port=9222 --user-data-dir=<fresh temp> --window-size=414,896`

Set `CDP_BROWSER` env var to a browser `.exe` path to override auto-detection
(Edge x86 → Edge x64 → Chrome).

## Cleanup (do it every time)

```bash
# stop the scratch server
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | ? { \$_.CommandLine -like '*app.main*' } | % { Stop-Process -Id \$_.ProcessId -Force }"
```

`Browser.__exit__` terminates its own Edge process and its temp profile is in the system
temp dir; a stray `msedge.exe --headless` from a crashed run can be killed with
`Get-Process msedge | ? Path -like '*Edge*' | Stop-Process -Force`.
