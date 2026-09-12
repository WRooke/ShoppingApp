"""Gemini structured-output (``response_schema``) Pydantic models — one per call.

Part of the ``ai_extraction`` package (split from the former single-file module at the
Phase 5 review, 2026-09-12 — see CLAUDE.md > Deferred Decisions). These are the shapes
Gemini's structured-output mode is constrained to return; ``calls.py`` still parses the
resulting JSON by hand and allow-list-validates fixed-vocabulary fields (§0a) rather than
trusting these schemas alone to guarantee a safe value — a field can be the right *type*
and still be a value we don't want to accept (a hallucinated section name, say).
"""

from __future__ import annotations

from pydantic import BaseModel


class _GIngredient(BaseModel):
    name: str
    quantity: float
    unit: str | None = None
    preparation: str | None = None
    original_text: str = ""


class _GExtraction(BaseModel):
    title: str | None = None
    servings: int | None = None
    cuisine: str | None = None
    protein: str | None = None
    ingredients: list[_GIngredient]


class _GSectionEntry(BaseModel):
    name: str
    section: str | None = None


class _GSections(BaseModel):
    sections: list[_GSectionEntry]


class _GFlag(BaseModel):
    original: str
    suggested_substitute: str
    note: str | None = None


class _GFlags(BaseModel):
    flags: list[_GFlag]


class _GUnitEntry(BaseModel):
    unit: str
    canonical: str | None = None


class _GUnitClassifications(BaseModel):
    units: list[_GUnitEntry]
