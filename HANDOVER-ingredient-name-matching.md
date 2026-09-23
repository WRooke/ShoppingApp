# Handover — ingredient alias vs. AI-extraction canonicalization

**Status: investigation complete, design proposed, NOT implemented.** Written 2026-09-23 for a
future session (or the maintainer) to pick up independently. Deliberately kept outside the
`docs/` Manifest tree (see `CLAUDE.md`) — this is undecided proposal material, not a settled
spec `docs/` cross-references would want yet. If a decision is made to proceed, fold the
relevant parts into `docs/ingredient-handling.md` and `docs/deferred-decisions.md` as usual, and
delete this file.

## The original question

Does the ingredient-alias screen (Settings → "Ingredient groups", `ingredient_aliases` table)
duplicate work already done by AI recipe-extraction's canonicalization step (a rule baked into
the Gemini system prompt)? If so, propose a consolidated design rather than maintaining two
parallel systems.

## Investigation finding: no, they're genuinely separate mechanisms today

- **Extraction-time canonicalization** is a fixed, non-editable rule baked into the Gemini
  system prompt (`app/services/ai_extraction/prompts.py`, `EXTRACTION_SYSTEM_PROMPT`, lines
  71–78): plain salt variants → "salt", "minced beef" → "beef mince", "green onion"/"scallion" →
  "spring onion". It fires exactly once, only on AI-extracted text (a URL scrape or a photo),
  and the capture-review screen (`static/js/capture-review.js`) shows its result directly —
  `ingredient_aliases` never touches this code path at all.
- **`ingredient_aliases` resolution** (`app/services/ingredient_aliases.py::alias_map()`) fires
  only inside `app/services/session_consolidation.py`'s `_scaled_lines()`, at shopping-list
  consolidation time — on every ingredient regardless of source (AI-captured or hand-typed) —
  and is entirely household-editable via Settings.
- **No seeded alias pair overlaps the prompt's hardcoded pairs.** `app/seed_data.py`'s
  `INGREDIENT_ALIAS_SEEDS` (canola oil / oil spray → vegetable oil; lemon/lime juice + zest →
  lemon/lime) shares zero ingredients with the prompt's salt/beef-mince/spring-onion rules.
  Confirmed via grep: zero references to `ingredient_aliases`/`alias_map` anywhere under
  `app/services/ai_extraction/`.
- **The already-documented deferred decision is still true in the code**: `docs/ingredient-handling.md`
  already notes "feeding the alias table into the extraction prompt itself... is a small
  possible follow-on, not built now" — confirmed nothing does this today.

## Why they're not overlapping in effect, even though conceptually similar

Both encode "these ingredient names mean the same shopping item," but at different trust levels
and different times:
- The prompt's rule is a generic, universal English-language fact an LLM can be trusted to know
  (kosher salt is salt, everywhere, always) — no household would ever want it to behave
  differently.
- `ingredient_aliases` is deliberately household-specific and user-owned (canola vs. vegetable
  oil is a judgement call, not a fact — see `docs/ingredient-handling.md`'s own reasoning for
  why alias groups are never AI-suggested).

Merging them naively would be wrong in either direction: making household-specific groupings
fire inside a fixed AI prompt bakes a private household preference into every future extraction
as if it were a fact; making the prompt's universal salt/beef-mince/spring-onion rule
Settings-editable adds admin for something no household has ever wanted to override.

## Proposed design 1 — a single source of truth for name-equivalence (not implemented)

The actual latent duplication isn't the *seeded pairs* (they're disjoint) — it's that there are
**two different places an ingredient-name equivalence can be recorded**, with no single table a
maintainer can audit.

1. Add a `source` column to `ingredient_aliases` (`'system'` | `'user'`, default `'user'`).
   Migrate the prompt's 3 current hardcoded pairs (salt-group, "minced beef", "green
   onion"/"scallion") into seeded `ingredient_aliases` rows with `source='system'`.
2. Change the extraction prompt to no longer hardcode those pairs as literal text; instead, read
   the `system`-sourced alias rows at call time and format them into a short, bounded list
   appended to the prompt as canonicalization hints. This is household-owned config data being
   injected into a prompt the app itself controls — not the §0a untrusted-webpage-content case,
   so no delimiter/wrapping is needed, but the list should still be capped defensively since it's
   now dynamic rather than a fixed string literal.
3. This closes the existing deferred decision for free: the capture-review screen would show the
   canonical name immediately for *any* alias (system or user) that matches on extraction,
   because the alias data becomes visible to the prompt, not just to post-hoc consolidation.
4. `source='system'` rows stay Settings-editable/deletable like any other alias row — a household
   that wants "kosher salt" kept distinct could delete that one system row with no code change, a
   flexibility the current hardcoded-in-prompt approach doesn't offer at all today.
5. `source='user'` rows (everything the household adds) are never fed into the prompt — this
   preserves the trust-model distinction above; only the small, originally-hardcoded universal
   set becomes prompt-visible, not arbitrary household groupings.

## A second, distinct gap found during this investigation — plural & punctuation variants

Raised alongside the original question, with examples (non-prescriptive): "spring onion" vs.
"spring onions", "egg" vs. "eggs", "extra virgin olive oil" vs. "extra-virgin olive oil". **This
is a real, confirmed bug in the base consolidation pipeline, independent of both mechanisms
above:**

- `app/services/consolidation.py::_normalise_name()` (lines 306–307) — the function that decides
  whether two ingredient lines merge into one shopping-list line **at all** — only lowercases and
  collapses whitespace:
  ```python
  def _normalise_name(name: str) -> str:
      return " ".join(name.strip().lower().split())
  ```
  It does **not** strip plurals or fold hyphens/spaces. So two recipes, one saying "spring onion"
  and the other "spring onions" (or "extra virgin olive oil" vs. "extra-virgin olive oil"), land
  in **two separate consolidated shopping-list lines** today — no alias, no AI involvement, and
  no existing mechanism catches it.
- The codebase already has the right precedent for fixing this, applied to a different axis:
  `app/services/unit_synonyms.py::strip_plural()` (a generic, tableless heuristic for *units* —
  "Layer A" of Ingredient Unit Handling, see `docs/ingredient-handling.md`) and
  `app/services/checklist.py::_singularise()` (the same idea, already applied to *ingredient
  names*, but only ever used for AnyList fuzzy-matching at checklist-load time — never for base
  consolidation grouping).

### Proposed fix

Promote `checklist._singularise()` into a small shared module (e.g.
`app/services/text_normalize.py`) that both `checklist.py` (unchanged behaviour) and
`consolidation.py` (new use) import, and extend `consolidation._normalise_name()` to run:
1. The same conservative pluralisation-strip `_singularise()` already does (tomatoes/potatoes/
   boxes/dishes-style rules; leaves ambiguous words alone — a false negative just means two
   lines don't merge, same safe-failure direction as today).
2. A hyphen/space fold (treat `-` as a space before collapsing whitespace), so "extra-virgin" and
   "extra virgin" become identical.

This mirrors `unit_synonyms`'s "Layer A" design exactly, but for ingredient names instead of
units: zero admin, a small universal heuristic, no per-ingredient Settings entry needed. The same
normalisation should also apply wherever `ingredient_aliases.alias_map()` and the proposed
system-alias prompt-hints above do their own name matching, so an alias also silently catches a
plural/hyphen variant of its `alias_name` without needing every form seeded separately.

### Why this needs its own go/no-go, separate from design 1

This is a **base-pipeline behaviour change** — it changes what merges on the shopping list for
every existing recipe, not just a Settings/UI change. Before building:
- Confirm `_singularise()`'s existing conservative word list (and the new hyphen-fold) is an
  acceptable scope — check it against real recipe data for any name pair that should NOT merge
  (e.g. two genuinely different ingredients that happen to differ only by a hyphen or a trailing
  "s" — none identified during this investigation, but worth a deliberate look before shipping).
- Check no existing test fixture relies on two differently-pluralised or differently-hyphenated
  names staying separate (a quick grep across `tests/` for ingredient names ending in "s" used
  twice in different forms would catch this before it becomes a surprise regression).

## Recommendation

Both proposals are worth doing, but neither is scheduled. If picked up:
1. Fix the plural/punctuation consolidation gap first (design 2 above) — it's a narrower, more
   clearly-correct change (a pure `services/` function change with unit-test coverage, no schema
   migration) that fixes a real, already-reproducible bug.
2. Then consider the `source` column / prompt-hint consolidation (design 1) as a separate,
   larger piece of work — it touches a migration, the extraction prompt, and the seed data.

Record whichever is picked up as a normal chunk under the current phase in
`docs/build-status/`, and fold the decided design into `docs/ingredient-handling.md` +
`docs/deferred-decisions.md`, replacing this handover file.
