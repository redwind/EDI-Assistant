"""EDI login kept in the operating system's credential store (Windows Credential Manager / macOS Keychain).

Never written to config, logs, screenshots or network recordings. Only the login step reads it, and only to
fill the login form of the configured EDI site."""
from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

SERVICE = "EDI Assistant - EDI Gateway login"
_USER_KEY = "__user__"   # the e-mail is stored under this fixed account name, the password under the e-mail


@dataclass(frozen=True)
class Login:
    user: str
    password: str

    def __repr__(self) -> str:   # never print the password
        return f"Login(user={self.user!r}, password=***)"


def _kr():
    import keyring   # imported lazily: a missing/broken backend must never stop the app
    return keyring


def available() -> bool:
    try:
        kr = _kr()
        return "fail" not in type(kr.get_keyring()).__module__.lower()
    except Exception:  # noqa: BLE001
        return False


def backend_name() -> str:
    try:
        return type(_kr().get_keyring()).__name__
    except Exception:  # noqa: BLE001
        return ""


def load() -> Login | None:
    try:
        kr = _kr()
        user = kr.get_password(SERVICE, _USER_KEY) or ""
        pwd = kr.get_password(SERVICE, user) if user else None
    except Exception as ex:  # noqa: BLE001
        log.warning("credential store not readable: %s", type(ex).__name__)
        return None
    return Login(user, pwd) if user and pwd else None


def saved_user() -> str:
    try:
        return _kr().get_password(SERVICE, _USER_KEY) or ""
    except Exception:  # noqa: BLE001
        return ""


def save(user: str, password: str) -> None:
    """Raises RuntimeError when the store cannot be written."""
    user = user.strip()
    if not user or not password:
        raise ValueError("user and password are required")
    try:
        kr = _kr()
        old = kr.get_password(SERVICE, _USER_KEY)
        if old and old != user:
            _delete(kr, old)
        kr.set_password(SERVICE, user, password)
        kr.set_password(SERVICE, _USER_KEY, user)
    except Exception as ex:  # noqa: BLE001
        raise RuntimeError(f"could not save the login: {type(ex).__name__}") from None


def _delete(kr, account: str) -> None:
    try:
        kr.delete_password(SERVICE, account)
    except Exception:  # noqa: BLE001
        pass


def clear() -> None:
    try:
        kr = _kr()
        user = kr.get_password(SERVICE, _USER_KEY)
        if user:
            _delete(kr, user)
        _delete(kr, _USER_KEY)
    except Exception:  # noqa: BLE001
        pass
