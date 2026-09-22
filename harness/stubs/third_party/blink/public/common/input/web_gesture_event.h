#ifndef STUB_BLINK_WEB_GESTURE_EVENT_H_
#define STUB_BLINK_WEB_GESTURE_EVENT_H_
#include <cstring>

namespace blink {

enum class WebGestureDevice {
  kUninitialized = 0,
  kTouchpad,
  kTouchscreen,
  kSyntheticAutoscroll,
  kScrollbar,
};

class WebPointerProperties {
 public:
  enum class PointerType { kUnknown = 0, kMouse, kPen, kEraser, kTouch };
};

class WebInputEvent {
 public:
  // Only the gesture types TouchActionFilter switches on are needed here; the
  // numeric values are irrelevant to its logic.
  enum class Type {
    kUndefined = 0,
    kGestureScrollBegin,
    kGestureScrollEnd,
    kGestureScrollUpdate,
    kGestureFlingStart,
    kGestureFlingCancel,
    kGesturePinchBegin,
    kGesturePinchEnd,
    kGesturePinchUpdate,
    kGestureTapDown,
    kGestureShowPress,
    kGestureTap,
    kGestureTapCancel,
    kGestureLongPress,
    kGestureLongTap,
    kGestureTwoFingerTap,
    kGestureTapUnconfirmed,
    kGestureDoubleTap,
  };
  enum Modifiers { kNoModifiers = 0 };

  Type GetType() const { return type_; }
  void SetType(Type type) { type_ = type; }

 protected:
  Type type_ = Type::kUndefined;
};

class WebGestureEvent : public WebInputEvent {
 public:
  WebGestureEvent() { std::memset(&data, 0, sizeof(data)); }

  WebGestureDevice SourceDevice() const { return source_device_; }
  void SetSourceDevice(WebGestureDevice device) { source_device_ = device; }

  WebPointerProperties::PointerType primary_pointer_type =
      WebPointerProperties::PointerType::kTouch;

  // Mirrors the shape of blink's union; TouchActionFilter only ever reads the
  // member matching the event type.
  union {
    struct {
      float delta_x_hint;
      float delta_y_hint;
      int pointer_count;
      bool cursor_control;
    } scroll_begin;
    struct {
      float delta_x;
      float delta_y;
    } scroll_update;
    struct {
      int tap_count;
    } tap;
    struct {
      int tap_down_count;
    } tap_down;
  } data;

 private:
  WebGestureDevice source_device_ = WebGestureDevice::kTouchscreen;
};

}  // namespace blink
#endif
