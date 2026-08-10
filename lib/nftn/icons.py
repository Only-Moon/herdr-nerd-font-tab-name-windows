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
        # Build normalized lookup maps for case-insensitive matching
        self._icons = config.section("icons")
        self._agents = config.section("agents")
        # Build normalized lookup: lowercase key -> icon
        self._icon_map = {k.lower(): v for k, v in self._icons.items()}
        self._agent_map = {k.lower(): v for k, v in self._agents.items()}
        # Folder name normalization: map common variations
        self._folder_aliases = {
            'download': 'downloads',
            'document': 'documents',
            'picture': 'pictures',
            'video': 'videos',
            'video': 'videos',
            'music': 'music',
            'audio': 'music',
            'project': 'projects',
            'code': 'projects',
            'src': 'projects',
            'source': 'projects',
            'dev': 'projects',
            'development': 'projects',
            'config': '.config',
            'configuration': '.config',
            'settings': '.config',
            'cache': '.cache',
            'local': '.local',
            'home': 'home',
            'userprofile': 'home',
            'user': 'home',
            'desktop': 'desktop',
            'download': 'downloads',
            'downloads': 'downloads',
            'document': 'documents',
            'documents': 'documents',
            'picture': 'pictures',
            'pictures': 'pictures',
            'image': 'pictures',
            'images': 'pictures',
            'video': 'videos',
            'videos': 'videos',
            'movie': 'videos',
            'movies': 'videos',
            'music': 'music',
            'audio': 'music',
            'song': 'music',
            'songs': 'music',
            'video': 'videos',
            'videos': 'videos',
            'movie': 'videos',
            'movies': 'videos',
            'doc': 'documents',
            'docs': 'documents',
            'pic': 'pictures',
            'pics': 'pictures',
            'img': 'pictures',
            'imgs': 'pictures',
            'vid': 'videos',
            'vids': 'videos',
            'pic': 'pictures',
            'pics': 'pictures',
        }

    @property
    def icons(self):
        """Backward compatibility: return original icons dict."""
        return self._icons

    @property
    def agents(self):
        """Backward compatibility: return original agents dict."""
        return self._agents

    # -- vocabulary -------------------------------------------------------

    def vocabulary(self):
        """Every glyph this resolver can emit.

        Used to recognise (and strip) an icon we previously wrote into a tab
        label, so a manual rename is never mistaken for one of our own.
        """
        glyphs = set(self._icons.values()) | set(self._agents.values())
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
        return self._icon_map.get(name.lower())

    def by_agent(self, agent):
        """Icon for a herdr-detected agent id, or None."""
        if not agent:
            return None
        key = agent.strip().lower()
        return self._agent_map.get(key) or self._icon_map.get(key) or self.config.option("agent-fallback-icon")

    def _normalize_folder(self, folder):
        """Normalize folder name for lookup."""
        if not folder:
            return None
        lower = folder.lower()
        # Check aliases first
        if lower in self._folder_aliases:
            return self._folder_aliases[lower]
        return lower

    def by_cwd(self, cwd):
        """Icon for a working directory, or None.

        Checks the immediate folder name, then walks up the directory tree
        to find project markers or known folder names.
        """
        if not cwd:
            return None

        cwd = os.path.normpath(cwd)

        # 1. Check immediate folder name
        folder = os.path.basename(cwd)
        if folder:
            norm = self._normalize_folder(folder)
            if norm:
                icon = self._icon_map.get(norm)
                if icon:
                    return icon

        # 2. Walk up the directory tree looking for project markers
        # or known folder names
        current = cwd
        while True:
            parent = os.path.dirname(current)
            if parent == current:  # reached root
                break
            current = parent

            folder = os.path.basename(current)
            if not folder:
                continue

            # Check for exact match
            norm = self._normalize_folder(folder)
            if norm:
                icon = self._icon_map.get(norm)
                if icon:
                    return icon

            # Check for project type markers
            marker_icon = self._project_marker_icon(current)
            if marker_icon:
                return marker_icon

        return None

    def _project_marker_icon(self, path):
        """Detect project type from marker files and return appropriate icon."""
        markers = {
            '.git': 'git',
            'package.json': 'npm',
            'Cargo.toml': 'rust',
            'go.mod': 'go',
            'pom.xml': 'maven',
            'build.gradle': 'gradle',
            'requirements.txt': 'python',
            'pyproject.toml': 'python',
            'setup.py': 'python',
            'composer.json': 'php',
            'Gemfile': 'ruby',
            'mix.exs': 'elixir',
            'rebar.config': 'erlang',
            'Makefile': 'make',
            'CMakeLists.txt': 'cmake',
            'docker-compose.yml': 'docker',
            'Dockerfile': 'docker',
            'docker-compose.yaml': 'docker',
            '.github': 'github',
            '.gitlab': 'gitlab',
            '.vscode': 'vscode',
            '.idea': 'intellij',
        }

        for marker, icon_key in markers.items():
            marker_path = os.path.join(path, marker)
            if os.path.exists(marker_path):
                icon = self._icon_map.get(icon_key.lower())
                if icon:
                    return icon
        return None

    def by_agent(self, agent):
        """Icon for a herdr-detected agent id, or None."""
        if not agent:
            return None
        key = agent.strip().lower()
        return self._agent_map.get(key) or self._icon_map.get(key) or self.config.option("agent-fallback-icon") or None

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