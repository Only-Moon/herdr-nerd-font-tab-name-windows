"""Command line surface.

    watch     run the watcher in the foreground (Unix only, daemon mode)
    start     spawn the watcher detached (Unix) or register event hooks (Windows)
    stop      stop the watcher (--restore also puts the original labels back)
    restart   stop then start
    status    report whether a watcher is running for this session
    once      do a single rename pass and exit
    icon      resolve the icon for a name, for testing config changes
    refresh   event-driven one-shot pass (Windows event hook entry point)
"""

import argparse
import os
import signal
import subprocess
import sys
import time

from .client import Client, HerdrError, socket_path
from .daemon import is_watcher_platform, is_oneshot_platform
from .config import Config
from .daemon import Watcher, oneshot_refresh
from .icons import Resolver
from .renamer import Renamer
from .state import Store

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENTRYPOINT = os.path.join(PLUGIN_ROOT, "bin", "herdr-nerd-font-tab-name")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="herdr-nerd-font-tab-name",
        description="Nerd Font icons for herdr tab labels.",
    )
    parser.add_argument("--config", help="path to a config file (overrides the usual lookup)")
    parser.add_argument("--socket", help="path to the herdr API socket")
    parser.add_argument("--verbose", action="store_true", help="log to stderr")
    sub = parser.add_subparsers(dest="command")

    if is_watcher_platform():
        sub.add_parser("watch", help="run the watcher in the foreground (Unix)")
        sub.add_parser("start", help="spawn the watcher in the background (Unix)")
        sub.add_parser("restart", help="restart the background watcher (Unix)")
        sub.add_parser("status", help="show watcher status (Unix)")

    sub.add_parser("once", help="apply icons once and exit")

    stop = sub.add_parser("stop", help="stop the background watcher (Unix)")
    stop.add_argument("--restore", action="store_true", help="also restore the original tab labels")

    # Windows event hook entry point
    if is_oneshot_platform():
        sub.add_parser("refresh", help="single rename pass for event hook (Windows)")

    icon = sub.add_parser("icon", help="print the icon a name resolves to")
    icon.add_argument("name")
    icon.add_argument("--agent", help="resolve as a herdr agent id instead of a command")
    return parser


def _logger(verbose):
    if not verbose:
        return lambda *_: None

    def log(message):
        sys.stderr.write("[nerd-font-tab-name] {}\n".format(message))
        sys.stderr.flush()

    return log


def _trim_log(path, limit=512 * 1024):
    """Keep the watcher log from growing without bound across restarts."""
    try:
        if os.path.getsize(path) > limit:
            os.remove(path)
    except OSError:
        pass


def _wait_for_exit(pid, timeout=5.0, interval=0.1):
    """Block until `pid` is gone. False if it outlived the timeout."""
    from .state import _is_pid_alive
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _is_pid_alive(pid):
            return True
        time.sleep(interval)
    return not _is_pid_alive(pid)


def _pieces(args):
    config = Config.load(user_path=args.config)
    path = args.socket or socket_path()
    return config, Resolver(config), path, Store(path)


def _renamer_factory(config, resolver, store):
    def factory(connection):
        return Renamer(connection, config, resolver, store)
    return factory


def cmd_watch(args):
    if not is_watcher_platform():
        sys.stderr.write("watch: not available on this platform (use 'refresh' on Windows)\n")
        return 1
    config, resolver, path, store = _pieces(args)
    log = _logger(args.verbose)

    lock = store.acquire_lock()
    if lock is None:
        log("another watcher already holds the lock for this session")
        return 0

    store.write_pid()
    watcher = Watcher(
        _renamer_factory(config, resolver, store),
        socket_path=path,
        poll_interval=config.float("poll-interval", 2.0),
        log=log,
    )
    watcher.install_signal_handlers()
    try:
        return watcher.run()
    except OSError as exc:
        log("could not reach herdr: {}".format(exc))
        return 1
    finally:
        if store.read_pid() == os.getpid():
            store.clear_pid()
        store.release_lock()


def cmd_start(args):
    if not is_watcher_platform():
        # Windows: event hooks are registered in herdr-plugin.toml, nothing to do here
        log = _logger(args.verbose)
        log("start: event hooks registered via herdr-plugin.toml on Windows")
        return 0

    _, _, path, store = _pieces(args)
    log = _logger(args.verbose)

    running = store.running_pid()
    if running:
        log("watcher already running (pid {})".format(running))
        return 0

    # Global flags come before the subcommand.
    command = [sys.executable, ENTRYPOINT, "--verbose"]
    if args.config:
        command += ["--config", args.config]
    if args.socket:
        command += ["--socket", args.socket]
    command.append("watch")

    log_path = store.log_path
    _trim_log(log_path)
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write("--- started {} ---\n".format(time.strftime("%Y-%m-%d %H:%M:%S")))
        handle.flush()
        # Detach: herdr startup hooks are one-shot, so nothing supervises this.
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=handle,
            start_new_session=True,
            env=dict(os.environ, HERDR_SOCKET_PATH=path),
        )
    # The child writes the pid file itself, once it holds the session lock —
    # so a spawn that loses the race leaves the running watcher's pid intact.
    log("watcher started (pid {}), logging to {}".format(process.pid, log_path))
    return 0


def cmd_stop(args):
    if not is_watcher_platform():
        sys.stderr.write("stop: not available on this platform (no persistent watcher on Windows)\n")
        return 1

    config, resolver, path, store = _pieces(args)
    log = _logger(args.verbose)

    pid = store.running_pid()
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            log("stopped watcher (pid {})".format(pid))
        except OSError as exc:
            log("could not stop pid {}: {}".format(pid, exc))
    else:
        log("no watcher running")

    if pid and not _wait_for_exit(pid):
        # A watcher still in its select() loop would undo the restore below.
        log("watcher {} did not exit in time".format(pid))
    store.clear_pid()

    if args.restore:
        # Reload: the watcher owns the state file while it runs.
        store.load()
        try:
            renamer = Renamer(get_client(), config, resolver, store)
            for tab_id, label in renamer.restore():
                log("restored {} -> {}".format(tab_id, label))
        except (OSError, HerdrError) as exc:
            log("could not restore labels: {}".format(exc))
            return 1
    return 0


def cmd_restart(args):
    if not is_watcher_platform():
        sys.stderr.write("restart: not available on this platform\n")
        return 1
    args.restore = False
    cmd_stop(args)  # waits for the old watcher to exit
    return cmd_start(args)


def cmd_status(args):
    if not is_watcher_platform():
        print("status: no persistent watcher on this platform (event-driven on Windows)")
        return 0
    _, _, path, store = _pieces(args)
    pid = store.running_pid()
    print("socket:  {}".format(path))
    print("watcher: {}".format("running (pid {})".format(pid) if pid else "not running"))
    print("state:   {}".format(store.path))
    print("log:     {}".format(store.log_path))
    return 0


def cmd_once(args):
    config, resolver, path, store = _pieces(args)
    log = _logger(args.verbose)
    try:
        renamer = Renamer(get_client(), config, resolver, store)
        for tab_id, label in renamer.refresh():
            log("renamed {} -> {}".format(tab_id, label))
    except (OSError, HerdrError) as exc:
        sys.stderr.write("herdr-nerd-font-tab-name: {}\n".format(exc))
        return 1
    return 0


def cmd_refresh(args):
    """Event-driven one-shot pass (Windows event hook entry point)."""
    if not is_oneshot_platform():
        sys.stderr.write("refresh: only available on Windows (event-driven mode)\n")
        return 1
    config, resolver, path, store = _pieces(args)
    log = _logger(args.verbose)
    return oneshot_refresh(_renamer_factory(config, resolver, store), socket_path=path, log=log)


def cmd_icon(args):
    config = Config.load(user_path=args.config)
    resolver = Resolver(config)
    if args.agent:
        icon, _ = resolver.resolve(agent=args.agent, label=args.name)
    else:
        icon, _ = resolver.resolve(processes=[{"name": args.name}], label=args.name)
    print(icon)
    return 0


COMMANDS = {
    "watch": cmd_watch,
    "start": cmd_start,
    "stop": cmd_stop,
    "restart": cmd_restart,
    "status": cmd_status,
    "once": cmd_once,
    "refresh": cmd_refresh,
    "icon": cmd_icon,
}


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    sys.exit(main())