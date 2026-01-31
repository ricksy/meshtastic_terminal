"""Database schema and migrations for Meshtastic Terminal."""

import aiosqlite
from typing import Optional

CURRENT_SCHEMA_VERSION = 1

# Initial schema creation
SCHEMA_V1 = """
-- Messages table
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    packet_id INTEGER UNIQUE,
    contact_key TEXT NOT NULL,
    from_node_id TEXT NOT NULL,
    to_node_id TEXT,
    content TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    received_time INTEGER NOT NULL,
    status TEXT DEFAULT 'received',
    read INTEGER DEFAULT 0,
    hop_count INTEGER DEFAULT 0,
    snr REAL,
    channel INTEGER DEFAULT 0
);

-- Nodes table
CREATE TABLE IF NOT EXISTS nodes (
    node_id TEXT PRIMARY KEY,
    node_num INTEGER,
    long_name TEXT,
    short_name TEXT,
    hw_model TEXT,
    role TEXT DEFAULT 'CLIENT',
    latitude REAL,
    longitude REAL,
    altitude INTEGER,
    battery_level INTEGER,
    voltage REAL,
    snr REAL,
    last_heard INTEGER,
    first_seen INTEGER,
    is_favorite INTEGER DEFAULT 0,
    is_muted INTEGER DEFAULT 0
);

-- Contacts table (conversation metadata)
CREATE TABLE IF NOT EXISTS contacts (
    contact_key TEXT PRIMARY KEY,
    display_name TEXT,
    last_message_time INTEGER,
    last_message_text TEXT,
    unread_count INTEGER DEFAULT 0,
    message_count INTEGER DEFAULT 0,
    mute_until INTEGER DEFAULT 0,
    node_id TEXT
);

-- Settings table
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_messages_contact_key ON messages(contact_key);
CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);
CREATE INDEX IF NOT EXISTS idx_messages_from_node ON messages(from_node_id);
CREATE INDEX IF NOT EXISTS idx_contacts_last_message ON contacts(last_message_time DESC);
CREATE INDEX IF NOT EXISTS idx_nodes_last_heard ON nodes(last_heard DESC);
"""


async def get_schema_version(db: aiosqlite.Connection) -> int:
    """Get the current schema version from the database."""
    try:
        async with db.execute(
            "SELECT value FROM settings WHERE key = 'schema_version'"
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return int(row[0])
    except aiosqlite.OperationalError:
        # Table doesn't exist yet
        pass
    return 0


async def set_schema_version(db: aiosqlite.Connection, version: int) -> None:
    """Set the schema version in the database."""
    await db.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES ('schema_version', ?)",
        (str(version),)
    )
    await db.commit()


async def migrate_database(db: aiosqlite.Connection) -> None:
    """Run all necessary migrations to bring database to current version."""
    current_version = await get_schema_version(db)

    if current_version < 1:
        # Apply initial schema
        await db.executescript(SCHEMA_V1)
        await set_schema_version(db, 1)

    # Future migrations would go here:
    # if current_version < 2:
    #     await apply_migration_v2(db)
    #     await set_schema_version(db, 2)


async def create_default_contacts(db: aiosqlite.Connection) -> None:
    """Create default broadcast channel contacts if they don't exist."""
    # Create primary channel (0^all)
    await db.execute(
        """INSERT OR IGNORE INTO contacts (contact_key, display_name, unread_count, message_count)
           VALUES ('0^all', 'Primary Channel', 0, 0)"""
    )
    await db.commit()
