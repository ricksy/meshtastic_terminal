"""Message bubble widget for chat view."""

from datetime import datetime
from textual.app import ComposeResult
from textual.widgets import Static
from textual.containers import Horizontal, Vertical
from textual.message import Message as TextualMessage

from db.models import Message, MessageStatus
from .status_badge import get_status_icon
from .contact_item import node_id_to_color


class MessageBubble(Static):
    """A chat message bubble widget."""

    class Clicked(TextualMessage):
        """Message sent when this bubble is clicked."""
        def __init__(self, message: Message):
            self.message = message
            super().__init__()

    DEFAULT_CSS = """
    MessageBubble {
        width: 100%;
        height: auto;
        padding: 0 1;
        margin: 1 0;
    }

    MessageBubble.outgoing {
        align: right top;
    }

    MessageBubble.incoming {
        align: left top;
    }

    MessageBubble > Vertical {
        width: auto;
        max-width: 80%;
        height: auto;
        padding: 1;
        border: round $primary;
    }

    MessageBubble.outgoing > Vertical {
        border: round $success;
        background: $success 10%;
    }

    MessageBubble.incoming > Vertical {
        border: round $primary;
        background: $primary 10%;
    }

    MessageBubble .sender-name {
        width: auto;
        height: 1;
        text-style: bold;
        margin-bottom: 0;
    }

    MessageBubble .message-content {
        width: auto;
        height: auto;
    }

    MessageBubble .message-footer {
        width: 100%;
        height: 1;
        margin-top: 0;
    }

    MessageBubble .message-time {
        width: auto;
        height: 1;
        color: $text-muted;
    }

    MessageBubble .message-status {
        width: auto;
        height: 1;
        margin-left: 1;
    }

    MessageBubble .message-status.status-queued {
        color: $text-muted;
    }

    MessageBubble .message-status.status-enroute,
    MessageBubble .message-status.status-received {
        color: $warning;
    }

    MessageBubble .message-status.status-acked {
        color: $success;
    }

    MessageBubble .message-status.status-failed {
        color: $error;
    }

    MessageBubble .reply-preview {
        width: auto;
        height: auto;
        color: $text-muted;
        text-style: italic;
        border-left: thick $accent;
        padding-left: 1;
        margin-bottom: 1;
    }

    MessageBubble:hover {
        background: $surface;
    }
    """

    def __init__(
        self,
        message: Message,
        is_outgoing: bool = False,
        sender_name: str = None,
        show_sender: bool = True,
        reply_preview: str = None,
        **kwargs
    ):
        """Initialize the message bubble."""
        super().__init__(**kwargs)
        self.message = message
        self.is_outgoing = is_outgoing
        self.sender_name = sender_name or message.from_node_id
        self.show_sender = show_sender
        self.reply_preview = reply_preview

        if is_outgoing:
            self.add_class("outgoing")
        else:
            self.add_class("incoming")

    def compose(self) -> ComposeResult:
        """Create the message bubble layout."""
        with Vertical():
            # Reply preview if present
            if self.reply_preview:
                yield Static(f"\u21a9 {self.reply_preview}", classes="reply-preview")

            # Sender name (only for incoming messages in groups)
            if self.show_sender and not self.is_outgoing:
                yield Static(self.sender_name, classes="sender-name")

            # Message content
            content = self.message.content
            # Handle reply indicator in content
            if content.startswith("\u21a9 "):
                content = content[2:]  # Remove reply arrow, shown separately
            yield Static(content, classes="message-content")

            # Footer with time and status
            with Horizontal(classes="message-footer"):
                # Time
                dt = datetime.fromtimestamp(self.message.timestamp)
                time_str = dt.strftime("%H:%M")
                yield Static(time_str, classes="message-time")

                # Status indicator (only for outgoing)
                if self.is_outgoing:
                    status_icon = get_status_icon(self.message.status)
                    status_class = f"message-status status-{self.message.status.value}"
                    yield Static(status_icon, classes=status_class)

    def on_mount(self) -> None:
        """Apply sender color after mounting."""
        if self.show_sender and not self.is_outgoing:
            color = node_id_to_color(self.message.from_node_id)
            try:
                name_widget = self.query_one(".sender-name", Static)
                name_widget.styles.color = color
            except Exception:
                pass

    def on_click(self) -> None:
        """Handle click to initiate reply."""
        self.post_message(self.Clicked(self.message))

    def update_status(self, status: MessageStatus) -> None:
        """Update the message status indicator."""
        self.message.status = status
        if self.is_outgoing:
            try:
                status_widget = self.query_one(".message-status", Static)
                # Remove old status classes
                for s in MessageStatus:
                    status_widget.remove_class(f"status-{s.value}")
                # Add new status class
                status_widget.add_class(f"status-{status.value}")
                status_widget.update(get_status_icon(status))
            except Exception:
                pass
