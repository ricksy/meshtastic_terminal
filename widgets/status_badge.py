"""Status badge widget for message delivery indicators."""

from textual.widgets import Static
from db.models import MessageStatus


def get_status_icon(status: MessageStatus) -> str:
    """Get the icon for a message status."""
    icons = {
        MessageStatus.QUEUED: "\u23f3",    # Hourglass
        MessageStatus.ENROUTE: "\u2713",   # Check mark (single)
        MessageStatus.RECEIVED: "\u2713",  # Check mark (single)
        MessageStatus.ACKED: "\u2713\u2713",  # Double check mark
        MessageStatus.FAILED: "\u2717",    # X mark
    }
    return icons.get(status, "")


def get_status_color(status: MessageStatus) -> str:
    """Get the color class for a message status."""
    colors = {
        MessageStatus.QUEUED: "status-queued",
        MessageStatus.ENROUTE: "status-enroute",
        MessageStatus.RECEIVED: "status-received",
        MessageStatus.ACKED: "status-acked",
        MessageStatus.FAILED: "status-failed",
    }
    return colors.get(status, "")


class StatusBadge(Static):
    """Widget displaying message delivery status."""

    DEFAULT_CSS = """
    StatusBadge {
        width: auto;
        height: auto;
        padding: 0 1;
    }

    StatusBadge.status-queued {
        color: $text-muted;
    }

    StatusBadge.status-enroute {
        color: $warning;
    }

    StatusBadge.status-received {
        color: $success;
    }

    StatusBadge.status-acked {
        color: $success;
    }

    StatusBadge.status-failed {
        color: $error;
    }
    """

    def __init__(self, status: MessageStatus, **kwargs):
        """Initialize the status badge."""
        super().__init__(get_status_icon(status), **kwargs)
        self._status = status
        self.add_class(get_status_color(status))

    @property
    def status(self) -> MessageStatus:
        """Get the current status."""
        return self._status

    def update_status(self, status: MessageStatus) -> None:
        """Update the displayed status."""
        # Remove old status class
        self.remove_class(get_status_color(self._status))

        # Update status
        self._status = status

        # Add new status class and update text
        self.add_class(get_status_color(status))
        self.update(get_status_icon(status))
