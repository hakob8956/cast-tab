#!/bin/bash
# @raycast.schemaVersion 1
# @raycast.title Cast: Status
# @raycast.mode compact
# @raycast.packageName Cast TV
# @raycast.icon 📺
out=$("$HOME/.local/bin/cast-tab" status 2>&1 | grep -v "Failed to determine")
echo "${out:-nothing playing}" | tail -n 8
