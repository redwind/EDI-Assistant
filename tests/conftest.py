"""Suite-wide isolation: tests never read or write the developer's real OS password store."""
from __future__ import annotations

import keyring
import pytest
from keyring.backend import KeyringBackend


class _MemoryKeyring(KeyringBackend):
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


@pytest.fixture(autouse=True)
def memory_keyring():
    old = keyring.get_keyring()
    mem = _MemoryKeyring()
    keyring.set_keyring(mem)
    yield mem
    keyring.set_keyring(old)
