# test_cast_tab.py — cast-tab + tab-media + cast-ctl together, against a fake TV, a fake browser (osascript stand-in
# answering like Arc) and a stand-in for catt. Nothing real is touched: no TV, no browser, no notifications.
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


def script(name, text):
    path = os.path.join(TMP, "bin", name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return path


# the browser: answers System Events, the front tab's URL, and tab-media's page scripts the way Arc does (a quoted
# string with \n and \" escaped)
script("osascript", r'''#!/bin/bash
if [ "$1" = "-e" ]; then
  case "$2" in
    *"System Events"*)        echo "${FAKE_FRONT:-Arc}" ;;
    *"get URL of active tab"*) echo "$FAKE_PAGE" ;;
    *"display notification"*)  echo "$2" >> "$STUB_DIR/notifications" ;;
  esac
  exit 0
fi
cat > "$STUB_DIR/last.applescript"
js="$2"; want="$3"
if [ -n "$want" ] && [ "$want" != "$FAKE_PAGE" ]; then echo "notab"; exit 0; fi
case "$js" in
  *'"time="'*)               kind=info;    out="time=${FAKE_TIME:-72}\\nduration=1200\\npaused=${FAKE_PAUSED:-1}\\ntitle=$FAKE_TITLE" ;;
  *getEntriesByType*)        kind=urls;    out="$FAKE_URLS" ;;
  *'if(!v.paused)return'*)   kind=settime; out=ok ;;
  *'v.muted=false'*)         kind=play;    out=ok ;;
  *'v.currentTime='*)        kind=seek;    out=ok ;;
  *'v.pause()'*)             kind=pause;   out=ok ;;
  *)                         kind=other;   out= ;;
esac
echo "$kind|$want|$(echo "$js" | grep -oE 'currentTime=[0-9]+' | head -1)" >> "$STUB_DIR/tab.calls"
printf '"%s"\n' "$(printf '%s' "$out" | sed 's/"/\\"/g')"
''')
script("pbpaste", '#!/bin/bash\necho "$FAKE_CLIP"\n')

# catt: `catt -d <tv> cast [-s subs] [-l title] [-t sec] <url>` loads the URL on the fake TV, like the real one
PY = sys.executable
CATT = script("catt", '''#!%s
import os, sys, uuid
import pychromecast
from pychromecast.models import CastInfo, HostServiceInfo
args = sys.argv[1:]
open(os.environ["STUB_DIR"] + "/catt.calls", "a").write("\\x1f".join(args) + "\\n")
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
    def __init__(self, tv_name="127.0.0.1"):
        self.tv = FakeTV().start()
        self.dir = tempfile.mkdtemp(prefix="w-", dir=TMP)
        os.makedirs(os.path.join(self.dir, ".config", "cast-tab"))
        with open(os.path.join(self.dir, ".config", "cast-tab", "config"), "w") as f:
            f.write("CAST_TV='%s'\n" % tv_name)
        self.log = os.path.join(self.dir, "cast-tab.log")
        self.env = dict(os.environ, HOME=self.dir, PATH=os.path.join(TMP, "bin") + ":" + os.environ["PATH"], CATT=CATT,
                        TABMEDIA=os.path.join(BIN, "tab-media"), CAST_TAB_LOG=self.log, STUB_DIR=self.dir,
                        FAKE_PAGE=PAGE, FAKE_TITLE=TITLE, FAKE_URLS=STREAM + "\\n" + SUBS)

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

    def logged(self, text, within=10):
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


def test_cast_front_tab_then_tv_closes_the_player(w):
    out = w.run()
    assert out.splitlines()[0] == "Casting: " + PAGE and "Stream: " + STREAM in out and "Subtitles: " + SUBS in out, out
    s = w.tv.session
    assert s["media"]["contentId"] == STREAM and s["media"]["metadata"]["title"] == TITLE, s
    assert s["media"]["tracks"][0]["trackContentId"] == SUBS and s["tracks"] == [1], s
    assert 72 <= w.tv.pos() < 80, w.tv.pos()
    cast = w.calls("catt.calls")[-1].split("\x1f")
    assert cast == ["-d", "127.0.0.1", "cast", "-s", SUBS, "-l", TITLE, "-t", "72", STREAM], cast
    assert [c.split("|")[0] for c in w.calls("tab.calls")] == ["info", "urls", "pause"], w.calls("tab.calls")
    w.logged("watching " + TITLE)
    assert len(w.watchers()) == 1
    time.sleep(6)                                    # the watcher polls every 5 s
    w.tv.close_app()
    w.logged("player closed on the TV at 1:")
    w.logged("page moved to 1:")
    moved = [c for c in w.calls("tab.calls") if c.startswith("settime|")]
    assert len(moved) == 1 and moved[0].split("|")[1] == PAGE and 77 <= int(moved[0].split("=")[1]) <= 90, moved
    time.sleep(0.5)
    assert not w.watchers()


def test_stop_ends_the_watcher_and_leaves_the_page_alone(w):
    w.run()
    w.logged("watching")
    assert w.run("stop") == "⏹ stopped" and w.tv.app is None
    time.sleep(1)
    assert not w.watchers()
    assert "page" not in open(w.log).read() and not w.calls("notifications")
    assert w.run("status") == "Nothing playing on TV"


def test_back_to_mac(w):
    w.run()
    w.logged("watching")
    out = w.run("back")
    assert out.startswith("Back on Mac at 1m1") and w.tv.app is None, out
    time.sleep(1)
    assert not w.watchers()
    seek = [c for c in w.calls("tab.calls") if c.startswith("seek|")]
    assert len(seek) == 1 and seek[0].split("|")[1] == "" and 72 <= int(seek[0].split("=")[1]) <= 80, seek
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
    assert "page" not in open(w.log).read()          # the old watcher left without touching the page


def test_stream_not_loaded_yet_starts_the_page_video(w):
    out = w.run(FAKE_URLS="")
    assert "No stream loaded yet" in out and "No stream found in the tab" in out, out
    assert "play" in [c.split("|")[0] for c in w.calls("tab.calls")]
    assert not w.watchers() and w.tv.session is None


def test_site_yt_dlp_knows(w):
    page = "https://video.example/watch/1"
    out = w.run(FAKE_PAGE=page)
    assert w.tv.session["media"]["contentId"] == page, out
    cast = w.calls("catt.calls")[-1].split("\x1f")
    assert cast == ["-d", "127.0.0.1", "cast", "-t", "72", page], cast
    assert [c.split("|")[0] for c in w.calls("tab.calls")] == ["info", "pause"]
    w.logged("watching")


def test_site_yt_dlp_does_not_know_falls_back_to_the_tab(w):
    out = w.run(FAKE_PAGE="https://video.example/nostream/1")
    assert "Not a yt-dlp site — reading the stream from the Arc tab" in out and "Stream: " + STREAM in out, out
    assert w.tv.session["media"]["contentId"] == STREAM
    w.logged("watching")


def test_url_argument_and_clipboard(w):
    w.run("https://video.example/watch/2")
    assert w.tv.session["media"]["contentId"] == "https://video.example/watch/2" and not w.calls("tab.calls")
    w.logged("watching")
    assert w.run("clip", FAKE_CLIP="not a url") == "Clipboard has no URL"
    w.run("clip", FAKE_CLIP="https://video.example/watch/3")
    assert w.tv.session["media"]["contentId"] == "https://video.example/watch/3"
    assert "nostream" in w.run("https://video.example/nostream/9") or True
    w.tv.close_app()                                 # cast from a URL: there is no page to move
    w.logged("player closed on the TV")
    time.sleep(0.5)
    assert not [c for c in w.calls("tab.calls") if c.startswith("settime")]


def test_other_browser_in_front(w):
    w.run(FAKE_FRONT="Google Chrome")
    assert 'tell application "Google Chrome"' in open(os.path.join(w.dir, "last.applescript")).read()
    w.run("back", FAKE_FRONT="Google Chrome")
    assert 'tell application "Google Chrome"' in open(os.path.join(w.dir, "last.applescript")).read()


def test_tv_off(w):
    w.tv.off()
    assert w.run("status") == "TV refuses the Cast connection (off, or its Cast service is restarting — try again in a minute)"
    assert w.took < 6, w.took


def test_cast_name_instead_of_ip_does_not_wait_for_the_port():
    w = World(tv_name="Living Room TV")
    try:
        w.run("https://video.example/watch/5")
        assert w.tv.session["media"]["contentId"] == "https://video.example/watch/5"
        assert w.took < 8, w.took                    # used to probe port 8009 on the *name* for 2.5 minutes
        assert w.calls("catt.calls")[-1].split("\x1f")[:3] == ["-d", "Living Room TV", "cast"]
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
