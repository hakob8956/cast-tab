#!/bin/bash
# @raycast.schemaVersion 1
# @raycast.title Cast: Mute / Unmute
# @raycast.mode silent
# @raycast.packageName Cast TV
# @raycast.icon 📺
out=$("$HOME/.local/bin/cast-tab" volumemute 2>&1 | grep -v "Failed to determine")
echo "${out:-🔇 toggled}" | tail -n 1
