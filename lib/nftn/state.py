"""On-disk state: what we last wrote to each tab, and the watcher's lock.

State is keyed by socket path so several herdr sessions can run the plugin at
the same time without fighting over one file.

The location is deliberately *not* HERDR_PLUGIN_STATE_DIR. herdr only sets that
when it launches the command itself, so a watcher started by the startup hook
and a `stop --restore` you run from a shell would look in different places —
they would not see each other's pid file and you would end up with two watchers
fighting over every tab. One fixed path keeps every entry point in agreement.
"""

import errno
import hashlib
import json
import os
import sys

try:
    import portalocker
except ImportError:
    portalocker = None

try:
    import psutil
except ImportError:
    psutil = None


STATE_DIR_ENV = "HERDR_NERD_FONT_TAB_NAME_STATE_DIR"


def is_pid_alive(pid: int) -> bool:
    """Cross-platform check if a PID is alive."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        if psutil is not None:
            try:
                return psutil.pid_exists(pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return False
        # Fallback: use tasklist
        import subprocess
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, check=False
            ).stdout
            return str(pid) in out
        except Exception:
            return False
    else:
        # Unix: os.kill(pid, 0)
        try:
            os.kill(pid, 0)
        except OSError as exc:
            if exc.errno == errno.EPERM:
                return True
            return False
        return True


def state_dir():
    root = os.environ.get(STATE_DIR_ENV)
    if not root:
        # Cross-platform state directory
        if sys.platform == "win32":
            # Windows: %LOCALAPPDATA%\herdr-nerd-font-tab-name
            root = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "herdr-nerd-font-tab-name")
        else:
            # Unix: XDG_STATE_HOME or ~/.local/state
            xdg = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
            root = os.path.join(xdg, "herdr-nerd-font-tab-name")
    root = os.path.expanduser(root)
    os.makedirs(root, exist_ok=True)
    return root


def _session_key(socket_path):
    return hashlib.sha1(socket_path.encode("utf-8")).hexdigest()[:12]


class Store:
    """Per-session record of the labels we applied."""

    def __init__(self, socket_path):
        key = _session_key(socket_path)
        root = state_dir()
        self.path = os.path.join(root, "tabs-{}.json".format(key))
        self.pid_path = os.path.join(root, "watcher-{}.pid".format(key))
        self.lock_path = os.path.join(root, "watcher-{}.lock".format(key))
        self.log_path = os.path.join(root, "watcher-{}.log".format(key))
        self.tabs = {}
        self.pane_cwds = {}  # pane_id -> {"cwd": str, "updated": float}
        self._lock_handle = None
        self.load()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as handle:
                data = json.load(handle)
            self.tabs = data.get("tabs", {}) if isinstance(data, dict) else {}
            self.pane_cwds = data.get("pane_cwds", {})
        except (OSError, ValueError):
            self.tabs = {}
            self.pane_cwds = {}

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump({"tabs": self.tabs, "pane_cwds": self.pane_cwds}, handle, ensure_ascii=False)
        os.replace(tmp, self.path)

    def get(self, tab_id):
        return self.tabs.get(tab_id)

    def remember(self, tab_id, base, applied):
        self.tabs[tab_id] = {"base": base, "applied": applied}

    def forget(self, tab_id):
        self.tabs.pop(tab_id, None)

    def prune(self, live_tab_ids):
        for tab_id in list(self.tabs):
            if tab_id not in live_tab_ids:
                del self.tabs[tab_id]

    # -- pane cwd tracking -------------------------------------------------

    def get_pane_cwd(self, pane_id):
        """Get last known cwd for a pane."""
        entry = self.pane_cwds.get(pane_id)
        if entry:
            return entry.get("cwd")
        return None

    def set_pane_cwd(self, pane_id, cwd):
        """Update cwd for a pane with timestamp."""
        import time
        self.pane_cwds[pane_id] = {"cwd": cwd, "updated": time.time()}

    def should_update_cwd(self, pane_id, new_cwd, cooldown_seconds=2):
        """Check if cwd changed and cooldown expired."""
        entry = self.pane_cwds.get(pane_id)
        if not entry:
            return True
        if entry.get("cwd") != new_cwd:
            import time
            if time.time() - entry.get("updated", 0) >= cooldown_seconds:
                return True
        return False

    def prune(self, live_tab_ids):
        for tab_id in list(self.tabs):
            if tab_id not in live_tab_ids:
                del self.tabs[tab_id]

    # -- watcher pid ------------------------------------------------------

    def write_pid(self, pid=None):
        with open(self.pid_path, "w", encoding="utf-8") as handle:
            handle.write(str(pid or os.getpid()))

    def read_pid(self):
        try:
            with open(self.pid_path, encoding="utf-8") as handle:
                return int(handle.read().strip())
        except (OSError, ValueError):
            return None

    def clear_pid(self):
        try:
            os.remove(self.pid_path)
        except OSError:
            pass

    def running_pid(self):
        """The watcher pid if a process with it is alive, else None."""
        pid = self.read_pid()
        if not pid:
            return None

        # Cross-platform process check
        if sys.platform == "win32" and psutil is not None:
            try:
                return pid if psutil.pid_exists(pid) else None
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return None
        else:
            # Unix: os.kill(pid, 0)
            try:
                os.kill(pid, 0)
            except OSError as exc:
                if exc.errno == errno.EPERM:
                    return pid
                return None
        return pid

    def acquire_lock(self):
        """Take the session's watcher lock, or return None if it is held.

        The pid file answers "is one running?" cheaply; this is what actually
        makes a second watcher impossible, including when two of them race.
        """
        # Open in append mode so we can lock without truncating
        self._lock_handle = open(self.lock_path, "a")
        try:
            if sys.platform == "win32" and portalocker is not None:
                portalocker.lock(self._lock_handle, portalocker.LOCK_EX | portalocker.LOCK_NB)
            else:
                import fcntl
                fcntl.flock(self._lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._lock_handle.close()
            self._lock_handle = None
            return None

        self._lock_handle.seek(0)
        self._lock_handle.truncate()
        self._lock_handle.write(str(os.getpid()))
        self._lock_handle.flush()
        return self._lock_handle

    def release_lock(self):
        if self._lock_handle:
            try:
                if sys.platform == "win32" and portalocker is not None:
                    portalocker.unlock(self._lock_handle)
                else:
                    import fcntl
                    fcntl.flock(self._lock_handle, fcntl.LOCK_UN)
            except OSError:
                pass
            self._lock_handle.close()
            self._lock_handle = None