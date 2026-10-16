"""Builds ONE self-contained HTML page of the batch 3 mockups, for publishing as an Artifact.

    .venv\\Scripts\\python docs\\mockups\\chunk-6.7-batch3\\build_artifact.py  ->  artifact.html
Same approach as ../chunk-6.7-clarity/build_artifact.py (real stylesheets scoped under .frame,
fonts embedded, page chrome follows the viewer's theme).
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "chunk-6.7"))
import build_artifact as prev  # noqa: E402

_spec = importlib.util.spec_from_file_location("batch3_bm", HERE / "build_mockups.py")
b3 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(b3)


def main() -> None:
    parts = [
        ("settings", "Settings lists", "Pack sizes and Unit spellings, before and after. Saved ingredient swaps and The usuals follow the same pattern.", b3.build_settings()),
        ("checklist", "Checklist", "“I have some”, and what live updates look like.", b3.build_checklist()),
        ("status", "Status", "Copy errors on a phone browser.", b3.build_status()),
    ]
    hoisted, scoped = prev.scoped_app_css()
    theme = prev.bm._theme_css()
    body = ['<div class="top"><div class="in"><b>Polish batch 3</b>' + "".join(f'<a href="#{a}">{t}</a>' for a, t, *_ in parts) + '</div></div><div class="wrap">']
    body.append('<h1 class="main">Polish batch 3 mockups</h1><p class="lede">Static pictures drawn with the app’s real styles, light and dark. '
                'Nothing is built yet. Tell me which scenes to change, or say “approved”.</p>')
    for anchor, title, lede, scenes in parts:
        sc = "".join(
            re.sub(r'<section class="scene"><h2>(.*?)</h2>', lambda m: '<section class="scene"><h3 class="st">' + m.group(1) + '</h3>', prev._fix(s))
            for s in scenes
        )
        body.append(f'<section class="part" id="{anchor}"><h2>{title}</h2><p class="lede">{lede}</p>{sc}</section>')
    body.append("</div>")
    html = (
        "<title>Polish Batch Mockups</title>\n<style>\n" + prev.font_faces() + "\n" + hoisted + "\n" + theme + "\n" + prev.CHROME
        + "\n" + scoped + "\n" + b3.EXTRA_CSS + "\n"
        + ".frame .app-header, .frame .bottom-nav, .frame .sticky-actions, .frame .update-banner { position: static; }\n"
        + ".frame .toast { position: static; transform: none; opacity: 1; white-space: normal; }\n"
        + "</style>\n" + "".join(body) + "\n"
    )
    out = HERE / "artifact.html"
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({len(html) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
