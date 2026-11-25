# Web app

`ssift web` opens the research chat as a page in your browser. It is the
interactive interface: saved conversations, answers with citations and charts,
and artifacts you can keep and export.

```console
$ ssift web
SourceSift is running at http://127.0.0.1:51023/#…
Press Ctrl+C to stop.
```

The page opens in your default browser. The server stops with Ctrl+C.

| Option | Effect |
|---|---|
| `--port N` | Listen on a fixed port; by default a free one is chosen |
| `--no-browser` | Print the link without opening a browser |
| `--file`, `-f` | Attach a context file to each new conversation; repeatable |
| `--no-save` | Keep conversations in memory only; by default each is saved |
| `--continue`, `-c` | Open the most recently saved conversation first |
| `--model`, `--reasoning-effort`, `--config` | As for [`ssift ask`](cli.md) |

## The page

The page has three parts.

**Conversations, on the left.** Every saved conversation, newest first, with the
number of artifacts it holds. Click one to reopen it. Hover a row to rename or
delete it; deleting asks once more, then removes the conversation and its
artifact files. **New chat** starts a conversation with every source enabled. On
a narrow window the list hides behind the ☰ button.

**The chat, in the middle.**

- Enter sends; Shift+Enter adds a line; the send button becomes Stop while a
  turn runs. Clicking a suggestion sends it.
- While the agent works, the turn shows what it is doing, one step per lookup
  ("Getting data from Weather", "Checking NPR, BBC News", "Drawing a line
  chart"). Each step expands to show its parameters and what came back. When the
  answer arrives the list folds into one line, such as "3 steps · 10s".
- A [figure](research.md#figures) appears in the answer where the model placed
  it. It is a picture drawn by SourceSift from the rows a source returned.
- Each numbered citation chip opens the Evidence panel at that reference, with
  its publisher, kind, dates, and any limitations. The line under an answer
  ("2 sources · 1 note") expands to the same references and the answer's notes.
- **Copy** puts the answer's Markdown on the clipboard. **Keep as artifact**
  turns the answer into an artifact.
- **Sources** lets you browse the catalog and choose which sources this chat may
  use. **Evidence** lists everything retrieved in this chat.

**The side pane, on the right.** It opens for an artifact, the evidence list, or
the source list, and closes with **Close**.

## Artifacts

An artifact is a document that lasts beyond one answer: a briefing, a report, a
comparison. Ask for one ("write a report on…") and the model writes it; ask for
a change ("make it shorter") and the model revises the same artifact, which
gains a version number. An artifact can cite evidence and place figures, as an
answer can. A conversation holds up to 12.

The pane shows the artifact with its notes and the references it cites, and
offers:

| Action | Result |
|---|---|
| **Copy** | The artifact's Markdown on the clipboard |
| **Download** | A zip with the artifact's [Quarto](https://quarto.org) file (`.qmd`), its references and their citation style, and its figures |
| **Export as…** | A web page, PDF, Word document, or slides |

**Export as…** appears only when Quarto is installed on your computer, because
Quarto does the conversion. SourceSift does not need it for anything else. The
`.qmd` file opens as Markdown in any editor, and you can render it yourself
later with `quarto render`. See [artifact files](research.md#artifact-files) for
what the folder contains and why rendering it runs no code.

## Saved conversations

Each conversation is saved after every completed turn, in its own folder in the
[sessions directory](configuration.md#saved-conversations). The folder also
holds the conversation's artifacts as files, updated whenever one changes.
A saved conversation contains your prompts, the answers, retrieved text, and the
text of attached files, so the folder is readable only by you.

Reloading the page keeps the open conversation. Start with `--no-save` to keep
conversations in memory only; they are gone when the server stops, and the list
on the left stays empty.

## Access and privacy

The server is for one person on one computer.

- It listens on the loopback address `127.0.0.1` only, so other devices on your
  network cannot reach it.
- The printed link ends in a random token for this launch. The page sends it with
  every request, and requests without it are refused. Treat the link like a
  password while the server is running.
- Requests must name the server's own address and, when the browser reports where
  a request came from, that must be the page itself. This stops other websites
  open in your browser from using the server.
- The page loads nothing from other hosts: no scripts, styles, fonts, or images.
  Figures are drawn on your computer. Raw HTML in a model's answer is shown as
  text, and the only images shown are figures.
- Prompts, attached files, and retrieved text still go to the configured model
  through OpenRouter, as with `ssift ask`.

## Not yet in the page

Model and reasoning choices are set when starting the server, and files are
attached with `--file` rather than uploaded.
