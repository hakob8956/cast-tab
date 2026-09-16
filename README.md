# cast-tab

Play the video from your browser tab on the TV — only the video, not the screen — with one hotkey, and control it from anywhere on the Mac.

Built for a Samsung TV with Google Cast (S85F), Arc browser and Raycast. Works with any Google Cast receiver (Chromecast, Android/Google TV, Samsung 2025+, LG with Cast) and any Chromium browser.

> Why Cast and not AirPlay? Samsung's AirPlay only implements "AirPlay Video V2", an undocumented Apple protocol; every open-source AirPlay sender gets `404` from it. The TV's Google Cast works fine, and Chrome-family browsers speak Cast natively, so everything here is Cast.

## What it does

- `cast-tab` — video in the front tab → TV, **starting where the page is**; the page video pauses (no double audio)
- `cast-tab back` — stop the TV and **continue in the page** from the TV position
- play/pause, ±10 s, volume, mute, stop, status — from Raycast hotkeys
- `cast-tab clip` — cast the URL in the clipboard
- subtitles: the track loaded in the page player is attached on the TV
- TV shows a real title (`Show · Season 4 · Episode 21`)

### How it finds the stream
1. **yt-dlp** (bundled in catt) for the ~1800 sites it knows: YouTube, Vimeo, Twitter/X, Reddit, TikTok, Twitch VODs…
2. Otherwise **straight from the page's player**: `tab-media` asks the tab (AppleScript + JS) which `.m3u8`/`.mp4` the player loaded and casts that URL directly. Newest stream wins, so switching episodes without a reload works. If the video hasn't been started yet, the script presses play for you. Sites known to need this path (rezka etc.) skip step 1 (`PAGE_PLAYER_SITES` in `bin/cast-tab`).

Quality = whatever the page player is using at cast time (pick it in the player, then cast).

### Won't work
- DRM (Netflix, Prime, Disney+, Apple TV+, Max…) — use their own cast button
- player inside a cross-origin iframe — open the frame in its own tab first
- streams locked to your login session (TV fetches on its own → 403)

## Install

```bash
git clone git@github.com:hakob8956/cast-tab.git && cd cast-tab && ./install.sh
```

Requirements: macOS, [Homebrew](https://brew.sh), Arc / Chrome / Brave / Edge, TV with Google Cast on the same Wi-Fi. Raycast optional.
Chrome-family (not Arc): enable **View → Developer → Allow JavaScript from Apple Events** so `tab-media` can read the player.
First run asks macOS to let Terminal/Raycast control the browser — allow it.

Config: `~/.config/cast-tab/config` → `CAST_TV=<ip>` (see `config.example`; `catt scan` lists devices).

### Raycast
Settings → search **Script Commands** → **Add Directories** → `~/RaycastScripts/cast-tv`. Then set hotkeys, e.g.

| Command | Hotkey |
|---|---|
| Cast: Current Tab | ⌃⌥C |
| Cast: Play / Pause | ⌃⌥Space |
| Cast: Back 10s / Forward 10s | ⌃⌥← / ⌃⌥→ |
| Cast: Volume Up / Down | ⌃⌥↑ / ⌃⌥↓ |
| Cast: Mute / Unmute | ⌃⌥M |
| Cast: Stop | ⌃⌥S |
| Cast: Back to Mac | ⌃⌥B |
| Cast: Clipboard URL | ⌃⌥V |
| Cast: Status | ⌃⌥I |

## Usage

```bash
cast-tab                  # front tab → TV (resumes at page position)
cast-tab <url>            # any yt-dlp URL
cast-tab clip             # URL from clipboard
cast-tab back             # TV → back to the page
cast-tab toggle | play | pause | stop | status | info | skip
cast-tab rewind [s] | ffwd [s] | seek <s> | volume <0-100> | volumeup [d] | volumedown [d] | volumemute

tab-media urls|info|play|pause|seek <s> [App]   # low-level: talk to the tab's video player
```

## Troubleshooting
- `TV Cast service restarting — waiting…` — Samsung drops its Cast service for 1–2 min after a session ends; the script waits up to 90 s.
- `No stream found in the tab` — DRM, iframe player, or the video never started. Press play in the page and retry.
- TV shows black/error on a page-player site — the CDN refused the TV (needs cookies/referer). Nothing to do.
- `Failed to determine cast type` warnings from catt are harmless (Samsung lacks one Chromecast info endpoint); the scripts filter them.

## Files
- `bin/cast-tab` — main command
- `bin/tab-media` — AppleScript/JS bridge to the browser tab's player
- `raycast/*.sh` — Raycast script commands (thin wrappers around cast-tab)
- `install.sh`, `config.example`
