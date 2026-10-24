#!/usr/bin/env python3
"""Smoke-test the addon's real API client against a live Audiobookshelf server.

    pip install Kodistubs requests
    python3 tools/live_check.py https://audiobooks.dev/audiobookshelf demo demo
    python3 tools/live_check.py https://abs.example.com --api-key XXXX
    python3 tools/live_check.py URL USER PASS --play     # also opens a session

Read-only by default. --play opens one playback session, range-reads a few bytes
from the public track URL and closes it (this records a tiny listening session).
"""
import argparse
import os
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ADDON = os.path.join(ROOT, "addons", "plugin.audio.audiobookshelf.sync")
sys.path.insert(0, ADDON)
PROFILE = tempfile.mkdtemp(prefix="abs-live-")
SETTINGS = {}

import xbmcaddon  # noqa: E402  (Kodistubs)
import xbmcvfs  # noqa: E402


class FakeAddon:
    def __init__(self, *a, **k):
        pass

    def getAddonInfo(self, key):
        return {"id": "plugin.audio.audiobookshelf.sync", "name": "Audiobookshelf Sync", "version": "live",
                "path": ADDON, "profile": PROFILE}[key]

    getSettingString = getSetting = lambda self, k: str(SETTINGS.get(k, ""))
    getSettingBool = lambda self, k: bool(SETTINGS.get(k, False))
    getSettingInt = lambda self, k: int(SETTINGS.get(k, 0))
    getLocalizedString = lambda self, i: "#%d" % i


xbmcaddon.Addon = FakeAddon
xbmcvfs.translatePath = lambda p: p

from resources.lib import api  # noqa: E402

FAILED = []


def step(name, fn):
    try:
        result = fn()
        text = "" if result is None else str(result)
        print("PASS  %-34s %s" % (name, text if len(text) < 80 else text[:77] + "..."))
        return result
    except Exception as exc:  # noqa: BLE001 - report every failure kind
        FAILED.append(name)
        print("FAIL  %-34s %s: %s" % (name, type(exc).__name__, exc))
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("username", nargs="?")
    ap.add_argument("password", nargs="?")
    ap.add_argument("--api-key")
    ap.add_argument("--play", action="store_true")
    a = ap.parse_args()
    SETTINGS.update({"server_url": a.url, "verify_ssl": True, "auth_method": 0 if a.api_key else 1,
                     "api_key": a.api_key or "", "username": a.username or "", "password": a.password or ""})
    c = api.ABSClient()
    print("server base: %s\n" % c.base)
    step("ping + auth (/api/me)", lambda: c.test()[1] if c.test()[0] else (_ for _ in ()).throw(RuntimeError(c.test()[1])))
    libs = step("libraries", lambda: c.libraries()) or []
    print("      " + ", ".join("%s[%s]" % (l["name"], l["mediaType"]) for l in libs))
    step("progress map", lambda: "%d entries" % len(c.progress_map()))
    step("in-progress items", lambda: "%d items" % len(c.in_progress()))
    sample = None
    for lib in libs:
        data = step("items: " + lib["name"], lambda l=lib: c.library_items(l["id"], limit=5))
        if data and data.get("results") and sample is None:
            sample = (lib, data["results"][0])
        if lib["mediaType"] == "podcast":
            step("recent episodes: " + lib["name"], lambda l=lib: "%d" % len(c.recent_episodes(l["id"], limit=5)))
        step("search: " + lib["name"], lambda l=lib: list(c.library_search(l["id"], "a").keys()))
    if not sample:
        return
    lib, li = sample
    item = step("expanded item", lambda: c.item(li["id"]))
    step("cover (no auth)", lambda: "%s bytes" % len(c.http.get(c.cover_url(li["id"], 200), timeout=15).content))
    if not (a.play and item):
        return
    media = item["media"]
    ep = None
    if lib["mediaType"] == "podcast":
        eps = [e for e in media.get("episodes", []) if e.get("audioFile")]
        ep = eps[0]["id"] if eps else None
    sess = step("open session", lambda: c.start_session(li["id"], ep))
    if not sess:
        return
    url = c.track_url(sess["id"], sess["audioTracks"][0].get("index", 1))
    step("public track range read", lambda: _range(c, url))
    step("session sync", lambda: c.sync_session(sess["id"], sess.get("currentTime", 0), 0, sess["duration"]) or "ok")
    step("session close", lambda: c.close_session(sess["id"], sess.get("currentTime", 0), 0, sess["duration"]) or "ok")


def _range(c, url):
    r = c.http.get(url, headers={"Range": "bytes=0-1023"}, timeout=20, stream=True)
    r.close()
    if r.status_code not in (200, 206):
        raise RuntimeError("HTTP %d" % r.status_code)
    return "HTTP %d (%s)" % (r.status_code, "Range honoured" if r.status_code == 206 else "full body")


if __name__ == "__main__":
    main()
    print("\n%s" % ("ALL OK" if not FAILED else "FAILED: " + ", ".join(FAILED)))
    sys.exit(1 if FAILED else 0)
