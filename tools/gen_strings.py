#!/usr/bin/env python3
"""Single source of truth for UI strings.

Generates, for the Audiobookshelf Sync addon:
  resources/language/resource.language.en_gb/strings.po
  resources/lib/strings.py   (constants used by the code)

Usage: python3 tools/gen_strings.py
"""
import os

ADDON = os.path.join(os.path.dirname(__file__), "..", "addons", "plugin.audio.audiobookshelf.sync")

STRINGS = [
    # --- settings: categories / groups -------------------------------------
    ("CAT_CONNECTION", 30010, "Connection"),
    ("CAT_BROWSING", 30011, "Library"),
    ("CAT_PLAYBACK", 30012, "Playback and sync"),
    ("CAT_DOWNLOADS", 30013, "Downloads"),
    ("CAT_ADVANCED", 30014, "Advanced"),
    ("GRP_SERVER", 30020, "Server"),
    ("GRP_ACCOUNT", 30021, "Account"),
    ("GRP_BROWSING", 30022, "Browsing"),
    ("GRP_RESUME", 30023, "Resume"),
    ("GRP_SYNC", 30024, "Progress sync"),
    ("GRP_OFFLINE", 30025, "Offline files"),
    ("GRP_AUTO", 30026, "Auto-download"),
    ("GRP_DIAG", 30027, "Diagnostics"),
    # --- settings: labels ----------------------------------------------------
    ("SET_SERVER_URL", 30030, "Server address (for example https://abs.example.com)"),
    ("SET_AUTH_METHOD", 30032, "Sign-in method"),
    ("OPT_API_KEY", 30033, "API key (recommended)"),
    ("OPT_PASSWORD", 30034, "Username and password"),
    ("SET_API_KEY", 30035, "API key"),
    ("SET_USERNAME", 30037, "Username"),
    ("SET_PASSWORD", 30038, "Password"),
    ("SET_VERIFY_TLS", 30039, "Verify TLS certificate"),
    ("SET_TEST", 30041, "Test connection"),
    ("SET_PAGE_SIZE", 30042, "Items per page"),
    ("SET_NEWEST_FIRST", 30043, "Show newest episodes first"),
    ("SET_HIDE_PLAYED", 30044, "Hide played episodes"),
    ("SET_RESUME_MODE", 30045, "When an item has progress"),
    ("OPT_RESUME_AUTO", 30046, "Resume automatically"),
    ("OPT_RESUME_ASK", 30047, "Ask me each time"),
    ("SET_REWIND", 30048, "Rewind on resume (seconds)"),
    ("SET_SYNC_INTERVAL", 30049, "Send progress to the server"),
    ("OPT_SYNC_15", 30050, "Every 15 seconds"),
    ("OPT_SYNC_30", 30051, "Every 30 seconds"),
    ("OPT_SYNC_60", 30052, "Every minute"),
    ("OPT_SYNC_120", 30053, "Every 2 minutes"),
    ("SET_PREFER_LOCAL", 30054, "Prefer the downloaded copy when available"),
    ("SET_DOWNLOAD_PATH", 30055, "Download folder (empty = addon data folder)"),
    ("SET_DELETE_PLAYED", 30057, "Delete downloaded episodes once played"),
    ("SET_AUTO_INTERVAL", 30058, "Check subscribed podcasts"),
    ("OPT_AUTO_OFF", 30059, "Never"),
    ("OPT_AUTO_30", 30060, "Every 30 minutes"),
    ("OPT_AUTO_60", 30061, "Every hour"),
    ("OPT_AUTO_180", 30062, "Every 3 hours"),
    ("OPT_AUTO_360", 30063, "Every 6 hours"),
    ("SET_AUTO_KEEP", 30064, "Default number of unplayed episodes to keep offline"),
    ("SET_DEBUG", 30065, "Verbose logging"),
    ("SET_SYNC_NOW", 30066, "Sync pending listening now"),
    # --- menus -----------------------------------------------------------------
    ("M_CONTINUE", 30100, "Continue listening"),
    ("M_LATEST", 30101, "Latest episodes"),
    ("M_PODCASTS", 30102, "Podcasts"),
    ("M_BOOKS", 30103, "Audiobooks"),
    ("M_SEARCH", 30104, "Search"),
    ("M_DOWNLOADS", 30105, "Downloads"),
    ("M_ADD_PODCAST", 30106, "Add a podcast to the server"),
    ("M_SYNC_NOW", 30107, "Sync now"),
    ("M_SETTINGS", 30108, "Settings"),
    ("M_NEXT_PAGE", 30109, "Next page"),
    ("M_CHAPTERS", 30110, "Chapters"),
    ("M_PODCAST_OPTIONS", 30180, "Podcast options..."),
    ("M_PLAY_FROM_START", 30181, "Play from the beginning"),
    # --- context menu ----------------------------------------------------------
    ("C_PLAY", 30111, "Play"),
    ("C_MARK_PLAYED", 30112, "Mark as played"),
    ("C_MARK_UNPLAYED", 30113, "Mark as not played"),
    ("C_DOWNLOAD", 30114, "Download for offline"),
    ("C_REMOVE_DL", 30115, "Remove download"),
    ("C_GOTO_PODCAST", 30116, "Go to podcast"),
    ("C_AUTO_ON", 30117, "Auto-download new episodes"),
    ("C_AUTO_OFF", 30118, "Stop auto-downloading"),
    ("C_FIND_NEW", 30119, "Find episodes not on the server yet"),
    ("C_CHECK_NEW", 30120, "Ask the server to check for new episodes"),
    ("C_REMOVE_ALL_DL", 30121, "Remove all downloads of this podcast"),
    ("C_DOWNLOAD_ALL_UNPLAYED", 30122, "Download all unplayed episodes"),
    # --- status labels -----------------------------------------------------------
    ("ST_PLAYED", 30130, "Played"),
    ("ST_LEFT", 30131, "%s left"),
    ("ST_DOWNLOADED", 30132, "Downloaded"),
    ("ST_QUEUED", 30133, "Queued"),
    ("ST_NEW", 30134, "New"),
    # --- dialogs / notifications ---------------------------------------------------
    ("D_SEARCH_HEADING", 30140, "Search your libraries"),
    ("D_NO_RESULTS", 30141, "No results"),
    ("D_EMPTY", 30142, "Nothing here yet"),
    ("D_RESUME_FROM", 30143, "Resume from %s"),
    ("D_FROM_START", 30144, "Start from the beginning"),
    ("D_OFFLINE", 30145, "Cannot reach the server"),
    ("D_OFFLINE_DL", 30146, "Cannot reach the server. Showing downloads only."),
    ("D_AUTH_FAILED", 30147, "Sign-in failed. Check the settings."),
    ("D_FORBIDDEN", 30148, "This action needs an admin account on the server."),
    ("D_SETUP", 30149, "Enter your server address and credentials first."),
    ("D_TEST_OK", 30150, "Connected as %s"),
    ("D_TEST_FAIL", 30151, "Connection failed: %s"),
    ("D_DL_START", 30152, "Downloading: %s"),
    ("D_DL_DONE", 30153, "Downloaded: %s"),
    ("D_DL_FAIL", 30154, "Download failed: %s"),
    ("D_DL_SPACE", 30155, "Not enough free disk space"),
    ("D_DL_QUEUED", 30156, "Queued %d download(s)"),
    ("D_DL_LOCAL_ONLY", 30157, "The download folder must be a local path"),
    ("D_DL_REMOVED", 30158, "Download removed"),
    ("D_DL_CONFIRM", 30159, "Remove this download from the device?"),
    ("D_DL_ALL_CONFIRM", 30160, "Remove every downloaded item of this podcast?"),
    ("D_AUTO_ON", 30161, "Auto-download on: keeping %d unplayed episodes"),
    ("D_AUTO_OFF", 30162, "Auto-download off"),
    ("D_AUTO_ASK", 30163, "How many unplayed episodes should be kept offline?"),
    ("D_SYNCED", 30164, "Synced %d listening session(s)"),
    ("D_NOTHING_TO_SYNC", 30165, "Nothing waiting to sync"),
    ("D_SYNC_PENDING", 30166, "%d session(s) will sync when the server is reachable"),
    ("D_PODCAST_ADDED", 30167, "Podcast added to the server"),
    ("D_PICK_PODCAST", 30168, "Choose a podcast to add"),
    ("D_PICK_LIBRARY", 30169, "Choose the podcast library"),
    ("D_PICK_EPISODES", 30170, "Choose episodes to fetch on the server"),
    ("D_SERVER_DL_QUEUED", 30171, "The server is downloading %d episode(s)"),
    ("D_NO_NEW", 30172, "No new episodes"),
    ("D_NEW_FOUND", 30173, "Server found %d new episode(s)"),
    ("D_UNAVAILABLE", 30174, "This item is not available"),
    ("D_NO_PODCAST_LIB", 30175, "No podcast library found on the server"),
    ("D_ALREADY_EXISTS", 30176, "That podcast is already on the server"),
    ("D_PLAYING_LOCAL", 30177, "Playing the downloaded copy"),
    ("D_SEARCH_PODCASTS", 30178, "Search for a podcast to add"),
    ("D_MARKED", 30179, "Updated"),
]

HEADER = '''# Kodi Media Center language file
# Addon Name: Audiobookshelf Sync
# Addon id: plugin.audio.audiobookshelf.sync
# Addon Provider: mmbesar
msgid ""
msgstr ""
"Project-Id-Version: plugin.audio.audiobookshelf.sync\\n"
"Report-Msgid-Bugs-To: https://github.com/mmbesar/Kodi-Addons/issues\\n"
"POT-Creation-Date: 2026-10-22 00:00+0000\\n"
"Last-Translator: mmbesar\\n"
"Language-Team: English (UK)\\n"
"MIME-Version: 1.0\\n"
"Content-Type: text/plain; charset=UTF-8\\n"
"Content-Transfer-Encoding: 8bit\\n"
"Language: en_GB\\n"
"Plural-Forms: nplurals=2; plural=(n != 1);\\n"

'''


def main():
    ids = [s[1] for s in STRINGS]
    names = [s[0] for s in STRINGS]
    assert len(ids) == len(set(ids)), "duplicate string id"
    assert len(names) == len(set(names)), "duplicate string name"
    po = HEADER
    for name, sid, text in STRINGS:
        po += 'msgctxt "#%d"\nmsgid "%s"\nmsgstr ""\n\n' % (sid, text.replace('"', '\\"'))
    po_path = os.path.join(ADDON, "resources", "language", "resource.language.en_gb", "strings.po")
    os.makedirs(os.path.dirname(po_path), exist_ok=True)
    with open(po_path, "w", encoding="utf-8") as fh:
        fh.write(po)
    py = "# SPDX-License-Identifier: GPL-3.0-or-later\n# GENERATED by tools/gen_strings.py - do not edit.\n"
    py += '"""String ids for resources/language/*/strings.po."""\n\n\nclass S:\n'
    for name, sid, _ in STRINGS:
        py += "    %s = %d\n" % (name, sid)
    with open(os.path.join(ADDON, "resources", "lib", "strings.py"), "w", encoding="utf-8") as fh:
        fh.write(py)
    print("wrote %d strings" % len(STRINGS))


if __name__ == "__main__":
    main()
