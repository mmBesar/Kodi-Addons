# SPDX-License-Identifier: GPL-3.0-or-later
import json
import time

import pytest

from conftest import SETTINGS, api


def test_normalize_url():
    n = api.normalize_url
    assert n("abs.example.com") == "https://abs.example.com"
    assert n(" https://abs.example.com/ ") == "https://abs.example.com"
    assert n("http://10.0.0.5:13378") == "http://10.0.0.5:13378"
    assert n("https://example.com/abs/") == "https://example.com/abs"  # reverse-proxy sub-path
    assert n("") == "" and n("   ") == ""


def test_api_key_auth_and_test_connection(env):
    client = api.ABSClient()
    assert client.configured()
    ok, msg = client.test()
    assert ok and "mohanad" in msg
    # the key is sent as a Bearer header, never in the URL
    assert all("key-123" not in path for _m, path in env.state.requests)


def test_domain_with_trailing_slash_is_accepted(env):
    assert api.ABSClient().libraries()[0]["id"] == "lib_pod"


def test_bad_api_key_raises_auth_error(env):
    SETTINGS["api_key"] = "nope"
    with pytest.raises(api.ABSAuthError):
        api.ABSClient().libraries()


def test_unreachable_server_is_connection_error(env):
    env.state.offline = True
    with pytest.raises(api.ABSConnectionError):
        api.ABSClient().libraries()


def _password_mode():
    SETTINGS.update({"auth_method": 1, "username": "mohanad", "password": "secret", "api_key": ""})


def test_password_login_requests_tokens_and_persists_them(env):
    _password_mode()
    client = api.ABSClient()
    client.libraries()
    assert env.state.logins == 1
    saved = json.load(open(api.AUTH_FILE))
    assert saved["access"] and saved["refresh"].startswith("r-")
    assert saved["exp"] > time.time() + 3000
    # a new client (new Kodi invocation) reuses the cached token: no second login
    api.ABSClient().libraries()
    assert env.state.logins == 1


def test_expired_access_token_refreshes_and_rotates_refresh_token(env):
    _password_mode()
    api.ABSClient().libraries()
    first = json.load(open(api.AUTH_FILE))
    env.state.access_tokens.clear()  # server forgets/expires the access token -> 401
    api.ABSClient().libraries()
    second = json.load(open(api.AUTH_FILE))
    assert env.state.refreshes == 1 and env.state.logins == 1
    assert second["refresh"] != first["refresh"], "rotated refresh token must be persisted"
    assert second["access"] != first["access"]


def test_dead_refresh_token_falls_back_to_login(env):
    _password_mode()
    api.ABSClient().libraries()
    env.state.access_tokens.clear()
    env.state.refresh_tokens.clear()
    api.ABSClient().libraries()
    assert env.state.logins == 2


def test_wrong_password_is_auth_error(env):
    _password_mode()
    SETTINGS["password"] = "wrong"
    with pytest.raises(api.ABSAuthError):
        api.ABSClient().libraries()


def test_auth_cache_is_ignored_when_account_changes(env):
    _password_mode()
    api.ABSClient().libraries()
    SETTINGS["username"] = "someone-else"
    assert api.ABSClient()._auth == {}


def test_track_and_cover_urls_contain_no_secrets(env):
    client = api.ABSClient()
    assert "token" not in client.track_url("sid", 1) and "key-123" not in client.track_url("sid", 1)
    assert "token" not in client.cover_url("li_x")
    assert client.track_url("a/b", 2).endswith("/public/session/a%2Fb/track/2")
