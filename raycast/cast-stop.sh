#!/bin/bash
# @raycast.schemaVersion 1
# @raycast.title Cast: Stop
# @raycast.mode silent
# @raycast.packageName Cast TV
# @raycast.icon 📺
out=$("$HOME/.local/bin/cast-tab" stop 2>&1 | grep -v "Failed to determine")
echo "${out:-⏹ stopped}" | tail -n 1
