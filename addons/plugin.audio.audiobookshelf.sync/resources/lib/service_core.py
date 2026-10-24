# SPDX-License-Identifier: GPL-3.0-or-later
"""Background service.

A plugin invocation is short-lived, so everything that must outlive it lives
here: the Player subclass that reports progress, the offline-queue flusher, the
download worker and the auto-download scheduler.

Progress model
  session mode : server-side playback session, POST /session/<id>/sync every N
                 seconds and /close at the end (listening time is credited too).
  local mode   : downloaded file; a *local session* is sent instead. If the
                 server cannot be reached the session is queued and replayed.
Position is always tracked as an absolute offset in the whole item, so
multi-file audiobooks resume correctly.
"""
import os
import threading
import time

import xbmc

from . import api, downloads, store, sync, utils

PENDING_FINISH_GRACE = 5.0  # seconds to wait for the next playlist entry


def _now():
    """Monotonic clock (a hook so tests can drive time)."""
    return time.monotonic()


def _same(a, b):
    if a.startswith(("http://", "https://")) or b.startswith(("http://", "https://")):
        return a.split("|")[0] == b.split("|")[0]
    return os.path.normpath(a) == os.path.normpath(b)


class ABSPlayer(xbmc.Player):
    def __init__(self):
        super().__init__()
        self.lock = threading.RLock()
        self.ctx = None
        self.client = None
        self._clear()

    def _clear(self):
        self.track_idx = 0
        self.last_pos = 0.0
        self.unsynced = 0.0
        self.total = 0.0
        self.paused = False
        self.last_tick = _now()
        self.last_sync = _now()
        self.pending_finish = None

    # --------------------------------------------------------------- helpers
    def _match(self, playing):
        for i, track in enumerate(self.ctx["tracks"]):
            if _same(track["url"], playing):
                return i
        return None

    def _offset(self):
        return self.ctx["tracks"][self.track_idx]["offset"]

    def _read_position(self):
        try:
            return self._offset() + self.getTime()
        except RuntimeError:
            return None

    # -------------------------------------------------------------- callbacks
    def onAVStarted(self):
        with self.lock:
            try:
                playing = self.getPlayingFile()
            except RuntimeError:
                return
            if self.ctx:
                idx = self._match(playing)
                if idx is not None:  # next file of the same book/episode
                    self.track_idx = idx
                    self.pending_finish = None
                    self.paused = False
                    self.last_tick = _now()
                    return
                self._finish(ended=False)  # user moved on to something else
            ctx = utils.pop_ctx()
            if not ctx:
                return
            self.ctx = ctx
            idx = self._match(playing)
            if idx is None:
                self.ctx = None
                return
            self._clear()
            self.track_idx = idx
            self.last_pos = float(ctx.get("start_position", 0))
            self.client = api.ABSClient()
            utils.debug("tracking %s (%s) from %.0fs" % (ctx["item_id"], ctx["mode"], self.last_pos))
            start = ctx.get("start_in_track", 0)
            if idx == ctx.get("start_track") and start > 1:
                try:  # StartOffset is not honoured everywhere; make sure we resume
                    if abs(self.getTime() - start) > 3:
                        self.seekTime(start)
                except RuntimeError:
                    pass

    def onPlayBackPaused(self):
        with self.lock:
            if self.ctx:
                self._update_position()
                self.paused = True
                self._sync()

    def onPlayBackResumed(self):
        with self.lock:
            self.paused = False
            self.last_tick = _now()

    def onPlayBackSeek(self, time_ms, seek_offset):
        with self.lock:
            if self.ctx:
                self.last_pos = self._offset() + time_ms / 1000.0
                self._sync()

    def onPlayBackStopped(self):
        with self.lock:
            self._finish(ended=False)

    def onPlayBackError(self):
        with self.lock:
            self._finish(ended=False)

    def onPlayBackEnded(self):
        with self.lock:
            if not self.ctx:
                return
            if self.track_idx < len(self.ctx["tracks"]) - 1:
                self.pending_finish = _now()  # a following track may start
                return
            self._finish(ended=True)

    # ---------------------------------------------------------------- engine
    def _update_position(self):
        pos = self._read_position()
        if pos is not None:
            self.last_pos = pos

    def tick(self):
        """Called about once per second from the service loop."""
        with self.lock:
            if not self.ctx:
                return
            now = _now()
            dt = min(now - self.last_tick, 5.0)
            self.last_tick = now
            if self.pending_finish and now - self.pending_finish >= PENDING_FINISH_GRACE:
                return self._finish(ended=False)
            if self.paused or not self.isPlaying():
                return
            self.unsynced += dt
            self.total += dt
            self._update_position()
            if now - self.last_sync >= max(10, utils.s_int("sync_interval", 30)):
                self._sync()

    def _local_payload(self, position):
        return sync.build_local_session(self.ctx, position, self.total, self.ctx["started_at"])

    def _sync(self):
        ctx = self.ctx
        self.last_sync = _now()
        duration = ctx.get("duration", 0)
        store.save_progress(ctx["item_id"], ctx.get("episode_id"), self.last_pos, duration)
        try:
            if ctx["mode"] == "session":
                self.client.sync_session(ctx["session_id"], self.last_pos, round(self.unsynced, 2), duration)
                self.unsynced = 0.0
            else:
                if sync.try_send(self.client, self._local_payload(self.last_pos)):
                    self.unsynced = 0.0
        except api.ABSNotFound:
            # The server forgot the open session (restart/expiry): continue as a local session.
            utils.log("session %s unknown to server, continuing as local session" % ctx["session_id"][:8])
            ctx["mode"] = "local"
            sync.try_send(self.client, self._local_payload(self.last_pos))
        except api.ABSError as exc:
            utils.debug("progress sync deferred: %s" % exc)

    def _finish(self, ended, shutting_down=False):
        ctx = self.ctx
        if not ctx:
            return
        self.ctx = None
        self.pending_finish = None
        if ended and ctx.get("duration"):
            position = ctx["duration"]
        else:
            self._update_position_safe()
            position = self.last_pos
        finished = bool(ended)
        store.save_progress(ctx["item_id"], ctx.get("episode_id"), position, ctx.get("duration", 0), finished)
        try:
            if shutting_down:
                raise api.ABSConnectionError("shutting down")
            if ctx["mode"] == "session":
                self.client.close_session(ctx["session_id"], position, round(self.unsynced, 2), ctx.get("duration", 0))
            elif not sync.try_send(self.client, self._payload_for(ctx, position)):
                raise api.ABSConnectionError("deferred")
        except api.ABSNotFound:
            if not sync.try_send(self.client, self._payload_for(ctx, position)):
                store.queue_session(self._payload_for(ctx, position))
        except api.ABSError as exc:
            utils.debug("queued session %s (%s)" % (ctx["session_id"][:8], exc))
            store.queue_session(self._payload_for(ctx, position))
        if ended and ctx.get("episode_id") and not shutting_down:
            threading.Thread(target=_post_play_cleanup, daemon=True).start()

    def _update_position_safe(self):
        try:
            self._update_position()
        except Exception:
            pass

    def _payload_for(self, ctx, position):
        return sync.build_local_session(ctx, position, self.total, ctx["started_at"])

    def shutdown(self):
        with self.lock:
            if self.ctx:
                self._finish(ended=False, shutting_down=True)


def _post_play_cleanup():
    try:
        client = api.ABSClient()
        sync.flush_queue(client)
        downloads.cleanup_played(client)
    except Exception as exc:
        utils.debug("post-play cleanup skipped: %s" % exc)


class Service(xbmc.Monitor):
    def __init__(self):
        super().__init__()
        self.player = ABSPlayer()
        self.autosync_event = threading.Event()
        self._busy = {"flush": False, "auto": False}

    def onSettingsChanged(self):
        utils.reload_settings()
        self.autosync_event.set()

    def onNotification(self, sender, method, data):
        if sender == utils.ADDON_ID and method.endswith("autosync"):
            self.autosync_event.set()

    # background jobs -------------------------------------------------------
    def _spawn(self, name, fn):
        if self._busy[name]:
            return
        self._busy[name] = True

        def runner():
            try:
                fn()
            except Exception as exc:
                utils.debug("%s job failed: %s" % (name, exc))
            finally:
                self._busy[name] = False

        threading.Thread(target=runner, daemon=True).start()

    def _flush(self):
        client = api.ABSClient()
        if client.configured() and store.pending_count():
            sent, _left = sync.flush_queue(client)
            if sent:
                utils.debug("flushed %d queued session(s)" % sent)

    def _auto(self):
        client = api.ABSClient()
        if client.configured() and (store.list_auto() or utils.s_bool("delete_played", True)):
            queued = downloads.autosync(client)
            if queued:
                utils.debug("auto-download queued %d episode(s)" % queued)

    def download_loop(self):
        while not self.abortRequested():
            if store.queue_len() == 0:
                self.waitForAbort(3)
                continue
            result = downloads.process_next(self)
            if result == "offline":
                self.waitForAbort(60)
            elif result == "failed":
                self.waitForAbort(5)

    def run(self):
        utils.log("service started (%s)" % utils.ADDON_VERSION)
        threading.Thread(target=self.download_loop, daemon=True).start()
        started = _now()
        last_flush = last_auto = 0.0
        first_auto = True
        while not self.abortRequested():
            self.player.tick()
            now = _now()
            if now - started > 8 and now - last_flush > 60:
                last_flush = now
                if store.pending_count():
                    self._spawn("flush", self._flush)
            minutes = utils.s_int("auto_interval", 60)
            due = minutes > 0 and now - last_auto > minutes * 60 and now - started > 30
            if self.autosync_event.is_set() or due or (first_auto and minutes > 0 and now - started > 30):
                self.autosync_event.clear()
                first_auto = False
                last_auto = now
                self._spawn("auto", self._auto)
            if self.waitForAbort(1):
                break
        self.player.shutdown()
        utils.log("service stopped")
