#!/usr/bin/env bash
# Prints the ID of the simulator to build and test on: the one named by the first argument, or by
# SIMULATOR_NAME, or else the newest available iPhone simulator.
set -euo pipefail

name="${1:-${SIMULATOR_NAME:-}}"
devices=$(xcrun simctl list devices available)

if [ -n "$name" ]; then
  line=$(printf '%s\n' "$devices" | grep -F -- " $name (" | tail -n 1 || true)
else
  line=$(printf '%s\n' "$devices" | grep -E '^ +iPhone ' | tail -n 1 || true)
fi

id=$(printf '%s\n' "$line" | grep -Eo '[0-9A-Fa-f]{8}(-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}' | tail -n 1 || true)
if [ -z "$id" ]; then
  if [ -n "$name" ]; then
    echo "No available iOS simulator matched SIMULATOR_NAME=$name" >&2
  else
    echo "No available iPhone simulator found. Install a simulator runtime in Xcode or set SIMULATOR_NAME." >&2
  fi
  exit 1
fi
echo "$id"
