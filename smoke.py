#!/usr/bin/env python3
"""Rig smoke test: can we make the page scroll at all with injected touches?

Tries each candidate touch-injection path so we know which one actually drives
the browser-side gesture pipeline on this build.
"""
import sys, time
from cdp import Browser, Session, Touch

URL = "http://127.0.0.1:8731/index.html"

CANDIDATES = [
    ("default",              []),
    ("SyntheticPointerActions", ["--enable-features=SyntheticPointerActions"]),
    ("no-SyntheticPointerActions", ["--disable-features=SyntheticPointerActions"]),
]

def try_one(name, extra):
    b = Browser(extra_args=["--touch-events=enabled", *extra])
    try:
        s = b.new_page(URL)
        s.send("Runtime.enable")
        s.goto(URL)
        time.sleep(1.0)
        s.eval("window.scrollTo(0,0)")
        time.sleep(0.3)
        before = s.eval("window.scrollY")
        t = Touch(s, settle=0.02)
        # one-finger drag upward on plain background (touch-action: auto)
        t.drag(1, 250, 500, 250, 120, steps=15)
        time.sleep(0.8)
        after = s.eval("window.scrollY")
        touched = s.eval("window.__log.length")
        print(f"  {name:28s} scrollY {before} -> {after}   page events: {touched}")
        return after > before
    finally:
        b.close()

if __name__ == "__main__":
    print("smoke: one-finger drag on background should scroll the page")
    ok = {}
    for name, extra in CANDIDATES:
        try:
            ok[name] = try_one(name, extra)
        except Exception as e:
            print(f"  {name:28s} ERROR {e}")
            ok[name] = False
    print()
    good = [k for k, v in ok.items() if v]
    print("paths that produce scrolling:", good or "NONE")
    sys.exit(0 if good else 1)
