"""Mockups for Chunk 6.7 polish batch 3 (2026-10-16): Settings list layout, "I have some",
live checklist hints, and the Copy errors fallback. Static light/dark pictures only.

    .venv\\Scripts\\python docs\\mockups\\chunk-6.7-batch3\\build_artifact.py  ->  artifact.html

Reuses the clarity mockups' frame helpers and the app's real stylesheets (so the "After" Settings
scenes use the real `.settings-group-row` / `.settings-add-card` classes already in the app).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
_p = HERE.parent / "chunk-6.7-clarity" / "build_mockups.py"
_s = importlib.util.spec_from_file_location("clarity_base", _p)
cl = importlib.util.module_from_spec(_s)
_s.loader.exec_module(cl)

compare, scene, header, nav, mini, wrap = cl.compare, cl.scene, cl.header, cl.nav, cl.mini, cl.wrap
checklist_row = cl.checklist_row

# New styles proposed in this batch (they move into static/css/components-screens.css on approval).
EXTRA_CSS = cl.EXTRA_CSS + """
.frame .row-changed { background: var(--accent-tint); border-radius: var(--r-md); }
.frame .row-changed .meta .changed-tag { color: var(--accent); font-size: var(--text-xs); margin-left: var(--sp-2); }
.frame .live-note { font-size: var(--text-sm); border-left: 3px solid var(--accent); background: var(--accent-tint);
  padding: var(--sp-2) var(--sp-3); margin: var(--sp-2) 0 var(--sp-3); }
.frame .have-link { margin-top: var(--sp-1); }
.frame .have-inline { display: flex; flex-wrap: wrap; align-items: center; gap: var(--sp-2); margin-top: var(--sp-2); font-size: var(--text-sm); }
.frame .have-inline input { width: 4.5rem; }
.frame .have-sentence { display: flex; flex-wrap: wrap; align-items: center; gap: var(--sp-2); margin: var(--sp-2) 0; }
.frame .have-sentence input { width: 5rem; }
.frame .copy-fallback { width: 100%; min-height: 7rem; font-family: var(--font-mono); font-size: var(--text-xs); }
.frame .settings-group-name-line { font-weight: 700; margin-bottom: var(--sp-2); }
"""


def old_row(inner: str) -> str:
    return f'<div class="settings-row">{inner}</div>'


# ---------------------------------------------------------------------------------------------
def build_settings():
    def packs(after: bool) -> str:
        if not after:
            def r(name):
                return old_row(
                    '<div class="ing-grid" style="grid-template-columns:2fr 1fr">'
                    + mini("Sold as (blank = just list the name)", "bunch") + mini("One covers how many recipes?", "2") + "</div>"
                    f'<div class="log-controls" style="margin-top:6px"><b>{name}</b><button class="btn-sm primary">Save changes</button><button class="btn-sm">Remove</button></div>'
                )
            add = (
                '<div style="margin-top:12px"><div class="settings-row">'
                '<div class="ing-grid" style="grid-template-columns:1fr 1fr">' + mini("Ingredient", ph="e.g. parsley") + mini("Sold as (blank = just list the name)", ph="e.g. bunch") + "</div>"
                + mini("One covers how many recipes?", "3") + '<div class="log-controls"><button class="btn-sm primary">Add</button></div></div></div>'
            )
            return wrap('<div class="card"><h3>Bought by the bunch</h3><div class="settings-list">' + r("mint") + r("parsley") + "</div>" + add + "</div>")

        def r(name):
            return (
                '<div class="settings-group-row"><div class="settings-group-name-line">' + name + "</div>"
                '<div class="ing-grid" style="grid-template-columns:2fr 1fr">'
                + mini("Sold as (blank = just list the name)", "bunch") + mini("One covers how many recipes?", "2") + "</div>"
                '<div class="settings-row-actions-line"><button class="btn-link-danger">Remove</button><button class="btn-sm primary">Save changes</button></div></div>'
            )
        add = (
            '<div class="settings-add-card"><div class="settings-add-title">Add one</div>'
            '<div class="ing-grid" style="grid-template-columns:1fr 1fr">' + mini("Ingredient", ph="e.g. parsley") + mini("Sold as (blank = just list the name)", ph="e.g. bunch") + "</div>"
            + mini("One covers how many recipes?", "3") + '<div class="log-controls" style="margin-top:6px"><button class="btn-sm primary">Add</button></div></div>'
        )
        return wrap('<div class="card"><h3>Bought by the bunch</h3><div class="settings-list">' + r("mint") + r("parsley") + "</div>" + add + "</div>")

    s1 = compare(
        "1. Pack sizes (Bought by the bunch) — name first, a clear line before “add”",
        "Before: each item's name and buttons sit BELOW its boxes, so “mint” reads like a heading for the row underneath, and nothing separates the last entry from the add form. "
        "After: the name is the heading of its own row, lines go between rows, and the add form is its own dashed box titled “Add one” (the same look “Same item, different names” already has). "
        "Saved ingredient swaps and The usuals get exactly this treatment too.",
        packs(False), packs(True))

    def spellings(after: bool) -> str:
        pairs = [("tablespoon", "tbsp"), ("tbs", "tbsp"), ("tbspn", "tbsp")]
        if not after:
            rows = "".join(old_row(f'<span class="muted">{a} → {b}</span><button class="btn-sm">Remove</button>') for a, b in pairs)
            add = (
                '<div style="margin-top:12px"><div class="settings-row">' + mini("When a recipe says", ph="e.g. tablespoon")
                + '<div class="pair-dir muted">↓ count it as</div>' + mini("Count it as", ph="e.g. tbsp")
                + '<div class="log-controls"><button class="btn-sm primary">Save this spelling</button></div></div></div>'
            )
            return wrap('<div class="card"><h3>Unit spellings</h3><div class="sub-group-heading">tbsp</div>' + rows + add + "</div>")
        rows = "".join(
            f'<div class="settings-group-row"><div class="settings-row-actions-line" style="margin-top:0;justify-content:space-between">'
            f'<span>{a} <span class="muted">counts as</span> {b}</span><button class="btn-link-danger">Remove</button></div></div>' for a, b in pairs
        )
        add = (
            '<div class="settings-add-card"><div class="settings-add-title">Add one</div>'
            + mini("When a recipe says", ph="e.g. tablespoon") + '<div class="pair-dir muted">↓ count it as</div>'
            + mini("Unit on your list", ph="e.g. tbsp") + '<div class="log-controls" style="margin-top:6px"><button class="btn-sm primary">Save this spelling</button></div></div>'
        )
        return wrap('<div class="card"><h3>Unit spellings</h3><div class="settings-sub-head">tbsp</div>' + rows + add + "</div>")

    s2 = compare(
        "2. Unit spellings — the hint stacks between the two boxes",
        "Before: “↓ count it as” floats to the right of the first box and the second box repeats “Count it as”. After: the hint sits centred between the two boxes (as in "
        "“Same item, different names”), the second box is labelled “Unit on your list”, each saved spelling reads “tablespoon counts as tbsp”, and the group has no double line.",
        spellings(False), spellings(True))
    return [s1, s2]


# ---------------------------------------------------------------------------------------------
def build_checklist():
    def row(name, meta, state="", have=None, editing=False, changed=False, on_list=False):
        """A checklist row with the always-visible "I have some" control under the amount."""
        cls = "checklist-row" + (" row-changed" if changed else "") + (" on-anylist" if on_list else "")
        tag = '<span class="tag-on">On AnyList</span>' if on_list else ""
        hv = ' aria-pressed="true"' if state == "have" else ""
        nd = ' aria-pressed="true"' if state == "need" else ""
        ctl = ""
        if editing:
            ctl = (
                '<div class="have-inline"><span>I have</span><input value="1" inputmode="decimal" aria-label="How many you have">'
                '<span>of 3</span><button class="btn-sm primary">Save</button><button class="btn-sm">Cancel</button></div>'
            )
        elif have is not None:
            ctl = '<button class="btn-link have-link">Change what I have</button>'
        elif state != "have":
            ctl = '<button class="btn-link have-link">I have some</button>'
        tail = '<span class="changed-tag">Changed on another phone</span>' if changed else ""
        return (
            f'<div class="{cls}"><div class="main"><div class="name">{name} ▾{tag}</div><div class="meta">{meta}{tail}</div>{ctl}</div>'
            f'<div class="have-need-pair"><button class="have-need-btn have"{hv}>Have it</button><button class="have-need-btn need"{nd}>Need it</button></div></div>'
        )

    def screen(rows, note=""):
        return header("Checklist") + '<div class="pad"><div class="card">' + note + '<div class="sub-group-heading">Ingredients</div>' + rows + "</div></div>" + nav("plan")

    s1 = scene(
        "3. “I have some” — one tap away on the row, no panel to open",
        "Every row with a single amount (not “to taste”, “by the bunch” or mixed-unit rows) shows a small “I have some” link under its amount. Rows already marked Have it don't show it.",
        screen(row("Tomatoes", "3", "need") + row("Lime", "5") + row("Milk", "2 L", "have", on_list=True)),
    )
    s2 = scene(
        "3a. Tap it: the field opens right on the row",
        "Type how many you already have and tap Save (or Cancel). Only this plan. Having all of it (3 of 3) turns the row to Have it.",
        screen(row("Tomatoes", "3", "need", editing=True) + row("Lime", "5")),
    )
    s3 = scene(
        "3b. How the row reads afterwards",
        "The first number is what goes to AnyList (“Tomatoes — 2”). Packs are counted on what is still to buy: 900 g needs two 500 g bags, but with 450 g in the cupboard it is one. "
        "The link becomes “Change what I have” (set it to 0 to clear). Wording alternatives: “Buy 2 (you have 1)” or “2 more needed (have 1 of 3)”.",
        screen(
            row("Tomatoes", "Buy 2 · have 1 of 3", "need", have=1)
            + row("Plain flour", "Buy 1 × 500g bag · have 450 of 900 g", "need", have=450)
            + row("Lime", "5")
        ),
    )
    s4 = scene(
        "4. Live checklist — a change from another phone",
        "The row is tinted and says where it came from for a few seconds, then returns to normal. Nothing else on screen moves. No sound, no pop-up.",
        screen(row("Tomatoes", "Buy 2 · have 1 of 3", "need", have=1) + row("Lime", "5", "have", changed=True) + row("Milk", "2 L", "have", on_list=True)),
    )
    s5 = scene(
        "4b. …while you are in the middle of typing",
        "If you are typing (or have a panel open), the other phone's change waits so nothing you typed is lost. One line says so; the change appears when you finish.",
        screen(row("Tomatoes", "3", "need", editing=True) + row("Lime", "5"),
               note='<div class="live-note">Another phone changed this list. You’ll see it when you finish.</div>'),
    )
    return [s1, s2, s3, s4, s5]


# ---------------------------------------------------------------------------------------------
def build_status():
    def card(after: bool) -> str:
        err = ('<div class="errors-box"><div class="log-line"><span class="log-time">17 Oct, 5:41 am</span><span class="log-level ERROR">ERROR</span>'
               '<span class="log-msg">app.client: Browser error on /#/diagnostics: …</span></div></div>')
        top = '<div class="log-controls"><h3 style="margin:0">Recent errors</h3><button style="margin-left:auto">Copy errors</button></div>'
        if not after:
            inner = f'<div class="card">{top}<div class="muted">Tap “Copy errors” on Firefox over the home network: nothing happens, and it adds a new error to this list.</div>{err}</div>'
        else:
            inner = (
                f'<div class="card">{top}'
                '<div class="hint">Couldn’t copy automatically. Press and hold the text below, then choose Copy.</div>'
                '<textarea class="copy-fallback" readonly>17 Oct, 5:41 am | ERROR | app.client: Browser error on /#/diagnostics …</textarea>'
                f'{err}</div>'
            )
        return (wrap(inner, "Status", "diag")).replace("Diagnostics", "Status")

    s1 = compare(
        "5. Status — Copy errors on a phone browser",
        "Most of the time the button now just works (it copies, then the usual “Copied 3 errors” toast). Only if the browser refuses both ways does the text appear in a box, already selected, "
        "so a press-and-hold copies it. Also: the bare “Script error.” lines you saw come from a browser add-on, not the app; they will now be logged as a quiet warning "
        "(“Script error from outside the app”) and no longer light the red dot on Status.",
        card(False), card(True))
    return [s1]
