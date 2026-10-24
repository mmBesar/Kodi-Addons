# SPDX-License-Identifier: GPL-3.0-or-later
"""End-to-end: plugin resolves playback, the service player syncs it."""
import json

import xbmc
import xbmcplugin

from conftest import SETTINGS, api, downloads, playback, service_core, store, sync, utils


class FakePlayer:
    """Drives an ABSPlayer the way Kodi would."""

    def __init__(self, env):
        self.env = env
        self.player = service_core.ABSPlayer()
        self.url = None
        self.t = 0.0
        self.player.getPlayingFile = lambda: self.url
        self.player.getTime = lambda: self.t
        self.player.isPlaying = lambda: True
        self.seeks = []
        self.player.seekTime = lambda v: self.seeks.append(v)

    def start(self, url, t=0.0):
        self.url, self.t = url, t
        self.player.onAVStarted()

    def listen(self, seconds, step=1):
        for _ in range(int(seconds / step)):
            self.env.clock.advance(step)
            self.t += step
            self.player.tick()


def resolve(env, item, ep=None, start=None, monkeypatch=None):
    calls = []
    orig = xbmcplugin.setResolvedUrl
    xbmcplugin.setResolvedUrl = lambda h, ok, li: calls.append(ok)
    try:
        playback.resolve(1, item, ep, start)
    finally:
        xbmcplugin.setResolvedUrl = orig
    return calls


def test_streaming_session_syncs_progress_and_closes(env):
    env.state.progress["li_pod1:ep_1"] = {"libraryItemId": "li_pod1", "episodeId": "ep_1",
                                          "currentTime": 600.0, "duration": 1800, "isFinished": False,
                                          "lastUpdate": 1}
    assert resolve(env, "li_pod1", "ep_1") == [True]
    ctx = json.loads(env.window.getProperty(utils.CTX_PROPERTY))
    assert ctx["mode"] == "session"
    assert ctx["start_position"] == 597.0  # 600s minus 3s rewind
    url = ctx["tracks"][0]["url"]
    assert "/public/session/" in url and "token" not in url and "key-123" not in url

    fp = FakePlayer(env)
    fp.start(url, t=597.0)
    assert fp.player.ctx is not None and fp.seeks == []  # Kodi honoured StartOffset
    fp.listen(65)
    syncs = env.state.syncs
    assert len(syncs) == 2  # every 30s
    assert abs(syncs[0][1]["timeListened"] - 30) < 2
    assert abs(syncs[0][1]["currentTime"] - (597 + 30)) < 2

    fp.player.onPlayBackStopped()
    assert len(env.state.closes) == 1
    sid, body = env.state.closes[0]
    assert abs(body["currentTime"] - (597 + 65)) < 2
    assert abs(env.state.progress["li_pod1:ep_1"]["currentTime"] - 662) < 2
    assert fp.player.ctx is None


def test_resume_corrective_seek_when_kodi_ignores_start_offset(env):
    env.state.progress["li_pod1:ep_2"] = {"libraryItemId": "li_pod1", "episodeId": "ep_2",
                                          "currentTime": 300.0, "duration": 900, "isFinished": False,
                                          "lastUpdate": 1}
    resolve(env, "li_pod1", "ep_2")
    ctx = json.loads(env.window.getProperty(utils.CTX_PROPERTY))
    fp = FakePlayer(env)
    fp.start(ctx["tracks"][0]["url"], t=0.0)  # Kodi started at 0 -> we must seek
    assert fp.seeks == [297.0]


def test_pause_and_seek_sync_immediately_and_pause_time_is_not_counted(env):
    resolve(env, "li_pod1", "ep_2")
    ctx = json.loads(env.window.getProperty(utils.CTX_PROPERTY))
    fp = FakePlayer(env)
    fp.start(ctx["tracks"][0]["url"])
    fp.listen(10)
    fp.t = 10.0
    fp.player.onPlayBackPaused()
    assert len(env.state.syncs) == 1
    paused_sync = env.state.syncs[0][1]
    assert abs(paused_sync["timeListened"] - 10) < 2 and abs(paused_sync["currentTime"] - 10) < 2
    env.clock.advance(600)  # ten minutes paused
    fp.player.tick()
    fp.player.onPlayBackResumed()
    fp.player.onPlayBackSeek(120000, 0)  # user jumps to 2:00
    assert abs(env.state.syncs[-1][1]["currentTime"] - 120) < 1
    assert env.state.syncs[-1][1]["timeListened"] < 2  # the pause was not "listening"


def test_natural_end_marks_episode_finished(env):
    resolve(env, "li_pod1", "ep_2")
    ctx = json.loads(env.window.getProperty(utils.CTX_PROPERTY))
    fp = FakePlayer(env)
    fp.start(ctx["tracks"][0]["url"])
    fp.listen(5)
    fp.player.onPlayBackEnded()
    assert env.state.progress["li_pod1:ep_2"]["isFinished"] is True


def test_multi_file_book_uses_absolute_position(env):
    env.state.progress["li_book1"] = {"libraryItemId": "li_book1", "episodeId": None, "currentTime": 4000.0,
                                      "duration": 7200, "isFinished": False, "lastUpdate": 1}
    added = []

    class PL:
        def clear(self):
            pass

        def add(self, url, li=None):
            added.append(url)

    orig_pl, orig_player = xbmc.PlayList, xbmc.Player
    played = []

    class P:
        def play(self, pl, startpos=0):
            played.append(startpos)

    xbmc.PlayList, xbmc.Player = lambda kind: PL(), P
    try:
        assert resolve(env, "li_book1") == [False]
    finally:
        xbmc.PlayList, xbmc.Player = orig_pl, orig_player
    assert len(added) == 2 and played == [1]  # starts on file 2
    ctx = json.loads(env.window.getProperty(utils.CTX_PROPERTY))
    assert abs(ctx["start_in_track"] - (3997 - 3600)) < 0.01

    fp = FakePlayer(env)
    fp.start(ctx["tracks"][1]["url"], t=ctx["start_in_track"])
    fp.listen(31)
    assert abs(env.state.syncs[-1][1]["currentTime"] - (3997 + 31)) < 2  # offset 3600 + position in file
    fp.player.onPlayBackStopped()
    assert len(env.state.closes) == 1


def test_playlist_advance_between_files_keeps_one_session(env):
    env.state.progress["li_book1"] = {"libraryItemId": "li_book1", "episodeId": None, "currentTime": 3590.0,
                                      "duration": 7200, "isFinished": False, "lastUpdate": 1}
    orig_pl, orig_player = xbmc.PlayList, xbmc.Player
    xbmc.PlayList = lambda kind: type("PL", (), {"clear": lambda s: None, "add": lambda s, u, li=None: None})()
    xbmc.Player = type("P", (), {"play": lambda s, pl, startpos=0: None})
    try:
        resolve(env, "li_book1")
    finally:
        xbmc.PlayList, xbmc.Player = orig_pl, orig_player
    ctx = json.loads(env.window.getProperty(utils.CTX_PROPERTY))
    assert ctx["start_track"] == 0
    fp = FakePlayer(env)
    fp.start(ctx["tracks"][0]["url"], t=ctx["start_in_track"])
    fp.listen(10)
    fp.player.onPlayBackEnded()  # file 1 finished; file 2 is about to start
    assert fp.player.ctx is not None and not env.state.closes
    fp.start(ctx["tracks"][1]["url"], t=0.0)  # Kodi starts the next file
    assert fp.player.track_idx == 1 and fp.player.pending_finish is None
    fp.listen(31)
    assert env.state.syncs[-1][1]["currentTime"] > 3600  # absolute, not per-file
    fp.player.onPlayBackStopped()
    assert len(env.state.closes) == 1


def test_playlist_end_without_next_file_closes_after_grace(env):
    resolve(env, "li_book1", start=3500.0)
    ctx = json.loads(env.window.getProperty(utils.CTX_PROPERTY))
    fp = FakePlayer(env)
    fp.start(ctx["tracks"][0]["url"], t=ctx["start_in_track"])
    fp.player.onPlayBackEnded()
    env.clock.advance(service_core.PENDING_FINISH_GRACE + 1)
    fp.player.tick()
    assert fp.player.ctx is None and len(env.state.closes) == 1


def test_server_forgets_session_then_progress_continues_as_local_session(env):
    resolve(env, "li_pod1", "ep_1")
    ctx = json.loads(env.window.getProperty(utils.CTX_PROPERTY))
    fp = FakePlayer(env)
    fp.start(ctx["tracks"][0]["url"])
    env.state.sessions.clear()  # server restarted
    fp.listen(31)
    assert env.state.local_sessions, "fell back to a local session"
    assert env.state.local_sessions[-1]["id"] == ctx["session_id"]
    assert env.state.local_sessions[-1]["playMethod"] == 3


def test_offline_stop_queues_session_and_flush_delivers_it(env):
    resolve(env, "li_pod1", "ep_1")
    ctx = json.loads(env.window.getProperty(utils.CTX_PROPERTY))
    fp = FakePlayer(env)
    fp.start(ctx["tracks"][0]["url"])
    fp.listen(20)
    env.state.offline = True  # wifi drops mid-listen
    fp.listen(40)
    fp.player.onPlayBackStopped()
    assert store.pending_count() == 1
    assert store.get_progress("li_pod1", "ep_1")["position"] > 55  # local mirror survives

    env.state.offline = False
    sent, left = sync.flush_queue()
    assert (sent, left) == (1, 0)
    delivered = env.state.local_sessions[-1]
    assert delivered["libraryItemId"] == "li_pod1" and delivered["episodeId"] == "ep_1"
    assert delivered["timeListening"] >= 55 and delivered["currentTime"] > 55
    assert env.state.progress["li_pod1:ep_1"]["currentTime"] > 55


def test_flush_keeps_queue_while_offline(env):
    store.queue_session(sync.build_local_session(
        {"session_id": "s1", "item_id": "li_pod1", "episode_id": "ep_1", "media_type": "podcast",
         "duration": 1800}, 100, 50, utils.now_ms() - 1000))
    env.state.offline = True
    assert sync.flush_queue() == (0, 1)
    env.state.offline = False
    assert sync.flush_queue() == (1, 0)


def test_last_write_wins_between_devices(env):
    """Phone listened more recently on the server than the offline Kodi session."""
    old = utils.now_ms() - 3600_000
    env.state.progress["li_pod1:ep_1"] = {"libraryItemId": "li_pod1", "episodeId": "ep_1", "currentTime": 1500,
                                          "duration": 1800, "isFinished": False, "lastUpdate": utils.now_ms()}
    payload = sync.build_local_session(
        {"session_id": "s2", "item_id": "li_pod1", "episode_id": "ep_1", "media_type": "podcast",
         "duration": 1800}, 200, 60, old - 100000, updated_at_ms=old)
    assert sync.try_send(api.ABSClient(), payload)
    assert env.state.progress["li_pod1:ep_1"]["currentTime"] == 1500  # newer server progress kept


def test_shutdown_during_playback_queues_instead_of_blocking(env):
    resolve(env, "li_pod1", "ep_1")
    ctx = json.loads(env.window.getProperty(utils.CTX_PROPERTY))
    fp = FakePlayer(env)
    fp.start(ctx["tracks"][0]["url"])
    fp.listen(15)
    fp.player.shutdown()
    assert store.pending_count() == 1 and not env.state.closes


def test_unrelated_playback_is_ignored(env):
    fp = FakePlayer(env)
    fp.start("/home/user/music/song.mp3")
    assert fp.player.ctx is None
    fp.listen(60)
    assert env.state.syncs == []


def test_resume_dialog_choice_start_over(env, monkeypatch):
    SETTINGS["resume_mode"] = 1
    env.state.progress["li_pod1:ep_1"] = {"libraryItemId": "li_pod1", "episodeId": "ep_1", "currentTime": 900.0,
                                          "duration": 1800, "isFinished": False, "lastUpdate": 1}
    monkeypatch.setattr(playback.xbmcgui.Dialog, "contextmenu", lambda self, items: 1)
    resolve(env, "li_pod1", "ep_1")
    assert json.loads(env.window.getProperty(utils.CTX_PROPERTY))["start_position"] == 0.0


def test_finished_episode_restarts_from_zero(env):
    env.state.progress["li_pod1:ep_2"] = {"libraryItemId": "li_pod1", "episodeId": "ep_2", "currentTime": 890.0,
                                          "duration": 900, "isFinished": True, "lastUpdate": 1}
    resolve(env, "li_pod1", "ep_2")
    assert json.loads(env.window.getProperty(utils.CTX_PROPERTY))["start_position"] == 0.0
