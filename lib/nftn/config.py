"""Configuration loading.

The config format is deliberately the same flat two-level YAML the upstream tmux
plugin uses, so icon maps can be copied between the two projects. Only that
subset is parsed — no dependency on PyYAML.
"""

import os
import sys

# Where a user config is looked for, in order. The first file that exists wins;
# keys it does not define fall back to config/defaults.yml.
USER_CONFIG_ENV = "HERDR_NERD_FONT_TAB_NAME_CONFIG"

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_CONFIG_PATH = os.path.join(PLUGIN_ROOT, "config", "defaults.yml")

_TRUE = ("true", "yes", "on", "1")
_FALSE = ("false", "no", "off", "0")


def user_config_paths():
    """Candidate user config locations, most specific first (cross-platform)."""
    paths = []
    override = os.environ.get(USER_CONFIG_ENV)
    if override:
        paths.append(os.path.expanduser(override))
    plugin_config_dir = os.environ.get("HERDR_PLUGIN_CONFIG_DIR")
    if plugin_config_dir:
        paths.append(os.path.join(plugin_config_dir, "config.yml"))
    if sys.platform == "win32":
        # Windows: %APPDATA%\herdr\herdr-nerd-font-tab-name.yml
        appdata = os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming")
        paths.append(os.path.join(appdata, "herdr", "herdr-nerd-font-tab-name.yml"))
    else:
        # Unix: XDG_CONFIG_HOME or ~/.config
        xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        paths.append(os.path.join(xdg, "herdr", "herdr-nerd-font-tab-name.yml"))
    return paths


def parse_yaml(text):
    """Parse the flat `section:` / `  key: value` subset used by the config.

    Returns {section: {key: value}}. Values keep their raw string form; the
    Config accessors coerce them.
    """
    sections = {}
    current = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith((" ", "\t")):
            name = line.split(":", 1)[0].strip()
            if name:
                current = sections.setdefault(name, {})
            continue
        if current is None or ":" not in line:
            continue
        key, value = line.split(":", 1)
        current[key.strip()] = _clean_value(value)
    return sections


def _clean_value(value):
    value = value.strip()
    # A trailing comment only counts when it is separated by whitespace, so an
    # icon that happens to be "#" survives.
    if value[:1] in ("'", '"'):
        quote = value[0]
        end = value.find(quote, 1)
        if end != -1:
            return value[1:end]
    hash_at = value.find(" #")
    if hash_at != -1:
        value = value[:hash_at].rstrip()
    return value


def _read(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return parse_yaml(handle.read())
    except (OSError, UnicodeDecodeError):
        return {}


class Config:
    """Merged view of the user config over the shipped defaults."""

    def __init__(self, user=None, defaults=None):
        self.user = user or {}
        self.defaults = defaults or {}

    @classmethod
    def load(cls, default_path=None, user_path=None):
        defaults = _read(default_path or DEFAULT_CONFIG_PATH)
        if user_path is None:
            for candidate in user_config_paths():
                if os.path.isfile(candidate):
                    user_path = candidate
                    break
        user = _read(user_path) if user_path else {}
        return cls(user=user, defaults=defaults)

    def get(self, section, key, fallback=None):
        for source in (self.user, self.defaults):
            value = source.get(section, {}).get(key)
            if value is not None and value != "":
                return value
        return fallback

    def section(self, name):
        """Defaults for a section, with user entries layered on top."""
        merged = dict(self.defaults.get(name, {}))
        merged.update(self.user.get(name, {}))
        return merged

    def bool(self, key, fallback=False):
        value = self.get("config", key)
        if value is None:
            return fallback
        value = value.strip().lower()
        if value in _TRUE:
            return True
        if value in _FALSE:
            return False
        return fallback

    def float(self, key, fallback=0.0):
        try:
            return float(self.get("config", key, fallback))
        except (TypeError, ValueError):
            return fallback

    def option(self, key, fallback=""):
        """A config value, with the literal string "null" meaning unset."""
        value = self.get("config", key, fallback)
        if value is None or value == "null":
            return ""
        return value

    def tristate(self, key, fallback="auto"):
        """A value that may be true, false, or "auto"."""
        value = (self.get("config", key, fallback) or "").strip().lower()
        if value in _TRUE:
            return True
        if value in _FALSE:
            return False
        return "auto"