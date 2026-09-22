#!/usr/bin/env python3
"""crbug.com/515367462 -- the *abandoned sequence* variant.

repro.py showed that a well-formed touchcancel is harmless: the browser's
active-touch counter goes back to zero and the touch-action state resets.

What the OEM three-finger-screenshot handlers on the reporter's Ulefone /
Oukitel tablets actually do is swallow the rest of the gesture: the fingers
are gone as far as the user is concerned, but the app window never receives a
terminal ACTION_UP or ACTION_CANCEL for them. This script models that, and
then asks whether the user can still scroll.

The browser-process `input` trace category is captured so we can watch
TouchActionFilter::{Increase,Decrease}ActiveTouches and see the counter drift.
"""
import sys, time
from cdp import Browser, Session, Touch, browser_session, Trace

from geom import BG, BG2, BG3, CANVAS, check_hit_targets

URL = "http://127.0.0.1:8731/index.html"

TRACED = ("TouchActionFilter::IncreaseActiveTouches",
          "TouchActionFilter::DecreaseActiveTouches",
          "TouchActionFilter::SetTouchAction",
          "TouchActionFilter::ResetTouchAction")


def drag_scroll(sess, dist=380):
    sess.eval("window.scrollTo(0,0)")
    time.sleep(0.3)
    before = sess.eval("window.scrollY")
    Touch(sess, settle=0.02).drag(90, BG[0], BG[1], BG[0], BG[1] - dist, steps=15)
    time.sleep(0.8)
    return sess.eval("window.scrollY") - before


def draw_on_canvas(t, pid=7):
    x, y = CANVAS
    t.down(pid, x, y)
    for i in range(1, 9):
        t.move(pid, x + i * 6, y + i * 4)
    t.up(pid)


def abandon(t, fingers):
    """Fingers go down; the system then eats the rest of the sequence."""
    pts = [BG, BG2, BG3][:fingers]
    for i, p in enumerate(pts, start=1):
        t.down(i, *p)
    time.sleep(0.05)
    # ...and nothing else ever arrives for pointers 1..fingers.


def run(name, fingers, do_canvas, trace=False):
    b = Browser(extra_args=["--touch-events=enabled"])
    tr = None
    try:
        s = b.new_page(URL)
        s.send("Runtime.enable")
        s.goto(URL)
        time.sleep(0.8)
        check_hit_targets(s)

        if trace:
            tr = Trace(browser_session(b))
            tr.start("input")
            time.sleep(0.3)

        # 1. the abandoned system gesture
        if fingers:
            abandon(Touch(s, settle=0.02), fingers)

        # 2. the OS stops telling the browser about those pointers; the next
        #    thing the browser hears is a brand new finger. Model that with a
        #    fresh DevTools client, whose pointer bookkeeping starts empty.
        s2 = b.reattach()
        s2.send("Runtime.enable")

        # 3. the user draws on the touch-action:none canvas
        if do_canvas:
            draw_on_canvas(Touch(s2, settle=0.02))
            time.sleep(0.2)

        # 4. ...and now tries to scroll. Twice, to see if it ever recovers.
        d1 = drag_scroll(s2)
        d2 = drag_scroll(s2)

        events = tr.stop() if tr else []
        return d1, d2, events
    finally:
        b.close()


SCENARIOS = [
    # name,                                        fingers, canvas
    ("baseline (no abandoned sequence)",                 0, True),
    ("abandoned 3-finger, no canvas after",              3, False),
    ("abandoned 1-finger, then canvas",                  1, True),
    ("abandoned 3-finger, then canvas          <<<",     3, True),
]


def main():
    print(f"{'scenario':46s} {'scroll#1':>9s} {'scroll#2':>9s}   verdict")
    print("-" * 82)
    frozen = []
    for name, fingers, canvas in SCENARIOS:
        d1, d2, _ = run(name, fingers, canvas)
        bad = (d1 == 0 and d2 == 0)
        print(f"{name:46s} {d1:9d} {d2:9d}   {'FROZEN' if bad else 'scrolls'}")
        if bad:
            frozen.append(name)

    print()
    if not frozen:
        print("no scroll freeze observed")
        return 1

    print("scroll is dead after:", *(f"\n  - {f}" for f in frozen))
    print("\n--- browser-process trace for the failing scenario ---")
    _, _, events = run("traced", 3, True, trace=True)
    for e in events:
        if e.get("name") in TRACED:
            args = e.get("args") or {}
            extra = " ".join(f"{k}={v}" for k, v in args.items())
            print(f"  {e['name']:44s} {extra}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
