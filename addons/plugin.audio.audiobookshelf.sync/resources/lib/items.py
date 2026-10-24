# SPDX-License-Identifier: GPL-3.0-or-later
"""ListItem construction helpers."""
import time

import xbmcgui

from . import utils
from .strings import S


def release_date(ms):
    if not ms:
        return ""
    try:
        return time.strftime("%Y-%m-%d", time.gmtime(int(ms) / 1000.0))
    except (OverflowError, ValueError, OSError):
        return ""


def status_text(progress, duration=0, downloaded=False, queued=False):
    """Short right-hand label: played / time left, plus download state."""
    parts = []
    if progress:
        if progress.get("isFinished"):
            parts.append(utils.t(S.ST_PLAYED))
        else:
            cur = utils.to_float(progress.get("currentTime"))
            dur = utils.to_float(progress.get("duration")) or utils.to_float(duration)
            if cur > 5 and dur > cur:
                parts.append(utils.t(S.ST_LEFT) % utils.fmt_duration(dur - cur))
    if downloaded:
        parts.append(utils.t(S.ST_DOWNLOADED))
    elif queued:
        parts.append(utils.t(S.ST_QUEUED))
    return " · ".join(parts)


def apply_info(li, info):
    """Fill the music info tag (Kodi 20+ API)."""
    tag = li.getMusicInfoTag()
    tag.setMediaType(info.get("mediatype", "song"))
    tag.setTitle(info.get("title", ""))
    if info.get("artist"):
        tag.setArtist(info["artist"])
    if info.get("album"):
        tag.setAlbum(info["album"])
    if info.get("duration"):
        tag.setDuration(int(info["duration"]))
    if info.get("plot"):
        tag.setComment(info["plot"])
    if info.get("year"):
        tag.setYear(int(info["year"]))
    if info.get("date"):
        tag.setReleaseDate(info["date"])
    tag.setPlayCount(1 if info.get("played") else 0)
    if info.get("genre"):
        tag.setGenres([info["genre"]] if isinstance(info["genre"], str) else list(info["genre"]))


def make(label, url, folder=True, cover=None, info=None, label2=None, context=None,
         playable=False, props=None):
    """Returns the (url, listitem, isFolder) tuple xbmcplugin expects."""
    li = xbmcgui.ListItem(label=label, offscreen=True)
    if label2:
        li.setLabel2(label2)
    art = {"fanart": utils.FANART}
    if cover:
        art.update({"thumb": cover, "icon": cover, "poster": cover})
    else:
        art.update({"thumb": utils.ICON, "icon": utils.ICON})
    li.setArt(art)
    if info:
        apply_info(li, info)
    if playable:
        li.setProperty("IsPlayable", "true")
    for key, value in (props or {}).items():
        li.setProperty(key, str(value))
    if context:
        li.addContextMenuItems(context)
    return (url, li, folder)


def run(label, **params):
    """Context-menu entry that runs a plugin action."""
    return (label, "RunPlugin(%s)" % utils.plugin_url(**params))


def container(label, **params):
    return (label, "Container.Update(%s)" % utils.plugin_url(**params))
