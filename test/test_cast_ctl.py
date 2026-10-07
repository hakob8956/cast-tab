# test_cast_ctl.py — cast-ctl against a fake TV: the watcher through every way a cast can go wrong, and the remote
# commands. Run with catt's python:  $(head -1 ~/.local/bin/catt | cut -c3-) test/test_cast_ctl.py [name-filter]
import importlib.util
import logging
import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
from importlib.machinery import SourceFileLoader

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from fake_tv import YOUTUBE, FakeTV  # noqa: E402

CTL = os.path.join(HERE, "..", "bin", "cast-ctl")
TMP = tempfile.mkdtemp(prefix="cast-ctl-test-")
U1, U2 = "https://cdn.example/aaa/1.mp4:hls:manifest.m3u8", "https://cdn.example/bbb/2.mp4:hls:manifest.m3u8"
TITLE = "Show · Season 1 · Episode 1"

# a stand-in for tab-media: records how it was called, answers like a paused page showing STUB_TITLE
STUB = os.path.join(TMP, "tab-media")
with open(STUB, "w") as f:
    f.write('#!/bin/bash\necho "$TAB_URL|$*" >> "%s/tab.calls"\n'
            'case "$1" in info) printf "time=7\\nduration=1200\\npaused=%%s\\ntitle=%%s\\n" "${STUB_PAUSED:-1}" '
            '"$STUB_TITLE";; settime) echo ok;; esac\n' % TMP)
os.chmod(STUB, os.stat(STUB).st_mode | stat.S_IEXEC)


def tab_calls():
    try:
        with open(os.path.join(TMP, "tab.calls")) as f:
            return f.read().splitlines()
    except FileNotFoundError:
        return []


class Rig:
    """A fake TV and, in a thread, the watcher with its clocks sped up 25×."""

    def __init__(self, **env):
        self.tv = FakeTV().start()
        logging.getLogger("pychromecast").setLevel(logging.CRITICAL)
        spec = importlib.util.spec_from_loader("cast_ctl", SourceFileLoader("cast_ctl", CTL))
        self.m = m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        m.POLL, m.ANSWER, m.START, m.STALL, m.GRACE, m.AWAY, m.GIVE_UP = 0.2, 0.5, 4, 1.8, 1.2, 3, 8
        m.LONG_PAUSE = 1.0
        self.awake = []                       # every change of the keep-awake hold
        hold = lambda on: self.awake.append(on) if not self.awake or self.awake[-1] != on else None
        self.holder = type("Awake", (), {"hold": staticmethod(hold)})
        self.logs, self.notes, self.skew, self.t0 = [], [], 0.0, time.time()
        m.log = lambda msg: (self.logs.append(msg), VERBOSE and print("      %5.2f %s" % (time.time() - self.t0, msg)))
        m.notify = self.notes.append
        m.TABMEDIA = STUB
        m.wall = lambda: time.time() + self.skew
        fast = m.open_tv
        m.open_tv = lambda ip, player=None, listener=None, timeout=1, sender="sender-0": fast(ip, player, listener, timeout, sender)
        for k in ("CAST_APP", "CAST_PAGE", "CAST_PAGE_TITLE", "CAST_STREAM", "STUB_PAUSED", "STUB_TITLE"):
            os.environ.pop(k, None)
        os.environ.update({"CAST_APP": "Arc", "CAST_PAGE": "https://site.example/show#e1", "CAST_PAGE_TITLE": TITLE,
                           "STUB_TITLE": TITLE}, **env)
        if os.path.exists(os.path.join(TMP, "tab.calls")):
            os.remove(os.path.join(TMP, "tab.calls"))
        self.thread = None

    def watch(self, latch=True):
        def body():
            link = self.m.TV("127.0.0.1")
            try:
                self.m.follow(link, self.holder)
            finally:
                link.drop()
        self.thread = threading.Thread(target=body, daemon=True)
        self.thread.start()
        if latch:
            self.log("watching")
        return self

    def log(self, text, within=12):
        """Wait for a log line containing text."""
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

    def sleep_mac(self, seconds, meanwhile=None):
        """The Mac sleeps: its clock jumps, every connection is dead when it wakes. meanwhile(tv): what the TV does
        in that time, unseen."""
        with self.tv.lock:
            if meanwhile:
                meanwhile(self.tv)
            self.skew += seconds
        self.tv.cut()

    def close(self):
        self.m.GIVE_UP = 0   # lets a watcher that is still running go at once
        self.tv.off()
        if self.thread:
            self.thread.join(8)
        assert not self.tv.sent("LAUNCH"), "the watcher LAUNCHED an app on the TV"


def synced():
    return [c for c in tab_calls() if "|settime " in c]


# ── the watcher ────────────────────────────────────────────────────────────────────────────────────────────────────
def test_plays_to_the_end(r):
    r.tv.launch().play(U1, at=72)
    r.watch().runs(0.8)
    r.tv.idle("FINISHED")
    r.ends()
    r.log("finished")
    assert not r.tv.sent("LOAD") and not synced() and not r.notes


def test_player_error_reloads_at_position(r):
    tracks = [{"trackId": 1, "type": "TEXT", "trackContentId": "https://cdn.example/s.vtt", "language": "en-US"}]
    media = {"contentId": U1, "contentType": "application/x-mpegURL", "streamType": "BUFFERED", "tracks": tracks,
             "metadata": {"metadataType": 0, "title": TITLE, "images": [{"url": "https://cdn.example/t.jpg"}]},
             "textTrackStyle": {"edgeType": "OUTLINE"}}
    r.tv.launch().play(U1, at=300, media=media, tracks=[1])
    r.watch().runs(0.8)
    at = r.tv.pos()
    r.tv.idle("ERROR")
    r.log("player error at 5:0")
    r.log("PLAYING at")
    load = r.tv.sent("LOAD")[0]
    assert load["media"]["contentId"] == U1 and load["media"]["tracks"] == tracks, load
    assert load["media"]["metadata"]["title"] == TITLE and load["media"]["textTrackStyle"], load
    assert load["activeTrackIds"] == [1] and load["autoplay"] is True and "duration" not in load["media"], load
    assert at - 6.5 < load["currentTime"] < at - 3.5, (at, load["currentTime"])
    assert r.notes == ["TV player failed — resuming at 4:5%d" % (int(load["currentTime"]) % 10)], r.notes
    r.runs(1.5)                       # and it goes on watching the reloaded video
    r.tv.idle("FINISHED")
    r.ends()
    assert len(r.tv.sent("LOAD")) == 1 and not synced()


def test_gives_up_after_3_failed_reloads(r):
    r.tv.launch().play(U1, at=100)
    r.watch().runs(0.6)
    r.tv.on_load = "error"
    r.tv.idle("ERROR")
    r.ends(15)
    r.log("player failed 3 times in 15 min — giving up at 1:4")
    assert len(r.tv.sent("LOAD")) == 3, len(r.tv.sent("LOAD"))
    assert r.notes[-1].startswith("TV player keeps failing — gave up at 1:4"), r.notes
    assert len(synced()) == 1 and synced()[0].startswith("https://site.example/show#e1|settime 10"), tab_calls()
    r.log("page moved to 1:4")


def test_load_failed_message_counts_as_failure(r):
    r.tv.launch().play(U1, at=100)
    r.watch().runs(0.6)
    r.tv.on_load = "fail"
    r.tv.idle("ERROR")
    r.ends(15)
    r.log("TV says LOAD_FAILED (104 MEDIA_SRC_NOT_SUPPORTED)")
    r.log("giving up")
    assert len(r.tv.sent("LOAD")) == 3


def test_reload_that_never_starts_is_retried(r):
    r.tv.launch().play(U1, at=100)
    r.watch().runs(0.6)
    r.tv.on_load = "ignore"
    r.tv.idle("ERROR")
    r.log("player error at")
    r.tv.session["reason"] = None     # the TV stops repeating why it is idle
    r.tv.idle_get = "noreason"
    r.ends(15)
    r.log("giving up")
    assert len(r.tv.sent("LOAD")) == 3


def test_slow_reload_is_not_interrupted(r):
    r.tv.launch().play(U1, at=100)
    r.watch().runs(0.6)
    r.tv.on_load, r.tv.load_time = "slow", 3.0          # LOADING for longer than GRACE (1.2 s here)
    r.tv.idle("ERROR")
    r.log("player error at")
    r.log("PLAYING at 1:3", within=6)
    r.runs(0.6)
    assert len(r.tv.sent("LOAD")) == 1, len(r.tv.sent("LOAD"))
    r.no_log("giving up")


def test_slow_first_load_is_waited_for(r):
    r.tv.launch()
    r.tv.on_load, r.tv.load_time = "slow", 6.0          # LOADING for longer than START (4 s here)
    r.tv.media(type("C", (), {"send": lambda *a, **k: None})(), "LOAD", {"media": {"contentId": U1, "metadata": {"title": TITLE}}}, 1)
    r.watch(latch=False)
    r.log("watching Show", within=10)
    r.runs(0.3)


def test_error_reason_sticks_when_tv_stops_repeating_it(r):
    for mode in ("noreason", "empty"):
        r.tv.launch().play(U1, at=100)
        r.tv.idle_get = mode
        r.watch().runs(0.6)
        r.tv.idle("ERROR")
        r.log("player error at")
        r.tv.idle_get = None
        r.runs(1.0)
        r.tv.idle("FINISHED")
        r.ends()
        assert len(r.tv.sent("LOAD")) == 1, mode
        r.close()
        r.__init__()


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


def test_long_pause_lets_the_mac_sleep_again(r):
    r.tv.launch().play(U1, at=200)
    r.watch().runs(0.6)
    assert r.awake == [True], r.awake
    r.tv.set("PAUSED")
    r.runs(0.6)
    assert r.awake == [True], r.awake                       # a short pause: still held
    r.runs(1.2)
    assert r.awake == [True, False], r.awake
    r.tv.set("PLAYING")
    r.runs(0.6)
    assert r.awake == [True, False, True], r.awake


def test_length_that_comes_late_still_ends_the_watch(r):
    r.tv.launch().play(U1, at=1180, duration=None, state="BUFFERING")
    r.watch().runs(0.4)
    r.tv.session["media"] = {"duration": 1200.0}            # the TV tells the length later, and only that
    r.tv.set("PLAYING")
    r.runs(0.8)
    r.tv.end_session()                                      # … and ends without saying FINISHED: near the end = finished
    r.ends()
    assert r.logs[-1] == "finished", r.logs
    assert not r.tv.sent("LOAD") and not synced()


def test_connection_cut_reconnects_and_goes_on(r):
    r.tv.launch().play(U1, at=100)
    r.watch().runs(0.6)
    r.tv.cut()
    r.log("TV connection lost")
    r.log("TV connection back after 0:0")
    r.runs(1.0)
    r.tv.idle("ERROR")                # … and still does its job on the new connection
    r.log("player error at")
    r.runs(0.5)


def test_tv_off_then_on_again(r):
    r.tv.launch().play(U1, at=100)
    r.watch().runs(0.6)
    app, session = r.tv.app, r.tv.session
    r.tv.off()
    r.log("TV connection lost")
    time.sleep(2.0)
    r.tv.start()
    r.tv.app, r.tv.session = app, session
    r.log("TV connection back after 0:0")
    r.runs(1.0)
    r.no_log("stop watching")


def test_tv_off_for_good_gives_up(r):
    r.tv.launch().play(U1, at=100)
    r.watch().runs(0.6)
    r.tv.off()
    r.ends(15)
    r.log("nothing heard from the TV for")
    r.log("last seen at 1:4")
    assert len(synced()) == 1


def test_deaf_tv_is_reconnected(r):
    r.tv.launch().play(U1, at=100)
    r.watch().runs(0.6)
    r.tv.deaf = True
    r.log("TV's player does not answer — reconnecting")
    time.sleep(1.0)
    r.tv.deaf = False
    r.log("TV connection back")
    r.runs(1.0)
    r.no_log("stop watching")


def test_deaf_tv_for_good_gives_up(r):
    r.tv.launch().play(U1, at=100)
    r.watch().runs(0.6)
    r.tv.deaf = True
    r.ends(20)
    r.log("nothing heard from the TV for")


def test_player_closed_on_tv(r):
    r.tv.launch().play(U1, at=100)
    r.watch().runs(0.6)
    r.tv.close_app()
    r.ends()
    r.log("player closed on the TV at 1:4")
    r.log("(app now: None) — Back/Home on the remote")
    assert len(synced()) == 1 and not r.notes


def test_paused_player_closed_by_tv(r):
    r.tv.launch().play(U1, at=300)
    r.watch().runs(0.6)
    r.tv.set("PAUSED")
    r.runs(0.6)
    r.tv.close_app()
    r.ends()
    r.log("the TV closes a paused player after 20 min")
    assert synced()[0].endswith("|settime 300 Arc"), tab_calls()
    assert r.notes == ["TV closed the paused player at 5:00"], r.notes


def test_another_app_takes_over(r):
    r.tv.launch().play(U1, at=100)
    r.watch().runs(0.6)
    r.tv.launch(YOUTUBE)
    r.ends()
    r.log("(app now: YouTube)")


def test_youtube_is_not_watched(r):
    r.tv.launch(YOUTUBE).play("VXq0tQsHClg", at=6, title="ArmComedy")
    r.watch(latch=False)
    r.ends()
    r.log("YouTube plays this in its own TV app — nothing to watch")
    r.no_log("player closed")
    assert not r.tv.sent("LOAD") and not synced()


def test_something_else_cast(r):
    r.tv.launch().play(U1, at=100)
    r.watch().runs(0.6)
    r.tv.idle("INTERRUPTED")
    r.tv.play(U2, at=0, title="Other")
    r.ends()
    r.log("something else was cast — stop watching")
    assert not synced() and not r.tv.sent("LOAD")


def test_same_video_cast_again_keeps_watching(r):
    r.tv.launch().play(U1, at=100)
    r.watch().runs(0.6)
    r.tv.idle("INTERRUPTED", push=True)
    r.tv.play(U1, at=400)
    r.runs(1.5)
    assert not synced() and not r.tv.sent("LOAD")


def test_stopped_from_elsewhere(r):
    r.tv.launch().play(U1, at=100)
    r.watch().runs(0.6)
    r.tv.idle("CANCELLED")
    r.ends()
    r.log("stopped (CANCELLED) at 1:4")
    assert len(synced()) == 1 and not r.tv.sent("LOAD")


def test_idle_without_reason_is_not_reloaded(r):
    r.tv.launch().play(U1, at=100)
    r.watch().runs(0.6)
    r.tv.end_session()
    r.ends()
    r.log("stopped (None) at 1:4")
    assert not r.tv.sent("LOAD")


def test_mac_sleeps_tv_plays_on(r):
    r.tv.launch().play(U1, at=100)
    r.watch().runs(0.6)
    r.sleep_mac(400)
    r.log("Mac slept 6:40")
    r.log("TV connection back")
    r.runs(1.0)
    r.tv.idle("ERROR")
    r.log("player error at 1:4")      # position from the TV, not 400 s further on by the Mac's clock
    r.runs(0.3)


def test_mac_sleeps_video_ends_meanwhile(r):
    r.tv.launch().play(U1, at=1000)
    r.watch().runs(0.6)
    r.sleep_mac(400, lambda tv: setattr(tv, "app", None) or setattr(tv, "session", None))
    r.ends()
    r.log("finished (the TV has closed its player since)")
    assert not synced() and not r.notes


def test_mac_sleeps_video_ends_player_still_open(r):
    r.tv.launch().play(U1, at=1000)
    r.watch().runs(0.6)
    r.sleep_mac(400, lambda tv: tv.end_session(push=False))
    r.ends()
    assert r.logs[-1] == "finished", r.logs
    assert not synced() and not r.tv.sent("LOAD")


def test_mac_sleeps_player_closed_meanwhile(r):
    r.tv.launch().play(U1, at=100)
    r.watch().runs(0.6)
    r.sleep_mac(400, lambda tv: setattr(tv, "app", None) or setattr(tv, "session", None))
    r.ends()
    r.log("player closed on the TV at 1:4")
    r.log("while the Mac was out of touch")
    assert len(synced()) == 1 and r.notes == ["TV player closed — last seen at 1:4%s" % r.notes[0][-1]], r.notes


def test_mac_sleeps_player_failed_meanwhile(r):
    r.tv.launch().play(U1, at=100)
    r.watch().runs(0.6)
    r.sleep_mac(400, lambda tv: tv.idle("ERROR", push=False))
    r.ends()
    r.log("player stopped (ERROR) while the Mac was out of touch — last seen at 1:4")
    assert len(synced()) == 1 and not r.tv.sent("LOAD")     # where it stopped is a guess: no reload


def test_mac_sleeps_wakes_to_a_stalled_player(r):
    r.tv.launch().play(U1, at=72)
    r.watch().runs(0.6)
    r.sleep_mac(400, lambda tv: tv.set("BUFFERING", pos=191, push=False))   # Oct 4: stuck at 3:11 at wake
    r.log("Mac slept")
    woke = time.time()
    r.log("BUFFERING at 3:11")
    r.log("no progress for")
    assert time.time() - woke < 1.5, time.time() - woke   # sooner than a whole STALL (1.8 s here): it slept through most
    load = r.tv.sent("LOAD")[0]
    assert 185 <= load["currentTime"] <= 187, load["currentTime"]
    r.runs(0.5)


def test_waits_for_the_stream_it_was_started_for(r):
    r.tv.launch().play(U1, at=500, title="Old")
    os.environ["CAST_STREAM"] = U2
    r.watch(latch=False)
    time.sleep(0.6)
    r.no_log("watching")
    r.tv.idle("INTERRUPTED")
    r.tv.play(U2, at=0, title="New")
    r.log("watching New")
    r.runs(0.5)


def test_takes_what_plays_when_the_stream_url_differs(r):
    r.tv.launch().play(U1, at=500)
    os.environ["CAST_STREAM"] = U2
    r.watch(latch=False)
    r.log("watching Show", within=4)
    r.runs(0.3)


def test_nothing_playing_at_start(r):
    r.tv.launch()
    r.watch(latch=False)
    r.ends(8)
    r.log("watch: nothing playing on the TV's media player, not watching")


def test_tv_unreachable_at_start(r):
    r.tv.off()
    r.watch(latch=False)
    r.ends(10)
    r.log("watch: nothing playing")


def test_page_left_alone_when_it_moved_on(r):
    os.environ["STUB_TITLE"] = "Show · Season 1 · Episode 2"
    r.tv.launch().play(U1, at=100)
    r.watch().runs(0.6)
    r.tv.close_app()
    r.ends()
    r.log("page left as it is")
    assert not synced()


def test_page_left_alone_when_it_plays(r):
    os.environ["STUB_PAUSED"] = "0"
    r.tv.launch().play(U1, at=100)
    r.watch().runs(0.6)
    r.tv.close_app()
    r.ends()
    r.log("page left as it is")
    assert not synced()


def test_no_page_when_cast_from_url(r):
    del os.environ["CAST_PAGE"]
    r.tv.launch().play(U1, at=100)
    r.watch().runs(0.6)
    r.tv.close_app()
    r.ends()
    assert not tab_calls()


def test_status_poll_never_launches_the_player(r):
    r.tv.launch("NOMEDIA")                               # an app without media controls is on the TV
    player = r.m.Player()
    cc = r.m.open_tv("127.0.0.1", player)
    try:
        assert r.m.ask(cc, player) is None
        time.sleep(0.3)
        assert not r.tv.sent("LAUNCH") and r.tv.app["id"] == "NOMEDIA", r.tv.sent("LAUNCH")
    finally:
        r.m.close_tv(cc)


# ── the real process: keep-awake, SIGTERM, log file ────────────────────────────────────────────────────────────────
def test_process_keeps_mac_awake_and_leaves_quietly(r):
    r.tv.launch().play(U1, at=100)
    logf = os.path.join(TMP, "proc.log")
    env = dict(os.environ, CAST_TAB_LOG=logf)
    for k in ("CAST_APP", "CAST_PAGE"):
        env.pop(k)
    p = subprocess.Popen([sys.executable, CTL, "127.0.0.1", "watch"], env=env)
    try:
        until = time.time() + 10
        while time.time() < until and not (os.path.exists(logf) and "watching" in open(logf).read()):
            time.sleep(0.1)
        assert "watching Show" in open(logf).read(), open(logf).read() if os.path.exists(logf) else "no log"
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
    logf = os.path.join(TMP, "proc2.log")
    env = dict(os.environ, CAST_TAB_LOG=logf, CAST_KEEP_AWAKE="0")
    for k in ("CAST_APP", "CAST_PAGE"):
        env.pop(k)
    p = subprocess.Popen([sys.executable, CTL, "127.0.0.1", "watch"], env=env)
    try:
        until = time.time() + 10
        while time.time() < until and not (os.path.exists(logf) and "watching" in open(logf).read()):
            time.sleep(0.1)
        assert not subprocess.run(["pgrep", "-P", str(p.pid), "caffeinate"], capture_output=True, text=True).stdout
    finally:
        p.terminate()
        p.wait(5)


# ── remote commands ────────────────────────────────────────────────────────────────────────────────────────────────
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
    expect(["stop"], "⏹ stopped")
    tv.launch().play(U1, at=60)
    tv.deaf = True
    expect(["status"], "TV takes the Cast connection but does not answer", rc=1, faster=13)
    tv.deaf = False
    tv.off()
    expect(["status"], "TV refuses the Cast connection (off, or its Cast service is restarting — try again in a minute)",
           rc=1, faster=6)
    assert not tv.sent("LAUNCH")


def test_command_right_after_wake_waits_for_the_network(r):
    tv = r.tv.launch().play(U1, at=60)
    app, session = tv.app, tv.session
    tv.off()

    def back():
        time.sleep(2)
        tv.start()
        tv.app, tv.session = app, session
    threading.Thread(target=back, daemon=True).start()
    rc, out, took, _ = ctl("time")
    assert rc == 0 and out.isdigit() and 1.5 < took < 4.5, (rc, out, took)


if __name__ == "__main__":
    VERBOSE = "-v" in sys.argv
    wanted = [a for a in sys.argv[1:] if not a.startswith("-")]
    tests = [(n, f) for n, f in list(globals().items()) if n.startswith("test_") and (not wanted or any(w in n for w in wanted))]
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
            rig.m.GIVE_UP = 0   # let its watcher go before the next test starts
            rig.tv.off()
            if rig.thread:
                rig.thread.join(10)
        time.sleep(0.3)
    print("\n%d passed, %d failed%s" % (len(tests) - len(failed), len(failed), ": " + ", ".join(failed) if failed else ""))
    sys.exit(1 if failed else 0)
