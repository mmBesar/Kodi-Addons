# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline files: queueing, resumable download, removal and auto-download rules.

Files are written next to the Kodi profile (or a user-chosen *local* folder) as
`<Podcast>/<date> <title> [id].mp3` and `<Author - Title>/NN filename`. Partial
transfers keep a `.part` file and continue with an HTTP Range request.
"""
import os
import shutil
import time

import xbmcgui
import xbmcvfs

from . import api, store, utils
from .strings import S

CHUNK = 256 * 1024


class DownloadError(Exception):
    pass


class Aborted(Exception):
    pass


def root_dir():
    raw = utils.s_str("download_path").strip()
    path = xbmcvfs.translatePath(raw) if raw else os.path.join(utils.PROFILE, "downloads")
    if "://" in path:
        raise DownloadError(utils.t(S.D_DL_LOCAL_ONLY))
    os.makedirs(path, exist_ok=True)
    return path


def is_downloaded(item_id, episode_id=None):
    return store.get_download(store.make_key(item_id, episode_id)) is not None


def enqueue(item_id, episode_id=None):
    """Queue one item. Returns True if newly queued."""
    key = store.make_key(item_id, episode_id)
    if store.get_download(key) or store.is_queued(key):
        return False
    store.queue_download(item_id, episode_id)
    return True


# --------------------------------------------------------------------------
# Describing what to fetch
# --------------------------------------------------------------------------
def _ext(filename, default=".mp3"):
    ext = os.path.splitext(filename or "")[1].lower()
    return ext if 1 < len(ext) <= 6 else default


def describe(client, item_id, episode_id):
    """Returns (record, files). `files` = [{ino, filename, size, duration, offset}]."""
    item = client.item(item_id)
    media = item.get("media") or {}
    meta = media.get("metadata") or {}
    if episode_id:
        episode = next((e for e in media.get("episodes", []) if e.get("id") == episode_id), None)
        if not episode or not episode.get("audioFile"):
            raise api.ABSNotFound("episode is not on the server")
        audio = episode["audioFile"]
        duration = utils.to_float(episode.get("duration") or audio.get("duration"))
        files = [{"ino": audio["ino"], "filename": (audio.get("metadata") or {}).get("filename", "episode.mp3"),
                  "size": int((audio.get("metadata") or {}).get("size") or 0),
                  "duration": duration, "offset": 0.0}]
        record = {
            "media_type": "podcast", "title": episode.get("title", ""),
            "parent_title": meta.get("title", ""), "author": meta.get("author", ""),
            "description": utils.strip_html(episode.get("description") or episode.get("subtitle") or "")[:2000],
            "duration": duration, "published_at": int(episode.get("publishedAt") or 0),
        }
    else:
        tracks = media.get("tracks") or []
        if not tracks:
            raise api.ABSNotFound("book has no audio tracks")
        files = []
        for tr in tracks:
            files.append({
                "ino": str(tr.get("contentUrl", "")).rstrip("/").rsplit("/", 1)[-1],
                "filename": (tr.get("metadata") or {}).get("filename", "track.mp3"),
                "size": int((tr.get("metadata") or {}).get("size") or 0),
                "duration": utils.to_float(tr.get("duration")),
                "offset": utils.to_float(tr.get("startOffset")),
            })
        record = {
            "media_type": "book", "title": meta.get("title", ""),
            "parent_title": meta.get("seriesName") or "",
            "author": meta.get("authorName", ""),
            "description": utils.strip_html(meta.get("description") or "")[:2000],
            "duration": utils.to_float(media.get("duration")) or sum(f["duration"] for f in files),
            "published_at": 0,
        }
    record.update({"key": store.make_key(item_id, episode_id), "item_id": item_id, "episode_id": episode_id})
    return record, files


def _target_paths(root, record, files):
    short = (record["episode_id"] or record["item_id"])[-6:]
    if record["media_type"] == "podcast":
        folder = os.path.join(root, utils.safe_name(record["parent_title"]))
        date = time.strftime("%Y-%m-%d", time.gmtime(record["published_at"] / 1000)) if record["published_at"] else "undated"
        base = "%s %s [%s]" % (date, utils.safe_name(record["title"], 70), short)
        return folder, [os.path.join(folder, base + _ext(files[0]["filename"]))]
    label = utils.safe_name("%s - %s" % (record["author"] or "Unknown", record["title"]), 100)
    folder = os.path.join(root, "%s [%s]" % (label, short))
    return folder, [os.path.join(folder, "%02d %s" % (i + 1, utils.safe_name(f["filename"], 80)))
                    for i, f in enumerate(files)]


# --------------------------------------------------------------------------
# Transfer
# --------------------------------------------------------------------------
def _fetch(client, item_id, file_info, dest, progress, should_abort):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    part = dest + ".part"
    done = os.path.getsize(part) if os.path.exists(part) else 0
    headers = {"Accept-Encoding": "identity"}
    if done:
        headers["Range"] = "bytes=%d-" % done
    resp = client.stream("/api/items/%s/file/%s" % (item_id, file_info["ino"]), headers=headers)
    try:
        if resp.status_code == 416:  # we already have everything
            os.replace(part, dest)
            return
        if resp.status_code >= 400:
            api.ABSClient._parse(resp)  # raises the matching ABSError
        append = done > 0 and resp.status_code == 206
        if not append:
            done = 0
        with open(part, "ab" if append else "wb") as fh:
            for chunk in resp.iter_content(CHUNK):
                if should_abort():
                    raise Aborted()
                if chunk:
                    fh.write(chunk)
                    done += len(chunk)
                    progress(done)
    except api.requests.exceptions.RequestException as exc:
        raise api.ABSConnectionError("transfer interrupted: %s" % type(exc).__name__)
    finally:
        resp.close()
    expected = file_info.get("size") or 0
    if expected and os.path.getsize(part) < expected:
        raise api.ABSConnectionError("transfer incomplete")  # keeps .part for resume
    os.replace(part, dest)


def _save_cover(client, item_id, folder):
    dest = os.path.join(folder, "cover.jpg")
    if os.path.exists(dest):
        return dest
    try:
        resp = client.http.get(client.cover_url(item_id, 600, direct=True), timeout=(5, 20), verify=client.verify)
        if resp.status_code == 200 and resp.content:
            with open(dest, "wb") as fh:
                fh.write(resp.content)
            return dest
    except Exception as exc:  # artwork is optional
        utils.debug("cover download failed: %s" % exc)
    return ""


def process_next(monitor):
    """Handle one queue entry. Returns 'idle' | 'done' | 'offline' | 'failed'."""
    row = store.next_queued()
    if not row:
        return "idle"
    key = row["key"]
    client = api.ABSClient()
    bg = None
    try:
        if not client.configured():
            return "offline"
        record, files = describe(client, row["item_id"], row["episode_id"])
        root = root_dir()
        folder, dests = _target_paths(root, record, files)
        needed = sum(f["size"] for f in files)
        os.makedirs(folder, exist_ok=True)
        if needed and shutil.disk_usage(folder).free < needed * 1.1 + 50 * 1024 * 1024:
            raise DownloadError(utils.t(S.D_DL_SPACE))

        label = record["title"] or key
        utils.notify(utils.t(S.D_DL_START) % label, time_ms=2000)
        bg = xbmcgui.DialogProgressBG()
        bg.create(utils.ADDON_NAME, label)
        total = needed or 1
        finished_bytes = 0
        last_ui = [0.0]
        tracks = []
        for info, dest in zip(files, dests):
            base = finished_bytes

            def progress(done, _base=base):
                if time.monotonic() - last_ui[0] > 1.0:
                    last_ui[0] = time.monotonic()
                    bg.update(min(99, int((_base + done) * 100 / total)), utils.ADDON_NAME, label)

            _fetch(client, row["item_id"], info, dest, progress, monitor.abortRequested)
            finished_bytes += info["size"] or os.path.getsize(dest)
            tracks.append({"path": dest, "offset": info["offset"], "duration": info["duration"]})

        record["cover"] = _save_cover(client, row["item_id"], folder)
        record["size"] = finished_bytes
        record["tracks"] = tracks
        store.add_download(record)
        store.drop_queued(key)
        utils.notify(utils.t(S.D_DL_DONE) % label, time_ms=2500)
        return "done"
    except Aborted:
        return "idle"
    except api.ABSConnectionError as exc:
        utils.debug("download paused (offline): %s" % exc)
        return "offline"
    except api.ABSNotFound:
        store.drop_queued(key)
        return "failed"
    except (api.ABSError, DownloadError, OSError) as exc:
        store.fail_queued(key, str(exc))
        utils.notify(utils.t(S.D_DL_FAIL) % str(exc)[:70], error=True)
        if row["attempts"] + 1 >= 3:
            store.drop_queued(key)
        return "failed"
    finally:
        if bg is not None:
            bg.close()


# --------------------------------------------------------------------------
# Removal
# --------------------------------------------------------------------------
def remove(key):
    rec = store.get_download(key)
    if not rec:
        return False
    folders = set()
    for track in rec["tracks"]:
        folders.add(os.path.dirname(track["path"]))
        for path in (track["path"], track["path"] + ".part"):
            try:
                os.remove(path)
            except OSError:
                pass
    store.remove_download(key)
    for folder in folders:
        try:
            left = [n for n in os.listdir(folder) if n != "cover.jpg"]
            if not left:
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            pass
    return True


def remove_group(parent_title):
    count = 0
    for rec in store.list_downloads():
        if rec["parent_title"] == parent_title and rec["media_type"] == "podcast":
            count += 1 if remove(rec["key"]) else 0
    return count


# --------------------------------------------------------------------------
# Rules: auto-download and clean-up of played episodes
# --------------------------------------------------------------------------
def cleanup_played(client, progress=None):
    """Remove downloaded podcast episodes the server says are played."""
    if not utils.s_bool("delete_played", True):
        return 0
    progress = progress if progress is not None else client.progress_map()
    removed = 0
    for rec in store.list_downloads():
        if rec["media_type"] != "podcast":
            continue
        mp = progress.get(rec["key"])
        if mp and mp.get("isFinished"):
            removed += 1 if remove(rec["key"]) else 0
    return removed


def unplayed_episodes(item, progress):
    item_id = item["id"]
    episodes = [e for e in (item.get("media") or {}).get("episodes", []) if e.get("audioFile")]
    episodes.sort(key=lambda e: e.get("publishedAt") or 0, reverse=True)
    return [e for e in episodes if not (progress.get("%s:%s" % (item_id, e["id"])) or {}).get("isFinished")]


def autosync(client):
    """Apply every auto-download rule. Returns number of newly queued downloads."""
    rules = store.list_auto()
    progress = client.progress_map()
    queued = 0
    for rule in rules:
        try:
            item = client.item(rule["item_id"])
        except api.ABSNotFound:
            store.clear_auto(rule["item_id"])
            continue
        for episode in unplayed_episodes(item, progress)[:max(1, rule["keep"])]:
            queued += 1 if enqueue(rule["item_id"], episode["id"]) else 0
    cleanup_played(client, progress)
    return queued
