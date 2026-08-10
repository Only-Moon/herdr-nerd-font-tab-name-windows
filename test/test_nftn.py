"""Unit tests. Run with: python3 -m unittest discover -s test

On Windows, tests run 5x for flakiness detection.
"""

import os
import sys
import tempfile
import unittest
import platform

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))

from nftn import labels  # noqa: E402
from nftn.config import Config, parse_yaml  # noqa: E402
from nftn.icons import Resolver  # noqa: E402
from nftn.renamer import Renamer  # noqa: E402
from nftn.state import Store, is_pid_alive  # noqa: E402
from nftn.client import get_client, _use_cli_transport  # noqa: E402
from nftn.daemon import is_watcher_platform, is_oneshot_platform  # noqa: E402

DEFAULTS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "defaults.yml"
)


def config(**overrides):
    """A Config backed by the real defaults, with config-section overrides."""
    base = Config.load(default_path=DEFAULTS, user_path=False)
    base.user = {"config": {k.replace("_", "-"): str(v) for k, v in overrides.items()}}
    return base


def repeat_windows(times=5):
    """Decorator to repeat test N times on Windows."""
    def decorator(func):
        def wrapper(self):
            if platform.system() == "Windows":
                for i in range(times):
                    with self.subTest(iteration=i+1):
                        func(self)
            else:
                func(self)
        return wrapper
    return decorator


class ParseYamlTest(unittest.TestCase):
    def test_sections_and_quotes(self):
        parsed = parse_yaml('config:\n  show-name: "auto"\n\nicons:\n  vim: ""\n')
        self.assertEqual(parsed["config"]["show-name"], "auto")
        self.assertEqual(parsed["icons"]["vim"], "")

    def test_strips_trailing_comment_but_keeps_hash_icon(self):
        parsed = parse_yaml("config:\n  fallback-icon: ? # the default\nicons:\n  csharp: #\n")
        self.assertEqual(parsed["config"]["fallback-icon"], "?")
        self.assertEqual(parsed["icons"]["csharp"], "#")

    def test_ignores_comments_and_blank_lines(self):
        parsed = parse_yaml("# header\n\nconfig:\n  # note\n  show-name: true\n")
        self.assertEqual(parsed["config"], {"show-name": "true"})


class ConfigTest(unittest.TestCase):
    def test_user_overrides_default(self):
        merged = Config(user={"config": {"fallback-icon": "!"}}, defaults={"config": {"fallback-icon": "?"}})
        self.assertEqual(merged.get("config", "fallback-icon"), "!")

    def test_falls_back_when_user_omits_key(self):
        merged = Config(user={"config": {}}, defaults={"config": {"fallback-icon": "?"}})
        self.assertEqual(merged.get("config", "fallback-icon"), "?")

    def test_section_merges_icon_maps(self):
        merged = Config(user={"icons": {"vim": "V"}}, defaults={"icons": {"vim": "x", "top": "T"}})
        self.assertEqual(merged.section("icons"), {"vim": "V", "top": "T"})

    def test_tristate(self):
        self.assertEqual(config(show_name="auto").tristate("show-name"), "auto")
        self.assertIs(config(show_name="true").tristate("show-name"), True)
        self.assertIs(config(show_name="false").tristate("show-name"), False)

    def test_option_treats_null_as_unset(self):
        self.assertEqual(config(multi_pane_icon="null").option("multi-pane-icon"), "")


class ResolverTest(unittest.TestCase):
    def setUp(self):
        self.resolver = Resolver(config())

    def test_known_command(self):
        icon, fallback = self.resolver.resolve(processes=[{"name": "nvim"}])
        self.assertEqual(icon, self.resolver.icons["nvim"])
        self.assertFalse(fallback)

    def test_unknown_command_falls_back(self):
        icon, fallback = self.resolver.resolve(processes=[{"name": "definitely-not-a-tool"}])
        self.assertEqual(icon, "?")
        self.assertTrue(fallback)

    def test_innermost_process_wins(self):
        icon, _ = self.resolver.resolve(
            processes=[{"name": "less"}, {"name": "bash"}, {"name": "bash"}]
        )
        self.assertEqual(icon, self.resolver.icons["less"])

    def test_shell_shows_through_when_it_is_the_foreground(self):
        icon, _ = self.resolver.resolve(processes=[{"name": "zsh"}])
        self.assertEqual(icon, self.resolver.icons["zsh"])

    def test_argv0_preferred_when_it_has_an_icon(self):
        icon, _ = self.resolver.resolve(processes=[{"name": "node", "argv0": "/opt/bin/npm"}])
        self.assertEqual(icon, self.resolver.icons["npm"])

    def test_argv0_ignored_when_unknown(self):
        icon, _ = self.resolver.resolve(processes=[{"name": "node", "argv0": "some-wrapper"}])
        self.assertEqual(icon, self.resolver.icons["node"])

    def test_wrapper_unwrapped(self):
        icon, _ = self.resolver.resolve(processes=[{"name": "env", "argv": ["env", "htop"]}])
        self.assertEqual(icon, self.resolver.icons["htop"])

    def test_agent_beats_process(self):
        icon, _ = self.resolver.resolve(agent="claude", processes=[{"name": "node"}])
        self.assertEqual(icon, self.resolver.agents["claude"])

    def test_unknown_agent_uses_agent_fallback(self):
        icon, fallback = self.resolver.resolve(agent="brand-new-agent", processes=[{"name": "node"}])
        self.assertEqual(icon, config().option("agent-fallback-icon"))
        self.assertFalse(fallback)

    def test_agent_ignored_when_disabled(self):
        resolver = Resolver(config(prefer_agent_icons="false"))
        icon, _ = resolver.resolve(agent="claude", processes=[{"name": "node"}])
        self.assertEqual(icon, resolver.icons["node"])

    def test_sem_version_icon(self):
        resolver = Resolver(config(sem_version_icon="V"))
        icon, _ = resolver.resolve(processes=[{"name": "unknown"}], label="1.2.3")
        self.assertEqual(icon, "V")

    def test_vocabulary_includes_fallback_and_agents(self):
        vocabulary = self.resolver.vocabulary()
        self.assertIn("?", vocabulary)
        self.assertIn(self.resolver.agents["claude"], vocabulary)
        self.assertNotIn("", vocabulary)

    def test_folder_icon_resolution(self):
        """Test folder-based icon resolution via cwd."""
        icon, fallback = self.resolver.resolve(cwd="/home/user/.pi")
        self.assertEqual(icon, self.resolver.icons[".pi"])
        self.assertFalse(fallback)

        icon, fallback = self.resolver.resolve(cwd="/home/user/git-repos")
        self.assertEqual(icon, self.resolver.icons["git-repos"])
        self.assertFalse(fallback)


class LabelTest(unittest.TestCase):
    def test_auto_label_detection(self):
        self.assertTrue(labels.is_auto_label("3", 3))
        self.assertFalse(labels.is_auto_label("logs", 3))

    def test_strip_icons_removes_our_glyphs_only(self):
        self.assertEqual(labels.strip_icons("V logs", {"V"}), "logs")
        self.assertEqual(labels.strip_icons("logs V", {"V"}), "logs")
        self.assertEqual(labels.strip_icons("my logs", {"V"}), "my logs")

    def test_base_label_trusts_remembered_when_unchanged(self):
        tab = {"label": "V logs", "number": 2}
        remembered = {"base": "logs", "applied": "V logs"}
        self.assertEqual(labels.base_label(tab, remembered, {"V"}), "logs")

    def test_base_label_follows_manual_rename(self):
        tab = {"label": "deploy", "number": 2}
        remembered = {"base": "logs", "applied": "V logs"}
        self.assertEqual(labels.base_label(tab, remembered, {"V"}), "deploy")

    def test_base_label_falls_back_to_number(self):
        tab = {"label": "V", "number": 4}
        self.assertEqual(labels.base_label(tab, None, {"V"}), "4")

    def test_compose_auto_drops_the_tab_number(self):
        self.assertEqual(labels.compose("V", "4", config(), is_auto=True), "V")

    def test_compose_auto_keeps_a_real_name(self):
        self.assertEqual(labels.compose("V", "logs", config(), is_auto=False), "V logs")

    def test_compose_show_name_false(self):
        self.assertEqual(labels.compose("V", "logs", config(show_name="false")), "V")

    def test_compose_show_name_true_keeps_number(self):
        self.assertEqual(labels.compose("V", "4", config(show_name="true"), is_auto=True), "V 4")

    def test_compose_icon_on_the_right(self):
        self.assertEqual(labels.compose("V", "logs", config(icon_position="right")), "logs V")

    def test_compose_multi_pane_prefix(self):
        composed = labels.compose("V", "logs", config(multi_pane_icon="M"), pane_count=2)
        self.assertEqual(composed, "M V logs")

    def test_compose_always_show_fallback_name(self):
        cfg = config(show_name="false", always_show_fallback_name="true")
        self.assertEqual(labels.compose("?", "logs", cfg, is_fallback=True), "? logs")


class FakeConnection:
    """Stands in for a herdr socket connection."""

    def __init__(self, tabs, panes, layouts=None, processes=None):
        self.snapshot_data = {"tabs": tabs, "panes": panes, "layouts": layouts or []}
        self.processes = processes or {}
        self.renames = []

    def snapshot(self):
        return self.snapshot_data

    def process_info(self, pane_id):
        return {"foreground_processes": self.processes.get(pane_id, [])}

    def rename_tab(self, tab_id, label):
        self.renames.append((tab_id, label))
        for tab in self.snapshot_data["tabs"]:
            if tab["tab_id"] == tab_id:
                tab["label"] = label
        return {}


class RenamerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["HERDR_PLUGIN_STATE_DIR"] = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(os.environ.pop, "HERDR_PLUGIN_STATE_DIR", None)

    def build(self, connection, cfg=None):
        cfg = cfg or config()
        store = Store(os.path.join(self.tmp.name, "session.sock"))
        return Renamer(connection, cfg, Resolver(cfg), store), store

    def test_auto_tab_becomes_just_an_icon(self):
        connection = FakeConnection(
            tabs=[{"tab_id": "w1:t1", "number": 1, "label": "1", "pane_count": 1}],
            panes=[{"pane_id": "w1:p1", "tab_id": "w1:t1"}],
            processes={"w1:p1": [{"name": "vim"}]},
        )
        renamer, _ = self.build(connection)
        renamer.refresh()
        vim = renamer.resolver.icons["vim"]
        self.assertEqual(connection.renames, [("w1:t1", vim)])

    def test_named_tab_keeps_its_name(self):
        connection = FakeConnection(
            tabs=[{"tab_id": "w1:t1", "number": 1, "label": "logs", "pane_count": 1}],
            panes=[{"pane_id": "w1:p1", "tab_id": "w1:t1"}],
            processes={"w1:p1": [{"name": "vim"}]},
        )
        renamer, _ = self.build(connection)
        renamer.refresh()
        vim = renamer.resolver.icons["vim"]
        self.assertEqual(connection.renames, [("w1:t1", "{} logs".format(vim))])

    def test_second_pass_is_idempotent(self):
        connection = FakeConnection(
            tabs=[{"tab_id": "w1:t1", "number": 1, "label": "logs", "pane_count": 1}],
            panes=[{"pane_id": "w1:p1", "tab_id": "w1:t1"}],
            processes={"w1:p1": [{"name": "vim"}]},
        )
        renamer, _ = self.build(connection)
        renamer.refresh()
        renamer.refresh()
        self.assertEqual(len(connection.renames), 1)

    def test_icon_not_doubled_after_the_command_changes(self):
        connection = FakeConnection(
            tabs=[{"tab_id": "w1:t1", "number": 1, "label": "logs", "pane_count": 1}],
            panes=[{"pane_id": "w1:p1", "tab_id": "w1:t1"}],
            processes={"w1:p1": [{"name": "vim"}]},
        )
        renamer, _ = self.build(connection)
        renamer.refresh()
        connection.processes["w1:p1"] = [{"name": "htop"}]
        renamer.refresh()
        htop = renamer.resolver.icons["htop"]
        self.assertEqual(connection.snapshot_data["tabs"][0]["label"], "{} logs".format(htop))

    def test_manual_rename_becomes_the_new_base(self):
        connection = FakeConnection(
            tabs=[{"tab_id": "w1:t1", "number": 1, "label": "logs", "pane_count": 1}],
            panes=[{"pane_id": "w1:p1", "tab_id": "w1:t1"}],
            processes={"w1:p1": [{"name": "vim"}]},
        )
        renamer, store = self.build(connection)
        renamer.refresh()
        connection.snapshot_data["tabs"][0]["label"] = "deploy"
        renamer.refresh()
        vim = renamer.resolver.icons["vim"]
        self.assertEqual(connection.snapshot_data["tabs"][0]["label"], "{} deploy".format(vim))
        self.assertEqual(store.get("w1:t1")["base"], "deploy")

    def test_layout_focus_picks_the_pane(self):
        connection = FakeConnection(
            tabs=[{"tab_id": "w1:t1", "number": 1, "label": "1", "pane_count": 2}],
            panes=[
                {"pane_id": "w1:p1", "tab_id": "w1:t1"},
                {"pane_id": "w1:p2", "tab_id": "w1:t1"},
            ],
            layouts=[{"tab_id": "w1:t1", "focused_pane_id": "w1:p2"}],
            processes={"w1:p1": [{"name": "vim"}], "w1:p2": [{"name": "htop"}]},
        )
        renamer, _ = self.build(connection)
        renamer.refresh()
        self.assertEqual(connection.renames, [("w1:t1", renamer.resolver.icons["htop"])])

    def test_agent_pane_skips_the_process_lookup(self):
        connection = FakeConnection(
            tabs=[{"tab_id": "w1:t1", "number": 1, "label": "1", "pane_count": 1}],
            panes=[{"pane_id": "w1:p1", "tab_id": "w1:t1", "agent": "claude"}],
            processes={"w1:p1": [{"name": "node"}]},
        )
        renamer, _ = self.build(connection)
        renamer.refresh()
        self.assertEqual(connection.renames, [("w1:t1", renamer.resolver.agents["claude"])])

    def test_rename_auto_tabs_only_leaves_named_tabs_alone(self):
        connection = FakeConnection(
            tabs=[
                {"tab_id": "w1:t1", "number": 1, "label": "1", "pane_count": 1},
                {"tab_id": "w1:t2", "number": 2, "label": "logs", "pane_count": 1},
            ],
            panes=[
                {"pane_id": "w1:p1", "tab_id": "w1:t1"},
                {"pane_id": "w1:p2", "tab_id": "w1:t2"},
            ],
            processes={"w1:p1": [{"name": "vim"}], "w1:p2": [{"name": "vim"}]},
        )
        renamer, _ = self.build(connection, config(rename_auto_tabs_only="true"))
        renamer.refresh()
        self.assertEqual([tab_id for tab_id, _ in connection.renames], ["w1:t1"])

    def test_rename_auto_tabs_only_keeps_updating_tabs_it_owns(self):
        connection = FakeConnection(
            tabs=[{"tab_id": "w1:t1", "number": 1, "label": "1", "pane_count": 1}],
            panes=[{"pane_id": "w1:p1", "tab_id": "w1:t1"}],
            processes={"w1:p1": [{"name": "vim"}]},
        )
        renamer, _ = self.build(connection, config(rename_auto_tabs_only="true"))
        renamer.refresh()
        connection.processes["w1:p1"] = [{"name": "htop"}]
        renamer.refresh()
        self.assertEqual(connection.snapshot_data["tabs"][0]["label"], renamer.resolver.icons["htop"])

    def test_restore_puts_labels_back(self):
        connection = FakeConnection(
            tabs=[{"tab_id": "w1:t1", "number": 1, "label": "logs", "pane_count": 1}],
            panes=[{"pane_id": "w1:p1", "tab_id": "w1:t1"}],
            processes={"w1:p1": [{"name": "vim"}]},
        )
        renamer, store = self.build(connection)
        renamer.refresh()
        renamer.restore()
        self.assertEqual(connection.snapshot_data["tabs"][0]["label"], "logs")
        self.assertIsNone(store.get("w1:t1"))

    def test_closed_tabs_are_pruned_from_state(self):
        connection = FakeConnection(
            tabs=[{"tab_id": "w1:t1", "number": 1, "label": "1", "pane_count": 1}],
            panes=[{"pane_id": "w1:p1", "tab_id": "w1:t1"}],
            processes={"w1:p1": [{"name": "vim"}]},
        )
        renamer, store = self.build(connection)
        renamer.refresh()
        connection.snapshot_data["tabs"] = []
        connection.snapshot_data["panes"] = []
        renamer.refresh()
        self.assertEqual(store.tabs, {})

    def test_tab_without_panes_is_skipped(self):
        connection = FakeConnection(
            tabs=[{"tab_id": "w1:t1", "number": 1, "label": "1", "pane_count": 0}],
            panes=[],
        )
        renamer, _ = self.build(connection)
        renamer.refresh()
        self.assertEqual(connection.renames, [])

    def test_folder_icon_from_cwd(self):
        """Test folder icon resolution when pane has no process but has cwd."""
        connection = FakeConnection(
            tabs=[{"tab_id": "w1:t1", "number": 1, "label": "1", "pane_count": 1}],
            panes=[{"pane_id": "w1:p1", "tab_id": "w1:t1", "cwd": "/home/user/.pi"}],
            processes={},
        )
        renamer, _ = self.build(connection)
        renamer.refresh()
        pi_icon = renamer.resolver.icons[".pi"]
        self.assertEqual(connection.renames, [("w1:t1", pi_icon)])


class WindowsSpecificTest(unittest.TestCase):
    """Windows-specific tests that repeat 5x for flakiness detection."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["HERDR_PLUGIN_STATE_DIR"] = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(os.environ.pop, "HERDR_PLUGIN_STATE_DIR", None)

    def build(self, connection, cfg=None):
        cfg = cfg or config()
        store = Store(os.path.join(self.tmp.name, "session.sock"))
        return Renamer(connection, cfg, Resolver(cfg), store), store

    @repeat_windows(5)
    def test_cli_transport_selected_on_windows(self):
        """CLI transport is used on Windows."""
        if platform.system() != "Windows":
            self.skipTest("Windows only")
        self.assertTrue(_use_cli_transport())
        self.assertFalse(is_watcher_platform())
        self.assertTrue(is_oneshot_platform())
        client = get_client()
        from nftn.cli_client import CliClient
        self.assertIsInstance(client, CliClient)

    @repeat_windows(5)
    def test_state_dir_windows_path(self):
        """State directory uses %LOCALAPPDATA% on Windows."""
        if platform.system() != "Windows":
            self.skipTest("Windows only")
        from nftn.state import state_dir
        path = state_dir()
        self.assertIn("Local", path)
        self.assertIn("herdr-nerd-font-tab-name", path)

    @repeat_windows(5)
    def test_config_dir_windows_path(self):
        """Config directory uses %APPDATA% on Windows."""
        if platform.system() != "Windows":
            self.skipTest("Windows only")
        from nftn.config import user_config_paths
        paths = user_config_paths()
        # Should include APPDATA path
        appdata_path = None
        for p in paths:
            if "AppData" in p and "Roaming" in p:
                appdata_path = p
                break
        self.assertIsNotNone(appdata_path, "APPDATA path not found in config paths")

    @repeat_windows(5)
    def test_pid_alive_check_windows(self):
        """PID alive check works on Windows via tasklist."""
        if platform.system() != "Windows":
            self.skipTest("Windows only")
        # Current process should be alive
        self.assertTrue(is_pid_alive(os.getpid()))
        # Invalid PID should be false
        self.assertFalse(is_pid_alive(999999))

    @repeat_windows(5)
    def test_oneshot_refresh_works(self):
        """Event-driven one-shot refresh works on Windows."""
        if platform.system() != "Windows":
            self.skipTest("Windows only")
        from nftn.daemon import oneshot_refresh
        connection = FakeConnection(
            tabs=[{"tab_id": "w1:t1", "number": 1, "label": "1", "pane_count": 1}],
            panes=[{"pane_id": "w1:p1", "tab_id": "w1:t1"}],
            processes={"w1:p1": [{"name": "vim"}]},
        )
        renamer, store = self.build(connection)
        def factory(conn):
            return Renamer(conn, config(), Resolver(config()), store)
        result = oneshot_refresh(factory, log=lambda m: None)
        self.assertEqual(result, 0)

    @repeat_windows(5)
    def test_file_locking_portalocker(self):
        """File locking works cross-platform via portalocker."""
        if platform.system() != "Windows":
            self.skipTest("Windows only")
        import portalocker
        lock_file = os.path.join(self.tmp.name, "test.lock")
        # Just verify portalocker is available and basic locking works
        with open(lock_file, "w") as f:
            portalocker.lock(f, portalocker.LOCK_EX | portalocker.LOCK_NB)
            f.write(str(os.getpid()))
            f.flush()
            portalocker.unlock(f)
        # Verify we can re-lock after unlock
        with open(lock_file, "w") as f:
            portalocker.lock(f, portalocker.LOCK_EX | portalocker.LOCK_NB)
            portalocker.unlock(f)


if __name__ == "__main__":
    unittest.main()