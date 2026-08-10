"""Cross-platform herdr API client with transport abstraction.

On Unix: uses AF_UNIX socket (original implementation).
On Windows: uses `herdr` CLI subprocess (no AF_UNIX sockets available).

Both transports present the same interface: snapshot(), process_info(), rename_tab().
EventStream is Unix-only; Windows uses event-driven one-shot via herdr hooks.
"""

import json
import os
import socket
import sys

from .cli_client import CliClient, HerdrError, herdr_bin


def socket_path():
    """Resolve the socket the same way the herdr CLI does (Unix only)."""
    explicit = os.environ.get("HERDR_SOCKET_PATH")
    if explicit:
        return explicit
    config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    root = os.path.join(config_home, "herdr")
    session = os.environ.get("HERDR_SESSION")
    if session:
        return os.path.join(root, "sessions", session, "herdr.sock")
    return os.path.join(root, "herdr.sock")


def _use_cli_transport() -> bool:
    """True when CLI transport should be used (Windows, or explicit override)."""
    if os.environ.get("HERDR_NERD_FONT_TRANSPORT") == "cli":
        return True
    if os.environ.get("HERDR_NERD_FONT_TRANSPORT") == "socket":
        return False
    return sys.platform == "win32"


class _Wire:
    """Unix socket connection for newline-delimited JSON messages."""

    def __init__(self, path, timeout=None):
        self.path = path
        self._buffer = b""
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        self.sock.connect(path)

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def send(self, method, params=None, request_id="nftn-1"):
        payload = {"id": request_id, "method": method, "params": params or {}}
        self.sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        return request_id

    def has_buffered(self):
        return b"\n" in self._buffer

    def read_message(self):
        while b"\n" not in self._buffer:
            chunk = self.sock.recv(65536)
            if not chunk:
                return None
            self._buffer += chunk
        line, self._buffer = self._buffer.split(b"\n", 1)
        if not line.strip():
            return self.read_message()
        return json.loads(line.decode("utf-8"))


def _unwrap(message, method):
    if message is None:
        raise HerdrError("herdr closed the connection during {}".format(method))
    if "error" in message:
        error = message["error"]
        raise HerdrError("{}: {}".format(error.get("code", "error"), error.get("message", "")))
    return message.get("result", {})


class SocketClient:
    """Unix socket transport (original implementation)."""

    def __init__(self, path=None, timeout=10.0):
        self.path = path or socket_path()
        self.timeout = timeout

    def request(self, method, params=None):
        with _Wire(self.path, timeout=self.timeout) as wire:
            wire.send(method, params)
            while True:
                message = wire.read_message()
                if message is None or message.get("id") == "nftn-1":
                    return _unwrap(message, method)

    def snapshot(self):
        return self.request("session.snapshot").get("snapshot", {})

    def process_info(self, pane_id):
        return self.request("pane.process_info", {"pane_id": pane_id}).get("process_info", {})

    def rename_tab(self, tab_id, label):
        return self.request("tab.rename", {"tab_id": tab_id, "label": label})


class EventStream:
    """Unix-only: subscription connection that stays open and pushes events."""

    def __init__(self, path=None, timeout=1.0):
        self.path = path or socket_path()
        self.wire = _Wire(self.path, timeout=timeout)

    @property
    def sock(self):
        return self.wire.sock

    def subscribe(self, event_types):
        self.wire.send("events.subscribe", {"subscriptions": [{"type": name} for name in event_types]})
        while True:
            message = self.wire.read_message()
            if message is None or message.get("id") == "nftn-1":
                return _unwrap(message, "events.subscribe")

    def has_buffered(self):
        return self.wire.has_buffered()

    def read_message(self):
        return self.wire.read_message()

    def close(self):
        self.wire.close()


def get_client(timeout: float = 10.0):
    """Factory returning the appropriate client for the current platform."""
    if _use_cli_transport():
        return CliClient(timeout=timeout)
    return SocketClient(timeout=timeout)


def get_event_stream(timeout: float = 1.0):
    """Factory returning EventStream (Unix only). Returns None on Windows."""
    if _use_cli_transport():
        return None
    return EventStream(timeout=timeout)


class Client:
    """Cross-platform client with backwards-compatible constructor."""

    def __init__(self, path=None, timeout=10.0):
        self._impl = get_client(timeout=timeout)
        # path is ignored for CLI transport, used for socket transport
        if hasattr(self._impl, 'path') and path is not None:
            self._impl.path = path

    def __getattr__(self, name):
        return getattr(self._impl, name)


# Backwards compatibility: Client class with platform-appropriate transport