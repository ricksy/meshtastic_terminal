"""Settings tab for app configuration."""

from textual.app import ComposeResult
from textual.widgets import Static, ListView, ListItem, Label
from textual.containers import Vertical, Horizontal
from textual.message import Message as TextualMessage
from textual import on


class SettingItem(ListItem):
    """A setting item in the settings list."""

    class Activated(TextualMessage):
        """Message sent when this setting is activated."""
        def __init__(self, setting_id: str):
            self.setting_id = setting_id
            super().__init__()

    DEFAULT_CSS = """
    SettingItem {
        height: 3;
        padding: 0 1;
    }

    SettingItem > Horizontal {
        height: 100%;
        width: 100%;
    }

    SettingItem .setting-label {
        width: 1fr;
        height: 1;
    }

    SettingItem .setting-value {
        width: auto;
        min-width: 20;
        height: 1;
        color: $text-muted;
        text-align: right;
    }

    SettingItem:hover {
        background: $accent 20%;
    }

    SettingItem.-highlight {
        background: $accent;
    }
    """

    def __init__(self, setting_id: str, label: str, value: str = "", **kwargs):
        """Initialize the setting item."""
        super().__init__(**kwargs)
        self.setting_id = setting_id
        self._label = label
        self._value = value

    def compose(self) -> ComposeResult:
        """Create the setting item layout."""
        with Horizontal():
            yield Static(self._label, classes="setting-label")
            yield Static(self._value, classes="setting-value")

    def update_value(self, value: str) -> None:
        """Update the displayed value."""
        self._value = value
        try:
            self.query_one(".setting-value", Static).update(value)
        except Exception:
            pass


class SectionHeader(Static):
    """A section header in the settings list."""

    DEFAULT_CSS = """
    SectionHeader {
        width: 100%;
        height: 2;
        background: $surface;
        color: $text;
        text-style: bold;
        padding: 0 1;
        border-bottom: solid $primary;
    }
    """


class SettingsTab(Vertical):
    """Tab showing application settings."""

    class SettingSelected(TextualMessage):
        """Message sent when a setting is selected."""
        def __init__(self, setting_id: str):
            self.setting_id = setting_id
            super().__init__()

    DEFAULT_CSS = """
    SettingsTab {
        width: 100%;
        height: 100%;
    }

    SettingsTab #settings-list {
        width: 100%;
        height: 1fr;
    }

    SettingsTab #settings-footer {
        width: 100%;
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
        border-top: solid $primary;
    }
    """

    def __init__(self, **kwargs):
        """Initialize the settings tab."""
        super().__init__(**kwargs)
        self._settings: dict[str, SettingItem] = {}
        # Current values
        self.current_preset = None
        self.current_frequency_slot = None
        self.current_long_name = ""
        self.current_short_name = ""
        self.is_connected = False

    def compose(self) -> ComposeResult:
        """Create the settings view."""
        yield ListView(id="settings-list")
        yield Static("Press Enter to change a setting", id="settings-footer")

    async def on_mount(self) -> None:
        """Set up the settings list."""
        list_view = self.query_one("#settings-list", ListView)

        # Radio Config section
        await list_view.append(ListItem(SectionHeader("Radio Configuration")))

        preset_item = SettingItem("preset", "Radio Preset", self.current_preset or "Unknown")
        self._settings["preset"] = preset_item
        await list_view.append(preset_item)

        freq_item = SettingItem("frequency", "Frequency Slot", self._format_freq_slot())
        self._settings["frequency"] = freq_item
        await list_view.append(freq_item)

        # User settings section
        await list_view.append(ListItem(SectionHeader("User Settings")))

        name_item = SettingItem("username", "Node Name", self._format_name())
        self._settings["username"] = name_item
        await list_view.append(name_item)

        # Display section
        await list_view.append(ListItem(SectionHeader("Display")))

        hop_item = SettingItem("hops", "Show Hop Count", "Press H to toggle")
        self._settings["hops"] = hop_item
        await list_view.append(hop_item)

        # About section
        await list_view.append(ListItem(SectionHeader("About")))

        version_item = SettingItem("version", "Version", "0.1.0")
        self._settings["version"] = version_item
        await list_view.append(version_item)

        nodes_item = SettingItem("node_list", "View All Nodes", "Press Ctrl+N")
        self._settings["node_list"] = nodes_item
        await list_view.append(nodes_item)

        raw_item = SettingItem("raw_monitor", "Raw Monitor", "Press Ctrl+R")
        self._settings["raw_monitor"] = raw_item
        await list_view.append(raw_item)

    def _format_freq_slot(self) -> str:
        """Format the frequency slot display."""
        if self.current_frequency_slot is None:
            return "Unknown"
        if self.current_frequency_slot == 0:
            return "0 (auto)"
        return str(self.current_frequency_slot)

    def _format_name(self) -> str:
        """Format the node name display."""
        if self.current_long_name and self.current_short_name:
            return f"{self.current_long_name} ({self.current_short_name})"
        return self.current_long_name or self.current_short_name or "Not set"

    def update_values(
        self,
        preset: str = None,
        frequency_slot: int = None,
        long_name: str = None,
        short_name: str = None,
        is_connected: bool = None,
    ) -> None:
        """Update displayed setting values."""
        if preset is not None:
            self.current_preset = preset
            if "preset" in self._settings:
                self._settings["preset"].update_value(preset)

        if frequency_slot is not None:
            self.current_frequency_slot = frequency_slot
            if "frequency" in self._settings:
                self._settings["frequency"].update_value(self._format_freq_slot())

        if long_name is not None:
            self.current_long_name = long_name
        if short_name is not None:
            self.current_short_name = short_name
        if long_name is not None or short_name is not None:
            if "username" in self._settings:
                self._settings["username"].update_value(self._format_name())

        if is_connected is not None:
            self.is_connected = is_connected

    @on(ListView.Selected, "#settings-list")
    def on_setting_selected(self, event: ListView.Selected) -> None:
        """Handle setting selection."""
        if isinstance(event.item, SettingItem):
            # Only allow changing certain settings
            if event.item.setting_id in ("preset", "frequency", "username"):
                if self.is_connected:
                    self.post_message(self.SettingSelected(event.item.setting_id))
