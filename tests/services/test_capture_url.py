"""Unit tests for app/services/capture_url.py. httpx and ai_extraction are both mocked — no
network, no Gemini call, per CLAUDE.md > Code Architecture & Maintainability > Tests.
"""

from __future__ import annotations
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services.capture_url import RecipeFetchError, _extract_text, _extract_title, fetch_and_extract


def _mock_response(html: str, status_code: int = 200):
    response = MagicMock()
    response.text = html
    response.content = html.encode("utf-8")
    if status_code >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=MagicMock(status_code=status_code)
        )
    else:
        response.raise_for_status.return_value = None
    return response


# --- _extract_text -----------------------------------------------------------


def test_extract_text_prefers_article_content():
    html = """
    <html><body>
      <nav>Home | About | Contact</nav>
      <article><h1>Tacos</h1><p>500g beef mince</p></article>
      <footer>Copyright 2026</footer>
    </body></html>
    """
    text = _extract_text(html)
    assert "500g beef mince" in text
    assert "Home | About | Contact" not in text
    assert "Copyright" not in text


def test_extract_text_falls_back_to_whole_page_when_nothing_matches():
    html = "<html><body><div>500g beef mince, 1 onion</div></body></html>"
    text = _extract_text(html)
    assert "500g beef mince" in text


def test_extract_text_strips_script_and_style():
    html = """
    <html><body>
      <script>alert('hi')</script>
      <style>.x { color: red; }</style>
      <article>1 onion, diced</article>
    </body></html>
    """
    text = _extract_text(html)
    assert "onion" in text
    assert "alert" not in text
    assert "color: red" not in text


# --- fetch_and_extract ---------------------------------------------------


def test_fetch_and_extract_calls_ai_with_extracted_text():
    html = "<html><head><title>Tacos Page</title></head><body><article>500g beef mince</article></body></html>"
    fake_result = MagicMock(title="AI Title")
    with patch("app.services.capture_url.httpx.get", return_value=_mock_response(html)):
        with patch("app.services.capture_url.ai_extraction.capture_recipe") as mock_extract:
            mock_extract.return_value = fake_result
            result = fetch_and_extract("fake-db", "https://example.com/tacos")

    assert result is fake_result
    _, kwargs = mock_extract.call_args
    assert kwargs["call_type"] == "recipe_url"
    assert kwargs["context_id"] == "https://example.com/tacos"
    assert "500g beef mince" in kwargs["text"]
    # The AI already returned a title — the HTML fallback must not override it.
    assert result.title == "AI Title"


def test_fetch_and_extract_falls_back_to_html_title_when_ai_title_is_null():
    # Capture-Fixes-Staged.md issue 1/2 belt-and-braces fallback: no AI call cost, just
    # parses the page's own <title>/og:title/<h1>.
    html = "<html><head><title>Best Tacos Ever | SomeSite</title></head><body></body></html>"
    fake_result = MagicMock(title=None)
    with patch("app.services.capture_url.httpx.get", return_value=_mock_response(html)):
        with patch("app.services.capture_url.ai_extraction.capture_recipe", return_value=fake_result):
            result = fetch_and_extract("fake-db", "https://example.com/tacos")
    assert result.title == "Best Tacos Ever | SomeSite"


# --- _extract_title -----------------------------------------------------------


def test_extract_title_prefers_og_title():
    html = (
        '<html><head><title>Fallback</title>'
        '<meta property="og:title" content="Hearty Roasted Veggie Salad"></head>'
        "<body><h1>Different heading</h1></body></html>"
    )
    assert _extract_title(html) == "Hearty Roasted Veggie Salad"


def test_extract_title_falls_back_to_h1_then_title_tag():
    assert _extract_title("<html><body><h1>  Tacos  </h1></body></html>") == "Tacos"
    assert _extract_title("<html><head><title>Just A Title</title></head></html>") == "Just A Title"


def test_extract_title_none_when_nothing_present():
    assert _extract_title("<html><body><p>no heading here</p></body></html>") is None


def test_fetch_and_extract_raises_on_timeout():
    with patch("app.services.capture_url.httpx.get", side_effect=httpx.TimeoutException("timed out")):
        with pytest.raises(RecipeFetchError):
            fetch_and_extract("fake-db", "https://example.com/slow")


def test_fetch_and_extract_raises_on_http_status_error():
    with patch(
        "app.services.capture_url.httpx.get", return_value=_mock_response("<html></html>", status_code=404)
    ):
        with pytest.raises(RecipeFetchError):
            fetch_and_extract("fake-db", "https://example.com/missing")


def test_fetch_and_extract_raises_on_connection_error():
    with patch("app.services.capture_url.httpx.get", side_effect=httpx.ConnectError("refused")):
        with pytest.raises(RecipeFetchError):
            fetch_and_extract("fake-db", "https://example.com/down")
