"""Single-instance guard over QLocalServer/QLocalSocket.

Protocol (one short message per connection):
  "SHOW <version>"  new launch -> running app. The running app answers "VER <its version>" and raises its
                    window only when the versions match (or the caller sent no version).
  "SHOW"            raise the window (also what builds <= 0.1.1 send).
  "QUIT"            ask the running app to exit (used to replace an older/newer version).
Builds <= 0.1.1 never answer, so a launch that gets no "VER" reply knows an old build is running.
"""
from __future__ import annotations

import getpass
import time

from PySide6.QtCore import QCoreApplication, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

UNKNOWN_VERSION = "?"   # running build too old to report its version


def default_key() -> str:
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = "user"
    return f"EDIAssistant-{user}"


class SingleInstance(QObject):
    show_requested = Signal()
    quit_requested = Signal()

    def __init__(self, key: str | None = None, parent: QObject | None = None, version: str = ""):
        super().__init__(parent)
        self._key = key or default_key()
        self._version = version
        self._server: QLocalServer | None = None
        self.running_version: str | None = None   # set when another version is already running

    # ------------------------------------------------------------------ client side
    def _send(self, msg: bytes, *, want_reply: bool = False) -> bytes | None:
        """Send one message to the running instance. None = nobody listening."""
        sock = QLocalSocket()
        sock.connectToServer(self._key)
        if not sock.waitForConnected(300):
            return None
        sock.write(msg)
        sock.flush()
        sock.waitForBytesWritten(500)
        reply = b""
        if want_reply and sock.waitForReadyRead(1000):
            reply = bytes(sock.readAll())
        sock.disconnectFromServer()
        return reply

    def try_acquire(self) -> bool:
        """True if we are the first instance.

        Otherwise returns False: with the same version the running one shows itself; with a different version
        `running_version` is set (UNKNOWN_VERSION for old builds) and the caller decides what to do."""
        self.running_version = None
        msg = b"SHOW " + self._version.encode() if self._version else b"SHOW"
        reply = self._send(msg, want_reply=bool(self._version))
        if reply is not None:
            if self._version:
                other = reply[4:].decode(errors="replace").strip() if reply.startswith(b"VER ") else UNKNOWN_VERSION
                if other != self._version:
                    self.running_version = other
            return False
        QLocalServer.removeServer(self._key)  # stale socket from a crashed run
        server = QLocalServer(self)
        if not server.listen(self._key):
            return True  # cannot listen: do not block startup
        server.newConnection.connect(self._on_connection)
        self._server = server
        return True

    def raise_running(self) -> None:
        self._send(b"SHOW")

    def replace_running(self, timeout_s: float = 20.0) -> bool:
        """Ask the running instance to quit, wait for it to go, then become the instance. False on timeout."""
        if self._send(b"QUIT") is None:
            return self.try_acquire()
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            QCoreApplication.processEvents()
            time.sleep(0.2)
            probe = QLocalSocket()
            probe.connectToServer(self._key)
            alive = probe.waitForConnected(200)
            if alive:
                probe.disconnectFromServer()
                continue
            return self.try_acquire()
        return False

    # ------------------------------------------------------------------ server side
    def _on_connection(self) -> None:
        assert self._server is not None
        while self._server.hasPendingConnections():
            s = self._server.nextPendingConnection()
            s.waitForReadyRead(200)
            data = bytes(s.readAll())
            if data.startswith(b"SHOW"):
                caller = data[4:].decode(errors="replace").strip()
                if caller:
                    s.write(b"VER " + self._version.encode())
                    s.flush()
                    s.waitForBytesWritten(500)
                if not caller or caller == self._version:
                    self.show_requested.emit()
            elif data.startswith(b"QUIT"):
                self.quit_requested.emit()
            s.disconnectFromServer()

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
