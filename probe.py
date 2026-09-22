#!/usr/bin/env python3
"""Watch TouchActionFilter's internal state while feeding it touch sequences.

Before trusting any repro attempt, check that the rig actually drives the
browser-side state machine the way the source says it should:
  - IncreaseActiveTouches on the first finger of a sequence
  - DecreaseActiveTouches + ResetTouchAction when the last one lifts
  - SetTouchAction(NONE) while touching the touch-action:none canvas
"""
import sys, time
from cdp import Browser, Session, Touch, browser_session, Trace

from geom import BG, BG2, BG3, CANVAS, check_hit_targets

URL = "http://127.0.0.1:8731/index.html"

WATCH = ("IncreaseActiveTouches", "DecreaseActiveTouches",
         "TouchActionFilter::SetTouchAction", "ResetTouchAction",
         "SetTouchActionFromMain", "Drop Events",
         "No Sequence at GSB!", "Deferring Events")


def interesting(e):
    n = e.get("name", "")
    return any(w in n for w in WATCH)


def fmt(e):
    args = e.get("args") or {}
    extra = " ".join(f"{k}={v}" for k, v in args.items() if k != "src_file")
    return f"    {e.get('name','?'):46s} {extra}"


def scenario(label, body, settle=0.02):
    b = Browser(extra_args=["--touch-events=enabled"])
    try:
        s = b.new_page(URL)
        s.send("Runtime.enable")
        s.goto(URL)
        time.sleep(0.8)
        s.eval("window.scrollTo(0,0)")
        check_hit_targets(s)

        tr = Trace(browser_session(b))
        tr.start("input")
        time.sleep(0.4)

        body(b, s, Touch(s, settle=settle))
        time.sleep(0.6)

        events = tr.stop()
        print(f"\n### {label}")
        shown = [e for e in events if interesting(e)]
        if not shown:
            print("    (no TouchActionFilter trace events seen at all)")
        for e in shown:
            print(fmt(e))
        print(f"    final scrollY = {s.eval('window.scrollY')}")
    finally:
        b.close()


# --- bodies -----------------------------------------------------------------

def plain_scroll(b, s, t):
    t.drag(90, BG[0], BG[1], BG[0], BG[1] - 380, steps=12)


def canvas_then_scroll(b, s, t):
    x, y = CANVAS
    t.down(7, x, y)
    for i in range(1, 6):
        t.move(7, x + i * 6, y + i * 4)
    t.up(7)
    time.sleep(0.3)
    t.drag(90, BG[0], BG[1], BG[0], BG[1] - 380, steps=12)


def three_cancel_canvas_scroll(b, s, t):
    t.down(1, *BG); t.down(2, *BG2); t.down(3, *BG3)
    time.sleep(0.05)
    t.cancel()
    time.sleep(0.2)
    canvas_then_scroll(b, s, t)


def abandon_reattach_canvas_scroll(b, s, t):
    t.down(1, *BG); t.down(2, *BG2); t.down(3, *BG3)
    time.sleep(0.05)
    s2 = b.reattach()
    s2.send("Runtime.enable")
    time.sleep(0.2)
    canvas_then_scroll(b, s2, Touch(s2, settle=0.02))


CASES = {
    "plain-scroll":       plain_scroll,
    "canvas-then-scroll": canvas_then_scroll,
    "3f-cancel":          three_cancel_canvas_scroll,
    "abandon-reattach":   abandon_reattach_canvas_scroll,
}

if __name__ == "__main__":
    wanted = sys.argv[1:] or list(CASES)
    for name in wanted:
        scenario(name, CASES[name])
