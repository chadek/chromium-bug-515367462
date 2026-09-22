#ifndef STUB_BASE_TRACE_EVENT_TRACE_EVENT_H_
#define STUB_BASE_TRACE_EVENT_TRACE_EVENT_H_
#include <sstream>
#include <string>
#include <vector>

// Records the same trace points the real browser emits, so the harness can
// print a log directly comparable to what `probe.py` captures from Chromium.
namespace trace_stub {

inline std::vector<std::string>& Log() {
  static std::vector<std::string> log;
  return log;
}

inline void Emit(const std::string& s) { Log().push_back(s); }

inline void Record(const char*, const char* name) { Emit(name); }

template <typename V>
void Record(const char*, const char* name, const char* k1, V v1) {
  std::ostringstream o;
  o << name << " " << k1 << "=" << v1;
  Emit(o.str());
}

template <typename V1, typename V2>
void Record(const char*, const char* name, const char* k1, V1 v1,
            const char* k2, V2 v2) {
  std::ostringstream o;
  o << name << " " << k1 << "=" << v1 << " " << k2 << "=" << v2;
  Emit(o.str());
}

}  // namespace trace_stub

#define TRACE_EVENT0(...) ::trace_stub::Record(__VA_ARGS__)
#define TRACE_EVENT1(...) ::trace_stub::Record(__VA_ARGS__)
#define TRACE_EVENT2(...) ::trace_stub::Record(__VA_ARGS__)
#define TRACE_EVENT_INSTANT(...) ::trace_stub::Record(__VA_ARGS__)
#endif
