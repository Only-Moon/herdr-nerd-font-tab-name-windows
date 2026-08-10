"""Turning "what is running in this tab" into a single icon."""

import os
import re

SEM_VERSION = re.compile(r"^[0-9]+\.[0-9]+(\.[0-9]+)?$")

# Commands that only ever wrap another command; the wrapped one is the
# interesting part. `sudo` is deliberately absent — upstream gives it its own
# icon and that reads better than the command it is elevating.
WRAPPERS = ("env", "nohup", "setsid", "stdbuf", "time", "nice", "command")


class Resolver:
    """Resolves icons for panes, backed by the merged config."""

    def __init__(self, config):
        self.config = config
        self.icons = config.section("icons")
        self.agents = config.section("agents")

    # -- vocabulary -------------------------------------------------------

    def vocabulary(self):
        """Every glyph this resolver can emit.

        Used to recognise (and strip) an icon we previously wrote into a tab
        label, so a manual rename is never mistaken for one of our own.
        """
        glyphs = set(self.icons.values()) | set(self.agents.values())
        for key in ("fallback-icon", "multi-pane-icon", "sem-version-icon", "agent-fallback-icon"):
            value = self.config.option(key)
            if value:
                glyphs.add(value)
        glyphs.discard("")
        return glyphs

    # -- lookup -----------------------------------------------------------

    def by_name(self, name):
        """Icon for a command name, or None."""
        if not name:
            return None
        return self.icons.get(name) or self.icons.get(name.lower())

    def by_cwd(self, cwd):
        """Icon for a working directory folder name, or None."""
        if not cwd:
            return None
        # Get the final folder name from the path
        folder = os.path.basename(os.path.normpath(cwd))
        if not folder:
            return None
        # Try exact match first, then lowercase
        return self.icons.get(folder) or self.icons.get(folder.lower())

    def by_agent(self, agent):
        """Icon for a herdr-detected agent id, or None."""
        if not agent:
            return None
        key = agent.strip().lower()
        return self.agents.get(key) or self.icons.get(key) or self.config.option("agent-fallback-icon") or None

    def command_name(self, process):
        """The name to look up for a foreground process entry."""
        if not process:
            return None
        name = process.get("name") or ""
        if not self.config.bool("use-argv0", True):
            return name or None
        argv0 = os.path.basename(process.get("argv0") or "")
        if argv0 and argv0 != name and self.by_name(argv0):
            return argv0
        return name or None

    def foreground_name(self, processes):
        """Pick the command name that best describes a pane's foreground.

        herdr reports the foreground process group innermost first, so the
        first entry is the command actually in front of you: `man ls` reports
        `[less, sh, sh]` and the pager is what you want to see.
        """
        for process in processes or []:
            name = self.command_name(process)
            if not name:
                continue
            if name in WRAPPERS:
                argv = process.get("argv") or []
                for candidate in argv[1:]:
                    base = os.path.basename(candidate)
                    if base and not base.startswith("-"):
                        return base
            return name
        return None

    # -- resolution -------------------------------------------------------

    def title_name(self, title):
        """A command name guessed from a pane's terminal title.

        Only used when herdr reports no foreground process — some panes (a
        detached tty, a process herdr cannot inspect) have nothing else to go
        on, and shells commonly title the window after the running command.
        """
        for word in (title or "").split():
            name = os.path.basename(word)
            if self.by_name(name):
                return name
        return None

    def resolve(self, agent=None, processes=None, label=None, title=None, cwd=None):
        """Return (icon, is_fallback) for a pane.

        Order: herdr's detected agent, then the foreground command, then the
        working directory folder, then the pane title, then a semantic-version
        icon for version-looking labels, then the fallback.
        """
        if agent and self.config.bool("prefer-agent-icons", True):
            icon = self.by_agent(agent)
            if icon:
                return icon, False

        icon = self.by_name(self.foreground_name(processes))
        if icon:
            return icon, False

        # Try folder-based icon from cwd
        icon = self.by_cwd(cwd)
        if icon:
            return icon, False

        if not self.config.bool("prefer-agent-icons", True) and agent:
            icon = self.by_agent(agent)
            if icon:
                return icon, False

        icon = self.by_name(self.title_name(title))
        if icon:
            return icon, False

        sem_icon = self.config.option("sem-version-icon")
        if sem_icon and label and SEM_VERSION.match(label.strip()):
            return sem_icon, False

        return self.config.option("fallback-icon", "?"), True