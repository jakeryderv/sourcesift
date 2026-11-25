# Web app

`ssift web` opens the research chat as a page in your browser. It is the
interactive interface: a conversation with citations, plus charts, tables, and
headline figures built from retrieved data.

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
| `--file`, `-f` | Attach a context file to each conversation; repeatable |
| `--save` | Save each conversation after every completed turn |
| `--continue`, `-c` | Continue the most recently saved conversation |
| `--model`, `--reasoning-effort`, `--config` | As for [`ssift ask`](cli.md) |

## What the page does

- **Chat.** Enter sends; Shift+Enter adds a line; the send button becomes Stop
  while a turn runs. Clicking a suggestion sends it.
- **Activity.** While the agent works, the turn shows what it is doing, one step
  per lookup ("Getting data from Weather", "Checking NPR, BBC News", "Drawing a
  map"). Each step expands to show its parameters and what came back. When the
  answer arrives the list folds into one line, such as "3 steps · 10s", that you
  can reopen.
- **Visuals.** Everything the model chose to [show](research.md#visuals) is
  grouped in one card above the answer: headline figures, maps, charts, and
  tables. Charts and maps are interactive Plotly figures: hover for values, drag
  to zoom a chart, click a legend entry to hide a series, drag and scroll a map.
  "View data" under each one lists the rows it was drawn from. The card names the
  source and the evidence the visuals came from. A visual shows the data as it
  was when retrieved; ask again for newer data.
- **Answer.** Below the card is a brief summary. When visuals are shown, the
  model is told not to repeat them as Markdown tables or lists.
- **Citations.** Each numbered chip opens the Evidence panel at that reference,
  with its publisher, kind, dates, and any limitations. The line under an answer
  ("2 sources · 1 note") expands to the same references and the answer's notes.
- **Sources.** Browse the catalog and choose which sources this chat may use.
- **Copy** puts the answer's text on the clipboard. **Save report** writes a
  Markdown [report](cli.md#reports) of that answer to your reports folder, with
  tables and figures written in and each chart and map saved beside it as a PNG
  image on a white background and linked from the report.
- **New chat.** Starts a conversation with every source enabled.

Reloading the page keeps the conversation while the server is running.

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
- The page loads no outside scripts, styles, or fonts; the chart library ships
  with SourceSift. The one exception is a map: your browser then loads map tiles
  from CARTO and, with the radar layer, radar images from RainViewer, so those
  services see your network address and the area viewed. Raw HTML and images in a
  model's answer are never rendered.
- Prompts, attached files, and retrieved text still go to the configured model
  through OpenRouter, as with `ssift ask`.

## Not yet in the page

Model and reasoning choices are set when starting the server, files are attached
with `--file` rather than uploaded, and radar is the latest frame only, shown at
regional zoom and wider, with no animation or forecast.
