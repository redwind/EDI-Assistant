"""Single-instance guard over QLocalServer/QLocalSocket."""
from __future__ import annotations

import getpass

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


def default_key() -> str:
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = "user"
    return f"EDIAssistant-{user}"


class SingleInstance(QObject):
    show_requested = Signal()

    def __init__(self, key: str | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self._key = key or default_key()
        self._server: QLocalServer | None = None

    def try_acquire(self) -> bool:
        """True if we are the first instance. Otherwise ask the running one to show itself and return False."""
        sock = QLocalSocket()
        sock.connectToServer(self._key)
        if sock.waitForConnected(300):
            sock.write(b"SHOW")
            sock.flush()
            sock.waitForBytesWritten(500)
            sock.disconnectFromServer()
            return False
        QLocalServer.removeServer(self._key)  # stale socket from a crashed run
        server = QLocalServer(self)
        if not server.listen(self._key):
            return True  # cannot listen: do not block startup
        server.newConnection.connect(self._on_connection)
        self._server = server
        return True

    def _on_connection(self) -> None:
        assert self._server is not None
        while self._server.hasPendingConnections():
            s = self._server.nextPendingConnection()
            s.waitForReadyRead(200)
            if bytes(s.readAll()).startswith(b"SHOW"):
                self.show_requested.emit()
            s.disconnectFromServer()

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
