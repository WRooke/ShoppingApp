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

# Full desktop-Chrome header set, not just the UA — triaged 2026-09-07 against a real 406
# from tasty.co. httpx's bare defaults (Accept: */*, Accept-Encoding: gzip, deflate — no
# `br`) paired with a Chrome UA read as non-browser traffic to that site's WAF and got a flat
# 406 with no body, regardless of the UA string. A real Chrome request always advertises
# Accept-Encoding including `br` (brotli); sending that ourselves (rather than leaving it to
# httpx's auto-detection of the optional `brotli` package, which is easy to lose track of)
# is what gets past the check. `brotli` is pinned in requirements.txt so the br-encoded
# response actually decodes instead of coming back as mojibake — see the comment there.
ACCEPT_HEADERS = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,"
        "image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
}

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


def _extract_title(html: str) -> str | None:
    """Best-effort page title, straight from the fetched HTML — no AI call involved
    (Capture-Fixes-Staged.md issue 1/2, 2026-09-07). Used only as a fallback when the AI
    extraction call's own `title` comes back null; a page's <title>/og:title is often noisier
    than the AI's read of the actual recipe heading (site name suffixes, "| Recipe" etc.), so
    it's the fallback, not the primary source. Tries, in order: `og:title` meta tag (usually
    the cleanest — sites populate this deliberately for link previews), the first `<h1>`,
    then `<title>`."""
    soup = BeautifulSoup(html, "html.parser")

    og = soup.find("meta", property="og:title")
    if og and og.get("content", "").strip():
        return og["content"].strip()

    h1 = soup.find("h1")
    if h1:
        text = h1.get_text(strip=True)
        if text:
            return text

    if soup.title and soup.title.string and soup.title.string.strip():
        return soup.title.string.strip()

    return None


def fetch_and_extract(db: Session, url: str) -> ai_extraction.ExtractionResult:
    """Fetches `url`, extracts readable text, and calls ai_extraction.capture_recipe()
    with call_type='recipe_url'. Raises RecipeFetchError on fetch failure; extraction-side
    errors (spend cap, disabled, unparseable response) propagate from ai_extraction as-is.
    If the AI didn't return a title, falls back to one parsed straight from the page's own
    HTML (see _extract_title) — belt-and-braces, no extra AI cost."""
    logger.info("Recipe URL fetch attempt: %s", url)
    try:
        response = httpx.get(
            url,
            timeout=FETCH_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, **ACCEPT_HEADERS},
        )
        response.raise_for_status()
    except httpx.TimeoutException as exc:
        logger.error("Recipe URL fetch timed out: %s", url, exc_info=True)
        raise RecipeFetchError(url, "the request timed out") from exc
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        logger.error("Recipe URL fetch failed: HTTP %s for %s", status, url)
        # 403/406/429 on a page that opens fine in a browser is almost always anti-bot
        # blocking (the tasty.co 406 that prompted the header fix above was exactly this),
        # not a broken URL — say so, since "HTTP 406" alone gives the user nothing to act on.
        if status in (403, 406, 429):
            raise RecipeFetchError(
                url,
                f"the site blocked this request (HTTP {status}) — it may be detecting "
                "automated access; try again later or add the recipe manually",
            ) from exc
        raise RecipeFetchError(url, f"the page returned HTTP {status}") from exc
    except httpx.HTTPError as exc:
        logger.error("Recipe URL fetch failed: %s", url, exc_info=True)
        raise RecipeFetchError(url, str(exc)) from exc

    logger.info("Recipe URL fetch succeeded: %s (%d bytes)", url, len(response.content))
    html = response.text
    text = _extract_text(html)
    result = ai_extraction.capture_recipe(db, call_type="recipe_url", context_id=url, text=text)
    if not result.title:
        result.title = _extract_title(html)
    return result
