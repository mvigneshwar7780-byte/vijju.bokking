"""The help centre's content, parsed from the shared knowledge base.

**This is a display parser, not the RAG chunker.** The two read the same file and
deliberately process it differently:

* The retrieval pipeline splits the corpus into fixed-size overlapping windows,
  because that is what embeds and searches well.
* A reader wants a whole policy at once -- a refund schedule cut in half at 1000
  characters is useless on a page.

Sharing the *source* is the point: edit one file and both the help centre and
the assistant change together, so the page can never contradict the chatbot.
Sharing the *chunking* would serve neither well.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# app/modules/help/content.py -> app/
_APP_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS = _APP_ROOT / "db" / "seed" / "movie_booking_vector_embedding_corpus.txt"

_HEADING = re.compile(r"(?m)^##\s+(.+?)\s*$")

# The corpus also carries "Now Showing:" and "Upcoming:" film blurbs. Those are
# marketing copy that duplicates the live catalogue -- and the catalogue is the
# truth, so showing a frozen copy here would go stale the moment a film changes.
# Only the evergreen material belongs in a help centre.
_SHOWN = ("Policy", "FAQ", "Experience")

_CATEGORY_LABELS = {
    "Policy": "Policies",
    "FAQ": "Frequently asked",
    "Experience": "Formats and experiences",
}


def slugify(value: str) -> str:
    out = "".join(c.lower() if c.isalnum() else "-" for c in value)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")


@dataclass(frozen=True, slots=True)
class Section:
    category: str      # "Policy" | "FAQ" | "Experience"
    title: str         # heading with the prefix stripped
    slug: str          # stable anchor, also what a chatbot citation links to
    body: list[str]    # paragraphs and bullet lines, in order


def _split(document: str) -> list[tuple[str, str]]:
    """Heading/body pairs, in document order."""
    parts = _HEADING.split(document)
    # re.split with one group yields [pre, heading, body, heading, body, ...]
    return list(zip(parts[1::2], parts[2::2], strict=True))


def parse(document: str) -> list[Section]:
    sections: list[Section] = []

    for heading, body in _split(document):
        prefix, _, rest = heading.partition(":")
        prefix, title = prefix.strip(), rest.strip()
        if prefix not in _SHOWN or not title:
            continue

        lines = [line.strip() for line in body.strip().splitlines()]
        lines = [line for line in lines if line]
        if not lines:
            continue

        sections.append(
            Section(category=prefix, title=title, slug=slugify(title), body=lines)
        )

    return sections


@lru_cache(maxsize=4)
def load_sections(path: str | None = None) -> tuple[Section, ...]:
    """Read and parse the corpus.

    Cached: the file is small, immutable while the process runs, and this is on
    the request path. Returns a tuple so a caller cannot mutate the cached value.
    """
    source = Path(path) if path else DEFAULT_CORPUS
    if not source.exists():
        return ()
    return tuple(parse(source.read_text(encoding="utf-8")))


def category_label(category: str) -> str:
    return _CATEGORY_LABELS.get(category, category)
