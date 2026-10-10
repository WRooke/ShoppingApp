"""The client auto-update banner (static/js/update-banner.js), driven in a real headless browser.
docs/ui-ux.md > Client auto-update notification; docs/deployment-and-operations.md > "How an open
phone learns the NUC was updated".

`window.fetch` is stubbed for /api/v1/health so a "new build" can be simulated without restarting
the server; the full restart-for-real flow is tests/frontend/test_update_banner_e2e.py.
"""

from __future__ import annotations

import json
import time

TIMEOUT = 8.0

STUB = """
window.__h = {build: %s, fail: false, calls: 0};
if (!window.__realFetch) window.__realFetch = window.fetch;
window.fetch = function (url, opts) {
  if (String(url).indexOf('/api/v1/health') >= 0) {
    window.__h.calls++;
    if (window.__h.fail) return Promise.reject(new TypeError('Failed to fetch'));
    return Promise.resolve(new Response(
      JSON.stringify({ok: true, data: {build_id: window.__h.build}}), {status: 200}));
  }
  return window.__realFetch.apply(this, arguments);
};
"""


def _load(browser, server_url, path="/#/home"):
    browser.navigate(f"{server_url}{path}")
    browser.wait_for(".nav-item")


def _reload(browser):
    """location.reload(), then wait until the NEW document (not the one being replaced) has run its
    scripts — replaces fixed ``sleep(1.2)`` calls."""
    browser.eval("window.__pre = 1; location.reload();")
    assert _wait(browser, "window.__pre === undefined && !!window.UpdateBanner", timeout=8), "page never reloaded"


def _stub(browser, build):
    browser.eval(STUB % json.dumps(build))


def _wait(browser, expr, timeout=TIMEOUT):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if browser.eval(expr):
                return True
        except RuntimeError:
            # e.g. `window.UpdateBanner` not defined yet: `.nav-item` is in the static HTML, so it
            # exists before any script has run (2026-10-07: this made the unstamped-page test flaky).
            pass
        time.sleep(0.05)
    return False


def test_baseline_is_the_stamp_the_page_was_served_with_and_matches_the_server(browser, server_url, api):
    _load(browser, server_url)
    stamp = browser.eval("document.querySelector('meta[name=app-build]').getAttribute('content')")
    served = api.get("/api/v1/health").json()["data"]["build_id"]

    assert stamp == served and stamp != "__BUILD__"
    assert browser.eval("window.UpdateBanner.getLoadedVersion()") == stamp  # NOT learned from the network
    time.sleep(0.5)
    assert browser.eval("!document.querySelector('.update-banner')")  # same build -> no banner
    assert browser.eval("window.UpdateBanner.getState().status") == "idle"
    assert not browser.console_errors(), browser.console_errors()


def test_a_newer_server_build_shows_the_banner_and_it_does_not_cover_the_page(browser, server_url):
    _load(browser, server_url)
    _stub(browser, "some-newer-build")
    browser.eval("window.UpdateBanner.checkNow();")
    browser.wait_for(".update-banner")

    assert browser.text(".update-banner .msg") == "Update available"
    assert browser.text(".update-banner .cta") == "Tap to refresh"
    assert browser.eval("window.UpdateBanner.getState().status") == "available"
    geometry = browser.eval(
        "(function(){var b=document.querySelector('.update-banner').getBoundingClientRect();"
        "var h=document.querySelector('.app-header').getBoundingClientRect();"
        "var hit=document.elementFromPoint(b.left+b.width/2,b.top+b.height/2);"
        "return {bannerBottom:b.bottom, bannerHeight:b.height, headerTop:h.top,"
        "centreIsBanner: !!(hit && hit.closest('.update-banner')),"
        "bodyPad: parseFloat(getComputedStyle(document.body).paddingTop)};})()"
    )
    assert geometry["bannerHeight"] >= 44  # a real tap target
    assert geometry["centreIsBanner"]  # nothing sits on top of it
    assert geometry["headerTop"] >= geometry["bannerBottom"] - 1  # the page header is pushed BELOW it
    assert geometry["bodyPad"] >= geometry["bannerHeight"] - 1
    assert not browser.console_errors(), browser.console_errors()


def test_the_same_build_is_a_no_op_even_when_asked_repeatedly(browser, server_url):
    _load(browser, server_url)
    stamp = browser.eval("window.UpdateBanner.getLoadedVersion()")
    _stub(browser, stamp)
    for _ in range(3):
        browser.eval("window.UpdateBanner.checkNow();")
    time.sleep(0.4)
    assert browser.eval("!document.querySelector('.update-banner')")
    assert browser.eval("window.__h.calls") >= 1


def test_a_failed_check_does_not_lose_the_baseline_and_the_retry_finds_the_update(browser, server_url):
    """The old banner took its baseline from the first successful /health answer, so a failed (or
    late) first check meant the NEXT answer — already the new build — became the baseline and the
    banner never fired. The baseline now comes from the page's own stamp."""
    _load(browser, server_url)
    _stub(browser, "x")
    browser.eval("window.__h.fail = true; window.UpdateBanner.checkNow();")
    time.sleep(0.5)
    assert browser.eval("!document.querySelector('.update-banner')")
    assert any("update check failed" in c for c in browser.console_errors())  # not silent

    # the server is back, running a new build: the scheduled retry (5s) must find it
    browser.eval("window.__h.fail = false; window.__h.build = 'newer-after-outage';")
    assert _wait(browser, "!!document.querySelector('.update-banner')", timeout=9), "retry never ran"
    assert browser.eval("window.UpdateBanner.getState().target") == "newer-after-outage"


def test_checks_run_when_the_tab_returns_not_just_on_a_timer_and_are_coalesced(browser, server_url):
    _load(browser, server_url)
    stamp = browser.eval("window.UpdateBanner.getLoadedVersion()")
    _stub(browser, stamp)
    time.sleep(5.3)  # clear the minimum gap since the load-time check

    base = browser.eval("window.__h.calls")
    browser.eval("document.dispatchEvent(new Event('visibilitychange'));")  # headless: visible
    assert _wait(browser, f"window.__h.calls > {base}", timeout=3), "visibilitychange did not trigger a check"

    after_visible = browser.eval("window.__h.calls")
    browser.eval("window.dispatchEvent(new Event('focus')); window.dispatchEvent(new Event('focus'));")
    time.sleep(0.3)
    assert browser.eval("window.__h.calls") == after_visible  # focus right after = coalesced, not a storm

    browser.eval("window.dispatchEvent(new Event('online'));")  # network came back: forced
    assert _wait(browser, f"window.__h.calls > {after_visible}", timeout=3), "online did not trigger a check"

    after_online = browser.eval("window.__h.calls")
    browser.eval(
        "var e = new Event('pageshow'); e.persisted = true; window.dispatchEvent(e);"
    )  # restored from the back/forward cache: forced
    assert _wait(browser, f"window.__h.calls > {after_online}", timeout=3), "pageshow(persisted) did not trigger a check"


def test_a_restored_page_that_is_already_stale_is_noticed(browser, server_url):
    """The common phone case: the tab is restored from cache AFTER the server was updated. The
    page's stamp is the old build; the first check sees the new one."""
    _load(browser, server_url)
    _stub(browser, "the-server-moved-on")
    browser.eval("var e = new Event('pageshow'); e.persisted = true; window.dispatchEvent(e);")
    assert _wait(browser, "!!document.querySelector('.update-banner')", timeout=4)


def test_update_pending_survives_a_reload_and_reports_an_update_that_did_not_load(browser, server_url):
    _load(browser, server_url)
    browser.eval("sessionStorage.setItem('updatePendingBuild', 'a-newer-build');")
    browser.navigate(f"{server_url}/#/home")  # same document? force a real reload below
    _reload(browser)
    browser.wait_for(".update-banner")  # remembered across the reload, before any network answer
    assert browser.text(".update-banner .msg") == "Update available"

    browser.eval("sessionStorage.setItem('updateAttempt', JSON.stringify({target:'a-newer-build', n:1}));")
    _reload(browser)
    browser.wait_for(".update-banner")
    assert browser.text(".update-banner .msg") == "Update didn't load"
    assert browser.text(".update-banner .cta") == "Tap to try again"
    assert browser.eval("window.UpdateBanner.getState().status") == "failed"


def test_pending_state_clears_once_the_page_really_is_the_new_build(browser, server_url):
    _load(browser, server_url)
    stamp = browser.eval("window.UpdateBanner.getLoadedVersion()")
    browser.eval(
        f"sessionStorage.setItem('updatePendingBuild', {json.dumps(stamp)});"
        "sessionStorage.setItem('updateAttempt', JSON.stringify({target:" + json.dumps(stamp) + ", n:1}));"
    )
    _reload(browser)
    browser.wait_for(".nav-item")
    assert browser.eval("!document.querySelector('.update-banner')")
    assert browser.eval("sessionStorage.getItem('updatePendingBuild')") is None
    assert browser.eval("sessionStorage.getItem('updateAttempt')") is None


def test_tapping_navigates_to_a_fresh_document_keeps_the_route_and_tidies_the_url(browser, server_url):
    _load(browser, server_url, "/#/recipes")
    _stub(browser, "freshly-built")
    browser.eval("window.__marker = 'before-tap'; window.UpdateBanner.checkNow();")
    browser.wait_for(".update-banner")

    browser.eval("document.querySelector('.update-banner').click()")
    assert _wait(browser, "window.__marker === undefined", timeout=8), "tapping did not load a new document"
    browser.wait_for(".nav-item")
    assert browser.eval("location.hash") == "#/recipes"  # the user lands where they were
    # ?b= is tidied out of the address bar by the banner script once it has run. `.nav-item` is in the
    # static HTML (before any script), so wait for the tidy-up instead of assuming it already happened.
    assert _wait(browser, "location.search === ''", timeout=5), browser.eval("location.search")
    # the real server did NOT change build, so this page is still "stale" relative to the tap's
    # target and says so honestly instead of silently looping
    browser.wait_for(".update-banner")
    assert browser.text(".update-banner .msg") == "Update didn't load"


def test_keyboard_activation_works_like_a_tap(browser, server_url):
    _load(browser, server_url)
    _stub(browser, "kbd-build")
    browser.eval("window.__marker = 'x'; window.UpdateBanner.checkNow();")
    browser.wait_for(".update-banner")
    assert browser.eval("document.querySelector('.update-banner').getAttribute('role')") == "button"
    assert browser.eval("document.querySelector('.update-banner').tabIndex") == 0
    browser.eval(
        "document.querySelector('.update-banner').dispatchEvent("
        "new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));"
    )
    assert _wait(browser, "window.__marker === undefined", timeout=8)


def test_an_unstamped_page_degrades_to_first_answer_is_the_baseline(browser, server_url, api):
    """index.html opened raw (no server stamp) must not crash or nag: it behaves like the old
    banner — the first health answer becomes the baseline, a later different one fires."""
    browser.navigate(f"{server_url}/static/index.html#/home")
    browser.wait_for(".nav-item")
    served = api.get("/api/v1/health").json()["data"]["build_id"]
    assert _wait(browser, "window.UpdateBanner.getLoadedVersion() !== null", timeout=4)
    assert browser.eval("window.UpdateBanner.getLoadedVersion()") == served
    assert browser.eval("!document.querySelector('.update-banner')")
    _stub(browser, "changed")
    browser.eval("window.UpdateBanner.checkNow();")
    browser.wait_for(".update-banner")
