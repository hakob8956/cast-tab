# test_cast_ctl.py — cast-ctl against a fake TV: the watcher through the ways a cast can go wrong, the stream proxy
# against a Referer-locked origin, the load and remote commands, and the real process (keep-awake, one watcher per TV,
# SIGTERM, proxy hand-off). Run with catt's python:
#   $(head -1 ~/.local/bin/catt | cut -c3-) test/test_cast_ctl.py [name-filter] [-v] [--soak]
# --soak adds a 90 s run at real timings against a TV that pings every 10 s (pychromecast's heartbeat and our polls
# write to one TLS socket from two threads: the lock in connect() keeps the writes apart).
import importlib.util
import logging
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.machinery import SourceFileLoader

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from fake_tv import YOUTUBE, FakeTV  # noqa: E402

CTL = os.path.join(HERE, "..", "bin", "cast-ctl")
TMP = tempfile.mkdtemp(prefix="cast-ctl-test-")
U1, U2 = "https://cdn.example/aaa/1.mp4:hls:manifest.m3u8", "https://cdn.example/bbb/2.mp4:hls:manifest.m3u8"
TITLE = "Show · Season 1 · Episode 1"
VERBOSE = False


class Rig:
    """A fake TV and, in a thread, the watcher with its clocks sped up 25×."""

    def __init__(self):
        self.tv = FakeTV().start()
        logging.getLogger("pychromecast").setLevel(logging.CRITICAL)
        spec = importlib.util.spec_from_loader("cast_ctl", SourceFileLoader("cast_ctl", CTL))
        self.m = m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        m.POLL, m.ANSWER, m.START, m.STALL, m.GRACE, m.GIVE_UP = 0.2, 0.5, 4, 1.8, 1.2, 8
        self.logs, self.notes, self.t0 = [], [], time.time()
        m.log = lambda msg: (self.logs.append(msg), VERBOSE and print("      %5.2f %s" % (time.time() - self.t0, msg)))
        m.notify = self.notes.append
        self.thread = self.cc = None

    def watch(self, want=None, latch=True):
        def body():
            try:
                self.cc = self.m.connect("127.0.0.1", tries=None)
            except SystemExit:
                return
            try:
                self.m.follow(self.cc, want, None)
            finally:
                try:
                    self.cc.disconnect(timeout=2)
                except Exception:   # noqa: BLE001
                    pass
        self.thread = threading.Thread(target=body, daemon=True)
        self.thread.start()
        if latch:
            self.log("watching")
        return self

    def log(self, text, within=12):
        until = time.time() + within
        while time.time() < until:
            if any(text in line for line in self.logs):
                return True
            time.sleep(0.02)
        raise AssertionError("no log line with %r within %ss; log:\n  %s" % (text, within, "\n  ".join(self.logs)))

    def no_log(self, text):
        assert not any(text in line for line in self.logs), "unexpected log line with %r:\n  %s" % (text, "\n  ".join(self.logs))

    def ends(self, within=12):
        self.thread.join(within)
        assert not self.thread.is_alive(), "watcher still running; log:\n  %s" % "\n  ".join(self.logs)

    def runs(self, for_=1.0):
        time.sleep(for_)
        assert self.thread.is_alive(), "watcher ended early; log:\n  %s" % "\n  ".join(self.logs)

    def close(self):
        self.m.GIVE_UP = 0
        self.tv.off()
        if self.thread:
            self.thread.join(8)
        assert not self.tv.sent("LAUNCH"), "the watcher LAUNCHED an app on the TV"


# ── the watcher ────────────────────────────────────────────────────────────────────────────────────────────────────
def test_plays_to_the_end(r):
    r.tv.launch().play(U1, at=72)
    r.watch().runs(0.8)
    r.tv.idle("FINISHED")
    r.ends()
    r.log("finished")
    assert not r.tv.sent("LOAD") and not r.notes


def test_player_error_reloads_at_position(r):
    tracks = [{"trackId": 1, "type": "TEXT", "trackContentId": "https://cdn.example/s.vtt", "language": "ru", "trackContentType": "text/vtt"}]
    media = {"contentId": U1, "contentType": "application/x-mpegURL", "streamType": "BUFFERED", "tracks": tracks,
             "metadata": {"metadataType": 0, "title": TITLE}}
    r.tv.launch().play(U1, at=300, media=media, tracks=[1])
    r.watch().runs(0.8)
    at = r.tv.pos()
    r.tv.idle("ERROR")
    r.log("player error at 5:0")
    r.log("PLAYING at 4:5")
    load = r.tv.sent("LOAD")[0]
    assert load["media"]["contentId"] == U1 and load["media"]["contentType"] == "application/x-mpegURL", load
    assert load["media"]["metadata"]["title"] == TITLE and load["media"]["tracks"][0]["trackContentId"] == tracks[0]["trackContentId"], load
    assert load["media"]["tracks"][0]["language"] == "ru" and load["activeTrackIds"] == [1] and load["autoplay"] is True, load
    assert at - 6.5 < load["currentTime"] < at - 3.5, (at, load["currentTime"])
    assert r.notes == ["TV player failed — resuming at 4:5%d" % (int(load["currentTime"]) % 10)], r.notes
    r.runs(1.5)                       # and it goes on watching the reloaded video
    r.tv.idle("FINISHED")
    r.ends()
    assert len(r.tv.sent("LOAD")) == 1


def test_gives_up_after_3_failed_reloads(r):
    r.tv.launch().play(U1, at=100)
    r.watch().runs(0.6)
    r.tv.on_load = "error"
    r.tv.idle("ERROR")
    r.ends(15)
    r.log("player failed 3 times in 15 min — giving up at 1:4")
    assert len(r.tv.sent("LOAD")) == 3, len(r.tv.sent("LOAD"))
    assert r.notes[-1].startswith("TV player keeps failing — gave up at 1:4"), r.notes


def test_load_failed_message_counts_as_failure(r):
    r.tv.launch().play(U1, at=100)
    r.watch().runs(0.6)
    r.tv.on_load = "fail"
    r.tv.idle("ERROR")
    r.ends(15)
    r.log("load failed, error 104")
    r.log("giving up")
    assert len(r.tv.sent("LOAD")) == 3


def test_buffering_forever_reloads(r):
    r.tv.launch().play(U1, at=200)
    r.watch().runs(0.8)
    r.tv.set("BUFFERING")
    r.log("frozen: BUFFERING but position stuck at 3:2")
    r.log("no progress for")
    load = r.tv.sent("LOAD")[0]
    assert 193 < load["currentTime"] < 198, load["currentTime"]
    r.runs(1.0)
    assert len(r.tv.sent("LOAD")) == 1


def test_frozen_picture_reloads(r):
    r.tv.launch().play(U1, at=200)
    r.watch().runs(1.0)               # sees the clock move first
    r.tv.freeze()
    r.log("frozen: PLAYING but position stuck")
    r.log("no progress for")
    assert len(r.tv.sent("LOAD")) == 1


def test_short_buffering_is_left_alone(r):
    r.tv.launch().play(U1, at=200)
    r.watch().runs(0.6)
    r.tv.set("BUFFERING")
    time.sleep(0.9)
    r.tv.set("PLAYING")
    r.runs(2.5)
    assert not r.tv.sent("LOAD")
    r.log("unfrozen after")


def test_tv_whose_clock_never_moves_is_not_reloaded(r):
    r.tv.launch().play(U1, at=200)
    r.tv.freeze()
    r.watch().runs(3.5)
    r.log("frozen: PLAYING but position stuck")
    assert not r.tv.sent("LOAD")


def test_paused_is_not_a_stall(r):
    r.tv.launch().play(U1, at=200)
    r.watch().runs(0.6)
    r.tv.set("PAUSED")
    r.runs(3.0)
    assert not r.tv.sent("LOAD")
    r.no_log("frozen")


def test_connection_cut_reconnects_and_goes_on(r):
    r.tv.launch().play(U1, at=100)
    r.watch().runs(0.6)
    r.tv.cut()
    r.log("TV connection LOST")
    r.log("TV connection CONNECTED", within=15)
    r.runs(1.0)
    r.tv.idle("ERROR")                # … and still does its job on the new connection
    r.log("player error at")
    r.runs(0.5)


def test_tv_off_for_good_gives_up(r):
    r.tv.launch().play(U1, at=100)
    r.watch().runs(0.6)
    r.tv.off()
    r.ends(20)
    r.log("TV unreachable for 0 min (off?) — stop watching")


def test_player_closed_on_tv(r):
    r.tv.launch().play(U1, at=100)
    r.watch().runs(0.6)
    r.tv.close_app()
    r.ends()
    r.log("player closed on the TV at 1:4")
    r.log("(app now: None) — Back/Home on the remote")
    assert not r.notes


def test_another_app_takes_over(r):
    r.tv.launch().play(U1, at=100)
    r.watch().runs(0.6)
    r.tv.launch(YOUTUBE)
    r.ends()
    r.log("(app now: YouTube)")


def test_youtube_is_not_watched(r):
    r.tv.launch(YOUTUBE).play("VXq0tQsHClg", at=6, title="ArmComedy")
    r.watch(latch=False)
    r.ends(10)
    r.log("YouTube plays this in its own TV app — nothing to watch")
    r.no_log("player closed")
    assert not r.tv.sent("LOAD")


def test_something_else_cast(r):
    r.tv.launch().play(U1, at=100)
    r.watch().runs(0.6)
    r.tv.idle("INTERRUPTED")
    r.tv.play(U2, at=0, title="Other")
    r.ends()
    r.log("something else was cast — stop watching")
    assert not r.tv.sent("LOAD")


def test_stopped_from_elsewhere(r):
    r.tv.launch().play(U1, at=100)
    r.watch().runs(0.6)
    r.tv.idle("CANCELLED")
    r.ends()
    r.log("stopped (CANCELLED) at 1:4")
    assert not r.tv.sent("LOAD")


def test_session_gone_without_a_reason(r):
    r.tv.launch().play(U1, at=100)
    r.watch().runs(0.6)
    r.tv.end_session()
    r.ends()
    r.log("stopped (session gone) at 1:4")
    assert not r.tv.sent("LOAD")


def test_waits_for_the_stream_it_was_started_for(r):
    r.tv.launch().play(U1, at=500, title="Old")
    r.watch(want=U2, latch=False)
    time.sleep(0.8)
    r.no_log("watching")
    r.tv.idle("INTERRUPTED")
    r.tv.play(U2, at=0, title="New")
    r.log("watching New")
    r.runs(0.5)


def test_nothing_playing_at_start(r):
    r.tv.launch()
    r.watch(latch=False)
    r.ends(10)
    r.log("watch: nothing playing on the TV's media player, not watching")


def test_tv_unreachable_at_start(r):
    r.tv.off()
    r.watch(latch=False)
    r.ends(12)
    r.no_log("watching")


def test_status_poll_never_launches_the_player(r):
    r.tv.launch("NOMEDIA")                               # an app without media controls is on the TV
    r.watch(latch=False)
    r.ends(10)
    r.log("Screensaver plays this in its own TV app — nothing to watch")
    assert not r.tv.sent("LAUNCH") and r.tv.app["id"] == "NOMEDIA"


# ── the stream proxy ───────────────────────────────────────────────────────────────────────────────────────────────
SEG = bytes(range(256)) * 40
FILES = {
    "/hls/master.m3u8": ("application/vnd.apple.mpegurl", '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000000\n720/index.m3u8\n'
                         '#EXT-X-STREAM-INF:BANDWIDTH=500000\n/hls/480/index.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=2000000\n'
                         'http://ORIGIN/hls/1080/index.m3u8?tok=1\n#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="s",NAME="en",URI="../subs/en.m3u8"\n'),
    "/hls/720/index.m3u8": ("text/plain", '#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key.bin"\n#EXT-X-MAP:URI="init.mp4"\n'
                            '#EXTINF:6.0,\nseg1.ts\n#EXT-X-ENDLIST\n'),
    "/hls/720/seg1.ts": ("video/mp2t", SEG),
    "/subs/a.srt": ("application/x-subrip", "\ufeff1\r\n00:00:01,000 --> 00:00:02,500\r\nHi\r\n\r\n2\r\n00:00:03,000 --> 00:00:04,000\r\nThere\r\n"),
    "/dash/x.mpd": ("application/dash+xml", '<?xml version="1.0"?>\n<MPD><BaseURL>http://ORIGIN/dash/</BaseURL><Period>'
                    '<SegmentTemplate media="/dash/seg-$Number$.m4s" initialization="init.mp4"/></Period></MPD>'),
    "/noext": ("", "#EXTM3U\n#EXTINF:1,\ny.ts\n"),
    "/big.mp4": ("video/mp4", SEG * 50),
}


class Origin:
    """A stream server that answers only with the page as Referer."""

    def __init__(self):
        origin, self.seen = self, []

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_GET(self):
                self.serve(False)

            def do_HEAD(self):
                self.serve(True)

            def serve(self, head):
                origin.seen.append((self.path, self.headers.get("Referer"), self.headers.get("Origin"), self.headers.get("User-Agent")))

                def fin(code, body=b"", ct=None, extra=()):
                    self.send_response(code)
                    if ct:
                        self.send_header("Content-Type", ct)
                    for k, v in extra:
                        self.send_header(k, v)
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    if not head:
                        self.wfile.write(body)
                if self.headers.get("Referer") != "https://page.example/watch?x=1":
                    return fin(403)
                if self.path not in FILES:
                    return fin(404, b"nope")
                ct, body = FILES[self.path]
                body = (body.replace("http://ORIGIN", origin.url) if isinstance(body, str) else body)
                body = body if isinstance(body, bytes) else body.encode()
                rng = self.headers.get("Range")
                if rng and rng.startswith("bytes="):
                    a, b = rng[6:].split("-")
                    a, b = int(a), (int(b) if b else len(body) - 1)
                    return fin(206, body[a:b + 1], ct, [("Content-Range", "bytes %d-%d/%d" % (a, b, len(body))), ("Accept-Ranges", "bytes")])
                fin(200, body, ct, [("Accept-Ranges", "bytes")])

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d" % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()


def curl(url, *extra):
    return subprocess.run(["curl", "-s", "-i", *extra, url], capture_output=True).stdout.decode("utf-8", "replace")


def test_proxy_serves_a_referer_locked_stream(r):
    o = Origin()
    p = r.m.Proxy("127.0.0.1", referer="https://page.example/watch?x=1", ua="UA/1")
    try:
        base = "http://127.0.0.1:%d/s/http/127.0.0.1:%d" % (p.port, o.server.server_address[1])
        assert curl(o.url + "/hls/master.m3u8").startswith("HTTP/1.1 403")                      # the TV alone would get this
        assert p.url_for(o.url + "/hls/master.m3u8") == base + "/hls/master.m3u8"
        out = curl(base + "/hls/master.m3u8")
        head, body = out.split("\r\n\r\n", 1)
        assert "HTTP/1.1 200" in head and "application/vnd.apple.mpegurl" in head and "Access-Control-Allow-Origin: *" in head, head
        lines = body.splitlines()
        assert base + "/hls/720/index.m3u8" in lines and base + "/hls/480/index.m3u8" in lines, body       # relative, root-relative
        assert base + "/hls/1080/index.m3u8?tok=1" in lines and 'URI="%s/subs/en.m3u8"' % base in body, body   # absolute, attribute
        lvl = curl(base + "/hls/720/index.m3u8")
        assert "mpegurl" in lvl and 'URI="%s/hls/720/key.bin"' % base in lvl and base + "/hls/720/seg1.ts" in lvl, lvl
        seg = subprocess.run(["curl", "-s", "-r", "0-3", "-D", "-", base + "/hls/720/seg1.ts"], capture_output=True).stdout
        assert b"HTTP/1.1 206" in seg and b"Content-Range: bytes 0-3/10240" in seg and seg.endswith(b"\x00\x01\x02\x03"), seg[:200]
        assert subprocess.run(["curl", "-s", base + "/big.mp4"], capture_output=True).stdout == SEG * 50
        vtt = curl(base + "/subs/a.srt")
        assert "text/vtt" in vtt and vtt.split("\r\n\r\n", 1)[1].startswith("WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.500\nHi"), vtt
        mpd = curl(base + "/dash/x.mpd")
        assert "<BaseURL>%s/dash/</BaseURL>" % base in mpd and 'media="%s/dash/seg-$Number$.m4s"' % base in mpd and 'initialization="init.mp4"' in mpd, mpd
        assert "mpegurl" in curl(base + "/noext") and base + "/y.ts" in curl(base + "/noext")   # a playlist with no type at all
        assert curl(base + "/missing").startswith("HTTP/1.1 404") and curl("http://127.0.0.1:%d/x" % p.port).startswith("HTTP/1.1 404")
        assert "Content-Length: 10240" in curl(base + "/hls/720/seg1.ts", "-I")
        assert o.seen[-1][1:] == ("https://page.example/watch?x=1", "https://page.example", "UA/1"), o.seen[-1]
    finally:
        p.stop()
        o.stop()


# ── the real process: keep-awake, SIGTERM, one watcher per TV, proxy hand-off ──────────────────────────────────────
def start(env=None, log="proc.log"):
    logf = os.path.join(TMP, log)
    env = dict(os.environ, CAST_TAB_LOG=logf, **(env or {}))
    return subprocess.Popen([sys.executable, CTL, "127.0.0.1", "watch"], env=env), logf


def wait_log(logf, text, within=10):
    until = time.time() + within
    while time.time() < until:
        if os.path.exists(logf) and text in open(logf).read():
            return open(logf).read()
        time.sleep(0.1)
    raise AssertionError("no %r in %s:\n%s" % (text, logf, open(logf).read() if os.path.exists(logf) else "(no log)"))


def test_process_keeps_mac_awake_and_leaves_quietly(r):
    r.tv.launch().play(U1, at=100)
    p, logf = start()
    try:
        wait_log(logf, "watching Show")
        kids = subprocess.run(["pgrep", "-P", str(p.pid), "caffeinate"], capture_output=True, text=True).stdout.split()
        assert len(kids) == 1, kids
        p.terminate()
        assert p.wait(5) == 0
        time.sleep(0.5)
        assert subprocess.run(["ps", "-p", kids[0]], capture_output=True).returncode != 0, "caffeinate still running"
        assert "crashed" not in open(logf).read()
    finally:
        p.kill()


def test_process_can_run_without_keeping_awake(r):
    r.tv.launch().play(U1, at=100)
    p, logf = start({"CAST_KEEP_AWAKE": "0"}, "proc2.log")
    try:
        wait_log(logf, "watching Show")
        assert not subprocess.run(["pgrep", "-P", str(p.pid), "caffeinate"], capture_output=True, text=True).stdout
    finally:
        p.terminate()
        p.wait(5)


def test_one_watcher_per_tv(r):
    r.tv.launch().play(U1, at=100)
    p1, _ = start(log="proc3a.log")
    time.sleep(0.8)
    p2, logf2 = start(log="proc3b.log")
    try:
        wait_log(logf2, "watching Show")
        assert p1.wait(5) == 0, "the older watcher should have left"
        assert p2.poll() is None
    finally:
        p1.kill()
        p2.terminate()
        p2.wait(5)


def test_process_hands_out_proxied_urls_and_waits_for_them(r):
    r.tv.launch()
    f = os.path.join(TMP, "proxy.ready")
    p, logf = start({"CAST_PROXY_FILE": f, "CAST_PROXY_STREAM": U1, "CAST_PROXY_SUBS": "https://cdn.example/s.srt",
                     "CAST_PROXY_REFERER": "https://page.example/", "CAST_PROXY_UA": "UA/1"}, "proc4.log")
    try:
        until = time.time() + 10
        while time.time() < until and not os.path.exists(f):
            time.sleep(0.05)
        assert os.path.exists(f), "no proxy file"
        lines = open(f).read().splitlines()
        assert lines[0].startswith("stream=http://127.0.0.1:") and lines[0].endswith("/s/https/cdn.example/aaa/1.mp4:hls:manifest.m3u8"), lines
        assert lines[1].startswith("subs=http://127.0.0.1:") and lines[1].endswith("/s/https/cdn.example/s.srt"), lines
        wait_log(logf, "proxy on http://127.0.0.1:")
        r.tv.play(U2, at=0, title="Other")                   # something else playing: not ours
        time.sleep(1.5)
        assert "watching" not in open(logf).read()
        proxied = lines[0][len("stream="):]
        assert curl(proxied).startswith("HTTP/1.1 502")        # the proxy is up (cdn.example does not exist)
        r.tv.idle("INTERRUPTED")
        r.tv.play(proxied, at=30, title="Ours")
        wait_log(logf, "watching Ours")
        p.terminate()
        p.wait(5)
        time.sleep(0.3)
        assert subprocess.run(["curl", "-s", "-m", "2", proxied], capture_output=True).returncode != 0, "proxy still up"
    finally:
        p.kill()


# ── load and the remote commands ───────────────────────────────────────────────────────────────────────────────────
def ctl(*args, timeout=30):
    t = time.time()
    p = subprocess.run([sys.executable, CTL, "127.0.0.1", *args], capture_output=True, text=True, timeout=timeout,
                       env=dict(os.environ, CAST_TAB_LOG=os.path.join(TMP, "cmd.log")))
    return p.returncode, p.stdout.strip(), time.time() - t, p.stderr


def expect(args, out, rc=0, faster=2.0):
    got_rc, got, took, err = ctl(*args)
    assert (got_rc, got) == (rc, out), "%s → rc=%s %r (wanted rc=%s %r)\n%s" % (args, got_rc, got, rc, out, err)
    assert took < faster, "%s took %.1fs" % (args, took)
    assert not err, err


def test_commands(r):
    tv = r.tv.launch().play(U1, at=60)
    tv.set("PAUSED")
    expect(["status"], TITLE + "\n⏸  1:00 / 20:00\nVolume 24")
    expect(["time"], "60")
    expect(["toggle"], "▶ 1:00")
    assert tv.session["state"] == "PLAYING"
    expect(["pause"], "⏸ 1:00")
    expect(["pause"], "⏸ 1:00")
    expect(["play"], "▶ 1:00")
    tv.set("PAUSED")
    expect(["ffwd", "30"], "⏩ 1:30")
    assert tv.session["state"] == "PAUSED" and "resumeState" not in tv.sent("SEEK")[-1]   # a paused video stays paused
    expect(["rewind"], "⏪ 1:20")
    expect(["seek", "600"], "↪ 10:00")
    expect(["seek", "99999"], "↪ 19:55")
    expect(["rewind", "99999"], "⏪ 0:00")
    expect(["skip"], "⏭ skipped")
    assert tv.pos() == 1195
    expect(["volume", "40"], "🔊 40")
    expect(["volumeup"], "🔊 50")
    expect(["volumedown", "5"], "🔉 45")
    expect(["volumemute"], "🔇 muted")
    expect(["volumemute"], "🔈 unmuted")
    expect(["seek", "abc"], "seek: bad argument 'abc'", rc=1)
    expect(["bogus"], "unknown command: bogus", rc=1)
    expect(["stop"], "⏹ stopped")
    assert tv.app is None
    expect(["status"], "Nothing playing on TV", rc=1)
    expect(["toggle"], "Nothing playing on TV", rc=1)
    expect(["volumeup"], "🔊 55")                           # volume works with nothing playing
    assert not tv.sent("LAUNCH")


def test_load(r):
    tv = r.tv.launch()
    expect(["load", U1, "-t", "application/x-mpegURL", "-l", TITLE, "-s", "120", "-c", "https://cdn.example/s.srt"],
           'Playing "%s" on the TV' % TITLE)
    m = tv.session["media"]
    assert m["contentId"] == U1 and m["contentType"] == "application/x-mpegURL" and m["metadata"]["title"] == TITLE, m
    assert m["tracks"][0]["trackContentId"] == "https://cdn.example/s.srt" and m["tracks"][0]["trackContentType"] == "text/vtt", m
    assert tv.session["tracks"] == [1] and 120 <= tv.pos() < 125
    expect(["load", "https://cdn.example/v.mp4"], 'Playing "https://cdn.example/v.mp4" on the TV')
    assert tv.session["media"]["contentType"] == "video/mp4" and "currentTime" not in tv.sent("LOAD")[-1]
    expect(["load", "https://cdn.example/v.m3u8?x=1"], 'Playing "https://cdn.example/v.m3u8?x=1" on the TV')
    assert tv.session["media"]["contentType"] == "application/vnd.apple.mpegurl"
    tv.on_load = "fail"
    expect(["load", U2], "TV could not load the stream (LOAD_FAILED 104)", rc=1)
    tv.on_load = "play"
    tv.close_app()
    expect(["load", U2, "-l", "Fresh"], 'Playing "Fresh" on the TV')      # launches the player when none runs
    assert tv.app["id"] == "CC1AD845" and tv.session["media"]["contentId"] == U2
    assert len(tv.sent("LAUNCH")) == 1
    tv.got = [g for g in tv.got if g[1].get("type") != "LAUNCH"]           # (that one launch was wanted)


def test_commands_on_idle_or_other_apps(r):
    tv = r.tv.launch()
    expect(["status"], "Nothing playing on TV", rc=1)
    tv.play(U1, at=60)
    tv.idle("ERROR")
    expect(["toggle"], "Nothing playing on TV (last: ERROR)", rc=1)
    tv.launch("NOMEDIA")
    expect(["toggle"], "TV app Screensaver has no media controls", rc=1)
    tv.launch(YOUTUBE).play("VXq0tQsHClg", at=484, title="ArmComedy", duration=1665)
    expect(["status"], "ArmComedy\n▶  8:04 / 27:45\nVolume 24")
    expect(["pause"], "⏸ 8:04")
    expect(["stop"], "⏹ stopped")
    assert not tv.sent("LAUNCH")


def test_commands_when_the_tv_is_in_trouble(r):
    tv = r.tv.launch().play(U1, at=60)
    tv.mute_media = True
    expect(["status"], "TV did not answer", rc=1, faster=4.5)
    tv.mute_media = False
    tv.ignore = {"PAUSE"}
    expect(["pause"], "TV did not answer", rc=1, faster=6.5)
    tv.ignore = set()
    tv.stop_cuts = True
    expect(["stop"], "⏹ stopped", faster=6.5)
    tv.launch().play(U1, at=60)
    tv.deaf = True
    expect(["status"], "TV takes the Cast connection but does not answer", rc=1, faster=13)
    tv.deaf = False
    tv.off()
    expect(["status"], "TV refuses the Cast connection (off, or its Cast service is restarting — try again in a minute)",
           rc=1, faster=6)
    assert not tv.sent("LAUNCH")


def test_soak_at_real_timings(r):
    """90 s with the TV pinging every 10 s, polls every 5 s: no connection lost, every poll answered."""
    r.m.POLL, r.m.ANSWER = 5, 3
    r.tv.ping_every = 10
    r.tv.launch().play(U1, at=10, duration=100000)
    r.watch().runs(90)
    r.no_log("connection")
    assert r.tv.pongs >= 7 and len(r.tv.sent("GET_STATUS")) >= 16, (r.tv.pongs, len(r.tv.sent("GET_STATUS")))
    r.tv.idle("FINISHED")
    r.ends()


if __name__ == "__main__":
    VERBOSE = "-v" in sys.argv
    wanted = [a for a in sys.argv[1:] if not a.startswith("-")]
    tests = [(n, f) for n, f in list(globals().items()) if n.startswith("test_") and (not wanted or any(w in n for w in wanted))
             and (n != "test_soak_at_real_timings" or "--soak" in sys.argv or "soak" in wanted)]
    failed = []
    for name, fn in tests:
        rig, t = Rig(), time.time()
        try:
            fn(rig)
            rig.close()
            print("ok    %-52s %4.1fs" % (name[5:], time.time() - t))
        except Exception as e:   # noqa: BLE001
            failed.append(name)
            print("FAIL  %-52s %4.1fs\n      %s" % (name[5:], time.time() - t, str(e).replace("\n", "\n      ") or repr(e)))
            rig.m.GIVE_UP = 0
            rig.tv.off()
            if rig.thread:
                rig.thread.join(10)
        subprocess.run(["pkill", "-f", "cast-ctl 127.0.0.1 watch"])
        time.sleep(0.3)
    print("\n%d passed, %d failed%s" % (len(tests) - len(failed), len(failed), ": " + ", ".join(failed) if failed else ""))
    sys.exit(1 if failed else 0)
