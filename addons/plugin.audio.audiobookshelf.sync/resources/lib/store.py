# SPDX-License-Identifier: GPL-3.0-or-later
"""Local persistence (SQLite, WAL) shared by the plugin and the service."""
import json
import os
import sqlite3
import time

from . import utils

DB_PATH = os.path.join(utils.PROFILE, "abs_sync.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS downloads(
    key TEXT PRIMARY KEY,
    item_id TEXT NOT NULL,
    episode_id TEXT,
    media_type TEXT,
    title TEXT,
    parent_title TEXT,
    author TEXT,
    description TEXT,
    duration REAL DEFAULT 0,
    published_at INTEGER DEFAULT 0,
    cover TEXT,
    size INTEGER DEFAULT 0,
    added_at INTEGER,
    tracks TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dl_queue(
    key TEXT PRIMARY KEY,
    item_id TEXT NOT NULL,
    episode_id TEXT,
    queued_at INTEGER,
    attempts INTEGER DEFAULT 0,
    last_error TEXT
);
CREATE TABLE IF NOT EXISTS progress(
    key TEXT PRIMARY KEY,
    item_id TEXT NOT NULL,
    episode_id TEXT,
    position REAL DEFAULT 0,
    duration REAL DEFAULT 0,
    is_finished INTEGER DEFAULT 0,
    updated_at INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sync_queue(
    id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    created_at INTEGER,
    attempts INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS auto_dl(
    item_id TEXT PRIMARY KEY,
    title TEXT,
    keep INTEGER DEFAULT 3
);
"""


def make_key(item_id, episode_id=None):
    return "%s:%s" % (item_id, episode_id) if episode_id else item_id


def _connect():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.DatabaseError:
        pass
    conn.executescript(SCHEMA)
    return conn


def _run(sql, params=(), many=False, fetch=None):
    conn = _connect()
    try:
        cur = conn.executemany(sql, params) if many else conn.execute(sql, params)
        result = None
        if fetch == "one":
            row = cur.fetchone()
            result = dict(row) if row else None
        elif fetch == "all":
            result = [dict(r) for r in cur.fetchall()]
        conn.commit()
        return result
    finally:
        conn.close()


# --------------------------------------------------------------------------
# Downloads
# --------------------------------------------------------------------------
def add_download(rec):
    rec = dict(rec)
    rec["tracks"] = json.dumps(rec["tracks"])
    rec.setdefault("added_at", int(time.time()))
    cols = ["key", "item_id", "episode_id", "media_type", "title", "parent_title",
            "author", "description", "duration", "published_at", "cover", "size",
            "added_at", "tracks"]
    _run("INSERT OR REPLACE INTO downloads(%s) VALUES(%s)"
         % (",".join(cols), ",".join("?" * len(cols))),
         [rec.get(c) for c in cols])


def _decode(row):
    if row:
        row["tracks"] = json.loads(row["tracks"])
    return row


def get_download(key):
    return _decode(_run("SELECT * FROM downloads WHERE key=?", (key,), fetch="one"))


def list_downloads():
    rows = _run("SELECT * FROM downloads ORDER BY parent_title COLLATE NOCASE, "
                "published_at DESC, title COLLATE NOCASE", fetch="all")
    return [_decode(r) for r in rows]


def remove_download(key):
    _run("DELETE FROM downloads WHERE key=?", (key,))


def has_downloads():
    row = _run("SELECT COUNT(*) AS n FROM downloads", fetch="one")
    return bool(row and row["n"])


# --------------------------------------------------------------------------
# Download queue
# --------------------------------------------------------------------------
def queue_download(item_id, episode_id=None):
    key = make_key(item_id, episode_id)
    _run("INSERT OR IGNORE INTO dl_queue(key,item_id,episode_id,queued_at) VALUES(?,?,?,?)",
         (key, item_id, episode_id, int(time.time())))


def next_queued():
    return _run("SELECT * FROM dl_queue ORDER BY attempts, queued_at LIMIT 1", fetch="one")


def queue_len():
    row = _run("SELECT COUNT(*) AS n FROM dl_queue", fetch="one")
    return row["n"] if row else 0


def drop_queued(key):
    _run("DELETE FROM dl_queue WHERE key=?", (key,))


def fail_queued(key, error):
    _run("UPDATE dl_queue SET attempts=attempts+1, last_error=? WHERE key=?", (error[:200], key))


def is_queued(key):
    return _run("SELECT 1 AS x FROM dl_queue WHERE key=?", (key,), fetch="one") is not None


# --------------------------------------------------------------------------
# Local progress (for offline resume and conflict resolution)
# --------------------------------------------------------------------------
def save_progress(item_id, episode_id, position, duration, finished=False, updated_at=None):
    _run("INSERT OR REPLACE INTO progress(key,item_id,episode_id,position,duration,"
         "is_finished,updated_at) VALUES(?,?,?,?,?,?,?)",
         (make_key(item_id, episode_id), item_id, episode_id, position, duration,
          1 if finished else 0, updated_at or utils.now_ms()))


def get_progress(item_id, episode_id=None):
    return _run("SELECT * FROM progress WHERE key=?", (make_key(item_id, episode_id),), fetch="one")


# --------------------------------------------------------------------------
# Sync queue (local listening sessions waiting to reach the server)
# --------------------------------------------------------------------------
def queue_session(payload):
    _run("INSERT OR REPLACE INTO sync_queue(id,payload,created_at) VALUES(?,?,?)",
         (payload["id"], json.dumps(payload), int(time.time())))


def pending_sessions():
    rows = _run("SELECT * FROM sync_queue ORDER BY created_at", fetch="all")
    for row in rows:
        row["payload"] = json.loads(row["payload"])
    return rows


def drop_session(session_id):
    _run("DELETE FROM sync_queue WHERE id=?", (session_id,))


def bump_session(session_id):
    _run("UPDATE sync_queue SET attempts=attempts+1 WHERE id=?", (session_id,))


def pending_count():
    row = _run("SELECT COUNT(*) AS n FROM sync_queue", fetch="one")
    return row["n"] if row else 0


# --------------------------------------------------------------------------
# Auto-download rules
# --------------------------------------------------------------------------
def set_auto(item_id, title, keep):
    _run("INSERT OR REPLACE INTO auto_dl(item_id,title,keep) VALUES(?,?,?)", (item_id, title, keep))


def clear_auto(item_id):
    _run("DELETE FROM auto_dl WHERE item_id=?", (item_id,))


def get_auto(item_id):
    return _run("SELECT * FROM auto_dl WHERE item_id=?", (item_id,), fetch="one")


def list_auto():
    return _run("SELECT * FROM auto_dl", fetch="all")


def downloaded_keys():
    return {r["key"] for r in _run("SELECT key FROM downloads", fetch="all")}


def queued_keys():
    return {r["key"] for r in _run("SELECT key FROM dl_queue", fetch="all")}


def local_progress_map():
    """Local progress shaped like the server's mediaProgress entries."""
    out = {}
    for r in _run("SELECT * FROM progress", fetch="all"):
        out[r["key"]] = {"currentTime": r["position"], "duration": r["duration"],
                         "isFinished": bool(r["is_finished"]), "lastUpdate": r["updated_at"]}
    return out
