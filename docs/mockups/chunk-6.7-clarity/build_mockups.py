"""Generates the Chunk 6.7 "plain language & no ambiguity" mockups (static HTML, light + dark).

    .venv\\Scripts\\python docs\\mockups\\chunk-6.7-clarity\\build_mockups.py

Open docs/mockups/chunk-6.7-clarity/index.html. Reuses the frame/scene helpers and the real
stylesheets from ../chunk-6.7/build_mockups.py (so the screens look like the app). Wording is the
point: every "After" is the exact text proposed for the app, checked against what the code really
does (docs/ui-ux.md > Plain language & no ambiguity). Static by design (standing mockup rule).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
_base_path = HERE.parent / "chunk-6.7" / "build_mockups.py"
_spec = importlib.util.spec_from_file_location("chunk67_base", _base_path)
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)

frame, scene, compare, header, nav = base.frame, base.scene, base.compare, base.header, base.nav

EXTRA_CSS = """
.frame .pad { padding: var(--sp-4); }
.frame .hint { font-size: var(--text-sm); color: var(--text-dim); margin: var(--sp-1) 0 var(--sp-3); }
.frame .preview { font-size: var(--text-sm); border-left: 3px solid var(--accent); padding: var(--sp-2) var(--sp-3);
  background: var(--surface-2, transparent); margin: var(--sp-3) 0; }
.frame .dir { text-align: center; color: var(--text-dim); font-size: var(--text-sm); margin: var(--sp-1) 0; }
.frame .sentence { display: flex; flex-wrap: wrap; align-items: center; gap: var(--sp-2); margin: var(--sp-2) 0; font-size: var(--text-sm); }
.frame .sentence input { width: 4.2rem; }
.frame .tag-on { font-size: var(--text-xs, 12px); border: 1px solid var(--success); color: var(--success); border-radius: 999px; padding: 0 var(--sp-2); margin-left: var(--sp-2); white-space: nowrap; }
.frame .box { border: 1px solid var(--border); border-radius: var(--r-md); padding: var(--sp-3); margin: var(--sp-3) 0; }
.frame .section-list a { display: flex; justify-content: space-between; align-items: flex-start; padding: var(--sp-3) var(--sp-4); border-bottom: 1px solid var(--border); text-decoration: none; color: var(--text); }
.frame .section-list .sub { display: block; font-size: var(--text-sm); color: var(--text-dim); font-weight: 400; }
.frame .section-list .count { white-space: nowrap; }
.frame .section-list .name { font-weight: 600; }
.frame .h3s { margin: 0 0 var(--sp-2); }
.frame .row-line { display: flex; justify-content: space-between; gap: var(--sp-3); padding: var(--sp-2) 0; border-bottom: 1px solid var(--border); font-size: var(--text-sm); }
"""


def page(name: str, title: str, lede: str, scenes: list[str]) -> None:
    theme = base._theme_css()
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="../../../static/css/components.css"><link rel="stylesheet" href="../../../static/css/components-screens.css">
<link rel="stylesheet" href="../../../static/css/app.css"><link rel="stylesheet" href="../chunk-6.7/proposed.css">
<style>{theme}{base.PAGE_CSS}{EXTRA_CSS}</style></head><body><div class="mock-wrap">
<p class="nav-links"><a href="index.html">&larr; All clarity mockups</a><a href="settings.html">Settings</a><a href="checklist.html">Checklist &amp; push</a><a href="plan-recipes.html">Plan, recipes, status</a></p>
<h1 class="mock">{title}</h1><p class="lede">{lede}</p>{"".join(scenes)}</div></body></html>"""
    (HERE / name).write_text(html, encoding="utf-8")


def mini(label: str, value: str = "", ph: str = "") -> str:
    v = f' value="{value}"' if value else ""
    p = f' placeholder="{ph}"' if ph else ""
    return f'<div class="mini-field"><label>{label}</label><input type="text"{v}{p}></div>'


def wrap(inner: str, title: str = "Settings", active: str = "settings") -> str:
    return header(title) + f'<div class="pad">{inner}</div>' + nav(active)


# ---------------------------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------------------------
def build_settings() -> None:
    def index(after: bool) -> str:
        def row(name: str, count: str, sub: str = "") -> str:
            s = f'<span class="sub">{sub}</span>' if (after and sub) else ""
            return f'<a><span class="name">{name}{s}</span><span class="count muted">{count}</span></a>'
        if after:
            rows = (
                row("Appearance", "Match my phone", "Light, dark, or follow your phone. Only this phone.")
                + row("Pack sizes", "27 saved", "How each ingredient is sold, e.g. eggs by the dozen")
                + row("Saved ingredient swaps", "3 saved", "‘Buy this instead’ suggestions offered when you review a recipe")
                + row("Regular items", "5 saved", "Things you buy every few days or weeks")
                + row("Same item, different names", "4 saved", "A name in a recipe that should show as another name on your list")
                + row("Unit spellings", "6 saved", "e.g. tablespoon is the same as tbsp")
                + row("Bought by the bunch", "2 saved", "Items where you just count recipes, not amounts")
            )
        else:
            rows = (
                row("Appearance", "System") + row("Product units", "27") + row("Substitutions", "3") + row("The usuals", "5")
                + row("Ingredient groups", "4") + row("Unit spellings", "6") + row("Coarse ingredients", "2")
            )
        return wrap('<h3 class="h3s">Settings</h3><div class="card" style="padding:0"><div class="section-list">' + rows + "</div></div>")

    s1 = compare(
        "1. Settings index — say what each section is for",
        "Each section gets a one-line purpose and the number says what it counts. One name per feature (the page used to be called "
        "“Substitutions” in the list and “Saved ingredient swaps” inside; “Ingredient groups”, “Coarse” and “Product units” were jargon).",
        index(False), index(True),
    )

    def alias_form(after: bool) -> str:
        if not after:
            return wrap(
                '<div class="card"><h3>Ingredient groups</h3>'
                '<p class="muted">Ingredients that are the same thing to you, shown as one line on the shopping list — e.g. “canola oil” and “oil spray” '
                'grouped under “vegetable oil”, or “lemon juice” grouped under “lemon” with an optional amount conversion…</p>'
                '<h4>Add a new group</h4>' + mini("Ingredient name", ph="e.g. lemon juice") + '<div class="muted">=</div>'
                + mini("Same shopping item as", ph="e.g. lemon") + mini("Note", ph="optional")
                + '<div class="ing-grid" style="grid-template-columns:repeat(4,1fr)">'
                + mini("Alias amount") + mini("Alias unit") + mini("= Canonical amount") + mini("Canonical unit (blank = count)")
                + '</div><button class="btn-sm primary">Group these</button></div>'
            )
        return wrap(
            '<div class="card"><h3>Same item, different names</h3>'
            '<p class="hint">When a recipe uses the name on the left, your shopping list shows the name on the right instead. '
            "Recipes themselves aren’t changed. Applies to every recipe, existing and new.</p>"
            '<h4>Add one</h4>'
            + mini("When a recipe says", ph="e.g. lemon juice")
            + '<div class="dir">↓ show it on my shopping list as</div>'
            + mini("Shopping list shows", ph="e.g. lemon")
            + '<div class="box"><b>Change the amount too? (optional)</b>'
            '<div class="sentence"><input type="text" placeholder="3"> <input type="text" placeholder="tbsp"> <span>of the first =</span> '
            '<input type="text" placeholder="1"> <input type="text" placeholder="(whole)"> <span>of the second</span></div>'
            '<div class="hint">Only used when a recipe measures it in exactly that unit. Otherwise just the name changes and the amount is left as written. '
            "Leave all four blank to only rename. Leave the last unit blank for whole items.</div></div>"
            '<div class="preview">“lemon juice” in a recipe will show as “lemon” on your shopping list. 3 tbsp lemon juice becomes 1 lemon.</div>'
            '<button class="btn-sm primary">Save this name group</button></div>'
        )

    s2 = compare(
        "2. Settings → add a name group — the alias form from your note",
        "Direction is stated in words (“When a recipe says … show it as …”), the two amounts are one readable sentence, the unit rule is explained "
        "where it applies, and a live preview sentence says exactly what will happen. Half-filled amounts show an inline “fill both or leave blank” "
        "instead of silently being thrown away.",
        alias_form(False), alias_form(True),
    )

    def group_card(after: bool) -> str:
        if not after:
            return wrap(
                '<div class="card settings-group-card"><div class="settings-group-head"><span class="settings-group-name">lemon</span>'
                '<span class="settings-group-count">2 aliases</span></div>'
                '<div class="settings-group-row">' + mini("Ingredient name (fixed — delete and re-add to rename)", "lemon juice")
                + '<span class="muted">from a checklist merge</span>' + mini("Note", ph="optional") + '<b>Amount conversion (optional)</b>'
                + '<div class="log-controls"><button class="btn-link-danger">Delete</button><button class="btn-sm primary">Save</button></div></div></div>'
            )
        return wrap(
            '<div class="card settings-group-card"><div class="settings-group-head"><span class="settings-group-name">Shown as “lemon”</span>'
            '<span class="settings-group-count">2 names fold into it</span></div>'
            '<div class="settings-group-row"><b>“lemon juice” → “lemon”</b>'
            '<div class="hint">Added from a shopping-list merge. 3 tbsp = 1 whole (only when the recipe says tbsp).</div>'
            + mini("Note to self (only shown here)", ph="optional")
            + '<div class="log-controls"><button class="btn-link-danger">Remove</button><button class="btn-sm primary">Save changes</button></div></div></div>'
            '<div class="toast-static"><div class="toast">Removed “lemon juice”. It will show as itself again. <b>Undo</b></div></div>'
        )

    s3 = compare(
        "3. Existing groups — name the direction and the consequence",
        "The heading says what the list shows; each row reads “recipe name → list name”; Delete says what it does and how to undo it; Save says it applies "
        "everywhere immediately. “merge”/“system” tags become plain sentences.",
        group_card(False), group_card(True),
    )

    def unit_form(after: bool) -> str:
        if not after:
            return wrap('<div class="card"><h3>Unit spellings</h3><p class="muted">Units that are the same measurement, just spelled differently…</p>'
                        + mini("Unit as typed", ph="e.g. tablespoon") + '<div class="muted">=</div>' + mini("Same unit as", ph="e.g. tbsp")
                        + '<button class="btn-sm primary">Treat as the same unit</button></div>')
        return wrap('<div class="card"><h3>Unit spellings</h3><p class="hint">When a recipe uses the unit on the left, your shopping list counts it as the unit on the right. '
                    "Plain plurals (clove / cloves) are already handled.</p>"
                    + mini("When a recipe says", ph="e.g. tablespoon") + '<div class="dir">↓ count it as</div>' + mini("Count it as", ph="e.g. tbsp")
                    + '<div class="preview">“2 tablespoon” in a recipe will be counted as “2 tbsp”.</div>'
                    '<button class="btn-sm primary">Save this spelling</button></div>')

    s4 = compare("4. Unit spellings — same convention", "Same left → right wording as the name groups, so the three forms read alike.",
                 unit_form(False), unit_form(True))

    def swap_form(after: bool) -> str:
        if not after:
            return wrap('<div class="card"><h3>Saved ingredient swaps</h3><p class="muted">Swaps you’ve saved for hard-to-find ingredients. These never apply on their own…</p>'
                        + mini("Hard-to-find ingredient", ph="e.g. bulgarian feta") + '<div class="muted">→</div>' + mini("Buy instead", ph="e.g. regular feta")
                        + '<div class="ing-grid" style="grid-template-columns:repeat(4,1fr)">' + mini("Original amount") + mini("Original unit")
                        + mini("Substitute amount") + mini("Substitute unit") + '</div><button class="btn-sm primary">Save swap</button></div>')
        return wrap('<div class="card"><h3>Saved ingredient swaps</h3><p class="hint">“Buy this instead” choices you’ve saved. They are never applied automatically — '
                    "when you review a recipe or edit an ingredient they’re offered as a one-tap suggestion. "
                    "For a name that’s just the same item written differently, use “Same item, different names”.</p>"
                    + mini("If a recipe calls for", ph="e.g. bulgarian feta") + '<div class="dir">↓ buy this instead</div>' + mini("Buy this instead", ph="e.g. regular feta")
                    + '<div class="box"><b>How much? (optional)</b><div class="sentence"><input placeholder="2"> <input placeholder="can"> <span>of the original =</span> '
                    '<input placeholder="350"> <input placeholder="g"> <span>of the replacement</span></div>'
                    '<div class="hint">Fill in all four, or leave all four blank to keep the amount as written.</div></div>'
                    '<button class="btn-sm primary">Save this swap</button></div>')

    s5 = compare("5. Saved swaps — same convention", "Same shape again: original → replacement, with the amount ratio as a sentence.",
                 swap_form(False), swap_form(True))

    def packs(after: bool) -> str:
        if not after:
            return wrap('<div class="card"><h3>Product units</h3><p class="muted">How each ingredient is actually bought, e.g. eggs as a dozen. Used to turn a scaled quantity into a shopping-list amount…</p>'
                        + mini("Pack label", ph="e.g. 500g tub") + mini("Pack quantity", ph="500") + mini("Unit", ph="g") + '<button class="btn-sm primary">Add</button></div>')
        return wrap('<div class="card"><h3>Pack sizes</h3><p class="hint">The sizes you buy each ingredient in. Your list then says “2 × 500g tub” instead of “900 g”.</p>'
                    + mini("Ingredient (as written in your recipes)", ph="e.g. cottage cheese") + mini("Pack name (as you’d say it)", ph="e.g. 500g tub")
                    + mini("Amount in one pack", ph="500") + mini("Unit (g, kg, ml, l, cup, tbsp, tsp — blank for a count)", ph="g")
                    + '<div class="hint">Use the unit your recipes use. Other units only match a recipe that uses exactly that word.</div>'
                    '<button class="btn-sm primary">Add this pack size</button></div>')

    s6 = compare("6. Pack sizes (was “Product units”)", "Jargon out; the unit hint says which units actually match, because anything else was silently ignored.",
                 packs(False), packs(True))

    page("settings.html", "Settings — plain language",
         "Every Settings form that defines a rename, swap or conversion now reads left → right in words, with a live preview and a stated scope.",
         [s1, s2, s3, s4, s5, s6])


# ---------------------------------------------------------------------------------------------
# Checklist & push
# ---------------------------------------------------------------------------------------------
def checklist_row(name: str, meta: str, state: str = "", on_list: bool = False, caret: bool = True) -> str:
    have = ' aria-pressed="true"' if state == "have" else ""
    need = ' aria-pressed="true"' if state == "need" else ""
    tag = '<span class="tag-on">On AnyList</span>' if on_list else ""
    c = " ▾" if caret else ""
    return (
        f'<div class="checklist-row"><div class="main"><div class="name">{name}{c}{tag}</div><div class="meta">{meta}</div></div>'
        f'<div class="have-need-pair"><button class="have-need-btn have"{have}>Have it</button><button class="have-need-btn need"{need}>Need it</button></div></div>'
    )


def build_checklist() -> None:
    def top(after: bool) -> str:
        if after:
            head = ('<div class="sync-note"><span class="sync-dot"></span>Checked against AnyList when this page opened. Items already on your AnyList '
                    "are set to “Have it”, so they won’t be sent again.</div>"
                    '<div class="hint">Tap “Need it” for what you want sent to AnyList. “Have it” skips it. A row you don’t tap is not sent.</div>')
            rows = (checklist_row("Cottage cheese", "Buy 2 × 500g tub · recipes need 800 g", "need")
                    + checklist_row("Milk", "2 L", "have", on_list=True) + checklist_row("Lime", "5"))
            push = '<div class="muted">2 ingredients and 1 regular item will be sent to AnyList. 1 ingredient still needs an amount chosen (under “Needs review”).</div>'
        else:
            head = ('<div class="sync-note"><span class="sync-dot"></span>Checked against AnyList as of this page load — items already on the list are pre-ticked.</div>')
            rows = (checklist_row("Cottage cheese", "2 × 500g tub · need ~800 g", "need")
                    + checklist_row("Milk ✓", "2 L", "have") + checklist_row("Lime", "5"))
            push = '<div class="muted">2 ingredient(s) + 1 of 2 usual(s) selected will go on the list.</div>'
        return (header("Checklist") + '<div class="pad"><div class="card"><h2>Shopping checklist</h2>' + head
                + '<div class="sub-group-heading">Ingredients</div>' + rows + push
                + '<div class="sticky-actions"><button class="primary btn-block">' + ("Send 3 items to AnyList" if after else "Push to AnyList") + "</button></div></div></div>"
                + nav("plan"))

    s1 = compare("1. Checklist — what the buttons do and what gets sent",
                 "Nothing on screen said that a row you don’t tap isn’t sent, that the ✓ means “already on AnyList”, or what “~” and “2 × …” were. "
                 "Now: one helper line, an “On AnyList” tag, “Buy … · recipes need …”, and a push line in plain words. "
                 "Push is disabled with nothing to send (“Mark something as Need it first”).",
                 top(False), top(True))

    def panel(after: bool) -> str:
        chips = ("Pack size", "Substitute", "Alias", "Coarse item", "Merge") if not after else (
            "How it’s sold", "Swap for another", "Same as another name", "Buy by the bunch", "Combine with another row")
        scope = ("This list only", "Always (edits Settings)") if not after else ("Just this plan", "Always — every plan (saved in Settings → Same item, different names)")
        sub = ("Always for this recipe",) if not after else ("Always (saves a suggestion for next time — doesn’t change this list)",)
        chip_html = "".join(f'<button class="btn-sm">{c}</button> ' for c in chips)
        return (header("Checklist") + '<div class="pad"><div class="card">'
                + checklist_row("Greek yoghurt", "500 g", "need") + '<div class="log-controls">' + chip_html + "</div>"
                + ('<div class="swap-panel"><div class="hdr">Substitute this ingredient</div>' if not after else
                   '<div class="swap-panel"><div class="hdr">Use something else instead of “Greek yoghurt”</div>')
                + mini("Use instead" if not after else "Use this instead") + '<div class="persist-toggle"><button class="persist-btn on">' + scope[0]
                + '</button><button class="persist-btn">' + scope[1] + "</button></div>"
                + ('<div class="persist-toggle"><button class="persist-btn">' + sub[0] + "</button></div>")
                + ('<div class="hint">“Just this plan” changes this checklist only. “Always” saves a suggestion in Settings → Saved ingredient swaps; it never changes a recipe or this list by itself.</div>'
                   if after else "")
                + '<button class="btn-sm primary">Save</button></div></div></div>' + nav("plan"))

    s2 = compare("2. Ingredient panel — plain chip names and a true scope label",
                 "“Always for this recipe” was false (it only saves a suggestion; nothing changes). Chip names drop “Alias” and “Coarse item”, and every "
                 "“Always” says where it is saved.", panel(False), panel(True))

    def merge(after: bool) -> str:
        if not after:
            body = ('<div class="title">Merge these ingredients</div><div class="muted">parmesans + parmesan → parmesan</div>'
                    + mini("Keep which name?") + '<a class="btn-link">Not the same amount? Set the equivalent</a>'
                    '<div class="ing-grid" style="grid-template-columns:repeat(4,1fr)">' + mini("This amount") + mini("Unit") + mini("= Kept amount")
                    + mini("Unit (blank = count)") + '</div><button class="primary">Merge for this shopping list only</button>'
                    '<button>Merge every time — all future recipes</button>')
        else:
            body = ('<div class="title">Combine these into one ingredient</div>'
                    '<div class="muted">“parmesans” and “parmesan” → shown as <b>“parmesan”</b>. Amounts are added together. '
                    "If they’re in different kinds of unit you’ll be asked how to count them.</div>"
                    + mini("Show the combined item as") + '<a class="btn-link">Different measures? Tell us how they compare</a>'
                    '<div class="sentence"><input placeholder="1"> <input placeholder="tbsp"> <span>of each other item =</span> <input placeholder="0.5"> '
                    '<input placeholder="(whole)"> <span>of “parmesan”</span></div>'
                    '<div class="hint">Only used for lines measured in that unit; the others are added as they are.</div>'
                    '<button class="primary">Combine for this plan only</button><button>Always combine — in every plan and recipe</button>'
                    '<div class="hint">“Always” is saved in Settings → Same item, different names, where you can remove it.</div>')
        return header("Checklist") + '<div class="pad"><div class="inline-card">' + body + "</div></div>" + nav("plan")

    s3 = compare("3. Combining rows — which name wins, what happens to the amounts",
                 "States the direction, that amounts are added, what the ratio does and when it doesn’t apply (the app now also reports the lines it skipped).",
                 merge(False), merge(True))

    def review(after: bool) -> str:
        if not after:
            return (header("Checklist") + '<div class="pad"><div class="card"><div class="sub-group-heading">Needs review — pick one amount</div>'
                    '<div class="checklist-row"><div class="main"><div class="name">Cream</div><div class="meta">100 g + 200 ml</div></div></div>'
                    '<div class="log-controls"><button class="btn-sm">use 100 g</button><button class="btn-sm">use 200 ml</button></div></div></div>' + nav("plan"))
        return (header("Checklist") + '<div class="pad"><div class="card"><div class="sub-group-heading">Different units — choose how much to buy</div>'
                '<div class="checklist-row"><div class="main"><div class="name">Cream</div><div class="meta">Recipes need 100 g and 200 ml — these can’t be added together</div></div></div>'
                '<div class="log-controls"><button class="btn-sm">Buy 100 g</button><button class="btn-sm">Buy 200 ml</button><button class="btn-sm primary">Buy all of them</button></div>'
                '<div class="hint">“Buy all of them” keeps both amounts in the AnyList note. Picking one drops the other.</div></div></div>' + nav("plan"))

    s4 = compare("4. Needs review — nothing is forced to be thrown away", "New “Buy all of them” (built); clearer heading and button names.",
                 review(False), review(True))

    def push_again(after: bool) -> str:
        if not after:
            t = ("Already pushed to AnyList", "Pushing again checks the list and only changes what’s different — items already there are left alone.", "Push again", "Not now")
        else:
            t = ("Already sent to AnyList",
                 "Sending again checks AnyList and only changes what’s different. Items already there with the same amount are left alone; an item whose amount "
                 "is different has its amount replaced; and anything you’ve crossed off on AnyList that is still marked Need it is put back on the list.",
                 "Send again", "Not now")
        return (header("Checklist") + '<div class="pad"><div class="inline-card warn"><div class="title">' + t[0] + "</div><div>" + t[1]
                + '</div><div class="log-controls"><button class="primary">' + t[2] + "</button><button>" + t[3] + "</button></div></div>"
                '<div class="usual-card skipped"><div class="q">Milk — you restock this every 7 days</div>'
                + ('<div class="skipped-note">Added to this session’s push.</div>' if not after else
                   '<div class="skipped-note">Will be sent to AnyList when you tap Send. <a class="btn-link">Undo</a></div>')
                + "</div></div>" + nav("plan"))

    s5 = compare("5. “Push again” and the regular-items card", "The old text left out that crossed-off items come back and amounts are replaced — both true of the code. "
                 "Regular items get an Undo and say when they’re sent.", push_again(False), push_again(True))

    page("checklist.html", "Checklist & push — plain language",
         "Wording and small markup only; no new screens. Every statement here was checked against the push/consolidation code.",
         [s1, s2, s3, s4, s5])


# ---------------------------------------------------------------------------------------------
# Plan, recipes, status
# ---------------------------------------------------------------------------------------------
def build_plan_recipes() -> None:
    def home(after: bool) -> str:
        a = ("Start a new shopping plan", "Add or find a recipe") if after else ("New session", "New recipe")
        return (header("Home") + f'<div class="pad"><div class="home-actions"><a class="btn primary btn-block">{a[0]}</a><a class="btn btn-block">{a[1]}</a></div>'
                + ('<div class="card"><b>Week of 14 Oct</b><div class="muted">3 meals · in progress · started 12 Oct</div></div>' if after else
                   '<div class="card"><b>Session #12</b><div class="muted">3 items · active · 12/10/2026</div></div>') + "</div>" + nav("home"))

    s1 = compare("1. Home & Plan list — one noun, and what the numbers are",
                 "“session / planning session / shopping session / list” become **plan**; “items” (recipes here, ingredients on the checklist) becomes “meals”; "
                 "“New recipe” opened the library, so it says what it does; unnamed plans show a date, not a number.", home(False), home(True))

    def workspace(after: bool) -> str:
        if not after:
            return (header("Plan") + '<div class="pad"><div class="card"><input placeholder="Session name, e.g. Week of 14 Jul"><button class="btn-sm">Archive</button>'
                    '<div class="muted">Status: active</div><button class="btn-sm">+ Add leftovers day</button><button class="primary" disabled>Checklist →</button></div></div>' + nav("plan"))
        return (header("Plan") + '<div class="pad"><div class="card">' + mini("Plan name", "Week of 14 Oct")
                + '<div class="muted">In progress · started 12 Oct</div><button class="btn-sm">Archive this plan</button>'
                '<div class="hint">Moves it to Past. You can undo it straight away.</div>'
                '<button class="btn-sm">+ Add a leftovers day</button><div class="hint">Leftovers add nothing to the shopping list.</div>'
                '<button class="primary" disabled>Go to shopping checklist →</button><div class="hint">Add a recipe first.</div></div></div>' + nav("plan"))

    s2 = compare("2. Plan workspace", "A label for the name field (it saves when you leave it), consequences for Archive and Leftovers, and a reason when the button is disabled.",
                 workspace(False), workspace(True))

    def recipe(after: bool) -> str:
        if not after:
            return (header("Recipe") + '<div class="pad"><div class="card"><h2>Chilli con carne</h2><div class="muted">4 servings · Mexican · Beef · 👍</div>'
                    '<div class="muted">Archived</div><button class="btn-sm">I cooked this</button><div>1 to taste salt</div>'
                    '<div class="muted">→ using 2 can canned corn</div><h4>Edit recipe</h4>' + mini("Base servings", "4")
                    + '<button class="primary">Save</button><button>Cancel</button><button class="danger">Delete recipe</button></div></div>' + nav("recipes"))
        return (header("Recipe") + '<div class="pad"><div class="card"><h2>Chilli con carne</h2><div class="muted">Makes 4 servings · Mexican · Beef · Rated 👍</div>'
                '<div class="muted">Deleted (hidden from your library). <a class="btn-link">Bring it back</a></div>'
                '<button class="btn-sm">I cooked this (adds 1 to the count)</button><div>Salt, to taste</div>'
                '<div class="muted">Using instead: 2 can canned corn. Your shopping list will show this. Note: …</div><h4>Edit recipe</h4>'
                + mini("Servings this recipe makes (amounts below are for this many)", "4")
                + '<div class="hint">Changing this changes how amounts scale in any plan that already includes this recipe.</div>'
                '<button class="primary">Save recipe details</button><button>Discard changes and go back</button>'
                '<div class="hint">Each ingredient below has its own Save.</div>'
                '<button class="danger">Delete recipe</button><div class="hint">Removes it from your library. Plans already using it keep it. Undo is available for a few seconds.</div>'
                "</div></div>" + nav("recipes"))

    s3 = compare("3. Recipe page and edit — scopes and consequences",
                 "“Base servings”, the two Save scopes, “Archived” vs “Delete”, “1 to taste salt”, the bare “→” and the 👍 are all spelled out. "
                 "(Delete here is a soft delete — true of the code — so “hidden from your library” and “Bring it back” are accurate.)", recipe(False), recipe(True))

    def dup(after: bool) -> str:
        if not after:
            t = ("You might already have this:", "Pasta bake (archived)", "Restore this one", "Save anyway")
        else:
            t = ("This looks like a recipe you already have. Open it, or save this as a separate copy.", "Pasta bake (deleted) — same web page",
                 "Bring back the deleted one (leaves this form)", "Save as a separate recipe anyway")
        return (header("Add a recipe") + '<div class="pad"><div class="inline-card warn"><div class="title">' + t[0] + "</div><div>" + t[1]
                + '</div><div class="log-controls"><button>' + t[2] + "</button><button class=\"primary\">" + t[3] + "</button></div></div></div>" + nav("recipes"))

    s4 = compare("4. Duplicate warning", "Says why it matched, calls a soft-deleted recipe “deleted” (the rest of the app does), and what each button does to the form.",
                 dup(False), dup(True))

    def queued(after: bool) -> str:
        if not after:
            return (header("Capture") + '<div class="pad"><div class="card"><h2>Capture queued</h2><div class="muted">Every AI model is over its quota right now — '
                    "this capture has been queued and will be retried automatically.</div><div class=\"muted\">No need to do anything — check back in the recipe library in "
                    "a while, or watch the capture queue on the Diagnostics page.</div></div></div>" + nav("recipes"))
        return (header("Import") + '<div class="pad"><div class="card"><h2>Saved for later</h2><div class="muted">The recipe reader is busy right now, so this has been saved for later. '
                'It will be tried again automatically within the hour.</div><div class="muted">Nothing else to do. When it works, the recipe is added to Recipes as '
                "“Untitled captured recipe” — open it, give it a name and check the ingredients.</div></div></div>" + nav("recipes"))

    s5 = compare("5. Saved-for-later capture (built)", "No “AI / quota / queued”, and it says where the recipe will appear and what to do then. "
                 "A recipe made this way also gets a “Captured automatically — please check” badge.", queued(False), queued(True))

    def status(after: bool) -> str:
        if not after:
            return (header("Diagnostics") + '<div class="pad"><div class="card"><div class="muted">● state: green · API enabled: yes · fake mode: no</div>'
                    '<div class="muted">list: … · creds: …</div><div class="muted">5 lines · push a1b2c3 · session 12 · read 0s · send 1s · confirm 0s</div>'
                    '<div class="muted">confirmed</div></div></div>' + nav("diag"))
        return (header("Status") + '<div class="pad"><div class="card"><h3>Everything is working</h3>'
                '<div class="row-line"><span>AnyList</span><span>Working</span></div><div class="row-line"><span>Recipe reader</span><span>Working</span></div>'
                '<div class="row-line"><span>Last send to AnyList</span><span>Today 3:15 pm · AnyList has everything</span></div>'
                '<details><summary>Advanced (for the person who looks after the app)</summary><div class="muted">push a1b2c3 · session 12 · read 0s · send 1s · confirm 0s · '
                "release …</div></details></div></div>" + nav("diag", ))

    s6 = compare("6. Diagnostics → Status", "Plain summary first; developer detail behind “Advanced”. The nav label changes to “Status”.", status(False), status(True))

    page("plan-recipes.html", "Plan, recipes, capture, status — plain language",
         "Wording and small markup only. Items that were already implemented (the saved-for-later capture message) are shown for review.",
         [s1, s2, s3, s4, s5, s6])



# ---------------------------------------------------------------------------------------------
# Shortened-copy sample (2026-10-11): the same screens with every line cut to the fewest words that
# stay unambiguous. Approve the STYLE here, then it is applied to all scenes.
# ---------------------------------------------------------------------------------------------
def build_short() -> None:
    def aliases(short: bool) -> str:
        if not short:
            return wrap(
                '<div class="card"><h3>Same item, different names</h3>'
                '<p class="hint">When a recipe uses the name on the left, your shopping list shows the name on the right instead. '
                "Recipes themselves aren’t changed. Applies to every recipe, existing and new.</p>"
                + mini("When a recipe says", ph="e.g. lemon juice") + '<div class="dir">↓ show it on my shopping list as</div>'
                + mini("Shopping list shows", ph="e.g. lemon")
                + '<div class="box"><b>Change the amount too? (optional)</b><div class="sentence"><input placeholder="3"> <input placeholder="tbsp"> '
                '<span>of the first =</span> <input placeholder="1"> <input placeholder="(whole)"> <span>of the second</span></div>'
                '<div class="hint">Only used when a recipe measures it in exactly that unit. Otherwise just the name changes and the amount is left as written. '
                "Leave all four blank to only rename.</div></div>"
                '<div class="preview">“lemon juice” in a recipe will show as “lemon” on your shopping list. 3 tbsp lemon juice becomes 1 lemon.</div>'
                '<button class="btn-sm primary">Save this name group</button></div>'
            )
        return wrap(
            '<div class="card"><h3>Other names</h3>'
            '<p class="hint">A recipe’s name on the left shows as the name on the right. Recipes aren’t changed.</p>'
            + mini("Recipe says", ph="lemon juice") + '<div class="dir">↓</div>' + mini("List shows", ph="lemon")
            + '<div class="box"><b>Convert amount (optional)</b>'
            '<div class="sentence"><input placeholder="3"> <input placeholder="tbsp"> <span>=</span> <input placeholder="1"> <input placeholder="whole"></div>'
            '<div class="hint">Only when the recipe uses that unit.</div></div>'
            '<div class="preview">“lemon juice” → “lemon”. 3 tbsp becomes 1.</div>'
            '<button class="btn-sm primary">Save</button></div>'
        )

    s1 = compare("Name form — long vs short",
                 "Same facts, about a third of the words. The direction is still stated (“Recipe says” ↓ “List shows”), the unit rule is one short line, and there is still a live example.",
                 aliases(False), aliases(True))

    def review(short: bool) -> str:
        if not short:
            return (header("Checklist") + '<div class="pad"><div class="card"><div class="sub-group-heading">Different units — choose how much to buy</div>'
                    '<div class="checklist-row"><div class="main"><div class="name">Cream</div><div class="meta">Recipes need 100 g and 200 ml — these can’t be added together</div></div></div>'
                    '<div class="log-controls"><button class="btn-sm">Buy 100 g</button><button class="btn-sm">Buy 200 ml</button><button class="btn-sm primary">Buy all of them</button></div>'
                    "</div></div>" + nav("plan"))
        return (header("Checklist") + '<div class="pad"><div class="card"><div class="sub-group-heading">Mixed units</div>'
                '<div class="checklist-row"><div class="main"><div class="name">Cream</div><div class="meta">100 g + 200 ml</div></div></div>'
                '<div class="log-controls"><button class="btn-sm">Use 100 g</button><button class="btn-sm">Use 200 ml</button></div>'
                '<div class="box"><b>Or enter your own total</b>'
                '<div class="sentence"><input placeholder="250"> <input placeholder="ml"> <button class="btn-sm primary">Use this total</button></div>'
                '<div class="hint">Blank unit = whole items. One amount goes on the list.</div></div></div></div>' + nav("plan"))

    s2 = compare("Mixed units — now with your own total",
                 "The third choice you asked for: type the combined amount yourself. “Buy all of them” is gone. The row and AnyList then show only your total.",
                 review(False), review(True))

    def top(short: bool) -> str:
        if not short:
            head = ('<div class="sync-note"><span class="sync-dot"></span>Checked against AnyList when this page opened. Items already on your AnyList '
                    "are set to “Have it”, so they won’t be sent again.</div>"
                    '<div class="hint">Tap “Need it” for what you want sent to AnyList. “Have it” skips it. A row you don’t tap is not sent.</div>')
            line = "2 ingredients and 1 regular item will be sent to AnyList. 1 ingredient still needs an amount chosen (under “Needs review”)."
            btn = "Send 3 items to AnyList"
        else:
            head = ('<div class="sync-note"><span class="sync-dot"></span>Checked against AnyList at page open. Items on it are “Have it”.</div>'
                    '<div class="hint">Need it = sent · Have it = skipped · untouched = not sent</div>')
            line = "Sending 2 ingredients + 1 regular item. 1 still needs an amount."
            btn = "Send to AnyList"
        rows = (checklist_row("Cottage cheese", "Buy 2 × 500g tub (need 800 g)", "need")
                + checklist_row("Milk", "2 L", "have", on_list=True) + checklist_row("Lime", "5"))
        return (header("Checklist") + '<div class="pad"><div class="card"><h2>Shopping checklist</h2>' + head
                + '<div class="sub-group-heading">Ingredients</div>' + rows + '<div class="muted">' + line + "</div>"
                '<div class="sticky-actions"><button class="primary btn-block">' + btn + "</button></div></div></div>" + nav("plan"))

    s3 = compare("Checklist header and send line — long vs short",
                 "Each fact kept (what Need/Have do, untouched rows aren’t sent, what “On AnyList” means, what is being sent); the sentences are replaced by a short key.",
                 top(False), top(True))

    page("short.html", "Shorter copy — sample for approval",
         "Left is the wording in the previous mockups, right is the same screen cut down. If this style is right, every other scene gets the same treatment.",
         [s1, s2, s3])


def build_index() -> None:
    html = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Chunk 6.7 — clarity mockups</title>
<style>body{font-family:system-ui,sans-serif;max-width:760px;margin:40px auto;padding:0 16px;color:#2a2620;line-height:1.5}
a{color:#1f6b63}.card{background:#fff;border:1px solid #0002;border-radius:12px;padding:14px 18px;margin:12px 0}</style></head><body>
<h1>Plain language &amp; no ambiguity — mockups for approval</h1>
<p>Static light/dark mockups (each “After” is the exact text proposed). Standard being applied:
<code>docs/ui-ux.md &gt; Plain language &amp; no ambiguity</code>. Approve (or mark up) each page and I’ll implement exactly this.</p>
<div class="card"><h3><a href="settings.html">1. Settings</a></h3><p>Index subtitles; the name-group form from your note (direction, preview, amount sentence); existing groups; unit spellings; saved swaps; pack sizes.</p></div>
<div class="card"><h3><a href="checklist.html">2. Checklist &amp; push</a></h3><p>What Need/Have do and what is sent; “On AnyList”; ingredient panel names and scope labels; combining rows; needs-review; push-again card.</p></div>
<div class="card"><h3><a href="plan-recipes.html">3. Plan, recipes, capture, status</a></h3><p>One noun for “plan”; recipe page/edit scopes and delete consequences; duplicate warning; saved-for-later capture; Status page.</p></div>
<p>Regenerate: <code>.venv\\Scripts\\python docs\\mockups\\chunk-6.7-clarity\\build_mockups.py</code></p></body></html>"""
    (HERE / "index.html").write_text(html, encoding="utf-8")


if __name__ == "__main__":
    build_settings()
    build_checklist()
    build_plan_recipes()
    build_short()
    build_index()
    print("wrote", ", ".join(sorted(p.name for p in HERE.glob("*.html"))))
