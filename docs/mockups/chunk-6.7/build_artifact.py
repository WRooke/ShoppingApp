"""Builds ONE self-contained HTML page of all the Chunk 6.7 mockups, for publishing as an Artifact
(viewable remotely, no repo needed).

    .venv\\Scripts\\python docs\\mockups\\chunk-6.7\\build_artifact.py  ->  docs/mockups/chunk-6.7/artifact.html

Same scenes as the per-page files (it reuses build_mockups.py), but: the app's real stylesheets are
inlined and SCOPED under `.frame` with native CSS nesting (so they cannot restyle the page chrome),
@font-face/@keyframes are hoisted out (they cannot be nested), the three IBM Plex faces are embedded
as data: URIs (an Artifact may not load anything from the repo), and the page chrome follows the
viewer's light/dark theme while each frame shows both themes side by side.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

import build_mockups as bm

HERE = Path(__file__).resolve().parent
STATIC = bm.STATIC


def _take_at_rules(css: str, names: tuple[str, ...]) -> tuple[str, str]:
    """Pull every top-level `@name ... { balanced }` block out of css. Returns (hoisted, rest)."""
    hoisted, out, i = [], [], 0
    pat = re.compile(r"@(" + "|".join(names) + r")\b")
    while i < len(css):
        m = pat.search(css, i)
        if not m:
            out.append(css[i:])
            break
        out.append(css[i:m.start()])
        j = css.index("{", m.end())
        depth, k = 1, j + 1
        while depth:
            depth += {"{": 1, "}": -1}.get(css[k], 0)
            k += 1
        hoisted.append(css[m.start():k])
        i = k
    return "\n".join(hoisted), "".join(out)


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def scoped_app_css() -> tuple[str, str]:
    """(hoisted at-rules, `.frame { ...real css... }`)."""
    parts = []
    for name in ("components.css", "components-screens.css", "app.css"):
        parts.append(_strip_comments((STATIC / "css" / name).read_text(encoding="utf-8")))
    parts.append(_strip_comments((HERE / "proposed.css").read_text(encoding="utf-8")))
    css = "\n".join(parts)
    hoisted, rest = _take_at_rules(css, ("keyframes", "font-face"))
    return hoisted, ".frame {\n" + rest + "\n}"


def font_faces() -> str:
    def face(family: str, weight: str, file: str) -> str:
        data = base64.b64encode((STATIC / "fonts" / file).read_bytes()).decode()
        return (f'@font-face{{font-family:"{family}";font-weight:{weight};font-display:swap;'
                f'src:url(data:font/woff2;base64,{data}) format("woff2");}}')
    return (face("IBM Plex Sans", "400 700", "ibm-plex-sans-var.woff2")
            + face("IBM Plex Mono", "500", "ibm-plex-mono-500.woff2")
            + face("IBM Plex Mono", "600", "ibm-plex-mono-600.woff2"))


CHROME = """
:root {
  --pg-bg: #e7e3da; --pg-fg: #26231d; --pg-dim: #5b564b; --pg-card: #f5f2ea; --pg-line: #cfc9bb; --pg-accent: #1d6a62; --pg-chip: #ddd7c8;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --pg-bg: #15130f; --pg-fg: #efe9dc; --pg-dim: #b0a893; --pg-card: #211e17; --pg-line: #3a352a; --pg-accent: #8bb8e3; --pg-chip: #2f2b21; color-scheme: dark; } }
:root[data-theme="dark"] {
  --pg-bg: #15130f; --pg-fg: #efe9dc; --pg-dim: #b0a893; --pg-card: #211e17; --pg-line: #3a352a; --pg-accent: #8bb8e3; --pg-chip: #2f2b21; color-scheme: dark; }
body { background: var(--pg-bg); color: var(--pg-fg); font-family: "IBM Plex Sans", system-ui, sans-serif; line-height: 1.5; font-size: 15px;
  padding-inline: 16px; padding-block: 0 72px; }
.wrap { max-width: 880px; margin: 0 auto; }
.top { position: sticky; top: env(safe-area-inset-top, 0px); z-index: 20; background: var(--pg-bg); border-bottom: 1px solid var(--pg-line);
  padding-block: 10px; margin-inline: -16px; padding-inline: 16px; }
.top .in { max-width: 880px; margin: 0 auto; display: flex; flex-wrap: wrap; gap: 6px 14px; align-items: baseline; }
.top b { font-size: 15px; margin-right: 6px; }
.top a { color: var(--pg-accent); text-decoration: none; font-weight: 600; font-size: 14px; padding: 4px 0; }
.top a:hover, .top a:focus-visible { text-decoration: underline; }
h1.main { font-size: 1.7rem; margin: 22px 0 6px; text-wrap: balance; }
.lede { max-width: 68ch; color: var(--pg-dim); margin: 0 0 18px; }
.ask { background: var(--pg-card); border: 1px solid var(--pg-line); border-radius: 12px; padding: 14px 18px; margin: 14px 0 6px; max-width: 76ch; }
.ask h2 { font-size: 1rem; margin: 0 0 6px; } .ask ul { margin: 0; padding-left: 20px; } .ask li { margin: 2px 0; }
section.part { padding-top: 26px; scroll-margin-top: 60px; }
section.part > h2 { font-size: 1.35rem; margin: 0 0 4px; text-wrap: balance; }
section.part > .lede { margin-bottom: 14px; }
.scene { margin: 0 0 34px; }
.scene h3.st { font-size: 1.02rem; margin: 0 0 2px; text-wrap: balance; }
.scene .note { margin: 0 0 10px; max-width: 70ch; color: var(--pg-dim); font-size: .9rem; }
.pair, .cmp { display: flex; gap: 18px; flex-wrap: wrap; align-items: flex-start; }
.cmp .tag { font-weight: 700; font-size: .82rem; margin: 0 0 4px 6px; }
.cap { font-size: 11px; letter-spacing: .08em; text-transform: uppercase; color: var(--pg-dim); margin: 0 0 4px 6px; font-weight: 700; }
.framewrap { min-width: 0; max-width: 100%; }
.frame { width: 390px; max-width: 100%; box-sizing: border-box; border-radius: 20px; overflow: hidden; position: relative; background: var(--bg); color: var(--text);
  font-family: "IBM Plex Sans", system-ui, sans-serif; font-size: var(--text-base); line-height: 1.5; border: 1px solid #00000033; box-shadow: 0 6px 24px #00000026; }
.frame .pad { padding: var(--sp-4); }
.frame h3 { margin: 0 0 var(--sp-2); font-size: var(--text-md); }
.frame .app-header, .frame .bottom-nav, .frame .sticky-actions, .frame .update-banner { position: static; }
.frame .toast-static { display: flex; justify-content: center; padding: var(--sp-3) var(--sp-3) var(--sp-4); }
.frame .toast { position: static; transform: none; opacity: 1; }
.frame .statusbar { display: flex; justify-content: space-between; padding: 6px 18px; font-size: 12px; font-weight: 600; background: var(--bg); color: var(--text); }
.frame.phone-notch .update-banner { padding-top: calc(var(--sp-2) + 28px); }
.al { background: #212226; color: #fff; font-family: Roboto, system-ui, sans-serif; }
.al .top2 { padding: 14px 16px; border-bottom: 1px solid #0006; } .al .top2 b { font-size: 1.15rem; display: block; } .al .top2 span { color: #b9bbc2; font-size: .9rem; }
.al .item { padding: 13px 16px; border-bottom: 1px solid #ffffff22; font-size: 1.05rem; } .al .item small { color: #9a9ca3; font-size: .9rem; } .al .item.sub small { display: block; margin-top: 2px; }
.al .item .bad { background: #7a2a2a; border-radius: 4px; padding: 0 3px; } .al .item .good { background: #1f5d3a; border-radius: 4px; padding: 0 3px; }
"""

# scenes call the AnyList-app mock's header `top`; rename so it does not collide with the sticky nav
def _fix(html: str) -> str:
    return html.replace('<div class="top"><b>TestList</b>', '<div class="top2"><b>TestList</b>')


def main() -> None:
    collected: list[tuple[str, str, str, list[str]]] = []
    bm.page = lambda name, title, lede, scenes: collected.append((name, title, lede, scenes))
    bm.build_push(); bm.build_banner(); bm.build_popups(); bm.build_names()
    anchors = {"push.html": "push", "banner.html": "banner", "popups.html": "popups", "names.html": "names"}
    labels = {"push.html": "AnyList push", "banner.html": "Update banner", "popups.html": "No pop-ups", "names.html": "Names"}

    hoisted, scoped = scoped_app_css()
    theme = bm._theme_css()
    body = []
    body.append('<div class="top"><div class="in"><b>6.7 mockups</b>'
                + "".join(f'<a href="#{anchors[n]}">{labels[n]}</a>' for n, *_ in collected) + "</div></div><div class=\"wrap\">")
    body.append('<h1 class="main">Chunk 6.7 mockups</h1><p class="lede">Every screen that changes, in light and dark, using the app’s real styles. '
                'Static pictures only. Tell me what to change on any scene, or approve a whole section.</p>')
    body.append('<div class="ask"><h2>What I need from you</h2><ul>'
                '<li><b>Push</b>: approve the tracker, result card, needs-attention state and Diagnostics panels (the behaviour behind them is built and tested).</li>'
                '<li><b>Update banner</b>: approve the three small visual changes.</li>'
                '<li><b>No pop-ups</b>: approve the merge panel wording and buttons, the two inline cards and the four error patterns.</li>'
                '<li><b>Names</b>: approve the before/after wording.</li></ul></div>')
    for name, title, lede, scenes in collected:
        sc = "".join(
            re.sub(r'<section class="scene"><h2>(.*?)</h2>', lambda m: '<section class="scene"><h3 class="st">' + m.group(1) + '</h3>', _fix(s))
            for s in scenes
        )
        body.append(f'<section class="part" id="{anchors[name]}"><h2>{title}</h2><p class="lede">{lede}</p>{sc}</section>')
    body.append("</div>")

    html = (
        "<title>Chunk 6.7 Mockups</title>\n<style>\n" + font_faces() + "\n" + hoisted + "\n" + theme + "\n" + CHROME
        + "\n" + scoped + "\n"
        # the frame-level overrides must come after the scoped real CSS
        + ".frame .app-header, .frame .bottom-nav, .frame .sticky-actions, .frame .update-banner { position: static; }\n"
        + ".frame .toast { position: static; transform: none; opacity: 1; white-space: normal; }\n"
        + "</style>\n" + "".join(body) + "\n"
    )
    out = HERE / "artifact.html"
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({len(html) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
