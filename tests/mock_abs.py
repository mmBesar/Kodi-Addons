# SPDX-License-Identifier: GPL-3.0-or-later
"""A small in-process Audiobookshelf look-alike for tests.

Behaviour mirrors what was verified in audiobookshelf v2.37.1 sources:
  * /login returns accessToken (+ refreshToken only with x-return-tokens: true)
  * /auth/refresh rotates the refresh token
  * Bearer auth on /api, none on /public/session/<id>/track/<n>, none for covers
  * /api/session/local merges by last-write-wins on updatedAt
"""
import base64
import json
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

AUDIO = (b"ID3" + bytes(range(256))) * 400  # ~100 KB of fake audio


def jwt(exp):
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return "%s.%s.sig" % (enc({"alg": "none"}), enc({"exp": int(exp), "n": uuid.uuid4().hex[:6]}))


class State:
    def __init__(self):
        self.username, self.password = "mohanad", "secret"
        self.api_key = "key-123"
        self.access_tokens = {}      # token -> exp
        self.refresh_tokens = set()
        self.requests = []           # (method, path)
        self.offline = False
        self.progress = {}           # key -> mediaProgress dict
        self.sessions = {}           # id -> session dict
        self.syncs = []              # (session id, body)
        self.closes = []
        self.local_sessions = []
        self.public_auth = []
        self.logins = 0
        self.refreshes = 0
        self.access_ttl = 3600
        self.podcast_item = {
            "id": "li_pod1", "mediaType": "podcast", "updatedAt": 1,
            "media": {
                "metadata": {"title": "Linux Show", "author": "Host", "feedUrl": "http://feed"},
                "episodes": [
                    {"id": "ep_1", "title": "Episode One", "publishedAt": 1700000000000, "duration": 1800,
                     "description": "<p>Hello &amp; welcome</p>",
                     "audioFile": {"ino": "111", "duration": 1800, "metadata": {"filename": "one.mp3", "size": len(AUDIO)}}},
                    {"id": "ep_2", "title": "Episode Two", "publishedAt": 1700500000000, "duration": 900,
                     "audioFile": {"ino": "222", "duration": 900, "metadata": {"filename": "two.mp3", "size": len(AUDIO)}}},
                ]}}
        self.book_item = {
            "id": "li_book1", "mediaType": "book", "updatedAt": 1,
            "media": {
                "metadata": {"title": "Big Book", "authorName": "Some Author"},
                "duration": 7200, "chapters": [{"id": 0, "start": 0, "end": 3600, "title": "Part 1"},
                                                {"id": 1, "start": 3600, "end": 7200, "title": "Part 2"}],
                "tracks": [
                    {"index": 1, "startOffset": 0, "duration": 3600, "contentUrl": "/api/items/li_book1/file/b1",
                     "metadata": {"filename": "b1.mp3", "size": len(AUDIO)}},
                    {"index": 2, "startOffset": 3600, "duration": 3600, "contentUrl": "/api/items/li_book1/file/b2",
                     "metadata": {"filename": "b2.mp3", "size": len(AUDIO)}}]}}

    def item(self, item_id):
        return {"li_pod1": self.podcast_item, "li_book1": self.book_item}.get(item_id)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    state = None

    def log_message(self, *a):
        pass

    # ---- helpers
    def _body(self):
        return json.loads(self._raw) if self._raw else {}

    def _send(self, code, obj=None, raw=None, headers=None):
        data = raw if raw is not None else (json.dumps(obj).encode() if obj is not None else b"")
        self.send_response(code)
        self.send_header("Content-Length", str(len(data)))
        if raw is None and obj is not None:
            self.send_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _authed(self):
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return False
        token = auth[7:]
        s = self.state
        return token == s.api_key or s.access_tokens.get(token, 0) > time.time()

    def _file(self):
        rng = self.headers.get("Range")
        if rng:
            m = re.match(r"bytes=(\d+)-(\d*)", rng)
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else len(AUDIO) - 1
            if start >= len(AUDIO):
                return self._send(416, raw=b"")
            end = min(end, len(AUDIO) - 1)
            return self._send(206, raw=AUDIO[start:end + 1], headers={
                "Content-Range": "bytes %d-%d/%d" % (start, end, len(AUDIO)), "Accept-Ranges": "bytes"})
        self._send(200, raw=AUDIO, headers={"Accept-Ranges": "bytes", "Content-Type": "audio/mpeg"})

    # ---- routing
    def _route(self, method):
        s = self.state
        n = int(self.headers.get("Content-Length") or 0)
        self._raw = self.rfile.read(n) if n else b""  # always drain the body, like Express
        path = self.path.split("?")[0]
        s.requests.append((method, path))
        if s.offline:
            self.close_connection = True
            self.connection.close()
            return
        if path == "/ping":
            return self._send(200, {"success": True})
        if method == "POST" and path == "/login":
            b = self._body()
            if b.get("username") != s.username or b.get("password") != s.password:
                return self._send(401, raw=b"Unauthorized")
            s.logins += 1
            access = jwt(time.time() + s.access_ttl)
            s.access_tokens[access] = time.time() + s.access_ttl
            user = {"username": s.username, "type": "admin", "accessToken": access, "refreshToken": None}
            if self.headers.get("x-return-tokens") == "true":
                refresh = "r-" + uuid.uuid4().hex
                s.refresh_tokens.add(refresh)
                user["refreshToken"] = refresh
            return self._send(200, {"user": user})
        if method == "POST" and path == "/auth/refresh":
            old = self.headers.get("x-refresh-token")
            if old not in s.refresh_tokens:
                return self._send(401, {"error": "Invalid refresh token"})
            s.refreshes += 1
            s.refresh_tokens.discard(old)
            new_refresh = "r-" + uuid.uuid4().hex
            s.refresh_tokens.add(new_refresh)
            access = jwt(time.time() + s.access_ttl)
            s.access_tokens[access] = time.time() + s.access_ttl
            return self._send(200, {"user": {"accessToken": access, "refreshToken": new_refresh}})
        m = re.match(r"^/public/session/([^/]+)/track/(\d+)$", path)
        if m:
            s.public_auth.append(self.headers.get("Authorization"))
            return self._file() if m.group(1) in s.sessions else self._send(404, raw=b"")
        if re.match(r"^/api/items/[^/]+/cover$", path):
            return self._send(200, raw=b"\xff\xd8jpeg", headers={"Content-Type": "image/jpeg"})
        if not self._authed():
            return self._send(401, raw=b"Unauthorized")
        if path == "/api/me":
            return self._send(200, {"username": s.username, "type": "admin",
                                    "mediaProgress": list(s.progress.values())})
        if path == "/api/libraries":
            return self._send(200, {"libraries": [
                {"id": "lib_pod", "name": "Podcasts", "mediaType": "podcast"},
                {"id": "lib_book", "name": "Books", "mediaType": "book"}]})
        m = re.match(r"^/api/libraries/([^/]+)/items$", path)
        if m:
            item = s.podcast_item if m.group(1) == "lib_pod" else s.book_item
            mini = {"id": item["id"], "mediaType": item["mediaType"],
                    "media": {"metadata": item["media"]["metadata"], "duration": item["media"].get("duration", 0)}}
            return self._send(200, {"results": [mini], "total": 1})
        m = re.match(r"^/api/libraries/([^/]+)/search$", path)
        if m:
            item = s.podcast_item if m.group(1) == "lib_pod" else s.book_item
            mini = {"id": item["id"], "mediaType": item["mediaType"],
                    "media": {"metadata": item["media"]["metadata"], "duration": item["media"].get("duration", 0)}}
            return self._send(200, {("podcast" if m.group(1) == "lib_pod" else "book"): [{"libraryItem": mini}]})
        m = re.match(r"^/api/libraries/([^/]+)/recent-episodes$", path)
        if m:
            eps = [dict(e, libraryItemId="li_pod1", podcast={"metadata": s.podcast_item["media"]["metadata"]})
                   for e in s.podcast_item["media"]["episodes"]]
            return self._send(200, {"episodes": eps})
        if path == "/api/me/items-in-progress":
            return self._send(200, {"libraryItems": []})
        m = re.match(r"^/api/items/([^/]+)$", path)
        if method == "GET" and m:
            item = s.item(m.group(1))
            return self._send(200 if item else 404, item or {})
        m = re.match(r"^/api/items/([^/]+)/file/([^/]+)$", path)
        if m:
            return self._file()
        m = re.match(r"^/api/items/([^/]+)/play(?:/([^/]+))?$", path)
        if method == "POST" and m:
            item, ep = s.item(m.group(1)), m.group(2)
            if not item:
                return self._send(404, raw=b"")
            key = m.group(1) + (":" + ep if ep else "")
            sid = str(uuid.uuid4())
            prog = s.progress.get(key)
            start = 0 if (not prog or prog.get("isFinished")) else prog["currentTime"]
            if ep:
                e = next(e for e in item["media"]["episodes"] if e["id"] == ep)
                tracks = [{"index": 1, "startOffset": 0, "duration": e["duration"]}]
                title, author, dur = e["title"], item["media"]["metadata"]["author"], e["duration"]
                mtype, meta = "podcast", {"title": item["media"]["metadata"]["title"]}
            else:
                tracks = [{"index": t["index"], "startOffset": t["startOffset"], "duration": t["duration"]}
                          for t in item["media"]["tracks"]]
                title, author, dur = item["media"]["metadata"]["title"], item["media"]["metadata"]["authorName"], item["media"]["duration"]
                mtype, meta = "book", {"title": title}
            sess = {"id": sid, "libraryItemId": m.group(1), "episodeId": ep, "mediaType": mtype,
                    "displayTitle": title, "displayAuthor": author, "duration": dur, "currentTime": start,
                    "mediaMetadata": meta, "audioTracks": tracks}
            s.sessions[sid] = sess
            return self._send(200, sess)
        m = re.match(r"^/api/session/([^/]+)/(sync|close)$", path)
        if method == "POST" and m and m.group(1) != "local":
            sid, kind = m.group(1), m.group(2)
            sess = s.sessions.get(sid)
            if not sess:
                return self._send(404, raw=b"")
            body = self._body()
            (s.syncs if kind == "sync" else s.closes).append((sid, body))
            key = sess["libraryItemId"] + (":" + sess["episodeId"] if sess["episodeId"] else "")
            finished = body["duration"] and (body["duration"] - body["currentTime"]) < 5
            s.progress[key] = {"libraryItemId": sess["libraryItemId"], "episodeId": sess["episodeId"],
                               "currentTime": body["currentTime"], "duration": body["duration"],
                               "isFinished": bool(finished), "lastUpdate": int(time.time() * 1000)}
            if kind == "close":
                del s.sessions[sid]
            return self._send(200, raw=b"OK")
        if method == "POST" and path == "/api/session/local":
            body = self._body()
            s.local_sessions.append(body)
            key = body["libraryItemId"] + (":" + body["episodeId"] if body.get("episodeId") else "")
            cur = s.progress.get(key)
            if not cur or cur["lastUpdate"] <= body["updatedAt"]:  # last write wins
                finished = body["duration"] and (body["duration"] - body["currentTime"]) < 5
                s.progress[key] = {"libraryItemId": body["libraryItemId"], "episodeId": body.get("episodeId"),
                                   "currentTime": body["currentTime"], "duration": body["duration"],
                                   "isFinished": bool(finished), "lastUpdate": body["updatedAt"]}
            return self._send(200, raw=b"OK")
        m = re.match(r"^/api/me/progress/([^/]+)(?:/([^/]+))?$", path)
        if m:
            key = m.group(1) + (":" + m.group(2) if m.group(2) else "")
            if method == "GET":
                return self._send(200, s.progress[key]) if key in s.progress else self._send(404, raw=b"")
            if method == "PATCH":
                b = self._body()
                cur = s.progress.setdefault(key, {"libraryItemId": m.group(1), "episodeId": m.group(2),
                                                   "currentTime": 0, "duration": 0})
                cur.update(b)
                cur["lastUpdate"] = int(time.time() * 1000)
                return self._send(200, raw=b"OK")
        self._send(404, raw=b"")

    def do_GET(self):
        self._route("GET")

    def do_HEAD(self):  # Express answers HEAD for every GET route
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def do_PATCH(self):
        self._route("PATCH")


def start():
    state = State()
    handler = type("H", (Handler,), {"state": state})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state.url = "http://127.0.0.1:%d" % server.server_address[1]
    state.server = server
    return state
