#!/bin/bash
# install.sh — set up cast-tab on this Mac: catt (Cast CLI), scripts in ~/.local/bin, Raycast commands, TV config.
set -e
REPO="$(cd "$(dirname "$0")" && pwd)"
BIN="$HOME/.local/bin"; CFG="$HOME/.config/cast-tab/config"; RAY="$HOME/RaycastScripts/cast-tv"

command -v uv >/dev/null || { echo "Installing uv…"; brew install uv; }
command -v catt >/dev/null || [ -x "$BIN/catt" ] || { echo "Installing catt…"; uv tool install catt --python 3.12; }

mkdir -p "$BIN" "$(dirname "$CFG")" "$RAY"
ln -sf "$REPO/bin/cast-tab" "$BIN/cast-tab"
ln -sf "$REPO/bin/tab-media" "$BIN/tab-media"
cp "$REPO"/raycast/*.sh "$RAY/"
echo "Scripts linked into $BIN, Raycast commands copied to $RAY"

if [ ! -f "$CFG" ]; then
  echo; echo "Scanning for Cast devices…"; "$BIN/catt" scan 2>/dev/null | grep -v "Failed to determine" || true
  read -r -p "TV IP address: " ip
  printf 'CAST_TV=%s\n' "$ip" > "$CFG"; echo "Saved to $CFG"
fi
echo "$PATH" | tr ':' '\n' | grep -qx "$BIN" || echo "NOTE: add $BIN to your PATH (e.g. in ~/.zshrc: export PATH=\"\$HOME/.local/bin:\$PATH\")"

cat <<MSG

Done. Raycast: Settings → search "Script Commands" → Add Directories → $RAY, then set hotkeys.
Try: open a video in Arc → cast-tab
MSG
