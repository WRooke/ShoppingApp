# Capture fixes — staged bundle

Source: `Capture-Notes.txt` (hand-testing notes on the Phase 3.9 Gemini capture flow).
**Status: Implemented 2026-09-07** (all 5 issues) — ahead of the M-review, at the
maintainer's request, rather than waiting. Prompt/schema/frontend changes as specced below,
built as-is with no changes to the plan. CLAUDE.md's extraction-prompt block, "After
extraction", the "Ingredient Substitution Flagging" merged spec (issue 4's note tightening),
and the "Ingredient synonym normalisation (automatic)" Deferred Decisions row (issue 3's
bring-forward recommendation) were all updated in place. Fake fixtures + offline tests
updated (`tests/services/test_ai_extraction.py`, `tests/services/test_capture_url.py`) —
suite stays green, no real Gemini call made. **Still open, per the original plan:**
re-verify title/servings/canonicalisation/note-length/"to serve" against a real Gemini
response, only under a fresh §0c go-ahead — piggyback on the M-review's live check rather
than spending a call solely for this.

Issues 1, 2, 4, 5 are essentially one edit to `app/services/ai_extraction.py` (prompt +
schema + parsing) plus plumbing for two new fields. Issue 3's minimal form rides in the same
prompt edit; its robust fix is a deferred-decision bring-forward.

---

## 1 & 2 — Recipe title and servings are never extracted

**Symptom:** capture doesn't fetch the recipe title or the serving count; the review screen
shows a blank name box and a hardcoded `4`.

**Root cause:** `EXTRACTION_SYSTEM_PROMPT` and the `_GExtraction` schema in
[`app/services/ai_extraction.py`](app/services/ai_extraction.py) have no `title` / `servings`
field. Frontend never populates them — [`static/js/capture-review.js:58-71`](static/js/capture-review.js#L58-L71)
(`nameInput` placeholder only, `servingsInput.value = "4"`).

**Change:**

| File | Change |
|---|---|
| `app/services/ai_extraction.py` | Add `title: str \| None` + `servings: int \| None` to `_GExtraction` and to `ExtractionResult`. Extend `EXTRACTION_SYSTEM_PROMPT` JSON shape with `"title"` and `"servings"`, plus rules: *title = the dish name as written, null if unclear*; *servings = the integer the recipe yields, lower bound of a range, null if not stated*. Parse both in `extract_recipe()` (`data.get("title")`, coerce `servings` to `int`, drop if `< 1`). Add both to the fake fixtures. |
| `app/schemas/capture.py` | Add `title: str \| None` and `servings: int \| None` to `CaptureResult`. |
| `app/routers/recipes.py` | `_capture_result()` passes `result.title` / `result.servings` through. |
| `static/js/capture-review.js` | Pre-fill `nameInput.value = captureResult.title || ""` and `servingsInput.value = captureResult.servings || 4`. Both stay editable. |
| `app/services/capture_url.py` | **Belt-and-braces, no AI / no §0a cost:** parse `<title>` / `<meta property="og:title">` / first `<h1>` from the fetched HTML and pass as a fallback title to `capture_recipe()` (new kwarg, used only when the AI title comes back null). |

**§0a note (CLAUDE.md > Security §0a):** `title` is untrusted free text, but it is displayed
and fully editable on the review screen before anything is saved — same blast radius as the
ingredient `name` field, which is already accepted. `servings` is Pydantic-validated
`int >= 1`. Low added risk; one sentence in CLAUDE.md > Recipe Capture is enough.

**No migration** — `recipes.name` and `recipes.base_servings` already exist.

**CLAUDE.md edits:** the "Claude extraction prompt (system)" block (add the two fields +
rules), and a line in "After extraction" / "Source provenance" noting title/servings are
now AI-prefilled and user-editable.

---

## 3 — "cooking salt" vs "kosher salt" vs "table salt" break consolidation and staple matching

**Symptom:** the same ingredient named differently across recipes doesn't consolidate onto
one line; a staple named non-canonically (`cooking salt`) misses the `salt` staple row and
wrongly lands on the shopping list.

**Root cause:** two gaps.
- (a) `EXTRACTION_SYSTEM_PROMPT` never applies canonical forms, even though CLAUDE.md >
  Ingredient Normalisation already *specifies* some (`"beef mince"` not `"minced beef"`,
  `"spring onion"` not `"green onion"`). They were never put in the prompt.
- (b) Consolidation (`services/consolidation.py`) and staple detection
  (`services/sessions.py` `consolidate_session`) match on the exact normalised name.

**Change — minimal, in scope now (prompt wording only):** add a rule to
`EXTRACTION_SYSTEM_PROMPT` enumerating a **short, conservative** canonical list and telling
the model to normalise to it.

**⚠️ Only collapse names that cannot denote two different store products.** Safe:
- `table salt` / `cooking salt` / `kosher salt` / `sea salt` → `salt` — *but keep a
  distinct name when a recipe explicitly calls for flaky/finishing salt as an ingredient in
  its own right (e.g. "flaky sea salt to finish")*.
- pure word-order / regional synonyms of one physical product: `minced beef` → `beef mince`,
  `green onion` / `scallion` → `spring onion`, `capsicum` ↔ `bell pepper` (pick one).

**Do NOT canonicalise** anything where dried / fresh / ground / form changes which product
you buy — these are genuinely different items and must stay separate:
- `coriander` (fresh herb) vs `ground coriander` / `coriander seeds` — **keep distinct**
  (this was the specific caveat raised).
- likewise `ginger` (fresh) vs `ground ginger`, `garlic` vs `garlic powder`, `chilli` (fresh)
  vs `dried chilli` / `chilli flakes`, `parsley` fresh vs dried, etc.

Prompt wording sketch:
> Normalise ingredient names to a canonical form so the same item reads identically across
> recipes: all plain salts → "salt"; "minced beef" → "beef mince"; "green onion"/"scallion"
> → "spring onion". Do NOT merge names that describe a different product form — keep "fresh
> coriander" separate from "ground coriander", "fresh ginger" from "ground ginger", and so
> on. When unsure, leave the name as written.

**Flag as the real fix (deferred-decision bring-forward):** a small alias map applied
post-extraction in `create_recipe_from_capture` **and** in `consolidate_session`'s
effective-name step would also fix manually-typed recipes and give consistent staple
matching. That is the **"Ingredient synonym normalisation (automatic)"** row in
CLAUDE.md > Deferred Decisions (currently *"Phase 6 or later"*). Recommend pulling it into
Phase 5/6 as a **Settings-managed alias table** (user-editable, seeded with the salt group),
with the same dried/fresh caution baked into the seed. Not building it now.

---

## 4 — AI substitution notes are verbose and unwanted

**Symptom:** notes like *"Regular butter contains milk solids that brown and burn faster
than ghee, so watch the heat."* — the user doesn't want the rationale.

**Root cause:** `SUBSTITUTIONS_SYSTEM_PROMPT`
([`app/services/ai_extraction.py:128-140`](app/services/ai_extraction.py#L128-L140)) —
*"note is a short practical hint or null"* is far too permissive.

**Change:**

| File | Change |
|---|---|
| `app/services/ai_extraction.py` | Tighten the `note` rule in `SUBSTITUTIONS_SYSTEM_PROMPT`: *"note: include ONLY if the swap needs a real change to method or quantity (e.g. 'use 20% less — saltier'). A straight 1:1 swap MUST have note = null. Never explain why the two items are similar. ~10 words max."* |
| `app/services/ai_extraction.py` | Defensive guard in `flag_substitutions()` parsing: if `note` is longer than ~120 chars, set it to `None` and log at INFO — cheap insurance if the model ignores the instruction. |

**CLAUDE.md edit:** the "Ingredient Substitution Flagging — the merged spec" wording
(*"a short note"*) in the AI Provider Migration section — tighten to match.

Fake fixtures (`_FAKE_SUBSTITUTION_FLAGS`) are already terse — no change.

---

## 5 — "To serve" ingredients are dropped (curry with no rice)

**Symptom:** accompaniments listed under "to serve" (rice, naan, yoghurt) don't get
extracted, so the shopping list is missing them.

**Root cause:** `EXTRACTION_SYSTEM_PROMPT` rule *"Do not include method instructions or
serving suggestions"* ([`app/services/ai_extraction.py:111`](app/services/ai_extraction.py#L111))
— the model treats "to serve: rice" as a serving suggestion.

**Change:** split that rule in `EXTRACTION_SYSTEM_PROMPT`:
> - Do not include method / cooking steps.
> - DO include accompaniments listed "to serve" when they are concrete things to buy (rice,
>   naan, yoghurt, lime wedges) — set their `preparation` to "to serve". Exclude vague
>   suggestions with no specific ingredient ("serve with a crisp green salad").

Optional polish (not required): in `capture-review.js` group rows whose `preparation` is
`"to serve"` under a small "To serve" subheading so they're easy to eyeball. Minimal version
just lets them flow in as ordinary ingredients — they scale and consolidate correctly.

**CLAUDE.md edit:** the extraction prompt block + the "Do not include method instructions or
serving suggestions" line.

---

## Rollout

1. Land the four prompt/schema changes (1, 2, 4, 5) as one commit against
   `app/services/ai_extraction.py` + `app/schemas/capture.py` + `app/routers/recipes.py` +
   `static/js/capture-review.js` + `app/services/capture_url.py`.
2. Update the fake fixtures and `tests/services/test_ai_extraction.py` (title/servings
   present, verbose note nulled, "to serve" fixture ingredient) — stays fully offline.
3. Issue 3 minimal (prompt) rides in the same commit. Add the deferred-decision note about
   the Settings alias table to CLAUDE.md > Deferred Decisions.
4. Re-verify with a real Gemini call **only** under a fresh §0c go-ahead (piggyback on the
   M-review's live check if one is being done anyway).
5. Update the `⚠️`-free CLAUDE.md sections listed under each issue.
