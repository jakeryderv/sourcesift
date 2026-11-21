"""Built-in data sources and widgets, defined the way an extension would be."""

from sourcesift.builtin.hacker_news import hacker_news
from sourcesift.builtin.treasury import us_treasury
from sourcesift.builtin.weather import weather
from sourcesift.builtin.widgets import chart, place_map, stats, table
from sourcesift.extend import Toolkit
from sourcesift.sources import BUILTIN_SOURCES

DATA_SOURCES = (hacker_news, us_treasury, weather)
WIDGETS = (chart, table, stats, place_map)
# Every built-in catalog entry: feed sources, then live data sources.
BUILTIN_CATALOG = (*BUILTIN_SOURCES, *(item.source for item in DATA_SOURCES))


def builtin_toolkit() -> Toolkit:
    return Toolkit(DATA_SOURCES, WIDGETS)
