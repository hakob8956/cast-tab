#!/bin/bash
# @raycast.schemaVersion 1
# @raycast.title Cast: Current Tab
# @raycast.mode silent
# @raycast.packageName Cast TV
# @raycast.icon 📺
out=$("$HOME/.local/bin/cast-tab"  2>&1 | grep -v "Failed to determine")
echo "${out:-cast started}" | tail -n 1
