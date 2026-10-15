"""Small interactive panels used by the research chat."""

from typing import ClassVar

from pydantic import ValidationError
from rich.text import Text
from textual import events, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, OptionList, Select, Static

from sourcesift.completion import COMMANDS, fuzzy_matches
from sourcesift.core.config import AgentSettings
from sourcesift.errors import ConfigurationError
from sourcesift.model_catalog import CatalogModel, ModelCatalog

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

    BINDINGS: ClassVar = [
        Binding("escape", "dismiss", "Cancel"),
        Binding("up", "model_previous", show=False, priority=True),
        Binding("down", "model_next", show=False, priority=True),
        Binding("enter", "model_complete", show=False, priority=True),
        Binding("tab", "model_tab", show=False, priority=True),
    ]

    def __init__(
        self, agent: AgentSettings, catalog: ModelCatalog | None = None
    ) -> None:
        super().__init__()
        self.agent = agent
        self.catalog = catalog or ModelCatalog()
        self._models: tuple[CatalogModel, ...] = ()
        self._matches: list[CatalogModel] = []
        self._dismissed_value: str | None = None
        self._catalog_message = (
            "Loading OpenRouter models… You can also enter an ID manually."
        )

    def compose(self) -> ComposeResult:
        with Vertical(classes="panel"):
            with VerticalScroll(id="model-fields"):
                yield Static("Model setup", classes="label")
                yield Static("Applies to this chat only. Esc closes without changes.")
                yield Static("OpenRouter model (provider/model)")
                yield Input(
                    value=self.agent.model or "",
                    placeholder="Search models or enter provider/model",
                    id="model-name",
                )
                yield OptionList(id="model-completions")
                yield Static(self._catalog_message, id="catalog-status", markup=False)
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
                yield Input(
                    password=True, id="model-key", placeholder="OpenRouter API key"
                )
                yield Static("", id="model-error", markup=False)
            yield Button("Apply", id="apply-model", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#model-completions", OptionList).can_focus = False
        self.query_one("#model-name", Input).focus()
        self._load_catalog()

    @work(group="model-catalog", exclusive=True)
    async def _load_catalog(self) -> None:
        try:
            self._models = await self.catalog.load()
            self._catalog_message = (
                "Tool-capable text models · ↑/↓ choose · Tab/Enter select"
            )
        except ConfigurationError as exc:
            self._catalog_message = str(exc)
        self._update_models()

    def _update_models(self) -> None:
        field = self.query_one("#model-name", Input)
        popup = self.query_one("#model-completions", OptionList)
        query = "".join(field.value.split())
        self.query_one("#catalog-status", Static).update(self._catalog_message)
        if not field.has_focus or field.value == self._dismissed_value:
            popup.display = False
            return
        self._dismissed_value = None
        # Match each field separately: a query must not span ID/name boundaries.
        # Prefer ID matches, then supplement them with display-name matches.
        by_id = {model.id: model for model in self._models}
        matches = [
            (by_id[identifier], offsets)
            for identifier, offsets in fuzzy_matches(query, list(by_id))
        ]
        seen = {model.id for model, _ in matches}
        by_name: dict[str, list[CatalogModel]] = {}
        for model in self._models:
            by_name.setdefault(model.name, []).append(model)
        for name, offsets in fuzzy_matches(query, list(by_name)):
            for model in by_name[name]:
                if model.id not in seen:
                    matches.append(
                        (model, tuple(offset + len(model.id) + 2 for offset in offsets))
                    )
                    seen.add(model.id)
        matches = matches[:30]
        self._matches = [model for model, _ in matches]
        options = []
        for model, offsets in matches:
            text = Text(f"{model.id}  {model.name}")
            for offset in offsets:
                text.stylize("bold cyan", offset, offset + 1)
            options.append(text)
        popup.set_options(options)
        popup.highlighted = 0 if options else None
        popup.display = bool(options)
        if self._models and not options:
            self.query_one("#catalog-status", Static).update(
                "No matching models. You can still enter a provider/model ID manually."
            )

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "model-name":
            self._update_models()

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        if event.widget.id == "model-name":
            self._update_models()
        elif isinstance(event.widget, (Input, Select, Button)):
            # Hiding on Input.Blur would remove a clicked option before its
            # mouse selection arrives. Hide when another form field gains focus.
            self.query_one("#model-completions", OptionList).display = False

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "model_tab":
            return True
        if action.startswith("model_"):
            return (
                self.query_one("#model-name", Input).has_focus
                and self.query_one("#model-completions", OptionList).display
            )
        return True

    def action_model_tab(self) -> None:
        if self.check_action("model_complete", ()):
            self.action_model_complete()
        else:
            self.focus_next()

    def action_model_previous(self) -> None:
        self.query_one("#model-completions", OptionList).action_cursor_up()

    def action_model_next(self) -> None:
        self.query_one("#model-completions", OptionList).action_cursor_down()

    def action_model_complete(self) -> None:
        popup = self.query_one("#model-completions", OptionList)
        if popup.highlighted is None:
            return
        field = self.query_one("#model-name", Input)
        value = self._matches[popup.highlighted].id
        self._dismissed_value = value
        field.value = value
        field.cursor_position = len(value)
        popup.display = False
        field.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id == "model-completions":
            event.stop()
            self.action_model_complete()

    def dismiss_completions(self) -> bool:
        """Let Esc close suggestions before closing the setup panel."""
        popup = self.query_one("#model-completions", OptionList)
        if not popup.display:
            return False
        self._dismissed_value = self.query_one("#model-name", Input).value
        popup.display = False
        return True

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
