# crbug.com/515367462 — scroll freeze after canvas interaction

> Screen scroll freeze after canvas interaction having three-finger screenshot
> system option enabled — Chrome 148.0.7778.167, Android (Ulefone / Oukitel).

A reproduction rig, a root cause, and a fix.

## TL;DR

`TouchActionFilter::num_of_active_touches_` is a plain counter. It is
incremented when a touch **sequence start** is acked and decremented when a
touch **sequence end** is acked. If a sequence is ever abandoned — the browser
never sees a terminal `touchend`/`touchcancel` for it — the decrement is lost
and the counter is stuck above zero **forever**.

`ReportAndResetTouchAction()` only resets the touch action when that counter is
`<= 0`. So once it leaks, the first `touch-action: none` element the user
touches pins `allowed_touch_action_` to `kNone` for the lifetime of the widget,
and `FilterGestureEvent()` drops every `GestureScrollBegin`/`Update` from then
on. Scrolling is dead until the browser is killed — exactly as reported.

The MDN *Using Pointer Events* page in the report is a canvas with
`touch-action: none`, which is what latches the `kNone`.

## Layout

| file | what it does |
| --- | --- |
| `www/index.html` | repro page: scrollable document + MDN-style `touch-action: none` canvas |
| `cdp.py` | DevTools Protocol client, multi-touch injection, browser tracing |
| `geom.py` | shared touch coordinates + a hit-target self-check |
| `smoke.py` | proves injected touches really drive the gesture pipeline |
| `repro.py` | scenario matrix for a *clean* `touchcancel` (not the bug) |
| `repro2.py` | scenario matrix for an *abandoned* sequence (**the bug**) |
| `probe.py` | dumps `TouchActionFilter` trace events while gesturing |
| `harness/` | compiles the real upstream filter, red/green for the fix |

## Running it

Start the page server once:

```sh
(cd www && python3 -m http.server 8731 --bind 127.0.0.1) &
```

Then:

```sh
python3 smoke.py     # rig sanity: a drag must scroll
python3 repro2.py    # the bug
python3 probe.py     # browser-internal trace
./harness/run.sh     # red/green on the real filter source
```

Needs `chromium` on `PATH` and Python `websockets`. Verified against
Chromium 153.0.8010.36 on Linux.

## What the rig shows

`repro2.py`, against stock Chromium:

```
scenario                                        scroll#1  scroll#2   verdict
----------------------------------------------------------------------------
baseline (no abandoned sequence)                     365       365   scrolls
abandoned 3-finger, no canvas after                  365       365   scrolls
abandoned 1-finger, then canvas                        0         0   FROZEN
abandoned 3-finger, then canvas          <<<           0         0   FROZEN
```

Two conditions are both required, which is why the report needs the system
gesture *and* the canvas:

* an abandoned touch sequence, to leak the counter;
* a subsequent touch on a `touch-action: none` element, to latch `kNone`.

The browser's own trace (`probe.py`, `input` category) shows the counter never
returning to zero and `ResetTouchAction` never firing again:

```
TouchActionFilter::IncreaseActiveTouches     num=0     <- system gesture, abandoned
TouchActionFilter::IncreaseActiveTouches     num=1     <- canvas touch
TouchActionFilter::DecreaseActiveTouches     num=2     <- back to 1, no reset
TouchActionFilter::IncreaseActiveTouches     num=1
TouchActionFilter::DecreaseActiveTouches     num=2
TouchActionFilter::IncreaseActiveTouches     num=1
TouchActionFilter::DecreaseActiveTouches     num=2
Drop Events  (x12)                                     <- every scroll, forever
```

Compare a clean `touchcancel`, which is balanced and harmless — `repro.py`
finds no freeze in any scenario. A well-formed `ACTION_CANCEL` is *not* the
bug; a swallowed sequence is.

## Why a sequence gets abandoned on Android

`RenderWidgetHostViewAndroid::OnTouchEvent()` drops the touch outright when the
gesture provider rejects it:

```cpp
  ui::FilteredGestureProvider::TouchHandlingResult result =
      protector->OnTouchEvent(event);
  ...
  if (destroy_pending() || !result.succeeded) {
    return false;              // never reaches RouteOrForwardTouchEvent()
  }
```

`FilteredGestureProvider::OnTouchEvent()` returns `succeeded = false` when
`TouchDispositionGestureFilter::OnGesturePacket()` does not return `SUCCESS` —
including `EMPTY_GESTURE_SEQUENCE`, which is what a `TOUCH_SEQUENCE_CANCEL`
produces when the sequence queue is already empty. Several earlier branches in
the same function (`OnTouchHandleEvent`, `stylus_text_selector_`,
`overscroll_controller_`, `input_transfer_handler_`) also return without
forwarding. Any of them, hit on the terminal event of a sequence, leaks the
count. An OEM three-finger-screenshot handler claiming the gesture mid-sequence
is one way to get there.

Note that the fix does not depend on *which* of those paths swallows the event.
It makes the counter self-correcting, so no lost decrement can wedge the filter
permanently.

## The fix

`harness/apply_fix.py` is the single source of truth; `harness/make_cl.sh`
emits `harness/build/cl.patch`.

A new `TouchActionFilter::ResetActiveTouchesIfStale()` clears a count that can
no longer be decremented, and `InputRouterImpl::OnTouchEventAck()` calls it when
the touch queue has drained — at that point the acked event has already been
erased from `outstanding_touches_`, so an empty queue means no further touch
acks are coming and any remaining count is stale.

This deliberately preserves the guarantee in the existing
`TouchActionFilterTest.ResetTouchActionWithActiveTouch`: when the ack for a
second touch start arrives before the ack for the first touch end, the queue is
*not* empty, the reset is not called, and the touch action correctly survives
until the last finger is up.

## Verification status

* **Reproduction** — verified end-to-end against a stock Chromium build, with
  the browser's own trace confirming the mechanism.
* **Fix logic** — verified by `harness/run.sh`, which compiles the *real*
  upstream `components/input/touch_action_filter.cc` (byte-identical to
  chromium/src `main`) against minimal stubs and replays the captured call
  sequence. Fails on pristine upstream, passes with the patch, and the
  out-of-order-ack case keeps passing.
* **Not verified here** — a full Chromium build. `components_unittests` needs
  far more disk than this machine has free, so
  `touch_action_filter_unittest.cc` and the `input_router_impl.cc` hunk have
  not been compiled or run. A reviewer should run `components_unittests
  --gtest_filter=TouchActionFilterTest.*` before landing.
