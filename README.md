# herdr-nerd-font-tab-name (HNT)

Nerd Font icons for [herdr](https://herdr.dev) tabs. Replaces tab numbers and names with a Nerd Font icon for whatever is running in the tab.

Key operational characteristics:
- Event-driven on Windows (no persistent daemon), persistent watcher on Unix
- Cross-platform: Windows, macOS, Linux
- Dynamic icon updates on pane focus with 2s cooldown

## Table of Contents

- [Requirements](#requirements)
- [Quick Start](#quick-start)
- [Environment Configuration](#environment-configuration)
- [Configuration](#configuration)
- [Commands](#commands)
- [How It Works](#how-it-works)
- [Development](#development)
- [License](#license)

## Requirements

- herdr 0.7.0 or newer
- A [Nerd Font](https://www.nerdfonts.com/) in your terminal
- Python 3.8+

## Quick Start

```sh
# Install from GitHub
herdr plugin install Only-Moon/herdr-nerd-font-tab-name-windows

# Or from a local checkout
git clone https://github.com/Only-Moon/herdr-nerd-font-tab-name-windows.git
herdr plugin link /path/to/herdr-nerd-font-tab-name-windows

# Restart herdr or start the watcher
herdr plugin action invoke herdr-nerd-font-tab-name.restart
```

## Environment Configuration

### Required application secrets

None.

### Infra-tunable runtime values

| Variable | Default | Description |
|---|---|---|
| `HERDR_NERD_FONT_TAB_NAME_CONFIG` | (none) | Custom config file path |
| `HERDR_SESSION` | (auto) | Herdr session name |
| `HERDR_SOCKET_PATH` | (auto) | Herdr socket path |

### Optional feature toggles / external integrations

None.

## Configuration

Create the config file at:

- **Unix**: `~/.config/herdr/herdr-nerd-font-tab-name.yml`
- **Windows**: `%APPDATA%\herdr\herdr-nerd-font-tab-name.yml`

Only the keys you want to change; the rest fall back to [`config/defaults.yml`](config/defaults.yml).

```yml
config:
  show-name: "auto"        # auto | true | false
  icon-position: "left"    # left | right
  fallback-icon: "?"
  multi-pane-icon: ""     # blank disables
  poll-interval: 2        # cooldown seconds for cwd change detection

icons:
  zsh: ""                 # override anything from the defaults
  cmatrix: "🤯"            # or add your own — emoji work fine

agents:
  claude: ""
```

| Key | Default | Meaning |
| --- | ------- | ------- |
| `show-name` | `auto` | `auto` drops tab number, keeps real names |
| `icon-position` | `left` | Which side of the label the icon sits on |
| `fallback-icon` | `?` | Shown when nothing matches |
| `always-show-fallback-name` | `false` | Keep name beside fallback icon when `show-name: false` |
| `multi-pane-icon` | *(blank)* | Prefixed when tab holds >1 pane |
| `sem-version-icon` | `null` | Icon for labels like `1.2.3` |
| `prefer-agent-icons` | `true` | Agent detection wins over process name |
| `agent-fallback-icon` | `󰚩` | Icon for agent with no `agents:` entry |
| `use-argv0` | `true` | `npm run dev` shows npm not node |
| `title-fallback` | `true` | Guess from pane title when no process |
| `poll-interval` | `2` | Seconds cooldown for cwd changes; `0` = events only |
| `rename-auto-tabs-only` | `false` | Only touch auto-numbered tabs |

Config is read on startup, so apply changes with:

```sh
herdr plugin action invoke herdr-nerd-font-tab-name.restart
```

Custom config path:

```sh
export HERDR_NERD_FONT_TAB_NAME_CONFIG=~/dotfiles/herdr-icons.yml
```

## Commands

```sh
bin/herdr-nerd-font-tab-name once            # apply icons once
bin/herdr-nerd-font-tab-name start           # start watcher (Unix)
bin/herdr-nerd-font-tab-name stop --restore  # stop + restore labels
bin/herdr-nerd-font-tab-name restart
bin/herdr-nerd-font-tab-name status
bin/herdr-nerd-font-tab-name icon nvim       # what icon for name?
bin/herdr-nerd-font-tab-name icon claude --agent
```

On Windows, use the `.cmd` wrapper:

```cmd
bin\herdr-nerd-font-tab-name.cmd once
bin\herdr-nerd-font-tab-name.cmd icon nvim
bin\herdr-nerd-font-tab-name.cmd refresh    # event-driven one-shot
```

All honour `HERDR_SESSION` / `HERDR_SOCKET_PATH`.

## How It Works

### Unix (Persistent Watcher)
- `[[startup]]` spawns detached watcher via Unix socket
- `events.subscribe` connection refreshes on events, debounced 150ms
- 2s poll catches changes without events
- `tab.created` hook restarts watcher if it dies

### Windows (Event-Driven One-Shot)
- No persistent daemon — each event hook runs `refresh` and exits
- Uses `herdr` CLI subprocess for API calls (works over named pipes)
- Registers event hooks: `tab.created`, `tab.renamed`, `tab.focused`, `pane.created`, `pane.focused`, `pane.agent_detected`, `pane.agent_status_changed`, `pane.exited`
- State in `%LOCALAPPDATA%\herdr-nerd-font-tab-name\`
- File locking via `portalocker`, PID checks via `psutil`/`tasklist`

**Limitation:** No `pane.cwd_changed` event from herdr. Icon updates on focus events only.
Workaround: manual refresh or switch tabs.

## Development

```sh
make test   # 52 tests, stdlib-only (plus portalocker, psutil for Windows)
make lint
```

Tests cover icon resolution, label composition, folder icons, dynamic cwd updates.
Windows-specific tests run 5x for flakiness detection.

## License

[MIT](LICENSE) for the code here. The icon map and configuration format come
from [tmux-nerd-font-window-name](https://github.com/joshmedeski/tmux-nerd-font-window-name)
by Josh Medeski, which publishes no licence file. No licence claim is made over
that material here; it remains Josh's, and it is included with attribution and
gratitude. If you intend to reuse the icon map itself, take it up with upstream.

---

**Original author**: Rohan Kewalramani (rohankewal/herdr-nerd-font-tab-name)  
**Windows port**: moon (Only-Moon/herdr-nerd-font-tab-name-windows)  
**Upstream icon map**: Josh Medeski (joshmedeski/tmux-nerd-font-window-name)