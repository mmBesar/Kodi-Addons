#!/usr/bin/env python3
"""Build the Kodi repository in ./repo from the add-on sources in ./addons.

  python3 tools/build_repo.py          build / refresh ./repo
  python3 tools/build_repo.py --check  exit 1 if ./repo is out of date

Output (everything is deterministic, so unchanged add-ons produce no git diff):
  repo/addons.xml, repo/addons.xml.md5
  repo/<id>/<id>-<version>.zip, icon.png, fanart.jpg, changelog-<version>.txt
  repo/index.html and repo/<id>/index.html   (browsable by Kodi's file manager
                                              when served by GitHub Pages)
"""
import hashlib
import html
import os
import re
import shutil
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "addons")
OUT = os.path.join(ROOT, "repo")
FIXED_TIME = (2026, 1, 1, 0, 0, 0)
SKIP_DIRS = {"__pycache__", ".git", ".github"}
SKIP_FILES = {".DS_Store", "Thumbs.db"}
SKIP_SUFFIX = (".pyc", ".pyo", ".part")
VERSION_RE = re.compile(r"^\d+(\.\d+){0,3}([~+-][0-9A-Za-z.+~-]+)?$")


def read_addon(path):
    xml_path = os.path.join(path, "addon.xml")
    root = ET.parse(xml_path).getroot()
    addon_id, version = root.get("id"), root.get("version")
    if os.path.basename(path) != addon_id:
        raise SystemExit("%s: folder name must equal addon id %r" % (path, addon_id))
    if not version or not VERSION_RE.match(version):
        raise SystemExit("%s: invalid version %r" % (addon_id, version))
    with open(xml_path, encoding="utf-8") as fh:
        text = fh.read()
    text = re.sub(r"^\s*<\?xml[^>]*\?>\s*", "", text).strip()
    news = root.findtext(".//news") or ""
    return addon_id, version, text, news, root


def asset(root, tag):
    el = root.find(".//assets/" + tag)
    return el.text.strip() if el is not None and el.text else None


def build_zip(src_dir, addon_id, dest):
    files = []
    for base, dirs, names in os.walk(src_dir):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(names):
            if name in SKIP_FILES or name.endswith(SKIP_SUFFIX):
                continue
            files.append(os.path.join(base, name))
    tmp = dest + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in files:
            rel = os.path.relpath(path, src_dir).replace(os.sep, "/")
            info = zipfile.ZipInfo("%s/%s" % (addon_id, rel), FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with open(path, "rb") as fh:
                zf.writestr(info, fh.read())
    os.replace(tmp, dest)


def write_if_changed(path, data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    if os.path.exists(path):
        with open(path, "rb") as fh:
            if fh.read() == data:
                return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


def index_page(title, links):
    rows = "\n".join('<a href="%s">%s</a><br>' % (html.escape(h, quote=True), html.escape(t)) for h, t in links)
    return ("<!DOCTYPE html>\n<html><head><meta charset=\"utf-8\"><title>%s</title></head>\n<body>\n"
            "<h1>%s</h1>\n%s\n</body></html>\n" % (html.escape(title), html.escape(title), rows))


def build():
    addon_dirs = sorted(d for d in os.listdir(SRC) if os.path.isfile(os.path.join(SRC, d, "addon.xml")))
    if not addon_dirs:
        raise SystemExit("no add-ons found in %s" % SRC)
    entries, top_links = [], [("addons.xml", "addons.xml"), ("addons.xml.md5", "addons.xml.md5")]
    keep_dirs = set()
    for name in addon_dirs:
        src = os.path.join(SRC, name)
        addon_id, version, xml_text, news, root = read_addon(src)
        out_dir = os.path.join(OUT, addon_id)
        os.makedirs(out_dir, exist_ok=True)
        keep_dirs.add(addon_id)
        zip_name = "%s-%s.zip" % (addon_id, version)
        zip_path = os.path.join(out_dir, zip_name)
        tmp_zip = zip_path + ".new"
        build_zip(src, addon_id, tmp_zip)
        if os.path.exists(zip_path) and open(zip_path, "rb").read() == open(tmp_zip, "rb").read():
            os.remove(tmp_zip)
        else:
            os.replace(tmp_zip, zip_path)
        for key in ("icon", "fanart"):
            rel = asset(root, key)
            if rel and os.path.exists(os.path.join(src, rel)):
                dst = os.path.join(out_dir, os.path.basename(rel))
                if not os.path.exists(dst) or open(dst, "rb").read() != open(os.path.join(src, rel), "rb").read():
                    shutil.copyfile(os.path.join(src, rel), dst)
        if news:
            write_if_changed(os.path.join(out_dir, "changelog-%s.txt" % version), news.strip() + "\n")
        zips = sorted((f for f in os.listdir(out_dir) if f.endswith(".zip")), reverse=True)
        write_if_changed(os.path.join(out_dir, "index.html"),
                         index_page(addon_id, [("../", "..")] + [(z, z) for z in zips]))
        top_links.append((addon_id + "/", addon_id + "/"))
        entries.append(xml_text)
        print("  %s %s" % (addon_id, version))
    addons_xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<addons>\n%s\n</addons>\n' % "\n".join(entries)
    write_if_changed(os.path.join(OUT, "addons.xml"), addons_xml)
    write_if_changed(os.path.join(OUT, "addons.xml.md5"), hashlib.md5(addons_xml.encode("utf-8")).hexdigest())
    write_if_changed(os.path.join(OUT, "index.html"), index_page("mmbesar Kodi repository", top_links))
    for stale in os.listdir(OUT):
        full = os.path.join(OUT, stale)
        if os.path.isdir(full) and stale not in keep_dirs:
            shutil.rmtree(full)


def snapshot():
    out = {}
    for base, _dirs, names in os.walk(OUT):
        for n in names:
            p = os.path.join(base, n)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, OUT)] = hashlib.sha1(fh.read()).hexdigest()
    return out


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    if "--check" in sys.argv:
        before = snapshot()
        build()
        after = snapshot()
        if before != after:
            changed = sorted(set(before) ^ set(after) | {k for k in before if k in after and before[k] != after[k]})
            print("repo/ is out of date: %s" % ", ".join(changed))
            sys.exit(1)
        print("repo/ is up to date")
    else:
        print("building repository:")
        build()
