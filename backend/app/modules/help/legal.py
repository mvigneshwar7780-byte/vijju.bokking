"""The terms and policies document, parsed from its numbered outline.

A separate parser from ``content.py`` because the two source files are shaped
differently and serve different readers:

* ``movie_booking_vector_embedding_corpus.txt`` uses ``##`` headings and holds
  the operational rules a customer looks up mid-booking -- refunds, bag check,
  outside food. It is also what the assistant retrieves from.
* ``movie_policies.txt`` is a formal legal document numbered ``1.``, ``1.1``,
  ``1.2`` -- Terms of Service, Privacy, DMCA, Arbitration. Nobody searches it;
  they navigate it, so it needs its hierarchy preserved rather than flattened.

Trying to serve both through one parser would mean a lowest-common-denominator
shape that renders neither well.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LEGAL = _APP_ROOT / "db" / "seed" / "movie_policies.txt"

_TOP = re.compile(r"^(\d+)\.\s+(.+?)\s*$")        # "3. Privacy Policy"
_SUB = re.compile(r"^(\d+\.\d+)\s+(.+?)\s*$")     # "3.2 Data We Collect"

# The source is a template. Rendering "[Website Name]" to a customer looks
# broken, so the known placeholders are substituted at parse time -- the file
# stays a reusable template, and the page shows this product's details.
_SUBSTITUTIONS = {
    "[Website Name / Company Legal Name]": "vijju.booking",
    "[Website Name]": "vijju.booking",
    "[Company Legal Name]": "vijju.booking",
    "[legal@yourdomain.com]": "legal@vijju.booking",
    "[privacy@yourdomain.com]": "privacy@vijju.booking",
    "[dmca@yourdomain.com]": "dmca@vijju.booking",
}

# Address and jurisdiction placeholders are left alone on purpose: inventing a
# registered office would be worse than visibly not having one.


def _fill(text: str) -> str:
    for placeholder, value in _SUBSTITUTIONS.items():
        text = text.replace(placeholder, value)
    return text


def slugify(value: str) -> str:
    out = "".join(c.lower() if c.isalnum() else "-" for c in value)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")


@dataclass(frozen=True, slots=True)
class Clause:
    number: str        # "1.2"
    title: str
    slug: str          # "1-2-account-security-identity-and-conduct"
    body: list[str]


@dataclass(frozen=True, slots=True)
class Article:
    number: str        # "1"
    title: str
    slug: str
    clauses: list[Clause]


def parse(document: str) -> list[Article]:
    articles: list[Article] = []
    current: dict | None = None
    clause: dict | None = None

    def close_clause() -> None:
        if current is not None and clause is not None and clause["body"]:
            current["clauses"].append(
                Clause(
                    number=clause["number"],
                    title=clause["title"],
                    slug=clause["slug"],
                    body=clause["body"],
                )
            )

    def close_article() -> None:
        close_clause()
        if current is not None and current["clauses"]:
            articles.append(
                Article(
                    number=current["number"],
                    title=current["title"],
                    slug=current["slug"],
                    clauses=current["clauses"],
                )
            )

    for raw in document.splitlines():
        line = _fill(raw.strip())
        if not line:
            continue

        # The two patterns are disjoint, so this order is for readability
        # rather than correctness: _TOP requires whitespace after the dot
        # (`^(\d+)\.\s+`), which "1.1 Foo" does not have. Verified by
        # swapping the blocks -- the parse is unchanged.
        if (m := _SUB.match(line)) is not None:
            close_clause()
            number, title = m.group(1), m.group(2)
            clause = {
                "number": number,
                "title": title,
                "slug": f"{number.replace('.', '-')}-{slugify(title)}",
                "body": [],
            }
            continue

        if (m := _TOP.match(line)) is not None:
            close_article()
            number, title = m.group(1), m.group(2)
            current = {
                "number": number,
                "title": title,
                "slug": f"{number}-{slugify(title)}",
                "clauses": [],
            }
            clause = None
            continue

        if clause is not None:
            clause["body"].append(line)

    close_article()
    return articles


@lru_cache(maxsize=4)
def load_articles(path: str | None = None) -> tuple[Article, ...]:
    source = Path(path) if path else DEFAULT_LEGAL
    if not source.exists():
        return ()
    return tuple(parse(source.read_text(encoding="utf-8")))
