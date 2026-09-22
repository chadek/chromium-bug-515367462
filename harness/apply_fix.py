#!/usr/bin/env python3
"""Applies the crbug.com/515367462 fix to a Chromium source tree.

Single source of truth for the change: run.sh uses it to patch the harness
copy, and `--emit-patch` turns it into the diff to upload to Gerrit.

    ./apply_fix.py <tree>                # edit in place
    ./apply_fix.py <tree> --emit-patch   # edit, then print a unified diff
"""
import argparse, difflib, os, shutil, subprocess, sys, tempfile

FILTER_H = "components/input/touch_action_filter.h"
FILTER_CC = "components/input/touch_action_filter.cc"
ROUTER_CC = "components/input/input_router_impl.cc"
UNITTEST = "components/input/touch_action_filter_unittest.cc"


# --- the edits --------------------------------------------------------------

H_ANCHOR = """  void IncreaseActiveTouches();
  void DecreaseActiveTouches();
"""

H_NEW = """  void IncreaseActiveTouches();
  void DecreaseActiveTouches();

  // Drops an active-touch count that can never be decremented, resetting the
  // touch action if that leaves no touches active. Called by InputRouterImpl
  // once the touch event queue has drained: no further touch acks are coming
  // at that point, so any count still outstanding belongs to a touch sequence
  // the platform abandoned without a terminal touchend/touchcancel.
  void ResetActiveTouchesIfStale();
"""

CC_ANCHOR = """void TouchActionFilter::ReportAndResetTouchAction() {"""

CC_NEW = """void TouchActionFilter::ResetActiveTouchesIfStale() {
  if (num_of_active_touches_ <= 0) {
    return;
  }
  // The touch queue has drained, so every sequence we counted has been fully
  // acked -- except one that never produced a terminal touchend or
  // touchcancel. Several browser-side paths can swallow the rest of a
  // sequence: on Android, RenderWidgetHostViewAndroid::OnTouchEvent() drops
  // the event outright whenever the gesture provider rejects it, which is what
  // an OEM system gesture (e.g. the three-finger screenshot on some devices)
  // triggers when it claims the gesture mid-sequence.
  //
  // Left alone, the leaked count stops ReportAndResetTouchAction() from ever
  // resetting again, so the first touch-action: none element the user touches
  // afterwards pins |allowed_touch_action_| to kNone and scrolling stays dead
  // for the lifetime of the widget.
  TRACE_EVENT1("input", "TouchActionFilter::ResetActiveTouchesIfStale", "num",
               num_of_active_touches_);
  num_of_active_touches_ = 0;
  ReportAndResetTouchAction();
}

void TouchActionFilter::ReportAndResetTouchAction() {"""

ROUTER_ANCHOR = """  if (event.event.IsTouchSequenceEnd()) {
    touch_action_filter_.DecreaseActiveTouches();
    touch_action_filter_.ReportAndResetTouchAction();
    UpdateTouchAckTimeoutEnabled();
  }"""

ROUTER_NEW = """  if (event.event.IsTouchSequenceEnd()) {
    touch_action_filter_.DecreaseActiveTouches();
    touch_action_filter_.ReportAndResetTouchAction();
    // The acked event has already been removed from the queue, so an empty
    // queue here means no more touch acks are coming. Any active-touch count
    // still outstanding belongs to a sequence that was abandoned without a
    // terminal touchend/touchcancel and would otherwise pin the touch action
    // forever, permanently disabling scrolling.
    if (touch_event_queue_.Empty()) {
      touch_action_filter_.ResetActiveTouchesIfStale();
    }
    UpdateTouchAckTimeoutEnabled();
  }"""

TEST_ANCHOR = """// If the renderer is busy, the gesture event might have come before the"""

TEST_NEW = '''// Regression test for crbug.com/515367462. If a touch sequence is abandoned
// without a terminal touchend/touchcancel -- which happens when a browser-side
// path swallows the rest of the sequence, e.g. an Android OEM system gesture
// claiming a three-finger press -- its DecreaseActiveTouches() never runs. The
// leaked count must not keep the touch action pinned forever, otherwise the
// next touch-action: none element the user touches disables scrolling for good.
TEST_F(TouchActionFilterTest, AbandonedTouchSequenceDoesNotPinTouchAction) {
  filter_.OnHasTouchEventHandlers(true);

  // A touch sequence starts and is acked, then is abandoned: no touch end ack.
  filter_.OnSetTouchAction(cc::TouchAction::kAuto);
  filter_.IncreaseActiveTouches();

  // The user now touches a touch-action: none region and lifts off. The touch
  // queue has drained by the time this end ack is handled.
  filter_.OnSetTouchAction(cc::TouchAction::kNone);
  filter_.IncreaseActiveTouches();
  filter_.DecreaseActiveTouches();
  filter_.ReportAndResetTouchAction();
  filter_.ResetActiveTouchesIfStale();

  EXPECT_FALSE(filter_.allowed_touch_action().has_value());

  // Scrolling must work again on the next sequence.
  filter_.OnSetTouchAction(cc::TouchAction::kAuto);
  filter_.IncreaseActiveTouches();
  WebGestureEvent scroll_begin =
      SyntheticWebGestureEventBuilder::BuildScrollBegin(0, -5, kSourceDevice);
  WebGestureEvent scroll_update =
      SyntheticWebGestureEventBuilder::BuildScrollUpdate(0, -5, 0,
                                                         kSourceDevice);
  WebGestureEvent scroll_end = SyntheticWebGestureEventBuilder::Build(
      WebInputEvent::Type::kGestureScrollEnd, kSourceDevice);
  EXPECT_EQ(filter_.FilterGestureEvent(&scroll_begin),
            FilterGestureEventResult::kAllowed);
  EXPECT_EQ(filter_.FilterGestureEvent(&scroll_update),
            FilterGestureEventResult::kAllowed);
  EXPECT_EQ(filter_.FilterGestureEvent(&scroll_end),
            FilterGestureEventResult::kAllowed);
  filter_.DecreaseActiveTouches();
  filter_.ReportAndResetTouchAction();
}

// A count that is still legitimately outstanding -- the ack for a second touch
// start arriving before the ack for the first touch end -- must be left alone.
TEST_F(TouchActionFilterTest, StaleResetLeavesLiveTouchesAlone) {
  filter_.OnHasTouchEventHandlers(true);
  filter_.OnSetTouchAction(cc::TouchAction::kPanY);
  filter_.IncreaseActiveTouches();
  filter_.OnSetTouchAction(cc::TouchAction::kPan);
  filter_.IncreaseActiveTouches();

  // First touch end acked; the second sequence is still in the queue, so
  // InputRouterImpl would not call ResetActiveTouchesIfStale() here.
  filter_.DecreaseActiveTouches();
  filter_.ReportAndResetTouchAction();
  EXPECT_TRUE(filter_.allowed_touch_action().has_value());
  EXPECT_EQ(filter_.allowed_touch_action().value(), cc::TouchAction::kPanY);

  filter_.DecreaseActiveTouches();
  filter_.ReportAndResetTouchAction();
  filter_.ResetActiveTouchesIfStale();
  EXPECT_FALSE(filter_.allowed_touch_action().has_value());
}

// If the renderer is busy, the gesture event might have come before the'''


EDITS = [
    (FILTER_H, H_ANCHOR, H_NEW, True),
    (FILTER_CC, CC_ANCHOR, CC_NEW, True),
    (ROUTER_CC, ROUTER_ANCHOR, ROUTER_NEW, False),
    (UNITTEST, TEST_ANCHOR, TEST_NEW, False),
]


def apply(tree, verbose=True):
    """Apply every edit whose target file exists in |tree|. Returns the list
    of (relpath, before, after) actually changed."""
    changed = []
    for rel, anchor, new, required in EDITS:
        path = os.path.join(tree, rel)
        if not os.path.exists(path):
            if required:
                sys.exit(f"missing required file: {path}")
            if verbose:
                print(f"  skip   {rel} (not in this tree)")
            continue
        before = open(path, encoding="utf-8").read()
        if new.strip() in before:
            if verbose:
                print(f"  already {rel}")
            continue
        if before.count(anchor) != 1:
            sys.exit(f"anchor matched {before.count(anchor)}x in {rel}; "
                     "upstream has moved -- update apply_fix.py")
        after = before.replace(anchor, new, 1)
        open(path, "w", encoding="utf-8").write(after)
        changed.append((rel, before, after))
        if verbose:
            print(f"  patch  {rel}")
    return changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tree")
    ap.add_argument("--emit-patch", metavar="FILE", default=None)
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args()

    changed = apply(args.tree, verbose=not args.quiet)

    if args.emit_patch:
        out = []
        for rel, before, after in changed:
            out.extend(difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"a/{rel}", tofile=f"b/{rel}"))
        with open(args.emit_patch, "w", encoding="utf-8") as f:
            f.writelines(out)
        if not args.quiet:
            print(f"wrote {args.emit_patch}")


if __name__ == "__main__":
    main()
