"""Viewport coordinates used by every script, plus a self-check.

Getting these wrong silently invalidates the whole experiment -- a "canvas"
touch that actually lands on the background reports touch-action AUTO and
nothing latches. So the rig verifies its own hit targets before testing.
"""

CANVAS = (200, 350)      # inside #canvas          (touch-action: none)
BG     = (250, 600)      # inside #bottom          (touch-action: auto)
BG2    = (150, 640)
BG3    = (350, 570)


def check_hit_targets(sess):
    """Raise unless each coordinate hits the element it is supposed to hit."""
    expected = {"canvas": [CANVAS], "background": [BG, BG2, BG3]}
    js = """(() => {
      const at = (x, y) => {
        const e = document.elementFromPoint(x, y);
        return e ? (e.id || e.tagName) : null;
      };
      return JSON.stringify({
        canvas: %s.map(p => at(p[0], p[1])),
        background: %s.map(p => at(p[0], p[1])),
        innerH: innerHeight, innerW: innerWidth,
      });
    })()""" % (repr([list(CANVAS)]), repr([list(BG), list(BG2), list(BG3)]))
    import json
    r = json.loads(sess.eval(js))

    problems = []
    for name in r["canvas"]:
        if name != "canvas":
            problems.append(f"canvas point hit {name!r}, expected 'canvas'")
    for name in r["background"]:
        if name == "canvas":
            problems.append("background point landed on the canvas")
    if r["innerH"] < max(p[1] for p in (BG, BG2, BG3)) + 20:
        problems.append(f"viewport too short: innerHeight={r['innerH']}")
    if problems:
        raise AssertionError("bad rig geometry: " + "; ".join(problems)
                             + f" (viewport {r['innerW']}x{r['innerH']})")
    return r
