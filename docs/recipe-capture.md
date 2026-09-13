# Recipe Capture — AI Extraction

## Recipe Capture — AI Extraction

**Provider: Google Gemini** (`gemini-2.5-flash` → `gemini-2.5-flash-lite` → `capture_queue`),
`google-genai` SDK, structured-output mode. See
[AI Provider Migration (Phase 3.9)](#ai-provider-migration--anthropic-claude--google-gemini-phase-39)
for the full spec — the provider swap, the Flash→Flash-Lite→queue chain, the "Pending AI
processing" badge, and the substitution merge. *(Code is on the `anthropic` SDK / Haiku 4.5
until Phase 3.9 chunk M1.)*

**Three separate Gemini calls per capture**, not one combined call (Phase 3.9 M2):
1. **Recipe extraction** — ingredients + `cuisine` / `protein` (the JSON below, minus
   `suggested_section`).
2. **Ingredient substitution flagging** — per recipe, per-ingredient confirm/decline (the
   merged spec — see the migration section).
3. **Store section suggestion** — per ingredient (`suggested_section`), moved out of the
   extraction prompt into its own call.

Each call: its own system prompt, its own Gemini `response_schema` (structured-output), its
own fake-mode fixture, its own place in the Flash→Flash-Lite→queue chain. A failed/queued
enrichment call (2 or 3) does not block extraction — the recipe is still usable, and
`recipes.ai_tasks_pending` + the badge track what's outstanding.

The rest of this section — the extraction prompt, the §0a hardening, the review flow — is
otherwise preserved across the provider swap. Where it still says "Claude", read "the AI
extraction service".

### URL capture flow
1. User pastes URL
2. Backend fetches page with `httpx` (follow redirects, 10s timeout, desktop user-agent +
   full browser Accept/Accept-Language/Accept-Encoding headers — see the tasty.co note below)
3. Parse HTML with BeautifulSoup4, extract text content (strip nav, footer, ads — prefer
   `<article>`, `<main>`, `[class*="recipe"]`, `[class*="ingredient"]` elements)
4. Send extracted text to Claude with the extraction prompt (see below)
5. Return structured ingredient list to frontend for user review

**Triaged 2026-09-07 — a real-world 406 from tasty.co.** `httpx.get(url, headers={"User-Agent":
...})` alone got a flat `406` with no body from `https://tasty.co/recipe/...`, regardless of
which realistic Chrome UA string was used. Root cause, confirmed by comparison against `curl`
(which succeeded with no special headers at all): the site's edge WAF treats a Chrome UA
whose `Accept-Encoding` doesn't include `br` (brotli) as non-browser traffic and blocks it
outright — httpx only advertises `gzip, deflate` unless the optional `brotli` package happens
to be installed, which it wasn't. Fix, in `services/capture_url.py`: an explicit
`ACCEPT_HEADERS` dict (`Accept` / `Accept-Language` / `Accept-Encoding: gzip, deflate, br`)
merged with the UA on every request, made explicit rather than relying on httpx's silent
auto-detection of the `brotli` package (easy to lose track of, and it was in fact missing).
`brotli==1.2.0` is now pinned in `requirements.txt` — without it, a br-encoded response
would still 200 but decode to mojibake instead of real HTML, which is arguably worse than the
406 (a silent bad capture instead of a loud one). A `403`/`406`/`429` that still gets through
this (a different site's bot-protection) now gets a plain-language "the site blocked this
request" message via `RecipeFetchError` instead of a bare "HTTP 406".

### Photo capture flow
1. User uploads image (JPEG or PNG, from camera or gallery)
2. Store image in `images/` directory with UUID filename
3. Send image to Claude as base64 with the extraction prompt
4. Return structured ingredient list for user review
5. Keep image stored (linked to recipe record)

### Claude extraction prompt (system)

**Built at Phase 3 kickoff (2026-09-05) with the `suggested_section`/`cuisine`/`protein`
extension already folded in** — schema for these fields has existed since Phase 1, and the
extension was only waiting on the substitution-flagging gap, resolved the same day (see
[Decision Dialogues > "Substitution flagging" review
step](#substitution-flagging-review-step-before-phase-3-ai-extraction)). There is no
ingredients-only version of this prompt in the running app; building that and revising it
again a few chunks later would be pure churn. The response shape is a single JSON object
(not a bare array) so the recipe-level fields have somewhere to live:

```
You are a recipe extraction assistant. Given recipe text or an image of a recipe, extract
the recipe's title and servings, the ingredients list, plus a couple of recipe-level fields.
Return a single JSON object with this exact structure:
{
  "title": "the dish name as written" or null,
  "servings": 4 or null,
  "cuisine": "italian" or null,
  "protein": "chicken" or null,
  "ingredients": [
    {
      "name": "ingredient name, lowercase, no preparation notes",
      "quantity": 2.0,
      "unit": "g" or null for unitless items,
      "preparation": "finely diced" or null,
      "original_text": "the raw text as it appeared",
      "suggested_section": "produce" or null
    }
  ]
}

Rules:
- title is the dish/recipe name as written; null if it isn't clear
- servings is the integer number of servings/portions the recipe yields; if given as a range
  (e.g. "serves 4-6"), use the lower bound; null if not stated
- quantity must be a number (convert fractions: 1/2 → 0.5)
- unit must be one of: g, kg, ml, L, tsp, tbsp, cup, or null
- Convert any non-standard units to the closest standard unit
- If a quantity is a range (e.g. "1-2 cloves"), use the lower bound
- Separate compound ingredients (e.g. "for the sauce:") into individual items
- Do not include method / cooking-step instructions
- DO include accompaniments listed "to serve" when they are concrete things to buy (e.g.
  rice, naan, yoghurt, lime wedges) — set their preparation to "to serve". Exclude vague
  suggestions with no specific ingredient (e.g. "serve with a crisp green salad")
- Normalise ingredient names to a canonical form so the same item reads identically across
  recipes: all plain salts (table salt, cooking salt, kosher salt, sea salt) → "salt" (but
  keep a distinct name when a recipe calls for flaky/finishing salt as an ingredient in its
  own right, e.g. "flaky sea salt to finish"); "minced beef" → "beef mince"; "green onion" /
  "scallion" → "spring onion". Do NOT merge names that describe a different product form —
  keep "coriander" separate from "ground coriander" or "coriander seeds", "ginger" from
  "ground ginger", "garlic" from "garlic powder", fresh chilli from "dried chilli" / "chilli
  flakes", and so on. When unsure, leave the name as written.
- suggested_section must be one of: produce, dairy, meat & seafood, bakery, frozen, pantry,
  household, deli, drinks, other — or null if you are not reasonably confident
- cuisine and protein are freetext (lowercase, one or two words, e.g. "italian", "beef mince")
  — use null if not reasonably inferrable from the recipe
- Return ONLY valid JSON. No markdown, no explanation, no preamble.
```

> **Note (2026-09-07):** `suggested_section` is shown above as documentation of the original
> combined-call shape; Phase 3.9 M2 actually moved section suggestion into its own call
> (`suggest_sections()`) — the live `EXTRACTION_SYSTEM_PROMPT` in `app/services/ai_extraction.py`
> no longer asks for it. `title`/`servings`/the "to serve" rule/the canonicalisation rule were
> added the same session, folding in the 5 hand-testing issues staged in
> `Capture-Fixes-Staged.md` (title/servings never extracted, "cooking salt" vs "kosher salt"
> consolidation misses, verbose substitution notes, dropped "to serve" ingredients — issue 3's
> full fix, a Settings-managed alias table, stays a
> [Deferred Decision](./deferred-decisions.md#deferred-decisions); the note-length backstop for issue 4 lives in
> [Ingredient Substitution Flagging](./ingredient-handling.md#ingredient-substitution-flagging--the-merged-spec)).
> `app/services/ai_extraction.py` is the source of truth for the exact wording in force at any
> given time — this block is kept in sync opportunistically, not on every prompt tweak.

The `suggested_section` enum in the prompt text is kept in sync with
`SECTION_VOCABULARY` in `app/seed_data.py` by hand (see
[Section Vocabulary Starter List](./data-model.md#section-vocabulary-starter-list) — it's still provisional,
so if that list changes, update this prompt text too). The review UI (Chunk 3.4) shows every
field as editable — `suggested_section` per ingredient, `cuisine`/`protein` per recipe — and on
confirm writes `product_sections` rows with `source='ai_suggested'` for any newly-tagged
ingredient. No substitution/alternatives suggestion mechanism is part of this review step
(resolved 2026-09-05 — see the Decision Dialogue linked above) — still correct as of 2026-09-06:
ingredient substitution is real and in scope, but lives in Phase 4's planning flow, not here.
See [Ingredient Substitution](./ingredient-handling.md#ingredient-substitution).

### After extraction
- Display extracted ingredients in an editable review UI (inline edit of name, qty, unit)
- Recipe name and base servings are AI-prefilled from `title`/`servings` when the model
  returned them (2026-09-07 — Capture-Fixes-Staged.md issues 1 & 2); a URL capture also
  falls back to the page's own `<title>`/`og:title`/first `<h1>` (no extra AI call) when the
  AI didn't return a title — see `services/capture_url.py > _extract_title()`. Both fields
  stay fully editable, same as everything else on this screen.
- User confirms or edits, then saves
- On save: normalise ingredient names to lowercase, store in `recipe_ingredients`
- Log: recipe id, call type, model, token counts, outcome to `ai_call_log` (see
  [`ai_call_log`](./data-model.md#ai_call_log) — replaced `api_usage` at Phase 3.9 M5; no cost column,
  Gemini's free tier has none)

### Source provenance on the review screen (Phase 3 Chunk 3.7, 2026-09-06)
The review screen also carries two optional freetext inputs — **cookbook name** and **page** —
that the user fills in by hand while reviewing (same treatment as the existing `cuisine` /
`protein` inputs). They write `recipes.source_book` / `recipes.source_page` on confirm. Most
relevant for a photographed cookbook page; a URL capture already carries `source_url` through
without any new input.

**The extraction prompt is deliberately NOT extended to read the book title/page out of a
photo.** Reasons: OCR of a running-header book title / page number is unreliable; every new
prompt field costs a fresh round of [§0a](./security.md#0a-prompt-injection-hardening-highest-priority)
output-validation work on a prompt that was only just built and stabilised in Chunk 3.1; and
the manual inputs fully cover the need. Best-effort AI pre-fill of these two fields is parked
as a [Deferred Decision](./deferred-decisions.md#deferred-decisions) — revisit only if typing them every capture
turns out to be a real annoyance.

---

## AI Provider Migration — Anthropic Claude → Google Gemini (Phase 3.9)

**Status: IN PROGRESS — added 2026-09-06, chunked as Phase 3.9 (chunks M0–M8 below; M0–M8
all built and verified, only the M-review outstanding), decisions resolved 2026-09-06 (M8's
2026-09-07).** This is the authoritative spec for the AI extraction
provider and for ingredient substitution going forward. It **supersedes** the earlier
"Claude API" / "Anthropic API" / "Claude Haiku" references in the AI-extraction context and
the Phase 4 [Ingredient Substitution](./ingredient-handling.md#ingredient-substitution) design. As each chunk lands,
the relevant section ([Tech Stack](./project-overview.md#tech-stack), [Recipe Capture](#recipe-capture--ai-extraction),
[Ingredient Substitution](./ingredient-handling.md#ingredient-substitution), [Diagnostics & Logging](./diagnostics-and-logging.md#diagnostics--logging),
[Security §0a/§0b/§0c](./security.md#security), [Data Model](./data-model.md#data-model), [Environment
Variables](#environment-variables-env)) is rewritten in place and its `⚠️` banner removed.
Non-AI uses of the name "Claude" (Claude Code as this project's dev tool; git commit
`Co-Authored-By` lines) are unaffected.

**Why:** the Anthropic account used for recipe extraction is permanently unable to add
billing credit (see [Phase 3 Chunk 3.6](./build-status/phase-3-recipe-capture.md#phase-3--recipe-capture-ai), BLOCKED). Gemini's
free tier replaces it.

### Provider & model selection

- **Primary:** `gemini-flash-latest` — the current Gemini Flash, closest quality match to
  Haiku, especially for messy handwritten photo OCR.
- **Fallback (primary's daily quota exhausted):** `gemini-flash-lite-latest` — for volume,
  not the default; photo-capture accuracy is the priority.
- **Queue (both exhausted):** the capture is queued and retried later (see Queueing).

> **Model IDs — floating `*-latest` aliases, not pinned (resolved 2026-09-07 at M7).** The
> spec originally pinned `gemini-2.5-flash` / `gemini-2.5-flash-lite`. Between the spec being
> written (2026-09-06) and the M7 live call being run (2026-09-07), Google retired
> `gemini-2.5-flash` for newly-created keys — the live call came back `404 NOT_FOUND`,
> *"This model … is no longer available to new users."* Google's model line moves fast enough
> (3.5, 3.6, 3.7, 3.8 flashes all released within 2026) that pinning a specific version means
> a periodic forced bump. The maintainer chose the floating aliases so this can't recur.
> Accepted trade-off: a model swap underneath the app could shift extraction behaviour with
> no code change — the capture review step (the user confirms every ingredient before the
> recipe is saved) is the backstop, and `ai_call_log` records which concrete model answered
> each call. `ai_extraction.MODEL_ID` / `FALLBACK_MODEL_ID` are the single source of truth in
> code; older `gemini-2.5-flash` mentions elsewhere in this section are historical.

**Do not hardcode Gemini rate limits.** Free-tier RPM/TPM/RPD have changed repeatedly in
2026 and third-party numbers conflict. Instead: read quota state from `429`
`RESOURCE_EXHAUSTED` at runtime; link the Google AI Studio dashboard from diagnostics rather
than printing a hardcoded "X of Y"; track observed daily request counts and reset the quota
bar on *detected* recovery (poll hourly with a light test call or by re-attempting the
oldest queued item), not an assumed fixed reset time.

### Call structure — separate calls per task

Each capture issues **separate Gemini calls**, not one combined call:
1. **Recipe extraction** — ingredients, steps, metadata (from URL text or photo).
2. **Ingredient substitution flagging** — per-recipe, confirmation required (see below).
3. **Store section suggestion** — per ingredient, confirmation required (unchanged in intent
   from the prior addendum; today it rides inside the single extraction call).

Uses more daily quota than a combined call, but keeps each task's prompt, schema and
failure handling independent and debuggable — consistent with the diagnostics-first
philosophy. **Do not pre-optimise by combining** — revisit only if quota pressure becomes a
real problem. Every call uses Gemini structured-output / JSON-schema mode to preserve the
schema parity from prior addenda.

### Photo capture

- One photo per capture for now.
- Keep the image input a **list** structure (one element populated today) so multi-photo
  (card front/back, multi-page printout) is not a breaking schema change later.

### Fallback & retry

1. Call `gemini-2.5-flash`.
2. On `429` quota-exhausted → retry the same call on `gemini-2.5-flash-lite`.
3. Flash-Lite also `429` → queue the capture.
4. **Non-quota errors** (malformed response, network failure, …) do **not** fall through to
   Flash-Lite or the queue — surface as a normal capture failure per existing error
   conventions.

### Queueing

- New SQLite table (e.g. `capture_queue`): original input (URL/text/photo ref), task type,
  queued-at timestamp, attempt count.
- Retry ~hourly (not on an assumed fixed reset).
- On success, the item processes through the normal capture pipeline and is removed.

### Surfacing queued / pending state (both required)

- **Recipe library badge:** "Pending AI processing" until all required AI tasks (extraction,
  substitution flagging, section suggestion) complete.
- **Diagnostics panel:** queued items visible in the live log tail / component status view.

### API key storage

`.env`, plaintext — unchanged from the Anthropic key. `keyring` hardening stays deferred to
Phase 5 with the AnyList credential work.

### Resolved — free-tier data usage (2026-09-11)

On Gemini's free tier, prompt/response content (recipe photos and text) **may be used by
Google to improve their products**. Enabling Cloud Billing on the project stops this, even at
$0 spend under the free quota. **The maintainer has added a Cloud Billing payment method and
is willing to pay for ongoing usage** — unlike the Anthropic account (permanently unable to
add credit, the original reason this app migrated to Gemini at all), Google billing was
viable. This closes the privacy concern; it does not reopen §0c's spend-discipline norms
(enable switch off by default, no agent flips it, ask before every real call) or bring back
the M5-removed cost tracking — those stay exactly as they are unless separately asked for.

### Deferred — local LLM fallback (future phase, NOT now)

Placeholder direction only, if the Gemini dependency ever must be removed entirely
(cost/privacy/availability): Ollama native on the NUC (Windows, no Docker); candidate models
`llama3.2-vision`, `qwen2-VL`, `moondream2`. Known trade-offs to check against real NUC
hardware at that time: weaker messy-handwriting OCR; latency depends heavily on GPU vs
CPU-only. **Do not add Ollama dependencies or code paths now.**

> **Note (added during the 2026-09-12 CLAUDE.md split):** the migration's own historical
> "Resolved decisions (2026-09-06)" record and its superseded "Diagnostics — replacing
> 'Claude API spend tracking'" note now live in
> [Decision Dialogues & Historical Record](./decision-history.md#resolved-decisions-2026-09-06).
> The migration's chunk-by-chunk build/verification status (M0–M8 + M-review) lives in
> [Build Status — Phase 3.9](./build-status/phase-3.9-ai-provider-migration.md).

