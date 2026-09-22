#ifndef STUB_BASE_CHECK_OP_H_
#define STUB_BASE_CHECK_OP_H_
#include <cstdlib>
#include <iostream>
#include <sstream>
namespace base_stub {
// Swallows the "<< message" that CHECK/DCHECK callers append.
class VoidStream {
 public:
  explicit VoidStream(bool fail, const char* expr) : fail_(fail), expr_(expr) {}
  ~VoidStream() {
    if (fail_) {
      std::cerr << "CHECK failed: " << expr_ << " " << msg_.str() << "\n";
      std::abort();
    }
  }
  template <typename T> VoidStream& operator<<(const T& v) { msg_ << v; return *this; }
 private:
  bool fail_;
  const char* expr_;
  std::ostringstream msg_;
};
}  // namespace base_stub
#define STUB_CHECK(cond) ::base_stub::VoidStream(!(cond), #cond)
#define CHECK(cond) STUB_CHECK(cond)
#define DCHECK(cond) STUB_CHECK(cond)
#define CHECK_EQ(a, b) STUB_CHECK((a) == (b))
#define CHECK_NE(a, b) STUB_CHECK((a) != (b))
#define CHECK_GE(a, b) STUB_CHECK((a) >= (b))
#define CHECK_LE(a, b) STUB_CHECK((a) <= (b))
#define DCHECK_EQ(a, b) STUB_CHECK((a) == (b))
#define DCHECK_NE(a, b) STUB_CHECK((a) != (b))
#define DCHECK_GE(a, b) STUB_CHECK((a) >= (b))
#define DCHECK_LE(a, b) STUB_CHECK((a) <= (b))
#endif
