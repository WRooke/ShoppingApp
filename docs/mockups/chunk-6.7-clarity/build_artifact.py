"""Builds ONE self-contained HTML page of the clarity mockups, for publishing as an Artifact
(viewable remotely, no repo needed).

    .venv\\Scripts\\python docs\\mockups\\chunk-6.7-clarity\\build_artifact.py  ->  artifact.html

Reuses the Chunk 6.7 artifact builder (real stylesheets scoped under .frame, fonts embedded as
data: URIs, page chrome following the viewer's theme) and this folder's scenes.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PREV = HERE.parent / "chunk-6.7"
sys.path.insert(0, str(PREV))  # build_artifact (6.7) does `import build_mockups as bm`

import build_artifact as prev  # noqa: E402  (the chunk-6.7 builder)

_spec = importlib.util.spec_from_file_location("clarity_bm", HERE / "build_mockups.py")
cl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cl)


def main() -> None:
    collected: list[tuple[str, str, str, list[str]]] = []
    cl.page = lambda name, title, lede, scenes: collected.append((name, title, lede, scenes))
    cl.build_short()
    cl.build_settings()
    cl.build_checklist()
    cl.build_plan_recipes()
    anchors = {"short.html": "short", "settings.html": "settings", "checklist.html": "checklist", "plan-recipes.html": "plan"}
    labels = {"short.html": "Shorter copy", "settings.html": "Settings", "checklist.html": "Checklist & push", "plan-recipes.html": "Plan, recipes, status"}

    hoisted, scoped = prev.scoped_app_css()
    theme = prev.bm._theme_css()
    body = []
    body.append('<div class="top"><div class="in"><b>Clarity mockups</b>'
                + "".join(f'<a href="#{anchors[n]}">{labels[n]}</a>' for n, *_ in collected) + '</div></div><div class="wrap">')
    body.append('<h1 class="main">Plain language mockups</h1><p class="lede">Every “After” is the exact wording proposed for the app, '
                'checked against what the code really does, drawn in light and dark with the app’s real styles. Static pictures only.</p>')
    body.append('<div class="ask"><h2>What I need from you</h2><ul>'
                '<li><b>Shorter copy</b> (first section): approve the style, or say how much further to cut. The sections below are still the long wording and get cut the same way.</li>'
                '<li><b>Mixed units</b>: a new “enter your own total” choice replaces “Buy all of them”.</li>'
                '<li><b>Settings</b>: the “When a recipe says … show it as …” pattern (used for name groups, unit spellings, saved swaps, and again in the checklist). Approve or mark up.</li>'
                '<li><b>Checklist &amp; push</b>: the helper line, “On AnyList” tag, renamed chips and scope labels, combine-rows panel, push-again wording.</li>'
                '<li><b>Plan, recipes, status</b>: “plan” as the one noun, recipe edit scopes and delete consequence, duplicate warning, Status page.</li>'
                '<li>Anything you want worded differently, say which scene.</li></ul></div>')
    for name, title, lede, scenes in collected:
        sc = "".join(
            re.sub(r'<section class="scene"><h2>(.*?)</h2>', lambda m: '<section class="scene"><h3 class="st">' + m.group(1) + '</h3>', prev._fix(s))
            for s in scenes
        )
        body.append(f'<section class="part" id="{anchors[name]}"><h2>{title}</h2><p class="lede">{lede}</p>{sc}</section>')
    body.append("</div>")

    html = (
        "<title>Clarity Mockups</title>\n<style>\n" + prev.font_faces() + "\n" + hoisted + "\n" + theme + "\n" + prev.CHROME
        + "\n" + scoped + "\n"
        + cl.EXTRA_CSS + "\n"
        + ".frame .app-header, .frame .bottom-nav, .frame .sticky-actions, .frame .update-banner { position: static; }\n"
        + ".frame .toast { position: static; transform: none; opacity: 1; white-space: normal; }\n"
        + "</style>\n" + "".join(body) + "\n"
    )
    out = HERE / "artifact.html"
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({len(html) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
