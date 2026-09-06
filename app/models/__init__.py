"""ORM models. Importing this package registers every table on ``Base.metadata``.

One module per table group (see CLAUDE.md > Data Model).
"""

from app.models.catalog import ProductUnit, Staple
from app.models.diagnostics import ApiUsage, ApiUsageReset
from app.models.history import ShoppingHistory
from app.models.planning import PlanningSession, SessionChecklistItem, SessionRecipe
from app.models.recipes import Recipe, RecipeIngredient
from app.models.store import ProductSection, Store, StoreSection

__all__ = [
    "Recipe",
    "RecipeIngredient",
    "ProductUnit",
    "Staple",
    "PlanningSession",
    "SessionRecipe",
    "SessionChecklistItem",
    "ShoppingHistory",
    "ApiUsage",
    "ApiUsageReset",
    "Store",
    "StoreSection",
    "ProductSection",
]
