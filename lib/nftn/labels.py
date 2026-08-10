"""Composing tab labels, and recovering the user's own label from ours.

tmux regenerates a window name from scratch on every redraw, so the upstream
plugin never has to worry about clobbering anything. herdr tab labels are
persistent state that the user also edits, so this module keeps track of the
"base" label — what the tab would be called without us — and only ever writes
`icon + base`.
"""


def is_auto_label(label, number):
    """True when the label is still herdr's generated tab number."""
    return (label or "").strip() == str(number)


def strip_icons(label, vocabulary):
    """Remove leading/trailing glyphs that we could have written."""
    parts = (label or "").split()
    while parts and parts[0] in vocabulary:
        parts.pop(0)
    while parts and parts[-1] in vocabulary:
        parts.pop()
    return " ".join(parts)


def base_label(tab, remembered, vocabulary):
    """Work out the label a tab should carry underneath its icon.

    `remembered` is the state we stored last time we renamed this tab, or None.
    When the tab's current label is exactly what we last wrote, the stored base
    is still authoritative. Anything else means the label changed behind our
    back — a manual rename — so we take the new label as the base, minus any
    icon of ours that survived the edit.
    """
    label = tab.get("label") or ""
    if remembered and remembered.get("applied") == label:
        return remembered.get("base", label)

    base = strip_icons(label, vocabulary)
    if not base:
        base = str(tab.get("number", ""))
    return base


def compose(icon, base, config, is_fallback=False, is_auto=False, pane_count=1, duplicate_count=0):
    """Build the final tab label from an icon and the tab's base label."""
    multi = config.option("multi-pane-icon")
    if pane_count > 1 and multi:
        icon = "{} {}".format(multi, icon)

    show_name = config.tristate("show-name", "auto")
    if show_name == "auto":
        show_name = not is_auto
    if not show_name and is_fallback and config.bool("always-show-fallback-name", False):
        show_name = True

    if not show_name or not base:
        return icon
    if config.option("icon-position", "left") == "right":
        return "{} {}".format(base, icon)
    return "{} {}".format(icon, base)
