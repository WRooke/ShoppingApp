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

### Log file
- Write to `logs/app.log` in the project root
- Rotate daily, keep 14 days of history (`logging.handlers.TimedRotatingFileHandler`)
- The in-memory ring buffer that backs the Diagnostics UI (`/logs`, `/recent-errors`) holds
  the most recent 5000 entries (`app/log_config.py::RING_BUFFER_MAXLEN`, raised from 1000 at
  chunk 7.7) — bounded, not unbounded, so `app.log` (unbounded, rotated daily instead) is the
  place to look for anything older than the buffer currently holds
- A `logging.Filter` on the `asyncio` logger downgrades WinError 10054
  (`ConnectionResetError`, WSAECONNRESET) noise from a Windows client dropping its TCP
  connection mid-request — routine on a home LAN/WiFi, not an application fault — from ERROR
  to DEBUG, so it no longer floods `/recent-errors`; still visible at DEBUG when
  `LOG_LEVEL=DEBUG` (`app/log_config.py::_WinsockResetNoiseFilter`, chunk 7.7 5d). Nothing
  else is filtered this way — an unrelated real connection error still surfaces at ERROR.

### Diagnostics web UI
A `/diagnostics` page in the web app (accessible from the main nav) must show:
- **Live log tail**: last 200 log entries, auto-refreshing every 5 seconds, filterable by level
- **Component status panel**: green/amber/red indicators for:
  - Database connection
  - AI extraction service (Gemini) — last successful call timestamp, and which model handled
    it (`flash` / `flash-lite`) or whether the last capture is queued
  - AnyList connection (last successful auth timestamp)
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
  10" until 2026-10-01 diagnostics chunk 7.7, 5a/5b — a truncated slice was hiding real
  errors on a busy day)*

The diagnostics page must be built as a skeleton in Phase 1 and populated progressively as
each component is added.

---

