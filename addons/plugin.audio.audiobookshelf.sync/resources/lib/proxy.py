# SPDX-License-Identifier: GPL-3.0-or-later
"""Loopback proxy: Kodi speaks plain HTTP to 127.0.0.1, Python speaks HTTPS upstream.

Why: Kodi fetches stream and artwork URLs with its own libcurl stack, which can
fail on HTTPS setups (HTTP/2 servers such as Caddy, private CA certificates, old
CA bundles) even though Python's TLS works. Routing those two kinds of request
through the add-on removes Kodi's TLS stack from the picture.

Scope is deliberately tiny and never carries credentials:
  GET|HEAD /t/<session id>/<track index>  ->  <server>/public/session/<id>/track/<n>
  GET|HEAD /c/<item id>?w=<px>            ->  <server>/api/items/<id>/cover  (cached on disk)
Both upstream routes are unauthenticated on the Audiobookshelf server, the proxy
listens on loopback only, and any other path is rejected.
"""
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import requests

from . import api, utils

PROXY_PROPERTY = utils.PROXY_PROPERTY
DEFAULT_PORT = 18733  # stable so Kodi's texture cache keeps matching cover URLs
COVER_TTL = 7 * 86400
CHUNK = 64 * 1024
TRACK_RE = re.compile(r"^/t/([0-9A-Za-z-]{8,64})/(\d{1,4})$")
COVER_RE = re.compile(r"^/c/([0-9A-Za-z_-]{6,64})$")
PASS_HEADERS = ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges", "Last-Modified", "ETag")

_http = None
_http_lock = threading.Lock()


def cover_dir():
    path = os.path.join(utils.PROFILE, "covers")
    os.makedirs(path, exist_ok=True)
    return path


def _session():
    global _http
    with _http_lock:
        if _http is None:
            _http = api._build_session()
        return _http


def _upstream_base():
    return api.normalize_url(utils.s_str("server_url"))


def _verify():
    return utils.s_bool("verify_ssl", True)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ABSProxy/1"

    def log_message(self, *args):  # keep Kodi's log clean
        pass

    def do_GET(self):
        self._route(head=False)

    def do_HEAD(self):
        self._route(head=True)

    # ------------------------------------------------------------- plumbing
    def _empty(self, code):
        self.send_response(code)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _route(self, head):
        try:
            parts = urlsplit(self.path)
            match = TRACK_RE.match(parts.path)
            if match:
                return self._track(match.group(1), match.group(2), head)
            match = COVER_RE.match(parts.path)
            if match:
                width = _width(parse_qs(parts.query).get("w", ["600"])[0])
                return self._cover(match.group(1), width, head)
            self._empty(404)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self.close_connection = True
        except Exception as exc:  # never let a handler thread die noisily
            utils.debug("proxy error: %s" % exc)
            self.close_connection = True

    # ---------------------------------------------------------------- tracks
    def _track(self, session_id, index, head):
        base = _upstream_base()
        if not base:
            return self._empty(503)
        headers = {"Accept-Encoding": "identity"}
        for name in ("Range", "If-Range", "If-None-Match", "If-Modified-Since"):
            if self.headers.get(name):
                headers[name] = self.headers[name]
        url = "%s/public/session/%s/track/%s" % (base, session_id, index)
        try:
            up = _session().request("HEAD" if head else "GET", url, headers=headers, stream=True,
                                    timeout=(5, 30), verify=_verify())
        except requests.exceptions.RequestException as exc:
            utils.debug("proxy upstream failed: %s" % type(exc).__name__)
            return self._empty(502)
        try:
            self.send_response(up.status_code)
            if up.status_code >= 400:  # error: status only, no body, so no upstream length
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            for name in PASS_HEADERS:
                if up.headers.get(name):
                    self.send_header(name, up.headers[name])
            if up.headers.get("Content-Length") is None and not head:
                self.send_header("Connection", "close")  # unknown length: delimit by closing
                self.close_connection = True
            self.end_headers()
            if head:
                return
            try:
                for chunk in up.raw.stream(CHUNK, decode_content=False):
                    self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                self.close_connection = True  # Kodi seeked or stopped
            except Exception as exc:  # upstream dropped mid-stream
                utils.debug("proxy stream interrupted: %s" % type(exc).__name__)
                self.close_connection = True
        finally:
            up.close()

    # ---------------------------------------------------------------- covers
    def _cover(self, item_id, width, head):
        path = os.path.join(cover_dir(), "%s-%d.jpg" % (item_id, width))
        data = None
        if os.path.exists(path) and time.time() - os.path.getmtime(path) < COVER_TTL:
            data = _read(path)
        if data is None:
            base = _upstream_base()
            try:
                if base:
                    resp = _session().get("%s/api/items/%s/cover" % (base, item_id),
                                          params={"width": width, "format": "jpeg"},
                                          timeout=(5, 20), verify=_verify())
                    if resp.status_code == 200 and resp.content:
                        data = resp.content
                        _write(path, data)
            except requests.exceptions.RequestException as exc:
                utils.debug("cover fetch failed: %s" % type(exc).__name__)
            if data is None and os.path.exists(path):
                data = _read(path)  # stale beats nothing (offline browsing)
        if data is None:
            return self._empty(404)
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "max-age=86400")
        self.end_headers()
        if not head:
            self.wfile.write(data)


def _width(raw):
    try:
        return max(100, min(1000, int(raw)))
    except ValueError:
        return 600


def _read(path):
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def _write(path, data):
    tmp = path + ".tmp"
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except OSError:
        pass


def start():
    """Start the proxy on loopback and publish its port for the plugin side."""
    server = None
    for port in (DEFAULT_PORT, 0):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            continue
    if server is None:
        utils.log("local proxy could not start; Kodi will use direct URLs")
        return None
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.5}, daemon=True).start()
    utils.home_window().setProperty(PROXY_PROPERTY, str(server.server_address[1]))
    utils.log("local proxy listening on 127.0.0.1:%d" % server.server_address[1])
    return server


def stop(server):
    if server is None:
        return
    utils.home_window().clearProperty(PROXY_PROPERTY)
    server.shutdown()
    server.server_close()
