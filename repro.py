#!/usr/bin/env python3
"""crbug.com/515367462 -- scroll freeze after a canvas interaction that follows
a system-stolen (cancelled) multi-finger touch sequence.

Each scenario runs in a fresh page, then asks the only question that matters:
*can the user still scroll?*
"""
import sys, time
from cdp import Browser, Session, Touch, browser_session, Trace

URL = "http://127.0.0.1:8731/index.html"

BG     = (250, 520)       # plain background, touch-action: auto
BG2    = (150, 560)
BG3    = (350, 480)
CANVAS = (200, 300)       # inside #canvas, touch-action: none


class Rig:
    def __init__(self):
        self.b = Browser(extra_args=["--touch-events=enabled"])
        self.s = self.b.new_page(URL)
        self.s.send("Runtime.enable")

    def reset(self):
        self.s.goto(URL)
        time.sleep(0.8)
        self.s.eval("window.scrollTo(0,0); window.__clearLog()")
        time.sleep(0.2)

    def touch(self):
        return Touch(self.s, settle=0.02)

    def scroll_delta(self):
        """Try to scroll with a plain one-finger drag on the background."""
        self.s.eval("window.scrollTo(0,0)")
        time.sleep(0.3)
        before = self.s.eval("window.scrollY")
        t = self.touch()
        t.drag(90, 250, 560, 250, 160, steps=15)
        time.sleep(0.8)
        return self.s.eval("window.scrollY") - before

    def close(self):
        self.b.close()


# --- the individual gesture fragments --------------------------------------

def three_finger_then_cancel(t):
    """Android's three-finger-screenshot detector: three pointers go down,
    the system claims the gesture, the app window gets ACTION_CANCEL."""
    t.down(1, *BG)
    t.down(2, *BG2)
    t.down(3, *BG3)
    time.sleep(0.05)
    t.cancel()


def three_finger_then_up(t):
    t.down(1, *BG); t.down(2, *BG2); t.down(3, *BG3)
    time.sleep(0.05)
    t.up(3); t.up(2); t.up(1)


def one_finger_then_cancel(t):
    t.down(1, *BG)
    time.sleep(0.05)
    t.cancel()


def two_finger_then_cancel(t):
    t.down(1, *BG); t.down(2, *BG2)
    time.sleep(0.05)
    t.cancel()


def draw_on_canvas(t):
    x, y = CANVAS
    t.down(7, x, y)
    for i in range(1, 9):
        t.move(7, x + i * 6, y + i * 4)
    t.up(7)


SCENARIOS = [
    ("baseline: nothing before",            []),
    ("canvas draw only",                    [draw_on_canvas]),
    ("3-finger + CANCEL only",              [three_finger_then_cancel]),
    ("3-finger + normal UP, then canvas",   [three_finger_then_up, draw_on_canvas]),
    ("1-finger + CANCEL, then canvas",      [one_finger_then_cancel, draw_on_canvas]),
    ("2-finger + CANCEL, then canvas",      [two_finger_then_cancel, draw_on_canvas]),
    ("3-finger + CANCEL, then canvas  <<<", [three_finger_then_cancel, draw_on_canvas]),
]


def main():
    rig = Rig()
    print(f"{'scenario':42s} {'scrollY delta':>13s}   verdict")
    print("-" * 78)
    failures = []
    try:
        for name, steps in SCENARIOS:
            rig.reset()
            t = rig.touch()
            for step in steps:
                step(t)
            time.sleep(0.2)
            d = rig.scroll_delta()
            frozen = (d == 0)
            print(f"{name:42s} {d:13d}   {'FROZEN' if frozen else 'scrolls'}")
            if frozen:
                failures.append(name)
    finally:
        rig.close()
    print()
    if failures:
        print("scroll is dead after:", *(f"\n  - {f}" for f in failures))
    else:
        print("no scroll freeze observed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
