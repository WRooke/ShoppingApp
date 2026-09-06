"""Recipe library business logic — recipe CRUD (soft delete) and nested
recipe_ingredients CRUD. Plain Python / SQLAlchemy only, no `fastapi` import
here — see CLAUDE.md > Code Architecture & Maintainability. Routers
(app/routers/recipes.py) call these functions and translate the exceptions
below into the {"ok": false, "error": ...} envelope.
"""

from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import utcnow
from app.models.recipes import Recipe, RecipeIngredient
from app.schemas.capture import CaptureConfirmRequest
from app.schemas.recipes import (
    RecipeCreate,
    RecipeIngredientCreate,
    RecipeIngredientUpdate,
    RecipeUpdate,
)
from app.services import product_sections

logger = logging.getLogger(__name__)


class RecipeNotFoundError(Exception):
    def __init__(self, recipe_id: int) -> None:
        self.recipe_id = recipe_id
        super().__init__(f"Recipe {recipe_id} not found")


class IngredientNotFoundError(Exception):
    def __init__(self, recipe_id: int, ingredient_id: int) -> None:
        self.recipe_id = recipe_id
        self.ingredient_id = ingredient_id
        super().__init__(f"Ingredient {ingredient_id} not found on recipe {recipe_id}")


def _norm_resolved(value: str | None) -> str | None:
    """Normalise a resolved_ingredient the same way as an ingredient name (lowercase, trim);
    blank -> None (clears the substitution). Phase 3.9 M4."""
    if value is None:
        return None
    trimmed = " ".join(value.strip().lower().split())
    return trimmed or None


def _normalise_ingredient_name(name: str) -> str:
    """Lowercase + strip whitespace — see CLAUDE.md > Ingredient Normalisation.
    Automatic synonym matching ("green onion" vs "spring onion") is explicitly
    NOT implemented here — deferred, user review is the normalisation for now."""
    return name.strip().lower()


def _clean_optional_text(value: str | None) -> str | None:
    """Trim; a blank/whitespace-only string means 'not set' (-> None). Used for the
    optional free-text source-provenance fields on create — see CLAUDE.md > Data Model >
    recipes source provenance. (update_recipe stores what it's given via its exclude_unset
    loop; only the create paths normalise here.)"""
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


# --- duplicate recipe prevention -----------------------------------------
#
# Warn-with-override, never a hard block — see CLAUDE.md > Duplicate Recipe Prevention.
# All DB-read only / pure, so unit-testable with no network. Signals, strongest first:
# exact normalised source_url, exact normalised name, same book + overlapping page,
# conservative stdlib fuzzy name. Ingredient-set overlap is deliberately NOT a signal here
# (still deferred). Thresholds start strict (locked at Phase 4 kickoff: difflib ratio >= 0.85
# OR token-set Jaccard >= 0.8) and only loosen during verification if real near-dupes slip
# through.

_NAME_STOPWORDS = frozenset(
    {"the", "a", "an", "and", "with", "of", "in", "for", "on", "to"}
)
_FUZZY_RATIO_THRESHOLD = 0.85
_FUZZY_JACCARD_THRESHOLD = 0.8
# Priority (lower = stronger) drives both the 409 ordering and "one match per recipe".
_SIGNAL_PRIORITY = {"source_url": 1, "name_exact": 2, "book_page": 3, "fuzzy_name": 4}


@dataclass(frozen=True)
class DuplicateMatch:
    """A candidate existing recipe a save looked like. Maps 1:1 to
    schemas.recipes.DuplicateMatch (from_attributes) — the router doesn't reshape it."""

    id: int
    name: str
    source_summary: str | None
    matched_signal: str
    archived: bool


class PossibleDuplicateRecipeError(Exception):
    """Raised by the create paths when a save looks like an existing recipe and the request
    did not carry allow_duplicate=True. Translated to 409 POSSIBLE_DUPLICATE_RECIPE in
    app/main.py, with `matches` serialised into the error `detail`."""

    def __init__(self, matches: list[DuplicateMatch]) -> None:
        self.matches = matches
        super().__init__(f"{len(matches)} possible duplicate recipe(s)")


def _normalise_name_for_match(name: str) -> str:
    """strip().lower() with internal whitespace collapsed — the 'name exact' signal."""
    return " ".join((name or "").strip().lower().split())


def _normalise_source_url(url: str | None) -> str | None:
    """Lowercase host, drop the fragment, strip a trailing slash, drop utm_* query params.
    Returns None for anything that isn't a http(s) URL with a host."""
    if not url or not url.strip():
        return None
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return None
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        return None
    query = "&".join(
        part
        for part in parsed.query.split("&")
        if part and not part.lower().startswith("utm_")
    )
    path = parsed.path.rstrip("/")
    return urlunparse(
        (parsed.scheme.lower(), parsed.netloc.lower(), path, parsed.params, query, "")
    )


def _page_numbers(page: str | None) -> set[int]:
    """Integers referenced by a free-text page string, ranges expanded: "142-143" ->
    {142, 143}, "142 & 145" -> {142, 145}, "ch. 3" -> {3}. Empty when nothing parses."""
    if not page:
        return set()
    numbers: set[int] = set()
    for match in re.finditer(r"(\d+)\s*[-–]\s*(\d+)", page):
        lo, hi = int(match.group(1)), int(match.group(2))
        if lo <= hi and hi - lo <= 50:  # guard against a silly range blowing up the set
            numbers.update(range(lo, hi + 1))
    for token in re.findall(r"\d+", page):
        numbers.add(int(token))
    return numbers


def _name_token_set(name: str) -> set[str]:
    tokens = (
        re.sub(r"[^a-z0-9]+", "", w) for w in _normalise_name_for_match(name).split()
    )
    return {w for w in tokens if w and w not in _NAME_STOPWORDS}


def _fuzzy_name_match(a: str, b: str) -> bool:
    na, nb = _normalise_name_for_match(a), _normalise_name_for_match(b)
    if not na or not nb:
        return False
    if difflib.SequenceMatcher(None, na, nb).ratio() >= _FUZZY_RATIO_THRESHOLD:
        return True
    ta, tb = _name_token_set(a), _name_token_set(b)
    if not ta or not tb:
        return False
    jaccard = len(ta & tb) / len(ta | tb)
    return jaccard >= _FUZZY_JACCARD_THRESHOLD


def _source_summary(recipe: Recipe) -> str | None:
    if recipe.source_url:
        return recipe.source_url
    if recipe.source_book:
        return (
            f"From {recipe.source_book}, p.{recipe.source_page}"
            if recipe.source_page
            else f"From {recipe.source_book}"
        )
    return None


def _match_signal(
    candidate: Recipe,
    *,
    norm_name: str,
    norm_url: str | None,
    norm_book: str | None,
    page_nums: set[int],
    raw_name: str,
) -> str | None:
    """The strongest signal (if any) by which `candidate` looks like the recipe being saved."""
    if norm_url and _normalise_source_url(candidate.source_url) == norm_url:
        return "source_url"
    if norm_name and _normalise_name_for_match(candidate.name) == norm_name:
        return "name_exact"
    if (
        norm_book
        and candidate.source_book
        and _normalise_name_for_match(candidate.source_book) == norm_book
        and page_nums
        and page_nums & _page_numbers(candidate.source_page)
    ):
        return "book_page"
    if _fuzzy_name_match(raw_name, candidate.name):
        return "fuzzy_name"
    return None


def find_possible_duplicates(
    db: Session,
    *,
    name: str,
    source_url: str | None = None,
    source_book: str | None = None,
    source_page: str | None = None,
    exclude_id: int | None = None,
) -> list[DuplicateMatch]:
    """Existing recipes (archived included) that `name`/provenance look like, best signal
    per recipe, ordered strongest-signal-first then by name. DB reads only."""
    norm_name = _normalise_name_for_match(name)
    norm_url = _normalise_source_url(source_url)
    norm_book = _normalise_name_for_match(source_book) if source_book else None
    page_nums = _page_numbers(source_page)

    matches: list[DuplicateMatch] = []
    for candidate in db.query(Recipe).all():
        if exclude_id is not None and candidate.id == exclude_id:
            continue
        signal = _match_signal(
            candidate,
            norm_name=norm_name,
            norm_url=norm_url,
            norm_book=norm_book,
            page_nums=page_nums,
            raw_name=name,
        )
        if signal is None:
            continue
        matches.append(
            DuplicateMatch(
                id=candidate.id,
                name=candidate.name,
                source_summary=_source_summary(candidate),
                matched_signal=signal,
                archived=candidate.archived_at is not None,
            )
        )

    matches.sort(key=lambda m: (_SIGNAL_PRIORITY[m.matched_signal], m.name.lower()))
    return matches


def find_recipe_by_source_url(db: Session, url: str) -> Recipe | None:
    """Exact normalised-source_url match, for the URL-capture short-circuit (skip the Claude
    call entirely on a re-capture). Prefers a live recipe over an archived one."""
    norm_url = _normalise_source_url(url)
    if not norm_url:
        return None
    hits = [
        r
        for r in db.query(Recipe).filter(Recipe.source_url.isnot(None)).all()
        if _normalise_source_url(r.source_url) == norm_url
    ]
    hits.sort(key=lambda r: (r.archived_at is not None, r.id))
    return hits[0] if hits else None


def _raise_if_duplicate(db: Session, data: RecipeCreate | CaptureConfirmRequest) -> None:
    matches = find_possible_duplicates(
        db,
        name=data.name,
        source_url=data.source_url,
        source_book=data.source_book,
        source_page=data.source_page,
    )
    if matches:
        raise PossibleDuplicateRecipeError(matches)


# --- recipes ---------------------------------------------------------------


def create_recipe(db: Session, data: RecipeCreate, *, allow_duplicate: bool = False) -> Recipe:
    if not allow_duplicate:
        _raise_if_duplicate(db, data)
    recipe = Recipe(
        name=data.name.strip(),
        source_type=data.source_type,
        source_url=data.source_url,
        source_image_path=data.source_image_path,
        base_servings=data.base_servings,
        source_book=_clean_optional_text(data.source_book),
        source_page=_clean_optional_text(data.source_page),
        notes=data.notes,
        cuisine=data.cuisine,
        protein=data.protein,
    )
    for i, ing in enumerate(data.ingredients):
        recipe.ingredients.append(
            RecipeIngredient(
                name=_normalise_ingredient_name(ing.name),
                quantity=ing.quantity,
                unit=ing.unit,
                preparation=ing.preparation,
                sort_order=ing.sort_order or i,
                resolved_ingredient=_norm_resolved(ing.resolved_ingredient),
                substitution_note=_clean_optional_text(ing.substitution_note),
            )
        )
    db.add(recipe)
    db.commit()
    db.refresh(recipe)
    logger.info(
        "Recipe created: id=%s name=%r ingredients=%d",
        recipe.id,
        recipe.name,
        len(recipe.ingredients),
    )
    return recipe


def create_recipe_from_capture(
    db: Session, data: CaptureConfirmRequest, *, allow_duplicate: bool = False
) -> Recipe:
    """Saves a reviewed recipe capture (Chunk 3.4 — see CLAUDE.md > Build Phases > Phase 3).
    Differs from create_recipe() only in also writing product_sections rows for any
    ingredient carrying a suggested_section — see services/product_sections.py."""
    if not allow_duplicate:
        _raise_if_duplicate(db, data)
    recipe = Recipe(
        name=data.name.strip(),
        source_type=data.source_type,
        source_url=data.source_url,
        source_image_path=data.source_image_path,
        base_servings=data.base_servings,
        source_book=_clean_optional_text(data.source_book),
        source_page=_clean_optional_text(data.source_page),
        notes=data.notes,
        cuisine=data.cuisine,
        protein=data.protein,
    )
    ingredient_sections: dict[str, str] = {}
    confirmed_swaps: list[tuple[str, str]] = []
    for i, ing in enumerate(data.ingredients):
        normalised_name = _normalise_ingredient_name(ing.name)
        resolved = _norm_resolved(ing.resolved_ingredient)
        recipe.ingredients.append(
            RecipeIngredient(
                name=normalised_name,
                quantity=ing.quantity,
                unit=ing.unit,
                preparation=ing.preparation,
                sort_order=i,
                resolved_ingredient=resolved,
                substitution_note=_clean_optional_text(ing.substitution_note),
            )
        )
        if ing.suggested_section:
            ingredient_sections[normalised_name] = ing.suggested_section
        if resolved:
            confirmed_swaps.append((normalised_name, resolved))

    db.add(recipe)
    db.commit()
    db.refresh(recipe)
    logger.info(
        "Recipe created from capture: id=%s name=%r source_type=%s ingredients=%d",
        recipe.id,
        recipe.name,
        recipe.source_type,
        len(recipe.ingredients),
    )

    product_sections.tag_suggested_sections(db, ingredient_sections)

    # Bump last_used_at on any remembered substitution the user re-confirmed here, so it
    # floats to the top of the quick-picks next time (Phase 3.9 M4). Silent no-op for swaps
    # that aren't in the library.
    from app.services import substitutions as substitutions_service

    for original, substitute in confirmed_swaps:
        substitutions_service.touch(db, original_name=original, substitute_name=substitute)

    return recipe


def get_recipe(db: Session, recipe_id: int) -> Recipe:
    """Fetch by id regardless of archived state — archived recipes are still
    viewable by direct link, only excluded from the default browse list
    (see list_recipes)."""
    recipe = db.get(Recipe, recipe_id)
    if recipe is None:
        raise RecipeNotFoundError(recipe_id)
    return recipe


def list_recipes(
    db: Session,
    *,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    include_archived: bool = False,
) -> tuple[list[Recipe], int]:
    """Returns (page of recipes, total matching count) for pagination
    (see CLAUDE.md > API Conventions). Default view filters archived_at IS
    NULL, per CLAUDE.md > Data Model > recipes soft-delete."""
    query = db.query(Recipe)
    if not include_archived:
        query = query.filter(Recipe.archived_at.is_(None))
    if search:
        query = query.filter(func.lower(Recipe.name).contains(search.strip().lower()))

    total = query.count()
    recipes = query.order_by(Recipe.name.asc()).offset(offset).limit(limit).all()
    return recipes, total


def update_recipe(db: Session, recipe_id: int, data: RecipeUpdate) -> Recipe:
    recipe = get_recipe(db, recipe_id)
    changes = data.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is not None:
        changes["name"] = changes["name"].strip()
    for field, value in changes.items():
        setattr(recipe, field, value)
    db.commit()
    db.refresh(recipe)
    logger.info("Recipe updated: id=%s fields=%s", recipe_id, list(changes.keys()))
    return recipe


def archive_recipe(db: Session, recipe_id: int) -> None:
    """Soft delete — sets archived_at rather than removing the row (see
    CLAUDE.md > Data Model > recipes > soft-delete)."""
    recipe = get_recipe(db, recipe_id)
    recipe.archived_at = utcnow()
    db.commit()
    logger.info("Recipe archived: id=%s", recipe_id)


def unarchive_recipe(db: Session, recipe_id: int) -> Recipe:
    """Clears archived_at — backs the "Restore existing" action on the duplicate-recipe
    warning panel (see CLAUDE.md > Duplicate Recipe Prevention). Idempotent on a live recipe."""
    recipe = get_recipe(db, recipe_id)
    recipe.archived_at = None
    db.commit()
    db.refresh(recipe)
    logger.info("Recipe unarchived: id=%s", recipe_id)
    return recipe


# --- recipe_ingredients ------------------------------------------------


def add_ingredient(db: Session, recipe_id: int, data: RecipeIngredientCreate) -> RecipeIngredient:
    recipe = get_recipe(db, recipe_id)
    ingredient = RecipeIngredient(
        recipe_id=recipe.id,
        name=_normalise_ingredient_name(data.name),
        quantity=data.quantity,
        unit=data.unit,
        preparation=data.preparation,
        sort_order=data.sort_order,
        resolved_ingredient=_norm_resolved(data.resolved_ingredient),
        substitution_note=_clean_optional_text(data.substitution_note),
    )
    db.add(ingredient)
    db.commit()
    db.refresh(ingredient)
    logger.info(
        "Ingredient added: recipe_id=%s ingredient_id=%s name=%r",
        recipe_id,
        ingredient.id,
        ingredient.name,
    )
    return ingredient


def _get_ingredient(db: Session, recipe_id: int, ingredient_id: int) -> RecipeIngredient:
    ingredient = db.get(RecipeIngredient, ingredient_id)
    if ingredient is None or ingredient.recipe_id != recipe_id:
        raise IngredientNotFoundError(recipe_id, ingredient_id)
    return ingredient


def update_ingredient(
    db: Session, recipe_id: int, ingredient_id: int, data: RecipeIngredientUpdate
) -> RecipeIngredient:
    ingredient = _get_ingredient(db, recipe_id, ingredient_id)
    changes = data.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is not None:
        changes["name"] = _normalise_ingredient_name(changes["name"])
    if "resolved_ingredient" in changes:  # may be an explicit null to clear the swap
        changes["resolved_ingredient"] = _norm_resolved(changes["resolved_ingredient"])
    if "substitution_note" in changes:
        changes["substitution_note"] = _clean_optional_text(changes["substitution_note"])
    for field, value in changes.items():
        setattr(ingredient, field, value)
    db.commit()
    db.refresh(ingredient)
    logger.info(
        "Ingredient updated: recipe_id=%s ingredient_id=%s fields=%s",
        recipe_id,
        ingredient_id,
        list(changes.keys()),
    )
    return ingredient


def delete_ingredient(db: Session, recipe_id: int, ingredient_id: int) -> None:
    """Hard delete — recipe_ingredients has no soft-delete column in the data
    model (only recipes does), so removing an ingredient from a recipe is a
    real DELETE."""
    ingredient = _get_ingredient(db, recipe_id, ingredient_id)
    db.delete(ingredient)
    db.commit()
    logger.info("Ingredient deleted: recipe_id=%s ingredient_id=%s", recipe_id, ingredient_id)
