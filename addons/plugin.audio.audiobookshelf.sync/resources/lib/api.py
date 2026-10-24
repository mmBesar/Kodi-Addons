# SPDX-License-Identifier: GPL-3.0-or-later
"""Audiobookshelf API client.

Auth modes
  0  API key (Bearer, long-lived, recommended)
  1  Username + password. ABS >= 2.26 issues 1-hour access tokens and rotating
     refresh tokens, so tokens are cached in the profile folder and refreshed
     transparently. Servers that predate this return a single token instead.

Secrets are never written to the Kodi log and never placed in URLs that are
handed to the player: streaming uses the public session-track route and
covers need no authentication on the server side.
"""
import base64
import json
import os
import time
from urllib.parse import quote, urlsplit

import requests
from requests.adapters import HTTPAdapter

try:
    from urllib3.util.retry import Retry
except ImportError:  # pragma: no cover - ancient bundled urllib3
    Retry = None

from . import utils

AUTH_FILE = os.path.join(utils.PROFILE, "auth.json")
CONNECT_TIMEOUT = 5
READ_TIMEOUT = 25
SYNC_TIMEOUT = (4, 8)
MIME_TYPES = [
    "audio/mpeg", "audio/mp4", "audio/x-m4a", "audio/x-m4b", "audio/aac",
    "audio/flac", "audio/ogg", "audio/opus", "audio/webm", "audio/wav",
    "audio/x-ms-wma", "audio/x-aiff", "audio/vnd.wave",
]


class ABSError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class ABSConnectionError(ABSError):
    """Server unreachable (offline, DNS, TLS, timeout)."""


class ABSAuthError(ABSError):
    pass


class ABSForbidden(ABSError):
    pass


class ABSNotFound(ABSError):
    pass


def normalize_url(raw):
    """Accept 'abs.example.com', 'https://abs.example.com/' or a sub-path URL."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    parts = urlsplit(raw)
    if not parts.netloc:
        return ""
    return "%s://%s%s" % (parts.scheme, parts.netloc, parts.path.rstrip("/"))


def _jwt_exp(token):
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return int(json.loads(base64.urlsafe_b64decode(payload)).get("exp", 0))
    except Exception:
        return 0


def _build_session():
    session = requests.Session()
    if Retry is not None:
        try:
            retry = Retry(total=2, connect=2, read=0, backoff_factor=0.6,
                          status_forcelist=(502, 503, 504),
                          allowed_methods=frozenset(["GET", "HEAD"]))
        except TypeError:  # urllib3 < 1.26
            retry = Retry(total=2, connect=2, read=0, backoff_factor=0.6,
                          status_forcelist=(502, 503, 504),
                          method_whitelist=frozenset(["GET", "HEAD"]))
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
    session.headers["User-Agent"] = "Kodi-%s/%s" % (utils.ADDON_ID, utils.ADDON_VERSION)
    return session


class ABSClient:
    def __init__(self):
        self.base = normalize_url(utils.s_str("server_url"))
        self.verify = utils.s_bool("verify_ssl", True)
        self.mode = utils.s_int("auth_method", 0)
        self.http = _build_session()
        self._quick_http = requests.Session()  # no retries: offline checks must fail fast
        self._quick_http.headers.update(self.http.headers)
        self._auth = self._load_auth()

    # ------------------------------------------------------------------ auth
    def configured(self):
        if not self.base:
            return False
        if self.mode == 0:
            return bool(utils.s_str("api_key").strip())
        return bool(utils.s_str("username")) and bool(utils.s_str("password"))

    def _identity(self):
        return {"server": self.base, "user": utils.s_str("username")}

    def _load_auth(self):
        if self.mode != 1:
            return {}
        try:
            with open(AUTH_FILE, "r") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return {}
        ident = self._identity()
        if data.get("server") != ident["server"] or data.get("user") != ident["user"]:
            return {}
        return data

    def _save_auth(self, access, refresh):
        data = dict(self._identity())
        data.update({"access": access, "refresh": refresh or "", "exp": _jwt_exp(access)})
        self._auth = data
        tmp = AUTH_FILE + ".tmp"
        try:
            with open(tmp, "w") as fh:
                json.dump(data, fh)
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, AUTH_FILE)
        except OSError as exc:
            utils.log("could not persist auth state: %s" % exc)

    def _login(self):
        username = utils.s_str("username")
        password = utils.s_str("password")
        if not (username and password):
            raise ABSAuthError("Username and password are required")
        resp = self._send("POST", "/login", auth=False, json_body={"username": username, "password": password},
                          headers={"x-return-tokens": "true"})
        user = (self._parse(resp) or {}).get("user") or {}
        access = user.get("accessToken") or user.get("token")
        if not access:
            raise ABSAuthError("Server did not return a token")
        self._save_auth(access, user.get("refreshToken"))

    def _refresh(self):
        refresh = self._auth.get("refresh")
        if not refresh:
            return False
        try:
            resp = self._send("POST", "/auth/refresh", auth=False, headers={"x-refresh-token": refresh})
            user = (self._parse(resp) or {}).get("user") or {}
        except ABSAuthError:
            return False
        access = user.get("accessToken")
        if not access:
            return False
        # Refresh tokens rotate: always persist the new one.
        self._save_auth(access, user.get("refreshToken") or refresh)
        return True

    def _ensure_token(self):
        if self.mode == 0:
            key = utils.s_str("api_key").strip()
            if not key:
                raise ABSAuthError("API key is not set")
            return key
        exp = self._auth.get("exp", 0)  # 0 = legacy non-expiring token
        if not self._auth.get("access") or (exp and exp - time.time() < 60):
            if not (self._auth.get("access") and self._refresh()):
                self._login()
        return self._auth.get("access")

    def _reauth(self):
        if self.mode == 0:
            return False
        if not self._refresh():
            self._login()
        return True

    # ------------------------------------------------------------- transport
    def _headers(self, extra=None, auth=True):
        headers = {"Accept": "application/json"}
        if auth:
            headers["Authorization"] = "Bearer " + self._ensure_token()
        if extra:
            headers.update(extra)
        return headers

    def _send(self, method, path, auth=True, params=None, json_body=None, headers=None,
              stream=False, timeout=None, quick=False):
        if not self.base:
            raise ABSError("Server URL is not set")
        http = self._quick_http if quick else self.http
        if quick:
            timeout = (2, 3)
        try:
            return http.request(
                method, self.base + path, headers=self._headers(headers, auth), params=params,
                json=json_body, stream=stream, verify=self.verify,
                timeout=timeout or (CONNECT_TIMEOUT, READ_TIMEOUT))
        except requests.exceptions.SSLError as exc:
            raise ABSConnectionError("TLS error: %s" % str(exc)[:120])
        except requests.exceptions.RequestException as exc:
            raise ABSConnectionError("Cannot reach server: %s" % type(exc).__name__)

    @staticmethod
    def _parse(resp):
        if resp.status_code == 401:
            raise ABSAuthError("Authentication failed (401)", 401)
        if resp.status_code == 403:
            raise ABSForbidden("Permission denied (403)", 403)
        if resp.status_code == 404:
            raise ABSNotFound("Not found (404)", 404)
        if resp.status_code >= 400:
            raise ABSError("Server error %d: %s" % (resp.status_code, resp.text[:120]), resp.status_code)
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return resp.text

    def request(self, method, path, params=None, json_body=None, timeout=None, quick=False):
        resp = self._send(method, path, params=params, json_body=json_body, timeout=timeout, quick=quick)
        if resp.status_code == 401 and self._reauth():
            resp = self._send(method, path, params=params, json_body=json_body, timeout=timeout, quick=quick)
        return self._parse(resp)

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.request("POST", path, json_body=body if body is not None else {}, **kw)

    def patch(self, path, body, **kw):
        return self.request("PATCH", path, json_body=body, **kw)

    def stream(self, path, headers=None):
        """Authenticated streaming GET for downloads; caller closes the response."""
        resp = self._send("GET", path, headers=headers, stream=True, timeout=(CONNECT_TIMEOUT, 30))
        if resp.status_code == 401 and self._reauth():
            resp.close()
            resp = self._send("GET", path, headers=headers, stream=True, timeout=(CONNECT_TIMEOUT, 30))
        return resp

    # ---------------------------------------------------------------- server
    def ping(self):
        resp = self._send("GET", "/ping", auth=False, timeout=(CONNECT_TIMEOUT, 8))
        return resp.status_code == 200

    def test(self):
        """Returns (ok, message). Verifies reachability and credentials."""
        if not self.base:
            return False, "Server URL is not set"
        try:
            if not self.ping():
                return False, "Server answered, but /ping failed"
            me = self.get("/api/me", timeout=(CONNECT_TIMEOUT, 10))
        except ABSError as exc:
            return False, str(exc)
        name = (me or {}).get("username", "?")
        kind = (me or {}).get("type", "")
        return True, "%s (%s)" % (name, kind)

    def me(self):
        return self.get("/api/me")

    def libraries(self):
        return (self.get("/api/libraries") or {}).get("libraries", [])

    def library(self, library_id):
        return (self.get("/api/libraries/%s" % library_id) or {}).get("library") or {}

    def library_items(self, library_id, page=0, limit=100, sort="media.metadata.title", desc=False):
        return self.get("/api/libraries/%s/items" % library_id, params={
            "limit": limit, "page": page, "sort": sort, "desc": 1 if desc else 0,
            "minified": 1, "collapseseries": 0})

    def library_search(self, library_id, query, limit=30):
        return self.get("/api/libraries/%s/search" % library_id, params={"q": query, "limit": limit}) or {}

    def recent_episodes(self, library_id, limit=60, page=0):
        return (self.get("/api/libraries/%s/recent-episodes" % library_id,
                         params={"limit": limit, "page": page}) or {}).get("episodes", [])

    def in_progress(self, limit=40):
        return (self.get("/api/me/items-in-progress", params={"limit": limit}) or {}).get("libraryItems", [])

    def item(self, item_id, expanded=True):
        return self.get("/api/items/%s" % item_id, params={"expanded": 1 if expanded else 0})

    # -------------------------------------------------------------- progress
    def progress_map(self):
        """{key: progress} for the whole user, key = itemId or itemId:episodeId."""
        out = {}
        for mp in (self.me() or {}).get("mediaProgress", []) or []:
            key = mp.get("libraryItemId", "")
            if mp.get("episodeId"):
                key += ":" + mp["episodeId"]
            out[key] = mp
        return out

    def get_progress(self, item_id, episode_id=None, quick=False):
        path = "/api/me/progress/%s" % item_id + ("/%s" % episode_id if episode_id else "")
        try:
            return self.get(path, quick=quick)
        except ABSNotFound:
            return None

    def set_finished(self, item_id, episode_id, finished):
        path = "/api/me/progress/%s" % item_id + ("/%s" % episode_id if episode_id else "")
        body = {"isFinished": bool(finished)}
        if not finished:
            body.update({"currentTime": 0, "progress": 0})
        self.patch(path, body)

    # -------------------------------------------------------------- sessions
    def start_session(self, item_id, episode_id=None):
        path = "/api/items/%s/play" % item_id + ("/%s" % episode_id if episode_id else "")
        return self.post(path, {
            "deviceInfo": utils.device_info(),
            "forceDirectPlay": True,
            "forceTranscode": False,
            "supportedMimeTypes": MIME_TYPES,
            "mediaPlayer": "Kodi",
        })

    def sync_session(self, session_id, current_time, time_listened, duration):
        self.post("/api/session/%s/sync" % session_id, {
            "currentTime": current_time, "timeListened": time_listened, "duration": duration,
        }, timeout=SYNC_TIMEOUT)

    def close_session(self, session_id, current_time, time_listened, duration):
        self.post("/api/session/%s/close" % session_id, {
            "currentTime": current_time, "timeListened": time_listened, "duration": duration,
        }, timeout=SYNC_TIMEOUT)

    def sync_local_session(self, payload):
        self.post("/api/session/local", payload, timeout=SYNC_TIMEOUT)

    def track_url(self, session_id, index):
        return "%s/public/session/%s/track/%s" % (self.base, quote(session_id, safe=""), index)

    # --------------------------------------------------------------- artwork
    def cover_url(self, item_id, width=600):
        return "%s/api/items/%s/cover?width=%d&format=jpeg" % (self.base, item_id, width)

    # --------------------------------------------------------------- podcasts
    def search_podcasts(self, term):
        return self.get("/api/search/podcasts", params={"term": term}) or []

    def podcast_feed(self, rss_url):
        return (self.post("/api/podcasts/feed", {"rssFeed": rss_url}, timeout=(CONNECT_TIMEOUT, 60)) or {}).get("podcast") or {}

    def create_podcast(self, payload):
        return self.post("/api/podcasts", payload, timeout=(CONNECT_TIMEOUT, 60))

    def check_new_episodes(self, item_id, limit=3):
        return (self.get("/api/podcasts/%s/checknew" % item_id, params={"limit": limit},
                         timeout=(CONNECT_TIMEOUT, 90)) or {}).get("episodes", [])

    def download_episodes_on_server(self, item_id, episodes):
        self.post("/api/podcasts/%s/download-episodes" % item_id, episodes)
