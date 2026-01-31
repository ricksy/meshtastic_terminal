"""Messages tab for viewing and sending messages in a conversation."""

from textual.app import ComposeResult
from textual.widgets import Static, Input, Button, ListView, ListItem
from textual.containers import Vertical, Horizontal, VerticalScroll
from textual.message import Message as TextualMessage
from textual import on

from db.models import Message, Contact, MessageStatus
from widgets.message_bubble import MessageBubble


class NodeListItem(ListItem):
    """A list item showing a node in the conversation."""

    def __init__(self, node_id: str, name: str, **kwargs):
        super().__init__(**kwargs)
        self.node_id = node_id
        self.node_name = name

    def compose(self) -> ComposeResult:
        yield Static(self.node_name or self.node_id)


class MessagesTab(Vertical):
    """Tab showing messages for a selected conversation."""

    class MessageSendRequested(TextualMessage):
        """Message sent when user wants to send a message."""
        def __init__(self, content: str, contact_key: str, reply_to: int = None):
            self.content = content
            self.contact_key = contact_key
            self.reply_to = reply_to
            super().__init__()

    DEFAULT_CSS = """
    MessagesTab {
        width: 100%;
        height: 100%;
    }

    MessagesTab #messages-header {
        width: 100%;
        height: 3;
        background: $surface;
        border-bottom: solid $primary;
        padding: 1;
    }

    MessagesTab #contact-title {
        width: 1fr;
        height: 1;
        text-style: bold;
    }

    MessagesTab #main-content {
        width: 100%;
        height: 1fr;
    }

    MessagesTab #chat-area {
        width: 1fr;
        height: 100%;
    }

    MessagesTab #nodes-panel {
        width: 20;
        height: 100%;
        background: $surface;
        border-left: solid $primary;
    }

    MessagesTab #nodes-header {
        width: 100%;
        height: 2;
        background: $primary 20%;
        padding: 0 1;
        text-style: bold;
    }

    MessagesTab #nodes-list {
        width: 100%;
        height: 1fr;
    }

    MessagesTab #nodes-list ListItem {
        height: 2;
        padding: 0 1;
    }

    MessagesTab #messages-scroll {
        width: 100%;
        height: 1fr;
    }

    MessagesTab #messages-container {
        width: 100%;
        height: auto;
        padding: 1;
    }

    MessagesTab #no-messages {
        width: 100%;
        height: 100%;
        content-align: center middle;
        color: $text-muted;
    }

    MessagesTab #no-conversation {
        width: 100%;
        height: 100%;
        content-align: center middle;
        color: $text-muted;
    }

    MessagesTab #input-bar {
        width: 100%;
        height: auto;
        background: $surface;
        border-top: solid $primary;
        padding: 1;
    }

    MessagesTab #reply-preview {
        width: 100%;
        height: auto;
        background: $surface;
        border-left: thick $accent;
        padding: 0 1;
        margin-bottom: 1;
    }

    MessagesTab #reply-preview.hidden {
        display: none;
    }

    MessagesTab #message-input {
        width: 1fr;
        border: solid $primary;
        background: $surface;
        padding: 0 1;
    }

    MessagesTab #send-button {
        width: auto;
        min-width: 8;
        margin-left: 1;
    }
    """

    def __init__(self, my_node_id: str = None, **kwargs):
        """Initialize the messages tab."""
        super().__init__(**kwargs)
        self.my_node_id = my_node_id
        self.current_contact: Contact | None = None
        self.messages: list[Message] = []
        self._message_bubbles: dict[int, MessageBubble] = {}
        self._reply_to_message: Message | None = None
        self._participants: dict[str, str] = {}  # node_id -> name

    def compose(self) -> ComposeResult:
        """Create the messages view."""
        # Header showing current conversation
        with Horizontal(id="messages-header"):
            yield Static("Select a conversation", id="contact-title")

        # No conversation selected message
        yield Static(
            "Select a conversation from the Conversations tab (press 1)",
            id="no-conversation"
        )

        # Main content with chat and nodes panel
        with Horizontal(id="main-content"):
            # Chat area (messages + input)
            with Vertical(id="chat-area"):
                # Messages scroll area
                with VerticalScroll(id="messages-scroll"):
                    yield Vertical(id="messages-container")

                # No messages placeholder
                yield Static("No messages yet. Send the first message!", id="no-messages")

                # Input bar
                with Vertical(id="input-bar"):
                    # Reply preview
                    yield Static("", id="reply-preview", classes="hidden")

                    # Input row
                    with Horizontal():
                        yield Input(placeholder="Type a message...", id="message-input")
                        yield Button("Send", id="send-button", variant="primary")

            # Nodes panel (right side)
            with Vertical(id="nodes-panel"):
                yield Static("Participants", id="nodes-header")
                yield ListView(id="nodes-list")

    def on_mount(self) -> None:
        """Set up the tab when mounted."""
        self._update_visibility()

    def _update_visibility(self) -> None:
        """Update visibility based on current state."""
        no_convo = self.query_one("#no-conversation", Static)
        main_content = self.query_one("#main-content", Horizontal)
        scroll = self.query_one("#messages-scroll", VerticalScroll)
        no_msgs = self.query_one("#no-messages", Static)
        input_bar = self.query_one("#input-bar", Vertical)

        if self.current_contact is None:
            no_convo.display = True
            main_content.display = False
        else:
            no_convo.display = False
            main_content.display = True

            if not self.messages:
                scroll.display = False
                no_msgs.display = True
            else:
                scroll.display = True
                no_msgs.display = False

            input_bar.display = True

        # Force layout refresh after display changes
        self.refresh(layout=True)

    def set_contact(self, contact: Contact | None) -> None:
        """Set the current conversation contact."""
        self.current_contact = contact
        self.messages = []
        self._message_bubbles.clear()
        self._reply_to_message = None
        self._participants.clear()

        # Update header
        title = self.query_one("#contact-title", Static)
        if contact:
            name = contact.display_name or contact.contact_key
            if contact.is_channel:
                name = f"# {name}"
            title.update(name)
        else:
            title.update("Select a conversation")

        # Clear messages container
        container = self.query_one("#messages-container", Vertical)
        container.remove_children()

        # Clear nodes list
        nodes_list = self.query_one("#nodes-list", ListView)
        nodes_list.clear()

        # Clear reply preview
        self._clear_reply()

        self._update_visibility()

    async def load_messages(self, messages: list[Message], node_names: dict[str, str] = None) -> None:
        """Load messages into the view."""
        self.messages = messages
        self._message_bubbles.clear()
        node_names = node_names or {}
        self._participants = node_names.copy()

        container = self.query_one("#messages-container", Vertical)
        container.remove_children()

        # Update participants panel
        await self._update_participants_panel()

        # Messages come in reverse chronological order, so reverse them
        for msg in reversed(messages):
            await self._add_message_bubble(msg, node_names)

        self._update_visibility()

        # Scroll to bottom
        scroll = self.query_one("#messages-scroll", VerticalScroll)
        scroll.scroll_end(animate=False)

    async def _update_participants_panel(self) -> None:
        """Update the participants list panel."""
        nodes_list = self.query_one("#nodes-list", ListView)
        await nodes_list.clear()

        for node_id, name in self._participants.items():
            display_name = name or node_id
            item = NodeListItem(node_id, display_name)
            await nodes_list.append(item)

    async def add_message(self, message: Message, sender_name: str = None) -> None:
        """Add a new message to the view."""
        self.messages.insert(0, message)  # Add to front (newest)

        # Update participants if new sender
        if message.from_node_id and message.from_node_id not in self._participants:
            self._participants[message.from_node_id] = sender_name or message.from_node_id
            await self._update_participants_panel()

        await self._add_message_bubble(message, {message.from_node_id: sender_name} if sender_name else {})

        self._update_visibility()

        # Scroll to bottom
        scroll = self.query_one("#messages-scroll", VerticalScroll)
        scroll.scroll_end(animate=False)

    async def _add_message_bubble(self, message: Message, node_names: dict[str, str]) -> None:
        """Add a message bubble to the container."""
        container = self.query_one("#messages-container", Vertical)

        is_outgoing = message.from_node_id == self.my_node_id
        sender_name = node_names.get(message.from_node_id) or message.from_node_id

        # Determine if we should show sender (for group chats)
        show_sender = self.current_contact and self.current_contact.is_channel

        bubble = MessageBubble(
            message,
            is_outgoing=is_outgoing,
            sender_name=sender_name,
            show_sender=show_sender,
            id=f"msg-{message.id or message.packet_id or id(message)}",
        )

        self._message_bubbles[message.packet_id or id(message)] = bubble
        await container.mount(bubble)

    def update_message_status(self, packet_id: int, status: MessageStatus) -> None:
        """Update the status of a message."""
        if packet_id in self._message_bubbles:
            self._message_bubbles[packet_id].update_status(status)

    def _set_reply(self, message: Message) -> None:
        """Set the message being replied to."""
        self._reply_to_message = message
        preview = self.query_one("#reply-preview", Static)

        # Show preview
        content = message.content[:50] + "..." if len(message.content) > 50 else message.content
        preview.update(f"\u21a9 Replying to: {content}")
        preview.remove_class("hidden")

        # Focus input
        input_widget = self.query_one("#message-input", Input)
        input_widget.focus()

    def _clear_reply(self) -> None:
        """Clear the reply state."""
        self._reply_to_message = None
        try:
            preview = self.query_one("#reply-preview", Static)
            preview.update("")
            preview.add_class("hidden")
        except Exception:
            pass

    @on(MessageBubble.Clicked)
    def on_bubble_clicked(self, event: MessageBubble.Clicked) -> None:
        """Handle message bubble click to reply."""
        # Don't reply to our own messages
        if event.message.from_node_id != self.my_node_id:
            self._set_reply(event.message)

    @on(Input.Submitted, "#message-input")
    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle message submission."""
        self._send_message()

    @on(Button.Pressed, "#send-button")
    def on_send_pressed(self, event: Button.Pressed) -> None:
        """Handle send button press."""
        self._send_message()

    def _send_message(self) -> None:
        """Send the current message."""
        if not self.current_contact:
            return

        input_widget = self.query_one("#message-input", Input)
        content = input_widget.value.strip()

        if not content:
            return

        # Get reply ID if replying
        reply_to = self._reply_to_message.packet_id if self._reply_to_message else None

        # Post the send request
        self.post_message(self.MessageSendRequested(
            content=content,
            contact_key=self.current_contact.contact_key,
            reply_to=reply_to,
        ))

        # Clear input and reply state
        input_widget.value = ""
        self._clear_reply()

    def focus_input(self) -> None:
        """Focus the message input."""
        if self.current_contact:
            input_widget = self.query_one("#message-input", Input)
            input_widget.focus()
