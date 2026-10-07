# fake_tv.py — a scriptable stand-in for the TV's Cast receiver (TLS + protobuf on 127.0.0.1:8009), to test cast-ctl
# without a TV: it can lose connections, go deaf, fail or stall its player, close the app. Run with catt's python.
import json
import os
import socket
import ssl
import struct
import subprocess
import tempfile
import threading
import time
import uuid

from pychromecast.generated.cast_channel_pb2 import CastMessage

CONN, BEAT = "urn:x-cast:com.google.cast.tp.connection", "urn:x-cast:com.google.cast.tp.heartbeat"
RECV, MEDIA = "urn:x-cast:com.google.cast.receiver", "urn:x-cast:com.google.cast.media"
DEFAULT, YOUTUBE = "CC1AD845", "233637DE"
APPS = {DEFAULT: ("Default Media Receiver", [MEDIA]), YOUTUBE: ("YouTube", ["urn:x-cast:com.google.youtube.mdx", MEDIA]),
        "NOMEDIA": ("Screensaver", ["urn:x-cast:com.example.none"])}
_cert = None


def cert():
    global _cert
    if not _cert:
        d = tempfile.mkdtemp(prefix="faketv-")
        _cert = (os.path.join(d, "c.pem"), os.path.join(d, "k.pem"))
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2", "-subj", "/CN=faketv",
                        "-out", _cert[0], "-keyout", _cert[1]], check=True, capture_output=True)
    return _cert


class Conn:
    def __init__(self, tv, raw):
        self.tv, self.raw, self.wlock, self.links = tv, raw, threading.Lock(), set()

    def send(self, ns, data, src="receiver-0", dst="sender-0"):
        m = CastMessage()
        m.protocol_version, m.source_id, m.destination_id = m.CASTV2_1_0, src, dst
        m.payload_type, m.namespace, m.payload_utf8 = CastMessage.STRING, ns, json.dumps(data)
        body = m.SerializeToString()
        try:
            with self.wlock:
                self.raw.sendall(struct.pack(">I", len(body)) + body)
        except OSError:
            pass

    def close(self):
        try:
            self.raw.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.raw.close()

    def read(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.raw.recv(n - len(buf))
            if not chunk:
                raise OSError("closed")
            buf += chunk
        return buf

    def run(self):
        try:
            if self.tv.hang_tls:
                time.sleep(3600)
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(*cert())
            self.raw = ctx.wrap_socket(self.raw, server_side=True)
            while True:
                m = CastMessage()
                m.ParseFromString(self.read(struct.unpack(">I", self.read(4))[0]))
                self.tv.handle(self, m, json.loads(m.payload_utf8))
        except (OSError, ValueError):
            pass
        finally:
            with self.tv.lock:
                if self in self.tv.conns:
                    self.tv.conns.remove(self)
            self.close()


class FakeTV:
    def __init__(self, port=8009):
        self.port, self.lock, self.server, self.conns = port, threading.RLock(), None, []
        self.got = []            # (namespace, data, destination) of what senders sent, heartbeats aside
        self.app = self.session = None
        self.n = 0
        self.volume = {"controlType": "master", "level": 0.24, "muted": False, "stepInterval": 0.02}
        self.hang_tls = False    # takes the TCP connection, never does the TLS handshake
        self.deaf = False        # takes messages, answers nothing at all
        self.mute_media = False  # the player app answers nothing
        self.ignore = set()      # media commands the player silently drops, e.g. {"PAUSE"}
        self.on_load = "play"    # what a LOAD does: play | stall | error | fail | ignore | slow (LOADING for load_time s)
        self.load_time = 3.0
        self.idle_get = None     # GET_STATUS while idle: None = full status, "noreason", "empty" (status: [])
        self.stop_cuts = False   # a receiver STOP is answered by cutting the connection (Samsung's service restart)

    # ── the box ──────────────────────────────────────────────────────────────────────────────────────────────────
    def start(self):
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", self.port))
        s.listen(16)
        s.settimeout(0.1)
        self.server = s
        threading.Thread(target=self._accept, args=(s,), daemon=True).start()
        return self

    def _accept(self, s):
        while self.server is s:
            try:
                raw, _ = s.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            raw.settimeout(None)
            c = Conn(self, raw)
            with self.lock:
                self.conns.append(c)
            threading.Thread(target=c.run, daemon=True).start()
        s.close()

    def off(self):
        """Power off / Cast service down: nothing listens, every sender is cut."""
        self.server = None
        time.sleep(0.25)
        self.cut()

    def cut(self):
        """Drop every sender's connection (Wi-Fi blip, Cast service restart)."""
        for c in list(self.conns):
            c.close()

    # ── receiver ─────────────────────────────────────────────────────────────────────────────────────────────────
    def launch(self, app_id=DEFAULT):
        name, ns = APPS[app_id]
        sid = str(uuid.uuid4())
        with self.lock:
            self.app, self.session = {"id": app_id, "name": name, "ns": ns, "sid": sid}, None
        self.tell_all()
        return self

    def close_app(self):
        with self.lock:
            self.app = self.session = None
        self.tell_all()

    def receiver_status(self, rid=0):
        st = {"volume": dict(self.volume)}
        a = self.app
        if a:
            st["applications"] = [{"appId": a["id"], "appType": "WEB", "displayName": a["name"], "statusText": a["name"],
                                   "namespaces": [{"name": n} for n in a["ns"]], "sessionId": a["sid"],
                                   "transportId": a["sid"], "universalAppId": a["id"], "senderConnected": True}]
        return {"requestId": rid, "status": st, "type": "RECEIVER_STATUS"}

    def tell_all(self):
        if not self.deaf:
            for c in list(self.conns):
                c.send(RECV, self.receiver_status(), dst="*")

    # ── player ───────────────────────────────────────────────────────────────────────────────────────────────────
    def play(self, url, at=0.0, title="Show · Season 1 · Episode 1", duration=1200.0, state="PLAYING", media=None,
             tracks=None):
        media = dict(media or {"contentId": url, "contentType": "application/x-mpegURL", "streamType": "BUFFERED",
                               "metadata": {"metadataType": 0, "title": title}})
        if duration:
            media["duration"] = duration
        with self.lock:
            self.n += 1
            self.session = {"id": self.n, "state": state, "base": float(at), "t0": time.monotonic(), "media": media,
                            "tracks": tracks, "reason": None, "frozen": False}
        self.push()
        return self

    def pos(self):
        s = self.session
        if s["state"] == "PLAYING" and not s["frozen"]:
            return min(s["base"] + time.monotonic() - s["t0"], s["media"].get("duration") or 1e9)
        return s["base"]

    def set(self, state, pos=None, reason=None, push=True):
        with self.lock:
            s = self.session
            s["base"], s["t0"] = (self.pos() if pos is None else float(pos)), time.monotonic()
            s["state"], s["reason"], s["frozen"] = state, reason, False
        if push:
            self.push()

    def freeze(self):
        """Says PLAYING, picture and clock stand still."""
        with self.lock:
            self.session["base"], self.session["frozen"] = self.pos(), True

    def idle(self, reason, push=True):
        self.set("IDLE", reason=reason, push=push)

    def end_session(self, push=True):
        with self.lock:
            self.session = None
        if push:
            self.push()

    def media_status(self, rid=0, poll=False):
        s = self.session
        if not s or (poll and s["state"] == "IDLE" and self.idle_get == "empty"):
            return {"type": "MEDIA_STATUS", "status": [], "requestId": rid}
        st = {"mediaSessionId": s["id"], "playbackRate": 1, "supportedMediaCommands": 12303, "playerState": s["state"],
              "currentTime": 0 if s["state"] == "IDLE" else round(self.pos(), 3), "media": s["media"],
              "volume": {"level": 1, "muted": False}}
        if s.get("loading"):   # what a receiver says while a LOAD is under way: idle, with the new media on the side
            st["extendedStatus"] = {"playerState": "LOADING", "media": st.pop("media"), "mediaSessionId": s["id"]}
        if s["tracks"] is not None:
            st["activeTrackIds"] = s["tracks"]
        if s["state"] == "IDLE" and s["reason"] and not (poll and self.idle_get == "noreason"):
            st["idleReason"] = s["reason"]
        return {"type": "MEDIA_STATUS", "status": [st], "requestId": rid}

    def push(self):
        if self.app and not self.deaf and not self.mute_media:
            for c in list(self.conns):
                if self.app["sid"] in c.links:
                    c.send(MEDIA, self.media_status(), src=self.app["sid"], dst="*")

    # ── what senders say ─────────────────────────────────────────────────────────────────────────────────────────
    def sent(self, kind):
        return [d for _, d, _ in self.got if d.get("type") == kind]

    def handle(self, c, m, d):
        kind, rid = d.get("type"), d.get("requestId", 0)
        if m.namespace == BEAT:
            if kind == "PING" and not self.deaf:
                c.send(BEAT, {"type": "PONG"})
            return
        self.got.append((m.namespace, d, m.destination_id))
        if self.deaf:
            return
        if m.namespace == CONN:
            (c.links.add if kind == "CONNECT" else c.links.discard)(m.destination_id)
        elif m.namespace == RECV:
            if kind == "LAUNCH":
                self.launch(d["appId"])
            elif kind == "STOP":
                if self.stop_cuts:
                    with self.lock:
                        self.app = self.session = None
                    return self.cut()
                self.close_app()
            elif kind == "SET_VOLUME":
                self.volume.update(d["volume"])
            c.send(RECV, self.receiver_status(rid))
        elif m.namespace == MEDIA and self.app and m.destination_id == self.app["sid"] and MEDIA in self.app["ns"]:
            if not self.mute_media and kind not in self.ignore:
                self.media(c, kind, d, rid)

    def media(self, c, kind, d, rid):
        def answer(msg=None):
            c.send(MEDIA, msg or self.media_status(rid, poll=kind == "GET_STATUS"), src=self.app["sid"])

        s = self.session
        if kind == "GET_STATUS":
            return answer()
        if kind == "LOAD":
            if self.on_load == "ignore":
                return
            if self.on_load == "fail":
                self.end_session()
                return answer({"type": "LOAD_FAILED", "requestId": rid, "itemId": 1, "detailedErrorCode": 104})
            if s and s["state"] != "IDLE":
                self.idle("INTERRUPTED")
            self.play(None, at=d.get("currentTime") or 0, media=d["media"], tracks=d.get("activeTrackIds"),
                      duration=(s or {}).get("media", {}).get("duration", 1200.0),
                      state={"stall": "BUFFERING", "slow": "IDLE"}.get(self.on_load, "PLAYING"))
            if self.on_load == "error":
                self.idle("ERROR")
            if self.on_load == "slow":
                mine = self.session
                mine["loading"] = True

                def loaded():
                    if self.session is mine:
                        mine["loading"] = False
                        self.set("PLAYING", pos=mine["base"])
                threading.Timer(self.load_time, loaded).start()
                self.push()
            return answer()
        if not s or d.get("mediaSessionId") != s["id"]:
            return answer({"type": "INVALID_REQUEST", "requestId": rid, "reason": "INVALID_MEDIA_SESSION_ID"})
        if kind == "PAUSE":
            self.set("PAUSED", push=False)
        elif kind == "PLAY":
            self.set("PLAYING", push=False)
        elif kind == "SEEK":
            self.set(s["state"], pos=d["currentTime"], push=False)
        elif kind == "STOP":
            self.idle("CANCELLED", push=False)
        answer()
        self.push()


if __name__ == "__main__":   # a TV to poke at by hand: default player running, one video playing
    tv = FakeTV().start().launch()
    tv.play("https://example.com/video.m3u8", at=60)
    print("fake TV on 127.0.0.1:8009 — try: cast-ctl 127.0.0.1 status")
    while True:
        time.sleep(1)
