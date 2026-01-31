#!/usr/bin/env python3
import argparse
import asyncio
import signal
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
import meshtastic
import meshtastic.serial_interface
import meshtastic.ble_interface
import serial.tools.list_ports
from pubsub import pub
from textual.app import App, ComposeResult
from textual.containers import Container, Vertical, Horizontal
from textual.widgets import Header, Footer, Input, Static, TabbedContent, TabPane
from textual.binding import Binding
from textual.reactive import reactive
from textual import on

# Import modal screens
from modals import (
    PresetSelectorScreen,
    RADIO_PRESETS,
    FrequencySlotSelectorScreen,
    QuitConfirmScreen,
    UserNameSetterScreen,
    UserSelectorScreen,
    SerialPortSelectorScreen,
    BleDeviceSelectorScreen,
    NodeListScreen,
    RawMonitorScreen,
    NodeDetailScreen,
)

# Import database layer
from db import DatabaseManager, Message, Node, Contact, MessageStatus

# Import tabs
from tabs import ConversationsTab, MessagesTab, NodesTab, SettingsTab

# Load CSS from external file
CSS_FILE = Path(__file__).parent / "meshtastic_tui.css"
with open(CSS_FILE, "r") as f:
    APP_CSS = f.read()

# ====== CONFIG ======
SERIAL_PORT = None  # set explicitly if needed, e.g. "/dev/ttyUSB0"
MAX_MESSAGES = 500
# ====================


class ChatMonitor(App):
    """A Textual app for monitoring Meshtastic messages."""

    TITLE = "Meshtastic Terminal"
    SUB_TITLE = "Nodes: 0"
    CSS = APP_CSS

    BINDINGS = [
        Binding("1", "switch_tab('conversations')", "Conversations", show=True),
        Binding("2", "switch_tab('messages')", "Messages", show=True),
        Binding("3", "switch_tab('nodes')", "Nodes", show=True),
        Binding("4", "switch_tab('settings')", "Settings", show=True),
        Binding("s", "focus_send", "Send", show=True),
        Binding("d", "direct_message", "Direct Message", show=True),
        Binding("h", "toggle_hop_column", "Toggle Hops", show=False),
        Binding("ctrl+n", "show_node_list", "Node List", show=False),
        Binding("ctrl+r", "show_raw_monitor", "Raw Monitor", show=False),
        Binding("ctrl+m", "change_preset", "Change Preset", show=False),
        Binding("ctrl+f", "change_frequency_slot", "Change Freq Slot", show=False),
        Binding("ctrl+u", "set_user_name", "Set User Name", show=False),
        Binding("q", "request_quit", "Quit", show=True),
    ]

    node_count: reactive[int] = reactive(0)
    channel_util: reactive[float] = reactive(0.0)
    battery_level: reactive[int] = reactive(0)
    voltage: reactive[float] = reactive(0.0)
    is_connected: reactive[bool] = reactive(False)
    show_hop_column: reactive[bool] = reactive(False)
    current_contact_key: reactive[str] = reactive("0^all")

    def __init__(self, auto_connect: bool = False, use_ble: bool = False):
        super().__init__()
        self.iface = None
        self.my_node_id = None
        self.known_nodes = {}  # Track nodes we've seen: {node_id: {name, last_seen}}
        self.current_preset = None
        self.current_frequency_slot = None
        self.current_long_name = ""
        self.current_short_name = ""
        self.is_reconnecting = False
        self.is_disconnecting = False
        self.auto_reconnect_enabled = True
        self.reconnect_worker = None
        self.stats_worker = None
        self.last_packet_received = None
        self.selected_serial_port = None
        self.selected_ble_address = None
        self.auto_connect = auto_connect
        self.use_ble = use_ble

        # Database manager
        self.db_manager: Optional[DatabaseManager] = None

    def compose(self) -> ComposeResult:
        """Create child widgets."""
        yield Header()
        with TabbedContent(id="main-tabs"):
            with TabPane("Conversations", id="conversations"):
                yield ConversationsTab(id="conversations-tab")
            with TabPane("Messages", id="messages"):
                yield MessagesTab(id="messages-tab")
            with TabPane("Nodes", id="nodes"):
                yield NodesTab(id="nodes-tab")
            with TabPane("Settings", id="settings"):
                yield SettingsTab(id="settings-tab")
        yield Footer()

    def watch_node_count(self, node_count: int) -> None:
        """Update subtitle when node count changes."""
        self.update_subtitle()

    def watch_channel_util(self, channel_util: float) -> None:
        """Update subtitle when channel utilization changes."""
        self.update_subtitle()

    def watch_battery_level(self, battery_level: int) -> None:
        """Update subtitle when battery level changes."""
        self.update_subtitle()

    def watch_voltage(self, voltage: float) -> None:
        """Update subtitle when voltage changes."""
        self.update_subtitle()

    def watch_is_connected(self, is_connected: bool) -> None:
        """Update bindings when connection state changes."""
        self.refresh_bindings()
        # Update settings tab
        try:
            settings_tab = self.query_one("#settings-tab", SettingsTab)
            settings_tab.update_values(is_connected=is_connected)
        except Exception:
            pass

    def update_subtitle(self) -> None:
        """Update the subtitle with current stats."""
        parts = [f"Nodes: {self.node_count}"]

        if self.channel_util > 0:
            parts.append(f"ChUtil: {self.channel_util:.1f}%")

        if self.battery_level > 100:
            parts.append("Powered")
        elif self.battery_level > 0:
            parts.append(f"Batt: {self.battery_level}%")
        elif self.voltage > 0:
            parts.append(f"Volt: {self.voltage:.2f}V")

        self.sub_title = " | ".join(parts)

    async def on_mount(self) -> None:
        """Set up the app when mounted."""
        # Initialize database
        self.db_manager = DatabaseManager()
        await self.db_manager.initialize()

        # Set initial node count
        self.node_count = len(self.known_nodes)

        # Load contacts from database
        await self._load_contacts()

        # Auto-connect or show port/device selector
        if self.auto_connect:
            if self.use_ble:
                self._log_system(
                    "Auto-connect not supported for BLE, showing device selector"
                )
                self.show_ble_selector()
            else:
                self.auto_connect_first_port()
        else:
            if self.use_ble:
                self.show_ble_selector()
            else:
                self.show_port_selector()

    async def _load_contacts(self) -> None:
        """Load contacts from database."""
        if self.db_manager:
            contacts = await self.db_manager.get_contacts()
            conversations_tab = self.query_one("#conversations-tab", ConversationsTab)
            await conversations_tab.load_contacts(contacts)

    async def _load_messages_for_contact(self, contact_key: str) -> None:
        """Load messages for a specific contact."""
        if not self.db_manager:
            return

        messages = await self.db_manager.get_messages(contact_key, limit=100)

        # Get node names for display
        node_names = {}
        for msg in messages:
            if msg.from_node_id not in node_names:
                node_names[msg.from_node_id] = self.get_node_display_name(msg.from_node_id)

        messages_tab = self.query_one("#messages-tab", MessagesTab)
        messages_tab.my_node_id = self.my_node_id
        await messages_tab.load_messages(messages, node_names)

        # Mark as read
        await self.db_manager.mark_messages_read(contact_key)

        # Refresh contacts to update unread count
        await self._load_contacts()

    async def _load_nodes(self) -> None:
        """Load nodes from database and interface."""
        if not self.db_manager:
            return

        # Get nodes from database
        db_nodes = await self.db_manager.get_nodes()
        node_dict = {n.node_id: n for n in db_nodes}

        # Merge with interface nodes
        if self.iface and hasattr(self.iface, "nodes"):
            for node_id, node_data in self.iface.nodes.items():
                if node_id in node_dict:
                    # Update existing
                    node = node_dict[node_id]
                else:
                    # Create new
                    node = Node(node_id=node_id)

                # Update from interface data
                user = node_data.get("user", {})
                node.long_name = user.get("longName") or node.long_name
                node.short_name = user.get("shortName") or node.short_name
                node.hw_model = self._get_hw_model_name(user.get("hwModel"))
                node.role = self._get_role_name(user.get("role"))

                metrics = node_data.get("deviceMetrics", {})
                node.battery_level = metrics.get("batteryLevel") or node.battery_level
                node.voltage = metrics.get("voltage") or node.voltage

                position = node_data.get("position", {})
                node.latitude = position.get("latitude") or node.latitude
                node.longitude = position.get("longitude") or node.longitude
                node.altitude = position.get("altitude") or node.altitude

                node.snr = node_data.get("snr") or node.snr
                node.last_heard = node_data.get("lastHeard") or node.last_heard

                node_dict[node_id] = node

        nodes_tab = self.query_one("#nodes-tab", NodesTab)
        nodes_tab.my_node_id = self.my_node_id
        await nodes_tab.load_nodes(list(node_dict.values()))

    def _get_hw_model_name(self, hw_model) -> str:
        """Convert hardware model to string name."""
        if hw_model is None:
            return None
        if isinstance(hw_model, str):
            return hw_model
        if hasattr(hw_model, "name"):
            return hw_model.name
        # Map numeric codes
        hw_model_names = {
            0: "UNSET", 4: "TBEAM", 9: "RAK4631", 39: "HELTEC_V3",
            48: "HELTEC_WIRELESS_TRACKER", 50: "T_DECK",
        }
        return hw_model_names.get(hw_model, f"HW_{hw_model}")

    def _get_role_name(self, role) -> str:
        """Convert role to string name."""
        if role is None:
            return "CLIENT"
        if isinstance(role, str):
            return role
        if hasattr(role, "name"):
            return role.name
        role_names = {
            0: "CLIENT", 1: "CLIENT_MUTE", 2: "ROUTER", 3: "ROUTER_CLIENT",
            4: "REPEATER", 5: "TRACKER", 6: "SENSOR", 7: "TAK",
        }
        return role_names.get(role, f"ROLE_{role}")

    def check_action_state(self, action: str) -> bool:
        """Check if an action should be enabled based on connection state."""
        if action in (
            "change_preset",
            "change_frequency_slot",
            "send_message",
            "direct_message",
            "set_user_name",
            "show_node_list",
            "show_raw_monitor",
            "focus_send",
        ):
            return self.is_connected
        return True

    def subscribe_to_events(self) -> None:
        """Subscribe to pub/sub events (unsubscribes first to avoid duplicates)."""
        try:
            pub.unsubscribe(self.on_connection, "meshtastic.connection.established")
            pub.unsubscribe(self.on_disconnect, "meshtastic.connection.lost")
            pub.unsubscribe(self.on_receive, "meshtastic.receive")
        except Exception:
            pass

        pub.subscribe(self.on_connection, "meshtastic.connection.established")
        pub.subscribe(self.on_disconnect, "meshtastic.connection.lost")
        pub.subscribe(self.on_receive, "meshtastic.receive")

    def _normalize_node_id(self, packet) -> Optional[str]:
        """Extract and normalize node ID from packet to string format."""
        node_id = packet.get("fromId") or packet.get("toId")
        if node_id:
            return node_id

        node_num = packet.get("from") or packet.get("to")
        if node_num:
            if hasattr(self.iface, "nodesByNum") and node_num in self.iface.nodesByNum:
                node_info = self.iface.nodesByNum[node_num]
                return node_info.get("user", {}).get("id") or f"!{node_num:08x}"
            else:
                return f"!{node_num:08x}"

        return None

    def get_node_display_name(self, node_id: str, use_cache: bool = True) -> str:
        """Get a friendly display name for a node."""
        if not node_id:
            return "unknown"

        if use_cache:
            cached_name = self.known_nodes.get(node_id, {}).get("name")
            if cached_name and cached_name != node_id:
                return cached_name

        friendly_name = None
        if hasattr(self.iface, "nodes") and self.iface and node_id in self.iface.nodes:
            user_info = self.iface.nodes[node_id].get("user", {})
            friendly_name = user_info.get("longName") or user_info.get("shortName")

            if friendly_name and use_cache:
                self.register_node(node_id, friendly_name)

        return friendly_name or node_id

    def register_node(self, node_id: str, node_name: str = None) -> bool:
        """Register a node and return True if it's newly discovered."""
        is_new = node_id not in self.known_nodes

        existing_name = self.known_nodes.get(node_id, {}).get("name")

        if node_name and node_name != node_id:
            best_name = node_name
        elif existing_name and existing_name != node_id:
            best_name = existing_name
        else:
            best_name = node_id

        self.known_nodes[node_id] = {
            "name": best_name,
            "last_seen": datetime.now().isoformat(),
            "first_seen": self.known_nodes.get(node_id, {}).get(
                "first_seen", datetime.now().isoformat()
            ),
        }

        self.node_count = len(self.known_nodes)

        return is_new

    def auto_connect_first_port(self) -> None:
        """Auto-connect to the first available serial port."""
        ports = serial.tools.list_ports.comports()

        filtered_ports = [
            p
            for p in ports
            if not any(skip in p.device.lower() for skip in ["bluetooth", "debug"])
        ]

        if filtered_ports:
            self.selected_serial_port = filtered_ports[0].device
            self._log_system(
                f"Auto-connecting to first port: {self.selected_serial_port}"
            )
            self.run_worker(self.connect_device(), exclusive=True)
        else:
            self._log_system("No serial ports found, using auto-detect")
            self.selected_serial_port = None
            self.run_worker(self.connect_device(), exclusive=True)

    def show_port_selector(self) -> None:
        """Show serial port selector dialog on launch."""

        def handle_port_selection(selected_port) -> None:
            if selected_port is False:
                self._log_system("Connection cancelled by user", error=True)
                self.exit()
            else:
                self.selected_serial_port = selected_port
                self.run_worker(self.connect_device(), exclusive=True)

        self.push_screen(SerialPortSelectorScreen(), handle_port_selection)

    def show_ble_selector(self) -> None:
        """Show BLE device selector dialog on launch."""

        def handle_ble_selection(selected_address) -> None:
            if selected_address is False:
                self._log_system("Connection cancelled by user", error=True)
                self.exit()
            else:
                self.selected_ble_address = selected_address
                self.run_worker(self.connect_device(), exclusive=True)

        self.push_screen(BleDeviceSelectorScreen(), handle_ble_selection)

    async def connect_device(self) -> None:
        """Connect to Meshtastic device."""
        if self.use_ble:
            if self.selected_ble_address:
                self._log_system(
                    f"Connecting to BLE device {self.selected_ble_address}..."
                )
            else:
                self._log_system("Connecting to BLE device (auto-detect)...")
        else:
            if self.selected_serial_port:
                self._log_system(f"Connecting to {self.selected_serial_port}...")
            else:
                self._log_system("Connecting to device (auto-detect)...")

        try:
            loop = asyncio.get_event_loop()

            if self.use_ble:
                self.iface = await loop.run_in_executor(
                    None,
                    lambda: meshtastic.ble_interface.BLEInterface(
                        address=self.selected_ble_address
                    ),
                )
            else:
                self.iface = await loop.run_in_executor(
                    None,
                    lambda: meshtastic.serial_interface.SerialInterface(
                        devPath=self.selected_serial_port
                    ),
                )

            self._log_system("Initializing connection...")

            self.subscribe_to_events()

            await asyncio.sleep(2)

            info = await loop.run_in_executor(None, self.iface.getMyNodeInfo)
            self._log_system(f"Ready: {info['user']['longName']}")

            self.my_node_id = info["user"]["id"]
            self.current_long_name = info["user"].get("longName", "")
            self.current_short_name = info["user"].get("shortName", "")

            # Update messages tab with my node ID
            messages_tab = self.query_one("#messages-tab", MessagesTab)
            messages_tab.my_node_id = self.my_node_id

            self.register_node(self.my_node_id, info["user"].get("longName"))

            # Load existing nodes
            try:
                if hasattr(self.iface, "nodes") and self.iface.nodes:
                    node_count = 0
                    for node_id, node_info in self.iface.nodes.items():
                        if node_id != self.my_node_id:
                            user_info = node_info.get("user", {})
                            node_name = user_info.get("longName") or user_info.get(
                                "shortName"
                            )
                            self.register_node(node_id, node_name)

                            # Persist to database
                            if self.db_manager:
                                node = Node(
                                    node_id=node_id,
                                    node_num=node_info.get("num"),
                                    long_name=user_info.get("longName"),
                                    short_name=user_info.get("shortName"),
                                    hw_model=self._get_hw_model_name(user_info.get("hwModel")),
                                    role=self._get_role_name(user_info.get("role")),
                                    snr=node_info.get("snr"),
                                    last_heard=node_info.get("lastHeard"),
                                )
                                await self.db_manager.upsert_node(node)

                            node_count += 1

                    self._log_system(
                        f"Loaded {node_count} node{'s' if node_count != 1 else ''} from device"
                    )
            except Exception as e:
                self._log_system("Unable to load nodes from device")
                pass

            # Log radio configuration and update settings tab
            try:
                if hasattr(self.iface, "localNode") and self.iface.localNode:
                    local_config = self.iface.localNode.localConfig

                    if local_config and hasattr(local_config, "device"):
                        device_config = local_config.device
                        if hasattr(device_config, "role"):
                            role_value = device_config.role
                            role_name = self._get_role_name(role_value)
                            self._log_system(f"Device mode: {role_name}")

                    if local_config and hasattr(local_config, "lora"):
                        lora_config = local_config.lora
                        if hasattr(lora_config, "modem_preset"):
                            preset_value = lora_config.modem_preset
                            preset_names = {
                                0: "LONG_FAST", 1: "LONG_SLOW", 2: "VERY_LONG_SLOW",
                                3: "MEDIUM_SLOW", 4: "MEDIUM_FAST", 5: "SHORT_SLOW",
                                6: "SHORT_FAST", 7: "LONG_MODERATE",
                            }
                            if hasattr(preset_value, "name"):
                                preset_name = preset_value.name
                            else:
                                preset_name = preset_names.get(
                                    preset_value, f"Unknown ({preset_value})"
                                )
                            self.current_preset = preset_name
                            self._log_system(f"Radio preset: {preset_name}")

                        if hasattr(lora_config, "channel_num"):
                            channel_num = lora_config.channel_num
                            self.current_frequency_slot = channel_num
                            slot_display = (
                                f"{channel_num} (auto)"
                                if channel_num == 0
                                else str(channel_num)
                            )
                            self._log_system(f"Frequency slot: {slot_display}")

                        if hasattr(lora_config, "region"):
                            region_value = lora_config.region
                            region_names = {
                                0: "UNSET", 1: "US", 2: "EU_433", 3: "EU_868",
                                4: "CN", 5: "JP", 6: "ANZ", 7: "KR", 8: "TW",
                                9: "RU", 10: "IN", 11: "NZ_865",
                            }
                            if hasattr(region_value, "name"):
                                region_name = region_value.name
                            else:
                                region_name = region_names.get(
                                    region_value, f"Unknown ({region_value})"
                                )
                            self._log_system(f"Region: {region_name}")

                # Update settings tab
                settings_tab = self.query_one("#settings-tab", SettingsTab)
                settings_tab.update_values(
                    preset=self.current_preset,
                    frequency_slot=self.current_frequency_slot,
                    long_name=self.current_long_name,
                    short_name=self.current_short_name,
                    is_connected=True,
                )
            except Exception as e:
                pass

            # Load nodes into nodes tab
            await self._load_nodes()

            # Start periodic stats update
            self.stats_worker = self.run_worker(
                self.update_stats_loop(), exclusive=False
            )

        except Exception as e:
            self._log_system(f"FATAL: Could not connect: {e}", error=True)

    def on_connection(self, interface, topic=pub.AUTO_TOPIC):
        """Handle connection event."""
        try:
            node = interface.getMyNodeInfo()
            self.my_node_id = node["user"]["id"]
            self._log_system(
                f"Connected: {node['user']['shortName']} ({self.my_node_id})"
            )

            self.is_connected = True

            if self.is_reconnecting:
                self.is_reconnecting = False
                if self.reconnect_worker is not None:
                    self.reconnect_worker.cancel()
                    self.reconnect_worker = None

            self.is_disconnecting = False

        except Exception as e:
            self._log_system(f"Connection warning: {e}")

    def on_disconnect(self, interface=None, topic=pub.AUTO_TOPIC):
        """Handle disconnection event."""
        if self.is_disconnecting:
            return

        self.is_disconnecting = True
        self.is_connected = False
        self._log_system("Disconnected from device", error=True)

        if self.iface:
            try:
                self.iface.close()
            except Exception:
                pass
            self.iface = None

        if self.auto_reconnect_enabled and not self.is_reconnecting:
            self._log_system("Will attempt to reconnect in 15 seconds...")
            self.is_reconnecting = True
            if self.reconnect_worker is not None:
                self.reconnect_worker.cancel()
            self.reconnect_worker = self.run_worker(
                self.auto_reconnect_loop(), exclusive=False
            )

        asyncio.create_task(self._reset_disconnect_flag())

    async def _reset_disconnect_flag(self) -> None:
        """Reset the disconnecting flag after a brief delay."""
        await asyncio.sleep(2)
        self.is_disconnecting = False

    def on_receive(self, packet, interface):
        """Monitor received packets."""
        self.last_packet_received = datetime.now()

        decoded = packet.get("decoded", {})
        portnum = decoded.get("portnum", "unknown")

        from_id = self._normalize_node_id(
            {"fromId": packet.get("fromId"), "from": packet.get("from")}
        )

        if from_id and from_id != self.my_node_id and not from_id.startswith("^"):
            is_new = self.register_node(from_id, None)
            node_name = self.get_node_display_name(from_id, use_cache=False)

            if node_name != from_id:
                self.register_node(from_id, node_name)
                if is_new:
                    self._log_node_discovery(from_id, node_name)

        # Handle telemetry
        if portnum == "TELEMETRY_APP" and from_id == self.my_node_id:
            try:
                telemetry = decoded.get("telemetry", {})

                if "deviceMetrics" in telemetry:
                    metrics = telemetry["deviceMetrics"]
                    if "batteryLevel" in metrics and metrics["batteryLevel"] > 0:
                        self.battery_level = metrics["batteryLevel"]
                    if "voltage" in metrics and metrics["voltage"] > 0:
                        self.voltage = metrics["voltage"]
                    if "channelUtilization" in metrics:
                        self.channel_util = metrics["channelUtilization"]
            except Exception:
                pass
            return

        ignored_types = [
            "POSITION_APP", "TELEMETRY_APP", "ROUTING_APP", "ADMIN_APP", "unknown",
        ]

        # Handle NODEINFO
        if portnum == "NODEINFO_APP":
            if from_id and from_id != self.my_node_id and not from_id.startswith("^"):
                self.run_worker(self._process_nodeinfo(from_id), exclusive=False)
            return

        if portnum in ignored_types:
            return

        # Handle text messages
        if portnum == "TEXT_MESSAGE_APP" or portnum == 1:
            message_content = decoded.get("text")
            if not message_content and "payload" in decoded:
                try:
                    payload = decoded["payload"]
                    if isinstance(payload, bytes):
                        message_content = payload.decode("utf-8")
                    elif isinstance(payload, str):
                        message_content = payload
                except Exception:
                    return

            if message_content:
                msg_from_id = (
                    self._normalize_node_id(
                        {"fromId": packet.get("fromId"), "from": packet.get("from")}
                    )
                    or "unknown"
                )
                msg_to_id = (
                    self._normalize_node_id(
                        {"toId": packet.get("toId"), "to": packet.get("to")}
                    )
                    or "unknown"
                )

                reply_id = decoded.get("replyId") or packet.get("replyId")
                is_reply = reply_id is not None and reply_id != 0

                hop_limit = packet.get("hopLimit", 0)
                hop_start = packet.get("hopStart", hop_limit)
                hops_taken = hop_start - hop_limit if hop_start >= hop_limit else 0

                packet_id = packet.get("id", 0)
                channel = packet.get("channel", 0)

                # Run async message handling
                self.run_worker(
                    self._handle_received_message(
                        msg_from_id,
                        msg_to_id,
                        message_content,
                        packet_id,
                        channel,
                        hops_taken,
                        is_reply,
                    ),
                    exclusive=False,
                )

    async def _handle_received_message(
        self,
        from_id: str,
        to_id: str,
        content: str,
        packet_id: int,
        channel: int,
        hop_count: int,
        is_reply: bool,
    ) -> None:
        """Handle a received text message asynchronously."""
        if not self.db_manager:
            return

        # Determine contact key
        if to_id.startswith("^") or to_id == "^all":
            # Broadcast
            contact_key = f"{channel}^all"
        elif to_id == self.my_node_id:
            # DM to us - key by sender
            contact_key = f"{channel}{from_id}"
        else:
            # DM from us (shouldn't happen here, but handle it)
            contact_key = f"{channel}{to_id}"

        # Add reply indicator to content
        if is_reply:
            content = "\u21a9 " + content

        # Create message
        now = int(time.time())
        message = Message(
            packet_id=packet_id,
            contact_key=contact_key,
            from_node_id=from_id,
            to_node_id=to_id,
            content=content,
            timestamp=now,
            received_time=now,
            status=MessageStatus.RECEIVED,
            hop_count=hop_count,
            channel=channel,
        )

        # Insert to database
        message.id = await self.db_manager.insert_message(message)

        # Update contact
        sender_name = self.get_node_display_name(from_id)
        display_name = sender_name if not contact_key.endswith("^all") else "Primary Channel"
        await self.db_manager.update_contact_on_message(
            contact_key=contact_key,
            message_text=content,
            timestamp=now,
            is_incoming=True,
            display_name=display_name,
            node_id=from_id if not contact_key.endswith("^all") else None,
        )

        # Refresh contacts list
        await self._load_contacts()

        # If this is the current conversation, add to messages view
        if contact_key == self.current_contact_key:
            messages_tab = self.query_one("#messages-tab", MessagesTab)
            await messages_tab.add_message(message, sender_name)

            # Mark as read immediately
            await self.db_manager.mark_messages_read(contact_key)
            await self._load_contacts()

    async def _process_nodeinfo(self, from_id: str) -> None:
        """Process NODEINFO packet asynchronously to update node names."""
        await asyncio.sleep(0.1)

        old_name = self.known_nodes.get(from_id, {}).get("name", from_id)
        node_name = self.get_node_display_name(from_id, use_cache=False)

        learning_new_name = (
            node_name != from_id and old_name == from_id
        )

        self.register_node(from_id, node_name if node_name != from_id else None)

        # Update node in database
        if self.db_manager and self.iface and hasattr(self.iface, "nodes"):
            node_data = self.iface.nodes.get(from_id, {})
            user = node_data.get("user", {})
            node = Node(
                node_id=from_id,
                node_num=node_data.get("num"),
                long_name=user.get("longName"),
                short_name=user.get("shortName"),
                hw_model=self._get_hw_model_name(user.get("hwModel")),
                role=self._get_role_name(user.get("role")),
                snr=node_data.get("snr"),
                last_heard=node_data.get("lastHeard") or int(time.time()),
            )
            await self.db_manager.upsert_node(node)

            # Update nodes tab
            nodes_tab = self.query_one("#nodes-tab", NodesTab)
            await nodes_tab.update_node(node)

        if learning_new_name:
            self._log_node_discovery(from_id, node_name)

    def _log_system(self, message: str, error: bool = False) -> None:
        """Log a system message - currently just prints to console during dev."""
        # In the future, we might add a system messages area
        # For now, we'll use the app's notify
        self.notify(message, severity="error" if error else "information", timeout=3)

    def _log_node_discovery(self, node_id: str, node_name: str) -> None:
        """Log a node discovery event."""
        if node_name and node_name != node_id:
            message = f"Discovered: {node_name}"
        else:
            message = f"Discovered: {node_id}"
        self.notify(message, timeout=2)

    # ==================== Tab Navigation ====================

    def action_switch_tab(self, tab_id: str) -> None:
        """Switch to a specific tab."""
        tabs = self.query_one("#main-tabs", TabbedContent)
        tabs.active = tab_id

    def action_focus_send(self) -> None:
        """Focus the message input in the messages tab."""
        if not self.is_connected:
            return

        # Switch to messages tab and focus input
        self.action_switch_tab("messages")
        messages_tab = self.query_one("#messages-tab", MessagesTab)
        messages_tab.focus_input()

    # ==================== Event Handlers ====================

    @on(ConversationsTab.ConversationSelected)
    def on_conversation_selected(self, event: ConversationsTab.ConversationSelected) -> None:
        """Handle conversation selection."""
        contact = event.contact
        self.current_contact_key = contact.contact_key

        # Set contact on messages tab
        messages_tab = self.query_one("#messages-tab", MessagesTab)
        messages_tab.set_contact(contact)

        # Load messages
        self.run_worker(self._load_messages_for_contact(contact.contact_key))

        # Switch to messages tab
        self.action_switch_tab("messages")

    @on(MessagesTab.MessageSendRequested)
    def on_message_send_requested(self, event: MessagesTab.MessageSendRequested) -> None:
        """Handle message send request."""
        if not self.is_connected:
            self.notify("Not connected to device", severity="error")
            return

        self.run_worker(
            self._send_message(event.content, event.contact_key, event.reply_to),
            exclusive=False,
        )

    async def _send_message(self, content: str, contact_key: str, reply_to: int = None) -> None:
        """Send a message asynchronously."""
        if not self.iface:
            return

        # Parse contact key to get destination
        if "^" in contact_key:
            # Channel message
            channel = int(contact_key.split("^")[0])
            dest = "^all"
        else:
            # DM - extract node ID (contact key is "channel!nodeId")
            channel = int(contact_key[0])
            dest = contact_key[1:]  # Everything after channel number

        try:
            loop = asyncio.get_event_loop()

            is_broadcast = "^" in contact_key
            want_ack = not is_broadcast

            if reply_to:
                await loop.run_in_executor(
                    None,
                    lambda: self.iface.sendText(
                        content, destinationId=dest, wantAck=want_ack,
                        channelIndex=channel, replyId=reply_to
                    ),
                )
            else:
                await loop.run_in_executor(
                    None,
                    lambda: self.iface.sendText(
                        content, destinationId=dest, wantAck=want_ack,
                        channelIndex=channel
                    ),
                )

            # Store in database
            now = int(time.time())
            message = Message(
                contact_key=contact_key,
                from_node_id=self.my_node_id,
                to_node_id=dest,
                content=("\u21a9 " + content) if reply_to else content,
                timestamp=now,
                received_time=now,
                status=MessageStatus.ENROUTE,
                channel=channel,
            )

            if self.db_manager:
                message.id = await self.db_manager.insert_message(message)

                # Update contact
                await self.db_manager.update_contact_on_message(
                    contact_key=contact_key,
                    message_text=content,
                    timestamp=now,
                    is_incoming=False,
                )

                # Refresh UI
                await self._load_contacts()

                # Add to messages view
                messages_tab = self.query_one("#messages-tab", MessagesTab)
                await messages_tab.add_message(message, self.current_long_name or "You")

        except Exception as e:
            self.notify(f"Failed to send: {e}", severity="error")

    @on(NodesTab.NodeSelected)
    def on_node_selected(self, event: NodesTab.NodeSelected) -> None:
        """Handle node selection for details."""
        node = event.node
        is_my_node = node.node_id == self.my_node_id

        # Get full node data from interface if available
        node_data = {}
        if self.iface and hasattr(self.iface, "nodes"):
            node_data = self.iface.nodes.get(node.node_id, {})

        # If we don't have interface data, construct from our Node object
        if not node_data:
            node_data = {
                "user": {
                    "longName": node.long_name,
                    "shortName": node.short_name,
                    "hwModel": node.hw_model,
                    "role": node.role,
                },
                "position": {
                    "latitude": node.latitude,
                    "longitude": node.longitude,
                    "altitude": node.altitude,
                },
                "deviceMetrics": {
                    "batteryLevel": node.battery_level,
                    "voltage": node.voltage,
                },
                "snr": node.snr,
                "lastHeard": node.last_heard,
            }

        self.push_screen(NodeDetailScreen(node.node_id, node_data, is_my_node))

    @on(SettingsTab.SettingSelected)
    def on_setting_selected(self, event: SettingsTab.SettingSelected) -> None:
        """Handle setting selection."""
        setting_id = event.setting_id

        if setting_id == "preset":
            self.action_change_preset()
        elif setting_id == "frequency":
            self.action_change_frequency_slot()
        elif setting_id == "username":
            self.action_set_user_name()

    # ==================== Actions ====================

    def action_direct_message(self) -> None:
        """Show user selector dialog for direct messaging."""
        if not self.iface:
            self.notify("Not connected to device", severity="error")
            return

        if len(self.known_nodes) <= 1:
            self.notify("No other users available to message", severity="error")
            return

        def handle_user_selection(selected_node_id: str | None) -> None:
            if selected_node_id:
                self._start_direct_message(selected_node_id)

        self.push_screen(
            UserSelectorScreen(self.known_nodes, self.my_node_id),
            handle_user_selection,
        )

    def _start_direct_message(self, node_id: str) -> None:
        """Start a direct message conversation with a node."""
        # Create contact key for DM
        contact_key = f"0{node_id}"

        # Create or get contact
        node_name = self.get_node_display_name(node_id)
        contact = Contact(
            contact_key=contact_key,
            display_name=node_name,
            node_id=node_id,
        )

        self.current_contact_key = contact_key

        # Set up messages tab
        messages_tab = self.query_one("#messages-tab", MessagesTab)
        messages_tab.set_contact(contact)

        # Load any existing messages
        self.run_worker(self._load_messages_for_contact(contact_key))

        # Switch to messages tab and focus input
        self.action_switch_tab("messages")
        messages_tab.focus_input()

    def action_change_preset(self) -> None:
        """Show the preset selector dialog."""
        if not self.iface:
            self.notify("Not connected to device", severity="error")
            return

        def handle_preset_selection(preset_name: str | None) -> None:
            if preset_name:
                self.run_worker(self.change_radio_preset(preset_name), exclusive=False)

        self.push_screen(
            PresetSelectorScreen(self.current_preset), handle_preset_selection
        )

    def action_change_frequency_slot(self) -> None:
        """Show the frequency slot selector dialog."""
        if not self.iface:
            self.notify("Not connected to device", severity="error")
            return

        def handle_slot_selection(slot: int | None) -> None:
            if slot is not None:
                self.run_worker(self.change_frequency_slot(slot), exclusive=False)

        self.push_screen(
            FrequencySlotSelectorScreen(self.current_frequency_slot),
            handle_slot_selection,
        )

    def action_request_quit(self) -> None:
        """Show quit confirmation dialog."""

        def handle_quit_response(confirmed: bool) -> None:
            if confirmed:
                self.exit()

        self.push_screen(QuitConfirmScreen(), handle_quit_response)

    def action_toggle_hop_column(self) -> None:
        """Toggle the visibility of the hop count column (legacy, kept for compatibility)."""
        self.show_hop_column = not self.show_hop_column
        self.notify(f"Hop column: {'shown' if self.show_hop_column else 'hidden'}")

    def action_show_node_list(self) -> None:
        """Show the node list dialog."""
        if not self.iface:
            self.notify("Not connected to device", severity="error")
            return

        self.push_screen(NodeListScreen(self.iface, self.my_node_id))

    def action_show_raw_monitor(self) -> None:
        """Show the raw network monitor dialog."""
        if not self.iface:
            self.notify("Not connected to device", severity="error")
            return

        self.push_screen(RawMonitorScreen(self.iface))

    def action_set_user_name(self) -> None:
        """Show the user name setter dialog."""
        if not self.iface:
            self.notify("Not connected to device", severity="error")
            return

        def handle_user_name_response(result: tuple | None) -> None:
            if result:
                long_name, short_name = result
                self.run_worker(
                    self.set_user_names(long_name, short_name), exclusive=False
                )

        self.push_screen(
            UserNameSetterScreen(self.current_long_name, self.current_short_name),
            handle_user_name_response,
        )

    async def set_user_names(self, long_name: str, short_name: str) -> None:
        """Set the user long name and short name."""
        if not long_name and not short_name:
            self.notify("Both names are empty, no changes made")
            return

        self.notify("Setting user names...")

        try:
            loop = asyncio.get_event_loop()

            def set_names():
                try:
                    node = self.iface.localNode
                    if node:
                        node.setOwner(
                            long_name=long_name if long_name else None,
                            short_name=short_name if short_name else None,
                        )
                        return True
                    return False
                except Exception as e:
                    raise e

            success = await loop.run_in_executor(None, set_names)

            if success:
                if long_name:
                    self.current_long_name = long_name
                if short_name:
                    self.current_short_name = short_name

                # Update settings tab
                settings_tab = self.query_one("#settings-tab", SettingsTab)
                settings_tab.update_values(
                    long_name=self.current_long_name,
                    short_name=self.current_short_name,
                )

                display_parts = []
                if long_name:
                    display_parts.append(f"Long: '{long_name}'")
                if short_name:
                    display_parts.append(f"Short: '{short_name}'")

                self.notify(f"User names updated: {', '.join(display_parts)}")
                self.notify("Device will reboot to apply changes...")
            else:
                self.notify("Failed to set user names", severity="error")

        except Exception as e:
            self.notify(f"Error setting user names: {e}", severity="error")

    async def change_radio_preset(self, preset_name: str) -> None:
        """Change the radio preset and handle device reboot."""
        if preset_name not in RADIO_PRESETS:
            self.notify(f"Invalid preset: {preset_name}", severity="error")
            return

        preset_value = RADIO_PRESETS[preset_name]
        self.notify(f"Changing radio preset to {preset_name}...")

        try:
            loop = asyncio.get_event_loop()

            def set_preset():
                try:
                    node = self.iface.localNode
                    if node:
                        node.localConfig.lora.modem_preset = preset_value
                        node.writeConfig("lora")
                        return True
                    return False
                except Exception as e:
                    raise e

            success = await loop.run_in_executor(None, set_preset)

            if success:
                self.notify(
                    f"Preset changed to {preset_name}. Device will reboot..."
                )
                self.current_preset = preset_name

                # Update settings tab
                settings_tab = self.query_one("#settings-tab", SettingsTab)
                settings_tab.update_values(preset=preset_name)

                self.is_reconnecting = True

                await asyncio.sleep(10)

                self.notify("Attempting to reconnect...")
                await self.reconnect_device()
            else:
                self.notify("Failed to change preset", severity="error")

        except Exception as e:
            self.notify(f"Error changing preset: {e}", severity="error")
            self.is_reconnecting = False

    async def change_frequency_slot(self, slot: int) -> None:
        """Change the frequency slot and handle device reboot."""
        if not 0 <= slot <= 83:
            self.notify(
                f"Invalid frequency slot: {slot} (must be 0-83)", severity="error"
            )
            return

        slot_display = f"{slot} (auto)" if slot == 0 else str(slot)
        self.notify(f"Changing frequency slot to {slot_display}...")

        try:
            loop = asyncio.get_event_loop()

            def set_slot():
                try:
                    node = self.iface.localNode
                    if node:
                        node.localConfig.lora.channel_num = slot
                        node.writeConfig("lora")
                        return True
                    return False
                except Exception as e:
                    raise e

            success = await loop.run_in_executor(None, set_slot)

            if success:
                self.notify(
                    f"Frequency slot changed to {slot_display}. Device will reboot..."
                )
                self.current_frequency_slot = slot

                # Update settings tab
                settings_tab = self.query_one("#settings-tab", SettingsTab)
                settings_tab.update_values(frequency_slot=slot)

                self.is_reconnecting = True

                await asyncio.sleep(10)

                self.notify("Attempting to reconnect...")
                await self.reconnect_device()
            else:
                self.notify("Failed to change frequency slot", severity="error")

        except Exception as e:
            self.notify(f"Error changing frequency slot: {e}", severity="error")
            self.is_reconnecting = False

    async def reconnect_device(self) -> None:
        """Reconnect to the device after a reboot."""
        max_attempts = 5
        attempt = 0

        while attempt < max_attempts and self.is_reconnecting:
            attempt += 1
            self.notify(f"Reconnection attempt {attempt}/{max_attempts}...")

            try:
                if self.iface:
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, self.iface.close)
                    self.iface = None

                await asyncio.sleep(3)

                loop = asyncio.get_event_loop()
                if self.use_ble:
                    self.iface = await loop.run_in_executor(
                        None,
                        lambda: meshtastic.ble_interface.BLEInterface(
                            address=self.selected_ble_address
                        ),
                    )
                else:
                    self.iface = await loop.run_in_executor(
                        None,
                        lambda: meshtastic.serial_interface.SerialInterface(
                            devPath=self.selected_serial_port
                        ),
                    )

                self.subscribe_to_events()

                await asyncio.sleep(2)

                info = await loop.run_in_executor(None, self.iface.getMyNodeInfo)
                self.notify(f"Reconnected: {info['user']['longName']}")

                try:
                    if hasattr(self.iface, "localNode") and self.iface.localNode:
                        local_config = self.iface.localNode.localConfig
                        if local_config and hasattr(local_config, "lora"):
                            lora_config = local_config.lora
                            if hasattr(lora_config, "modem_preset"):
                                preset_value = lora_config.modem_preset
                                preset_names = {v: k for k, v in RADIO_PRESETS.items()}
                                if hasattr(preset_value, "name"):
                                    self.current_preset = preset_value.name
                                else:
                                    self.current_preset = preset_names.get(preset_value)
                                self.notify(f"Verified preset: {self.current_preset}")
                            if hasattr(lora_config, "channel_num"):
                                self.current_frequency_slot = lora_config.channel_num
                                self.notify(
                                    f"Verified frequency slot: {self.current_frequency_slot}"
                                )
                except Exception:
                    pass

                self.is_reconnecting = False
                self.is_disconnecting = False
                self.is_connected = True
                return

            except Exception as e:
                self.notify(f"Reconnection attempt {attempt} failed: {e}")
                if attempt >= max_attempts:
                    self.notify(
                        "Failed to reconnect. Please restart the app.", severity="error"
                    )
                    self.is_reconnecting = False

    async def auto_reconnect_loop(self) -> None:
        """Automatically attempt to reconnect every 15 seconds after disconnect."""
        while self.is_reconnecting and self.auto_reconnect_enabled:
            try:
                await asyncio.sleep(15)

                if not self.auto_reconnect_enabled or not self.is_reconnecting:
                    break

                self.notify("Attempting automatic reconnection...")

                if self.iface:
                    loop = asyncio.get_event_loop()
                    try:
                        await loop.run_in_executor(None, self.iface.close)
                    except Exception:
                        pass
                    self.iface = None

                await asyncio.sleep(2)

                loop = asyncio.get_event_loop()
                if self.use_ble:
                    self.iface = await loop.run_in_executor(
                        None,
                        lambda: meshtastic.ble_interface.BLEInterface(
                            address=self.selected_ble_address
                        ),
                    )
                else:
                    self.iface = await loop.run_in_executor(
                        None,
                        lambda: meshtastic.serial_interface.SerialInterface(
                            devPath=self.selected_serial_port
                        ),
                    )

                self.subscribe_to_events()

                await asyncio.sleep(3)

                info = await loop.run_in_executor(None, self.iface.getMyNodeInfo)
                self.notify(f"Successfully reconnected: {info['user']['longName']}")

                self.my_node_id = info["user"]["id"]

                self.is_reconnecting = False
                self.is_disconnecting = False
                self.is_connected = True
                self.reconnect_worker = None
                return

            except Exception as e:
                self.notify(
                    f"Reconnection failed: {e}. Will retry in 15 seconds..."
                )

    async def update_stats_loop(self) -> None:
        """Periodically request device telemetry and monitor connection health."""
        stale_timeout_seconds = 300

        while True:
            try:
                await asyncio.sleep(30)

                if not self.iface or not self.is_connected or self.is_reconnecting:
                    continue

                if self.last_packet_received:
                    time_since_last_packet = (
                        datetime.now() - self.last_packet_received
                    ).total_seconds()

                    if time_since_last_packet > stale_timeout_seconds:
                        self.notify(
                            f"No packets received for {int(time_since_last_packet)}s. Connection may be stale.",
                            severity="warning",
                        )
                        self.notify("Triggering reconnection...")

                        self.is_connected = False
                        self.on_disconnect()
                        continue

                loop = asyncio.get_event_loop()

                def request_telemetry():
                    try:
                        self.iface.sendTelemetry(
                            destinationId=self.my_node_id or "^local",
                            wantResponse=False,
                            channelIndex=0,
                            telemetryType="device_metrics",
                        )
                    except Exception:
                        pass

                await loop.run_in_executor(None, request_telemetry)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.notify(f"Error in stats loop: {e}")

    async def on_shutdown(self) -> None:
        """Clean up when shutting down."""
        self.auto_reconnect_enabled = False
        self.is_reconnecting = False

        if self.reconnect_worker is not None:
            self.reconnect_worker.cancel()
            self.reconnect_worker = None

        if self.stats_worker is not None:
            self.stats_worker.cancel()
            self.stats_worker = None

        try:
            pub.unsubscribe(self.on_connection, "meshtastic.connection.established")
            pub.unsubscribe(self.on_disconnect, "meshtastic.connection.lost")
            pub.unsubscribe(self.on_receive, "meshtastic.receive")
        except Exception:
            pass

        # Close database
        if self.db_manager:
            await self.db_manager.close()

        if self.iface:
            try:
                if hasattr(self.iface, "_want_receive"):
                    self.iface._want_receive = False

                if self.use_ble:
                    loop = asyncio.get_event_loop()
                    try:
                        await asyncio.wait_for(
                            loop.run_in_executor(None, self.iface.close), timeout=1.0
                        )
                    except asyncio.TimeoutError:
                        pass
                else:
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, self.iface.close)
            except Exception:
                pass


def main():
    """Run the app."""
    parser = argparse.ArgumentParser(
        description="Meshtastic Terminal - A modern terminal UI for Meshtastic mesh networks"
    )
    parser.add_argument(
        "-a",
        "--auto-connect",
        action="store_true",
        help="Auto-connect to the first available serial port",
    )
    parser.add_argument(
        "-b",
        "--ble",
        action="store_true",
        help="Use Bluetooth LE instead of serial connection",
    )
    args = parser.parse_args()

    app = ChatMonitor(auto_connect=args.auto_connect, use_ble=args.ble)

    if args.ble:
        original_sigint = signal.getsignal(signal.SIGINT)

        def handle_sigint(signum, frame):
            if app.iface and hasattr(app.iface, "_want_receive"):
                try:
                    app.iface._want_receive = False
                except Exception:
                    pass

            import os
            os._exit(0)

        signal.signal(signal.SIGINT, handle_sigint)

    app.run()


if __name__ == "__main__":
    main()
