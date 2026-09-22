# Comment for issue 515367462

I reproduced this outside Android and tracked it down. Repro rig, traces and a
patch: https://github.com/chadek/chromium-bug-515367462

## Root cause

`TouchActionFilter::num_of_active_touches_` leaks.

`InputRouterImpl::OnTouchEventAck()` increments it when a touch **sequence
start** is acked and decrements it when a touch **sequence end** is acked. If a
sequence is ever abandoned — the browser never sees a terminal
`touchend`/`touchcancel` for it — that decrement never happens and the counter
stays above zero permanently.

`ReportAndResetTouchAction()` only resets the touch action when the counter is
`<= 0`. So after a leak, the first `touch-action: none` element the user touches
pins `allowed_touch_action_` to `kNone` forever, and `FilterGestureEvent()`
drops every subsequent `GestureScrollBegin`/`GestureScrollUpdate`.

That is why the report needs *both* steps: the system gesture leaks the count,
and the canvas — the MDN *Using Pointer Events* demo sets `touch-action: none`
on it — latches `kNone`. Either one alone is harmless.

## On Android

`RenderWidgetHostViewAndroid::OnTouchEvent()` returns without calling
`RouteOrForwardTouchEvent()` whenever the gesture provider rejects the event:

```cpp
  ui::FilteredGestureProvider::TouchHandlingResult result =
      protector->OnTouchEvent(event);
  ...
  if (destroy_pending() || !result.succeeded) {
    return false;
  }
```

`FilteredGestureProvider::OnTouchEvent()` reports failure when
`TouchDispositionGestureFilter::OnGesturePacket()` does not return `SUCCESS`,
including the `EMPTY_GESTURE_SEQUENCE` a cancel produces against an
already-empty sequence queue. Several earlier branches of the same function
(touch handles, stylus text selection, overscroll, input transfer to Viz) can
also swallow a terminal event mid-sequence. An OEM three-finger-screenshot
handler claiming the gesture is one way in — which matches this happening on
Ulefone and Oukitel devices but not on stock builds.

## Reproduction

Repro is not Android-specific; the leaking state is in
`components/input`, shared by all platforms. Against stock Chromium
153.0.8010.36 on Linux, injecting an abandoned touch sequence over CDP and then
touching a `touch-action: none` canvas kills scrolling permanently:

```
scenario                                        scroll#1  scroll#2   verdict
----------------------------------------------------------------------------
baseline (no abandoned sequence)                     365       365   scrolls
abandoned 3-finger, no canvas after                  365       365   scrolls
abandoned 1-finger, then canvas                        0         0   FROZEN
abandoned 3-finger, then canvas                        0         0   FROZEN
```

The `input` trace category shows the counter never returning to zero and
`ResetTouchAction` never firing again:

```
TouchActionFilter::IncreaseActiveTouches     num=0     <- abandoned sequence
TouchActionFilter::IncreaseActiveTouches     num=1     <- canvas touch
TouchActionFilter::DecreaseActiveTouches     num=2     <- back to 1, no reset
TouchActionFilter::IncreaseActiveTouches     num=1
TouchActionFilter::DecreaseActiveTouches     num=2
Drop Events (x12)                                      <- every scroll, forever
```

A well-formed `ACTION_CANCEL` is *not* the trigger — it is balanced and the
filter recovers. Only a swallowed sequence leaks.

## Proposed fix

Add `TouchActionFilter::ResetActiveTouchesIfStale()` and call it from
`InputRouterImpl::OnTouchEventAck()` when the touch event queue has drained. The
acked event has already been erased from `outstanding_touches_` at that point,
so an empty queue means no further touch acks are coming and any remaining count
cannot belong to a live sequence.

This preserves `TouchActionFilterTest.ResetTouchActionWithActiveTouch`: when the
ack for a second touch start arrives before the ack for the first touch end, the
queue is not empty, the reset is not called, and the touch action correctly
survives until the last finger is up.

The fix does not depend on which path swallowed the event — it makes the counter
self-correcting, so no lost decrement can wedge the filter permanently.
