"""How the frontend is served — the half of the update banner that makes a refresh actually
deliver new code (docs/deployment-and-operations.md > "How an open phone learns the NUC was
updated"). Before 2026-10-06 static files had no Cache-Control, so a phone could keep running
old JS/CSS for hours after a reload."""

from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent.parent / "static"


def test_index_is_stamped_with_the_running_build_and_never_cached(client):
    build = client.get("/api/v1/health").json()["data"]["build_id"]
    resp = client.get("/")

    assert resp.status_code == 200 and resp.headers["cache-control"] == "no-cache"
    assert f'<meta name="app-build" content="{build}"' in resp.text
    assert "__BUILD__" not in resp.text  # the placeholder is always replaced


def test_every_asset_url_in_index_carries_the_build_so_a_new_build_is_a_new_url(client):
    """A guard: a script or stylesheet added to index.html WITHOUT `?v=__BUILD__` would be
    cached across updates (and silently run old code on phones)."""
    raw = (STATIC / "index.html").read_text(encoding="utf-8")
    refs = re.findall(r'<script[^>]+src="([^"]+)"', raw) + re.findall(
        r'<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"', raw
    )
    assert len(refs) > 30
    unversioned = [r for r in refs if "?v=__BUILD__" not in r]
    assert not unversioned, f"asset URLs without ?v=__BUILD__: {unversioned}"

    build = client.get("/api/v1/health").json()["data"]["build_id"]
    served = client.get("/").text
    assert re.findall(r'src="/static/js/api\.js\?v=([0-9a-f]+)"', served) == [build]


def test_static_files_always_revalidate_and_support_conditional_requests(client):
    first = client.get("/static/js/api.js")
    assert first.status_code == 200 and first.headers["cache-control"] == "no-cache"
    etag = first.headers["etag"]
    second = client.get("/static/js/api.js", headers={"If-None-Match": etag})
    assert second.status_code == 304  # an unchanged file costs a 304, not a download
    assert second.headers["cache-control"] == "no-cache"


def test_unknown_static_file_is_a_404(client):
    assert client.get("/static/js/does-not-exist.js").status_code == 404
