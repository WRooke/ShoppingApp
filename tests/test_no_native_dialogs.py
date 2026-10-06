"""Guard (Chunk 6.7, 2026-10-06): the frontend must never use the browser's native dialogs.

Rule and replacements: docs/ui-ux.md > "No native dialogs" (Feedback.error / Feedback.card /
Toast with tone "error"). Comments are ignored (they legitimately mention confirm()); a use in code
fails with the file and line.
"""

from __future__ import annotations

import re
from pathlib import Path

JS = Path(__file__).resolve().parent.parent / "static" / "js"
CALL = re.compile(r"(?<![\w.$])(?:(?:window|global|globalThis|self)\s*\.\s*)?(alert|confirm|prompt)\s*\(")


def _code_only(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)
    return re.sub(r"(?<![:\"'])//[^\n]*", "", text)


def test_no_native_dialog_calls_anywhere_in_the_frontend():
    offenders = []
    for path in sorted(JS.glob("*.js")):
        for n, line in enumerate(_code_only(path.read_text(encoding="utf-8")).splitlines(), 1):
            if CALL.search(line):
                offenders.append(f"{path.name}:{n}: {line.strip()[:100]}")
    assert not offenders, "native dialog use:\n" + "\n".join(offenders)


def test_the_guard_itself_catches_what_it_should():
    bad = "x(); global.alert('hi'); window.confirm(1); prompt('p'); alert(2)"
    assert len(CALL.findall(bad)) == 4
    assert not CALL.search(_code_only("// uses confirm() here\n/* alert( */ var ok = 1;"))
    assert not CALL.search("somealert(1); obj.confirm(2)")  # a method on another object is not the native one
