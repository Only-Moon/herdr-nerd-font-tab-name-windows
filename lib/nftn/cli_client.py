"""Cross-platform herdr API client.

Uses the `herdr` CLI binary on all platforms. On Unix this avoids raw socket
complexity; on Windows it's the only way since AF_UNIX sockets don't exist.

The CLI returns JSON envelopes with a `result` field matching the socket API.
"""

import json
import os
import subprocess
import sys
from typing import Any, Dict, List, Optional


class HerdrError(Exception):
    """An error response from the herdr server or CLI."""


def herdr_bin() -> str:
    """Resolve the herdr binary path, preferring HERDR_BIN_PATH env var."""
    explicit = os.environ.get("HERDR_BIN_PATH")
    if explicit:
        return explicit

    # Check PATH
    for path_dir in os.environ.get("PATH", "").split(os.pathsep):
        for name in ("herdr", "herdr.exe"):
            cand = os.path.join(path_dir, name)
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                return cand

    # Windows default install location
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA") or os.path.join(
            os.environ.get("USERPROFILE", ""), "AppData", "Local"
        )
        base = os.path.join(local, "Programs", "Herdr", "bin", "herdr")
        for cand in (base, base + ".exe"):
            if os.path.isfile(cand):
                return cand

    return "herdr"


def _run_herdr(args: List[str], timeout: float = 10.0) -> Dict[str, Any]:
    """Run herdr CLI and parse JSON envelope."""
    cmd = [herdr_bin()] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise HerdrError(f"herdr timeout: {' '.join(cmd)}") from exc
    except OSError as exc:
        raise HerdrError(f"herdr not found: {exc}") from exc

    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else ""
        raise HerdrError(f"herdr {' '.join(args)}: {stderr or 'failed'}")

    stdout = result.stdout.strip()
    if not stdout:
        return {}

    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise HerdrError(f"herdr {' '.join(args)}: invalid JSON: {exc}") from exc

    if isinstance(envelope, dict):
        if envelope.get("error"):
            err = envelope["error"]
            raise HerdrError(f"{err.get('code', 'error')}: {err.get('message', '')}")
        if "result" in envelope:
            return envelope["result"]
        return envelope

    return envelope


class CliClient:
    """herdr API via CLI subprocess (cross-platform)."""

    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout

    def request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Not used for CLI path; kept for interface compatibility."""
        raise NotImplementedError("Use specific methods")

    def snapshot(self) -> Dict[str, Any]:
        return _run_herdr(["api", "snapshot"], timeout=self.timeout).get("snapshot", {})

    def process_info(self, pane_id: str) -> Dict[str, Any]:
        return _run_herdr(["pane", "process-info", pane_id], timeout=self.timeout).get("process_info", {})

    def rename_tab(self, tab_id: str, label: str) -> Dict[str, Any]:
        return _run_herdr(["tab", "rename", tab_id, label], timeout=self.timeout)

    def tab_list(self) -> List[Dict[str, Any]]:
        return _run_herdr(["tab", "list"], timeout=self.timeout).get("tabs", [])

    def pane_list(self) -> List[Dict[str, Any]]:
        return _run_herdr(["pane", "list"], timeout=self.timeout).get("panes", [])