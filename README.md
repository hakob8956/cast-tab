# cast-tab

Watch the video from your browser tab on the TV — just the video, full screen, full quality — with one hotkey. Your Mac screen stays yours.

Works with an **Apple TV** (AirPlay) or a **Google Cast TV** (Chromecast, Google/Android TV, Samsung and LG TVs with Cast), on macOS with Arc, Chrome, Brave, Edge, Chromium or Vivaldi.

## What you can do

- **Press one key and the video moves to the TV**, starting where you were. The page pauses, so there's no double sound.
- Play/pause, skip ±10 s, volume, stop — with hotkeys, whichever app is in front.
- **Back to Mac:** stop the TV and keep watching in the browser from the same moment.
- Subtitles shown in the page come along.
- Cast a link from the clipboard (YouTube, Vimeo, Twitch, …).
- If the TV's player fails, the video is loaded again where it was.

## Get started

1. **Install** (needs [Homebrew](https://brew.sh)). In Terminal:
   ```bash
   git clone https://github.com/hakob8956/cast-tab.git && cd cast-tab && ./install.sh
   ```
   The installer looks for your TV and asks which one to use. For an Apple TV it then pairs: type the PIN the TV shows (twice — once for AirPlay, once for the remote).
2. **Chrome, Brave, Edge, Chromium, Vivaldi** (not needed for Arc): in the browser menu turn on **View → Developer → Allow JavaScript from Apple Events**.
3. **Hotkeys** with [Raycast](https://raycast.com): Raycast Settings → search **Script Commands** → **Add Directories** → `~/RaycastScripts/cast-tv`. Then give the commands hotkeys (suggestions below). No Raycast? Use the `cast-tab` commands in Terminal.
4. **Try it:** open a video in the browser, start it, press **⌃⌥C**. The first time, macOS asks whether Raycast (or Terminal) may control the browser — allow it.

## Hotkeys

| To… | Raycast command | Suggested hotkey | Terminal |
|---|---|---|---|
| Send the tab's video to the TV | Cast: Current Tab | ⌃⌥C | `cast-tab` |
| Play / pause | Cast: Play / Pause | ⌃⌥Space | `cast-tab toggle` |
| Back / forward 10 s | Cast: Back 10s / Forward 10s | ⌃⌥← / ⌃⌥→ | `cast-tab rewind` / `cast-tab ffwd` |
| Volume up / down | Cast: Volume Up / Down | ⌃⌥↑ / ⌃⌥↓ | `cast-tab volumeup` / `cast-tab volumedown` |
| Mute (Chromecast only) | Cast: Mute / Unmute | ⌃⌥M | `cast-tab volumemute` |
| Stop | Cast: Stop | ⌃⌥S | `cast-tab stop` |
| Continue on the Mac | Cast: Back to Mac | ⌃⌥B | `cast-tab back` |
| Cast the link in the clipboard | Cast: Clipboard URL | ⌃⌥V | `cast-tab clip` |
| What's playing | Cast: Status | ⌃⌥I | `cast-tab status` |
| Switch Apple TV ⇄ Chromecast | Cast: Switch AirPlay ⇄ Chromecast | ⌃⌥T | `cast-tab use toggle` |

More in Terminal: `cast-tab <link>` (a page or a stream URL), `cast-tab rewind 30`, `cast-tab seek 600` (jump to 10:00), `cast-tab skip` (to the end), `cast-tab use` (which TV is active).

## Which sites work

- **Most sites with a normal video player.** cast-tab takes the stream the page is playing, so the quality is whatever the player uses at that moment — pick it in the player first.
- **YouTube, Vimeo, Twitch, X, TikTok, Reddit** and the other sites [yt-dlp](https://github.com/yt-dlp/yt-dlp) knows. On a Chromecast, YouTube opens in the TV's YouTube app.
- **Doesn't work:** Netflix, Prime Video, Disney+, Apple TV+, Max and other services with copy protection (use their own Cast/AirPlay button); players embedded from another site in a frame; streams that the site only gives to your logged-in browser.

## Apple TV notes

- **Keep the Mac on and on the network while you watch.** An AirPlay video plays only while the Mac holds the connection. cast-tab keeps the Mac from going to sleep by itself, but closing the lid stops the video.
- The Siri Remote works as usual. Back or Home ends the video.
- Wi-Fi hiccup or a stuck player: the video is loaded again at the same spot. When a slow site makes the Apple TV jump back a few seconds after buffering, cast-tab puts it back where it was.
- Subtitles are turned on automatically when possible; if not, swipe down on the Siri Remote → Subtitles.
- Volume: up and down only (the Apple TV presses the TV's volume buttons); no mute.
- YouTube and other yt-dlp sites play over AirPlay, not in the TV's YouTube app. Formats: HLS (`.m3u8`) and MP4.
- Paused for an hour → stopped, so the Mac can sleep.
- Have both kinds of TV? AirPlay is the default; switch with ⌃⌥T or `cast-tab use cast` / `cast-tab use airplay`.
- A Samsung TV's own built-in AirPlay doesn't work with cast-tab (it uses a closed Apple protocol) — use its Google Cast instead.

## Chromecast notes

- After a video ends, Samsung TVs restart their Cast service for a minute or two; cast-tab waits for it.
- If the TV gets a new address on the network, cast-tab finds it again and updates the settings.

## Something wrong?

| You see | What to do |
|---|---|
| `No stream found in the tab` | Press play in the page, then cast again. Copy-protected services and embedded players can't be cast. |
| `Stream server is not answering` | The site's server is slow. Press play in the page, or try again in a minute. |
| `This site must be open in the browser` | That site can't be cast from a link: open it, start the video, press ⌃⌥C. |
| `Allow JavaScript from Apple Events` | Turn it on in the browser: View → Developer (step 2 above). |
| Nothing happens, or `Not authorized to send Apple events` | Allow Raycast/Terminal to control the browser: System Settings → Privacy & Security → Automation. |
| `TV Cast service restarting — waiting…` | Normal on Samsung right after a video; it waits by itself. |
| `TV not reachable` / `Apple TV not reachable` | Is the TV on, and on the same Wi-Fi as the Mac? |
| `Nothing playing on TV` | The remote hotkeys work only while something plays. |
| The video stopped by itself | `~/Library/Logs/cast-tab.log` says why: closed with the remote, connection lost, reloaded, … |

## Settings

The installer writes `~/.config/cast-tab/config` (see `config.example`):

| Line | Meaning |
|---|---|
| `CAST_TV=192.168.1.50` | the Google Cast TV's address (`catt scan` lists them) |
| `CAST_ATV=192.168.1.60` | the Apple TV's address (`atvremote scan` lists them) |
| `CAST_USE=cast` | which one to use when both are set (default: AirPlay) — `cast-tab use` changes it |

Pair the Apple TV again: `cast-tab pair`.

## How it works

- `bin/cast-tab` — the command. For sites yt-dlp knows, yt-dlp finds the video. Otherwise it asks the browser tab (through `bin/tab-media`: AppleScript + JavaScript) which stream (`.m3u8`, `.mp4`, …) and subtitle file the player loaded, and where the video is, and sends that stream to the TV. Sites that yt-dlp can't do are listed in `PAGE_PLAYER_SITES` and go straight to the tab.
- `bin/cast-ctl` — Google Cast: remote commands over a direct Cast connection (~0.1 s instead of catt's ~2.5 s), and a background watcher that logs what the TV does and reloads a failed player (at most 3 times in 15 min).
- `bin/atv-ctl` — Apple TV, with [pyatv](https://pyatv.dev): plays the stream through AirPlay's play queue (tvOS 26 ignores pyatv's `play_url`), and runs a background helper that holds the connection, answers remote commands in ~0.2 s, reloads, undoes the jump back after buffering, and serves subtitles (the Apple TV shows only subtitles that are part of the HLS stream, so the helper hands it a playlist from the Mac with the subtitle file added).
- `raycast/` — the Raycast commands (small wrappers around `cast-tab`). `install.sh`, `config.example`.
- `test/` — a fake Cast TV and tests for it; they were written for a newer Cast version than the one in `bin/` and are out of date.

Low-level commands:

```bash
tab-media urls | info | play | pause | seek <s> [App]                    # the tab's player
cast-ctl <ip> status | toggle | seek <s> | volume <0-100> | watch | …     # Google Cast TV (catt's python)
atv-ctl <ip> pair | load <url> [-s sec] [-l title] [-c subs] | status | … # Apple TV (pyatv's python)
```

Built on [catt](https://github.com/skorokithakis/catt), [pyatv](https://pyatv.dev) and [yt-dlp](https://github.com/yt-dlp/yt-dlp).
