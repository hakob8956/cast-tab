#!/bin/bash
# @raycast.schemaVersion 1
# @raycast.title Cast: Volume Down
# @raycast.mode silent
# @raycast.packageName Cast TV
# @raycast.icon 📺
out=$("$HOME/.local/bin/cast-tab" volumedown 10 2>&1 | grep -v "Failed to determine")
echo "${out:-🔉 -10}" | tail -n 1
