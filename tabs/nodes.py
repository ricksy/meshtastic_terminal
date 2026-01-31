"""Nodes tab for viewing mesh network nodes."""

import re
import time
from textual.app import ComposeResult
from textual.widgets import Static, ListView, Input, Button, Select
from textual.containers import Vertical, Horizontal
from textual.message import Message as TextualMessage
from textual import on

from db.models import Node
from widgets.node_card import NodeCard


def sanitize_id(node_id: str) -> str:
    """Sanitize a node ID to be a valid Textual widget ID."""
    return re.sub(r'[^a-zA-Z0-9_-]', '_', node_id)


class NodesTab(Vertical):
    """Tab showing list of mesh network nodes."""

    class NodeSelected(TextualMessage):
        """Message sent when a node is selected for details."""
        def __init__(self, node: Node):
            self.node = node
            super().__init__()

    class MessageNodeRequested(TextualMessage):
        """Message sent when user wants to message a node."""
        def __init__(self, node: Node):
            self.node = node
            super().__init__()

    DEFAULT_CSS = """
    NodesTab {
        width: 100%;
        height: 100%;
    }

    NodesTab #filter-bar {
        width: 100%;
        height: 3;
        background: $surface;
        border-bottom: solid $primary;
        padding: 0 1;
    }

    NodesTab #search-input {
        width: 1fr;
    }

    NodesTab #filter-online {
        width: auto;
        min-width: 12;
        margin-left: 1;
    }

    NodesTab #filter-favorites {
        width: auto;
        min-width: 12;
        margin-left: 1;
    }

    NodesTab #sort-select {
        width: 15;
        margin-left: 1;
    }

    NodesTab #nodes-list {
        width: 100%;
        height: 1fr;
    }

    NodesTab #no-nodes {
        width: 100%;
        height: 100%;
        content-align: center middle;
        color: $text-muted;
    }

    NodesTab #node-count {
        width: 100%;
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
        border-top: solid $primary;
    }

    NodesTab .filter-button {
        border: none;
        background: $surface;
    }

    NodesTab .filter-button.active {
        background: $primary;
        color: $background;
    }
    """

    SORT_OPTIONS = [
        ("name", "Name"),
        ("last_heard", "Last Seen"),
        ("snr", "Signal"),
    ]

    def __init__(self, my_node_id: str = None, **kwargs):
        """Initialize the nodes tab."""
        super().__init__(**kwargs)
        self.my_node_id = my_node_id
        self.nodes: list[Node] = []
        self._node_cards: dict[str, NodeCard] = {}
        self._filter_online = False
        self._filter_favorites = False
        self._search_query = ""
        self._sort_by = "last_heard"

    def compose(self) -> ComposeResult:
        """Create the nodes view."""
        # Filter bar
        with Horizontal(id="filter-bar"):
            yield Input(placeholder="Search nodes...", id="search-input")
            yield Button("Online", id="filter-online", classes="filter-button")
            yield Button("\u2605 Favorites", id="filter-favorites", classes="filter-button")
            yield Select(
                [(label, value) for value, label in self.SORT_OPTIONS],
                value="last_heard",
                id="sort-select",
                allow_blank=False,
            )

        # Nodes list
        yield ListView(id="nodes-list")

        # No nodes message
        yield Static("No nodes found", id="no-nodes")

        # Count footer
        yield Static("0 nodes", id="node-count")

    def on_mount(self) -> None:
        """Set up the tab when mounted."""
        self._update_visibility()

    def _update_visibility(self) -> None:
        """Update visibility based on filtered nodes."""
        list_view = self.query_one("#nodes-list", ListView)
        no_nodes = self.query_one("#no-nodes", Static)

        filtered = self._get_filtered_nodes()
        if filtered:
            list_view.display = True
            no_nodes.display = False
        else:
            list_view.display = False
            no_nodes.display = True

        # Update count
        total = len(self.nodes)
        shown = len(filtered)
        count_text = f"{shown} of {total} nodes" if shown != total else f"{total} nodes"
        self.query_one("#node-count", Static).update(count_text)

    def _get_filtered_nodes(self) -> list[Node]:
        """Get nodes filtered by current criteria."""
        filtered = self.nodes.copy()

        # Apply online filter
        if self._filter_online:
            cutoff = int(time.time()) - 900  # 15 minutes
            filtered = [n for n in filtered if n.last_heard and n.last_heard > cutoff]

        # Apply favorites filter
        if self._filter_favorites:
            filtered = [n for n in filtered if n.is_favorite]

        # Apply search
        if self._search_query:
            query = self._search_query.lower()
            filtered = [
                n for n in filtered
                if query in (n.long_name or "").lower()
                or query in (n.short_name or "").lower()
                or query in n.node_id.lower()
            ]

        # Apply sorting
        if self._sort_by == "name":
            filtered.sort(key=lambda n: (n.display_name or "").lower())
        elif self._sort_by == "last_heard":
            filtered.sort(key=lambda n: n.last_heard or 0, reverse=True)
        elif self._sort_by == "snr":
            filtered.sort(key=lambda n: n.snr or -999, reverse=True)

        # Always put our own node first
        if self.my_node_id:
            our_node = None
            other_nodes = []
            for n in filtered:
                if n.node_id == self.my_node_id:
                    our_node = n
                else:
                    other_nodes.append(n)
            if our_node:
                filtered = [our_node] + other_nodes

        return filtered

    def _is_online(self, node: Node) -> bool:
        """Check if a node is considered online."""
        if not node.last_heard:
            return False
        cutoff = int(time.time()) - 900  # 15 minutes
        return node.last_heard > cutoff

    async def load_nodes(self, nodes: list[Node]) -> None:
        """Load nodes into the list."""
        self.nodes = nodes
        await self._rebuild_list()

    async def _rebuild_list(self) -> None:
        """Rebuild the nodes list with current filters."""
        list_view = self.query_one("#nodes-list", ListView)
        await list_view.clear()
        self._node_cards.clear()

        filtered = self._get_filtered_nodes()

        for node in filtered:
            is_online = self._is_online(node)
            is_my_node = node.node_id == self.my_node_id
            card = NodeCard(
                node,
                is_online=is_online,
                is_my_node=is_my_node,
                id=f"node-{sanitize_id(node.node_id)}",
            )
            self._node_cards[node.node_id] = card
            await list_view.append(card)

        self._update_visibility()

    async def update_node(self, node: Node) -> None:
        """Update a single node in the list."""
        # Update in our list
        found = False
        for i, n in enumerate(self.nodes):
            if n.node_id == node.node_id:
                self.nodes[i] = node
                found = True
                break

        if not found:
            self.nodes.append(node)

        # Update card if visible
        if node.node_id in self._node_cards:
            self._node_cards[node.node_id].update_node(node, self._is_online(node))
        else:
            # May need to add to list if filter changed
            await self._rebuild_list()

        self._update_visibility()

    def get_selected_node(self) -> Node | None:
        """Get the currently selected node."""
        list_view = self.query_one("#nodes-list", ListView)
        if list_view.highlighted_child and isinstance(list_view.highlighted_child, NodeCard):
            return list_view.highlighted_child.node
        return None

    @on(Input.Changed, "#search-input")
    def on_search_changed(self, event: Input.Changed) -> None:
        """Handle search input change."""
        self._search_query = event.value
        self.run_worker(self._rebuild_list())

    @on(Button.Pressed, "#filter-online")
    def on_filter_online(self, event: Button.Pressed) -> None:
        """Toggle online filter."""
        self._filter_online = not self._filter_online
        button = self.query_one("#filter-online", Button)
        if self._filter_online:
            button.add_class("active")
        else:
            button.remove_class("active")
        self.run_worker(self._rebuild_list())

    @on(Button.Pressed, "#filter-favorites")
    def on_filter_favorites(self, event: Button.Pressed) -> None:
        """Toggle favorites filter."""
        self._filter_favorites = not self._filter_favorites
        button = self.query_one("#filter-favorites", Button)
        if self._filter_favorites:
            button.add_class("active")
        else:
            button.remove_class("active")
        self.run_worker(self._rebuild_list())

    @on(Select.Changed, "#sort-select")
    def on_sort_changed(self, event: Select.Changed) -> None:
        """Handle sort selection change."""
        self._sort_by = event.value
        self.run_worker(self._rebuild_list())

    @on(ListView.Selected, "#nodes-list")
    def on_node_selected(self, event: ListView.Selected) -> None:
        """Handle node selection."""
        if isinstance(event.item, NodeCard):
            self.post_message(self.NodeSelected(event.item.node))
