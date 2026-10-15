# Interactive research chat

`ssift chat` opens a Textual terminal interface backed by the same Python research
runtime as `ssift ask`. It supports follow-ups about retrieved articles, retained
citations, streamed drafts, and cancellation. Sessions stay in memory.

## Start a conversation

Set `OPENROUTER_API_KEY` securely in the environment and choose a tool-capable model:

```sh
export SOURCESIFT_MODEL=openai/gpt-6.1-sol
export SOURCESIFT_REASONING_EFFORT=medium
ssift chat
ssift chat --file project.md
ssift chat --config ~/.config/sourcesift/config.toml
```

Both stdin and stdout must be terminals. For pipes or quick requests, use
`ssift ask "Check tech"`. A bare `ssift` displays command help.

Try “Check tech and AI,” then “Which matters most for my project?” or “Read the
second article.” Follow-ups use the completed conversation and its evidence.
References below each answer include URLs, dates, and feed-summary/article status.
URLs are displayed for selection/copying; model-generated links do not launch a
browser automatically.

## Controls

| Key | Action |
|---|---|
| Enter | Send the current input or run a slash command |
| Shift+Enter | Insert a newline |
| Ctrl+J | Insert a newline (terminal-compatible fallback) |
| Alt+Enter | Insert a newline when reported by the terminal |
| Esc | Cancel the active turn, or close the context viewer |
| Ctrl+Q | Quit |

Shift+Enter requires a terminal that reports modified Enter keys. If your terminal
sends it as plain Enter, use Ctrl+J instead. Pasted multiline text stays in the
input until you press Enter.

Type a command in the prompt and press Enter:

| Command | Action |
|---|---|
| `/new` | Start a new session and reload context |
| `/context` | Inspect the loaded context; Esc closes the viewer |
| `/cancel` | Cancel the active turn |
| `/help` | Show controls and commands |
| `/quit` | Quit |

Only one turn runs at once. You may compose the next prompt while research runs;
submit it after the current turn completes. Slash commands remain available during
research, but cancel first before starting a new session.

Streaming text is labeled as a draft. Citation repair can replace it. The final
answer and references appear only after validation. A failed or cancelled turn is
shown in the transcript but is not added to conversation memory; previous completed
turns remain available. Cancellation stops local work, but cannot undo requests
already sent or charges already incurred at the provider.

## Personal context

Keep runtime settings in TOML and your interests and preferences in Markdown.
For example, `~/.config/sourcesift/config.toml` on Linux:

```toml
[agent]
model = "openai/gpt-6.1-sol"
reasoning_effort = "medium"

[context]
instructions_file = "context.md"
# files = ["project.md"]  # optional background material

[sources]
timezone = "America/Chicago"
```

Example `context.md` beside that config:

```markdown
# About my work
I build Python tools and run a small marketing consultancy.

# Research priorities
Focus on practical AI developments, developer tools, and marketing changes.
Explain why an item matters for my work.

# Response preferences
Start with a short briefing. Include dates and citations.
Separate reported facts from your interpretation.
```

This is explicitly selected personal guidance, similar in purpose to an agent
instructions file. Its filename is configurable. SourceSift does not automatically
read a repository's `AGENTS.md`, search parent directories, or learn preferences.
Background documents and fetched pages remain research material. Guidance cannot
override grounding, network restrictions, or the current task.

Context is loaded at session creation. Inspect its actual contents with `/context`;
after editing a file, `/new` reloads it and clears the conversation. An unreadable
file leaves the current session intact. Restart chat to reload model/source/TOML
settings. Configured paths are relative to their TOML file; `--file` paths are
relative to the working directory. All selected context is sent to the configured
model through OpenRouter.

## History and evidence limits

Citation IDs stay stable within a session, including feed-summary to article
upgrades. Earlier results retain their original provenance. Reused evidence is
explicitly labeled as retained; it does not establish that news is still current.
Ask for a fresh check when needed.

Default limits are 20 completed turns and 512 KiB of serialized history/evidence.
The next request is checked against the byte budget too. At a limit, start a new
session; SourceSift does not silently drop or summarize history. These are byte
guards, not model-token counts. Per-turn model, HTTP, source, and timeout budgets
still apply. See [configuration](configuration.md) for settings.

Quitting discards the conversation. Saving/resuming sessions, automatic context
compaction, and an article archive remain future work. The public
[`Session` API](sdk.md#interactive-sessions) provides the same behavior without Textual.
