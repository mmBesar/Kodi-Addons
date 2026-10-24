# SPDX-License-Identifier: GPL-3.0-or-later
"""Maps plugin:// URLs to views/actions."""
import sys
from urllib.parse import parse_qsl

import xbmc
import xbmcgui
import xbmcplugin

from . import actions, api, playback, store, utils, views
from .strings import S


def _params(query):
    return dict(parse_qsl(query.lstrip("?")))


def _flag(value):
    return str(value) in ("1", "true", "True")


def _need_config(handle, client):
    if client.configured():
        return False
    if xbmcgui.Dialog().yesno(utils.ADDON_NAME, utils.t(S.D_SETUP)):
        utils.open_settings()
    xbmcplugin.endOfDirectory(handle, succeeded=False)
    return True


def _browse(handle, p):
    ctx = views.Ctx(handle)
    action = p.get("action", "root")
    if action in ("downloads",):
        return views.downloads(ctx, p.get("group"))
    if action == "root":
        return views.root(ctx)
    if _need_config(handle, ctx.client):
        return None
    page = int(p.get("page", 0) or 0)
    if action == "continue":
        return views.continue_listening(ctx)
    if action == "latest":
        return views.latest(ctx)
    if action == "libraries":
        return views.libraries(ctx, p.get("kind", "podcast"))
    if action == "library":
        return views.library_items(ctx, p["lib"], p.get("kind", "podcast"), page)
    if action == "podcast":
        return views.podcast(ctx, p["item"], page)
    if action == "chapters":
        return views.chapters(ctx, p["item"])
    if action == "search":
        query = p.get("q") or xbmcgui.Dialog().input(utils.t(S.D_SEARCH_HEADING))
        if not query:
            return xbmcplugin.endOfDirectory(handle, succeeded=False)
        return views.search(ctx, query)
    if action == "podcast_menu":  # opened as a folder from the list; show the dialog, stay put
        actions.podcast_menu(ctx.client, p["item"])
        return xbmcplugin.endOfDirectory(handle, succeeded=False)
    if action == "add_podcast":
        actions.add_podcast(ctx.client)
        return xbmcplugin.endOfDirectory(handle, succeeded=False)
    if action == "sync_now":
        actions.sync_now()
        return xbmcplugin.endOfDirectory(handle, succeeded=False)
    raise ValueError("unknown action %r" % action)


def _do(p):
    """Actions started with RunPlugin: no directory handle is involved."""
    action = p["action"]
    client = api.ABSClient()
    if action == "mark":
        return actions.mark(client, p["item"], p.get("ep") or None, _flag(p.get("finished", 1)))
    if action == "dl_add":
        return actions.dl_add(p["item"], p.get("ep") or None)
    if action == "dl_remove":
        return actions.dl_remove(p["key"])
    if action == "dl_remove_group":
        return actions.dl_remove_group(p["group"])
    if action == "podcast_menu":
        return actions.podcast_menu(client, p["item"])
    if action == "sync_now":
        return actions.sync_now()
    if action == "test_connection":
        return actions.test_connection()
    if action == "open_settings":
        return utils.open_settings()
    raise ValueError("unknown action %r" % action)


RUN_ACTIONS = {"mark", "dl_add", "dl_remove", "dl_remove_group", "test_connection", "open_settings"}


def run(argv=None):
    argv = argv or sys.argv
    handle = int(argv[1]) if len(argv) > 1 and str(argv[1]).lstrip("-").isdigit() else -1
    p = _params(argv[2] if len(argv) > 2 else "")
    action = p.get("action", "root")
    try:
        if action == "play":
            return playback.resolve(handle, p["item"], p.get("ep") or None,
                                    float(p["start"]) if p.get("start") else None)
        if action == "play_start":
            return playback.resolve(handle, p["item"], p.get("ep") or None, 0.0)
        if handle < 0 or action in RUN_ACTIONS:
            return _do(p)
        return _browse(handle, p)
    except api.ABSConnectionError as exc:
        utils.log("offline: %s" % exc)
        if handle >= 0 and action not in RUN_ACTIONS:
            if store.has_downloads() and action != "downloads":
                utils.notify(utils.t(S.D_OFFLINE_DL), error=True)
                return views.downloads(views.Ctx(handle))
            xbmcplugin.endOfDirectory(handle, succeeded=False)
        utils.notify(utils.t(S.D_OFFLINE), error=True)
    except api.ABSAuthError:
        utils.notify(utils.t(S.D_AUTH_FAILED), error=True)
        if handle >= 0 and action not in RUN_ACTIONS:
            xbmcplugin.endOfDirectory(handle, succeeded=False)
    except api.ABSForbidden:
        utils.notify(utils.t(S.D_FORBIDDEN), error=True)
        if handle >= 0 and action not in RUN_ACTIONS:
            xbmcplugin.endOfDirectory(handle, succeeded=False)
    except api.ABSError as exc:
        utils.log("server error: %s" % exc, xbmc.LOGERROR)
        utils.notify(str(exc)[:90], error=True)
        if handle >= 0 and action not in RUN_ACTIONS:
            xbmcplugin.endOfDirectory(handle, succeeded=False)
