"""Shared ingredient-name normalisation (2026-09-27 — see CLAUDE.md > Ingredient Handling and
the ingredient-name-matching plan it was built from).

Before this module existed, the same `" ".join(name.strip().lower().split())` logic was
independently copy-pasted across at least 9 places (`consolidation.py`, `session_consolidation.py`,
`coarse_ingredients.py`, `ingredient_aliases.py`, `substitutions.py`, `settings.py`,
`usuals.py`, `checklist.py`, `unit_synonyms.py`) — harmless while it only ever did lowercase +
whitespace-collapse, but load-bearing now that it also has to agree on plural-stripping and
punctuation-folding: every one of those call sites must produce the *same* key for the *same*
ingredient, or matching against `product_units`/`coarse_ingredients`/`ingredient_aliases`/
`remembered_substitutions`/`usual_items` silently breaks. This module is the one place that
logic lives now; every module above calls into it instead of keeping its own copy.

**Pluralisation is a hybrid of hand-rolled rules and the `inflect` library — not either one
alone.** The original hand-rolled `singularise()` shipped with two real bugs (a blind "-ves"
suffix rule corrupted "cloves"->"clof"/"olives"->"olif"; a blind "-us" guard also caught
"tofus", leaving it unmerged with "tofu"). An empirical, corpus-based evaluation (every distinct
name from `data/mealplanner.db` + `data/mealplanner_prod.db`, plus every edge case already in
this module's test file) explored replacing the hand-rolled rules with `inflect.singular_noun()`
outright, and found:
  * It correctly handles true irregulars a suffix-rule approach can never cover (geese/goose,
    teeth/tooth, mice/mouse, children/child, people/person), and correctly disambiguates the
    "-ves" class using its own internal word list (knives/wolves/scarves/calves -> -f, while
    correctly leaving cloves/olives/gloves alone) — genuinely better than the original 2-word
    `_VES_IRREGULARS` whitelist.
  * TextBlob was evaluated too and rejected outright: same "-us" flaw as inflect (below), PLUS a
    new regression on a real, common ingredient ("olives" -> "olife", wrong), plus a much
    heavier dependency chain (`nltk` + 5 more packages vs. inflect's one, `typeguard`).
  * BUT `inflect.singular_noun()`'s generic fallback (for a word it doesn't specifically
    recognise) is far more aggressive than this app's "false negative is safe, false positive is
    dangerous" philosophy wants: it treats almost ANY word ending in a bare "s" as a candidate
    plural and blindly chops it, including "-ss" words ("glass"->"glas", "class"->"clas") and
    plain short words ("gas"->"ga", "less"->"les") that are obviously not plurals. This is a
    materially worse default than this module's own hand-rolled generic rule, which already
    guards both cases (a `len > 3` floor and an explicit `not endswith("ss")` check).

**The design below plays each approach to its strength**: the hand-rolled rules (proven safe
against the entire real corpus, already correctly guard "-ss" and short words) handle every
"ends in a recognisable regular-plural shape" case; `inflect` is consulted ONLY for the "-ves"
class specifically (empirically proven correct there) and for words that don't end in "s" at
all (the true irregulars, where inflect's aggressive-fallback risk cannot apply, since there's
no trailing "s" for it to blindly strip). A word ending in "ss", or a short/irregular "s"-ending
non-plural (this/plus/always/walrus/campus/virus), is a known, accepted gap — none of these are
remotely plausible ingredient names, same "don't pre-guess, extend only for a real gap" standing
as every other reference list in this app (see `_US_WHITELIST` below for the same precedent
applied to genuine grocery words).

Deliberately does NOT resolve genuine word-choice differences ("stock" vs "broth", "capsicum"
vs "red capsicum", "plain yoghurt" vs "greek yoghurt") — those are household judgment calls,
resolved via `ingredient_aliases`, never guessed at here. See CLAUDE.md > Ingredient Aliases.
"""

from __future__ import annotations

import re

import inflect

_INFLECT = inflect.engine()

# Hyphen/dash family folded to a space (never dropped) before whitespace-collapse — the only
# punctuation this module folds. "extra-virgin" -> "extra virgin", never "extravirgin". No real
# instance of apostrophes/slashes/periods causing a mismatch was found during this module's own
# design (see the ingredient-name-matching plan's pre-flight audit) — same "don't pre-guess, wait
# for a real gap" discipline as every other reference list in this app. Extending this set later
# is a one-line change, not a redesign.
_HYPHEN_FAMILY = re.compile(r"[-‐‑‒–—]")

# Explicit whitelist of words that ALREADY end in "-us" in their singular/mass-noun form and
# must never be treated as a plural (asparagus, couscous, hummus, citrus — confirmed real via
# the ingredient-name-matching plan's pre-flight data audit). Both the hand-rolled generic rule
# AND `inflect`'s fallback would otherwise mishandle these — see the module docstring. Matched
# as the *trailing word* (like the "-ves" handling below), so "dried hummus" is also protected,
# not just the bare word. A small, explicit, universal seed — same precedent as
# `unit_synonyms.py`'s own seed list — extend only if a real ingredient needs it.
_US_WHITELIST = {"asparagus", "couscous", "hummus", "citrus"}


def base_norm(name: str) -> str:
    """Lowercase, strip, fold hyphens/dashes to a space, collapse whitespace. The baseline every
    other function/call site in this module builds on."""
    folded = _HYPHEN_FAMILY.sub(" ", name.strip().lower())
    return " ".join(folded.split())


def _singularise_word(word: str) -> str:
    """The actual rule ladder, applied to a single word (no spaces) — see `singularise`'s
    docstring for the full reasoning behind this specific hand-rolled/`inflect` split."""
    if word in _US_WHITELIST:
        return word
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith("ves"):
        result = _INFLECT.singular_noun(word)
        return result if result else word
    if len(word) > 4 and word.endswith(("ses", "xes", "zes", "ches", "shes", "oes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    if not word.endswith("s"):
        result = _INFLECT.singular_noun(word)
        return result if result else word
    return word


def singularise(s: str) -> str:
    """Conservative de-pluralisation, applied to the *trailing word only* — English plural
    markers only ever attach to the last word of a noun phrase ("chicken thighs" -> singularise
    just "thighs"), and `inflect` itself operates on single words, not phrases. Checked in order
    (see `_singularise_word` and the module docstring for the full reasoning):

      1. `_US_WHITELIST` match -> unchanged.
      2. ends "ies" -> "y" (cherries -> cherry, berries -> berry).
      3. ends "ves" -> delegate to `inflect` (proven correct: leaves/loaves/knives/wolves/
         scarves/calves -> -f, while cloves/olives/gloves are correctly left alone).
      4. ends one of the plural sibilant-suffix endings -> drop the "es" (boxes -> box).
      5. ends "s" (not "ss"), longer than 3 chars -> drop the "s" (cloves -> clove — reached
         only when step 3 didn't already match).
      6. does NOT end in "s" at all -> delegate to `inflect` for true irregulars (geese/goose,
         teeth/tooth, feet/foot, mice/mouse, children/child, people/person) a suffix rule could
         never reach — safe specifically because there's no trailing "s" for `inflect`'s
         aggressive generic fallback to blindly strip.
      7. otherwise (a short word, or ends "ss") -> unchanged.

    Already-singular input is a safe no-op throughout. Expects `base_norm`-shaped input (already
    lowercased) but doesn't require it."""
    head, sep, tail = s.rpartition(" ")
    return f"{head}{sep}{_singularise_word(tail)}"


def normalise_ingredient_name(name: str) -> str:
    """The one shared ingredient-name grouping/matching key — `singularise(base_norm(name))`.
    Used at consolidation-grouping time, at every reference-table write/match site
    (`product_units`, `coarse_ingredients`, `ingredient_aliases`, `remembered_substitutions`,
    `usual_items`), and by the checklist's own AnyList fuzzy-match. Idempotent: normalising an
    already-normalised name is a no-op."""
    return singularise(base_norm(name))


def pluralise(name: str) -> str:
    """The natural-English plural of an already-singular, already-normalised name (2026-09-27,
    raised by hand-testing: the checklist showed "8 chicken thigh" — grammatically the matching
    key, but wrong as *display* text once a quantity or weight makes the plural the natural
    reading). Applied to the trailing word only, same reasoning as `singularise`.

    **Deliberately dumb about mass vs. count nouns — that decision does NOT belong here.**
    `inflect.plural_noun()` happily "pluralises" genuine mass nouns too (flour -> flours,
    salt -> salts, oil -> oils) in a way that reads wrong on a shopping list ("500g flours").
    Confirmed empirically the same way `singularise`'s own `inflect` split was: this is not a
    hand-rolled-vs-library gap, it's that "is this word countable at all" is a fact about the
    *ingredient*, not a fact `inflect` (or any generic English-morphology tool) can derive from
    the word's spelling alone. The caller — `app/services/checklist_display.py`, which has the
    DB access this pure module deliberately doesn't — decides *whether* to call this at all,
    using this household's own real usage as the countability signal (has this ingredient ever
    actually been recorded as a bare count anywhere?), not a guess from the word's shape."""
    head, sep, tail = name.rpartition(" ")
    result = _INFLECT.plural_noun(tail)
    return f"{head}{sep}{result if result else tail}"
