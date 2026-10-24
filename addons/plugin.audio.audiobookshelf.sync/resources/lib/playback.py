# SPDX-License-Identifier: GPL-3.0-or-later
"""Turns a "play" request into something Kodi can play, and tells the service
how to sync it.

Streaming  : opens a server playback session; tracks are served from the public
             session route, so neither the stream nor the cover URL has a token.
Downloaded : plays the local file(s); progress is stored locally and pushed as a
             local session (immediately if online, queued otherwise).

The hand-off to the background service is a JSON blob on the Home window
(see utils.set_ctx); the service's Player callbacks pick it up when audio starts.
"""
import os
import uuid

import xbmc
import xbmcgui
import xbmcplugin

from . import api, items, store, sync, utils
from .strings import S


class PlaybackFailed(Exception):
    pass


def _files_ok(download):
    return all(os.path.exists(t["path"]) for t in download["tracks"])


def _start_index(tracks, position):
    index = 0
    for i, track in enumerate(tracks):
        if track["offset"] <= position + 0.001:
            index = i
    return index


def _pick_start(position, duration, explicit_start):
    """Apply resume mode and rewind. `position` is the stored resume point."""
    if explicit_start is not None:
        return max(0.0, float(explicit_start))
    if position <= 1 or (duration and position >= duration - 5):
        return 0.0
    if utils.s_int("resume_mode", 0) == 1 and position > 30:
        choice = xbmcgui.Dialog().contextmenu([
            utils.t(S.D_RESUME_FROM) % utils.fmt_duration(position),
            utils.t(S.D_FROM_START),
        ])
        if choice == 1:
            return 0.0
        if choice < 0:
            raise PlaybackFailed("cancelled")
    rewind = utils.s_int("resume_rewind", 3)
    return max(0.0, position - rewind) if position > rewind + 1 else position


def _plan_session(client, item_id, episode_id, start):
    if not client.configured():
        raise api.ABSError(utils.t(S.D_SETUP))
    try:
        sync.flush_queue(client)
    except Exception as exc:  # never block playback on queue problems
        utils.debug("queue flush before play failed: %s" % exc)
    session = client.start_session(item_id, episode_id)
    sid = session["id"]
    tracks = [{
        "url": client.track_url(sid, tr.get("index", 1)),
        "offset": utils.to_float(tr.get("startOffset")),
        "duration": utils.to_float(tr.get("duration")),
    } for tr in session.get("audioTracks", [])]
    if not tracks:
        raise api.ABSNotFound("session has no audio tracks")
    duration = utils.to_float(session.get("duration")) or sum(t["duration"] for t in tracks)
    meta = session.get("mediaMetadata") or {}
    media_type = session.get("mediaType", "book")
    position = _pick_start(utils.to_float(session.get("currentTime")), duration, start)
    return {
        "mode": "session",
        "session_id": sid,
        "item_id": item_id,
        "episode_id": episode_id,
        "media_type": media_type,
        "title": session.get("displayTitle", ""),
        "author": session.get("displayAuthor", ""),
        "album": meta.get("title") or session.get("displayTitle", ""),
        "duration": duration,
        "tracks": tracks,
        "start_position": position,
        "cover": client.cover_url(item_id),
    }


def _server_progress_quick(client, item_id, episode_id):
    """Best-effort fetch with tight timeouts; offline playback must stay instant."""
    if client is None or not client.configured():
        return None
    try:
        return client.get_progress(item_id, episode_id, quick=True)
    except api.ABSError:
        return None


def _plan_local(client, download, start):
    item_id, episode_id = download["item_id"], download["episode_id"]
    local = store.get_progress(item_id, episode_id)
    server = _server_progress_quick(client, item_id, episode_id)
    position, finished, stamp = 0.0, False, 0
    if local:
        position, finished, stamp = local["position"], bool(local["is_finished"]), local["updated_at"]
    if server and utils.to_float(server.get("lastUpdate")) > stamp:
        position = utils.to_float(server.get("currentTime"))
        finished = bool(server.get("isFinished"))
    if finished:
        position = 0.0
    duration = utils.to_float(download.get("duration"))
    return {
        "mode": "local",
        "session_id": str(uuid.uuid4()),
        "item_id": item_id,
        "episode_id": episode_id,
        "media_type": download.get("media_type", "book"),
        "title": download.get("title", ""),
        "author": download.get("author", ""),
        "album": download.get("parent_title") or download.get("title", ""),
        "duration": duration,
        "tracks": [{"url": t["path"], "offset": t["offset"], "duration": t["duration"]}
                   for t in download["tracks"]],
        "start_position": _pick_start(position, duration, start),
        "cover": download.get("cover") or "",
    }


def _listitem(plan, track, start_in_track=None):
    li = xbmcgui.ListItem(label=plan["title"], path=track["url"], offscreen=True)
    items.apply_info(li, {
        "title": plan["title"], "artist": plan["author"], "album": plan["album"],
        "duration": plan["duration"] if len(plan["tracks"]) == 1 else track["duration"],
    })
    cover = plan.get("cover")
    li.setArt({"thumb": cover, "icon": cover, "fanart": utils.FANART} if cover else {"fanart": utils.FANART})
    if start_in_track and start_in_track > 1:
        li.setProperty("StartOffset", "%.1f" % start_in_track)
    return li


def resolve(handle, item_id, episode_id=None, start=None):
    """Entry point for plugin://...?action=play. Always resolves the handle."""
    key = store.make_key(item_id, episode_id)
    plan = None
    try:
        download = store.get_download(key)
        if download and not _files_ok(download):
            store.remove_download(key)
            download = None
        client = api.ABSClient()
        if download and utils.s_bool("prefer_local", True):
            plan = _plan_local(client, download, start)
            utils.notify(utils.t(S.D_PLAYING_LOCAL), time_ms=1500)
        else:
            try:
                plan = _plan_session(client, item_id, episode_id, start)
            except api.ABSConnectionError:
                if not download:
                    raise
                plan = _plan_local(None, download, start)
    except PlaybackFailed:
        pass
    except api.ABSConnectionError:
        utils.notify(utils.t(S.D_OFFLINE), error=True)
    except api.ABSAuthError:
        utils.notify(utils.t(S.D_AUTH_FAILED), error=True)
    except api.ABSNotFound:
        utils.notify(utils.t(S.D_UNAVAILABLE), error=True)
    except api.ABSError as exc:
        utils.notify(str(exc)[:80], error=True)

    if not plan:
        xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
        return

    tracks = plan["tracks"]
    start_track = _start_index(tracks, plan["start_position"])
    start_in_track = plan["start_position"] - tracks[start_track]["offset"]
    ctx = {k: plan[k] for k in ("mode", "session_id", "item_id", "episode_id", "media_type",
                                "title", "author", "duration", "tracks", "start_position")}
    ctx.update({"start_track": start_track, "start_in_track": start_in_track,
                "started_at": utils.now_ms()})
    utils.set_ctx(ctx)

    if len(tracks) == 1:
        xbmcplugin.setResolvedUrl(handle, True, _listitem(plan, tracks[0], start_in_track))
        return

    playlist = xbmc.PlayList(xbmc.PLAYLIST_MUSIC)
    playlist.clear()
    for i, track in enumerate(tracks):
        playlist.add(track["url"], _listitem(plan, track, start_in_track if i == start_track else None))
    xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
    xbmc.Player().play(playlist, startpos=start_track)
