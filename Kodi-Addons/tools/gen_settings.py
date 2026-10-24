#!/usr/bin/env python3
"""Generate resources/settings.xml (Kodi 20+ format, version 1) for Audiobookshelf Sync.

Every <setting> must sit inside a <group> or Kodi silently hides it, which is the
main reason this is generated from a spec instead of hand-edited.
"""
import os

ADDON = "plugin.audio.audiobookshelf.sync"
OUT = os.path.join(os.path.dirname(__file__), "..", "addons", ADDON, "resources", "settings.xml")
ind = lambda n: "  " * n


def _dep(kind, setting, value, op=None):
    opattr = ' operator="%s"' % op if op else ""
    return ('\n%s<dependencies>\n%s<dependency type="%s" setting="%s"%s>%s</dependency>\n%s</dependencies>'
            % (ind(5), ind(6), kind, setting, opattr, value, ind(5)))


def s_string(id, label, default="", hidden=False, visible=None):
    dep = _dep("visible", visible[0], visible[1], "is") if visible else ""
    hid = "\n%s<hidden>true</hidden>" % ind(6) if hidden else ""
    return f'''{ind(4)}<setting id="{id}" type="string" label="{label}" help="">
{ind(5)}<level>0</level>
{ind(5)}<default>{default}</default>
{ind(5)}<constraints><allowempty>true</allowempty></constraints>{dep}
{ind(5)}<control type="edit" format="string">
{ind(6)}<heading>{label}</heading>{hid}
{ind(5)}</control>
{ind(4)}</setting>'''


def s_bool(id, label, default, enable=None):
    dep = _dep("enable", enable, "true") if enable else ""
    return f'''{ind(4)}<setting id="{id}" type="boolean" label="{label}" help="">
{ind(5)}<level>0</level>
{ind(5)}<default>{str(default).lower()}</default>{dep}
{ind(5)}<control type="toggle"/>
{ind(4)}</setting>'''


def s_options(id, label, default, opts):
    o = "".join(f'\n{ind(7)}<option label="{l}">{v}</option>' for v, l in opts)
    return f'''{ind(4)}<setting id="{id}" type="integer" label="{label}" help="">
{ind(5)}<level>0</level>
{ind(5)}<default>{default}</default>
{ind(5)}<constraints>
{ind(6)}<options>{o}
{ind(6)}</options>
{ind(5)}</constraints>
{ind(5)}<control type="spinner" format="string"/>
{ind(4)}</setting>'''


def s_slider(id, label, default, lo, hi, step=1, fmt="integer", enable=None):
    dep = _dep("enable", enable, "true") if enable else ""
    return f'''{ind(4)}<setting id="{id}" type="integer" label="{label}" help="">
{ind(5)}<level>0</level>
{ind(5)}<default>{default}</default>
{ind(5)}<constraints>
{ind(6)}<minimum>{lo}</minimum>
{ind(6)}<step>{step}</step>
{ind(6)}<maximum>{hi}</maximum>
{ind(5)}</constraints>{dep}
{ind(5)}<control type="slider" format="{fmt}">
{ind(6)}<popup>false</popup>
{ind(5)}</control>
{ind(4)}</setting>'''


def s_action(id, label, action):
    return f'''{ind(4)}<setting id="{id}" type="action" label="{label}" help="">
{ind(5)}<level>0</level>
{ind(5)}<data>RunPlugin(plugin://{ADDON}/?action={action})</data>
{ind(5)}<constraints><allowempty>true</allowempty></constraints>
{ind(5)}<control type="button" format="action">
{ind(6)}<close>true</close>
{ind(5)}</control>
{ind(4)}</setting>'''


def s_path(id, label):
    return f'''{ind(4)}<setting id="{id}" type="path" label="{label}" help="">
{ind(5)}<level>0</level>
{ind(5)}<default></default>
{ind(5)}<constraints>
{ind(6)}<allowempty>true</allowempty>
{ind(6)}<writable>true</writable>
{ind(5)}</constraints>
{ind(5)}<control type="button" format="path">
{ind(6)}<heading>{label}</heading>
{ind(5)}</control>
{ind(4)}</setting>'''


def group(i, label, *settings):
    return f'{ind(3)}<group id="{i}" label="{label}">\n' + "\n".join(settings) + f'\n{ind(3)}</group>'


def category(id, label, *groups):
    return f'{ind(2)}<category id="{id}" label="{label}" help="">\n' + "\n".join(groups) + f'\n{ind(2)}</category>'


CATS = [
    category("connection", 30010,
             group(1, 30020, s_string("server_url", 30030), s_bool("verify_ssl", 30039, True)),
             group(2, 30021,
                   s_options("auth_method", 30032, 0, [(0, 30033), (1, 30034)]),
                   s_string("api_key", 30035, hidden=True, visible=("auth_method", 0)),
                   s_string("username", 30037, visible=("auth_method", 1)),
                   s_string("password", 30038, hidden=True, visible=("auth_method", 1)),
                   s_action("test_connection", 30041, "test_connection"))),
    category("library", 30011,
             group(1, 30022,
                   s_slider("page_size", 30042, 100, 50, 300, 25),
                   s_bool("newest_first", 30043, True),
                   s_bool("hide_played", 30044, False))),
    category("playback", 30012,
             group(1, 30023,
                   s_options("resume_mode", 30045, 0, [(0, 30046), (1, 30047)]),
                   s_slider("resume_rewind", 30048, 3, 0, 30, 1)),
             group(2, 30024,
                   s_options("sync_interval", 30049, 30, [(15, 30050), (30, 30051), (60, 30052), (120, 30053)]),
                   s_action("sync_now", 30066, "sync_now")),
             group(3, 30028,
                   s_bool("speed_engine", 30070, False),
                   s_slider("default_speed", 30071, 100, 50, 200, 5, fmt="percentage", enable="speed_engine"))),
    category("downloads", 30013,
             group(1, 30025,
                   s_path("download_path", 30055),
                   s_bool("prefer_local", 30054, True),
                   s_bool("delete_played", 30057, True)),
             group(2, 30026,
                   s_options("auto_interval", 30058, 60, [(0, 30059), (30, 30060), (60, 30061), (180, 30062), (360, 30063)]),
                   s_slider("auto_keep", 30064, 3, 1, 20, 1))),
    category("advanced", 30014,
             group(1, 30029, s_bool("use_proxy", 30072, True)),
             group(2, 30027, s_bool("debug_logging", 30065, False))),
]

XML = ('<?xml version="1.0" encoding="utf-8" standalone="yes"?>\n<settings version="1">\n  <section id="%s">\n%s\n  </section>\n</settings>\n'
       % (ADDON, "\n".join(CATS)))

if __name__ == "__main__":
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(XML)
    print("wrote settings.xml")
