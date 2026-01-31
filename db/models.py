"""Data models for Meshtastic Terminal database."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import time


class MessageStatus(Enum):
    """Status of a message."""
    QUEUED = "queued"
    ENROUTE = "enroute"
    RECEIVED = "received"
    ACKED = "acked"
    FAILED = "failed"


@dataclass
class Message:
    """Represents a message in the database."""
    id: Optional[int] = None
    packet_id: Optional[int] = None
    contact_key: str = ""  # "0^all" (broadcast) or "0!nodeId" (DM)
    from_node_id: str = ""
    to_node_id: Optional[str] = None
    content: str = ""
    timestamp: int = field(default_factory=lambda: int(time.time()))
    received_time: int = field(default_factory=lambda: int(time.time()))
    status: MessageStatus = MessageStatus.RECEIVED
    read: bool = False
    hop_count: int = 0
    snr: Optional[float] = None
    channel: int = 0

    @classmethod
    def from_row(cls, row: tuple) -> "Message":
        """Create a Message from a database row."""
        return cls(
            id=row[0],
            packet_id=row[1],
            contact_key=row[2],
            from_node_id=row[3],
            to_node_id=row[4],
            content=row[5],
            timestamp=row[6],
            received_time=row[7],
            status=MessageStatus(row[8]) if row[8] else MessageStatus.RECEIVED,
            read=bool(row[9]),
            hop_count=row[10] or 0,
            snr=row[11],
            channel=row[12] or 0,
        )


@dataclass
class Node:
    """Represents a node in the mesh network."""
    node_id: str = ""
    node_num: Optional[int] = None
    long_name: Optional[str] = None
    short_name: Optional[str] = None
    hw_model: Optional[str] = None
    role: str = "CLIENT"
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude: Optional[int] = None
    battery_level: Optional[int] = None
    voltage: Optional[float] = None
    snr: Optional[float] = None
    last_heard: Optional[int] = None
    first_seen: Optional[int] = None
    is_favorite: bool = False
    is_muted: bool = False

    @classmethod
    def from_row(cls, row: tuple) -> "Node":
        """Create a Node from a database row."""
        return cls(
            node_id=row[0],
            node_num=row[1],
            long_name=row[2],
            short_name=row[3],
            hw_model=row[4],
            role=row[5] or "CLIENT",
            latitude=row[6],
            longitude=row[7],
            altitude=row[8],
            battery_level=row[9],
            voltage=row[10],
            snr=row[11],
            last_heard=row[12],
            first_seen=row[13],
            is_favorite=bool(row[14]),
            is_muted=bool(row[15]),
        )

    @property
    def display_name(self) -> str:
        """Get the best display name for this node."""
        if self.long_name:
            return self.long_name
        if self.short_name:
            return self.short_name
        return self.node_id


@dataclass
class Contact:
    """Represents a conversation contact (node or channel)."""
    contact_key: str = ""  # "0^all" (broadcast ch 0), "0!nodeId" (DM on ch 0)
    display_name: Optional[str] = None
    last_message_time: Optional[int] = None
    last_message_text: Optional[str] = None
    unread_count: int = 0
    message_count: int = 0
    mute_until: int = 0
    node_id: Optional[str] = None  # Associated node ID for DMs

    @classmethod
    def from_row(cls, row: tuple) -> "Contact":
        """Create a Contact from a database row."""
        return cls(
            contact_key=row[0],
            display_name=row[1],
            last_message_time=row[2],
            last_message_text=row[3],
            unread_count=row[4] or 0,
            message_count=row[5] or 0,
            mute_until=row[6] or 0,
            node_id=row[7],
        )

    @property
    def is_channel(self) -> bool:
        """Check if this contact is a channel (broadcast)."""
        return "^" in self.contact_key

    @property
    def channel_number(self) -> Optional[int]:
        """Get channel number if this is a channel contact."""
        if not self.is_channel:
            return None
        try:
            return int(self.contact_key.split("^")[0])
        except (ValueError, IndexError):
            return None

    @classmethod
    def make_channel_key(cls, channel: int) -> str:
        """Create a contact key for a channel."""
        return f"{channel}^all"

    @classmethod
    def make_dm_key(cls, channel: int, node_id: str) -> str:
        """Create a contact key for a direct message."""
        return f"{channel}{node_id}"
