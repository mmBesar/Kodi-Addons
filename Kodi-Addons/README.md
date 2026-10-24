# mmbesar Kodi add-ons

A personal Kodi repository on GitHub. Add-ons live in `addons/`, the installable
repository is generated into `repo/`.

| Add-on | What it does |
| --- | --- |
| **Audiobookshelf Sync** (`plugin.audio.audiobookshelf.sync`) | Podcasts and audiobooks from your own [Audiobookshelf](https://github.com/advplyr/audiobookshelf) server, with two-way progress sync and offline downloads |
| **mmbesar Kodi Repository** (`repository.mmbesar`) | Lets Kodi install and update everything above |

## Install

Kodi 20 (Nexus) or newer.

1. Download the repository add-on to the device:
   `https://raw.githubusercontent.com/mmbesar/Kodi-Addons/main/repo/repository.mmbesar/repository.mmbesar-1.0.0.zip`
2. Kodi: *Settings, System, Add-ons, Unknown sources: On*.
3. *Add-ons, Install from zip file*, pick the downloaded file.
4. *Add-ons, Install from repository, mmbesar Kodi Repository, Music add-ons, Audiobookshelf Sync*.

Updates arrive whenever a new version is pushed here. To fetch one immediately: open the
repository add-on's page in Kodi and use *Check for updates*, or open the Audiobookshelf Sync
page and pick *Update*.

`raw.githubusercontent.com` does not provide folder listings, so it cannot be used as a
Kodi *file manager* source. If you prefer adding a source, enable GitHub Pages for this
repository (*Settings, Pages, Deploy from branch, main, / (root)*) and use
`https://mmbesar.github.io/Kodi-Addons/repo/` as the source URL; `tools/build_repo.py`
generates the `index.html` pages Kodi needs for that.

## Audiobookshelf Sync

* **Behind a reverse proxy**: enter `https://abs.example.com`, no IP or port. Sub-path installs
  (`https://example.com/audiobookshelf`) work too.
* **Sign-in**: an API key (*Audiobookshelf, Settings, API Keys*) or username and password.
  Password sign-in handles the 1-hour access tokens and rotating refresh tokens of ABS 2.26+.
* **Progress sync**: a background service reports position and listening time while you
  play, on pause, on seek and on stop. Multi-file audiobooks are tracked as one position.
* **Offline**: downloaded items play without the server; listening is queued and merged
  later. The server keeps whichever progress is newer, so phone and Kodi can be mixed freely.
* **Auto-download**: per podcast, keep the latest N unplayed episodes on the device; played
  episodes are removed from the device (setting).
* **Podcast tools**: latest episodes, continue listening, played markers, search, add a
  podcast, fetch episodes missing on the server (these three need an admin account).
* **Security**: no token ever appears in a stream, cover or log line. Streaming uses the
  server's public session route, covers need no authentication.
* **HTTPS that just works (local proxy)**: Kodi fetches audio and artwork with its own network
  stack (libcurl), which can fail on HTTPS setups, for example HTTP/2 servers such as Caddy,
  private CA certificates or an old CA bundle, even when Python's TLS is fine. The add-on's
  background service therefore runs a tiny proxy on `127.0.0.1` (port 18733). Kodi talks plain
  HTTP to it, and the add-on talks HTTPS to your server using your *Verify TLS* setting.
  Covers are also cached on disk, so browsing keeps its artwork offline. The proxy only serves
  two routes, listens on loopback only and never carries credentials. Setting:
  *Advanced, Load streams and artwork through the add-on's local proxy* (on by default).

### Playback speed (0.8x to 2.0x)

Kodi's music player has no speed control at all; only its video player does ("tempo",
pitch-corrected). So speed control is **opt-in**: *Settings, Playback and sync, Enable
playback speed control* makes the add-on play items through Kodi's video engine. The trade-off
is that Kodi shows its video screen instead of the music visualisation screen while playing.

* Pick a speed with the **Playback speed** entry in the add-on's main menu (works while
  something is playing; open the add-on from Kodi's menu). During playback the choice is applied
  at once and **remembered per podcast or book**; with nothing playing it sets the default.
* Presets: 0.8, 1.0, 1.2, 1.5, 1.8, 2.0. *Default playback speed* covers everything else.
* Optional keys: copy `extras/keymap-abs-speed.xml` to Kodi's `userdata/keymaps/` folder
  (`s` = speed picker, `[` and `]` = Kodi's own tempo down and up).
* **Kodi limits tempo to 1.5x by default.** Anything higher is silently ignored by Kodi, and the
  add-on tells you when that happens. To unlock 1.8x and 2.0x add this to
  `userdata/advancedsettings.xml` (create it if missing) and restart Kodi:

  ```xml
  <advancedsettings version="1.0">
    <video>
      <maxtempo>2.0</maxtempo>
    </video>
  </advancedsettings>
  ```

  Hardware that is slow at audio time-stretching may stutter at the top speeds.
* Tempo cannot be changed while paused; the add-on waits and applies it when you resume.

### If something does not play

Enable *Advanced, Verbose logging*, try again, then look in `kodi.log` for lines containing
`plugin.audio.audiobookshelf.sync`. `tools/live_check.py` tests the same client code from a
terminal and shows which step fails.

Settings that matter first: server address, sign-in, and *Test connection*.

## Layout

```
addons/<addon.id>/        add-on sources (folder name = add-on id)
repo/                     GENERATED: addons.xml, md5, zips, index pages
tools/build_repo.py       builds repo/ from addons/ (deterministic)
tools/gen_strings.py      strings.po + strings.py for the Audiobookshelf add-on
tools/gen_settings.py     settings.xml for the Audiobookshelf add-on (edit the spec, not the XML)
extras/                   optional Kodi keymap for the speed picker
tools/make_art.py         icons and fanart (Catppuccin Macchiato, Mauve)
tools/live_check.py       smoke test against a real Audiobookshelf server
tests/                    pytest suite with a mock Audiobookshelf server
```

### Adding another add-on

1. Create `addons/<new.addon.id>/addon.xml` plus code (the folder name must equal the id).
2. `python3 tools/build_repo.py`, commit, push. The new add-on appears in the repository.
3. To release an update, bump `version` in its `addon.xml` and push. Without a version bump
   Kodi will not offer the update.

The GitHub workflow rebuilds `repo/` on every push to `main`, so forgetting step 2 is harmless.

### Development

```
pip install Kodistubs requests pytest pyflakes Pillow
python3 -m pytest tests -q
python3 tools/live_check.py https://your.server USER PASS [--play]
```

The tests run the real add-on code against a mock server that mirrors behaviour verified in
the Audiobookshelf 2.37 sources (token rotation, sessions, last-write-wins local sync, Range
downloads). They do not replace a test on a real Kodi device.

## Credits and licence

GPL-3.0-or-later (see `LICENSE`). Unofficial; not affiliated with Audiobookshelf.
The add-on was written against the Audiobookshelf server and Android app sources
(advplyr, GPL-3.0). [Breezyslasher's Kodi addon](https://github.com/Breezyslasher/Kodi-Addons)
was studied for prior art; no code was copied from it.
