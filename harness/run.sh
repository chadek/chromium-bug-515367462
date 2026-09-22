#!/usr/bin/env bash
# Builds the real upstream components/input/touch_action_filter.cc twice --
# pristine, then with the fix applied -- and replays the browser-process call
# sequence captured from Chromium by probe.py.
#
#   pristine -> expected to FAIL (the bug)
#   patched  -> expected to PASS (the fix)
set -u

cd "$(dirname "$0")"
rm -rf build && mkdir -p build

CXXFLAGS="-std=c++20 -g -O0 -Wall -Wextra -Wno-unused-parameter -Istubs"

for variant in pristine patched; do
  mkdir -p "build/$variant"
  cp -r upstream/cc upstream/components "build/$variant/"
done

echo "### applying the fix to build/patched"
python3 ./apply_fix.py build/patched --emit-patch build/fix.patch || exit 2

echo "### building"
build() {  # $1 = tree, $2 = WITH_FIX, $3 = output
  g++ $CXXFLAGS -DWITH_FIX=$2 -I"$1" \
      filter_test.cc "$1/components/input/touch_action_filter.cc" -o "$3"
}
build build/pristine 0 build/filter_test_pristine || exit 2
build build/patched  1 build/filter_test_patched  || exit 2

echo
./build/filter_test_pristine; pristine_rc=$?
echo
./build/filter_test_patched;  patched_rc=$?

echo
echo "================================================================"
if [ $pristine_rc -ne 0 ] && [ $patched_rc -eq 0 ]; then
  echo "PASS: the replay fails on pristine upstream and passes with the fix."
  exit 0
fi
echo "UNEXPECTED: pristine rc=$pristine_rc (want non-zero), patched rc=$patched_rc (want 0)"
exit 1
