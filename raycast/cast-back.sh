#!/bin/bash
# @raycast.schemaVersion 1
# @raycast.title Cast: Back to Mac
# @raycast.mode silent
# @raycast.packageName Cast TV
# @raycast.icon 📺
out=$("$HOME/.local/bin/cast-tab" back 2>&1 | grep -v "Failed to determine")
echo "${out:-back on Mac}" | tail -n 1
