# Diagnostics & Logging

## Diagnostics & Logging

This is a first-class requirement, not an afterthought. The system must make it
readily apparent when, where, why and how something has failed.

### Rules
- Every module must use Python's `logging` library with a named logger (`logging.getLogger(__name__)`)
- Log levels: DEBUG (request/response detail, internal state), INFO (user actions, session events),
  WARNING (recoverable issues, unexpected but non-fatal states), ERROR (failures, exceptions)
- All exceptions must be caught at the outermost handler, logged with `exc_info=True`, and
  return a structured JSON error response to the frontend
- Every external API call (Claude API, AnyList, URL fetch) must be wrapped in try/except,
  log the attempt at INFO, log success at INFO, log failure at ERROR with full exception info
- Log format: `%(asctime)s [%(levelname)s] %(name)s: %(message)s`

### Failure logging

*(2026-10-07 audit)*
Every point of failure must say **what failed and why** in one line, without opening a debugger:
the operation, the identifiers that locate it (`push_id`, `context`/recipe/session id, queue item
id), the exception type and message, how long it took, and a traceback wherever the cause is not
already obvious. Concretely:
- **Where, not just whether.** A failure is logged at the place it happens (login, a data POST, a
  parse, a DB commit) as well as translated into an error response by the handler in `main.py`.
  The 502 handlers log at ERROR with the exception type and a traceback; an AI failure is logged
  once at ERROR by `ai_extraction/client.py` and by the handler at WARNING, so it is not counted
  twice.
- **Expected vs unexpected.** A user-supplied URL that 404s or times out is a WARNING with no
  traceback; a transport fault, an unparseable AI reply, a failed commit is an ERROR with one.
- **Validation (422) and 4xx/5xx `HTTPException`s** are logged with the field locations and
  messages (never the submitted values) / the `detail`. 404/405 are INFO.
- **Push context.** A failure anywhere in `push_to_anylist` — the list read, mid-push, saving the
  history after items landed — logs the `push_id`, so it joins up with the per-operation lines
  the connector wrote under the same id (`docs/anylist-push.md` > Runbook).
- **Silent masks are not allowed.** Corrupt JSON columns, swallowed exceptions and "treat as
  empty" fallbacks log a WARNING with the row id. A stored response that cannot be read is
  reported as **not confirmed**, never as confirmed.
- **Never logged:** secrets (the Gemini key, AnyList email/password — `log_config.redact()` masks
  the configured values and Google-key-shaped strings in the file, console and ring buffer), an
  AI reply in full (`describe_raw()`: length + first 200 chars), a response body from AnyList
  (status + byte count only), a URL's query string or fragment, or submitted field values.
- **Level hygiene.** `LOG_LEVEL` is validated (a typo falls back to INFO with a warning, instead
  of crashing at import). The app's own successful polling requests (`/health`, the diagnostics
  polls, capture/push progress) are logged at DEBUG; failures and everything else stay at INFO.

#### Browser errors
`static/js/error-report.js` reports `window.onerror`, unhandled promise rejections, a view that
throws while mounting, and `fetch` failures/unparseable responses to `POST /api/v1/client-log`
(`app/routers/client_log.py`, `app/services/client_log.py`). They are written under the
`app.client` logger — ERROR for script errors/rejections/view crashes, WARNING for failed
requests (routine while the server restarts for an update) — so they show up in Recent errors.
The endpoint is LAN-only like everything else and treats its input as hostile: bounded fields,
line breaks neutralised (a report cannot forge log lines), query strings stripped, 20 reports per
minute per client, at most 10 per page load from the browser. It always answers ok.

A bare **"Script error."** (no filename, no Error object) is the browser deliberately hiding an
error from a script on another origin. Every app script is same-origin, so on a phone this is a
browser extension, never the app: `error-report.js` sends it as kind `cross_origin`
(message "Script error from outside the app (no details - usually a browser extension)"), logged at
WARNING so it no longer lights the red Status dot but is still visible in the log (2026-10-16).

**Copy errors** (Status → Recent errors) used to throw on Firefox for Android: the app is served over
plain HTTP, where `navigator.clipboard` does not exist. It now tries the async API (secure contexts
only), then a select-and-`execCommand("copy")` fallback, and only if both fail shows the text in a
box, already selected, for press-and-hold copying (`diagnostics.js > copyText`).

#### Startup and scripts
- Startup logs the build id, then the schema check (`app/services/schema_check.py`): the
  `alembic_version` stamp against the migration head — a WARNING naming both revisions when the
  database is behind the code.
- `scripts/update.py` streams pip/alembic output to the console **and** writes it to `app.log`
  (tail on success, up to 200 lines on failure). `scripts/backup.py` exits non-zero when the git
  commit/push failed (the backup file is still saved). `scripts/restore.py` verifies the backup
  with `PRAGMA integrity_check` before overwriting anything, and verifies the result after.
- Helper scripts append to `app.log` without rotating it (`setup_logging(rotate=False)`); only
  the server rotates, so two processes never fight over the midnight rollover on Windows.

### Log file
- Write to `logs/app.log` in the project root
- Rotate daily, keep 14 days of history (`logging.handlers.TimedRotatingFileHandler`)
- WARNING-and-above are also kept in their own ring (`ERROR_RING_MAXLEN`, 500), which is what
  `level=WARNING|ERROR` reads (and so `/recent-errors`) use — routine INFO traffic can no longer
  push errors out of memory. Entries are capped at 2,000 characters of message (the file keeps
  the full line).
- The in-memory ring buffer that backs the Diagnostics UI (`/logs`, `/recent-errors`) holds
  the most recent 5000 entries (`app/log_config.py::RING_BUFFER_MAXLEN`, raised from 1000 at
  the Status page fixes) — bounded, not unbounded, so `app.log` (unbounded, rotated daily instead) is the
  place to look for anything older than the buffer currently holds
- A `logging.Filter` on the `asyncio` logger downgrades WinError 10054
  (`ConnectionResetError`, WSAECONNRESET) noise from a Windows client dropping its TCP
  connection mid-request — routine on a home LAN/WiFi, not an application fault — from ERROR
  to DEBUG, so it no longer floods `/recent-errors`; still visible at DEBUG when
  `LOG_LEVEL=DEBUG` (`app/log_config.py::_WinsockResetNoiseFilter`, the Status page fixes 5d). Nothing
  else is filtered this way — an unrelated real connection error still surfaces at ERROR.

### Diagnostics web UI
A `/diagnostics` page in the web app (accessible from the main nav) must show:
- **Live log tail**: last 200 log entries, auto-refreshing every 5 seconds, filterable by level
- **Component status panel**: green/amber/red indicators for:
  - Database connection
  - AI extraction service (Gemini) — last successful call timestamp, and which model handled
    it (`flash` / `flash-lite`) or whether the last capture is queued
  - AnyList connection (last successful auth timestamp) — **plus, since 2026-10-06 (Chunk 6.7, user-feedback batch), the last push in full**:
    its `push_id` (the same id is on every log line of that push), when, confirmed or not, counts per outcome and the
    **per-item result** (added / updated / un-crossed / already-active / failed + the reason) and timings; and a list of recent
    pushes (`GET /api/v1/diagnostics/pushes`). This is the first stop for "why didn't X arrive?" — see
    [anylist-push.md > Runbook](./anylist-push.md#7-runbook--an-item-didnt-arrive-on-anylist). *(API in place; the Diagnostics
    page's per-item rendering follows the approved mockup.)*
- **Daily quota usage indicator**: observed Gemini request count today per model (from
  `ai_call_log`), plus a link to the Google AI Studio dashboard. Best-effort — exact free-tier
  caps are not reliably documented, so this is an observed count, not "X of Y". *(Replaced the
  old USD "API spend tracker" + reset button at Phase 3.9 — the Gemini free tier has no
  per-call dollar cost. See [AI Provider Migration](./recipe-capture.md#ai-provider-migration--anthropic-claude--google-gemini-phase-39).)*
- **Recent capture attempt log**: last N `ai_call_log` rows — task type, model tried, outcome
  (`success` / `quota` / `error` / `queued`), error detail. Queued captures are also surfaced
  here.
- **Recent errors**: every ERROR-level (and above) entry currently in the ring buffer,
  highlighted prominently at the top, with a "Copy errors" button that copies all of them
  (timestamp, level, message, full traceback) to the clipboard in one go *(was a fixed "last
  10" until 2026-10-01 the Status page fixes — a truncated slice was hiding real
  errors on a busy day)*

The diagnostics page must be built as a skeleton in Phase 1 and populated progressively as
each component is added.

---

