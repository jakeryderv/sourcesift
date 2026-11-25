# Research and sources

Ask naturally: “check news,” “check tech and AI,” or “find developments relevant to
this project.” The model selects sources from their descriptions and your context.
There is no keyword router, category flag, or search engine.

## Built-in catalog

A plain “check news” means US national news (NPR and PBS). World news, science and
health, technology, and US policy and government each have their own sources below;
ask for them by topic or by publication. The catalog is a curated sample, not
comprehensive coverage, and can miss relevant reporting. Local news is not covered.

| ID | Publication | Coverage | Feed |
|---|---|---|---|
| `npr` | NPR | US national affairs and major world stories | [RSS](https://feeds.npr.org/1001/rss.xml) |
| `pbs` | PBS NewsHour | US public-interest news, politics, policy | [RSS](https://www.pbs.org/newshour/feeds/rss/headlines) |
| `ars-technica` | Ars Technica | Computing, science, security, AI | [RSS](https://feeds.arstechnica.com/arstechnica/index) |
| `techcrunch` | TechCrunch | Startups, technology businesses, commercial AI | [RSS](https://techcrunch.com/feed/) |
| `mit-technology-review` | MIT Technology Review | Emerging technology, AI research and impacts | [RSS](https://www.technologyreview.com/feed/) |
| `marketing-dive` | Marketing Dive | Advertising, brands, campaigns, marketing platforms | [RSS](https://www.marketingdive.com/feeds/news/) |
| `federal-reserve` | Federal Reserve | Primary US monetary-policy and banking announcements | [RSS](https://www.federalreserve.gov/feeds/press_all.xml) |
| `cnbc` | CNBC | Business, companies, markets, economics | [RSS](https://www.cnbc.com/id/100003114/device/rss/rss.html) |
| `bbc-news` | BBC News | World news from the UK public broadcaster | [RSS](https://feeds.bbci.co.uk/news/world/rss.xml) |
| `the-guardian` | The Guardian | International news and analysis | [RSS](https://www.theguardian.com/world/rss) |
| `dw` | Deutsche Welle | English-language international news from Germany's public broadcaster, strong on Europe, Africa, and Asia | [RSS](https://rss.dw.com/rdf/rss-en-all) |
| `al-jazeera` | Al Jazeera | International news with strong Middle East, Africa, and Global South coverage | [RSS](https://www.aljazeera.com/xml/rss/all.xml) (summaries only) |
| `sciencedaily` | ScienceDaily | Summaries of new research across science, health, environment, and technology, based on university and journal press releases rather than independent reporting | [RSS](https://www.sciencedaily.com/rss/all.xml) |
| `quanta-magazine` | Quanta Magazine | In-depth explanatory journalism on mathematics, physics, biology, and computer science research | [RSS](https://www.quantamagazine.org/feed/) |
| `nasa` | NASA | Official NASA news releases on missions, launches, space science, and agency announcements | [RSS](https://www.nasa.gov/news-release/feed/) |
| `stat-news` | STAT | Health, medicine, biotech, and pharmaceutical industry reporting | [RSS](https://www.statnews.com/feed/) |
| `kff-health-news` | KFF Health News | US health policy, insurance, public health, and healthcare costs from a nonprofit newsroom | [RSS](https://kffhealthnews.org/feed/) |
| `the-verge` | The Verge | Consumer technology, gadgets, platforms, and the technology industry, with product news and reviews | [RSS](https://www.theverge.com/rss/index.xml) |
| `wired` | WIRED | Technology and its effects on culture, business, security, and science, including longer features | [RSS](https://www.wired.com/feed/rss) |
| `github-blog` | GitHub Blog | Official GitHub posts on developer tools, product changes, open source, and software security | [RSS](https://github.blog/feed/) |
| `lwn` | LWN.net | Linux kernel, free software, and open-source community news for a technical audience | [RSS](https://lwn.net/headlines/rss) (summaries only) |
| `politico` | Politico | US politics, Congress, the White House, and campaigns | [RSS](https://rss.politico.com/politics-news.xml) (summaries only) |
| `the-hill` | The Hill | US congressional, administration, and campaign news with frequent short updates | [RSS](https://thehill.com/homenews/feed/) |
| `propublica` | ProPublica | Nonprofit investigative journalism on US government, business, justice, and public-interest accountability | [RSS](https://www.propublica.org/feeds/propublica/main) |
| `scotusblog` | SCOTUSblog | US Supreme Court cases, opinions, arguments, and analysis | [RSS](https://www.scotusblog.com/feed/) |
| `sec` | SEC | Official US Securities and Exchange Commission press releases on enforcement actions, rules, and agency announcements | [RSS](https://www.sec.gov/news/pressreleases.rss) |
| `gao` | GAO | US Government Accountability Office reports and testimony auditing federal programs and spending | [RSS](https://www.gao.gov/rss/reports.xml) |
| `justice-department` | US Department of Justice | Official US Department of Justice press releases on prosecutions, settlements, and enforcement | [RSS](https://www.justice.gov/news/rss?m=1) |

| `arxiv` | arXiv | New AI, machine learning, and computational linguistics preprints with abstracts | [RSS](https://rss.arxiv.org/rss/cs.AI+cs.LG+cs.CL) |

Sources marked “summaries only” refuse automated article retrieval (through
robots rules or by blocking the request), so answers can cite their feed summaries
but `read_article` cannot fetch the full text.

Feeds are public recent-entry sources, not historical archives. A reachable feed
does not imply that every linked article is accessible; subscriptions, robots
restrictions, JavaScript, and extraction failures can limit article access.
Custom source definitions use the same adapters; see [configuration](configuration.md)
and [SDK registration](sdk.md#source-definitions).

## Live data sources

Some sources answer with current data instead of offering a feed. The model
reaches them through the `query_source` tool with typed parameters, and their
records are cited like any other evidence, with the kind `api record`.

| ID | Parameters | Evidence | Tables for figures |
|---|---|---|---|
| `hacker-news` | `query`: keywords, or empty for the current front page | Story titles, points, comment counts, and submitted links; keyword results are limited to the date window | The stories with points, comments, and submitter |
| `weather` | `place`: a city or town, optionally with a region or country; `days` of forecast (1 to 7, default 3); `units`: `metric` or `imperial` | Current conditions and the daily forecast for the place it resolved, with local observation time | Current conditions, the location, hourly temperature, and the daily forecast |
| `us-treasury` | `dataset`: `debt`, `interest-rates`, or `exchange-rates`; `days` of history for `debt` (7 to 3650, default 30) | The latest published figures with their record date; for `debt`, also the range of the history retrieved | `debt`: the three debt figures by day. Others: name and value |
| `bls` | `series`: `unemployment-rate`, `labor-force-participation`, `nonfarm-payrolls`, `average-hourly-earnings`, `consumer-prices`, or `core-consumer-prices`; `years` of history (1 to 9, default 5) | The latest monthly value and the past year of values, with preliminary figures marked | The series by month; earnings and price series add the 12-month percent change |

Each is defined in Python with a parameter model. Parameters are validated before
any request is made; invalid ones are returned to the model to correct. A source
requests only its own documented endpoints, so the model cannot choose a host or
path. Requests use the same bounded HTTP adapter as feeds, so address checks,
robots rules, byte limits, and the request budget all apply. Weather comes from [Open-Meteo](https://open-meteo.com/)
forecast models (CC BY 4.0, free for non-commercial use); it is not an official
warning or alert service. Hacker News points and comments measure attention, not
accuracy. A Treasury record date is a
reporting period rather than a publication time, so those records are not
filtered by the date window; the same holds for a Bureau of Labor Statistics
reference month. BLS figures come from its public API without a key, which
allows about 25 requests a day from one address. The 12-month change in a BLS
price or earnings series is computed by SourceSift from the values retrieved.

### Robots rules and public APIs

A `robots.txt` file tells crawlers which pages not to collect. Some public data
APIs disallow all crawlers on their API host while documenting that host for
programs to call. A data source can therefore declare the API hosts it calls, and
requests to exactly those hosts skip the robots check. The weather source
does (`api.open-meteo.com` and `geocoding-api.open-meteo.com`), and so does the
Bureau of Labor Statistics source (`api.bls.gov`). Feeds, articles,
discovery, and every other host are still checked, and address checks, size
limits, timeouts, and the request budget apply to every request.

## Figures

A live data source can return its data as tables alongside the text the model
reads. The model is told each table's columns and may call the `make_figure`
tool to draw a chart from one of them, naming the columns to use:

| Option | Meaning |
|---|---|
| `kind` | `line`, `area`, `bar`, `stacked_bar`, `scatter`, or `donut` |
| `x` | The column across the chart: a time or number column, or categories for bars and donuts |
| `y` | One to eight numeric columns |
| `series` | A column whose values split one `y` column into separate series |
| `log_scale`, `title` | A logarithmic value axis; the chart's title |
| `period`, `combine` | One point per `day`, `week`, `month`, `quarter`, or `year`, taking the `last` or `first` recorded value or the `mean`, `sum`, `min`, or `max` |
| `since`, `top` | Start at an ISO date; keep only the N largest rows |

The tool returns an ID such as `F1`. The model places the figure in its answer
or in an artifact with an ordinary Markdown image whose target is that ID:
`![US public debt in 2026](F1)`.

- The picture is drawn in Python with Matplotlib, as a PNG on a white
  background. It needs no browser or network, so it is the same in the web app,
  in a saved artifact, and from the SDK.
- The model chooses the kind and the columns. It cannot pass values: the
  application draws the figure from the rows the source returned, so a number on
  the chart always comes from retrieved data.
- A recipe that does not fit the table (a column that does not exist or is not
  numeric, more than 60 bars, more than 8 series) is refused with the reason,
  which the model can correct.
- A figure is a snapshot of the data when it was retrieved, and it counts as a
  citation of that evidence. To update it, ask again.
- A figure the model made but did not place is added to the end of the answer.
- `limits.max_figures` (default 4) bounds new figures per turn; a conversation
  holds at most 48.
- In a conversation, a follow-up can draw data retrieved in an earlier turn
  without another request while the conversation is open. A saved conversation
  keeps its figures, with the rows each was drawn from, but not the other tables.
- Tables, headline numbers, and lists are written by the model as Markdown.
  The `read_table` tool gives it rows of a retrieved table to quote, at most 60
  at a time, with the same `period`, `combine`, `since`, and `top` options to
  summarize a long table first. The model sees only the rows it reads this way
  and the evidence text. There are no maps.
- Summarizing never invents a value: a `last` or `first` point is one recorded
  row with its own date, and the other choices are computed by the application
  from the retrieved rows.
- Each request in a conversation lists the tables still held, so a follow-up
  charts or reads them instead of querying the source again.

Figures are returned as `Result.figures` and in `--json` output: the recipe and
the rows, not the picture. `sourcesift.render_png(figure)` draws one.

## Artifacts

An artifact is a document the model writes for keeping: a report, a briefing, a
comparison. In `ssift web` and SDK sessions the model has a `write_artifact`
tool taking a title and Markdown; `ssift ask --artifact` enables it for one
request. Passing an existing artifact's ID revises it and raises its version.

The model has no tool that writes a file or runs code. The application checks
the text and writes the files itself. An artifact is refused, with the reason
returned to the model, when it:

- cites an evidence ID that does not exist, or contains an image that is not a
  figure made in this conversation;
- contains a Quarto code cell (```` ```{python} ````), inline code that runs,
  a shortcode (`{{< include … >}}`), or a raw HTML or LaTeX block;
- starts with a YAML header, or is longer than `limits.max_artifact_chars`
  (default 40,000).

A conversation holds up to 12 artifacts. Each carries the notes (coverage,
freshness, retrieval gaps) of the turn that wrote it.

### Artifact files

A saved artifact is a small folder that [Quarto](https://quarto.org) can render:

```text
A1-us-public-debt-in-2026.qmd   the document
references.json                 the cited references (CSL JSON)
figures/F1.png                  each placed figure
figures/F1.json                 its recipe and the rows it was drawn from
```

In the `.qmd` file each `[S1]` is written as the Quarto citation `[@S1]`, so
Quarto formats the reference list from `references.json` and links each
citation to it. A figure points at its picture in `figures/`. The notes become a
"Notes" section.

Rendering the file runs no code and reads no other file. The header sets
`execute: enabled: false` and turns off raw HTML and LaTeX, and the checks above
keep cells and includes out of the text, so an export contains only what the
artifact shows. Text retrieved from the web still appears in the references, as
titles and publisher names.

Quarto is optional. Without it the `.qmd` file reads as Markdown. With it,
`quarto render <file> --to html`, `typst` (PDF), `docx`, or `revealjs` (slides)
produces a finished document, and the web app offers the same exports as
buttons.

arXiv's search API also disallows all automated agents in `robots.txt`. It has
not been given the exemption above, so arXiv is read through its RSS feed without
search.

## Selection and retrieval

The `research` tool receives the agent's chosen sources, direct URLs, named-only
constraints, and window. Follow-up calls may add sources within the same window
and constraints. `read_article` can fetch a link from retained evidence or the
original task. URLs embedded only in background documents do not authorize retrieval.

A request such as “use only NPR” should select NPR or explain why it is unavailable.
The model interprets the restriction; Python enforces the declared named-only list
once supplied. Unknown or disabled named sources never silently fall back to others.
This is a semantic constraint, not a domain sandbox: a feed can link or redirect
to another publisher, whose actual hostname is preserved in the reference. Direct
URLs combined with named-only restrictions must use the registered feed path.

HTTP retrieves only public HTTP(S) addresses on standard ports. Each destination,
including redirects, resolves to public IP addresses and is pinned for the connection
while retaining the original Host and TLS server name. Private, loopback, link-local,
reserved, and multicast destinations are rejected. Retrieval uses no environment
proxies, authentication, or retained cookies. Publisher robots rules are checked;
missing robots files (404/410) permit access, while unavailable rules fail closed.
Requests are sequential and bounded; there is no general crawl or paywall bypass.

RSS and Atom summaries are parsed with feedparser. If a source has no explicit
feed URL, declared RSS/Atom links are discovered from its website. HTML article
text is extracted with Trafilatura from bytes already fetched by the bounded HTTP
adapter. PDF, browser rendering, and arbitrary website search are unsupported.

## Dates and evidence

The run captures a UTC clock. `sources.timezone` defaults to UTC and controls local
calendar boundaries; it is never inferred from the machine's locale.

- **Recent:** the preceding `recent_days` (default seven rolling days).
- **Today:** local midnight through the run's start.
- **This week:** Monday at local midnight through the run's start, including DST.
- **Any:** no lower date bound, normally used for a direct article summary.

Known publication dates determine freshness. An update date is used only when
publication is unknown, and is labeled as such. Missing or zone-less dates remain
unknown; those items may be shown with an explicit unverified-freshness warning.
Future and out-of-window dated entries are excluded. Retrieval time never proves
publication time. Explicit article dates take precedence over feed dates; missing
article dates can retain the feed's date. Arbitrary historical ranges are unsupported.

URLs are normalized by removing fragments and common tracking parameters. Identical
normalized URLs or identical normalized title/text pairs are deduplicated within
the run. This does not detect all syndicated stories or different reports about
the same event. Retained evidence and text are capped; feed entries are considered
newest dated first, so older or undated relevant items can be omitted by the cap.

Each citation such as `[S1]` maps to a typed reference with the title, final article
URL, requested retrieval URL, actual feed/page fetched, publisher hostname, source
ID, available author/dates, retrieval timestamp, and limitations. A `feed_summary`
reference means the feed supplied the text; it does not claim the article was
fetched. Article follow-ups replace that evidence while preserving its citation ID
unless it merges with an already known final URL.

The runtime rejects invented citation IDs and asks once for missing citations when
retrieved evidence exists. If retrieval yields no usable evidence, it returns an
explicit inability to verify information. Citation existence is checked in Python;
claim-level support, relevance, and honest geographic scope still depend on the
model and require evaluation. Untrusted documents and tool text are explicitly
separated from instructions, but prompt instructions alone are not a guarantee
against every prompt-injection attack.

## Validation and live evaluation

Normal CI uses deterministic model calls and authored fixtures: RSS/Atom, discovery,
article extraction, date windows/DST, duplicates, redirects, HTTP limits, partial
failures, named-only restrictions, and citation repair. Live models are disabled.
Hypothesis additionally checks URL-normalization idempotence.

Run the fixed eight-case evaluation explicitly from a checkout:

```sh
export SOURCESIFT_MODEL=openai/gpt-6.1-sol
export SOURCESIFT_REASONING_EFFORT=medium
uv run --locked python scripts/research_eval.py
# Or one case:
uv run --locked python scripts/research_eval.py --case named-only
```

Set `OPENROUTER_API_KEY` securely first. To deliberately load a local ignored `.env`,
use `uv run --env-file .env ...`; the application never loads it automatically.
This evaluation incurs model usage and contacts public publishers. Two cases use
a live model with synthetic unavailable/date/duplicate source fixtures. No other
case substitutes publisher content. Default output is ignored `evaluation-results/`.

Records include the exact request/context, model/effort, selected sources, window,
answer, references, evidence, elapsed time, and reported usage. Automatic selection
and evidence-presence checks are smoke checks; fill in the separate human-review
fields after checking relevance, each citation's support, and freshness disclosures.
Keep these records private if prompts/context are private. They are not persisted
by normal application requests.

The Phase 2 acceptance baseline (2026-10-15 UTC / October 14 US Central) used
`openai/gpt-6.1-sol` at medium effort. All eight source-selection/evidence-presence
checks passed, taking 4.27–16.54 seconds and two or three model requests per case.
Codex reviewed the 12 cited references against captured evidence; the observed
claims were supported, missing dates/access were disclosed, and the named-only
cases did not substitute other publications. A separate actual CLI check fetched
and summarized a direct article URL with clean plain-text output.

The committed `evaluations/baseline.json` records prompts, settings, source sets,
windows, usage, timings, and review notes without reproducing publisher articles.
This is a small agent-reviewed acceptance baseline, not an independent human
assessment or a measured general accuracy rate. Before expanding the catalog,
require these eight checks to stay green, zero unknown citation IDs, explicit
unknown-date handling, and review every cited claim in the fixed cases. Add labeled
cases for the new coverage before setting broader relevance targets.
