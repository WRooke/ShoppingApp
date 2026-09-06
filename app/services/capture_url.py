"""URL-based recipe capture — fetch the page, extract readable text, hand it to Claude.

See CLAUDE.md > Recipe Capture — AI Extraction > URL capture flow. Plain Python /
httpx / BeautifulSoup only, no `fastapi` import — see CLAUDE.md > Code Architecture &
Maintainability. Never executes anything derived from the fetched page — it's parsed as
text only and handed to `ai_extraction`, which treats it as untrusted data (see CLAUDE.md >
Security §0a and §4).
"""

from __future__ import annotations

import logging

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.services import ai_extraction

logger = logging.getLogger(__name__)

FETCH_TIMEOUT_SECONDS = 10.0

# A generic desktop UA — some recipe sites block the default httpx UA outright.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Prefer these elements' text over the whole page — cuts down nav/ad/footer noise before it
# ever reaches Claude. See CLAUDE.md > Recipe Capture > URL capture flow.
PREFERRED_SELECTORS = ["article", "main", "[class*=recipe]", "[class*=ingredient]"]

# Stripped outright regardless of which selector matched — never genuinely recipe content.
_NOISE_TAGS = ["script", "style", "nav", "footer", "header", "noscript"]


class RecipeFetchError(Exception):
    """Raised when the page can't be fetched at all — timeout, connection failure, or a
    non-2xx status. Callers translate this to the {"ok": false, "error": ...} envelope."""

    def __init__(self, url: str, reason: str) -> None:
        self.url = url
        self.reason = reason
        super().__init__(f"Could not fetch {url}: {reason}")


def _extract_text(html: str) -> str:
    """Best-effort readable text from a recipe page. Falls back to the whole page's text if
    none of the preferred selectors match anything — still safe to send on, since
    ai_extraction wraps it in the untrusted-content delimiter and enforces a length cap
    regardless of how it was extracted (see CLAUDE.md > Security §0a)."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(_NOISE_TAGS):
        tag.decompose()

    seen_elements: set[int] = set()
    parts: list[str] = []
    for selector in PREFERRED_SELECTORS:
        for element in soup.select(selector):
            if id(element) in seen_elements:
                continue
            seen_elements.add(id(element))
            text = element.get_text(separator="\n", strip=True)
            if text:
                parts.append(text)

    if parts:
        return "\n\n".join(parts)
    return soup.get_text(separator="\n", strip=True)


def fetch_and_extract(db: Session, url: str) -> ai_extraction.ExtractionResult:
    """Fetches `url`, extracts readable text, and calls ai_extraction.capture_recipe()
    with call_type='recipe_url'. Raises RecipeFetchError on fetch failure; extraction-side
    errors (spend cap, disabled, unparseable response) propagate from ai_extraction as-is."""
    logger.info("Recipe URL fetch attempt: %s", url)
    try:
        response = httpx.get(
            url,
            timeout=FETCH_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
    except httpx.TimeoutException as exc:
        logger.error("Recipe URL fetch timed out: %s", url, exc_info=True)
        raise RecipeFetchError(url, "the request timed out") from exc
    except httpx.HTTPStatusError as exc:
        logger.error(
            "Recipe URL fetch failed: HTTP %s for %s", exc.response.status_code, url
        )
        raise RecipeFetchError(url, f"the page returned HTTP {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        logger.error("Recipe URL fetch failed: %s", url, exc_info=True)
        raise RecipeFetchError(url, str(exc)) from exc

    logger.info("Recipe URL fetch succeeded: %s (%d bytes)", url, len(response.content))
    text = _extract_text(response.text)
    return ai_extraction.capture_recipe(db, call_type="recipe_url", context_id=url, text=text)
