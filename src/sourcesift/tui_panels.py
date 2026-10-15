"""Small interactive panels used by the research chat."""

from typing import ClassVar

from pydantic import ValidationError
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Select, Static

from sourcesift.completion import COMMANDS
from sourcesift.core.config import AgentSettings

HELP = "Enter send · Shift+Enter newline (Ctrl+J fallback) · / commands · @ files · Esc cancel"


class HelpScreen(ModalScreen[None]):
    """Show discoverable controls without clipping them to the status line."""

    BINDINGS: ClassVar = [Binding("escape", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="panel"):
            yield Static("Chat controls", classes="label")
            yield Static(HELP, markup=False)
            yield Static(
                "Picker: ↑/↓ navigate · Enter/Tab accept · Esc dismiss\n"
                "Accepting a suggestion never sends a prompt.\n"
                "History: ↑ at the first line / ↓ at the last line.\n"
                "Attachments: select with @, then click × or delete the mention to remove.\n"
                "Only selected files are read, when you send.\n"
                "Ctrl+Q quits. Conversations and model changes stay in memory.",
                markup=False,
            )
            for command, description in COMMANDS.items():
                yield Static(f"{command}  {description}", markup=False)
            yield Button("Close", id="close-help")

    def on_button_pressed(self) -> None:
        self.dismiss()


class ModelScreen(ModalScreen[AgentSettings | None]):
    """Choose explicit model settings; keep credentials out of saved files."""

    BINDINGS: ClassVar = [Binding("escape", "dismiss", "Cancel")]

    def __init__(self, agent: AgentSettings) -> None:
        super().__init__()
        self.agent = agent

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="panel"):
            yield Static("Model setup", classes="label")
            yield Static("Applies to this chat only. Esc closes without changes.")
            yield Static("OpenRouter model (provider/model)")
            yield Input(
                value=self.agent.model or "",
                placeholder="provider/model",
                id="model-name",
            )
            yield Static("Reasoning effort")
            yield Select(
                [
                    (name, name)
                    for name in [
                        "default",
                        "none",
                        "minimal",
                        "low",
                        "medium",
                        "high",
                        "xhigh",
                    ]
                ],
                value=self.agent.reasoning_effort or "default",
                allow_blank=False,
                id="model-effort",
            )
            yield Static(
                "API key already loaded; leave blank to keep it."
                if self.agent.api_key
                else "OpenRouter API key (kept in memory only)"
            )
            yield Input(password=True, id="model-key", placeholder="OpenRouter API key")
            yield Static("", id="model-error", markup=False)
            yield Button("Apply", id="apply-model", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "apply-model":
            return
        key = self.query_one("#model-key", Input).value.strip()
        effort = self.query_one("#model-effort", Select).value
        try:
            agent = AgentSettings.model_validate(
                {
                    "model": self.query_one("#model-name", Input).value.strip(),
                    "reasoning_effort": None if effort == "default" else effort,
                    "api_key": key or self.agent.api_key,
                }
            )
        except ValidationError:
            self.query_one("#model-error", Static).update(
                "Enter a valid provider/model ID and reasoning effort."
            )
            return
        if agent.api_key is None or not agent.api_key.get_secret_value().strip():
            self.query_one("#model-error", Static).update(
                "Enter an API key, or launch with OPENROUTER_API_KEY set."
            )
            return
        self.query_one("#model-key", Input).value = ""
        self.dismiss(agent)
