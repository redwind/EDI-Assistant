"""Saved EDI login: OS credential store, Settings section, one guarded automatic attempt."""
from __future__ import annotations

from types import SimpleNamespace

import keyring
import pytest
from keyring.backend import KeyringBackend

from edi_assistant.automation import autologin
from edi_assistant.core import credentials


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        super().__init__()
        self.store = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        self.store.pop((service, username), None)


@pytest.fixture
def kr():
    old = keyring.get_keyring()
    mem = MemoryKeyring()
    keyring.set_keyring(mem)
    yield mem
    keyring.set_keyring(old)


def test_save_load_replace_clear(kr):
    assert credentials.load() is None
    credentials.save(" a@b.com ", "pw1")
    assert credentials.load() == credentials.Login("a@b.com", "pw1") and "pw1" not in repr(credentials.load())
    credentials.save("c@d.com", "pw2")
    assert credentials.load().user == "c@d.com" and ("Burlington" not in str(kr.store))
    assert all(v != "pw1" for v in kr.store.values())          # old account removed
    credentials.clear()
    assert credentials.load() is None and kr.store == {}


def test_settings_dialog_saves_into_the_store_not_the_config(qtbot, kr):
    from edi_assistant.app.dialogs.settings_dialog import SettingsDialog
    from edi_assistant.core.config import AppConfig, config_to_dict
    dlg = SettingsDialog(AppConfig())
    qtbot.addWidget(dlg)
    dlg.login_user.setText("a@b.com")
    dlg.login_pwd.setText("secret")
    dlg.save_login()
    assert credentials.load().password == "secret" and dlg.login_pwd.text() == ""
    assert "secret" not in str(config_to_dict(dlg.result_config() if hasattr(dlg, "result_config") else AppConfig()))
    dlg.clear_login()
    assert credentials.load() is None


def _session(url, title, login_after=False, pwd_box=True):
    calls = []

    class Loc:
        def __init__(self, what):
            self.what = what

        def locator(self, css):
            return Loc(css)

        @property
        def first(self):
            return self

        def count(self):
            return 0 if ("password" in self.what and not pwd_box) else 1

        def fill(self, v):
            calls.append((self.what, v))

        def click(self):
            calls.append(("click", ""))

    class Nav:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    page = SimpleNamespace(url=url, locator=lambda css: Loc(css), expect_navigation=lambda **k: Nav(),
                           evaluate=lambda js: pwd_box)
    s = SimpleNamespace(page=page, site=SimpleNamespace(effective_base_url=lambda: "https://edi.coat.com/vms-gateway/"),
                        title=lambda: title, is_login_page=lambda: login_after, auto_login_failed=False)
    return s, calls


def test_auto_login_only_on_the_edi_login_page(kr):
    credentials.save("a@b.com", "secret")
    s, calls = _session("https://edi.coat.com/vms-gateway/login.do", "Vendor Management Suite -- Login")
    assert autologin.try_auto_login(s) == autologin.DONE
    assert ("[data-edi-login='pwd']", "secret") in calls and calls[-1][0] == "click"
    s, calls = _session("https://evil.example/vms-gateway/login.do", "Vendor Management Suite -- Login")
    assert autologin.try_auto_login(s) == autologin.NOT_HERE and calls == []      # other host: never
    s, calls = _session("https://edi.coat.com/vms-gateway/gateway/inbox.do", "EDI Gateway Inbox", pwd_box=False)
    assert autologin.try_auto_login(s) == autologin.NOT_HERE and calls == []


def test_one_attempt_only(kr):
    credentials.save("a@b.com", "wrong")
    s, calls = _session("https://edi.coat.com/vms-gateway/login.do", "Vendor Management Suite -- Login", login_after=True)
    assert autologin.try_auto_login(s) == autologin.FAILED and s.auto_login_failed
    calls.clear()
    assert autologin.try_auto_login(s) == autologin.FAILED and calls == []         # no second try


def test_no_saved_login(kr):
    s, calls = _session("https://edi.coat.com/vms-gateway/login.do", "Vendor Management Suite -- Login")
    assert autologin.try_auto_login(s) == autologin.NO_LOGIN and calls == []
