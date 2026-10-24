# SPDX-License-Identifier: GPL-3.0-or-later
import json
import os

import xbmcplugin

import mock_abs
from conftest import SETTINGS, api, downloads, playback, store, sync, utils
from test_sync import FakePlayer, resolve


class Monitor:
    def abortRequested(self):
        return False


def run_queue():
    results = []
    while store.queue_len():
        r = downloads.process_next(Monitor())
        results.append(r)
        if r != "done":
            break
    return results


def test_download_episode_writes_file_and_metadata(env):
    assert downloads.enqueue("li_pod1", "ep_1")
    assert not downloads.enqueue("li_pod1", "ep_1")  # no duplicates
    assert run_queue() == ["done"]
    rec = store.get_download("li_pod1:ep_1")
    assert rec["title"] == "Episode One" and rec["parent_title"] == "Linux Show"
    assert rec["description"] == "Hello & welcome"
    path = rec["tracks"][0]["path"]
    assert open(path, "rb").read() == mock_abs.AUDIO
    assert not os.path.exists(path + ".part")
    assert os.path.exists(os.path.join(os.path.dirname(path), "cover.jpg"))
    assert os.path.basename(path).startswith("2023-11-14 Episode One [")


def test_interrupted_download_resumes_with_range(env):
    downloads.enqueue("li_pod1", "ep_2")
    record, files = downloads.describe(api.ABSClient(), "li_pod1", "ep_2")
    folder, dests = downloads._target_paths(downloads.root_dir(), record, files)
    os.makedirs(folder, exist_ok=True)
    half = len(mock_abs.AUDIO) // 3
    open(dests[0] + ".part", "wb").write(mock_abs.AUDIO[:half])
    assert run_queue() == ["done"]
    assert open(dests[0], "rb").read() == mock_abs.AUDIO  # byte-identical after resume
    ranged = [r for r in env.state.requests if r[1].endswith("/file/222")]
    assert ranged  # fetched the remainder


def test_offline_pause_keeps_queue_and_part_file(env):
    downloads.enqueue("li_pod1", "ep_1")
    env.state.offline = True
    assert downloads.process_next(Monitor()) == "offline"
    assert store.queue_len() == 1
    env.state.offline = False
    assert run_queue() == ["done"]


def test_audiobook_download_has_all_tracks_with_offsets(env):
    downloads.enqueue("li_book1")
    assert run_queue() == ["done"]
    rec = store.get_download("li_book1")
    assert [t["offset"] for t in rec["tracks"]] == [0.0, 3600.0]
    assert all(os.path.exists(t["path"]) for t in rec["tracks"])
    assert rec["author"] == "Some Author"


def test_remove_cleans_files_and_empty_folder(env):
    downloads.enqueue("li_pod1", "ep_1")
    run_queue()
    folder = os.path.dirname(store.get_download("li_pod1:ep_1")["tracks"][0]["path"])
    assert downloads.remove("li_pod1:ep_1")
    assert not os.path.exists(folder) and store.get_download("li_pod1:ep_1") is None


def test_local_playback_offline_then_sync_on_reconnect(env):
    downloads.enqueue("li_pod1", "ep_1")
    run_queue()
    env.state.offline = True  # airplane mode: must still play instantly
    assert resolve(env, "li_pod1", "ep_1") == [True]
    ctx = json.loads(env.window.getProperty(utils.CTX_PROPERTY))
    assert ctx["mode"] == "local" and ctx["tracks"][0]["url"].endswith(".mp3")
    fp = FakePlayer(env)
    fp.start(ctx["tracks"][0]["url"])
    fp.listen(95)
    fp.player.onPlayBackStopped()
    assert store.pending_count() == 1
    assert 90 <= store.get_progress("li_pod1", "ep_1")["position"] <= 96

    env.state.offline = False
    assert sync.flush_queue() == (1, 0)
    assert env.state.progress["li_pod1:ep_1"]["currentTime"] >= 90

    # next play (still the downloaded copy) resumes where the offline session ended
    assert resolve(env, "li_pod1", "ep_1") == [True]
    resumed = json.loads(env.window.getProperty(utils.CTX_PROPERTY))["start_position"]
    assert 85 <= resumed <= 95


def test_local_playback_picks_up_progress_made_on_another_device(env):
    downloads.enqueue("li_pod1", "ep_1")
    run_queue()
    store.save_progress("li_pod1", "ep_1", 100, 1800, updated_at=utils.now_ms() - 600_000)
    env.state.progress["li_pod1:ep_1"] = {"libraryItemId": "li_pod1", "episodeId": "ep_1", "currentTime": 1200.0,
                                          "duration": 1800, "isFinished": False,
                                          "lastUpdate": utils.now_ms()}  # phone listened later
    resolve(env, "li_pod1", "ep_1")
    ctx = json.loads(env.window.getProperty(utils.CTX_PROPERTY))
    assert ctx["mode"] == "local" and abs(ctx["start_position"] - 1197) < 1


def test_deleted_file_falls_back_to_streaming(env):
    downloads.enqueue("li_pod1", "ep_1")
    run_queue()
    os.remove(store.get_download("li_pod1:ep_1")["tracks"][0]["path"])
    resolve(env, "li_pod1", "ep_1")
    assert json.loads(env.window.getProperty(utils.CTX_PROPERTY))["mode"] == "session"
    assert store.get_download("li_pod1:ep_1") is None


def test_prefer_local_off_streams_even_when_downloaded(env):
    downloads.enqueue("li_pod1", "ep_1")
    run_queue()
    SETTINGS["prefer_local"] = False
    resolve(env, "li_pod1", "ep_1")
    assert json.loads(env.window.getProperty(utils.CTX_PROPERTY))["mode"] == "session"


def test_streaming_falls_back_to_download_when_server_unreachable(env):
    downloads.enqueue("li_pod1", "ep_1")
    run_queue()
    SETTINGS["prefer_local"] = False
    env.state.offline = True
    assert resolve(env, "li_pod1", "ep_1") == [True]
    assert json.loads(env.window.getProperty(utils.CTX_PROPERTY))["mode"] == "local"


def test_unreachable_and_not_downloaded_fails_cleanly(env):
    env.state.offline = True
    assert resolve(env, "li_pod1", "ep_1") == [False]
    assert env.window.getProperty(utils.CTX_PROPERTY) == ""
    assert env.notes and env.notes[-1][1] is True


def test_auto_download_keeps_latest_unplayed_and_cleans_played(env):
    store.set_auto("li_pod1", "Linux Show", 1)
    env.state.progress["li_pod1:ep_2"] = {"libraryItemId": "li_pod1", "episodeId": "ep_2", "isFinished": True,
                                          "currentTime": 900, "duration": 900, "lastUpdate": 1}
    # newest (ep_2) is played -> the newest *unplayed* one (ep_1) is wanted
    assert downloads.autosync(api.ABSClient()) == 1
    assert store.queue_len() == 1 and store.next_queued()["episode_id"] == "ep_1"
    run_queue()
    assert store.get_download("li_pod1:ep_1")
    # once ep_1 is played on any device the local copy goes away
    env.state.progress["li_pod1:ep_1"] = {"libraryItemId": "li_pod1", "episodeId": "ep_1", "isFinished": True,
                                          "currentTime": 1800, "duration": 1800, "lastUpdate": 2}
    downloads.autosync(api.ABSClient())
    assert store.get_download("li_pod1:ep_1") is None


def test_cleanup_respects_setting_and_never_touches_books(env):
    downloads.enqueue("li_book1")
    downloads.enqueue("li_pod1", "ep_1")
    run_queue()
    run_queue()
    env.state.progress["li_pod1:ep_1"] = {"isFinished": True, "libraryItemId": "li_pod1", "episodeId": "ep_1"}
    env.state.progress["li_book1"] = {"isFinished": True, "libraryItemId": "li_book1", "episodeId": None}
    SETTINGS["delete_played"] = False
    assert downloads.cleanup_played(api.ABSClient()) == 0
    SETTINGS["delete_played"] = True
    assert downloads.cleanup_played(api.ABSClient()) == 1
    assert store.get_download("li_book1")


def test_download_path_must_be_local(env):
    SETTINGS["download_path"] = "smb://nas/share"
    try:
        downloads.root_dir()
        assert False, "should refuse remote paths"
    except downloads.DownloadError:
        pass
