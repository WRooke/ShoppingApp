"""Duplicate recipe prevention (Phase 4 Chunk 4.2) — split out of ``services/recipes.py`` at
the Phase 3.9 M-review per CLAUDE.md > Code Architecture > File size and scope discipline.

Warn-with-override, never a hard block — see CLAUDE.md > Duplicate Recipe Prevention. All
functions here are DB-read-only / pure (no network), so they unit-test with an in-memory
SQLite session and nothing else. ``services/recipes.py`` re-exports the public names
(``DuplicateMatch``, ``PossibleDuplicateRecipeError``, ``find_possible_duplicates``,
``find_recipe_by_source_url``) so existing ``recipes_service.<name>`` call sites and imports
keep working unchanged.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

from sqlalchemy.orm import Session

from app.models.recipes import Recipe
from app.schemas.capture import CaptureConfirmRequest
from app.schemas.recipes import RecipeCreate

# Signals, strongest first: exact normalised source_url, exact normalised name, same book +
# overlapping page, conservative stdlib fuzzy name. Ingredient-set overlap is deliberately
# NOT a signal here (still deferred). Thresholds locked at Phase 4 kickoff: difflib ratio
# >= 0.85 OR token-set Jaccard >= 0.8 — start strict, only loosen if real near-dupes slip
# through. See CLAUDE.md > Duplicate Recipe Prevention.

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


def raise_if_duplicate(db: Session, data: RecipeCreate | CaptureConfirmRequest) -> None:
    matches = find_possible_duplicates(
        db,
        name=data.name,
        source_url=data.source_url,
        source_book=data.source_book,
        source_page=data.source_page,
    )
    if matches:
        raise PossibleDuplicateRecipeError(matches)
