# SPDX-License-Identifier: GPL-3.0-or-later
"""Local listening sessions and the offline sync queue.

The server merges a local session with last-write-wins on `updatedAt`
(PlaybackSessionManager.syncLocalSession): progress is only overwritten when
the session is newer than what the server already holds, so listening offline
on Kodi and then on a phone resolves sensibly in either order.
"""
import time

from . import api, store, utils

# After this many failed attempts for a *permanent* error the entry is dropped.
MAX_PERMANENT_FAILURES = 5


def build_local_session(ctx, position, time_listening, started_at_ms, updated_at_ms=None):
    """Payload for POST /api/session/local, mirroring the official app's shape."""
    updated = updated_at_ms or utils.now_ms()
    local = time.localtime(updated / 1000.0)
    return {
        "id": ctx["session_id"],
        "libraryItemId": ctx["item_id"],
        "episodeId": ctx.get("episode_id"),
        "mediaType": ctx.get("media_type", "book"),
        "mediaMetadata": {},
        "chapters": [],
        "displayTitle": ctx.get("title", ""),
        "displayAuthor": ctx.get("author", ""),
        "coverPath": None,
        "duration": ctx.get("duration", 0),
        "playMethod": 3,  # PlayMethod.LOCAL
        "mediaPlayer": "Kodi",
        "deviceInfo": utils.device_info(),
        "date": time.strftime("%Y-%m-%d", local),
        "dayOfWeek": time.strftime("%A", local),
        "timeListening": int(round(time_listening)),
        "startTime": float(ctx.get("start_position", 0)),
        "currentTime": float(position),
        "startedAt": int(started_at_ms),
        "updatedAt": int(updated),
    }


def try_send(client, payload):
    """Send one local session. Returns True when the server accepted it."""
    try:
        client.sync_local_session(payload)
        return True
    except api.ABSConnectionError:
        return False
    except api.ABSNotFound:
        # media no longer exists on the server; nothing sensible to retry
        utils.log("dropping session for missing media %s" % payload.get("libraryItemId"))
        return True
    except api.ABSError as exc:
        utils.log("session sync rejected: %s" % exc)
        return False


def flush_queue(client=None):
    """Push every queued session. Returns (sent, remaining)."""
    pending = store.pending_sessions()
    if not pending:
        return 0, 0
    client = client or api.ABSClient()
    if not client.configured():
        return 0, len(pending)
    sent = 0
    for row in pending:
        payload = row["payload"]
        try:
            client.sync_local_session(payload)
        except api.ABSConnectionError:
            break  # offline: keep everything, try later
        except api.ABSNotFound:
            store.drop_session(row["id"])
            continue
        except api.ABSAuthError:
            break
        except api.ABSError as exc:
            store.bump_session(row["id"])
            utils.log("queued session %s rejected: %s" % (row["id"][:8], exc))
            if row["attempts"] + 1 >= MAX_PERMANENT_FAILURES:
                store.drop_session(row["id"])
            continue
        store.drop_session(row["id"])
        sent += 1
    return sent, store.pending_count()
