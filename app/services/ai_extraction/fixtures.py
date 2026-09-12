"""Canned fake-mode responses — CLAUDE.md > Security §0c (offline development).

Part of the ``ai_extraction`` package (split from the former single-file module at the
Phase 5 review, 2026-09-12 — see CLAUDE.md > Deferred Decisions). Every call function in
``calls.py`` checks ``settings.ai_extraction_fake_mode`` first and, if set, returns one of
these instead of touching the network — zero key, zero cost, deterministic (the same input
always picks the same fixture, via ``_pick_fake_fixture``'s hash).
"""

from __future__ import annotations

import hashlib

_FAKE_FIXTURES: list[dict] = [
    {
        "_label": "weeknight beef tacos",
        "title": "Weeknight Beef Tacos",
        "servings": 4,
        "cuisine": "mexican",
        "protein": "beef mince",
        "ingredients": [
            {"name": "beef mince", "quantity": 500.0, "unit": "g", "preparation": None, "original_text": "500g beef mince", "suggested_section": "meat & seafood"},
            {"name": "onion", "quantity": 1.0, "unit": None, "preparation": "finely diced", "original_text": "1 onion, finely diced", "suggested_section": "produce"},
            {"name": "garlic", "quantity": 2.0, "unit": None, "preparation": "crushed", "original_text": "2 cloves garlic, crushed", "suggested_section": "produce"},
            {"name": "diced tomatoes", "quantity": 400.0, "unit": "g", "preparation": None, "original_text": "400g canned diced tomatoes", "suggested_section": "pantry"},
            {"name": "tortillas", "quantity": 8.0, "unit": None, "preparation": None, "original_text": "8 small tortillas", "suggested_section": "bakery"},
            {"name": "avocado", "quantity": 1.0, "unit": None, "preparation": None, "original_text": "1 avocado", "suggested_section": "produce"},
        ],
    },
    {
        "_label": "veggie stir fry",
        "title": "Veggie Stir Fry",
        "servings": 4,
        "cuisine": "chinese",
        "protein": "tofu",
        "ingredients": [
            {"name": "tofu", "quantity": 300.0, "unit": "g", "preparation": "cubed", "original_text": "300g firm tofu, cubed", "suggested_section": "deli"},
            {"name": "broccoli", "quantity": 1.0, "unit": None, "preparation": "cut into florets", "original_text": "1 head broccoli, cut into florets", "suggested_section": "produce"},
            {"name": "capsicum", "quantity": 1.0, "unit": None, "preparation": "sliced", "original_text": "1 capsicum, sliced", "suggested_section": "produce"},
            {"name": "soy sauce", "quantity": 3.0, "unit": "tbsp", "preparation": None, "original_text": "3 tbsp soy sauce", "suggested_section": "pantry"},
            {"name": "ginger", "quantity": 1.0, "unit": "tbsp", "preparation": "grated", "original_text": "1 tbsp grated ginger", "suggested_section": "produce"},
            {"name": "basmati rice", "quantity": 300.0, "unit": "g", "preparation": None, "original_text": "300g rice", "suggested_section": "pantry"},
        ],
    },
    {
        "_label": "creamy mushroom pasta",
        "title": "Creamy Mushroom Pasta",
        "servings": 4,
        "cuisine": "italian",
        "protein": None,
        "ingredients": [
            {"name": "pasta", "quantity": 400.0, "unit": "g", "preparation": None, "original_text": "400g pasta", "suggested_section": "pantry"},
            {"name": "mushrooms", "quantity": 300.0, "unit": "g", "preparation": "sliced", "original_text": "300g mushrooms, sliced", "suggested_section": "produce"},
            {"name": "cream", "quantity": 300.0, "unit": "ml", "preparation": None, "original_text": "300ml cream", "suggested_section": "dairy"},
            {"name": "garlic", "quantity": 3.0, "unit": None, "preparation": "crushed", "original_text": "3 cloves garlic, crushed", "suggested_section": "produce"},
            {"name": "parmesan", "quantity": 50.0, "unit": "g", "preparation": "grated", "original_text": "50g parmesan, grated", "suggested_section": "dairy"},
            {"name": "spinach", "quantity": 100.0, "unit": "g", "preparation": None, "original_text": "100g baby spinach", "suggested_section": "produce"},
        ],
    },
]

# Canned substitution flags for fake mode — keyed by ingredient name (see flag_substitutions).
_FAKE_SUBSTITUTION_FLAGS: dict[str, tuple[str, str | None]] = {
    "parmesan": ("pecorino", "a similar hard grating cheese"),
    "tortillas": ("flatbread or roti", "close enough for wraps"),
    "capsicum": ("bell pepper", "same thing, different name"),
}

_FAKE_SECTION_MAP: dict[str, str] = {
    ing["name"]: ing["suggested_section"]
    for fx in _FAKE_FIXTURES
    for ing in fx["ingredients"]
    if ing["suggested_section"]
}

# Canned unit classifications for fake mode (see classify_units()). Deliberately small and
# hand-picked rather than derived from anything — anything not listed here comes back
# unmatched in fake mode, same as a genuinely distinct unit would in real classification.
_FAKE_UNIT_CLASSIFICATIONS: dict[str, str] = {
    "grms": "g",
    "mlitre": "ml",
    "tbspoon": "tbsp",
}


def _pick_fake_fixture(seed_material: str) -> dict:
    digest = hashlib.sha256(seed_material.encode("utf-8")).hexdigest()
    return _FAKE_FIXTURES[int(digest, 16) % len(_FAKE_FIXTURES)]
