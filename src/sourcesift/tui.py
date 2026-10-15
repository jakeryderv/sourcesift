"""Textual presentation for the shared asyncio session runtime."""

import asyncio
import re
from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import HorizontalScroll, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Markdown,
    OptionList,
    Select,
    Static,
    TextArea,
)
from textual.worker import Worker

from sourcesift.cli import render_result
from sourcesift.completion import (
    COMMANDS,
    MENTION,
    FileIndex,
    attachment_path,
    discover_files,
    fuzzy_matches,
    mention,
    mentioned_paths,
)
from sourcesift.core.config import AgentSettings, ContextSettings
from sourcesift.core.context import prepare_request
from sourcesift.core.session import Session
from sourcesift.errors import SourceSiftError
from sourcesift.model_catalog import ModelCatalog
from sourcesift.models import Request, Result, SessionEvent
from sourcesift.tui_panels import HELP, HelpScreen, ModelScreen


class ChatInput(TextArea):
    """Submit with Enter while preserving multiline editing and paste."""

    class Submitted(Message):
        """The user requested submission of the current prompt."""

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            self.post_message(self.Submitted())
        elif event.key in {"shift+enter", "alt+enter", "ctrl+j"}:
            event.stop()
            event.prevent_default()
            # Use TextArea's keyboard edit path for selection and undo support.
            await super()._on_key(events.Key("enter", "\n"))
        else:
            await super()._on_key(event)


class ContextScreen(ModalScreen[None]):
    """Inspect exactly the context loaded into this session, without markup."""

    BINDINGS: ClassVar = [Binding("escape", "dismiss", "Close")]

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.session = session

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="context-panel"):
            yield Static("Loaded context · Esc to close", classes="label")
            if not self.session.context:
                yield Static(
                    "No context files configured. Set [context].instructions_file or [context].files in config.toml."
                )
            for document in self.session.context:
                yield Static(
                    f"{document.name} ({document.role})\n\n{document.text}",
                    markup=False,
                )
        yield Footer()


class ChatApp(App[None]):
    """A minimal research conversation; model and retrieval logic live in Session."""

    TITLE = "SourceSift"
    CSS = """
    Screen { background: $surface; }
    #transcript { height: 1fr; padding: 1 2; }
    .label { color: $accent; text-style: bold; margin-top: 1; }
    .message { height: auto; margin-bottom: 1; }
    .references { color: $text-muted; margin-bottom: 1; }
    #status { height: auto; max-height: 3; padding: 0 2; color: $text-muted; }
    #prompt { height: 5; margin: 0 1; border: round $primary; }
    #completions { height: auto; max-height: 9; margin: 0 1; border: round $accent; display: none; }
    #attachments { height: 3; margin: 0 1; display: none; }
    #attachments Button { min-width: 8; width: auto; margin-right: 1; }
    ModalScreen { align: center middle; }
    #context-panel, .panel { width: 90%; height: 85%; padding: 1 2; border: round $primary; background: $surface; }
    #context-panel Static, .panel Static { margin-bottom: 1; }
    .panel Input, .panel Select { margin-bottom: 1; }
    .panel Button { dock: bottom; }
    ModelScreen .panel Static, ModelScreen .panel Input, ModelScreen .panel Select { margin-bottom: 0; }
    #model-error { color: $error; }
    #model-completions { height: auto; max-height: 7; display: none; border: round $accent; }
    #catalog-status { height: auto; color: $text-muted; }
    """
    BINDINGS: ClassVar = [
        Binding("escape", "cancel_turn", "Cancel", priority=True),
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("up", "composer_up", show=False, priority=True),
        Binding("down", "composer_down", show=False, priority=True),
        Binding("enter,tab", "complete", show=False, priority=True),
    ]

    def __init__(self, session: Session, *, workspace: Path | None = None) -> None:
        super().__init__()
        self.session = session
        self._turn_worker: Worker | None = None
        self._draft_widget: Static | None = None
        self._draft = ""
        self._rendered_draft = ""
        self._turn_active = False
        self._turn_started = False
        self._cancel_requested = False
        self.workspace = (workspace or Path.cwd()).resolve()
        self._file_index = FileIndex(())
        self._files_ready = False
        self._file_error = ""
        self._chosen: set[str] = set()
        self._attachments: list[str] = []
        self._matches: list[str] = []
        self._completion: tuple[str, str, int, int] | None = None
        self._dismissed: tuple[str, tuple[int, int]] | None = None
        self._history: list[str] = []
        self._history_index: int | None = None
        self._history_draft = ""
        self._model_catalog = ModelCatalog()

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="transcript"):
            yield Static("Ask a question, then follow the evidence.", classes="label")
            yield Static(HELP, markup=False)
        yield Static("", id="status", markup=False)
        yield OptionList(id="completions")
        yield HorizontalScroll(id="attachments")
        yield ChatInput(
            id="prompt",
            placeholder="Ask anything · / commands · @ files · Enter to send",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._status("Ready")
        self.query_one("#prompt", TextArea).focus()
        self.set_interval(0.08, self._flush_draft)
        self.query_one("#completions", OptionList).can_focus = False
        if (
            not self.session.settings.agent.model
            or self.session.settings.agent.api_key is None
            or not self.session.settings.agent.api_key.get_secret_value().strip()
        ):
            self.action_show_model()

    @work(group="file-index", exclusive=True)
    async def _index_files(self) -> None:
        try:
            self._file_index = await asyncio.to_thread(discover_files, self.workspace)
        except SourceSiftError as exc:
            self._file_error = str(exc)
        self._files_ready = True
        self._update_completions()

    def _composer_state(self) -> tuple[str, tuple[int, int]]:
        editor = self.query_one("#prompt", TextArea)
        return editor.text, editor.cursor_location

    def _update_completions(self) -> None:
        editor = self.query_one("#prompt", TextArea)
        popup = self.query_one("#completions", OptionList)
        self._completion = None
        if self._composer_state() == self._dismissed or isinstance(
            self.screen, ModalScreen
        ):
            popup.display = False
            return
        self._dismissed = None
        row, column = editor.cursor_location
        line = editor.document.get_line(row)
        if not editor.selection.is_empty:
            popup.display = False
            return
        if (
            row == 0
            and line.startswith("/")
            and "\n" not in editor.text
            and not any(c.isspace() for c in line)
        ):
            kind, query, start = "command", line, 0
            candidates = list(COMMANDS)
        elif match := re.search(r'(?:^|\s)@([^\s"]*)$', line[:column]):
            kind, query, start = "file", match[1], column - len(match[1]) - 1
            candidates = list(self._file_index.paths)
            if not self._files_ready and not any(
                worker.group == "file-index" for worker in self.workers
            ):
                self._index_files()
        else:
            popup.display = False
            return
        self._completion = kind, query, row, start
        matches = fuzzy_matches(query, candidates)
        self._matches = [name for name, _ in matches]
        options = []
        for name, offsets in matches:
            text = Text(name)
            for offset in offsets:
                text.stylize("bold cyan", offset, offset + 1)
            if kind == "command":
                text.append("  " + COMMANDS[name], style="dim")
            options.append(text)
        popup.set_options(options)
        popup.highlighted = 0 if options else None
        popup.border_title = (
            "Commands" if kind == "command" else "Attach a workspace file"
        )
        message = "↑/↓ choose · Tab/Enter accept · Esc close"
        if not options:
            message = self._file_error or (
                "Finding files…"
                if kind == "file" and not self._files_ready
                else "No matches · Esc close"
            )
        elif kind == "file" and self._file_index.limited:
            message = "Partial file list · launch in a smaller directory for more"
        popup.border_subtitle = message
        popup.display = True

    async def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id == "prompt":
            await self._update_attachments()
            self._update_completions()

    def on_text_area_selection_changed(self, event: TextArea.SelectionChanged) -> None:
        if event.text_area.id == "prompt":
            self._update_completions()

    async def _update_attachments(self) -> None:
        selected = sorted(
            self._chosen & mentioned_paths(self.query_one("#prompt", TextArea).text)
        )
        if selected == self._attachments:
            return
        self._attachments = selected
        bar = self.query_one("#attachments", HorizontalScroll)
        await bar.remove_children()
        bar.display = bool(selected)
        if selected:
            await bar.mount(
                *(
                    Button(Text("× " + path), id=f"attachment-{index}")
                    for index, path in enumerate(selected)
                )
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id and event.button.id.startswith("attachment-"):
            path = self._attachments[int(event.button.id.removeprefix("attachment-"))]
            editor = self.query_one("#prompt", TextArea)
            editor.load_text(
                MENTION.sub(
                    lambda match: "" if path in mentioned_paths(match[0]) else match[0],
                    editor.text,
                )
            )
            editor.focus()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action not in {"complete", "composer_up", "composer_down"}:
            return True
        if not isinstance(self.focused, ChatInput) or isinstance(
            self.screen, ModalScreen
        ):
            return False
        if self.query_one("#completions", OptionList).display:
            return True
        if action == "complete":
            return False
        editor = self.query_one("#prompt", TextArea)
        row, _ = editor.cursor_location
        return (
            bool(self._history)
            and editor.selection.is_empty
            and (
                row == 0
                if action == "composer_up"
                else row == editor.document.line_count - 1
            )
        )

    def action_composer_up(self) -> None:
        if self.query_one("#completions", OptionList).display:
            self.query_one("#completions", OptionList).action_cursor_up()
        else:
            self._recall(-1)

    def action_composer_down(self) -> None:
        if self.query_one("#completions", OptionList).display:
            self.query_one("#completions", OptionList).action_cursor_down()
        else:
            self._recall(1)

    def _recall(self, direction: int) -> None:
        editor = self.query_one("#prompt", TextArea)
        if self._history_index is None:
            if direction > 0:
                return
            self._history_draft = editor.text
            self._history_index = len(self._history)
        self._history_index = max(
            0, min(len(self._history), self._history_index + direction)
        )
        text = (
            self._history[self._history_index]
            if self._history_index < len(self._history)
            else self._history_draft
        )
        editor.load_text(text)
        editor.move_cursor(editor.document.end)
        self._dismissed = self._composer_state()

    def action_complete(self) -> None:
        popup = self.query_one("#completions", OptionList)
        if self._completion is None or popup.highlighted is None:
            return
        selected = self._matches[popup.highlighted]
        kind, _, row, start = self._completion
        editor = self.query_one("#prompt", TextArea)
        if kind == "file":
            self._chosen.add(selected)
            replacement = mention(selected) + " "
            _, column = editor.cursor_location
            suffix = re.match(r'[^\s"]*', editor.document.get_line(row)[column:])
            assert suffix is not None
            end = row, column + len(suffix[0])
        else:
            replacement = selected
            end = editor.document.end
        editor.replace(replacement, (row, start), end, maintain_selection_offset=False)
        self._dismissed = self._composer_state()
        popup.display = False
        editor.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id == "completions":
            self.action_complete()

    def _status(self, message: str) -> None:
        agent = self.session.settings.agent
        self.query_one("#status", Static).update(
            f"{agent.model} · {agent.reasoning_effort or 'default'} effort · "
            f"{len(self.session.context)} context files · {len(self.session.turns)} turns\n{message}"
        )

    def _event(self, event: SessionEvent) -> None:
        if event.kind == "draft":
            self._draft += event.text
        elif event.kind == "reset":
            self._draft = ""
        else:
            self._status(event.text)

    def _flush_draft(self) -> None:
        if self._draft_widget is not None and self._draft != self._rendered_draft:
            self._draft_widget.update("Draft · checking citations…\n" + self._draft)
            self._rendered_draft = self._draft
            self.query_one("#transcript", VerticalScroll).scroll_end(animate=False)

    async def on_chat_input_submitted(self) -> None:
        await self.action_send()

    async def action_send(self) -> None:
        editor = self.query_one("#prompt", TextArea)
        prompt = editor.text.strip()
        if not prompt:
            return
        if prompt.startswith("/"):
            if prompt == "/new":
                await self.action_new_session()
            elif prompt == "/context":
                self.action_show_context()
            elif prompt == "/cancel":
                self.action_cancel_turn()
            elif prompt == "/quit":
                self.exit()
            elif prompt == "/help":
                self.push_screen(HelpScreen())
            elif prompt == "/model":
                self.action_show_model()
            else:
                self._status("Unknown command. Type / to see commands, or /help.")
                return
            editor.clear()
            return
        if self._turn_active:
            self._status(
                "A turn is running. Esc cancels it; your next draft stays in the input."
            )
            return
        agent = self.session.settings.agent
        if (
            not agent.model
            or agent.api_key is None
            or not agent.api_key.get_secret_value().strip()
        ):
            self.action_show_model()
            return
        # Set before awaiting mount so two submit events cannot start two turns.
        self._turn_active = True
        self._turn_started = False
        self._cancel_requested = False
        selected = sorted(self._chosen & mentioned_paths(editor.text))
        request: str | Request = prompt
        if selected:
            try:
                request = await asyncio.to_thread(
                    self._attachment_request, prompt, selected
                )
            except SourceSiftError as exc:
                self._turn_active = False
                self._status(str(exc))
                return
        self._history.append(editor.text)
        self._history = self._history[-100:]
        self._history_index = None
        editor.clear()
        transcript = self.query_one("#transcript", VerticalScroll)
        self._draft = self._rendered_draft = ""
        self._draft_widget = Static("Thinking…", classes="message", markup=False)
        await transcript.mount(
            Static("You", classes="label"),
            Static(prompt, classes="message", markup=False),
            Static("SourceSift", classes="label"),
            self._draft_widget,
        )
        transcript.scroll_end(animate=False)
        self._turn_worker = self._run_turn(request)

    def _attachment_request(self, prompt: str, selected: list[str]) -> Request:
        settings = self.session.settings.model_copy(
            update={"context": ContextSettings()}
        )
        paths = [attachment_path(self.workspace, path) for path in selected]
        prepared = prepare_request(Request(prompt=prompt), settings, files=paths)
        # Preserve relative labels when two directories contain the same basename.
        documents = tuple(
            doc.model_copy(update={"name": path})
            for doc, path in zip(prepared.context, selected, strict=True)
        )
        initial = self.session.context if not self.session.turns else ()
        prepare_request(Request(prompt=prompt, context=initial + documents), settings)
        return Request(prompt=prompt, context=documents)

    @work(group="research", exit_on_error=False)
    async def _run_turn(self, prompt: str | Request) -> None:
        try:
            self._turn_started = True
            if self._cancel_requested:
                raise asyncio.CancelledError
            result = await self.session.run(prompt, on_event=self._event)
            # The result is committed: finish rendering it even if Esc arrives now.
            self._turn_started = False
            await self._show_result(result)
            self._status("Ready")
        except asyncio.CancelledError:
            if self._draft_widget is not None:
                self._draft_widget.update(
                    "Cancelled. This turn was not added to conversation memory."
                )
            self._status("Cancelled · ready")
            raise
        except SourceSiftError as exc:
            if self._draft_widget is not None:
                self._draft_widget.update(str(exc))
            self._status("Turn failed · previous conversation preserved")
        except Exception:  # noqa: BLE001 -- UI boundary must not expose provider internals
            # Never render provider response bodies, credentials, or tracebacks.
            if self._draft_widget is not None:
                self._draft_widget.update(
                    "Unexpected error. Try again or start a new session."
                )
            self._status("Turn failed")
        finally:
            self._draft_widget = None
            self._turn_started = False
            self._turn_active = False

    async def _show_result(self, result: Result) -> None:
        if self._draft_widget is not None:
            await self._draft_widget.remove()
            self._draft_widget = None
        transcript = self.query_one("#transcript", VerticalScroll)
        await transcript.mount(
            Markdown(result.answer, classes="message", open_links=False)
        )
        details = render_result(
            result.model_copy(update={"answer": ""}), "markdown"
        ).strip()
        if details:
            await transcript.mount(Static(details, classes="references", markup=False))
        transcript.scroll_end(animate=False)

    def action_cancel_turn(self) -> None:
        if isinstance(self.screen, ModalScreen):
            for select in self.screen.query(Select):
                if select.expanded:
                    select.expanded = False
                    return
            if (
                isinstance(self.screen, ModelScreen)
                and self.screen.dismiss_completions()
            ):
                return
            self.pop_screen()
            return
        popup = self.query_one("#completions", OptionList)
        if popup.display:
            popup.display = False
            self._dismissed = self._composer_state()
            return
        if self._turn_active:
            self._status("Cancelling…")
            self._cancel_requested = True
            # Cancelling an unstarted asyncio task skips the coroutine's finally
            # block. Let it start and consume the pending cancellation instead.
            if self._turn_started and self._turn_worker is not None:
                self._turn_worker.cancel()

    async def action_new_session(self) -> None:
        if self._turn_active:
            self._status(
                "Cancel the active turn with Esc before starting a new session."
            )
            return
        try:
            self.session.reset()
        except SourceSiftError as exc:
            self._status(str(exc))
            return
        await self.query_one("#transcript", VerticalScroll).remove_children()
        self._files_ready = False
        self._file_error = ""
        self._status("New session · context reloaded")

    def action_show_context(self) -> None:
        self.push_screen(ContextScreen(self.session))

    def action_show_model(self) -> None:
        if self._turn_active:
            self._status("Finish or cancel the active turn before changing models.")
            return
        self.push_screen(
            ModelScreen(self.session.settings.agent, self._model_catalog),
            self._apply_model,
        )

    def _apply_model(self, agent: AgentSettings | None) -> None:
        if agent is not None:
            self.session.settings = self.session.settings.model_copy(
                update={"agent": agent}
            )
            self._status("Model settings applied to this chat")
