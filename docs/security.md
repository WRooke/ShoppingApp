# Security

## Security

Covers the security posture for the app's deployment on the NUC. The system is
local-network-only by design — no internet exposure is required or intended. The goal is not
to harden this like an internet-facing service, but to make sure a compromised or
untrustworthy device on the home WiFi (an IoT gadget, a guest's phone) can't read AnyList
credentials or interfere with the app.

Items marked **`[Phase 1 fix]`** apply to the already-built Phase 1 app. Where the fix is
config/environment (firewall scope, Task Scheduler privilege level) it's applied at NUC
deployment time — see `SETUP.md` steps 6 and 8, which carry the concrete commands/checkboxes.
Where it's something Claude Code can just do (repo hygiene), it's done.

### 0a. Prompt Injection Hardening (highest priority)

**Set 2026-09-05 — see [Non-Negotiable Operating Rules](../CLAUDE.md#-non-negotiable-operating-rules).**
Any content this app sends to an LLM that did not originate from the household's own direct
input — a scraped recipe webpage, a photographed cookbook page, or any future untrusted
source — is treated as data only, never as instructions, and the app is built to resist
attempts embedded in that content to change its behaviour. This overrides every other design
concern, including the usual `services/` "no DB" purity and "small stable interface" norms in
[Code Architecture](./code-architecture.md#code-architecture--maintainability) where they'd otherwise conflict.

Concretely, for every LLM call that includes untrusted content (post-Phase-3.9: the
extraction and substitution-flagging calls in `services/ai_extraction.py`; pre-M1:
`claude_client.py` > `extract_ingredients()`):
- The system prompt explicitly tells the model the untrusted content is data, not
  instructions, and to ignore anything inside it that looks like a request to change
  behaviour, reveal the prompt, or do anything other than extract ingredients.
- The untrusted content is wrapped in an explicit, non-guessable delimiter tag in the user
  message, so it can never be mistaken for a system-level instruction or spoof its own
  closing tag.
- Input length is capped (`MAX_INPUT_TEXT_CHARS` in `claude_client.py`) — this bounds the
  size of any injected payload, and incidentally keeps per-call cost predictable too.
- The parsed response is validated against strict expected types and, for any field with a
  fixed vocabulary (`suggested_section`), an allow-list — a hallucinated or injected value
  outside that vocabulary is discarded (set to `null`), never passed through. Never trust a
  field's content just because the JSON parsed.
- No tool-use / code execution / external actions are ever granted to an extraction call, and
  this must stay true — an injection that can only influence the JSON payload returned (which
  the user reviews and can edit before anything is saved, per
  [Recipe Capture](./recipe-capture.md#recipe-capture--ai-extraction)) has a far smaller blast radius than one
  that could trigger an action.
- This same pattern (delimiter + explicit instruction + strict output validation) applies to
  any future LLM call this app adds that includes content from outside the household's direct
  input — it is not a one-off fix scoped to Chunk 3.1.

**Why:** the app's core workflow feeds arbitrary external content (webpages, photos) straight
into an LLM prompt with no human review step before that call happens — a textbook prompt
injection surface. Erring on the side of caution here costs little (a delimiter, a stricter
parse) and closes off a class of failure that would otherwise be easy to miss until it's
exploited.

### 0b. API Usage Observability (no hard cap)

> **⚠️ Provider change (Phase 3.9 M5) — [AI Provider Migration](./recipe-capture.md#ai-provider-migration--anthropic-claude--google-gemini-phase-39).**
> Gemini's free tier has no per-call dollar cost, so **all** USD-spend observability is
> removed at M5: `calculate_cost_usd_cents`, `cost_usd_cents`, the diagnostics "spend
> tracker" + its reset button, and the `api_usage` / `api_usage_resets` tables. Replacement:
> the [`ai_call_log`](./data-model.md#ai_call_log) table + a **daily quota usage indicator** (observed
> request count per model) + a **recent capture-attempt log**. §0a prompt-injection hardening
> and §0c enable-switch / fake-mode / ask-first **carry over verbatim**. The prose below
> describes the pre-M5 Claude code, still live until then.

**Set 2026-09-05, revised 2026-09-06.** This section originally documented a hard AU$0.50
lifetime spend cap enforced in code (`enforce_spend_cap()`, `MAX_API_SPEND_AUD_CENTS`,
`SpendCapExceededError`). **That cap has been removed** — it was based on a mistaken
assumption that Anthropic API billing is an open-ended postpaid invoice that could run away
unnoticed. It isn't: calls are billed against credit purchased upfront, so the account's own
prepaid balance is already the real ceiling, and an additional in-app dollar cap wasn't
protecting against anything that couldn't otherwise happen. There is no cap-related
`Security §0b` mechanism to follow any more, and none should be re-added without the
maintainer explicitly asking for it again.

What stays, because it's genuinely useful independent of any cap:

- `app/services/api_usage.py` still calculates the USD cost of every call
  (`calculate_cost_usd_cents()`) and logs it to the `api_usage` table
  (`log_api_usage()`) — `claude_client.py` > `extract_ingredients()` still calls
  `log_api_usage()` immediately after every real call, including when the response turns out
  to be unparseable, so the log is never missing a call that Anthropic actually billed.
- `GET /api/v1/diagnostics/status` still reports running token totals and estimated USD spend
  on the `claude_api` block, plus a reset-with-confirmation action
  (`POST /api/v1/diagnostics/reset-spend`) so the maintainer can zero the *displayed* running
  total when they want a fresh view (e.g. starting real Chunk 3.6+ usage) — this only inserts a
  reset marker (`api_usage_resets` table); it never deletes or edits `api_usage` rows
  themselves, so the underlying log stays a genuine append-only record of every call ever made
  (see [Data Model](./data-model.md#data-model) > `api_usage`).
- This is pure observability, not enforcement — nothing in the app refuses a call because of
  cost. **The actual guardrails against unwanted spend are the enable switch and fake mode in
  §0c below** — never write a new dollar-cap mechanism in place of this section without being
  asked to.

**Why keep the logging at all, then?** Because "no hard cap" isn't "don't bother tracking
cost" — the maintainer still wants to see what recipe capture actually costs in practice, and
that number is cheap to keep accurate now that it's already wired through every real call.

### 0c. API Enable Switch & Offline Development (highest priority)

> **⚠️ Names change at Phase 3.9 M1, semantics unchanged
> ([AI Provider Migration](./recipe-capture.md#ai-provider-migration--anthropic-claude--google-gemini-phase-39)):**
> `CLAUDE_API_ENABLED` → `AI_EXTRACTION_ENABLED`, `CLAUDE_API_FAKE_MODE` →
> `AI_EXTRACTION_FAKE_MODE`, and the check moves from `claude_client.extract_ingredients()`
> to `ai_extraction.py`'s per-task call functions. Everything below applies verbatim to
> Gemini — off by default, no agent flips it, ask before any real call, fake mode bypasses
> everything. Phase 3.9 M1–M6 build entirely in fake mode; **M7** is the single live call.

**Set 2026-09-05, still in force after the 2026-09-06 spend-cap revision above.** Two
mechanisms push the real API's involvement in building this app as close to the very end as
possible, and give the maintainer explicit, deliberate control over when it's used at all —
this is the part of the original rule set that actually did the job the spend cap was
mistakenly added alongside:

**The enable switch.** `CLAUDE_API_ENABLED` in `.env`, defaulting to `false`. Checked in
`claude_client.py` > `extract_ingredients()` before anything else — a configured key alone is
not enough; a real call also needs this explicitly set to `true`. Raising it is the
maintainer's action alone, taken in `.env`: **no agent session may set this to `true` on its
own initiative, ever, including when a task description asks for a real API call to be made.**
Separately, and just as binding: an agent session must ask the maintainer in conversation
before running anything that would make a real call, even once this switch is on — the switch
protects the app; asking protects against an agent deciding "close enough to permission" on
the maintainer's behalf.

**Fake mode.** `CLAUDE_API_FAKE_MODE` in `.env`, defaulting to `false`. When `true`,
`extract_ingredients()` returns a canned fixture (one of a small set of generic sample
recipes, picked deterministically from a hash of the input — same input always gives the same
fixture, different inputs land on different ones) instead of calling the real API at all. Zero
network, zero cost, no key required, bypasses the enable switch entirely because nothing
billable happens. Must never be `true` outside local development.

**Even with no hard cap, minimising real calls during development still matters** — every real
call has a real (if now unbounded-by-code) cost, and there's no reason to spend anything at all
on a call whose only purpose is checking that a button renders correctly. Fake mode and the
enable switch remain the mechanism for that, same as before 2026-09-06 — nothing about their
behaviour changed, only the (now-removed) cap that used to sit alongside them.

**What this buys, concretely — restructuring Phase 3 so the real key is needed exactly once:**
almost none of Phase 3's remaining work actually depends on a real Claude response:
- Chunks 3.2/3.3 (capture endpoints): the fetch/parse/upload logic has nothing to do with
  Claude; only the final `extract_ingredients()` call does, and fake mode covers that for
  manual click-through testing the same way a mocked SDK client covers it in automated tests.
- Chunk 3.4 (review UI): operates entirely on whatever extraction result it's handed — a real
  one or a fixture look identical to this layer. Fully buildable and clickable-through with
  fake mode on.
- Chunk 3.5 (diagnostics wiring): the enable/fake-mode/spend-observability fields are
  exercised by writing directly to `api_usage` in tests, not by real calls.
- **One live check, at the very end of the phase, not spread across it.** After 3.2-3.5 are
  built and manually verified with fake mode, a single explicit "does this actually work
  against the real API" pass is what Chunk 3.1's own verification step becomes — see the Phase
  3 chunk list, where this is now its own final chunk rather than a Chunk 3.1 blocker. It
  needs, in order: a real key added to `.env` (maintainer's action), `CLAUDE_API_ENABLED=true`
  (maintainer's action), and the maintainer's go-ahead in conversation for that specific call
  (agent's obligation to ask, per above). Cost is a few USD-cents — no cap to stay inside of
  any more, but still no reason to make more than the one call this chunk needs.

**Why:** the maintainer asked directly — "how much of the development can be restructured to
be developed without the API key" — and the honest answer turned out to be "nearly all of it."
Treating that as the default going forward (for this integration and any future one) means the
real API is something the app is deliberately, explicitly switched on to use, not something
that's live by accident because it was never obviously off.

### 1. Network exposure
- The server binds to `0.0.0.0` so it's reachable from phones on the LAN. Required for the
  intended use case, but it means anything else on the WiFi can also reach it.
- **Do not port-forward port 8080 on the router.** There is no reason for this app to be
  reachable from the internet, ever.
- **`[Phase 1 fix]`** Scope the Windows Firewall inbound rule for port 8080 to the home LAN
  subnet (e.g. `192.168.1.0/24`) and the Private profile, rather than any/all. Applied at NUC
  setup — see `SETUP.md` step 6 for the exact `netsh` commands.
- If the router supports a separate IoT/guest VLAN, keep smart-home devices on that VLAN and the
  NUC off it, so those devices can't reach port 8080 at all.

### 2. AnyList credentials (Phase 5, plan ahead now)
- AnyList's API is unofficial and reverse-engineered — a straight username/password login, not
  OAuth/token-based. That password should be treated as sensitive as an email password: a leak
  means someone can read and write the shared household list.
- **Never commit credentials to source control.** `.env` is in `.gitignore` as of Phase 1 —
  done, ahead of Phase 5 introducing the real credential.
- **Storage — resolved 2026-09-07 at Phase 5 kickoff: hybrid, keyring-first.** `app/config.py`
  reads Windows Credential Manager via the `keyring` package (service name `shoppingapp`, keys
  `anylist_email` / `anylist_password`); if a value isn't there it falls back to the
  `ANYLIST_EMAIL` / `ANYLIST_PASSWORD` `.env` vars and logs a one-time WARNING that a plaintext
  fallback is in use. `keyring` is a pinned dependency. The NUC can use either — `keyring set`
  once, or plain `.env` — documented in `SETUP.md` / `DEPLOY.md`. Built in
  [Phase 5 Chunk 5.1](./build-status/phase-5-checklist-anylist.md#phase-5--checklist--anylist-integration).
- **`ANYLIST_ENABLED` gate + `ANYLIST_FAKE_MODE`** (Phase 5 kickoff, mirrors §0c for the AI):
  every real AnyList call is refused unless `ANYLIST_ENABLED=true` (default `false`, no agent
  flips it); `ANYLIST_FAKE_MODE=true` swaps an in-memory fake list in so the flow builds and
  runs offline. Manual verification runs only against `ANYLIST_TARGET_LIST_NAME` (dev default
  `TestList`); **the real household list is never touched without a fresh per-occasion
  go-ahead.**
- The Node.js microservice fallback was **not** taken (Phase 1.5 spike → Python-native). If it
  ever were, it must bind to `127.0.0.1` only — never `0.0.0.0`.

### 3. Windows 10 host
- Win10's end-of-support concerns are mainly about internet-facing exposure. Since this stays
  LAN-only, the realistic risk is a compromised device already on the WiFi, not an external
  attacker — so firewall scoping (§1) is the main mitigation, not OS patching urgency.
- Keep Windows Update running normally; don't disable Defender or the firewall for convenience
  during development (easy to forget to re-enable).
- **`[Phase 1 fix]`** Run the app as a standard user, not admin — limits the damage if a
  dependency ever has a vulnerability. Neither binding port 8080 (only sub-1024 ports need
  elevation) nor writing to the project's own folders needs admin rights. Applied at NUC setup
  — see `SETUP.md` step 8 (Task Scheduler task explicitly leaves "Run with highest privileges"
  unticked).

### 4. App-level
- **`[Phase 1 fix]`** CORS is scoped, not wide open. The initial build used
  `allow_origins=["*"]`, which — combined with there being no login at all — meant any
  origin's JavaScript (an ad, a compromised site, anything open in a browser tab on the same
  WiFi) could call the API cross-origin and read or write responses. `ALLOWED_ORIGINS` in
  `.env` now controls this (`app/config.py`, consumed in `app/main.py`'s `CORSMiddleware`),
  defaulting to `localhost`/`127.0.0.1` for dev. **Add the NUC's static IP to it once step 5
  of `SETUP.md` assigns one** — see that step for the exact line to add.
- No login system is fine for the household use case, but since any device on the WiFi can reach
  the API, a single shared basic-auth password on the API routes would be a cheap extra barrier
  against IoT devices or guests poking at it. **Optional, not a `[Phase 1 fix]`** — flagged as a
  recommendation, not built (see [Deferred Decisions](./deferred-decisions.md#deferred-decisions)). CORS scoping above
  is a partial, free complement to this, not a replacement for it.
- Recipe URL scraping (httpx + BeautifulSoup) fetches external, untrusted HTML. Not a credential
  risk, but don't ever `eval()` or execute anything derived from scraped content — parse it as
  data only, which is already the plan.
- Light access logging on `/api/v1/*` (especially the future AnyList routes) is worth having —
  not for compliance, just so an unexpected access pattern from an unfamiliar device is visible
  if it ever happens.

### 5. Deployment/Task Scheduler
- **`[Phase 1 fix]`** Any Task Scheduler task auto-starting the server (or running the weekly
  backup) leaves "Run with highest privileges" unticked unless there's a specific reason it's
  needed. Applied at NUC setup — see `SETUP.md` steps 8 and 9.
- Keep the venv and any secrets outside of any folder that Plex or other services on the NUC
  might expose (e.g. a Plex media/share folder) — accidental exposure through an unrelated
  service is an easy thing to miss on a multi-purpose box.

---

