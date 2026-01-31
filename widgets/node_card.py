"""Node card widget for the nodes list."""

from datetime import datetime
from textual.app import ComposeResult
from textual.widgets import Static, ListItem
from textual.containers import Horizontal, Vertical, Grid
from textual.message import Message as TextualMessage

from db.models import Node
from .contact_item import node_id_to_color


def format_last_heard(timestamp: int) -> str:
    """Format last heard time as relative time."""
    if not timestamp:
        return "Never"

    now = datetime.now()
    dt = datetime.fromtimestamp(timestamp)
    delta = now - dt

    if delta.total_seconds() < 60:
        return "now"
    elif delta.total_seconds() < 3600:
        mins = int(delta.total_seconds() / 60)
        return f"{mins}m ago"
    elif delta.total_seconds() < 86400:
        hours = int(delta.total_seconds() / 3600)
        return f"{hours}h ago"
    else:
        days = int(delta.total_seconds() / 86400)
        return f"{days}d ago"


def snr_to_bars(snr: float) -> str:
    """Convert SNR to signal strength bars."""
    if snr is None:
        return "\u2581\u2581\u2581\u2581"  # All low

    # SNR ranges: <-10 = 1 bar, -10 to 0 = 2 bars, 0 to 10 = 3 bars, >10 = 4 bars
    if snr < -10:
        return "\u2583\u2581\u2581\u2581"
    elif snr < 0:
        return "\u2583\u2585\u2581\u2581"
    elif snr < 10:
        return "\u2583\u2585\u2587\u2581"
    else:
        return "\u2583\u2585\u2587\u2589"


def battery_to_icon(level: int) -> str:
    """Convert battery level to icon."""
    if level is None:
        return ""
    if level > 100:
        return "\u26a1"  # Lightning bolt (powered)
    elif level > 75:
        return "\u2588\u2588\u2588\u2588"
    elif level > 50:
        return "\u2588\u2588\u2588\u2591"
    elif level > 25:
        return "\u2588\u2588\u2591\u2591"
    elif level > 10:
        return "\u2588\u2591\u2591\u2591"
    else:
        return "\u2591\u2591\u2591\u2591"


class NodeCard(ListItem):
    """A list item representing a mesh network node."""

    class Selected(TextualMessage):
        """Message sent when this node is selected."""
        def __init__(self, node: Node):
            self.node = node
            super().__init__()

    class MessageRequested(TextualMessage):
        """Message sent when user wants to message this node."""
        def __init__(self, node: Node):
            self.node = node
            super().__init__()

    DEFAULT_CSS = """
    NodeCard {
        height: 4;
        padding: 0 1;
    }

    NodeCard > Horizontal {
        height: 100%;
        width: 100%;
    }

    NodeCard .color-chip {
        width: 2;
        height: 3;
        margin-right: 1;
        content-align: center middle;
    }

    NodeCard .node-info {
        width: 1fr;
        height: 100%;
    }

    NodeCard .node-name {
        width: 100%;
        height: 1;
        text-style: bold;
    }

    NodeCard .node-model {
        width: 100%;
        height: 1;
        color: $text-muted;
    }

    NodeCard .node-stats {
        width: auto;
        height: 100%;
        padding-left: 1;
    }

    NodeCard .signal-bars {
        width: auto;
        height: 1;
        color: $success;
    }

    NodeCard .battery-level {
        width: auto;
        height: 1;
    }

    NodeCard .battery-level.low {
        color: $error;
    }

    NodeCard .battery-level.medium {
        color: $warning;
    }

    NodeCard .battery-level.high {
        color: $success;
    }

    NodeCard .battery-level.powered {
        color: $accent;
    }

    NodeCard .last-heard {
        width: auto;
        min-width: 8;
        height: 1;
        color: $text-muted;
        text-align: right;
    }

    NodeCard .role-badge {
        width: auto;
        height: 1;
        padding: 0 1;
        background: $primary 30%;
        color: $text;
    }

    NodeCard .role-badge.router {
        background: $warning 30%;
    }

    NodeCard .role-badge.repeater {
        background: $success 30%;
    }

    NodeCard .favorite-star {
        width: 2;
        height: 1;
        color: $warning;
    }

    NodeCard .favorite-star.hidden {
        display: none;
    }

    NodeCard:hover {
        background: $accent 20%;
    }

    NodeCard.-highlight {
        background: $accent;
    }

    NodeCard.online .node-name {
        color: $success;
    }

    NodeCard.offline .node-name {
        color: $text-muted;
    }
    """

    def __init__(self, node: Node, is_online: bool = False, is_my_node: bool = False, **kwargs):
        """Initialize the node card."""
        super().__init__(**kwargs)
        self.node = node
        self.is_online = is_online
        self.is_my_node = is_my_node

        if is_online:
            self.add_class("online")
        else:
            self.add_class("offline")

    def compose(self) -> ComposeResult:
        """Create the node card layout."""
        with Horizontal():
            # Color chip
            yield Static("\u2588", classes="color-chip", markup=False)

            # Node info
            with Vertical(classes="node-info"):
                # Name with star for own node
                name = self.node.display_name
                if self.is_my_node:
                    name = f"\u2605 {name}"
                yield Static(name, classes="node-name")

                # Model and role
                with Horizontal():
                    model = self.node.hw_model or "Unknown"
                    if len(model) > 15:
                        model = model[:12] + "..."
                    yield Static(model, classes="node-model")

                    # Role badge
                    role = self.node.role or "CLIENT"
                    role_class = "role-badge"
                    if "ROUTER" in role:
                        role_class += " router"
                    elif "REPEATER" in role:
                        role_class += " repeater"
                    yield Static(role, classes=role_class)

            # Stats column
            with Vertical(classes="node-stats"):
                # Signal strength
                signal = snr_to_bars(self.node.snr)
                yield Static(signal, classes="signal-bars")

                # Battery
                battery = battery_to_icon(self.node.battery_level)
                battery_class = "battery-level"
                if self.node.battery_level:
                    if self.node.battery_level > 100:
                        battery_class += " powered"
                    elif self.node.battery_level > 50:
                        battery_class += " high"
                    elif self.node.battery_level > 20:
                        battery_class += " medium"
                    else:
                        battery_class += " low"
                yield Static(battery, classes=battery_class)

            # Last heard
            last_heard = format_last_heard(self.node.last_heard)
            yield Static(last_heard, classes="last-heard")

            # Favorite star
            star_class = "favorite-star"
            if not self.node.is_favorite:
                star_class += " hidden"
            yield Static("\u2605", classes=star_class)

    def on_mount(self) -> None:
        """Apply the color to the chip after mounting."""
        color = node_id_to_color(self.node.node_id)
        chip = self.query_one(".color-chip", Static)
        chip.styles.color = color

    def update_node(self, node: Node, is_online: bool = None) -> None:
        """Update the displayed node information."""
        self.node = node

        if is_online is not None:
            self.is_online = is_online
            if is_online:
                self.remove_class("offline")
                self.add_class("online")
            else:
                self.remove_class("online")
                self.add_class("offline")

        # Update name
        name = node.display_name
        if self.is_my_node:
            name = f"\u2605 {name}"
        self.query_one(".node-name", Static).update(name)

        # Update model
        model = node.hw_model or "Unknown"
        if len(model) > 15:
            model = model[:12] + "..."
        self.query_one(".node-model", Static).update(model)

        # Update signal
        signal = snr_to_bars(node.snr)
        self.query_one(".signal-bars", Static).update(signal)

        # Update battery
        battery = battery_to_icon(node.battery_level)
        battery_widget = self.query_one(".battery-level", Static)
        battery_widget.update(battery)

        # Update last heard
        last_heard = format_last_heard(node.last_heard)
        self.query_one(".last-heard", Static).update(last_heard)

        # Update favorite
        star = self.query_one(".favorite-star", Static)
        if node.is_favorite:
            star.remove_class("hidden")
        else:
            star.add_class("hidden")
