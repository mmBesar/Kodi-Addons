# SPDX-License-Identifier: GPL-3.0-or-later
import os
import re
import sys
import tempfile

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ADDON_DIR = os.path.join(ROOT, "addons", "plugin.audio.audiobookshelf.sync")
sys.path.insert(0, ADDON_DIR)
sys.path.insert(0, os.path.dirname(__file__))

SESSION_PROFILE = tempfile.mkdtemp(prefix="abs-profile-")
SETTINGS = {}


def _load_strings():
    out = {}
    text = open(os.path.join(ADDON_DIR, "resources", "language", "resource.language.en_gb", "strings.po"),
                encoding="utf-8").read()
    for sid, msg in re.findall(r'msgctxt "#(\d+)"\nmsgid "(.*?)"\nmsgstr', text):
        out[int(sid)] = msg.replace('\\"', '"')
    return out


STRINGS = _load_strings()

import xbmcaddon  # noqa: E402  (Kodistubs)
import xbmcvfs  # noqa: E402


class FakeAddon:
    def __init__(self, *args, **kwargs):
        pass

    def getAddonInfo(self, key):
        return {"id": "plugin.audio.audiobookshelf.sync", "name": "Audiobookshelf Sync",
                "version": "1.0.0", "path": ADDON_DIR, "profile": SESSION_PROFILE}[key]

    def getSettingString(self, key):
        return str(SETTINGS.get(key, ""))

    def getSettingBool(self, key):
        return bool(SETTINGS.get(key, False))

    def getSettingInt(self, key):
        return int(SETTINGS.get(key, 0))

    def getSetting(self, key):
        return str(SETTINGS.get(key, ""))

    def setSetting(self, key, value):
        SETTINGS[key] = value

    def getLocalizedString(self, sid):
        return STRINGS.get(sid, "#%d" % sid)

    def openSettings(self):
        pass


xbmcaddon.Addon = FakeAddon
xbmcvfs.translatePath = lambda p: p

from resources.lib import api, downloads, playback, router, service_core, store, sync, utils  # noqa: E402
import mock_abs  # noqa: E402


class FakeTag:
    def __init__(self):
        self.data = {}

    def __getattr__(self, name):
        if name.startswith("set"):
            return lambda *a: self.data.__setitem__(name[3:], a[0] if len(a) == 1 else a)
        raise AttributeError(name)


class FakeListItem:
    """Remembers what the addon sets (Kodistubs' ListItem forgets everything)."""

    def __init__(self, label="", label2="", path="", offscreen=False):
        self.label, self.label2, self.path = label, label2, path
        self.props, self.art, self.menu, self.tag = {}, {}, [], FakeTag()

    def getLabel(self):
        return self.label

    def getLabel2(self):
        return self.label2

    def setLabel2(self, v):
        self.label2 = v

    def getPath(self):
        return self.path

    def setPath(self, v):
        self.path = v

    def setProperty(self, k, v):
        self.props[k] = v

    def getProperty(self, k):
        return self.props.get(k, "")

    def setArt(self, a):
        self.art = a

    def addContextMenuItems(self, m):
        self.menu = m

    def getMusicInfoTag(self):
        return self.tag


import xbmcgui  # noqa: E402

xbmcgui.ListItem = FakeListItem


class FakeWindow:
    def __init__(self):
        self.props = {}

    def setProperty(self, key, value):
        self.props[key] = value

    def getProperty(self, key):
        return self.props.get(key, "")

    def clearProperty(self, key):
        self.props.pop(key, None)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Fresh DB/auth/profile, a running mock server and sane settings."""
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "abs.db"))
    monkeypatch.setattr(api, "AUTH_FILE", str(tmp_path / "auth.json"))
    monkeypatch.setattr(utils, "PROFILE", str(tmp_path))
    server = mock_abs.start()
    SETTINGS.clear()
    SETTINGS.update({
        "server_url": server.url + "/", "auth_method": 0, "api_key": "key-123", "verify_ssl": True,
        "sync_interval": 30, "resume_rewind": 3, "resume_mode": 0, "prefer_local": True,
        "download_path": str(tmp_path / "dl"), "delete_played": True, "page_size": 100,
        "newest_first": True,
    })
    window = FakeWindow()
    monkeypatch.setattr(utils, "home_window", lambda: window)
    notes = []
    monkeypatch.setattr(utils, "notify", lambda msg, error=False, time_ms=0: notes.append((msg, error)))
    clock = Clock()
    monkeypatch.setattr(service_core, "_now", clock)

    class E:
        pass

    e = E()
    e.server, e.state, e.window, e.notes, e.clock, e.tmp = server, server, window, notes, clock, tmp_path
    yield e
    server.server.shutdown()
    server.server.server_close()
