# SPDX-License-Identifier: GPL-3.0-or-later
"""Side-effect actions invoked via RunPlugin (no directory listing)."""
import xbmc
import xbmcgui

from . import api, downloads, speed, store, sync, utils
from .strings import S


def refresh():
    xbmc.executebuiltin("Container.Refresh")


def mark(client, item_id, episode_id, finished):
    client.set_finished(item_id, episode_id, finished)
    store.save_progress(item_id, episode_id, 0, 0, finished=finished)
    if finished and episode_id and utils.s_bool("delete_played", True):
        downloads.remove(store.make_key(item_id, episode_id))
    utils.notify(utils.t(S.D_MARKED), time_ms=1500)
    refresh()


def dl_add(item_id, episode_id):
    try:
        downloads.root_dir()
    except downloads.DownloadError as exc:
        return utils.notify(str(exc), error=True)
    queued = downloads.enqueue(item_id, episode_id)
    utils.notify(utils.t(S.D_DL_QUEUED) % (1 if queued else 0), time_ms=2000)
    refresh()


def dl_remove(key):
    if xbmcgui.Dialog().yesno(utils.ADDON_NAME, utils.t(S.D_DL_CONFIRM)):
        downloads.remove(key)
        utils.notify(utils.t(S.D_DL_REMOVED), time_ms=1500)
        refresh()


def dl_remove_group(group):
    if xbmcgui.Dialog().yesno(utils.ADDON_NAME, utils.t(S.D_DL_ALL_CONFIRM)):
        downloads.remove_group(group)
        utils.notify(utils.t(S.D_DL_REMOVED), time_ms=1500)
        refresh()


def auto_toggle(client, item_id):
    if store.get_auto(item_id):
        store.clear_auto(item_id)
        return utils.notify(utils.t(S.D_AUTO_OFF), time_ms=2000)
    item = client.item(item_id)
    title = ((item.get("media") or {}).get("metadata") or {}).get("title", "")
    default = max(1, utils.s_int("auto_keep", 3))
    answer = xbmcgui.Dialog().numeric(0, utils.t(S.D_AUTO_ASK), str(default))
    keep = int(answer) if str(answer).isdigit() and int(answer) > 0 else default
    store.set_auto(item_id, title, keep)
    utils.notify(utils.t(S.D_AUTO_ON) % keep, time_ms=2500)
    xbmc.executebuiltin("NotifyAll(%s,autosync,{})" % utils.ADDON_ID)


def download_all_unplayed(client, item_id):
    item = client.item(item_id)
    eps = downloads.unplayed_episodes(item, client.progress_map())
    queued = sum(1 if downloads.enqueue(item_id, e["id"]) else 0 for e in eps)
    utils.notify(utils.t(S.D_DL_QUEUED) % queued, time_ms=2500)
    refresh()


def check_new(client, item_id):
    try:
        found = client.check_new_episodes(item_id)
    except api.ABSForbidden:
        return utils.notify(utils.t(S.D_FORBIDDEN), error=True)
    utils.notify(utils.t(S.D_NEW_FOUND) % len(found) if found else utils.t(S.D_NO_NEW), time_ms=2500)
    refresh()


def find_new(client, item_id):
    item = client.item(item_id)
    meta = (item.get("media") or {}).get("metadata") or {}
    existing = (item.get("media") or {}).get("episodes", [])
    seen_urls = {(e.get("enclosure") or {}).get("url") for e in existing}
    seen_guids = {e.get("guid") for e in existing if e.get("guid")}
    if not meta.get("feedUrl"):
        return utils.notify(utils.t(S.D_NO_NEW), time_ms=2000)
    try:
        feed = client.podcast_feed(meta["feedUrl"])
    except api.ABSForbidden:
        return utils.notify(utils.t(S.D_FORBIDDEN), error=True)
    fresh = [e for e in feed.get("episodes", [])
             if (e.get("enclosure") or {}).get("url") not in seen_urls
             and not (e.get("guid") and e["guid"] in seen_guids)]
    if not fresh:
        return utils.notify(utils.t(S.D_NO_NEW), time_ms=2500)
    picked = xbmcgui.Dialog().multiselect(utils.t(S.D_PICK_EPISODES), [e.get("title", "?") for e in fresh])
    if not picked:
        return
    try:
        client.download_episodes_on_server(item_id, [fresh[i] for i in picked])
    except api.ABSForbidden:
        return utils.notify(utils.t(S.D_FORBIDDEN), error=True)
    utils.notify(utils.t(S.D_SERVER_DL_QUEUED) % len(picked), time_ms=3000)


def podcast_menu(client, item_id):
    auto = store.get_auto(item_id)
    options = [
        (utils.t(S.C_AUTO_OFF if auto else S.C_AUTO_ON), lambda: auto_toggle(client, item_id)),
        (utils.t(S.C_DOWNLOAD_ALL_UNPLAYED), lambda: download_all_unplayed(client, item_id)),
        (utils.t(S.C_CHECK_NEW), lambda: check_new(client, item_id)),
        (utils.t(S.C_FIND_NEW), lambda: find_new(client, item_id)),
    ]
    choice = xbmcgui.Dialog().select(utils.t(S.M_PODCAST_OPTIONS), [o[0] for o in options])
    if choice >= 0:
        options[choice][1]()


def add_podcast(client):
    libs = [l for l in client.libraries() if l.get("mediaType") == "podcast"]
    if not libs:
        return utils.notify(utils.t(S.D_NO_PODCAST_LIB), error=True)
    term = xbmcgui.Dialog().input(utils.t(S.D_SEARCH_PODCASTS))
    if not term:
        return
    results = client.search_podcasts(term)
    if not results:
        return utils.notify(utils.t(S.D_NO_RESULTS), time_ms=2000)
    labels = ["%s - %s" % (r.get("title", "?"), r.get("artistName", "")) for r in results]
    pick = xbmcgui.Dialog().select(utils.t(S.D_PICK_PODCAST), labels)
    if pick < 0:
        return
    chosen = results[pick]
    lib = libs[0]
    if len(libs) > 1:
        idx = xbmcgui.Dialog().select(utils.t(S.D_PICK_LIBRARY), [l.get("name", "?") for l in libs])
        if idx < 0:
            return
        lib = libs[idx]
    folders = client.library(lib["id"]).get("folders") or lib.get("folders") or []
    if not folders:
        return utils.notify(utils.t(S.D_NO_PODCAST_LIB), error=True)
    folder = folders[0]
    payload = {
        "path": folder["fullPath"].rstrip("/") + "/" + utils.safe_name(chosen.get("title", "podcast")),
        "folderId": folder["id"],
        "libraryId": lib["id"],
        "media": {"metadata": {
            "title": chosen.get("title"), "author": chosen.get("artistName"),
            "description": chosen.get("description"), "genres": chosen.get("genres") or [],
            "feedUrl": chosen.get("feedUrl"), "imageUrl": chosen.get("cover"),
            "itunesPageUrl": chosen.get("pageUrl"), "itunesId": chosen.get("id"),
            "itunesArtistId": chosen.get("artistId"), "explicit": bool(chosen.get("explicit")),
        }, "autoDownloadEpisodes": False},
    }
    try:
        created = client.create_podcast(payload)
    except api.ABSForbidden:
        return utils.notify(utils.t(S.D_FORBIDDEN), error=True)
    except api.ABSError as exc:
        if exc.status == 400 and "exist" in str(exc).lower():
            return utils.notify(utils.t(S.D_ALREADY_EXISTS), error=True)
        raise
    utils.notify(utils.t(S.D_PODCAST_ADDED), time_ms=2500)
    if created and created.get("id"):
        find_new(client, created["id"])


def sync_now():
    client = api.ABSClient()
    if not client.configured():
        return utils.notify(utils.t(S.D_SETUP), error=True)
    sent, left = sync.flush_queue(client)
    if sent:
        utils.notify(utils.t(S.D_SYNCED) % sent, time_ms=2500)
    elif left:
        utils.notify(utils.t(S.D_SYNC_PENDING) % left, error=True)
    else:
        utils.notify(utils.t(S.D_NOTHING_TO_SYNC), time_ms=2000)
    xbmc.executebuiltin("NotifyAll(%s,autosync,{})" % utils.ADDON_ID)


def test_connection():
    client = api.ABSClient()
    ok, message = client.test()
    if ok:
        utils.notify(utils.t(S.D_TEST_OK) % message, time_ms=3500)
    else:
        xbmcgui.Dialog().ok(utils.ADDON_NAME, utils.t(S.D_TEST_FAIL) % message)


def choose_speed():
    """Pick a playback speed. During playback it applies live and is remembered
    for that show/book; otherwise it becomes the default for everything."""
    if not speed.enabled():
        return utils.notify(utils.t(S.D_SPEED_DISABLED), error=True)
    item_id = speed.current_item()
    current = speed.target_for(item_id) if item_id else speed.default_speed()
    labels = ["%gx%s" % (p, "   <" if abs(p - current) < 0.01 else "") for p in speed.PRESETS]
    choice = xbmcgui.Dialog().select(utils.t(S.D_SPEED_PICK), labels)
    if choice < 0:
        return
    value = speed.PRESETS[choice]
    if item_id:
        store.set_speed(item_id, value)
        utils.home_window().setProperty(speed.REQUEST_PROPERTY, "%.2f" % value)  # the service applies it
    else:
        utils.set_setting("default_speed", str(int(round(value * 100))))
        utils.notify(utils.t(S.D_SPEED_DEFAULT_SET) % value, time_ms=2000)
