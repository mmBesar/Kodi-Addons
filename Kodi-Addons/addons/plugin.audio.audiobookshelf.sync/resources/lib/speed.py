# SPDX-License-Identifier: GPL-3.0-or-later
"""Playback speed (Kodi "tempo": pitch-corrected time stretching).

Facts this relies on, verified in the Kodi sources:
  * Only VideoPlayer implements tempo; PAPlayer (the music player) does not.
    Kodi picks VideoPlayer when an item carries a *video* info tag, so with the
    "speed control" setting on, playback items are built that way (playback.py).
  * Player.SetTempo(playerid, tempo) sets an absolute value, but VideoPlayer
    silently ignores anything at or above `maxtempo` + 0.05 (default 1.55).
    The reply contains the tempo Kodi actually holds, which is how a capped
    request is detected. Raising the cap needs, in advancedsettings.xml:
        <advancedsettings><video><maxtempo>2.0</maxtempo></video></advancedsettings>
  * Tempo cannot be changed while paused and is unavailable for live streams.
"""
import json

import xbmc

from . import store, utils

PRESETS = [0.8, 1.0, 1.2, 1.5, 1.8, 2.0]
NOW_PROPERTY = "abs.sync.now"  # item id currently tracked by the service
REQUEST_PROPERTY = utils.SPEED_PROPERTY  # plugin -> service: "apply this speed"


def enabled():
    return utils.s_bool("speed_engine", False)


def default_speed():
    return max(0.5, min(2.0, utils.s_int("default_speed", 100) / 100.0))


def target_for(item_id):
    """Remembered speed of this show/book, else the default."""
    return store.get_speed(item_id) or default_speed()


def _rpc(method, params):
    request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    try:
        return json.loads(xbmc.executeJSONRPC(request))
    except (ValueError, TypeError):
        return {}


def _player_id():
    for player in _rpc("Player.GetActivePlayers", {}).get("result") or []:
        if player.get("type") in ("video", "audio"):
            return player.get("playerid")
    return None


def apply(tempo):
    """Ask Kodi for `tempo`. Returns the tempo Kodi reports, or None when it
    cannot be set right now (no player yet, paused, not supported)."""
    player_id = _player_id()
    if player_id is None:
        return None
    reply = _rpc("Player.SetTempo", {"playerid": player_id, "tempo": float(tempo)})
    result = reply.get("result")
    if "error" in reply or result is None:
        return None
    value = result.get("tempo") if isinstance(result, dict) else result
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def current_item():
    return utils.home_window().getProperty(NOW_PROPERTY)
