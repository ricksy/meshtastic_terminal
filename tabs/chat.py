"""Chat tab combining conversations list and messages view."""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message as TextualMessage
from textual import on

from .conversations import ConversationsTab
from .messages import MessagesTab
from db.models import Contact, Message, MessageStatus


class ChatTab(Vertical):
    """Combined chat view with conversations sidebar and messages panel."""

    class MessageSendRequested(TextualMessage):
        """Message sent when user wants to send a message."""
        def __init__(self, content: str, contact_key: str, reply_to: int = None):
            self.content = content
            self.contact_key = contact_key
            self.reply_to = reply_to
            super().__init__()

    DEFAULT_CSS = """
    ChatTab {
        width: 100%;
        height: 100%;
    }

    ChatTab #chat-split {
        width: 100%;
        height: 100%;
    }

    ChatTab #conversations-sidebar {
        width: 30;
        height: 100%;
        border-right: solid $primary;
    }

    ChatTab #messages-panel {
        width: 1fr;
        height: 100%;
    }
    """

    def __init__(self, my_node_id: str = None, **kwargs):
        super().__init__(**kwargs)
        self.my_node_id = my_node_id

    def compose(self) -> ComposeResult:
        """Create the split chat view."""
        with Horizontal(id="chat-split"):
            # Left sidebar - conversations list
            with Vertical(id="conversations-sidebar"):
                yield ConversationsTab(id="conversations-list")

            # Right panel - messages
            yield MessagesTab(id="messages-panel", my_node_id=self.my_node_id)

    def on_mount(self) -> None:
        """Focus the conversations list on mount."""
        convos = self.query_one("#conversations-list", ConversationsTab)
        convos.focus_list()

    @on(ConversationsTab.ConversationSelected)
    def on_conversation_selected(self, event: ConversationsTab.ConversationSelected) -> None:
        """Handle conversation selection - update messages panel."""
        messages_panel = self.query_one("#messages-panel", MessagesTab)
        messages_panel.set_contact(event.contact)
        # Don't bubble this event - we handle it here
        event.stop()
        # Post our own event for the main app to load messages
        self.post_message(self.ConversationSelected(event.contact))

    class ConversationSelected(TextualMessage):
        """Message sent when a conversation is selected in the chat tab."""
        def __init__(self, contact: Contact):
            self.contact = contact
            super().__init__()

    @on(MessagesTab.MessageSendRequested)
    def on_message_send_requested(self, event: MessagesTab.MessageSendRequested) -> None:
        """Forward message send request to main app."""
        self.post_message(self.MessageSendRequested(
            content=event.content,
            contact_key=event.contact_key,
            reply_to=event.reply_to,
        ))
        event.stop()

    # Delegate methods to child components
    async def load_contacts(self, contacts: list[Contact]) -> None:
        """Load contacts into the conversations list."""
        convos = self.query_one("#conversations-list", ConversationsTab)
        await convos.load_contacts(contacts)

    async def update_contact(self, contact: Contact) -> None:
        """Update a contact in the list."""
        convos = self.query_one("#conversations-list", ConversationsTab)
        await convos.update_contact(contact)

    def set_contact(self, contact: Contact | None) -> None:
        """Set the current contact in the messages panel."""
        messages_panel = self.query_one("#messages-panel", MessagesTab)
        messages_panel.set_contact(contact)

    async def load_messages(self, messages: list[Message], node_names: dict[str, str] = None) -> None:
        """Load messages into the messages panel."""
        messages_panel = self.query_one("#messages-panel", MessagesTab)
        await messages_panel.load_messages(messages, node_names)

    async def add_message(self, message: Message, sender_name: str = None) -> None:
        """Add a new message to the messages panel."""
        messages_panel = self.query_one("#messages-panel", MessagesTab)
        await messages_panel.add_message(message, sender_name)

    def update_message_status(self, packet_id: int, status: MessageStatus) -> None:
        """Update message status in the messages panel."""
        messages_panel = self.query_one("#messages-panel", MessagesTab)
        messages_panel.update_message_status(packet_id, status)

    def focus_input(self) -> None:
        """Focus the message input."""
        messages_panel = self.query_one("#messages-panel", MessagesTab)
        messages_panel.focus_input()

    def focus_conversations(self) -> None:
        """Focus the conversations list."""
        convos = self.query_one("#conversations-list", ConversationsTab)
        convos.focus_list()

    def get_selected_contact(self) -> Contact | None:
        """Get the currently selected contact."""
        convos = self.query_one("#conversations-list", ConversationsTab)
        return convos.get_selected_contact()

    @property
    def current_contact(self) -> Contact | None:
        """Get the current contact from messages panel."""
        messages_panel = self.query_one("#messages-panel", MessagesTab)
        return messages_panel.current_contact

    def set_my_node_id(self, node_id: str) -> None:
        """Set the node ID for message display."""
        self.my_node_id = node_id
        messages_panel = self.query_one("#messages-panel", MessagesTab)
        messages_panel.my_node_id = node_id
