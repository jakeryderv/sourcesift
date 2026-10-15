"""Textual presentation for the shared asyncio session runtime."""

import asyncio
from typing import ClassVar

from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Markdown, Static, TextArea
from textual.worker import Worker

from sourcesift.cli import render_result
from sourcesift.core.session import Session
from sourcesift.errors import SourceSiftError
from sourcesift.models import Result, SessionEvent

HELP = "Enter send · Shift+Enter newline (Ctrl+J fallback) · Esc cancel\nCommands: /new, /context, /cancel, /help, /quit. Conversations stay in memory."


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
    ContextScreen { align: center middle; }
    #context-panel { width: 90%; height: 85%; padding: 1 2; border: round $primary; background: $surface; }
    #context-panel Static { margin-bottom: 1; }
    """
    BINDINGS: ClassVar = [
        Binding("escape", "cancel_turn", "Cancel", priority=True),
        Binding("ctrl+q", "quit", "Quit", priority=True),
    ]

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.session = session
        self._turn_worker: Worker | None = None
        self._draft_widget: Static | None = None
        self._draft = ""
        self._rendered_draft = ""
        self._turn_active = False
        self._turn_started = False
        self._cancel_requested = False

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="transcript"):
            yield Static("Ask a question, then follow the evidence.", classes="label")
            yield Static(HELP, markup=False)
        yield Static("", id="status", markup=False)
        yield ChatInput(
            id="prompt",
            placeholder="Ask anything, or /help · Enter to send · Shift+Enter for newline",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._status("Ready")
        self.query_one("#prompt", TextArea).focus()
        self.set_interval(0.08, self._flush_draft)

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
                self._status(HELP)
            else:
                self._status(
                    "Unknown command. Use /new, /context, /cancel, /help, or /quit."
                )
                return
            editor.clear()
            return
        if self._turn_active:
            self._status(
                "A turn is running. Esc cancels it; your next draft stays in the input."
            )
            return
        # Set before awaiting mount so two submit events cannot start two turns.
        self._turn_active = True
        self._turn_started = False
        self._cancel_requested = False
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
        self._turn_worker = self._run_turn(prompt)

    @work(group="research", exit_on_error=False)
    async def _run_turn(self, prompt: str) -> None:
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
        if isinstance(self.screen, ContextScreen):
            self.pop_screen()
            return
        if self._turn_active and self._turn_worker is not None:
            self._status("Cancelling…")
            self._cancel_requested = True
            # Cancelling an unstarted asyncio task skips the coroutine's finally
            # block. Let it start and consume the pending cancellation instead.
            if self._turn_started:
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
        self._status("New session · context reloaded")

    def action_show_context(self) -> None:
        self.push_screen(ContextScreen(self.session))
