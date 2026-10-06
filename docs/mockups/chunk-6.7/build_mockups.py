"""Generates the Chunk 6.7 mockup pages (static HTML, light + dark side by side).

    .venv\\Scripts\\python docs\\mockups\\chunk-6.7\\build_mockups.py

Open docs/mockups/chunk-6.7/index.html in a browser. The pages link the REAL stylesheets in
static/css/ (so they look like the app) plus proposed.css (the new components). Light/dark frames
are produced by scoping the real token values under .theme-light / .theme-dark, because the real
tokens.css only switches on <html data-theme>. Static by design (standing mockup rule): no
interactivity, no tweak panel.
"""

from __future__ import annotations

import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATIC = HERE.parent.parent.parent / "static"


def _theme_css() -> str:
    tokens = (STATIC / "css" / "tokens.css").read_text(encoding="utf-8")
    root = re.search(r"^:root \{(.*?)^\}", tokens, re.S | re.M).group(1)
    dark = re.search(r':root\[data-theme="dark"\] \{(.*?)^\}', tokens, re.S | re.M).group(1)
    root = re.sub(r"color-scheme:[^;]*;", "", root)
    return (
        ".theme-light {" + root + "color-scheme: light; }\n"
        ".theme-dark {" + root + dark + "color-scheme: dark; }\n"
    )


PAGE_CSS = """
@font-face { font-family: "IBM Plex Sans"; font-weight: 400 700; src: url("../../../static/fonts/ibm-plex-sans-var.woff2") format("woff2"); }
@font-face { font-family: "IBM Plex Mono"; font-weight: 500; src: url("../../../static/fonts/ibm-plex-mono-500.woff2") format("woff2"); }
@font-face { font-family: "IBM Plex Mono"; font-weight: 600; src: url("../../../static/fonts/ibm-plex-mono-600.woff2") format("woff2"); }
html { background: #d9d6cf; }
body { margin: 0; padding: 24px 16px 80px; font-family: "IBM Plex Sans", system-ui, sans-serif; color: #2a2620; }
.mock-wrap { max-width: 1000px; margin: 0 auto; }
h1.mock { font-size: 1.5rem; margin: 0 0 4px; } p.lede { margin: 0 0 24px; max-width: 70ch; color: #4a463e; }
.scene { margin: 0 0 40px; }
.scene h2 { font-size: 1.05rem; margin: 0 0 2px; } .scene .note { margin: 0 0 12px; max-width: 80ch; color: #4a463e; font-size: .9rem; }
.pair { display: flex; gap: 20px; flex-wrap: wrap; align-items: flex-start; }
.frame { width: 390px; box-sizing: border-box; border-radius: 20px; overflow: hidden; position: relative; background: var(--bg); color: var(--text);
  font-family: "IBM Plex Sans", system-ui, sans-serif; font-size: var(--text-base); line-height: 1.5; border: 1px solid #00000033;
  box-shadow: 0 6px 24px #00000026; }
.cap { font-size: 11px; letter-spacing: .08em; text-transform: uppercase; color: #4a463e; margin: 0 0 4px 6px; font-weight: 700; }
.frame .pad { padding: var(--sp-4); }
.frame h3 { margin: 0 0 var(--sp-2); font-size: var(--text-md); }
.frame .app-header { position: static; }
.frame .bottom-nav { position: static; }
.frame .sticky-actions { position: static; }
.frame .update-banner { position: static; }
.frame .toast-static { display: flex; justify-content: center; padding: var(--sp-3) var(--sp-3) var(--sp-4); }
.frame .toast { position: static; transform: none; opacity: 1; }
.frame .statusbar { display: flex; justify-content: space-between; padding: 6px 18px; font-size: 12px; font-weight: 600; background: var(--bg); color: var(--text); }
.frame.phone-notch .update-banner { padding-top: calc(var(--sp-2) + 28px); }
.cmp { display: flex; gap: 20px; flex-wrap: wrap; } .cmp .tag { font-weight: 700; margin: 0 0 6px; font-size: .85rem; }
.nav-links a { margin-right: 16px; }
.decide { background: #fff8; border: 1px solid #0003; border-radius: 12px; padding: 14px 18px; max-width: 80ch; }
/* "AnyList app" imitation for the naming page */
.al { background: #212226; color: #fff; font-family: Roboto, system-ui, sans-serif; }
.al .top { padding: 14px 16px; border-bottom: 1px solid #0006; } .al .top b { font-size: 1.15rem; display: block; } .al .top span { color: #b9bbc2; font-size: .9rem; }
.al .item { padding: 13px 16px; border-bottom: 1px solid #ffffff22; font-size: 1.05rem; } .al .item small { color: #9a9ca3; font-size: .9rem; } .al .item.sub small { display: block; margin-top: 2px; }
.al .item .bad { background: #7a2a2a; border-radius: 4px; padding: 0 3px; } .al .item .good { background: #1f5d3a; border-radius: 4px; padding: 0 3px; }
"""


_frame_no = [0]


def frame(theme: str, inner: str, *, extra_class: str = "") -> str:
    _frame_no[0] += 1
    inner = inner.replace('name="k"', f'name="k{_frame_no[0]}"')  # radio groups must not span frames
    return f'<div class="framewrap"><div class="cap">{theme}</div><div class="frame theme-{theme} {extra_class}">{inner}</div></div>'


def scene(title: str, note: str, inner: str, *, extra_class: str = "") -> str:
    return (
        f'<section class="scene"><h2>{title}</h2><p class="note">{note}</p><div class="pair">'
        f'{frame("light", inner, extra_class=extra_class)}{frame("dark", inner, extra_class=extra_class)}</div></section>'
    )


def compare(title: str, note: str, before: str, after: str, theme: str = "dark", extra_class: str = "") -> str:
    return (
        f'<section class="scene"><h2>{title}</h2><p class="note">{note}</p><div class="cmp">'
        f'<div><p class="tag">Before (today)</p>{frame(theme, before, extra_class=extra_class)}</div>'
        f'<div><p class="tag">After</p>{frame(theme, after, extra_class=extra_class)}</div></div></section>'
    )


def page(name: str, title: str, lede: str, scenes: list[str]) -> None:
    theme = _theme_css()
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="../../../static/css/components.css"><link rel="stylesheet" href="../../../static/css/components-screens.css">
<link rel="stylesheet" href="../../../static/css/app.css"><link rel="stylesheet" href="proposed.css">
<style>{theme}{PAGE_CSS}</style></head><body><div class="mock-wrap">
<p class="nav-links"><a href="index.html">&larr; All mockups</a><a href="push.html">Push</a><a href="banner.html">Update banner</a><a href="popups.html">No popups</a><a href="names.html">Names</a></p>
<h1 class="mock">{title}</h1><p class="lede">{lede}</p>{"".join(scenes)}</div></body></html>"""
    (HERE / name).write_text(html, encoding="utf-8")


# ------------------------------------------------------------------------------------------
# shared bits of markup
# ------------------------------------------------------------------------------------------
def header(title: str) -> str:
    return f'<header class="app-header"><h1>{title}</h1></header>'


def nav(active: str = "plan") -> str:
    def item(key, icon, label):
        cls = "nav-item active" if key == active else "nav-item"
        return f'<a class="{cls}"><span class="nav-icon">{icon}</span><span class="nav-label">{label}</span></a>'
    return '<nav class="bottom-nav">' + item("home", "🏠", "Home") + item("recipes", "📖", "Recipes") + item("plan", "📋", "Plan") + item("settings", "⚙️", "Settings") + item("diag", "📊", "Diagnostics") + "</nav>"


def steps_list(active: str = "Checklist") -> str:
    labels = ["Plan", "Checklist", "Push"]
    parts = []
    for i, l in enumerate(labels):
        parts.append(f'<span class="{"on" if l == active else ""}">{l}</span>')
        if i < len(labels) - 1:
            parts.append('<span class="sep">→</span>')
    return '<div class="step-list">' + "".join(parts) + "</div>"


def step_row(status: str, name: str) -> str:
    icon = {"done": "✓", "failed": "✕"}.get(status, "")
    return f'<div class="step-row"><div class="step-icon {status}">{icon}</div><div class="step-label {status}">{name}</div></div>'


def stages(states: list[str], counts: str | None = None) -> str:
    names = ["Reading your list", "Sending", "Confirming", "Done"]
    lis = []
    for n, st in zip(names, states):
        extra = f' <span class="count">{counts}</span>' if (n == "Sending" and counts) else ""
        lis.append(f'<li class="{st}">{n}{extra}</li>')
    return '<ol class="push-stages">' + "".join(lis) + "</ol>"


def row(name: str, qty: str, state: str = "", on_list: bool = False, merge_checked: bool | None = None) -> str:
    have = 'aria-pressed="true"' if state == "have" else 'aria-pressed="false"'
    need = 'aria-pressed="true"' if state == "need" else 'aria-pressed="false"'
    cls = "checklist-row on-anylist" if on_list else "checklist-row"
    cb = ""
    pair = f'<div class="have-need-pair"><button class="have-need-btn have" {have}>Have it</button><button class="have-need-btn need" {need}>Need it</button></div>'
    if merge_checked is not None:
        cb = f'<input type="checkbox" class="merge-select-checkbox" {"checked" if merge_checked else ""}>'
        pair = ""
    return f'<div class="{cls}">{cb}<div class="main"><button class="name recipe-row-name-btn">{name} ▾</button><div class="meta-row"><div class="meta">{qty}</div></div></div>{pair}</div>'


# ------------------------------------------------------------------------------------------
# PUSH page
# ------------------------------------------------------------------------------------------
def build_push() -> None:
    sendrows = (
        step_row("done", "Beef Mince") + step_row("done", "Eggs") + step_row("done", "Olive Oil")
        + step_row("active", "Red Capsicums") + step_row("pending", "Salt") + step_row("pending", "Spring Onions")
    )
    allsent = "".join(step_row("done", n) for n in ["Beef Mince", "Eggs", "Olive Oil", "Red Capsicums", "Salt", "Spring Onions"])
    push_btn = '<div class="sticky-actions"><button class="primary btn-block">Push to AnyList</button></div>'
    busy_btn = '<div class="sticky-actions"><button class="primary btn-block" disabled><span class="spinner"></span> Pushing…</button></div>'

    s1 = scene(
        "1. Push — idle",
        "Unchanged from today: the summary line and the button. (Shown so the other states have context.)",
        header("Checklist") + '<div class="pad">' + steps_list() + '<div class="card"><h2>Shopping checklist</h2>'
        + row("beef mince", "500 g", "need") + row("eggs", "8", "need", on_list=False) + row("salt", "to taste", "have")
        + '<div class="muted" style="margin-top:12px">31 ingredient(s) + 2 of 3 usual(s) selected will go on the list.</div>'
        + push_btn + '</div></div>' + nav(),
    )
    s2 = scene(
        "2. Push — sending",
        "Terse, four stages: Reading your list → Sending (n of N) → Confirming → Done. Each item just shows its name with the existing spinner/tick icons "
        "(no 'Adding…/Added…' sentences). The list scrolls inside itself so the Push button never leaves the screen. Items are tracked by checklist row, "
        "so the ticks always line up (today they never do).",
        header("Checklist") + '<div class="pad"><div class="card"><h2>Shopping checklist</h2>' + busy_btn
        + stages(["done", "active", "", ""], "12 of 31") + '<div class="push-steps"><div class="step-list-vertical">' + sendrows + "</div></div></div></div>" + nav(),
    )
    s3 = scene(
        "3. Push — confirming",
        "The new real step: after the last item is sent, the app re-reads the AnyList list and checks every item is there, uncrossed, with the right amount. "
        "Nothing is called 'done' until this passes. Any retries happen here.",
        header("Checklist") + '<div class="pad"><div class="card"><h2>Shopping checklist</h2>' + busy_btn
        + stages(["done", "done", "active", ""]) + '<div class="push-steps"><div class="step-list-vertical">' + allsent + "</div></div>"
        + '<div class="push-note"><span class="spinner"></span> Checking AnyList has everything…</div></div></div>' + nav(),
    )
    ok_list = (
        '<ul class="result-list">'
        + '<li><span>Beef Mince</span><span class="chip-out uncrossed">un-crossed</span></li>'
        + '<li><span>Eggs</span><span class="chip-out updated">updated</span></li>'
        + '<li><span>Olive Oil</span><span class="chip-out added">added</span></li>'
        + '<li><span>Red Capsicums</span><span class="chip-out added">added</span></li>'
        + '<li><span>Salt</span><span class="chip-out">already there</span></li>'
        + '<li><span>Spring Onions</span><span class="chip-out">already there</span></li></ul>'
    )
    done_card = (
        '<div class="push-result"><span class="ico">✓</span><div class="body"><div class="title">31 on your list</div>'
        '<div class="sub">27 added · 3 updated (1 un-crossed) · 1 already there</div></div><button class="btn-link">Details ▾</button></div>'
    )
    s4 = scene(
        "4. Push — done (collapsed, then Details open)",
        "Replaces the 5-second toast. It stays until you leave the screen, and only appears after the read-back passed. Details lists every item with what happened to it "
        "('un-crossed' = it was ticked off on AnyList from last week and has been put back).",
        header("Checklist") + '<div class="pad"><div class="card"><h2>Shopping checklist</h2>' + done_card
        + '<div class="push-result" style="margin-top:var(--sp-3)"><span class="ico">✓</span><div class="body"><div class="title">31 on your list</div>'
        '<div class="sub">27 added · 3 updated (1 un-crossed) · 1 already there</div>' + ok_list + '</div><button class="btn-link">Hide ▴</button></div></div></div>' + nav(),
    )
    bad_list = (
        '<ul class="result-list">'
        + '<li><span>Red Capsicums</span><span class="chip-out failed">failed</span><span class="why">Not on the list after sending — AnyList ignored it 3 times.</span></li>'
        + '<li><span>Beef Mince</span><span class="chip-out failed">failed</span><span class="why">Quantity shows “1”, expected “500 g”.</span></li></ul>'
    )
    s5 = scene(
        "5. Push — some items need attention",
        "Never a green tick when something is missing. Failed items are named with the plain reason; everything else is already on the list. "
        "Try again re-reads the list and retries only the failed ones — no 'already pushed' prompt, no duplicates.",
        header("Checklist") + '<div class="pad"><div class="card"><h2>Shopping checklist</h2>'
        '<div class="push-result warn"><span class="ico">⚠️</span><div class="body"><div class="title">2 items need attention</div>'
        '<div class="sub">The other 29 are on your list.</div>' + bad_list
        + '<div class="actions"><button class="primary btn-sm">Try again</button><button class="btn-sm">Details ▾</button></div></div></div></div></div>' + nav(),
    )
    s6 = scene(
        "6. Push — couldn't reach AnyList",
        "If the very first read fails nothing has been changed, and it says so. Uses the existing error box (replaces the pop-up alert).",
        header("Checklist") + '<div class="pad"><div class="card"><h2>Shopping checklist</h2>' + push_btn
        + '<div class="error-state" style="margin-top:var(--sp-3)"><div><b>Couldn’t reach AnyList.</b><br>Nothing was changed. Check the connection and try again.'
        '<div class="actions" style="margin-top:8px"><button class="btn-sm primary">Try again</button></div></div></div></div></div>' + nav(),
    )
    diag_hist = (
        '<div class="push-history"><div class="hdr">Recent pushes</div>'
        '<div class="history-row open"><div class="history-head"><div class="main"><div class="name">Today 6:35 pm</div><div class="meta">31 lines · push 9d3a1c7e</div></div>'
        '<span class="status-pill attention">2 failed</span><span class="chev">›</span></div>'
        '<div class="history-body"><ul class="result-list">'
        '<li><span>Red Capsicums</span><span class="chip-out failed">failed</span><span class="why">Not on the list after sending (retried 2×)</span></li>'
        '<li><span>Beef Mince</span><span class="chip-out failed">failed</span><span class="why">Quantity shows “1”, expected “500 g”</span></li>'
        '<li><span>Eggs</span><span class="chip-out updated">updated</span></li>'
        '<li><span>Salt</span><span class="chip-out">already there</span></li></ul>'
        '<dl class="kv"><dt>Timings</dt><dd>read 0.6s · send 9.1s · confirm 1.2s</dd><dt>Log</dt><dd>grep 9d3a1c7e logs/app.log</dd></dl></div></div>'
        '<div class="history-row"><div class="history-head"><div class="main"><div class="name">Today 9:12 am</div><div class="meta">27 lines · push 41be07a2</div></div>'
        '<span class="status-pill confirmed">confirmed</span><span class="chev">›</span></div></div>'
        '<div class="history-row"><div class="history-head"><div class="main"><div class="name">Mon 3:02 pm</div><div class="meta">19 lines · push 7c20de19</div></div>'
        '<span class="status-pill confirmed">confirmed</span><span class="chev">›</span></div></div></div>'
    )
    s7 = scene(
        "7. Diagnostics — push history",
        "The AnyList row keeps its dot and message; below it, recent pushes with the per-item result. This is the first place to look for 'why didn't X arrive' "
        "(the push id ties it to the log lines). 'Check AnyList now' stays as today.",
        header("Diagnostics") + '<div class="pad"><div class="card"><h2>Component status</h2>'
        '<div class="status-row"><span class="dot red"></span><div class="status-body"><div class="status-name">AnyList connection</div>'
        '<div class="status-msg">Last push was not fully confirmed — 2 items need attention</div>'
        '<div class="status-msg">enabled: yes · list: TestList · creds: keyring</div>'
        '<div class="status-msg"><button class="btn-sm">Check AnyList now</button></div></div></div>' + diag_hist + '</div></div>' + nav("diag"),
    )
    s8 = scene(
        "8. Diagnostics — running build",
        "Answers 'is the NUC running the code I just deployed?' at a glance (and is what the update banner compares). Same status-row pattern as the others.",
        header("Diagnostics") + '<div class="pad"><div class="card"><h2>Component status</h2>'
        '<div class="status-row"><span class="dot green"></span><div class="status-body"><div class="status-name">Running build</div>'
        '<div class="status-msg">Started today 7:41 pm</div>'
        '<dl class="kv"><dt>Build</dt><dd>37ef218b7f12</dd><dt>Release</dt><dd>release-20261006-091500Z</dd><dt>Process</dt><dd>boot a6e4ac08d401</dd></dl></div></div></div></div>' + nav("diag"),
    )
    page(
        "push.html", "AnyList push — progress, result and Diagnostics",
        "Everything visible about the push. The behaviour behind it is already built and live-tested (docs/anylist-push.md); these screens are the part waiting for your approval.",
        [s1, s2, s3, s4, s5, s6, s7, s8],
    )


# ------------------------------------------------------------------------------------------
# BANNER page
# ------------------------------------------------------------------------------------------
def build_banner() -> None:
    page_body = (
        header("Recipes") + '<div class="pad"><h3>Recipes</h3><p class="muted">Search, filter and open a recipe…</p>'
        '<div class="card"><div class="recipe-row"><div class="recipe-row-main"><div class="recipe-row-name">Veg stir fry</div><div class="recipe-row-meta muted">4 servings</div></div></div></div></div>'
    )
    banner_ok = '<div class="update-banner" role="button"><span class="ico">🔄</span><span class="msg">Update available</span><span class="cta">Tap to refresh</span></div>'
    banner_fail = '<div class="update-banner" role="button"><span class="ico">🔄</span><span class="msg">Update didn’t load</span><span class="cta">Tap to try again</span></div>'
    covered = (
        '<div style="position:relative;height:0"><div class="update-banner" style="position:absolute;top:0;left:0;right:0;z-index:3" role="button">'
        '<span class="ico">🔄</span><span class="msg">Update available</span><span class="cta">Tap to refresh</span></div></div>' + page_body
    )
    s1 = compare(
        "1. Banner no longer covers the page title",
        "Today the banner is pinned over the top of the screen, hiding the header (“Recipes”). Now the page and its sticky header sit below it, and it is a proper 44px tap target. "
        "Same look and colours as today.",
        covered, banner_ok + page_body, theme="light",
    )
    s2 = scene(
        "2. 'Update didn't load' (new)",
        "If you tap and the new version somehow doesn't arrive (it should, now that the app tells the browser never to reuse stale files), it says so and offers another go — "
        "instead of silently reloading the old version forever.",
        banner_fail + page_body,
    )
    status = '<div class="statusbar"><span>6:37</span><span>▂▄▆ 99%</span></div>'
    s3 = scene(
        "3. On a phone with a status bar / notch",
        "The banner's top padding clears the status bar (it uses the device's safe-area inset), so the text is never under the clock or camera.",
        status + banner_ok + page_body, extra_class="phone-notch",
    )
    page(
        "banner.html", "Update banner",
        "Detection and delivery are rebuilt (see docs/deployment-and-operations.md); the only visual changes are the three below.",
        [s1, s2, s3],
    )


# ------------------------------------------------------------------------------------------
# POPUPS page
# ------------------------------------------------------------------------------------------
def build_popups() -> None:
    merge_rows = (
        '<div class="sub-group-heading">Ingredients <button class="btn-link" style="margin-left:auto">Cancel</button></div>'
        + row("parmesan", "35 g", merge_checked=True) + row("parmesans", "20 g", merge_checked=True) + row("pork tenderloin", "600 g", merge_checked=False)
        + '<div class="log-controls" style="margin-top:8px"><button class="btn-sm primary">Merge (2)</button></div>'
    )
    def merge_panel_core_fn(group: str) -> str:
        return (
            '<div class="inline-card"><div class="title">Merge these ingredients</div>'
            '<div class="merge-summary"><span class="name-chip">parmesans</span> + <span class="name-chip">parmesan</span> → <span class="name-chip keep">parmesan</span></div>'
            '<div class="merge-pick">Keep which name?</div>'
            f'<label class="radio-row"><input type="radio" name="{group}" checked> parmesan</label><label class="radio-row"><input type="radio" name="{group}"> parmesans</label>'
        )
    merge_panel_core = merge_panel_core_fn("k")
    link_collapsed = '<div class="meta-row"><button class="btn-link">Not the same amount? Set the equivalent</button></div>'
    link_open = (
        '<div class="meta-row"><button class="btn-link">Hide the amount equivalence</button></div>'
        '<div class="ing-grid" style="grid-template-columns:1fr 1fr"><div class="mini-field"><label>This amount</label><input value="1"></div><div class="mini-field"><label>Unit</label><input value="tbsp"></div>'
        '<div class="mini-field"><label>= Kept amount</label><input value="5"></div><div class="mini-field"><label>Unit</label><input value="g"></div></div>'
    )
    merge_buttons = (
        '<div class="actions"><button class="primary">Merge for this shopping list only</button>'
        '<button>Merge every time — all future recipes</button></div>'
        '<div class="fine">Every time: any future recipe that says “parmesans” will list it as “parmesan”. You can undo this any time in Settings → Ingredient groups.</div>'
        '<div class="actions row" style="margin-top:var(--sp-2)"><button class="btn-sm">Cancel</button></div>'
    )
    s1 = scene(
        "1. Merge — pick the items",
        "Unchanged from today (checkboxes on the rows, 'Merge (2)' once two are ticked).",
        header("Checklist") + '<div class="pad"><div class="card"><h2>Shopping checklist</h2>' + merge_rows + "</div></div>" + nav(),
    )
    s2 = scene(
        "2. Merge — the new panel (replaces the browser pop-up)",
        "Says what will happen in words: which names are being merged and which one survives. The two buttons are the choice itself — no OK/Cancel. "
        "Choosing 'every time' states plainly that it applies to all future recipes and where to undo it.",
        header("Checklist") + '<div class="pad"><div class="card"><h2>Shopping checklist</h2>' + merge_rows + merge_panel_core + link_collapsed + merge_buttons + "</div></div></div>" + nav(),
    )
    s3 = scene(
        "3. Merge — with an amount equivalence",
        "Optional: 'not the same amount' reveals the four fields (as today). The summary and buttons stay the same.",
        header("Checklist") + '<div class="pad"><div class="card"><h2>Shopping checklist</h2>' + merge_panel_core + link_open + merge_buttons + "</div></div></div>" + nav(),
    )
    s4 = scene(
        "4. Merge — a problem is shown inside the panel",
        "e.g. the name is already grouped elsewhere. Plain words, next to the buttons, no alert box.",
        header("Checklist") + '<div class="pad"><div class="card"><h2>Shopping checklist</h2>' + merge_panel_core + link_collapsed + merge_buttons
        + '<div class="form-error" role="alert" style="margin-top:8px">“parmesans” is already grouped under “parmesan” (Settings → Ingredient groups). Choose a different name to keep.</div></div></div></div>' + nav(),
    )
    s5 = scene(
        "5. After merging — Undo",
        "One tap puts it back (this list only: removes the merge; every time: also removes the saved group). The toast now wraps and says exactly what happened.",
        header("Checklist") + '<div class="pad"><div class="card"><h2>Shopping checklist</h2>' + row("parmesan", "55 g", "need") + row("pork tenderloin", "600 g")
        + '</div></div><div class="toast-static"><div class="toast" role="status"><span>Merged into “parmesan” — every time</span><button>Undo</button></div></div>'
        '<div class="toast-static" style="padding-top:0"><div class="toast" role="status"><span>Merged into “parmesan” — this list only</span><button>Undo</button></div></div>' + nav(),
    )
    s6 = scene(
        "6. 'Already pushed — push again?' (replaces the pop-up)",
        "An inline card above the button, in plain words, with buttons that say what they do.",
        header("Checklist") + '<div class="pad"><div class="card"><h2>Shopping checklist</h2><div class="muted">31 ingredient(s) will go on the list.</div>'
        '<div class="sticky-actions"><button class="primary btn-block">Push to AnyList</button></div>'
        '<div class="inline-card warn"><div class="title">Already pushed to AnyList</div><div class="body">Pushing again checks the list and only changes what’s different — items already there are left alone.</div>'
        '<div class="actions row"><button class="primary btn-sm">Push again</button><button class="btn-sm">Not now</button></div></div></div></div>' + nav(),
    )
    s7 = scene(
        "7. 'No shopping session yet — start one?' (replaces the pop-up)",
        "Appears right under the '+ Add to session' button it came from (shown in the recipe list and on the recipe page).",
        header("Recipes") + '<div class="pad"><div class="card">'
        '<div class="recipe-row"><div class="recipe-row-main"><div class="recipe-row-name">Veg stir fry</div><div class="recipe-row-meta muted">4 servings</div></div><button class="btn-sm">+ Add to session</button></div>'
        '<div class="inline-card"><div class="title">No shopping session yet</div><div class="body">Start one with “Veg stir fry” in it?</div>'
        '<div class="actions row"><button class="primary btn-sm">Start one with this recipe</button><button class="btn-sm">Not now</button></div></div></div>'
        '<div class="card"><div class="detail-head-row"><h2>Veg stir fry</h2><button class="btn-sm">Edit</button><button class="btn-sm">+ Add to session</button></div>'
        '<div class="inline-card"><div class="title">No shopping session yet</div><div class="body">Start one with “Veg stir fry” in it?</div>'
        '<div class="actions row"><button class="primary btn-sm">Start one with this recipe</button><button class="btn-sm">Not now</button></div></div></div></div>' + nav("recipes"),
    )
    s8 = scene(
        "8. Errors — four patterns replace every alert()",
        "Where an error appears depends on where you were: (a) on the row you tapped, (b) next to the button, (c) a box in place when the whole thing failed, "
        "(d) a toast with Retry when the thing you tapped is already gone (e.g. an Undo that failed). All wrap, all readable, none block the screen.",
        header("Examples") + '<div class="pad">'
        '<h3>a) On the row</h3><div class="card">' + row("eggs", "8", "need")
        + '<div class="form-error" role="alert" style="margin:0 0 4px 0">Couldn’t save — AnyList wasn’t reached. Tap again to retry.</div></div>'
        '<h3>b) Next to the button</h3><div class="card"><div class="log-controls"><button class="btn-sm primary">use this</button><span class="form-error" role="alert">Enter an amount greater than 0.</span></div></div>'
        '<h3>c) Box in place</h3><div class="error-state"><div><b>Couldn’t restore the recipe.</b> It may already be gone.<div class="actions" style="margin-top:8px"><button class="btn-sm primary">Retry</button></div></div></div>'
        '</div><div class="toast-static"><div class="toast error" role="alert"><span>Couldn’t restore “olive oil” — the server didn’t answer.</span><button>Retry</button></div></div>' + nav(),
    )
    s9 = scene(
        "9. Settings → Ingredient groups — where a group came from",
        "A small tag shows whether a group is built in, came from a checklist merge, or was typed in by hand (no tag). Delete and Undo work as today, so a learned merge is "
        "reviewable and reversible here. Session-only merges never appear here — they only last for that shopping list (and have Undo right after).",
        header("Settings") + '<div class="pad"><div class="card"><h2>Ingredient groups</h2>'
        '<div class="settings-group-card"><div class="settings-group-head"><span class="settings-group-name">parmesan</span><span class="settings-group-count">1 alias</span></div>'
        '<div class="settings-group-row"><div class="mini-field"><label>Ingredient name (fixed — delete and re-add to rename)</label><div style="display:flex;gap:8px;align-items:center"><input disabled value="parmesans" style="flex:1"><span class="source-tag merge">from a checklist merge</span></div></div>'
        '<div class="settings-row-actions-line"><button class="btn-link-danger">Delete</button><button class="btn-sm primary">Save</button></div></div></div>'
        '<div class="settings-group-card"><div class="settings-group-head"><span class="settings-group-name">canned tomato</span><span class="settings-group-count">2 aliases</span></div>'
        '<div class="settings-group-row"><div class="mini-field"><label>Ingredient name (fixed — delete and re-add to rename)</label><div style="display:flex;gap:8px;align-items:center"><input disabled value="diced tomato" style="flex:1"><span class="source-tag system">built-in</span></div></div></div>'
        '<div class="settings-group-row"><div class="mini-field"><label>Ingredient name (fixed — delete and re-add to rename)</label><input disabled value="crushed tomato"></div></div></div></div></div>' + nav("settings"),
    )
    page(
        "popups.html", "No native pop-ups — inline questions and errors",
        "Rule going forward: no browser dialogs; buttons say what they do (never OK/Cancel). 3 confirm() boxes and 22 alert() boxes are replaced by the patterns below.",
        [s1, s2, s3, s4, s5, s6, s7, s8, s9],
    )


# ------------------------------------------------------------------------------------------
# NAMES page
# ------------------------------------------------------------------------------------------
def build_names() -> None:
    before = (
        header("Checklist") + '<div class="pad"><div class="card">'
        + row("paprika", "1 tsp", "have") + row("parmesans", "35 g", "have") + row("pork tenderloin", "600 g", "need", on_list=True)
        + row("rice vermicelli noodle", "150 g", "need", on_list=True) + row("salts", "2 tsp", "have") + row("salted peanut", "8 tbsp", "have")
        + row("vegetable oils", "4 tbsp") + row("black bean", "800 g") + "</div></div>" + nav()
    )
    after = (
        header("Checklist") + '<div class="pad"><div class="card">'
        + row("paprika", "1 tsp", "have") + row("parmesan", "35 g", "have") + row("pork tenderloin", "600 g", "need", on_list=True)
        + row("rice vermicelli noodles", "150 g", "need", on_list=True) + row("salt", "2 tsp", "have") + row("salted peanuts", "8 tbsp", "have")
        + row("vegetable oil", "4 tbsp") + row("black beans", "800 g") + "</div></div>" + nav()
    )
    s1 = compare(
        "1. The checklist — names use your recipes' own wording",
        "No more 'salts', 'parmesans', 'vegetable oils', and no more 'black bean', 'salted peanut'. The name shown is the form your own recipes use for that ingredient "
        "(e.g. your recipes say “black beans” and “salt”). Nothing stored changes, and nothing about matching changes.",
        before, after,
    )
    al_before = (
        '<div class="al"><div class="top"><b>TestList</b><span>31 of 33 items remaining</span></div>'
        '<div class="item sub">Sesame Oil <small>(8.5 tbsp)</small></div><div class="item">Unsalted Cashew Nut <small>(175 g)</small></div>'
        '<div class="item">Black Bean <small>(800 g)</small></div><div class="item">Broccoli Floret <small>(5 cup)</small></div>'
        '<div class="item sub">Cheddar Cheese <span class="bad">Or</span> Monterey Jack <small>(200 g)</small></div><div class="item">Corn Chip <small>(300 g)</small></div>'
        '<div class="item">Bachelor<span class="bad">S</span> Handbag</div></div>'
    )
    al_after = (
        '<div class="al"><div class="top"><b>TestList</b><span>31 of 33 items remaining</span></div>'
        '<div class="item sub">Sesame Oil <small>(8.5 tbsp)</small></div><div class="item">Unsalted Cashew Nuts <small>(175 g)</small></div>'
        '<div class="item">Black Beans <small>(800 g)</small></div><div class="item">Broccoli Florets <small>(5 cup)</small></div>'
        '<div class="item sub">Cheddar Cheese <span class="good">or</span> Monterey Jack <small>(200 g)</small></div><div class="item">Corn Chips <small>(300 g)</small></div>'
        '<div class="item">Bachelor’s Handbag</div></div>'
    )
    s2 = compare(
        "2. What lands on AnyList",
        "Same wording as the checklist, and small words (or, and, of, with…) stay lowercase and apostrophes are right (“Bachelor’s”, not “Bachelor’S”). "
        "(Illustrative imitation of the AnyList app.)",
        al_before, al_after,
    )
    page(
        "names.html", "Ingredient names — plural/singular and capitalisation",
        "Wording only; no layout changes. Examples are the ones from your screenshots.",
        [s1, s2],
    )


def build_index() -> None:
    html = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Chunk 6.7 mockups</title>
<style>body{font-family:system-ui,sans-serif;max-width:760px;margin:40px auto;padding:0 16px;color:#2a2620;line-height:1.5}
a{color:#1f6b63}.card{background:#fff;border:1px solid #0002;border-radius:12px;padding:14px 18px;margin:12px 0}</style></head><body>
<h1>Chunk 6.7 — mockups for approval</h1>
<p>Static light/dark mockups using the app's real stylesheets (<code>static/css/</code>) plus <code>proposed.css</code> (the new components). Each screen is shown in
light and dark. Nothing here is built yet except where noted — approve (or mark up) each page and I'll implement exactly this.</p>
<div class="card"><h3><a href="push.html">1. AnyList push — progress, result, Diagnostics</a></h3>
<p>Reading → Sending → <b>Confirming</b> → Done tracker (terse), a result card that only appears after the read-back passes, a clear "needs attention" state with
reasons, and per-item push history + running build on Diagnostics. <i>Behaviour already built and live-tested.</i></p></div>
<div class="card"><h3><a href="banner.html">2. Update banner</a></h3><p>Doesn't cover the page title any more, handles phone status bars, and a new honest "Update didn't load" state.</p></div>
<div class="card"><h3><a href="popups.html">3. No native pop-ups</a></h3><p>The merge panel (with the two clearly-labelled buttons), "push again", "start a session", the four error patterns, undo, and source tags in Settings.</p></div>
<div class="card"><h3><a href="names.html">4. Ingredient names</a></h3><p>Before/after for the checklist and for AnyList, from your screenshots.</p></div>
<p>Regenerate after any change: <code>.venv\\Scripts\\python docs\\mockups\\chunk-6.7\\build_mockups.py</code></p></body></html>"""
    (HERE / "index.html").write_text(html, encoding="utf-8")


if __name__ == "__main__":
    build_push()
    build_banner()
    build_popups()
    build_names()
    build_index()
    print("wrote", ", ".join(sorted(p.name for p in HERE.glob("*.html"))))
