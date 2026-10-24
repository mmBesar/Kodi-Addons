# SPDX-License-Identifier: GPL-3.0-or-later
"""Directory listings."""
import xbmcgui
import xbmcplugin

from . import api, items, store, utils
from .strings import S


class Ctx:
    """Per-invocation state: plugin handle, API client and cached lookups."""

    def __init__(self, handle):
        self.handle = handle
        self.client = api.ABSClient()
        self._progress = None
        self.downloaded = store.downloaded_keys()
        self.queued = store.queued_keys()

    def progress(self):
        """Server progress overlaid with newer local progress (offline listening)."""
        if self._progress is None:
            try:
                merged = self.client.progress_map()
            except api.ABSError:  # offline / not configured: fall back to local progress
                merged = {}
            for key, local in store.local_progress_map().items():
                remote = merged.get(key)
                if not remote or local["lastUpdate"] > utils.to_float(remote.get("lastUpdate")):
                    merged[key] = local
            self._progress = merged
        return self._progress

    def page_size(self):
        return max(20, utils.s_int("page_size", 100))


def finish(ctx, entries, content="songs", title=None, sort=False, cache=False):
    xbmcplugin.setContent(ctx.handle, content)
    if title:
        xbmcplugin.setPluginCategory(ctx.handle, title)
    if sort:
        xbmcplugin.addSortMethod(ctx.handle, xbmcplugin.SORT_METHOD_LABEL_IGNORE_THE)
    else:
        xbmcplugin.addSortMethod(ctx.handle, xbmcplugin.SORT_METHOD_UNSORTED)
    if entries:
        xbmcplugin.addDirectoryItems(ctx.handle, entries, len(entries))
    xbmcplugin.endOfDirectory(ctx.handle, succeeded=True, cacheToDisc=cache)


def empty(ctx):
    xbmcgui.Dialog().notification(utils.ADDON_NAME, utils.t(S.D_EMPTY), xbmcgui.NOTIFICATION_INFO, 2500)
    xbmcplugin.endOfDirectory(ctx.handle, succeeded=False)


# --------------------------------------------------------------------------
# Builders
# --------------------------------------------------------------------------
def _play_url(item_id, episode_id=None, **extra):
    return utils.plugin_url(action="play", item=item_id, ep=episode_id, **extra)


def episode_entry(ctx, item_id, ep, podcast_title, author, show_podcast=False):
    ep_id = ep["id"]
    key = store.make_key(item_id, ep_id)
    progress = ctx.progress().get(key)
    duration = utils.to_float(ep.get("duration") or (ep.get("audioFile") or {}).get("duration"))
    downloaded = key in ctx.downloaded
    label = ep.get("title") or "?"
    if show_podcast and podcast_title:
        label = "%s - %s" % (podcast_title, label)
    played = bool(progress and progress.get("isFinished"))
    desc = utils.strip_html(ep.get("description") or ep.get("subtitle") or "")
    cover = ctx.client.cover_url(item_id)
    menu = [
        items.run(utils.t(S.C_MARK_UNPLAYED if played else S.C_MARK_PLAYED),
                  action="mark", item=item_id, ep=ep_id, finished=0 if played else 1),
        items.run(utils.t(S.C_REMOVE_DL if downloaded else S.C_DOWNLOAD),
                  action="dl_remove" if downloaded else "dl_add", item=item_id, ep=ep_id, key=key),
        items.container(utils.t(S.C_GOTO_PODCAST), action="podcast", item=item_id),
        items.run(utils.t(S.M_PODCAST_OPTIONS), action="podcast_menu", item=item_id),
    ]
    return items.make(
        label, _play_url(item_id, ep_id), folder=False, cover=cover, playable=True,
        label2=items.status_text(progress, duration, downloaded, key in ctx.queued),
        info={"title": ep.get("title", ""), "artist": author, "album": podcast_title,
              "duration": duration, "plot": desc, "played": played,
              "date": items.release_date(ep.get("publishedAt"))},
        context=menu)


def book_entry(ctx, li):
    item_id = li["id"]
    meta = (li.get("media") or {}).get("metadata") or {}
    progress = ctx.progress().get(item_id)
    duration = utils.to_float((li.get("media") or {}).get("duration"))
    downloaded = item_id in ctx.downloaded
    played = bool(progress and progress.get("isFinished"))
    menu = [
        items.run(utils.t(S.C_MARK_UNPLAYED if played else S.C_MARK_PLAYED),
                  action="mark", item=item_id, finished=0 if played else 1),
        items.run(utils.t(S.C_REMOVE_DL if downloaded else S.C_DOWNLOAD),
                  action="dl_remove" if downloaded else "dl_add", item=item_id, key=item_id),
        items.container(utils.t(S.M_CHAPTERS), action="chapters", item=item_id),
        items.run(utils.t(S.M_PLAY_FROM_START), action="play_start", item=item_id),
    ]
    return items.make(
        meta.get("title", "?"), _play_url(item_id), folder=False,
        cover=ctx.client.cover_url(item_id), playable=True,
        label2=items.status_text(progress, duration, downloaded, item_id in ctx.queued),
        info={"title": meta.get("title", ""), "artist": meta.get("authorName", ""),
              "album": meta.get("seriesName") or meta.get("title", ""), "duration": duration,
              "played": played, "year": meta.get("publishedYear") or None, "mediatype": "song"},
        context=menu)


def podcast_entry(ctx, li):
    item_id = li["id"]
    media = li.get("media") or {}
    meta = media.get("metadata") or {}
    auto = store.get_auto(item_id)
    menu = [items.run(utils.t(S.M_PODCAST_OPTIONS), action="podcast_menu", item=item_id)]
    label2 = utils.t(S.C_AUTO_ON) if auto else ""
    return items.make(
        meta.get("title", "?"), utils.plugin_url(action="podcast", item=item_id), folder=True,
        cover=ctx.client.cover_url(item_id), label2=label2, context=menu,
        info={"title": meta.get("title", ""), "artist": meta.get("author", ""),
              "album": meta.get("title", ""), "mediatype": "album",
              "plot": utils.strip_html(meta.get("description") or "")[:1500]})


def _next_page(action, page, **extra):
    return items.make(utils.t(S.M_NEXT_PAGE) + " >", utils.plugin_url(action=action, page=page, **extra),
                      folder=True)


# --------------------------------------------------------------------------
# Views
# --------------------------------------------------------------------------
def root(ctx):
    def entry(label, **params):
        return items.make(label, utils.plugin_url(**params), folder=True)

    entries = [
        entry(utils.t(S.M_CONTINUE), action="continue"),
        entry(utils.t(S.M_LATEST), action="latest"),
        entry(utils.t(S.M_PODCASTS), action="libraries", kind="podcast"),
        entry(utils.t(S.M_BOOKS), action="libraries", kind="book"),
        entry(utils.t(S.M_SEARCH), action="search"),
        entry(utils.t(S.M_DOWNLOADS), action="downloads"),
        entry(utils.t(S.M_ADD_PODCAST), action="add_podcast"),
        entry(utils.t(S.M_SYNC_NOW), action="sync_now"),
        entry(utils.t(S.M_SETTINGS), action="open_settings"),
    ]
    finish(ctx, entries, content="files")


def libraries(ctx, kind):
    libs = [l for l in ctx.client.libraries() if l.get("mediaType") == kind]
    if not libs:
        return empty(ctx)
    if len(libs) == 1:
        return library_items(ctx, libs[0]["id"], kind, 0)
    entries = [items.make(l.get("name", "?"), utils.plugin_url(action="library", lib=l["id"], kind=kind),
                          folder=True) for l in libs]
    finish(ctx, entries, content="files")


def library_items(ctx, lib_id, kind, page):
    size = ctx.page_size()
    data = ctx.client.library_items(lib_id, page=page, limit=size)
    results = data.get("results", [])
    if not results:
        return empty(ctx)
    build = podcast_entry if kind == "podcast" else book_entry
    entries = [build(ctx, li) for li in results]
    if (page + 1) * size < data.get("total", 0):
        entries.append(_next_page("library", page + 1, lib=lib_id, kind=kind))
    finish(ctx, entries, content="albums" if kind == "podcast" else "songs")


def continue_listening(ctx):
    entries = []
    for li in ctx.client.in_progress(limit=ctx.page_size()):
        meta = (li.get("media") or {}).get("metadata") or {}
        recent = li.get("recentEpisode")
        if recent:
            entries.append(episode_entry(ctx, li["id"], recent, meta.get("title", ""),
                                         meta.get("author", ""), show_podcast=True))
        elif li.get("mediaType") == "book":
            entries.append(book_entry(ctx, li))
    if not entries:
        return empty(ctx)
    finish(ctx, entries)


def latest(ctx):
    episodes = []
    for lib in ctx.client.libraries():
        if lib.get("mediaType") == "podcast":
            episodes.extend(ctx.client.recent_episodes(lib["id"], limit=ctx.page_size()))
    episodes.sort(key=lambda e: e.get("publishedAt") or 0, reverse=True)
    entries = []
    for ep in episodes[:ctx.page_size()]:
        pod = ((ep.get("podcast") or {}).get("metadata")) or {}
        entries.append(episode_entry(ctx, ep.get("libraryItemId"), ep, pod.get("title", ""),
                                     pod.get("author", ""), show_podcast=True))
    if not entries:
        return empty(ctx)
    finish(ctx, entries)


def podcast(ctx, item_id, page):
    item = ctx.client.item(item_id)
    media = item.get("media") or {}
    meta = media.get("metadata") or {}
    episodes = [e for e in media.get("episodes", []) if e.get("audioFile")]
    episodes.sort(key=lambda e: e.get("publishedAt") or 0, reverse=utils.s_bool("newest_first", True))
    progress = ctx.progress()
    if utils.s_bool("hide_played", False):
        episodes = [e for e in episodes if not (progress.get(store.make_key(item_id, e["id"])) or {}).get("isFinished")]
    size = ctx.page_size()
    window = episodes[page * size:(page + 1) * size]
    entries = []
    if page == 0:
        entries.append(items.make(utils.t(S.M_PODCAST_OPTIONS), utils.plugin_url(action="podcast_menu", item=item_id),
                                  folder=True, cover=ctx.client.cover_url(item_id)))
    entries += [episode_entry(ctx, item_id, e, meta.get("title", ""), meta.get("author", "")) for e in window]
    if (page + 1) * size < len(episodes):
        entries.append(_next_page("podcast", page + 1, item=item_id))
    finish(ctx, entries, title=meta.get("title"))


def chapters(ctx, item_id):
    item = ctx.client.item(item_id)
    media = item.get("media") or {}
    meta = media.get("metadata") or {}
    entries = []
    for chap in media.get("chapters", []):
        start = utils.to_float(chap.get("start"))
        label = "%s  (%s)" % (chap.get("title", "?"), utils.fmt_duration(start))
        entries.append(items.make(
            label, _play_url(item_id, start="%.2f" % start), folder=False, playable=True,
            cover=ctx.client.cover_url(item_id),
            info={"title": chap.get("title", ""), "artist": meta.get("authorName", ""),
                  "album": meta.get("title", ""),
                  "duration": utils.to_float(chap.get("end")) - start}))
    if not entries:
        return empty(ctx)
    finish(ctx, entries, title=meta.get("title"))


def search(ctx, query):
    results_pod, results_books = [], []
    for lib in ctx.client.libraries():
        data = ctx.client.library_search(lib["id"], query)
        if lib.get("mediaType") == "podcast":
            results_pod += [r["libraryItem"] for r in data.get("podcast", []) if r.get("libraryItem")]
        else:
            results_books += [r["libraryItem"] for r in data.get("book", []) if r.get("libraryItem")]
    entries = [podcast_entry(ctx, li) for li in results_pod] + [book_entry(ctx, li) for li in results_books]
    if not entries:
        xbmcgui.Dialog().notification(utils.ADDON_NAME, utils.t(S.D_NO_RESULTS), xbmcgui.NOTIFICATION_INFO, 2500)
        return xbmcplugin.endOfDirectory(ctx.handle, succeeded=False)
    finish(ctx, entries, title=query)


def downloads(ctx, group=None):
    records = store.list_downloads()
    entries = []
    progress = ctx.progress()
    if group is None:
        seen = set()
        for rec in records:
            if rec["media_type"] == "podcast":
                if rec["parent_title"] not in seen:
                    seen.add(rec["parent_title"])
                    entries.append(items.make(
                        rec["parent_title"], utils.plugin_url(action="downloads", group=rec["parent_title"]),
                        folder=True, cover=rec.get("cover") or None,
                        context=[items.run(utils.t(S.C_REMOVE_ALL_DL), action="dl_remove_group",
                                           group=rec["parent_title"])]))
    for rec in records:
        if group is None and rec["media_type"] == "podcast":
            continue
        if group is not None and (rec["media_type"] != "podcast" or rec["parent_title"] != group):
            continue
        mp = progress.get(rec["key"])
        entries.append(items.make(
            rec["title"], _play_url(rec["item_id"], rec["episode_id"]), folder=False,
            cover=rec.get("cover") or None, playable=True,
            label2=items.status_text(mp, rec["duration"]),
            info={"title": rec["title"], "artist": rec["author"], "album": rec["parent_title"],
                  "duration": rec["duration"], "plot": rec.get("description", ""),
                  "played": bool(mp and mp.get("isFinished")),
                  "date": items.release_date(rec.get("published_at"))},
            context=[items.run(utils.t(S.C_REMOVE_DL), action="dl_remove", key=rec["key"])]))
    if not entries:
        return empty(ctx)
    finish(ctx, entries, title=utils.t(S.M_DOWNLOADS))
