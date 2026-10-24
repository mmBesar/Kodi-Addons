# SPDX-License-Identifier: GPL-3.0-or-later
from urllib.parse import parse_qs, urlparse

import pytest
import xbmcgui
import xbmcplugin

from conftest import SETTINGS, api, downloads, router, store, utils
from test_downloads import run_queue


@pytest.fixture
def ui(env, monkeypatch):
    rec = {"items": [], "ended": [], "content": None, "dialogs": []}
    monkeypatch.setattr(xbmcplugin, "addDirectoryItems", lambda h, items, n=0: rec["items"].extend(items))
    monkeypatch.setattr(xbmcplugin, "endOfDirectory", lambda h, succeeded=True, **kw: rec["ended"].append(succeeded))
    monkeypatch.setattr(xbmcplugin, "setContent", lambda h, c: rec.__setitem__("content", c))
    monkeypatch.setattr(xbmcplugin, "addSortMethod", lambda *a, **k: None)
    monkeypatch.setattr(xbmcplugin, "setPluginCategory", lambda *a, **k: None)
    monkeypatch.setattr(xbmcgui.Dialog, "notification", lambda self, *a, **k: rec["dialogs"].append(a))
    rec["env"] = env

    def go(query):
        rec["items"].clear()
        rec["ended"].clear()
        router.run(["plugin://x/", "7", query])
        return rec

    rec["go"] = go
    return rec


def labels(ui):
    return [li.getLabel() for _u, li, _f in ui["items"]]


def params(url):
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


def test_root_menu(ui):
    ui["go"]("")
    assert ui["ended"] == [True]
    assert labels(ui)[:3] == ["Continue listening", "Latest episodes", "Podcasts"]
    assert "Downloads" in labels(ui)


def test_podcasts_to_episodes_flow(ui):
    ui["go"]("?action=libraries&kind=podcast")  # single library -> straight to its items
    assert labels(ui) == ["Linux Show"] and ui["items"][0][2] is True
    ui["go"]("?" + urlparse(ui["items"][0][0]).query)
    labs = labels(ui)
    assert labs[0] == "Podcast options..."
    assert labs[1:] == ["Episode Two", "Episode One"]  # newest first
    play = params(ui["items"][1][0])
    assert play == {"action": "play", "item": "li_pod1", "ep": "ep_2"}
    assert ui["items"][1][2] is False  # playable leaf


def test_oldest_first_and_hide_played(ui):
    SETTINGS["newest_first"] = False
    ui["env"].state.progress["li_pod1:ep_1"] = {"libraryItemId": "li_pod1", "episodeId": "ep_1",
                                                "isFinished": True, "currentTime": 1800, "duration": 1800}
    assert labels(ui["go"]("?action=podcast&item=li_pod1"))[1:] == ["Episode One", "Episode Two"]
    SETTINGS["hide_played"] = True
    assert labels(ui["go"]("?action=podcast&item=li_pod1"))[1:] == ["Episode Two"]


def test_status_labels_show_played_left_and_downloaded(ui):
    ui["env"].state.progress["li_pod1:ep_1"] = {"libraryItemId": "li_pod1", "episodeId": "ep_1",
                                                "isFinished": False, "currentTime": 600, "duration": 1800}
    ui["env"].state.progress["li_pod1:ep_2"] = {"libraryItemId": "li_pod1", "episodeId": "ep_2",
                                                "isFinished": True, "currentTime": 900, "duration": 900}
    downloads.enqueue("li_pod1", "ep_1")
    run_queue()
    ui["go"]("?action=podcast&item=li_pod1")
    by = {li.getLabel(): li.getLabel2() for _u, li, _f in ui["items"]}
    assert by["Episode Two"] == "Played"
    assert by["Episode One"] == "20m left · Downloaded"


def test_latest_episodes(ui):
    ui["go"]("?action=latest")
    assert labels(ui) == ["Linux Show - Episode Two", "Linux Show - Episode One"]


def test_books_and_chapters(ui):
    ui["go"]("?action=libraries&kind=book")
    assert labels(ui) == ["Big Book"]
    ui["go"]("?action=chapters&item=li_book1")
    assert [l.split("  ")[0] for l in labels(ui)] == ["Part 1", "Part 2"]
    assert params(ui["items"][1][0])["start"] == "3600.00"


def test_search(ui):
    ui["go"]("?action=search&q=linux")
    assert "Linux Show" in labels(ui) and "Big Book" in labels(ui)


def test_downloads_view_grouping(ui):
    downloads.enqueue("li_pod1", "ep_1")
    downloads.enqueue("li_book1")
    run_queue()
    run_queue()
    ui["go"]("?action=downloads")
    assert sorted(labels(ui)) == ["Big Book", "Linux Show"]
    group = [u for u, li, f in ui["items"] if f][0]
    ui["go"]("?" + urlparse(group).query)
    assert labels(ui) == ["Episode One"]


def test_empty_downloads_does_not_crash(ui):
    ui["go"]("?action=downloads")
    assert ui["ended"] == [False]


def test_offline_browse_falls_back_to_downloads(ui):
    downloads.enqueue("li_pod1", "ep_1")
    run_queue()
    ui["env"].state.offline = True
    ui["go"]("?action=latest")
    assert labels(ui) == ["Linux Show"]  # the downloads listing, not an error screen
    assert ui["ended"] == [True]


def test_offline_without_downloads_fails_gracefully(ui):
    ui["env"].state.offline = True
    ui["go"]("?action=latest")
    assert ui["ended"] == [False] and ui["items"] == []


def test_unconfigured_prompts_instead_of_crashing(ui, monkeypatch):
    SETTINGS["server_url"] = ""
    asked = []
    monkeypatch.setattr(xbmcgui.Dialog, "yesno", lambda self, *a, **k: asked.append(a) or False)
    ui["go"]("?action=latest")
    assert asked and ui["ended"] == [False]


def test_bad_credentials_notify(ui):
    SETTINGS["api_key"] = "wrong"
    ui["go"]("?action=latest")
    assert ui["ended"] == [False]
    assert any("Sign-in failed" in n[0] for n in ui["env"].notes)


def test_mark_played_action(ui):
    router.run(["plugin://x/", "-1", "?action=mark&item=li_pod1&ep=ep_1&finished=1"])
    assert ui["env"].state.progress["li_pod1:ep_1"]["isFinished"] is True
    router.run(["plugin://x/", "-1", "?action=mark&item=li_pod1&ep=ep_1&finished=0"])
    assert ui["env"].state.progress["li_pod1:ep_1"]["isFinished"] is False


def test_page_size_paginates_episodes(ui):
    SETTINGS["page_size"] = 20
    state = ui["env"].state
    base = state.podcast_item["media"]["episodes"][0]
    state.podcast_item["media"]["episodes"] = [dict(base, id="ep_%d" % i, title="E%d" % i, publishedAt=1700000000000 + i)
                                               for i in range(45)]
    ui["go"]("?action=podcast&item=li_pod1")
    assert len(ui["items"]) == 1 + 20 + 1  # options + page + "next page"
    nxt = params(ui["items"][-1][0])
    assert nxt["page"] == "1"
    ui["go"]("?action=podcast&item=li_pod1&page=2")
    assert len(ui["items"]) == 5 and not any("Next page" in l for l in labels(ui))
