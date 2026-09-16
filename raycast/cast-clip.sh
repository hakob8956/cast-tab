#!/bin/bash
# @raycast.schemaVersion 1
# @raycast.title Cast: Clipboard URL
# @raycast.mode silent
# @raycast.packageName Cast TV
# @raycast.icon 📺
out=$("$HOME/.local/bin/cast-tab" clip 2>&1 | grep -v "Failed to determine")
echo "${out:-cast started}" | tail -n 1
