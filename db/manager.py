"""Async database manager for Meshtastic Terminal."""

import aiosqlite
from pathlib import Path
from typing import Optional, List
import time

from .models import Message, Node, Contact, MessageStatus
from .migrations import migrate_database, create_default_contacts


def get_database_path() -> Path:
    """Get the path to the database file."""
    data_dir = Path.home() / ".local" / "share" / "meshtastic-terminal"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "meshtastic.db"


class DatabaseManager:
    """Async database manager for Meshtastic Terminal."""

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize the database manager."""
        self.db_path = db_path or get_database_path()
        self.db: Optional[aiosqlite.Connection] = None

    async def initialize(self) -> None:
        """Initialize the database connection and run migrations."""
        self.db = await aiosqlite.connect(self.db_path)
        self.db.row_factory = aiosqlite.Row
        await migrate_database(self.db)
        await create_default_contacts(self.db)

    async def close(self) -> None:
        """Close the database connection."""
        if self.db:
            await self.db.close()
            self.db = None

    # ==================== Message Operations ====================

    async def insert_message(self, message: Message) -> int:
        """Insert a new message and return its ID."""
        cursor = await self.db.execute(
            """INSERT INTO messages
               (packet_id, contact_key, from_node_id, to_node_id, content,
                timestamp, received_time, status, read, hop_count, snr, channel)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                message.packet_id,
                message.contact_key,
                message.from_node_id,
                message.to_node_id,
                message.content,
                message.timestamp,
                message.received_time,
                message.status.value,
                int(message.read),
                message.hop_count,
                message.snr,
                message.channel,
            ),
        )
        await self.db.commit()
        return cursor.lastrowid

    async def get_messages(
        self, contact_key: str, limit: int = 100, offset: int = 0
    ) -> List[Message]:
        """Get messages for a contact, ordered by timestamp descending."""
        async with self.db.execute(
            """SELECT id, packet_id, contact_key, from_node_id, to_node_id,
                      content, timestamp, received_time, status, read,
                      hop_count, snr, channel
               FROM messages
               WHERE contact_key = ?
               ORDER BY timestamp DESC
               LIMIT ? OFFSET ?""",
            (contact_key, limit, offset),
        ) as cursor:
            rows = await cursor.fetchall()
            return [Message.from_row(tuple(row)) for row in rows]

    async def get_all_messages(self, limit: int = 500) -> List[Message]:
        """Get all recent messages across all contacts."""
        async with self.db.execute(
            """SELECT id, packet_id, contact_key, from_node_id, to_node_id,
                      content, timestamp, received_time, status, read,
                      hop_count, snr, channel
               FROM messages
               ORDER BY timestamp DESC
               LIMIT ?""",
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [Message.from_row(tuple(row)) for row in rows]

    async def update_message_status(
        self, packet_id: int, status: MessageStatus
    ) -> bool:
        """Update the status of a message by packet ID."""
        cursor = await self.db.execute(
            "UPDATE messages SET status = ? WHERE packet_id = ?",
            (status.value, packet_id),
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def mark_messages_read(self, contact_key: str) -> int:
        """Mark all messages for a contact as read."""
        cursor = await self.db.execute(
            "UPDATE messages SET read = 1 WHERE contact_key = ? AND read = 0",
            (contact_key,),
        )
        await self.db.commit()

        # Also reset unread count on contact
        await self.db.execute(
            "UPDATE contacts SET unread_count = 0 WHERE contact_key = ?",
            (contact_key,),
        )
        await self.db.commit()

        return cursor.rowcount

    async def get_message_by_packet_id(self, packet_id: int) -> Optional[Message]:
        """Get a message by its packet ID."""
        async with self.db.execute(
            """SELECT id, packet_id, contact_key, from_node_id, to_node_id,
                      content, timestamp, received_time, status, read,
                      hop_count, snr, channel
               FROM messages WHERE packet_id = ?""",
            (packet_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return Message.from_row(tuple(row))
            return None

    # ==================== Node Operations ====================

    async def upsert_node(self, node: Node) -> None:
        """Insert or update a node."""
        now = int(time.time())
        await self.db.execute(
            """INSERT INTO nodes
               (node_id, node_num, long_name, short_name, hw_model, role,
                latitude, longitude, altitude, battery_level, voltage, snr,
                last_heard, first_seen, is_favorite, is_muted)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(node_id) DO UPDATE SET
                   node_num = COALESCE(excluded.node_num, node_num),
                   long_name = COALESCE(excluded.long_name, long_name),
                   short_name = COALESCE(excluded.short_name, short_name),
                   hw_model = COALESCE(excluded.hw_model, hw_model),
                   role = COALESCE(excluded.role, role),
                   latitude = COALESCE(excluded.latitude, latitude),
                   longitude = COALESCE(excluded.longitude, longitude),
                   altitude = COALESCE(excluded.altitude, altitude),
                   battery_level = COALESCE(excluded.battery_level, battery_level),
                   voltage = COALESCE(excluded.voltage, voltage),
                   snr = COALESCE(excluded.snr, snr),
                   last_heard = COALESCE(excluded.last_heard, last_heard)""",
            (
                node.node_id,
                node.node_num,
                node.long_name,
                node.short_name,
                node.hw_model,
                node.role,
                node.latitude,
                node.longitude,
                node.altitude,
                node.battery_level,
                node.voltage,
                node.snr,
                node.last_heard or now,
                node.first_seen or now,
                int(node.is_favorite),
                int(node.is_muted),
            ),
        )
        await self.db.commit()

    async def get_nodes(
        self, online_only: bool = False, favorites_only: bool = False
    ) -> List[Node]:
        """Get all nodes, optionally filtered."""
        query = """SELECT node_id, node_num, long_name, short_name, hw_model, role,
                          latitude, longitude, altitude, battery_level, voltage, snr,
                          last_heard, first_seen, is_favorite, is_muted
                   FROM nodes WHERE 1=1"""
        params = []

        if online_only:
            # Consider nodes online if heard within last 15 minutes
            cutoff = int(time.time()) - 900
            query += " AND last_heard > ?"
            params.append(cutoff)

        if favorites_only:
            query += " AND is_favorite = 1"

        query += " ORDER BY last_heard DESC"

        async with self.db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [Node.from_row(tuple(row)) for row in rows]

    async def get_node(self, node_id: str) -> Optional[Node]:
        """Get a specific node by ID."""
        async with self.db.execute(
            """SELECT node_id, node_num, long_name, short_name, hw_model, role,
                      latitude, longitude, altitude, battery_level, voltage, snr,
                      last_heard, first_seen, is_favorite, is_muted
               FROM nodes WHERE node_id = ?""",
            (node_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return Node.from_row(tuple(row))
            return None

    async def set_node_favorite(self, node_id: str, is_favorite: bool) -> None:
        """Set the favorite status of a node."""
        await self.db.execute(
            "UPDATE nodes SET is_favorite = ? WHERE node_id = ?",
            (int(is_favorite), node_id),
        )
        await self.db.commit()

    async def set_node_muted(self, node_id: str, is_muted: bool) -> None:
        """Set the muted status of a node."""
        await self.db.execute(
            "UPDATE nodes SET is_muted = ? WHERE node_id = ?",
            (int(is_muted), node_id),
        )
        await self.db.commit()

    # ==================== Contact Operations ====================

    async def get_contacts(self) -> List[Contact]:
        """Get all contacts sorted by last message time."""
        async with self.db.execute(
            """SELECT contact_key, display_name, last_message_time, last_message_text,
                      unread_count, message_count, mute_until, node_id
               FROM contacts
               ORDER BY last_message_time DESC NULLS LAST"""
        ) as cursor:
            rows = await cursor.fetchall()
            return [Contact.from_row(tuple(row)) for row in rows]

    async def get_contact(self, contact_key: str) -> Optional[Contact]:
        """Get a specific contact by key."""
        async with self.db.execute(
            """SELECT contact_key, display_name, last_message_time, last_message_text,
                      unread_count, message_count, mute_until, node_id
               FROM contacts WHERE contact_key = ?""",
            (contact_key,),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return Contact.from_row(tuple(row))
            return None

    async def update_contact_on_message(
        self,
        contact_key: str,
        message_text: str,
        timestamp: int,
        is_incoming: bool = True,
        display_name: Optional[str] = None,
        node_id: Optional[str] = None,
    ) -> None:
        """Update contact metadata when a message is sent/received."""
        # First, get current contact or create it
        contact = await self.get_contact(contact_key)

        if contact:
            # Update existing contact
            unread_increment = 1 if is_incoming else 0
            await self.db.execute(
                """UPDATE contacts SET
                       last_message_time = ?,
                       last_message_text = ?,
                       unread_count = unread_count + ?,
                       message_count = message_count + 1,
                       display_name = COALESCE(?, display_name),
                       node_id = COALESCE(?, node_id)
                   WHERE contact_key = ?""",
                (
                    timestamp,
                    message_text[:100],  # Truncate preview
                    unread_increment,
                    display_name,
                    node_id,
                    contact_key,
                ),
            )
        else:
            # Create new contact
            await self.db.execute(
                """INSERT INTO contacts
                   (contact_key, display_name, last_message_time, last_message_text,
                    unread_count, message_count, node_id)
                   VALUES (?, ?, ?, ?, ?, 1, ?)""",
                (
                    contact_key,
                    display_name,
                    timestamp,
                    message_text[:100],
                    1 if is_incoming else 0,
                    node_id,
                ),
            )

        await self.db.commit()

    async def get_unread_count(self, contact_key: Optional[str] = None) -> int:
        """Get total unread count, optionally for a specific contact."""
        if contact_key:
            async with self.db.execute(
                "SELECT unread_count FROM contacts WHERE contact_key = ?",
                (contact_key,),
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0
        else:
            async with self.db.execute(
                "SELECT SUM(unread_count) FROM contacts"
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] or 0

    async def mute_contact(self, contact_key: str, until: int = 0) -> None:
        """Mute a contact until a specific timestamp (0 = forever, -1 = unmute)."""
        await self.db.execute(
            "UPDATE contacts SET mute_until = ? WHERE contact_key = ?",
            (until, contact_key),
        )
        await self.db.commit()

    # ==================== Settings Operations ====================

    async def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get a setting value."""
        async with self.db.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else default

    async def set_setting(self, key: str, value: str) -> None:
        """Set a setting value."""
        await self.db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )
        await self.db.commit()

    async def delete_setting(self, key: str) -> None:
        """Delete a setting."""
        await self.db.execute("DELETE FROM settings WHERE key = ?", (key,))
        await self.db.commit()
