#!/bin/bash
# @raycast.schemaVersion 1
# @raycast.title Cast: Back 10s
# @raycast.mode silent
# @raycast.packageName Cast TV
# @raycast.icon 📺
out=$("$HOME/.local/bin/cast-tab" rewind 10 2>&1 | grep -v "Failed to determine")
echo "${out:-⏪ -10s}" | tail -n 1
