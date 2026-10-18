# test_cast_tab.py — cast-tab + tab-media + cast-ctl together, against a fake TV, a fake browser (an osascript stand-in
# answering like Arc), a stand-in for catt and one for curl (the stream probe). Nothing real is touched: no TV, no
# browser, no network, no notifications.
# Run with catt's python:  $(head -1 ~/.local/bin/catt | cut -c3-) test/test_cast_tab.py [name-filter]
import os
import stat
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from fake_tv import FakeTV  # noqa: E402

BIN = os.path.join(HERE, "..", "bin")
TMP = tempfile.mkdtemp(prefix="cast-tab-test-")
PAGE = "https://rezka.example/series/1-show.html#t:1-s:1-e:1"
STREAM, SUBS = "https://cdn.example/aaa/1.mp4:hls:manifest.m3u8", "https://cdn.example/aaa/1.vtt"
TITLE = "Шоу “1” · Сезон 1 · Серия 1"
URLS = "subs %s\nhls %s" % (SUBS, STREAM)
YT = "https://www.youtube.com/watch?v="


def script(name, text):
    path = os.path.join(TMP, "bin", name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return path


# the browser: answers System Events, the tab's URL, tab-media's page scripts the way Arc does (a quoted string with
# \n and \" escaped), and makes/closes the helper tab (while it is "open", the page scripts answer for it)
script("osascript", r'''#!/bin/bash
helper="$STUB_DIR/helper-open"
if [ "$1" = "-e" ]; then
  case "$2" in
    *"whose frontmost is true"*)   echo "${FAKE_FRONT:-Arc}" ;;
    *"background only is false"*) echo "${FAKE_RUNNING:-Finder, Arc, Terminal}" ;;
    *"get URL of active tab"*)     echo "$FAKE_PAGE" ;;
    *"display notification"*)      echo "$2" >> "$STUB_DIR/notifications" ;;
  esac
  exit 0
fi
[ "$1" = "-" ] && shift                   # osascript - <args>: the script comes on stdin, then its arguments
cat > "$STUB_DIR/last.applescript"
case "$(cat "$STUB_DIR/last.applescript")" in
  *"make new tab"*) echo "open|$1" >> "$STUB_DIR/tab.calls"; touch "$helper"; echo 'new-tab-id old-tab-id'; exit 0 ;;
  *"close t"*)      echo "close|$1 $2" >> "$STUB_DIR/tab.calls"; rm -f "$helper"; echo ok; exit 0 ;;
esac
[ -n "$FAKE_JS_OFF" ] && { echo "execution error: Executing JavaScript through AppleScript is turned off. (-10000)" >&2; exit 1; }
js="$1"
if [ -e "$helper" ]; then urls="$FAKE_HELPER_URLS"; t="${FAKE_HELPER_TIME-0}"; else urls="$FAKE_URLS"; t="${FAKE_TIME-72}"; fi
[ -e "$STUB_DIR/played" ] && [ ! -e "$helper" ] && [ -n "$FAKE_URLS_AFTER_PLAY" ] && urls="$FAKE_URLS_AFTER_PLAY"
case "$js" in
  *'"time="'*)             kind=info;    out="time=$t\\nduration=1200\\npaused=${FAKE_PAUSED:-1}\\ntitle=$FAKE_TITLE\\nua=FakeBrowser/1.0" ;;
  *getEntriesByType*)      kind=urls;    out="$urls" ;;
  *getBoundingClientRect*) kind=frames;  out="$FAKE_FRAMES" ;;
  *'if(!v.paused)return'*) kind=settime; out=ok ;;
  *'v.muted=false'*)       kind=play;    out=ok; touch "$STUB_DIR/played" ;;
  *'v.currentTime='*)      kind=seek;    out=ok ;;
  *'v.pause()'*)           kind=pause;   out=ok ;;
  *)                       kind=other;   out= ;;
esac
echo "$kind|$(echo "$js" | grep -oE 'currentTime=[0-9]+' | head -1)" >> "$STUB_DIR/tab.calls"
printf '"%s"\n' "$(printf '%s' "$out" | sed 's/"/\\"/g')"
''')
script("pbpaste", '#!/bin/bash\necho "$FAKE_CLIP"\n')
# the stream probe. FAKE_PROBE: open (200 to anyone, default) | referer (403 without -e, 200 with) | closed (403)
script("curl", r'''#!/bin/bash
echo "curl|$*" >> "$STUB_DIR/curl.calls"
ref=0; for a in "$@"; do [ "$a" = "-e" ] && ref=1; done
case "${FAKE_PROBE:-open}" in
  open)    printf 200 ;;
  referer) [ "$ref" = 1 ] && printf 200 || printf 403 ;;
  closed)  printf 403 ;;
esac
''')

# catt: `catt -d <tv> cast [-s subs] [-l title] [-t sec] <url>` loads the URL on the fake TV, like the real one;
# a URL with "nostream" in it is one yt-dlp cannot do
PY = sys.executable
CATT = script("catt", '''#!%s
import os, sys, uuid
import pychromecast
from pychromecast.models import CastInfo, HostServiceInfo
args = sys.argv[1:]
open(os.environ["STUB_DIR"] + "/catt.calls", "a").write("\\x1f".join(args) + "\\n")
if "scan" in args:
    print("Scanning Chromecasts..."); print("127.0.0.1 - Fake TV - Samsung Fake"); sys.exit(0)
if "cast" not in args:
    sys.exit(0)
url = args[-1]
if "nostream" in url:
    sys.exit("Error: Remote resource not found")
opt = lambda f: args[args.index(f) + 1] if f in args else None
info = CastInfo({HostServiceInfo("127.0.0.1", 8009)}, uuid.uuid4(), "m", "Fake TV", "127.0.0.1", 8009, "cast", "x")
cc = pychromecast.get_chromecast_from_cast_info(info, None, tries=1, timeout=5)
cc.wait(5)
mc = cc.media_controller
mc.play_media(url, "application/x-mpegURL", title=opt("-l"), current_time=float(opt("-t")) if opt("-t") else None,
              stream_type="BUFFERED", subtitles=opt("-s"))
mc.block_until_active(10)
print('Playing "%%s" on "Fake TV"...' %% (opt("-l") or url))
cc.disconnect(2)
''' % PY)


class World:
    def __init__(self, tv_name="127.0.0.1", config_extra=""):
        self.tv = FakeTV().start()
        self.dir = tempfile.mkdtemp(prefix="w-", dir=TMP)
        os.makedirs(os.path.join(self.dir, ".config", "cast-tab"))
        self.config = os.path.join(self.dir, ".config", "cast-tab", "config")
        with open(self.config, "w") as f:
            f.write("CAST_TV=%s\n%s" % (tv_name, config_extra))
        self.log = os.path.join(self.dir, "cast-tab.log")
        self.env = dict(os.environ, HOME=self.dir, PATH=os.path.join(TMP, "bin") + ":" + os.environ["PATH"], CATT=CATT,
                        TABMEDIA=os.path.join(BIN, "tab-media"), CAST_TAB_LOG=self.log, STUB_DIR=self.dir, CAST_TV_WAIT="6",
                        FAKE_PAGE=PAGE, FAKE_TITLE=TITLE, FAKE_URLS=URLS)
        for k in list(self.env):
            if k.startswith("FAKE_") and k not in ("FAKE_PAGE", "FAKE_TITLE", "FAKE_URLS"):
                del self.env[k]

    def run(self, *args, **env):
        t = time.time()
        p = subprocess.run(["/bin/bash", os.path.join(BIN, "cast-tab"), *args], capture_output=True, text=True,
                           env=dict(self.env, **env), timeout=120)
        self.took = time.time() - t
        return (p.stdout + p.stderr).strip()

    def calls(self, name):
        try:
            with open(os.path.join(self.dir, name)) as f:
                return f.read().splitlines()
        except FileNotFoundError:
            return []

    def tab_kinds(self):
        return [c.split("|")[0] for c in self.calls("tab.calls")]

    def logged(self, text, within=12):
        until = time.time() + within
        while time.time() < until:
            if os.path.exists(self.log) and text in open(self.log).read():
                return True
            time.sleep(0.05)
        raise AssertionError("no %r in the log:\n%s" % (text, open(self.log).read() if os.path.exists(self.log) else "(no log)"))

    def watchers(self):
        return subprocess.run(["pgrep", "-f", "cast-ctl 127.0.0.1 watch"], capture_output=True, text=True).stdout.split()

    def close(self):
        subprocess.run(["pkill", "-f", "cast-ctl 127.0.0.1 watch"])
        self.tv.off()


def media(w):
    return w.tv.session["media"]


def test_page_player_site_front_tab_then_tv_closes_the_player(w):
    out = w.run()
    assert out.splitlines()[0] == "Casting: " + PAGE and "Stream: " + STREAM in out and "Subtitles: " + SUBS in out, out
    assert 'Playing "%s" on the TV' % TITLE in out, out
    m = media(w)
    assert m["contentId"] == STREAM and m["contentType"] == "application/vnd.apple.mpegurl" and m["metadata"]["title"] == TITLE, m
    assert m["tracks"][0]["trackContentId"] == SUBS and m["tracks"][0]["trackContentType"] == "text/vtt" and w.tv.session["tracks"] == [1], m
    assert 72 <= w.tv.pos() < 80, w.tv.pos()
    assert not w.calls("catt.calls"), w.calls("catt.calls")          # straight to the TV: no yt-dlp, no catt
    assert w.tab_kinds() == ["info", "urls", "pause"], w.tab_kinds()
    w.logged("watching " + TITLE)
    assert len(w.watchers()) == 1
    w.tv.close_app()
    w.logged("player closed on the TV at 1:")
    time.sleep(0.5)
    assert not w.watchers()


def test_stop_ends_the_watcher(w):
    w.run()
    w.logged("watching")
    assert w.run("stop") == "⏹ stopped" and w.tv.app is None
    time.sleep(1)
    assert not w.watchers() and not w.calls("notifications")
    assert w.run("status") == "Nothing playing on TV"


def test_back_to_mac(w):
    w.run()
    w.logged("watching")
    out = w.run("back")
    assert out.startswith("Back on Mac at 1m1") and w.tv.app is None, out
    time.sleep(1)
    assert not w.watchers()
    seek = [c for c in w.calls("tab.calls") if c.startswith("seek|")]
    assert len(seek) == 1 and 72 <= int(seek[0].split("=")[1]) <= 80, seek
    assert w.run("back") == "Nothing playing on TV"


def test_remote_commands_pass_through(w):
    w.run()
    assert w.run("pause").startswith("⏸ 1:1")
    assert w.run("toggle").startswith("▶ 1:1")
    assert w.run("ffwd", "30").startswith("⏩ 1:4")
    assert w.run("rewind").startswith("⏪ 1:3")
    assert w.run("volumeup") == "🔊 34" and w.run("volumedown", "4") == "🔉 30"
    assert w.run("volumemute") == "🔇 muted" and w.run("volumemute") == "🔈 unmuted"
    assert w.run("status").splitlines()[0] == TITLE


def test_casting_again_leaves_one_watcher(w):
    w.run()
    w.logged("watching")
    first = w.watchers()
    w.run(FAKE_TIME="300")
    time.sleep(1.5)
    now = w.watchers()
    assert len(first) == 1 and len(now) == 1 and now != first, (first, now)
    assert 300 <= w.tv.pos() < 310


def test_stream_not_loaded_yet_starts_the_page_video(w):
    out = w.run(FAKE_URLS="", FAKE_URLS_AFTER_PLAY=URLS, FAKE_TIME="0")
    assert "No stream loaded yet" in out and "Playing" in out, out
    kinds = w.tab_kinds()
    assert "play" in kinds and kinds.index("play") < kinds.index("pause"), kinds
    assert media(w)["contentId"] == STREAM and w.tv.pos() < 5
    assert not w.calls("catt.calls")                                 # a page-player site: yt-dlp is not tried


def test_nothing_castable_in_the_page(w):
    out = w.run(FAKE_URLS="", FAKE_TIME="0")
    assert "No stream found in the tab" in out, out
    assert not w.watchers() and w.tv.session is None and not w.calls("catt.calls")


def test_unknown_site_with_a_visible_stream_casts_the_page(w):
    out = w.run(FAKE_PAGE="https://video.example/watch/1")
    assert media(w)["contentId"] == STREAM and not w.calls("catt.calls"), out
    w.logged("watching")


def test_yt_dlp_site_goes_through_yt_dlp(w):
    out = w.run(FAKE_PAGE=YT + "1")
    assert media(w)["contentId"] == YT + "1", out
    cast = w.calls("catt.calls")[-1].split("\x1f")
    assert cast == ["-d", "127.0.0.1", "cast", "-t", "72", YT + "1"], cast
    assert w.tab_kinds() == ["info", "urls", "pause"], w.tab_kinds()
    w.logged("watching")


def test_unknown_site_nothing_visible_yt_dlp_fails_then_the_page(w):
    out = w.run(FAKE_PAGE="https://video.example/nostream/1", FAKE_URLS="", FAKE_URLS_AFTER_PLAY=URLS, FAKE_TIME="0")
    assert "Not a yt-dlp site" in out and "No stream loaded yet" in out and media(w)["contentId"] == STREAM, out
    assert w.calls("catt.calls")                                     # yt-dlp was tried first
    w.logged("watching")


def test_player_in_a_cross_origin_frame(w):
    frame = "https://embed.example/e/abc"
    out = w.run(FAKE_PAGE="https://video.example/nostream/2", FAKE_URLS="", FAKE_TIME="", FAKE_FRAMES=frame,
                FAKE_HELPER_URLS=URLS, FAKE_PROBE="referer")
    assert "Looking into the player frame" in out and "through this Mac" in out, out
    calls = w.calls("tab.calls")
    assert "open|" + frame in calls and "close|new-tab-id old-tab-id" in calls, calls
    assert calls.index("open|" + frame) < calls.index("pause|") < calls.index("close|new-tab-id old-tab-id"), calls
    cid = media(w)["contentId"]
    assert cid.startswith("http://127.0.0.1:") and cid.endswith("/s/https/cdn.example/aaa/1.mp4:hls:manifest.m3u8"), cid
    assert "currentTime" not in w.tv.sent("LOAD")[-1], w.tv.sent("LOAD")[-1]   # the frame's player: from the start
    assert "-e " + frame in w.calls("curl.calls")[-1], w.calls("curl.calls")   # the frame is the referer
    w.logged("watching " + TITLE)


def test_stream_server_wants_the_page_headers(w):
    out = w.run(FAKE_PROBE="referer")
    assert "through this Mac" in out, out
    m = media(w)
    assert m["contentId"].startswith("http://127.0.0.1:") and m["contentId"].endswith("/s/https/cdn.example/aaa/1.mp4:hls:manifest.m3u8"), m
    sub = m["tracks"][0]["trackContentId"]
    assert sub.startswith("http://127.0.0.1:") and sub.endswith("/s/https/cdn.example/aaa/1.vtt"), sub
    assert 72 <= w.tv.pos() < 80
    curl = w.calls("curl.calls")
    assert len(curl) == 2 and "-e" not in curl[0] and "-e " + PAGE in curl[1] and "Origin: https://rezka.example" in curl[1], curl
    w.logged("proxy on http://127.0.0.1:")
    w.logged("watching " + TITLE)
    assert w.run("stop") == "⏹ stopped"
    time.sleep(1)
    assert not w.watchers()


def test_closed_stream_server_is_tried_anyway(w):
    out = w.run(FAKE_PROBE="closed")
    assert "trying the TV anyway" in out and media(w)["contentId"] == STREAM, out


def test_srt_subtitles_go_through_the_proxy(w):
    srt = "https://cdn.example/aaa/1.srt"
    w.run(FAKE_URLS="subs %s\nhls %s" % (srt, STREAM))
    m = media(w)
    assert m["contentId"] == STREAM, m                               # the stream itself goes direct
    sub = m["tracks"][0]
    assert sub["trackContentId"].startswith("http://127.0.0.1:") and sub["trackContentId"].endswith("/s/https/cdn.example/aaa/1.srt"), sub
    assert sub["trackContentType"] == "text/vtt", sub
    w.logged("proxy on")
    w.logged("watching")


def test_url_argument_and_clipboard(w):
    w.run(YT + "2")
    assert media(w)["contentId"] == YT + "2" and not w.calls("tab.calls")
    w.logged("watching")
    assert w.run("clip", FAKE_CLIP="not a url") == "Clipboard has no URL"
    w.run("clip", FAKE_CLIP=YT + "3")
    assert media(w)["contentId"] == YT + "3"
    out = w.run("https://cdn.example/x/y.m3u8")                     # a stream URL: straight to the TV
    m = media(w)
    assert m["contentId"] == "https://cdn.example/x/y.m3u8" and m["contentType"] == "application/vnd.apple.mpegurl", out
    w.run("https://cdn.example/x/y.mp4?tok=1")
    assert media(w)["contentType"] == "video/mp4"
    assert not w.calls("tab.calls")
    assert len([c for c in w.calls("catt.calls") if "cast" in c]) == 2, w.calls("catt.calls")


def test_other_browser_in_front(w):
    w.run(FAKE_FRONT="Google Chrome")
    assert 'tell application "Google Chrome"' in open(os.path.join(w.dir, "last.applescript")).read()
    w.run("back", FAKE_FRONT="Google Chrome")
    assert 'tell application "Google Chrome"' in open(os.path.join(w.dir, "last.applescript")).read()


def test_raycast_in_front_uses_the_running_browser(w):
    w.run(FAKE_FRONT="Raycast", FAKE_RUNNING="Finder, Google Chrome, Raycast")
    assert 'tell application "Google Chrome"' in open(os.path.join(w.dir, "last.applescript")).read()
    w.run(FAKE_FRONT="Raycast", FAKE_RUNNING="Finder, Google Chrome, Arc")
    assert 'tell application "Arc"' in open(os.path.join(w.dir, "last.applescript")).read()


def test_javascript_blocked_in_the_browser(w):
    out = w.run(FAKE_JS_OFF="1", FAKE_PAGE="https://video.example/nostream/3")
    assert "Allow JavaScript from Apple Events" in out and "No stream found" in out, out
    assert w.tv.session is None


def test_tv_off(w):
    w.tv.off()
    assert w.run("status") == "TV refuses the Cast connection (off, or its Cast service is restarting — try again in a minute)"
    assert w.took < 6, w.took
    out = w.run()
    assert "TV not reachable on port 8009" in out and w.took < 12, (out, w.took)


def test_cast_name_instead_of_ip_goes_through_catt():
    w = World(tv_name="'Living Room TV'")
    try:
        w.run(YT + "5")
        assert media(w)["contentId"] == YT + "5"
        assert w.took < 8, w.took                    # no probing of port 8009 on the *name*
        assert w.calls("catt.calls")[-1].split("\x1f")[:3] == ["-d", "Living Room TV", "cast"]
        w.run()
        cast = w.calls("catt.calls")[-1].split("\x1f")
        assert cast == ["-d", "Living Room TV", "cast", "-s", SUBS, "-l", TITLE, "-t", "72", STREAM], cast
        assert media(w)["contentId"] == STREAM
    finally:
        w.close()


def test_tv_moved_to_another_ip():
    w = World(tv_name="127.0.0.2", config_extra="CAST_KEEP_AWAKE=1\n")
    try:
        out = w.run()
        assert "TV moved: 127.0.0.2 → 127.0.0.1 (config updated)" in out and media(w)["contentId"] == STREAM, out
        assert open(w.config).read() == "CAST_TV=127.0.0.1\nCAST_KEEP_AWAKE=1\n"
    finally:
        w.close()


if __name__ == "__main__":
    wanted = [a for a in sys.argv[1:] if not a.startswith("-")]
    tests = [(n, f) for n, f in list(globals().items()) if n.startswith("test_") and (not wanted or any(x in n for x in wanted))]
    failed = []
    for name, fn in tests:
        t = time.time()
        w = World() if fn.__code__.co_argcount else None
        try:
            fn(w) if w else fn()
            print("ok    %-58s %4.1fs" % (name[5:], time.time() - t))
        except Exception as e:   # noqa: BLE001
            failed.append(name)
            print("FAIL  %-58s %4.1fs\n      %s" % (name[5:], time.time() - t, (str(e) or repr(e)).replace("\n", "\n      ")))
        finally:
            if w:
                w.close()
        time.sleep(0.4)
    print("\n%d passed, %d failed%s" % (len(tests) - len(failed), len(failed), ": " + ", ".join(failed) if failed else ""))
    sys.exit(1 if failed else 0)
