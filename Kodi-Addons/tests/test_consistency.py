# SPDX-License-Identifier: GPL-3.0-or-later
"""Static checks: every string/setting reference resolves, repo output is current."""
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

from conftest import ADDON_DIR, ROOT, STRINGS

LIB = os.path.join(ADDON_DIR, "resources", "lib")


def _sources():
    for name in sorted(os.listdir(LIB)):
        if name.endswith(".py"):
            yield name, open(os.path.join(LIB, name), encoding="utf-8").read()


def test_every_S_constant_used_in_code_exists():
    from resources.lib.strings import S
    for name, text in _sources():
        for const in re.findall(r"\bS\.([A-Z_0-9]+)", text):
            assert hasattr(S, const), "%s uses missing S.%s" % (name, const)


def test_every_string_id_has_text_and_strings_py_matches_po():
    from resources.lib.strings import S
    ids = {v for k, v in vars(S).items() if k.isupper()}
    assert ids == set(STRINGS), "strings.py and strings.po are out of sync (run tools/gen_strings.py)"


def test_settings_xml_labels_and_ids():
    root = ET.parse(os.path.join(ADDON_DIR, "resources", "settings.xml")).getroot()
    for el in root.iter():
        for attr in ("label", "help"):
            val = el.get(attr)
            if val and val.isdigit():
                assert int(val) in STRINGS, "settings.xml references missing string %s" % val
    for el in root.iter("heading"):
        assert int(el.text) in STRINGS
    ids = {s.get("id") for s in root.iter("setting")}
    used = set()
    for _n, text in _sources():
        used |= set(re.findall(r's_(?:str|bool|int)\("([a-z_]+)"', text))
    assert used <= ids, "code reads settings that settings.xml does not define: %s" % (used - ids)


def test_every_setting_has_a_default_and_every_group_nests_settings():
    root = ET.parse(os.path.join(ADDON_DIR, "resources", "settings.xml")).getroot()
    for s in root.iter("setting"):
        assert s.find("level") is not None
    for cat in root.iter("category"):
        assert cat.findall("group"), "category %s has no group (Kodi would hide its settings)" % cat.get("id")
        assert not cat.findall("setting")


def test_addon_xml_is_consistent():
    root = ET.parse(os.path.join(ADDON_DIR, "addon.xml")).getroot()
    assert root.get("id") == os.path.basename(ADDON_DIR)
    for point in ("xbmc.python.pluginsource", "xbmc.service"):
        ext = [e for e in root.findall("extension") if e.get("point") == point][0]
        assert os.path.exists(os.path.join(ADDON_DIR, ext.get("library")))
    for tag in ("icon", "fanart"):
        assert os.path.exists(os.path.join(ADDON_DIR, root.find(".//assets/" + tag).text))


def test_repo_directory_is_up_to_date():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "build_repo.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_settings_xml_matches_its_generator():
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import gen_settings
    current = open(os.path.join(ADDON_DIR, "resources", "settings.xml"), encoding="utf-8").read()
    assert current == gen_settings.XML, "settings.xml is stale: run python3 tools/gen_settings.py"
