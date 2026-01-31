"""Conversations tab for viewing all contacts."""

import re
from textual.app import ComposeResult
from textual.widgets import Static, ListView, ListItem
from textual.containers import Vertical
from textual.message import Message as TextualMessage
from textual import on

from db.models import Contact
from widgets.contact_item import ContactItem


def sanitize_id(contact_key: str) -> str:
    """Sanitize a contact key to be a valid Textual widget ID."""
    # Replace any non-alphanumeric characters (except hyphen/underscore) with underscore
    return re.sub(r'[^a-zA-Z0-9_-]', '_', contact_key)


class ConversationsTab(Vertical):
    """Tab showing list of conversations sorted by recent activity."""

    class ConversationSelected(TextualMessage):
        """Message sent when a conversation is selected."""
        def __init__(self, contact: Contact):
            self.contact = contact
            super().__init__()

    DEFAULT_CSS = """
    ConversationsTab {
        width: 100%;
        height: 100%;
    }

    ConversationsTab #conversations-list {
        width: 100%;
        height: 100%;
    }

    ConversationsTab #no-conversations {
        width: 100%;
        height: 100%;
        content-align: center middle;
        color: $text-muted;
    }

    ConversationsTab .section-header {
        width: 100%;
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
        text-style: bold;
    }
    """

    def __init__(self, **kwargs):
        """Initialize the conversations tab."""
        super().__init__(**kwargs)
        self.contacts: list[Contact] = []
        self._contact_items: dict[str, ContactItem] = {}

    def compose(self) -> ComposeResult:
        """Create the conversations list."""
        yield ListView(id="conversations-list")
        yield Static("No conversations yet", id="no-conversations")

    def on_mount(self) -> None:
        """Set up the tab when mounted."""
        # Don't hide anything initially - let the layout compute sizes first
        # Visibility will be updated when data is loaded
        pass

    def _update_visibility(self) -> None:
        """Update visibility of list vs empty message."""
        list_view = self.query_one("#conversations-list", ListView)
        no_convos = self.query_one("#no-conversations", Static)

        if self.contacts:
            list_view.display = True
            no_convos.display = False
        else:
            list_view.display = False
            no_convos.display = True

        # Force layout refresh after display changes
        self.refresh(layout=True)

    async def load_contacts(self, contacts: list[Contact]) -> None:
        """Load contacts into the list."""
        self.contacts = contacts
        list_view = self.query_one("#conversations-list", ListView)

        # Clear existing items
        await list_view.clear()
        self._contact_items.clear()

        # Separate channels and DMs
        channels = [c for c in contacts if c.is_channel]
        dms = [c for c in contacts if not c.is_channel]

        # Add channels first
        if channels:
            for contact in channels:
                item = ContactItem(contact, id=f"contact-{sanitize_id(contact.contact_key)}")
                self._contact_items[contact.contact_key] = item
                await list_view.append(item)

        # Add DMs
        if dms:
            for contact in dms:
                item = ContactItem(contact, id=f"contact-{sanitize_id(contact.contact_key)}")
                self._contact_items[contact.contact_key] = item
                await list_view.append(item)

        self._update_visibility()

    async def update_contact(self, contact: Contact) -> None:
        """Update a single contact in the list."""
        if contact.contact_key in self._contact_items:
            self._contact_items[contact.contact_key].update_contact(contact)
        else:
            # New contact - add to appropriate position
            list_view = self.query_one("#conversations-list", ListView)
            item = ContactItem(contact, id=f"contact-{sanitize_id(contact.contact_key)}")
            self._contact_items[contact.contact_key] = item

            # Insert at the top (most recent)
            if list_view.children:
                await list_view.mount(item, before=list_view.children[0])
            else:
                await list_view.append(item)

            self.contacts.insert(0, contact)
            self._update_visibility()

    def get_selected_contact(self) -> Contact | None:
        """Get the currently selected contact."""
        list_view = self.query_one("#conversations-list", ListView)
        if list_view.highlighted_child and isinstance(list_view.highlighted_child, ContactItem):
            return list_view.highlighted_child.contact
        return None

    @on(ListView.Selected, "#conversations-list")
    def on_contact_selected(self, event: ListView.Selected) -> None:
        """Handle contact selection."""
        if isinstance(event.item, ContactItem):
            self.post_message(self.ConversationSelected(event.item.contact))
