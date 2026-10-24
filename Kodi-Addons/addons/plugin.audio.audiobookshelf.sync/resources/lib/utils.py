# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared helpers: settings, logging, localisation, formatting."""
import html
import json
import os
import re
import uuid
from urllib.parse import urlencode

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

ADDON_ID = "plugin.audio.audiobookshelf.sync"
_ADDON = xbmcaddon.Addon(ADDON_ID)
ADDON_NAME = _ADDON.getAddonInfo("name")
ADDON_VERSION = _ADDON.getAddonInfo("version")
ADDON_PATH = xbmcvfs.translatePath(_ADDON.getAddonInfo("path"))
PROFILE = xbmcvfs.translatePath(_ADDON.getAddonInfo("profile"))
FANART = os.path.join(ADDON_PATH, "resources", "fanart.jpg")
ICON = os.path.join(ADDON_PATH, "resources", "icon.png")
BASE_URL = "plugin://" + ADDON_ID + "/"
HOME_WINDOW_ID = 10000
CTX_PROPERTY = "abs.sync.ctx"
PROXY_PROPERTY = "abs.sync.proxy"
SPEED_PROPERTY = "abs.sync.speed"

try:
    os.makedirs(PROFILE, exist_ok=True)
except OSError:
    pass


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------
def reload_settings():
    """Long-running processes (the service) must call this on settings change."""
    global _ADDON
    _ADDON = xbmcaddon.Addon(ADDON_ID)


def s_str(key, default=""):
    try:
        value = _ADDON.getSettingString(key)
    except Exception:
        value = _ADDON.getSetting(key)
    return value if value not in (None, "") else default


def s_bool(key, default=False):
    try:
        return _ADDON.getSettingBool(key)
    except Exception:
        raw = _ADDON.getSetting(key)
        return default if raw == "" else raw.lower() == "true"


def s_int(key, default=0):
    try:
        return _ADDON.getSettingInt(key)
    except Exception:
        try:
            return int(_ADDON.getSetting(key))
        except (TypeError, ValueError):
            return default


def set_setting(key, value):
    _ADDON.setSetting(key, value)


def t(string_id):
    return _ADDON.getLocalizedString(string_id)


def open_settings():
    _ADDON.openSettings()


# --------------------------------------------------------------------------
# Logging / UI
# --------------------------------------------------------------------------
def log(message, level=xbmc.LOGINFO):
    xbmc.log("[%s] %s" % (ADDON_ID, message), level)


def debug(message):
    if s_bool("debug_logging", False):
        log(message, xbmc.LOGINFO)
    else:
        xbmc.log("[%s] %s" % (ADDON_ID, message), xbmc.LOGDEBUG)


def notify(message, error=False, time_ms=4000):
    icon = xbmcgui.NOTIFICATION_ERROR if error else xbmcgui.NOTIFICATION_INFO
    xbmcgui.Dialog().notification(ADDON_NAME, message, icon, time_ms)


def plugin_url(**params):
    clean = {k: v for k, v in params.items() if v is not None}
    return BASE_URL + "?" + urlencode(clean)


def home_window():
    return xbmcgui.Window(HOME_WINDOW_ID)


def proxy_base():
    """Base URL of the service's loopback proxy, or '' when unavailable/disabled."""
    if not s_bool("use_proxy", True):
        return ""
    port = home_window().getProperty(PROXY_PROPERTY)
    return "http://127.0.0.1:%s" % port if port.isdigit() else ""


def set_ctx(ctx):
    home_window().setProperty(CTX_PROPERTY, json.dumps(ctx))


def pop_ctx():
    win = home_window()
    raw = win.getProperty(CTX_PROPERTY)
    if raw:
        win.clearProperty(CTX_PROPERTY)
        try:
            return json.loads(raw)
        except ValueError:
            return None
    return None


# --------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------
def device_id():
    """Stable per-install id so the server groups this Kodi as one device."""
    path = os.path.join(PROFILE, "device_id")
    try:
        with open(path, "r") as fh:
            value = fh.read().strip()
            if value:
                return value
    except OSError:
        pass
    value = str(uuid.uuid4())
    try:
        with open(path, "w") as fh:
            fh.write(value)
    except OSError:
        pass
    return value


def device_info():
    return {
        "deviceId": device_id(),
        "clientName": "Kodi",
        "clientVersion": ADDON_VERSION,
        "manufacturer": "Kodi",
        "model": ADDON_NAME,
    }


# --------------------------------------------------------------------------
# Formatting
# --------------------------------------------------------------------------
_TAG = re.compile(r"<[^>]+>")
_BR = re.compile(r"<\s*br\s*/?\s*>|</\s*(p|div|li)\s*>", re.I)
_WS = re.compile(r"[ \t\r\f\v]+")


def strip_html(text):
    if not text:
        return ""
    text = _BR.sub("\n", text)
    text = _TAG.sub("", text)
    text = html.unescape(text)
    text = _WS.sub(" ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def fmt_duration(seconds):
    seconds = int(max(0, seconds or 0))
    hours, rem = divmod(seconds, 3600)
    minutes = rem // 60
    if hours:
        return "%dh %02dm" % (hours, minutes)
    return "%dm" % max(1, minutes) if seconds else "0m"


def safe_name(text, limit=90):
    text = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", text or "").strip(" .")
    text = re.sub(r"\s+", " ", text)
    return (text[:limit].rstrip(" .")) or "untitled"


def to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def now_ms():
    import time
    return int(time.time() * 1000)
