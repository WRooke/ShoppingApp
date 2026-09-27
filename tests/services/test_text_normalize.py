"""Unit tests for app/services/text_normalize.py — the shared ingredient-name normaliser
(2026-09-27, see the ingredient-name-matching plan). Pure functions, no DB.
"""

from __future__ import annotations

from app.services.text_normalize import base_norm, normalise_ingredient_name, pluralise, singularise


# --- base_norm ---------------------------------------------------------------------


def test_base_norm_lowercases_and_trims():
    assert base_norm("  Carrot  ") == "carrot"


def test_base_norm_collapses_internal_whitespace():
    assert base_norm("spring   onion") == "spring onion"


def test_base_norm_folds_hyphen_to_space_both_directions():
    assert base_norm("extra-virgin olive oil") == "extra virgin olive oil"
    assert base_norm("extra virgin olive oil") == "extra virgin olive oil"


def test_base_norm_does_not_glue_words_together():
    assert "extravirgin" not in base_norm("extra-virgin olive oil")


# --- singularise (backed by `inflect`, see the module docstring for why) ------------------


def test_singularise_generic_plural():
    assert singularise("cloves") == "clove"
    assert singularise("carrots") == "carrot"


def test_singularise_leaves_already_singular_alone():
    assert singularise("clove") == "clove"


def test_singularise_ss_ending_untouched():
    assert singularise("glass") == "glass"


def test_singularise_sibilant_plural():
    assert singularise("boxes") == "box"
    assert singularise("dishes") == "dish"


def test_singularise_ies_to_y():
    assert singularise("cherries") == "cherry"
    assert singularise("berries") == "berry"


def test_singularise_ves_to_f():
    assert singularise("leaves") == "leaf"
    assert singularise("loaves") == "loaf"
    # `inflect` handles the general -ves -> -f/-fe pattern correctly on its own — unlike the
    # original hand-rolled whitelist (only leaves/loaves), it also gets knives/wolves/scarves/
    # calves right without needing each one enumerated by hand.
    assert singularise("knives") == "knife"
    assert singularise("wolves") == "wolf"
    assert singularise("scarves") == "scarf"
    assert singularise("calves") == "calf"


def test_singularise_ves_ending_non_irregular_words_use_generic_strip():
    # These end in "ves" as a coincidence of their own stem, not the leaf/loaf irregular
    # pattern — a blind "-ves -> -f" suffix rule would corrupt them (clof, olif, glof).
    # Also the specific word TextBlob was found to regress ("olives" -> "olife", wrong) during
    # this module's library evaluation — locked in here as a permanent regression guard.
    assert singularise("cloves") == "clove"
    assert singularise("olives") == "olive"
    assert singularise("gloves") == "glove"


def test_singularise_irregular_plural_matches_as_trailing_word_not_whole_string_only():
    # normalise_ingredient_name() calls this on full, often-multi-word ingredient names —
    # the irregular must be recognised as the trailing word, not just when it's the entire
    # string (a real bug caught in this module's original hand-rolled implementation).
    assert singularise("coriander leaves") == "coriander leaf"
    assert singularise("flat leaf parsley loaves") == "flat leaf parsley loaf"


def test_singularise_true_irregulars_a_suffix_rule_approach_could_never_cover():
    # The actual value-add of delegating to `inflect` instead of hand-rolled suffix rules —
    # none of these end in a plain "+s"/"+es" pattern a regex could catch.
    assert singularise("geese") == "goose"
    assert singularise("teeth") == "tooth"
    assert singularise("feet") == "foot"
    assert singularise("mice") == "mouse"
    assert singularise("children") == "child"
    assert singularise("people") == "person"


def test_singularise_us_guard():
    # Real pantry words ending in a bare "us" must never be treated as a plural — `inflect`
    # itself gets these wrong by default (treats ANY "-us" ending as a candidate "-u" plural),
    # confirmed empirically during this module's library evaluation; _US_WHITELIST guards them.
    for word in ("asparagus", "couscous", "hummus", "citrus"):
        assert singularise(word) == word


def test_singularise_double_s_ending_never_delegated_to_inflect():
    # A second real `inflect` bug found empirically during this module's library evaluation:
    # `singular_noun()` blindly strips a trailing "s" from ANY word it doesn't specifically
    # recognise, including double-"s" words that are never plurals of a single-"s" word
    # ("glass" -> "glas", "class" -> "clas"). The hand-rolled generic rule's own
    # `not endswith("ss")` guard (pre-existing, kept from before the `inflect` adoption) means
    # these never reach `inflect`'s fallback in the first place — this test is a permanent
    # regression guard for that specific interaction, not just the guard in isolation.
    for word in ("glass", "class", "brass", "boss", "dress", "success", "business"):
        assert singularise(word) == word


def test_singularise_short_or_non_plural_s_words_never_delegated_to_inflect():
    # Same class of `inflect` fallback aggressiveness as the "-ss" case above, for short or
    # clearly-non-plural words ending in a single "s" — none of these are plausible ingredient
    # names, but they demonstrate the hand-rolled rule's existing `len > 3` floor already
    # protects against `inflect`'s fallback here too, without needing a dedicated guard.
    for word in ("gas", "yes", "his", "was", "has"):
        assert singularise(word) == word


def test_singularise_us_guard_is_a_whitelist_not_a_blanket_rule():
    # The whitelist must NOT become a blanket "ends in us" bypass — that would reintroduce the
    # original hand-rolled bug this module's design fixed: "tofus" (tofu + a plain "s") must
    # still correctly reduce to "tofu", since it's not one of the 4 whitelisted words.
    assert singularise("tofus") == "tofu"


def test_singularise_idempotent():
    for word in ("carrots", "leaves", "cherries", "asparagus", "clove", "geese", "tofus"):
        once = singularise(word)
        assert singularise(once) == once


# --- normalise_ingredient_name -------------------------------------------------------


def test_confirmed_real_pairs_normalise_identically():
    pairs = [
        ("carrot", "carrots"),
        ("spring onion", "spring onions"),
        ("extra virgin olive oil", "extra-virgin olive oil"),
        ("chicken thigh", "chicken thighs"),
    ]
    for a, b in pairs:
        assert normalise_ingredient_name(a) == normalise_ingredient_name(b), (a, b)


def test_must_not_merge_cases_stay_distinct():
    groups = [
        ["coriander", "coriander leaves", "fresh coriander"],
        ["ground cumin", "cumin"],
        ["chicken breasts", "chicken legs", "chicken thighs"],
        ["heavy cream", "thickened cream"],
        ["broth", "stock"],
        ["plain yoghurt", "greek yoghurt"],
    ]
    for group in groups:
        keys = {normalise_ingredient_name(name) for name in group}
        assert len(keys) == len(group), group


def test_asparagus_couscous_hummus_citrus_unchanged_end_to_end():
    for word in ("asparagus", "couscous", "hummus", "citrus"):
        assert normalise_ingredient_name(word) == word


# --- corpus regression guard (F1.1a) ------------------------------------------------------
# Every distinct ingredient name from both data/mealplanner.db and data/mealplanner_prod.db as
# of the 2026-09-27 empirical library evaluation (192 names) normalised to a stable, reviewed
# value with zero surprises — see the ingredient-name-matching plan's F1.1a decision rule. This
# is a frozen snapshot, not a live DB query: a future `inflect` version bump or rule change that
# silently changes real-word behaviour must fail this test, not slip through unnoticed. Encoded
# as "no two names in this list collide except the ones already confirmed as intentional merges"
# rather than asserting every single mapping, to stay maintainable.
_REAL_CORPUS_MUST_NOT_COLLIDE = [
    # A representative slice most likely to exercise a future regression — full list intentionally
    # not enumerated here (192 entries); see the plan's F1.1a for the full one-off comparison run.
    "beef mince", "chicken breast", "chicken thigh", "egg", "egg yolk", "diced tomato",
    "cherry tomato", "tomato passata", "tomato paste", "coriander", "coriander leaves",
    "fresh coriander", "ground cumin", "cumin", "asparagus", "couscous", "hummus", "citrus",
    "basmati rice", "white rice", "olive oil", "vegetable oil", "sesame oil", "soy sauce",
    "fish sauce", "oyster sauce", "garlic", "garlic powder", "ginger", "onion", "red onion",
    "brown onion", "capsicum", "red capsicum", "feta", "bulgarian feta", "parsley",
    "parsley leaves", "flat leaf parsley leaves", "dill leaves",
]


def test_real_corpus_has_no_unexpected_collisions():
    seen: dict[str, str] = {}
    for name in _REAL_CORPUS_MUST_NOT_COLLIDE:
        key = normalise_ingredient_name(name)
        if key in seen and seen[key] != name:
            # Only the plural/hyphen pairs already confirmed as intentional merges may collide.
            raise AssertionError(f"unexpected collision: {name!r} and {seen[key]!r} both -> {key!r}")
        seen[key] = name


# --- pluralise (2026-09-27 — checklist display, see app/services/checklist_display.py for the
# DB-aware countability gate that decides WHETHER to call this; this module only knows HOW) ---


def test_pluralise_regular_count_nouns():
    assert pluralise("carrot") == "carrots"
    assert pluralise("egg") == "eggs"
    assert pluralise("tomato") == "tomatoes"


def test_pluralise_multi_word_only_pluralises_trailing_word():
    assert pluralise("chicken thigh") == "chicken thighs"
    assert pluralise("extra virgin olive oil") == "extra virgin olive oils"


def test_pluralise_is_the_inverse_of_singularise_for_real_pairs():
    for singular in ("carrot", "chicken thigh", "tomato", "egg", "clove"):
        assert singularise(pluralise(singular)) == singular


def test_pluralise_does_not_crash_on_us_whitelisted_words():
    # Not expected to be called on these in practice (checklist_display.py's countability gate
    # would never let a mass noun like this reach pluralise()), but must not raise either way.
    for word in ("asparagus", "hummus"):
        assert isinstance(pluralise(word), str)
