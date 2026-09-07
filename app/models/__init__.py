"""ORM models. Importing this package registers every table on ``Base.metadata``.

One module per table group (see CLAUDE.md > Data Model).
"""

from app.models.catalog import ProductUnit, RememberedSubstitution, Staple, UsualItem
from app.models.diagnostics import AiCallLog
from app.models.history import ShoppingHistory
from app.models.planning import PlanningSession, SessionChecklistItem, SessionRecipe
from app.models.queue import CaptureQueueItem
from app.models.recipes import Recipe, RecipeIngredient
from app.models.store import ProductSection, Store, StoreSection

__all__ = [
    "Recipe",
    "RecipeIngredient",
    "ProductUnit",
    "Staple",
    "UsualItem",
    "RememberedSubstitution",
    "PlanningSession",
    "SessionRecipe",
    "SessionChecklistItem",
    "ShoppingHistory",
    "AiCallLog",
    "Store",
    "StoreSection",
    "ProductSection",
    "CaptureQueueItem",
]
