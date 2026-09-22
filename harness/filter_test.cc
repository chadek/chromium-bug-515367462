// Replays, against the real upstream components/input/touch_action_filter.cc,
// the exact browser-process call sequence that `probe.py` captured from
// Chromium while reproducing crbug.com/515367462.
//
// Build twice: once against pristine upstream (expected RED) and once with
// fix.patch applied (expected GREEN). See run.sh.

#include <cstdio>
#include <string>
#include <vector>

#include "base/trace_event/trace_event.h"
#include "components/input/touch_action_filter.h"
#include "third_party/blink/public/common/input/web_gesture_event.h"

using blink::WebGestureEvent;
using blink::WebInputEvent;

namespace {

int g_failures = 0;
int g_checks = 0;

void Check(bool ok, const std::string& what) {
  ++g_checks;
  if (!ok) {
    ++g_failures;
    std::printf("  FAIL  %s\n", what.c_str());
  } else {
    std::printf("  ok    %s\n", what.c_str());
  }
}

class NoopClient : public input::TouchActionFilterClient {
 public:
  void OnUnconfirmedTapConvertedToTap() override {}
};

// Models the parts of InputRouterImpl / PassthroughTouchEventQueue that drive
// TouchActionFilter, so the replay is one-to-one with input_router_impl.cc.
class RouterModel {
 public:
  RouterModel() : filter_(&client_) { filter_.OnHasTouchEventHandlers(true); }

  // InputRouterImpl::OnTouchEventAck(), IsTouchSequenceStart() branch, plus
  // the SetTouchActionFromMain that the renderer sends for the sequence.
  void AckSequenceStart(cc::TouchAction action) {
    filter_.OnSetTouchAction(action);
    filter_.IncreaseActiveTouches();
  }

  // InputRouterImpl::OnTouchEventAck(), IsTouchSequenceEnd() branch.
  // |queue_empty| is PassthroughTouchEventQueue::Empty() at that moment; the
  // acked event has already been erased from outstanding_touches_ by then.
  void AckSequenceEnd(bool queue_empty = true) {
    filter_.DecreaseActiveTouches();
    filter_.ReportAndResetTouchAction();
#if WITH_FIX
    if (queue_empty) {
      filter_.ResetActiveTouchesIfStale();
    }
#endif
  }

  // A one-finger vertical drag: can the user scroll?
  bool ScrollWorks() {
    WebGestureEvent tap_down;
    tap_down.SetType(WebInputEvent::Type::kGestureTapDown);
    tap_down.data.tap_down.tap_down_count = 1;
    filter_.FilterGestureEvent(&tap_down);

    WebGestureEvent begin;
    begin.SetType(WebInputEvent::Type::kGestureScrollBegin);
    begin.data.scroll_begin.delta_x_hint = 0.f;
    begin.data.scroll_begin.delta_y_hint = -40.f;
    begin.data.scroll_begin.pointer_count = 1;
    auto begin_result = filter_.FilterGestureEvent(&begin);

    WebGestureEvent update;
    update.SetType(WebInputEvent::Type::kGestureScrollUpdate);
    update.data.scroll_update.delta_x = 0.f;
    update.data.scroll_update.delta_y = -40.f;
    auto update_result = filter_.FilterGestureEvent(&update);

    WebGestureEvent end;
    end.SetType(WebInputEvent::Type::kGestureScrollEnd);
    filter_.FilterGestureEvent(&end);

    return begin_result == input::FilterGestureEventResult::kAllowed &&
           update_result == input::FilterGestureEventResult::kAllowed;
  }

  input::TouchActionFilter& filter() { return filter_; }

 private:
  NoopClient client_;
  input::TouchActionFilter filter_;
};

// --- the cases -------------------------------------------------------------

// Sanity: an ordinary sequence on a touch-action:auto region.
void HealthySequence() {
  std::printf("\nHealthySequence\n");
  RouterModel r;
  r.AckSequenceStart(cc::TouchAction::kAuto);
  r.AckSequenceEnd();
  Check(r.ScrollWorks(), "scrolling works after a normal sequence");
}

// Sanity: touching a touch-action:none element blocks scrolling only for that
// sequence, and the page scrolls again afterwards.
void TouchActionNoneIsScopedToItsSequence() {
  std::printf("\nTouchActionNoneIsScopedToItsSequence\n");
  RouterModel r;
  r.AckSequenceStart(cc::TouchAction::kNone);
  Check(!r.ScrollWorks(), "scrolling blocked while on the touch-action:none canvas");
  r.AckSequenceEnd();
  r.AckSequenceStart(cc::TouchAction::kAuto);
  Check(r.ScrollWorks(), "scrolling works again on the next sequence");
  r.AckSequenceEnd();
}

// The existing upstream guarantee (TouchActionFilterTest.
// ResetTouchActionWithActiveTouch): the ack for a second touch start can
// arrive before the ack for the first touch end, and the touch action must not
// be reset until the last finger is really up. The fix must not break this.
void OutOfOrderAcksStillHoldTheTouchAction() {
  std::printf("\nOutOfOrderAcksStillHoldTheTouchAction\n");
  RouterModel r;
  r.AckSequenceStart(cc::TouchAction::kPanY);
  r.AckSequenceStart(cc::TouchAction::kPan);
  // First touch end acked while the second sequence's end is still queued.
  r.AckSequenceEnd(/*queue_empty=*/false);
  Check(r.filter().allowed_touch_action().has_value() &&
            r.filter().allowed_touch_action().value() == cc::TouchAction::kPanY,
        "touch action survives the first end ack");
  r.AckSequenceEnd(/*queue_empty=*/true);
  Check(!r.filter().allowed_touch_action().has_value(),
        "touch action resets once the last end ack arrives");
}

// crbug.com/515367462. A touch sequence is abandoned: the browser never gets a
// terminal touchend/touchcancel for it, so its DecreaseActiveTouches() never
// runs. The leaked count then stops ReportAndResetTouchAction() from ever
// resetting again, and the first touch-action:none element the user touches
// afterwards disables scrolling permanently.
void AbandonedSequenceMustNotFreezeScrolling() {
  std::printf("\nAbandonedSequenceMustNotFreezeScrolling\n");
  RouterModel r;

  // The three-finger system gesture. Its start is acked; nothing else arrives.
  r.AckSequenceStart(cc::TouchAction::kAuto);

  // The user then draws on the canvas (touch-action: none).
  r.AckSequenceStart(cc::TouchAction::kNone);
  r.AckSequenceEnd();

  Check(r.ScrollWorks(), "scrolling works after the canvas interaction");

  // ...and stays working, sequence after sequence.
  for (int i = 0; i < 3; ++i) {
    r.AckSequenceStart(cc::TouchAction::kAuto);
    r.AckSequenceEnd();
    Check(r.ScrollWorks(), "still scrolls on later sequence " + std::to_string(i + 1));
  }
}

}  // namespace

int main() {
#if WITH_FIX
  std::printf("=== touch_action_filter replay  [WITH fix.patch] ===\n");
#else
  std::printf("=== touch_action_filter replay  [pristine upstream] ===\n");
#endif

  HealthySequence();
  TouchActionNoneIsScopedToItsSequence();
  OutOfOrderAcksStillHoldTheTouchAction();
  AbandonedSequenceMustNotFreezeScrolling();

  std::printf("\n%d/%d checks passed\n", g_checks - g_failures, g_checks);
  return g_failures == 0 ? 0 : 1;
}
