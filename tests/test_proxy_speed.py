# SPDX-License-Identifier: GPL-3.0-or-later
"""Local proxy (HTTPS workaround) and playback speed."""
import json

import pytest
import requests
import xbmc
import xbmcgui
import xbmcplugin

import mock_abs
from conftest import SETTINGS, api, playback, service_core, store, utils
from resources.lib import actions, proxy, speed
from test_sync import FakePlayer


@pytest.fixture
def px(env):
    SETTINGS["use_proxy"] = True
    srv = proxy.start()
    env.base = "http://127.0.0.1:%d" % srv.server_address[1]
    yield env
    proxy.stop(srv)


def session_url(env):
    c = api.ABSClient()
    sess = c.start_session("li_pod1", "ep_1")
    return sess, c.track_url(sess["id"], 1)


# ------------------------------------------------------------------ proxy
def test_proxy_listens_on_loopback_only_and_publishes_port(px):
    assert utils.home_window().getProperty(utils.PROXY_PROPERTY) == px.base.rsplit(":", 1)[1]
    assert px.base.startswith("http://127.0.0.1:")


def test_stream_urls_use_proxy_and_cover_urls_too(px):
    sess, url = session_url(px)
    assert url == "%s/t/%s/1" % (px.base, sess["id"])
    assert api.ABSClient().cover_url("li_pod1", 300) == "%s/c/li_pod1?w=300" % px.base
    assert "/api/items/" in api.ABSClient().cover_url("li_pod1", direct=True)


def test_proxy_off_gives_direct_urls(px):
    SETTINGS["use_proxy"] = False
    _s, url = session_url(px)
    assert url.startswith(px.state.url + "/public/session/")


def test_full_body_and_range_pass_through(px):
    _s, url = session_url(px)
    full = requests.get(url, timeout=10)
    assert full.status_code == 200 and full.content == mock_abs.AUDIO
    assert full.headers["Accept-Ranges"] == "bytes" and full.headers["Content-Type"] == "audio/mpeg"
    part = requests.get(url, headers={"Range": "bytes=1000-1999"}, timeout=10)  # what seeking does
    assert part.status_code == 206 and part.content == mock_abs.AUDIO[1000:2000]
    assert part.headers["Content-Range"] == "bytes 1000-1999/%d" % len(mock_abs.AUDIO)
    tail = requests.get(url, headers={"Range": "bytes=%d-" % (len(mock_abs.AUDIO) - 10)}, timeout=10)
    assert tail.content == mock_abs.AUDIO[-10:]


def test_head_request_and_keepalive_reuse(px):
    _s, url = session_url(px)
    head = requests.head(url, timeout=10)
    assert head.status_code == 200 and int(head.headers["Content-Length"]) == len(mock_abs.AUDIO) and not head.content
    with requests.Session() as s:  # several requests on one connection, like Kodi
        for start in (0, 5000, 20000):
            r = s.get(url, headers={"Range": "bytes=%d-%d" % (start, start + 99)}, timeout=10)
            assert r.content == mock_abs.AUDIO[start:start + 100]


def test_no_credentials_ever_reach_the_public_route(px):
    _s, url = session_url(px)
    requests.get(url, timeout=10)
    assert px.state.public_auth and all(a is None for a in px.state.public_auth)


def test_only_the_two_known_routes_are_served(px):
    for path in ("/api/me", "/login", "/t/../api/me", "/t/short/1", "/c/x", "/c/../../etc/passwd", "/"):
        assert requests.get(px.base + path, timeout=10).status_code == 404, path
    assert not any(r[1] == "/api/me" and r[0] == "GET" for r in px.state.requests[-3:])


def test_unknown_session_is_404_without_hanging(px):
    r = requests.get("%s/t/%s/1" % (px.base, "00000000-0000-0000-0000-000000000000"), timeout=10)
    assert r.status_code == 404 and r.content == b""


def test_upstream_down_gives_502_not_a_hang(px):
    _s, url = session_url(px)
    px.state.offline = True
    assert requests.get(url, timeout=15).status_code == 502


def test_cover_is_cached_and_survives_offline(px):
    url = "%s/c/li_pod1?w=300" % px.base
    first = requests.get(url, timeout=10)
    assert first.status_code == 200 and first.headers["Content-Type"] == "image/jpeg" and first.content.startswith(b"\xff\xd8")
    px.state.offline = True
    again = requests.get(url, timeout=15)
    assert again.status_code == 200 and again.content == first.content
    assert requests.get("%s/c/li_other_item" % px.base, timeout=15).status_code == 404  # never cached


def test_cover_width_is_clamped(px):
    assert requests.get("%s/c/li_pod1?w=999999" % px.base, timeout=10).status_code == 200
    assert requests.get("%s/c/li_pod1?w=abc" % px.base, timeout=10).status_code == 200


def test_playback_context_uses_proxy_and_streams_bytes(px):
    calls = []
    orig = xbmcplugin.setResolvedUrl
    xbmcplugin.setResolvedUrl = lambda h, ok, li: calls.append(ok)
    try:
        playback.resolve(1, "li_pod1", "ep_1", None)
    finally:
        xbmcplugin.setResolvedUrl = orig
    ctx = json.loads(px.window.getProperty(utils.CTX_PROPERTY))
    url = ctx["tracks"][0]["url"]
    assert url.startswith(px.base + "/t/") and requests.get(url, timeout=10).content == mock_abs.AUDIO
    fp = FakePlayer(px)
    fp.start(url)
    assert fp.player.ctx is not None  # the service still recognises the proxied URL


# ------------------------------------------------------------------ speed
class FakeKodi:
    """Stands in for Kodi's JSON-RPC: VideoPlayer ignores tempo >= maxtempo + 0.05."""

    def __init__(self, cap=1.5):
        self.tempo, self.cap, self.calls, self.player, self.paused = 1.0, cap, [], True, False

    def __call__(self, raw):
        req = json.loads(raw)
        self.calls.append((req["method"], req["params"]))
        if req["method"] == "Player.GetActivePlayers":
            return json.dumps({"result": [{"playerid": 1, "type": "video"}] if self.player else []})
        if self.paused:
            return json.dumps({"error": {"code": -32100, "message": "Failed to execute method."}})
        wanted = req["params"]["tempo"]
        if wanted < self.cap + 0.05:
            self.tempo = wanted
        return json.dumps({"result": {"tempo": self.tempo}})

    def tempo_requests(self):
        return [p["tempo"] for m, p in self.calls if m == "Player.SetTempo"]


@pytest.fixture
def kodi(monkeypatch):
    k = FakeKodi()
    monkeypatch.setattr(xbmc, "executeJSONRPC", k)
    return k


def test_apply_reports_what_kodi_holds(env, kodi):
    assert speed.apply(1.2) == 1.2
    assert speed.apply(1.8) == 1.2, "a capped request leaves the old tempo in place: that is how it is detected"
    kodi.cap = 2.0
    assert speed.apply(1.8) == 1.8 and speed.apply(2.0) == 2.0


def test_apply_returns_none_when_not_possible_yet(env, kodi):
    kodi.player = False
    assert speed.apply(1.5) is None
    kodi.player, kodi.paused = True, True
    assert speed.apply(1.5) is None


def test_playback_item_is_video_tagged_only_when_speed_is_enabled(env, monkeypatch):
    captured = []
    monkeypatch.setattr(xbmcplugin, "setResolvedUrl", lambda h, ok, li: captured.append(li))
    playback.resolve(1, "li_pod1", "ep_1", None)
    li = captured[-1]
    assert li.tag.data.get("Title") == "Episode One" and li.vtag.data == {}  # music engine
    SETTINGS["speed_engine"] = True
    playback.resolve(1, "li_pod1", "ep_1", None)
    li = captured[-1]
    assert li.vtag.data["Title"] == "Episode One" and li.tag.data == {}  # VideoPlayer is chosen


def play(env, ep="ep_1"):
    captured = []
    orig = xbmcplugin.setResolvedUrl
    xbmcplugin.setResolvedUrl = lambda h, ok, li: captured.append(ok)
    try:
        playback.resolve(1, "li_pod1", ep, None)
    finally:
        xbmcplugin.setResolvedUrl = orig
    ctx = json.loads(env.window.getProperty(utils.CTX_PROPERTY))
    fp = FakePlayer(env)
    fp.start(ctx["tracks"][0]["url"])
    return fp


def test_default_speed_is_applied_after_start(env, kodi):
    SETTINGS.update({"speed_engine": True, "default_speed": 120})
    fp = play(env)
    assert env.window.getProperty(speed.NOW_PROPERTY) == "li_pod1"
    fp.listen(3)
    assert kodi.tempo == 1.2 and kodi.tempo_requests() == [1.2]  # applied once, then stops retrying
    fp.player.onPlayBackStopped()
    assert env.window.getProperty(speed.NOW_PROPERTY) == ""


def test_speed_is_remembered_per_show(env, kodi):
    SETTINGS.update({"speed_engine": True, "default_speed": 100})
    store.set_speed("li_pod1", 1.5)
    fp = play(env)
    fp.listen(2)
    assert kodi.tempo == 1.5


def test_engine_off_never_touches_tempo(env, kodi):
    SETTINGS.update({"speed_engine": False, "default_speed": 150})
    fp = play(env)
    fp.listen(5)
    assert kodi.tempo_requests() == []


def test_capped_speed_tells_the_user_how_to_raise_it(env, kodi):
    SETTINGS.update({"speed_engine": True, "default_speed": 180})
    fp = play(env)
    fp.listen(6)
    msgs = [m for m, err in env.notes if err]
    assert any("capped at 1.00x" in m or "capped" in m for m in msgs)
    assert len(kodi.tempo_requests()) == 3  # gave up after three tries, not hammering


def test_high_speed_works_once_maxtempo_is_raised(env, kodi):
    kodi.cap = 2.0
    SETTINGS.update({"speed_engine": True, "default_speed": 200})
    fp = play(env)
    fp.listen(3)
    assert kodi.tempo == 2.0 and not [1 for m, e in env.notes if e]


def test_tempo_waits_while_paused_then_applies(env, kodi):
    SETTINGS.update({"speed_engine": True, "default_speed": 150})
    kodi.paused = True
    fp = play(env)
    fp.player.paused = True
    fp.listen(5)
    assert kodi.tempo_requests() == []  # service does not even try while paused
    fp.player.paused = False
    kodi.paused = False
    fp.listen(2)
    assert kodi.tempo == 1.5


def test_speed_picker_during_playback_applies_and_remembers(env, kodi, monkeypatch):
    SETTINGS.update({"speed_engine": True, "default_speed": 100})
    fp = play(env)
    fp.listen(2)
    monkeypatch.setattr(xbmcgui.Dialog, "select", lambda self, title, labels: speed.PRESETS.index(1.5))
    actions.choose_speed()
    assert store.get_speed("li_pod1") == 1.5
    fp.listen(2)
    assert kodi.tempo == 1.5 and any("1.50x" in m for m, _e in env.notes)


def test_speed_picker_without_playback_sets_the_default(env, monkeypatch):
    SETTINGS.update({"speed_engine": True, "default_speed": 100})
    monkeypatch.setattr(xbmcgui.Dialog, "select", lambda self, title, labels: speed.PRESETS.index(1.2))
    actions.choose_speed()
    assert SETTINGS["default_speed"] == "120"


def test_speed_picker_refuses_when_feature_is_off(env, monkeypatch):
    SETTINGS["speed_engine"] = False
    called = []
    monkeypatch.setattr(xbmcgui.Dialog, "select", lambda *a: called.append(1) or 0)
    actions.choose_speed()
    assert not called and env.notes[-1][1] is True


def test_presets_cover_requested_speeds():
    for wanted in (1.2, 1.5, 1.8, 2.0):
        assert wanted in speed.PRESETS
