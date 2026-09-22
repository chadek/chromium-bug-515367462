#ifndef STUB_BASE_NOTREACHED_H_
#define STUB_BASE_NOTREACHED_H_
#include <cstdlib>
#include <iostream>
namespace base_stub {
[[noreturn]] inline void NotReached(const char* where) {
  std::cerr << "NOTREACHED at " << where << "\n";
  std::abort();
}
}  // namespace base_stub
#define NOTREACHED() ::base_stub::NotReached(__FILE__)
#endif
