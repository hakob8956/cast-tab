#!/bin/bash
# @raycast.schemaVersion 1
# @raycast.title Cast: Play / Pause
# @raycast.mode silent
# @raycast.packageName Cast TV
# @raycast.icon 📺
out=$("$HOME/.local/bin/cast-tab" toggle 2>&1 | grep -v "Failed to determine")
echo "${out:-⏯ toggled}" | tail -n 1
