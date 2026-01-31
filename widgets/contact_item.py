"""Contact item widget for the conversations list."""

from datetime import datetime
from textual.app import ComposeResult
from textual.widgets import Static, ListItem
from textual.containers import Horizontal
from textual.message import Message as TextualMessage

from db.models import Contact


def node_id_to_color(node_id: str) -> str:
    """Generate a consistent color from a node ID."""
    if not node_id or node_id.startswith("^"):
        # Channel - use a neutral color
        return "#6e6e6e"

    # Hash the node ID to get RGB values
    hash_val = hash(node_id)
    r = (hash_val & 0xFF0000) >> 16
    g = (hash_val & 0x00FF00) >> 8
    b = hash_val & 0x0000FF

    # Ensure colors are bright enough to be visible
    r = max(80, min(220, r))
    g = max(80, min(220, g))
    b = max(80, min(220, b))

    return f"#{r:02x}{g:02x}{b:02x}"


def format_relative_time(timestamp: int) -> str:
    """Format a timestamp as relative time."""
    if not timestamp:
        return ""

    now = datetime.now()
    dt = datetime.fromtimestamp(timestamp)
    delta = now - dt

    if delta.total_seconds() < 60:
        return "now"
    elif delta.total_seconds() < 3600:
        mins = int(delta.total_seconds() / 60)
        return f"{mins}m"
    elif delta.total_seconds() < 86400:
        hours = int(delta.total_seconds() / 3600)
        return f"{hours}h"
    elif delta.total_seconds() < 604800:  # 7 days
        days = int(delta.total_seconds() / 86400)
        return f"{days}d"
    else:
        return dt.strftime("%m/%d")


class ContactItem(ListItem):
    """A list item representing a conversation contact."""

    class Selected(TextualMessage):
        """Message sent when this contact is selected."""
        def __init__(self, contact: Contact):
            self.contact = contact
            super().__init__()

    DEFAULT_CSS = """
    ContactItem {
        height: 3;
        padding: 0 1;
    }

    ContactItem > Horizontal {
        height: 100%;
        width: 100%;
    }

    ContactItem .color-chip {
        width: 2;
        height: 1;
        margin-right: 1;
        content-align: center middle;
    }

    ContactItem .contact-name {
        width: 1fr;
        height: 1;
    }

    ContactItem .last-message {
        width: 1fr;
        height: 1;
        color: $text-muted;
    }

    ContactItem .time-stamp {
        width: auto;
        min-width: 5;
        height: 1;
        color: $text-muted;
        text-align: right;
    }

    ContactItem .unread-badge {
        width: auto;
        min-width: 3;
        height: 1;
        background: $primary;
        color: $background;
        text-align: center;
        margin-left: 1;
    }

    ContactItem .unread-badge.hidden {
        display: none;
    }

    ContactItem:hover {
        background: $accent 20%;
    }

    ContactItem.-highlight {
        background: $accent;
    }
    """

    def __init__(self, contact: Contact, **kwargs):
        """Initialize the contact item."""
        super().__init__(**kwargs)
        self.contact = contact

    def compose(self) -> ComposeResult:
        """Create the contact item layout."""
        with Horizontal():
            # Color chip
            color = node_id_to_color(self.contact.node_id or self.contact.contact_key)
            yield Static("\u2588", classes="color-chip", markup=False)

            # Contact info container
            with Horizontal():
                # Name
                name = self.contact.display_name or self.contact.contact_key
                if self.contact.is_channel:
                    name = f"#{name}"
                yield Static(name, classes="contact-name")

                # Last message preview
                preview = self.contact.last_message_text or ""
                if len(preview) > 30:
                    preview = preview[:27] + "..."
                yield Static(preview, classes="last-message")

            # Time
            time_str = format_relative_time(self.contact.last_message_time)
            yield Static(time_str, classes="time-stamp")

            # Unread badge
            badge_class = "unread-badge"
            if self.contact.unread_count == 0:
                badge_class += " hidden"
            yield Static(
                str(self.contact.unread_count) if self.contact.unread_count > 0 else "",
                classes=badge_class,
            )

    def on_mount(self) -> None:
        """Apply the color to the chip after mounting."""
        color = node_id_to_color(self.contact.node_id or self.contact.contact_key)
        chip = self.query_one(".color-chip", Static)
        chip.styles.color = color

    def update_contact(self, contact: Contact) -> None:
        """Update the displayed contact information."""
        self.contact = contact

        # Update name
        name = contact.display_name or contact.contact_key
        if contact.is_channel:
            name = f"#{name}"
        self.query_one(".contact-name", Static).update(name)

        # Update preview
        preview = contact.last_message_text or ""
        if len(preview) > 30:
            preview = preview[:27] + "..."
        self.query_one(".last-message", Static).update(preview)

        # Update time
        time_str = format_relative_time(contact.last_message_time)
        self.query_one(".time-stamp", Static).update(time_str)

        # Update unread badge
        badge = self.query_one(".unread-badge", Static)
        if contact.unread_count > 0:
            badge.update(str(contact.unread_count))
            badge.remove_class("hidden")
        else:
            badge.update("")
            badge.add_class("hidden")
