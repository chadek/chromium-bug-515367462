"""Minimal synchronous Chrome DevTools Protocol client + touch injection helpers.

Runs an asyncio websockets client on a background thread so the test scripts
can stay linear and readable.
"""
import asyncio, itertools, json, os, shutil, socket, subprocess, tempfile, threading, time
import urllib.request
import websockets


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Browser:
    def __init__(self, binary="chromium", extra_args=(), headless=False):
        self.port = _free_port()
        self.profile = tempfile.mkdtemp(prefix="cdp-profile-")
        args = [
            binary,
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self.profile}",
            "--no-first-run", "--no-default-browser-check",
            "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding",
            "--disable-backgrounding-occluded-windows",
            "--force-device-scale-factor=1",
            "--window-size=500,800",
            "--window-position=0,0",
        ]
        if headless:
            args.append("--headless=new")
        args += list(extra_args)
        args.append("about:blank")
        self.args = args
        self.proc = subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env={**os.environ, "LANG": "C"})
        self.ws_url = self._wait_for_devtools()

    def _wait_for_devtools(self, timeout=30):
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{self.port}/json/version", timeout=1) as r:
                    return json.load(r)["webSocketDebuggerUrl"]
            except Exception as e:      # devtools not up yet
                last = e
                time.sleep(0.2)
        raise RuntimeError(f"devtools never came up: {last}")

    def new_page(self, url="about:blank"):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/json/new?{url}", method="PUT")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                info = json.load(r)
        except Exception:
            # Older/newer builds differ on the verb; fall back to the tab that
            # the browser already opened.
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}/json/list", timeout=5) as r:
                tabs = [t for t in json.load(r) if t.get("type") == "page"]
            if not tabs:
                raise
            info = tabs[0]
        self.page_ws_url = info["webSocketDebuggerUrl"]
        return Session(self.page_ws_url)

    def reattach(self):
        """A second DevTools client on the same page.

        Each client gets its own InputHandler, so its notion of which touch
        points are down starts empty -- while the browser's InputRouterImpl
        keeps whatever state the previous client left behind. That is exactly
        what an OEM system-gesture handler does when it swallows the rest of a
        touch sequence: the browser never learns the fingers went away.
        """
        return Session(self.page_ws_url)

    def close(self):
        try:
            self.proc.terminate()
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()
        shutil.rmtree(self.profile, ignore_errors=True)


class Session:
    """One CDP websocket. Synchronous API, asyncio loop on a worker thread."""

    def __init__(self, ws_url):
        self._ids = itertools.count(1)
        self._pending = {}
        self._events = []
        self._lock = threading.Lock()
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(ws_url,), daemon=True)
        self._thread.start()
        if not self._ready.wait(20):
            raise RuntimeError("websocket did not connect")

    def _run(self, ws_url):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._main(ws_url))

    async def _main(self, ws_url):
        async with websockets.connect(ws_url, max_size=64 * 1024 * 1024,
                                      ping_interval=None) as ws:
            self._ws = ws
            self._ready.set()
            try:
                async for raw in ws:
                    msg = json.loads(raw)
                    if "id" in msg:
                        fut = self._pending.pop(msg["id"], None)
                        if fut and not fut.done():
                            fut.set_result(msg)
                    else:
                        with self._lock:
                            self._events.append(msg)
            except Exception:
                pass

    def send(self, method, params=None, timeout=30):
        mid = next(self._ids)
        payload = json.dumps({"id": mid, "method": method, "params": params or {}})
        fut = self._loop.create_future()
        self._pending[mid] = fut

        async def _go():
            await self._ws.send(payload)
        asyncio.run_coroutine_threadsafe(_go(), self._loop).result(timeout)
        msg = asyncio.run_coroutine_threadsafe(
            asyncio.wait_for(asyncio.shield(fut), timeout), self._loop).result(timeout + 5)
        if "error" in msg:
            raise RuntimeError(f"{method}: {msg['error']}")
        return msg.get("result", {})

    def drain_events(self, name=None):
        with self._lock:
            evs = self._events[:]
            self._events.clear()
        return [e for e in evs if name is None or e.get("method") == name]

    # -- convenience ---------------------------------------------------------
    def eval(self, expr, await_promise=False):
        r = self.send("Runtime.evaluate", {
            "expression": expr, "returnByValue": True, "awaitPromise": await_promise})
        if "exceptionDetails" in r:
            raise RuntimeError(r["exceptionDetails"].get("text", str(r["exceptionDetails"])))
        return r["result"].get("value")

    def goto(self, url, timeout=30):
        self.send("Page.enable")
        self.drain_events()
        self.send("Page.navigate", {"url": url})
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.drain_events("Page.loadEventFired"):
                return
            time.sleep(0.05)
        raise RuntimeError("page load timed out")


# ---------------------------------------------------------------------------
# Touch injection
# ---------------------------------------------------------------------------
class Touch:
    """Tracks live touch points and dispatches Input.dispatchTouchEvent.

    CDP wants the *full* set of currently-down points on every touchStart /
    touchMove; touchEnd carries the points that remain; touchCancel carries none.
    """

    def __init__(self, session, settle=0.016):
        self.s = session
        self.points = {}          # id -> (x, y)
        self.settle = settle

    def _pts(self):
        return [{"x": float(x), "y": float(y), "id": i}
                for i, (x, y) in sorted(self.points.items())]

    def _dispatch(self, type_, pts):
        self.s.send("Input.dispatchTouchEvent", {"type": type_, "touchPoints": pts})
        time.sleep(self.settle)

    def down(self, pid, x, y):
        self.points[pid] = (x, y)
        self._dispatch("touchStart", self._pts())

    def move(self, pid, x, y):
        self.points[pid] = (x, y)
        self._dispatch("touchMove", self._pts())

    def up(self, pid):
        self.points.pop(pid, None)
        self._dispatch("touchEnd", self._pts())

    def cancel(self):
        """What Android delivers when the system steals the gesture
        (e.g. the three-finger-screenshot detector firing): ACTION_CANCEL."""
        self.points.clear()
        self._dispatch("touchCancel", [])

    def drag(self, pid, x0, y0, x1, y1, steps=12):
        self.down(pid, x0, y0)
        for i in range(1, steps + 1):
            self.move(pid, x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps)
        self.up(pid)


def browser_session(b):
    """CDP session on the browser target (for the Tracing domain)."""
    return Session(b.ws_url)


class Trace:
    """Collects the browser-process `input` trace category around a scenario."""

    def __init__(self, bsession):
        self.s = bsession

    def start(self, categories="input,benchmark,toplevel"):
        self.s.drain_events()
        self.s.send("Tracing.start", {
            "traceConfig": {"includedCategories": categories.split(","),
                            "recordMode": "recordAsMuchAsPossible"},
            "transferMode": "ReportEvents"})

    def stop(self, timeout=20):
        self.s.send("Tracing.end")
        deadline = time.time() + timeout
        events = []
        while time.time() < deadline:
            for e in self.s.drain_events():
                if e.get("method") == "Tracing.dataCollected":
                    events.extend(e["params"]["value"])
                elif e.get("method") == "Tracing.tracingComplete":
                    return events
            time.sleep(0.05)
        return events
