#!/bin/bash
# @raycast.schemaVersion 1
# @raycast.title Cast: Switch AirPlay ⇄ Chromecast
# @raycast.mode silent
# @raycast.packageName Cast TV
# @raycast.icon 📺
"$HOME/.local/bin/cast-tab" use toggle 2>&1 | tail -n 1
