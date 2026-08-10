"""Cross-platform watcher.

Unix: long-running daemon with event stream subscription.
Windows: event-driven one-shot (herdr hooks run once per event, no persistent process).
"""

import os
import select
import signal
import socket
import sys
import time

from .client import Client, EventStream, HerdrError, get_event_stream


# Events that can change what a tab is running or which pane speaks for it.
EVENTS = (
    "tab.created",
    "tab.closed",
    "tab.renamed",
    "tab.moved",
    "tab.focused",
    "pane.created",
    "pane.closed",
    "pane.updated",
    "pane.focused",
    "pane.moved",
    "pane.exited",
    "pane.agent_detected",
    "layout.updated",
)

DEBOUNCE_SECONDS = 0.15


def _use_event_stream() -> bool:
    """True when event stream is available (Unix only)."""
    return get_event_stream() is not None


def connect_events(path=None, attempts=10, delay=0.5, timeout=1.0):
    """Open the event stream (Unix only)."""
    if not _use_event_stream():
        raise RuntimeError("Event stream not available on this platform")
    last = None
    for attempt in range(attempts):
        try:
            return EventStream(path, timeout=timeout)
        except OSError as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(delay)
    raise last


class Watcher:
    """Long-running watcher (Unix only)."""

    def __init__(self, renamer_factory, socket_path=None, poll_interval=2.0, log=None):
        if not _use_event_stream():
            raise RuntimeError("Watcher not available on this platform; use oneshot_refresh()")
        self.renamer_factory = renamer_factory
        self.socket_path = socket_path
        self.poll_interval = max(0.0, poll_interval)
        self.log = log or (lambda *_: None)
        self.running = True

    def stop(self, *_):
        self.running = False

    def install_signal_handlers(self):
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            try:
                signal.signal(sig, self.stop)
            except (ValueError, OSError):
                pass

    def run(self):
        """Subscribe, then refresh on events and polling safety net."""
        events = connect_events(self.socket_path)
        renamer = self.renamer_factory(Client(self.socket_path))
        try:
            events.subscribe(EVENTS)
        except HerdrError as exc:
            self.log("subscribe failed: {}".format(exc))
            events.close()
            return 1

        self.log("watching {}".format(events.path))
        self._refresh(renamer)
        last_pass = time.time()
        due = None

        while self.running:
            now = time.time()
            timeouts = [1.0]
            if due is not None:
                timeouts.append(max(0.0, due - now))
            if self.poll_interval:
                timeouts.append(max(0.0, last_pass + self.poll_interval - now))
            readable, _, _ = select.select([events.sock], [], [], min(timeouts))

            if readable:
                if not self._drain(events):
                    self.log("herdr closed the event stream; exiting")
                    break
                due = time.time() + DEBOUNCE_SECONDS

            now = time.time()
            if due is not None and now >= due:
                due = None
                self._refresh(renamer)
                last_pass = now
            elif self.poll_interval and now - last_pass >= self.poll_interval:
                self._refresh(renamer)
                last_pass = now

        events.close()
        return 0

    def _drain(self, events):
        while True:
            try:
                message = events.read_message()
            except socket.timeout:
                return True
            except (OSError, ValueError):
                return False
            if message is None:
                return False
            if not events.has_buffered():
                return True

    def _refresh(self, renamer):
        try:
            for tab_id, label in renamer.refresh():
                self.log("renamed {} -> {}".format(tab_id, label))
        except HerdrError as exc:
            self.log("refresh failed: {}".format(exc))
        except OSError as exc:
            self.log("connection lost: {}".format(exc))
            self.running = False
        except Exception as exc:
            self.log("unexpected error: {!r}".format(exc))


def oneshot_refresh(renamer_factory, socket_path=None, log=None):
    """Single rename pass for event-driven mode (Windows).

    Called by herdr event hooks on Windows. No persistent process, no event stream.
    """
    log = log or (lambda *_: None)
    client = Client(socket_path)
    renamer = renamer_factory(client)
    try:
        for tab_id, label in renamer.refresh():
            log("renamed {} -> {}".format(tab_id, label))
    except HerdrError as exc:
        log("refresh failed: {}".format(exc))
        return 1
    except OSError as exc:
        log("connection lost: {}".format(exc))
        return 1
    except Exception as exc:
        log("unexpected error: {!r}".format(exc))
        return 1
    return 0


def is_watcher_platform() -> bool:
    """True if the persistent watcher can run (Unix)."""
    return _use_event_stream()


def is_oneshot_platform() -> bool:
    """True if event-driven one-shot should be used (Windows)."""
    return not _use_event_stream()