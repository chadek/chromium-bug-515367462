#!/usr/bin/env bash
# Emits the complete CL diff (all four files) from the pristine upstream copies.
set -eu
cd "$(dirname "$0")"
rm -rf build/cl && mkdir -p build/cl
cp -r upstream/cc upstream/components build/cl/
python3 ./apply_fix.py build/cl --emit-patch build/cl.patch
echo
echo "--- build/cl.patch ---"
wc -l build/cl.patch
