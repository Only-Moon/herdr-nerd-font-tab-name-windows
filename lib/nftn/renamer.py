"""One pass of "look at every tab, give it the right icon"."""

from . import labels
from .client import HerdrError


class Renamer:
    """Computes and applies tab labels for a herdr session.

    Takes a connection-like object so tests can drive it with a fake.
    """

    def __init__(self, connection, config, resolver, store):
        self.connection = connection
        self.config = config
        self.resolver = resolver
        self.store = store
        self.vocabulary = resolver.vocabulary()

    # -- pane selection ---------------------------------------------------

    def primary_pane(self, tab_id, panes, layouts):
        """The pane whose contents the tab's icon should describe.

        The tab's own focused pane if the layout snapshot names one, otherwise
        the first pane in the tab.
        """
        in_tab = [pane for pane in panes if pane.get("tab_id") == tab_id]
        if not in_tab:
            return None
        by_id = {pane.get("pane_id"): pane for pane in in_tab}
        for layout in layouts or []:
            if layout.get("tab_id") != tab_id:
                continue
            focused = by_id.get(layout.get("focused_pane_id"))
            if focused:
                return focused
        for pane in in_tab:
            if pane.get("focused"):
                return pane
        return in_tab[0]

    # -- label computation ------------------------------------------------

    def label_for(self, tab, pane):
        """The label a tab should have, or None to leave it alone."""
        number = tab.get("number", "")
        current = tab.get("label") or ""
        is_auto = labels.is_auto_label(current, number)
        remembered = self.store.get(tab.get("tab_id"))

        if self.config.bool("rename-auto-tabs-only", False):
            # A tab we already renamed still counts as auto-labelled if its
            # remembered base is the tab number.
            owned_auto = remembered and labels.is_auto_label(remembered.get("base"), number)
            if not is_auto and not owned_auto:
                return None

        base = labels.base_label(tab, remembered, self.vocabulary)
        icon, is_fallback = self.resolver.resolve(
            agent=pane.get("agent") or pane.get("display_agent"),
            processes=self.processes_for(pane),
            label=base,
            title=self.title_of(pane),
            cwd=pane.get("foreground_cwd") or pane.get("cwd"),
        )
        return labels.compose(
            icon,
            base,
            self.config,
            is_fallback=is_fallback,
            is_auto=labels.is_auto_label(base, number),
            pane_count=tab.get("pane_count", 1),
        ), base

    def processes_for(self, pane):
        """Foreground processes for a pane, or [] when herdr cannot report them."""
        agent = pane.get("agent") or pane.get("display_agent")
        if agent and self.config.bool("prefer-agent-icons", True):
            # An agent match wins outright; skip the extra round-trip.
            if self.resolver.by_agent(agent):
                return []
        try:
            info = self.connection.process_info(pane["pane_id"])
        except (OSError, HerdrError):
            return []
        return info.get("foreground_processes") or []

    def title_of(self, pane):
        """The pane's terminal title, used only when no process is reported."""
        if not self.config.bool("title-fallback", True):
            return None
        return pane.get("terminal_title_stripped") or pane.get("terminal_title")

    # -- the pass ---------------------------------------------------------

    def refresh(self):
        """Bring every tab's label up to date. Returns the renames applied."""
        snapshot = self.connection.snapshot()
        tabs = snapshot.get("tabs", [])
        panes = snapshot.get("panes", [])
        layouts = snapshot.get("layouts", [])

        applied = []
        for tab in tabs:
            pane = self.primary_pane(tab.get("tab_id"), panes, layouts)
            if pane is None:
                continue
            computed = self.label_for(tab, pane)
            if computed is None:
                continue
            label, base = computed
            if label == (tab.get("label") or ""):
                self.store.remember(tab["tab_id"], base, label)
                continue
            try:
                self.connection.rename_tab(tab["tab_id"], label)
            except HerdrError:
                # A tab can close between the snapshot and the rename.
                continue
            self.store.remember(tab["tab_id"], base, label)
            applied.append((tab["tab_id"], label))

        self.store.prune({tab.get("tab_id") for tab in tabs})
        self.store.save()
        return applied

    def restore(self):
        """Put every remembered base label back and forget our state."""
        snapshot = self.connection.snapshot()
        restored = []
        for tab in snapshot.get("tabs", []):
            remembered = self.store.get(tab.get("tab_id"))
            if not remembered:
                continue
            base = remembered.get("base")
            if base and (tab.get("label") or "") != base:
                try:
                    self.connection.rename_tab(tab["tab_id"], base)
                    restored.append((tab["tab_id"], base))
                except HerdrError:
                    pass
            self.store.forget(tab["tab_id"])
        self.store.save()
        return restored
