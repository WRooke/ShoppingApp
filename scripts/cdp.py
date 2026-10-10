"""Minimal, dependency-free Chrome DevTools Protocol driver for headless-browser
verification of the frontend (see HEADLESS_VERIFY.md).

Why this exists: every past frontend-verification session re-invented a way to drive
headless Edge and hit the same wall (stale profile locks, dump-dom not waiting for
async JS, an ad-hoc `websocket-client` install that then gets removed). This is the
committed, stdlib-only answer — no `pip install`, no node.

Usage (module):

    from scripts.cdp import Browser
    with Browser("http://127.0.0.1:8099/#/recipes/new") as b:
        b.wait_for(".dup-hint")            # CSS selector present in the DOM
        b.fill("input", "Sunday Roast Chicken", nth=0)
        b.click("button.primary")
        b.wait_for(".dup-warn")
        print(b.text(".dup-warn-heading"))
        b.screenshot("out.png")
        assert not b.console_errors(), b.console_errors()

Usage (CLI smoke — dumps the rendered DOM after JS settles):

    python -m scripts.cdp http://127.0.0.1:8099/#/recipes/new

Only meant for local dev verification against a scratch server. Not imported by the app.
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request

# Edge is the browser present on the dev/NUC Windows boxes (Chrome would work identically).
_EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
]


def _find_browser() -> str:
    override = os.environ.get("CDP_BROWSER")
    if override and os.path.exists(override):
        return override
    for path in _EDGE_CANDIDATES:
        if os.path.exists(path):
            return path
    raise RuntimeError(
        "No Edge/Chrome found. Set CDP_BROWSER to the .exe path. Looked in:\n  "
        + "\n  ".join(_EDGE_CANDIDATES)
    )


# --- a tiny RFC6455 client (text frames only, client-masked as the spec requires) --------


class _WS:
    def __init__(self, url: str):
        # ws://host:port/path
        assert url.startswith("ws://"), url
        host_port, _, path = url[len("ws://") :].partition("/")
        host, _, port = host_port.partition(":")
        self.sock = socket.create_connection((host, int(port or "80")), timeout=10)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall(
            (
                f"GET /{path} HTTP/1.1\r\n"
                f"Host: {host_port}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            ).encode()
        )
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.sock.recv(4096)
        if b" 101 " not in buf.split(b"\r\n", 1)[0]:
            raise RuntimeError(f"WS handshake failed: {buf[:200]!r}")
        self._rest = buf.split(b"\r\n\r\n", 1)[1]

    def send(self, text: str) -> None:
        payload = text.encode()
        header = bytearray([0x81])  # FIN + text opcode
        n = len(payload)
        mask = os.urandom(4)
        if n < 126:
            header.append(0x80 | n)
        elif n < (1 << 16):
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    def _recv_exact(self, n: int) -> bytes:
        while len(self._rest) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RuntimeError("WS closed")
            self._rest += chunk
        out, self._rest = self._rest[:n], self._rest[n:]
        return out

    def recv(self) -> str:
        while True:
            b0, b1 = self._recv_exact(2)
            opcode = b0 & 0x0F
            length = b1 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._recv_exact(8))[0]
            data = self._recv_exact(length)
            if opcode == 0x8:  # close
                raise RuntimeError("WS server closed the connection")
            if opcode in (0x9, 0xA):  # ping/pong — ignore
                continue
            return data.decode("utf-8", "replace")

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.sock.close()


# --- the driver ----------------------------------------------------------------------------


def _launch_edge(port: int, window: str) -> tuple[subprocess.Popen, str]:
    """Start a headless browser on a FRESH profile (no lock/reuse) and return (process, profile)."""
    profile = tempfile.mkdtemp(prefix="cdp-edge-")
    proc = subprocess.Popen(
        [
            _find_browser(),
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--no-first-run",
            "--disable-extensions",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}",
            f"--window-size={window}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc, profile


def _kill_browser(proc: subprocess.Popen) -> None:
    with contextlib.suppress(Exception):
        proc.terminate()
        proc.wait(timeout=5)
    # terminate() only ends the launcher; Edge's renderer/GPU children can outlive it and keep
    # holding the debug port, so the NEXT Browser silently attaches to a stale page whose server
    # is gone (2026-10-07: that made unrelated tests fail with "Failed to fetch"). Kill the tree.
    if sys.platform == "win32":
        with contextlib.suppress(Exception):
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
            )


class BrowserProcess:
    """ONE headless browser process that many `Browser`s share (2026-10-07 test-suite audit).

    Launching Edge costs ~1.5 s, and the frontend suite used to do it for every test. Each
    `Browser(url, process=...)` instead opens its own *browser context* inside this process —
    Chromium's incognito-style isolation: separate cookies, localStorage, sessionStorage and
    cache — so a test still starts from a clean slate, exactly as with a fresh profile, without
    paying for a launch. Disposing the context at the end of the test discards all of it.

    Fails loudly if something already answers on the debug port: a stale Edge from an aborted run
    would otherwise be attached to silently (see `_kill_browser`)."""

    def __init__(self, *, port: int = 9222, window: str = "414,896"):
        self.port = port
        self._id = 0
        if self._answering(port):
            raise RuntimeError(
                f"Something is already listening on the DevTools port {port} (a stale headless "
                "Edge from an earlier run?). Kill it (`taskkill /F /IM msedge.exe`) and retry."
            )
        self._proc, self._profile = _launch_edge(port, window)
        deadline = time.time() + 20
        info = None
        while time.time() < deadline:
            try:
                info = json.loads(
                    urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2).read()
                )
                break
            except Exception:
                time.sleep(0.1)
        if not info:
            _kill_browser(self._proc)
            raise RuntimeError("Could not reach the browser's DevTools endpoint")
        self._ws = _WS(info["webSocketDebuggerUrl"])

    @staticmethod
    def _answering(port: int) -> bool:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1).read()
            return True
        except Exception:
            return False

    def _cmd(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        mid = self._id
        self._ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        deadline = time.time() + 15
        while time.time() < deadline:
            msg = json.loads(self._ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method} -> {msg['error']}")
                return msg.get("result", {})
        raise TimeoutError(f"{method} timed out")

    def open_context(self) -> tuple[str, str]:
        """A new isolated context with one blank page: (context id, that page's websocket URL)."""
        ctx = self._cmd("Target.createBrowserContext")["browserContextId"]
        target = self._cmd("Target.createTarget", {"url": "about:blank", "browserContextId": ctx})
        return ctx, f"ws://127.0.0.1:{self.port}/devtools/page/{target['targetId']}"

    def close_context(self, ctx: str) -> None:
        with contextlib.suppress(Exception):
            self._cmd("Target.disposeBrowserContext", {"browserContextId": ctx})

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._ws.close()
        _kill_browser(self._proc)

    def __enter__(self) -> "BrowserProcess":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


# Injected into every new document (Page.addScriptToEvaluateOnNewDocument) so `_settle` can wait
# for the page to actually be idle instead of sleeping a fixed time: counts in-flight fetch/XHR and
# short (<= 1 s) setTimeouts, and records when the DOM last changed.
_IDLE_TRACKER = r"""
(function () {
  if (window.__cdp) return;
  var s = window.__cdp = {busy: 0, lastMut: Date.now()};
  var f = window.fetch;
  if (f) window.fetch = function () {
    s.busy++;
    var p;
    try { p = f.apply(this, arguments); } catch (e) { s.busy--; throw e; }
    var done = function () { s.busy--; };
    p.then(done, done);
    return p;
  };
  var send = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function () {
    s.busy++;
    this.addEventListener('loadend', function () { s.busy--; });
    return send.apply(this, arguments);
  };
  var st = window.setTimeout, ct = window.clearTimeout, live = {};
  window.setTimeout = function (fn, d) {
    if (typeof fn !== 'function' || (d || 0) > 1000) return st.apply(window, arguments);
    var args = [].slice.call(arguments, 2), id;
    s.busy++;
    id = st.call(window, function () {
      if (live[id]) { delete live[id]; s.busy--; }
      return fn.apply(this, args);
    }, d);
    live[id] = 1;
    return id;
  };
  window.clearTimeout = function (id) {
    if (live[id]) { delete live[id]; s.busy--; }
    return ct.call(window, id);
  };
  new MutationObserver(function () { s.lastMut = Date.now(); })
    .observe(document, {subtree: true, childList: true, attributes: true, characterData: true});
})();
"""

_IS_IDLE = (
    "(function(){var s=window.__cdp;"
    "return document.readyState==='complete' && (!s || (s.busy<=0 && Date.now()-s.lastMut>=60));})()"
)


class Browser:
    def __init__(
        self,
        url: str,
        *,
        port: int = 9222,
        window: str = "414,896",
        wait: float = 0.0,
        process: BrowserProcess | None = None,
    ):
        """Without ``process`` this launches (and on close kills) its own browser, as it always
        has. With a shared `BrowserProcess` it opens an isolated context in that browser instead
        and only disposes the context on close."""
        self._url = url
        self._port = port
        self._shared = process
        self._ctx: str | None = None
        self._proc = None
        self._id = 0
        self._console: list[str] = []
        if process is None:
            self._proc, self._profile = _launch_edge(port, window)
            self._connect(self._find_page_ws())
        else:
            self._ctx, ws_url = process.open_context()
            self._connect(ws_url)
            # A launched headless Edge asked for 414x896 actually renders a 492x757 viewport (Chrome's
            # minimum window width plus its own chrome). Layout assertions in the suite were written
            # against that, so a default-sized shared page emulates exactly it rather than 414x896.
            w, _, h = ("492,757" if window == "414,896" else window).partition(",")
            self._cmd(
                "Emulation.setDeviceMetricsOverride",
                {"width": int(w), "height": int(h), "deviceScaleFactor": 1, "mobile": False},
            )
        if wait:
            time.sleep(wait)
        self.navigate(url)

    # -- lifecycle --
    def _find_page_ws(self) -> str:
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                raw = urllib.request.urlopen(
                    f"http://127.0.0.1:{self._port}/json", timeout=2
                ).read()
                pages = [t for t in json.loads(raw) if t.get("type") == "page"]
                if pages:
                    return pages[0]["webSocketDebuggerUrl"]
            except Exception:
                time.sleep(0.1)
        raise RuntimeError("Could not reach the browser's DevTools endpoint")

    def _connect(self, ws_url: str) -> None:
        self._ws = _WS(ws_url)
        self._cmd("Page.enable")
        self._cmd("Runtime.enable")
        self._cmd("Console.enable")
        self._cmd("Page.addScriptToEvaluateOnNewDocument", {"source": _IDLE_TRACKER})

    def _cmd(self, method: str, params: dict | None = None, *, timeout: float = 15.0) -> dict:
        self._id += 1
        mid = self._id
        self._ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = json.loads(self._ws.recv())
            if msg.get("method") in ("Runtime.consoleAPICalled", "Console.messageAdded"):
                self._record_console(msg)
                continue
            if msg.get("method") == "Runtime.exceptionThrown":
                d = msg["params"]["exceptionDetails"]
                self._console.append("EXCEPTION: " + d.get("text", json.dumps(d))[:500])
                continue
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method} -> {msg['error']}")
                return msg.get("result", {})
        raise TimeoutError(f"{method} timed out")

    def _record_console(self, msg: dict) -> None:
        p = msg["params"]
        if msg["method"] == "Console.messageAdded":
            m = p["message"]
            if m.get("level") in ("error", "warning"):
                self._console.append(f"{m['level']}: {m.get('text', '')}"[:500])
        else:  # Runtime.consoleAPICalled
            if p.get("type") in ("error", "warning"):
                txt = " ".join(str(a.get("value", a.get("description", ""))) for a in p.get("args", []))
                self._console.append(f"{p['type']}: {txt}"[:500])

    def __enter__(self) -> "Browser":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._ws.close()
        if self._shared is not None:
            self._shared.close_context(self._ctx)
        elif self._proc is not None:
            _kill_browser(self._proc)

    # -- actions --
    def navigate(self, url: str) -> None:
        before = None
        with contextlib.suppress(Exception):
            before = (self.eval("location.href.split('#')[0]"), self.eval("performance.timeOrigin"))
        self._cmd("Page.navigate", {"url": url})
        # A different document (anything but a pure #fragment change) must actually have replaced the
        # old one before we judge "idle" — otherwise we'd be asking the page we just left.
        if before and url.split("#")[0] == before[0] and "#" in url:
            pass  # same-document hash navigation: no new document to wait for
        elif before:
            deadline = time.time() + 5
            while time.time() < deadline:
                try:
                    if self.eval("performance.timeOrigin") != before[1]:
                        break
                except Exception:
                    pass
                time.sleep(0.02)
        self._settle()

    def _settle(self, ms: int = 700) -> None:
        """Wait until the page is idle (loaded, no fetch/XHR/short timer in flight, DOM quiet for
        60 ms) — at most ``ms``, which is what this used to sleep unconditionally. SPA has no
        reliable load event per hash change, hence the injected tracker (`_IDLE_TRACKER`). The
        50 ms floor lets handlers deferred to the next frame start their work before we look."""
        time.sleep(0.05)
        deadline = time.time() + ms / 1000
        while time.time() < deadline:
            try:
                if self.eval(_IS_IDLE):
                    return
            except Exception:
                pass  # mid-navigation: the execution context is gone; try again
            time.sleep(0.025)

    def eval(self, expression: str):
        res = self._cmd(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        if res.get("exceptionDetails"):
            raise RuntimeError("JS error: " + res["exceptionDetails"].get("text", "?"))
        return res.get("result", {}).get("value")

    def wait_for(self, selector: str, *, timeout: float = 8.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.eval(f"!!document.querySelector({json.dumps(selector)})"):
                return
            time.sleep(0.05)
        raise TimeoutError(f"selector not found: {selector}")

    def text(self, selector: str) -> str:
        return self.eval(
            f"(document.querySelector({json.dumps(selector)})||{{}}).textContent || ''"
        )

    def html(self, selector: str = "body") -> str:
        return self.eval(
            f"(document.querySelector({json.dumps(selector)})||document.body).outerHTML"
        )

    def fill(self, selector: str, value: str, *, nth: int = 0) -> None:
        self.eval(
            f"(function(){{var e=document.querySelectorAll({json.dumps(selector)})[{nth}];"
            f"e.value={json.dumps(value)};"
            "e.dispatchEvent(new Event('input',{bubbles:true}));"
            "e.dispatchEvent(new Event('change',{bubbles:true}));"
            "e.dispatchEvent(new Event('blur',{bubbles:true}));}())"
        )
        self._settle(250)

    def click(self, selector: str, *, nth: int = 0, contains: str | None = None) -> None:
        if contains is not None:
            js = (
                f"Array.from(document.querySelectorAll({json.dumps(selector)}))"
                f".filter(function(e){{return e.textContent.indexOf({json.dumps(contains)})>=0;}})[{nth}]"
            )
        else:
            js = f"document.querySelectorAll({json.dumps(selector)})[{nth}]"
        self.eval(f"(function(){{var e={js}; if(!e) throw new Error('no element to click'); e.click();}}())")
        self._settle()

    def screenshot(self, path: str) -> None:
        data = self._cmd("Page.captureScreenshot", {"format": "png"})["data"]
        with open(path, "wb") as fh:
            fh.write(base64.b64decode(data))

    def console_errors(self) -> list[str]:
        return list(self._console)


def _main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    url = argv[0]
    with Browser(url) as b:
        b._settle(1500)
        sys.stdout.write(b.html("body"))
        errs = b.console_errors()
        if errs:
            sys.stderr.write("\n\nCONSOLE ERRORS:\n" + "\n".join(errs) + "\n")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
