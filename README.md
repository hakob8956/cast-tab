# cast-tab

Play the video from your browser tab on the TV — only the video, not the screen — with one hotkey, and control it from anywhere on the Mac.

Built for a Samsung TV with Google Cast (S85F), Arc browser and Raycast. Works with any Google Cast receiver (Chromecast, Android/Google TV, Samsung 2025+, LG with Cast) and any Chromium browser.

> Why Cast and not AirPlay? Samsung's AirPlay only implements "AirPlay Video V2", an undocumented Apple protocol; every open-source AirPlay sender gets `404` from it. The TV's Google Cast works fine, and Chrome-family browsers speak Cast natively, so everything here is Cast.

## What it does

- `cast-tab` — video in the front tab → TV, **starting where the page is**; the page video pauses (no double audio)
- `cast-tab back` — stop the TV and **continue in the page** from the TV position
- play/pause, ±10 s, volume, mute, stop, status — from Raycast hotkeys
- `cast-tab clip` / `cast-tab <url>` — cast a page URL (yt-dlp) or a stream URL (`.m3u8` / `.mpd` / `.mp4`)
- subtitles: the track loaded in the page player is attached on the TV (`.srt` is converted to WebVTT on the way)
- TV shows a real title (`Show · Season 4 · Episode 21`)
- while the TV plays, a background watcher keeps the Mac awake and one Cast connection up, loads the video again at the same position if the TV's player fails or makes no progress for 45 s (up to 3 times in 15 min), and reconnects after Wi-Fi drops or Mac sleep

### How it finds the stream — any site
1. **The page's player.** `tab-media` asks the tab (AppleScript + JS) what it is playing: the `<video>`'s own source, what known players (video.js, JW Player, …) report, and every playlist or video file the page fetched — by URL, by the content type the browser exposes, or by a look at the first bytes of playlists served without an extension. Newest wins, so switching episodes without a reload works. The subtitle track comes along. The TV then plays exactly that stream, from the page position. If the video hasn't been started yet, the script presses play for you.
   - **Stream server that refuses the TV** (wants the page as `Referer`, a browser `User-Agent`): the TV gets the stream through a small proxy on this Mac (part of the watcher) — manifests rewritten, segments, keys and byte ranges passed through, CORS added. The Mac must stay on the network while that plays; the watcher keeps it from idle-sleeping.
   - **Player in a cross-origin iframe:** the frame is opened in its own tab for a few seconds to read its stream, then closed again.
2. **yt-dlp** (bundled in catt) comes first for the sites it does best — YouTube (plays in the TV's own app), Vimeo, Twitch, Twitter/X, TikTok, Reddit, … (`YTDLP_SITES` in `bin/cast-tab`) — and is the fallback when the page's player shows nothing castable. Sites yt-dlp can't do (`PAGE_PLAYER_SITES`: rezka etc.) skip it.

Quality = whatever the page player is using at cast time (pick it in the player, then cast).

### Won't work
- DRM (Netflix, Prime, Disney+, Apple TV+, Max…) — use their own cast button
- streams tied to your login cookies (the server refuses even with the page's headers) — the proxy sends `Referer`/`Origin`/`User-Agent`, not cookies
- a player frame that refuses to load outside its page

## Install

```bash
git clone git@github.com:hakob8956/cast-tab.git && cd cast-tab && ./install.sh
```

Requirements: macOS, [Homebrew](https://brew.sh), Arc / Chrome / Brave / Edge / Chromium / Vivaldi, TV with Google Cast on the same Wi-Fi. Raycast optional.
Chrome-family (not Arc): enable **View → Developer → Allow JavaScript from Apple Events** so `tab-media` can read the player.
First run asks macOS to let Terminal/Raycast control the browser — allow it. If the macOS firewall is on, allow catt's `python` to accept incoming connections (the proxy).

Config: `~/.config/cast-tab/config` → `CAST_TV=<ip>` (see `config.example`; `catt scan` lists devices). If the TV's IP changes (DHCP), the next cast finds it again and updates the config. Optional: `CAST_KEEP_AWAKE=0` lets the Mac idle-sleep while the TV plays (no watcher reloads, no proxy then).

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
cast-tab <url>            # a yt-dlp URL, or a stream URL (.m3u8 / .mpd / .mp4)
cast-tab clip             # URL from clipboard
cast-tab back             # TV → back to the page
cast-tab toggle | play | pause | stop | status | info | skip
cast-tab rewind [s] | ffwd [s] | seek <s> | volume <0-100> | volumeup [d] | volumedown [d] | volumemute

tab-media urls|info|frames|play|pause|seek <s>|settime <s>|open <url>|close <ids> [App]   # low-level: the tab's player
cast-ctl <ip> load <url> [-t type] [-l title] [-s sec] [-c subs] | watch | status | …      # low-level: the TV (catt's python)
```

## Troubleshooting
- Video stopped in the middle — see `~/Library/Logs/cast-tab.log`: `player error` / `no progress for … — loading the video again` (automatic, at most 3 times in 15 min), `frozen` (a stall, and for how long), `player closed on the TV` (remote, or the TV closed it — it closes a paused player after 20 min), `stopped (session gone)` (the TV dropped the media session), `TV connection LOST` / `CONNECTED` (reconnected), `TV unreachable for 10 min`.
- `Stream server wants the page's headers … — the TV gets it through this Mac` — a proxied stream: the Mac must stay on the network and awake (the watcher holds off idle sleep; a closed lid still sleeps it, and the TV then stalls).
- `Stream server answered 403 to a test fetch (403 with the page's headers) — trying the TV anyway` — the stream is tied to cookies or the TV's address; expect black on the TV. Nothing to do.
- `Looking into the player frame: …` — the player sits in an iframe; a tab opens and closes by itself. If the frame refuses to load on its own, open it in a tab yourself and cast from there.
- `No stream found in the tab` — DRM, or the video never started. Press play in the page and retry.
- `Arc blocks scripts: enable View → Developer → Allow JavaScript from Apple Events` — Chrome-family setting; Arc does not need it.
- `TV refuses the Cast connection` / `TV Cast service restarting — waiting…` — Samsung drops its Cast service for 1–2 min after a session ends. Casting waits up to 90 s for it; the remote commands say so and return.
- `TV moved: <old> → <new> (config updated)` — DHCP gave the TV another address; nothing to do.
- A remote command says `TV did not answer` or `Lost the connection to the TV` — it did not get through; press again.
- `Failed to determine cast type` warnings from catt are harmless (Samsung lacks one Chromecast info endpoint); the scripts filter them.
- Remote commands are instant only with an IP in `CAST_TV`; with a Cast name they go through catt (~2.5 s each), and streams go direct without the proxy.

## Files
- `bin/cast-tab` — main command
- `bin/tab-media` — AppleScript/JS bridge to the browser tab's player
- `bin/cast-ctl` — fast remote (play/pause/seek/volume/status), `load` (a stream straight to the TV's player, no probing), the `watch`er that runs in the background after each cast (log, keep-awake, reloads) and the stream proxy that lives inside it; over a direct Cast socket, with one lock around every write (pychromecast writes from two threads otherwise). YouTube casts play in the TV's own app and are not watched
- `raycast/*.sh` — Raycast script commands (thin wrappers around cast-tab)
- `install.sh`, `config.example`
- `test/` — a fake TV (`fake_tv.py`: scriptable Cast receiver, can lose connections, go deaf, fail or stall its player, ping like Samsung) and tests that run cast-ctl and cast-tab against it (plus a fake browser, a fake catt, a Referer-locked origin server): `$(head -1 ~/.local/bin/catt | cut -c3-) test/test_cast_ctl.py [--soak]`, same for `test_cast_tab.py`. Both bind port 8009: one at a time. `--soak` adds 90 s at real timings with the TV pinging every 10 s.
