"""The help centre endpoint.

The contract that matters is that this page and the assistant read the *same*
knowledge base, so a customer cannot be told two different things. These tests
pin that, plus the anchor slugs the assistant's citations link to.
"""

from __future__ import annotations

from app.modules.help.content import DEFAULT_CORPUS, parse, slugify

API = "/api/v1"


def test_guest_can_read_the_help_centre(client) -> None:  # noqa: ANN001
    """No login: these are the questions asked before anyone has an account."""
    resp = client.get(f"{API}/help/sections")
    assert resp.status_code == 200, resp.text
    assert resp.json()["sections"], "help centre came back empty"


def test_sections_have_the_shape_the_page_renders(client) -> None:  # noqa: ANN001
    body = client.get(f"{API}/help/sections").json()
    assert set(body) == {"sections", "categories"}

    for section in body["sections"]:
        assert set(section) == {"category", "category_label", "title", "slug", "body"}
        assert section["title"] and section["slug"]
        assert isinstance(section["body"], list) and section["body"]


def test_film_listings_are_excluded(client) -> None:  # noqa: ANN001
    """The catalogue is the truth about what is showing.

    The corpus also carries "Now Showing"/"Upcoming" blurbs for the assistant to
    retrieve. Rendering those here would publish a frozen copy that goes stale
    the moment an operator schedules something.
    """
    body = client.get(f"{API}/help/sections").json()
    assert {s["category"] for s in body["sections"]} <= {"Policy", "FAQ", "Experience"}


def test_slugs_are_unique_and_stable(client) -> None:  # noqa: ANN001
    """Slugs are public anchors — a citation link breaks if they collide."""
    sections = client.get(f"{API}/help/sections").json()["sections"]
    slugs = [s["slug"] for s in sections]
    assert len(slugs) == len(set(slugs)), "duplicate slug would make a citation ambiguous"
    for section in sections:
        assert section["slug"] == slugify(section["title"])


def test_the_refund_policy_is_published(client) -> None:  # noqa: ANN001
    """The single most-asked topic, and the one the footer links to directly."""
    sections = client.get(f"{API}/help/sections").json()["sections"]
    assert any("refund" in s["title"].lower() for s in sections)


def test_both_knowledge_sources_ship_with_the_app() -> None:
    """Whatever each surface reads must be in the repo, not on one laptop.

    This originally asserted the help page and the assistant read the *same*
    file, so neither could drift. They have since been pointed at different
    documents on purpose -- the page at the operational corpus, the assistant
    at the legal terms -- so the invariant is now the weaker one: both files
    exist and are shipped.

    Worth knowing what the split costs: the operational topics (refund
    schedule, outside food, bag check, accessibility) live only in the corpus,
    so an assistant reading just the legal document cannot answer them.
    Ingesting both documents would restore that without undoing the split.
    """
    from app.db.seed.ingest_help import CORPUS as ASSISTANT_CORPUS

    assert DEFAULT_CORPUS.exists(), "the help centre corpus is not shipped"
    assert ASSISTANT_CORPUS.exists(), "the assistant's corpus is not shipped"


def test_a_section_without_a_body_is_dropped() -> None:
    """A bare heading would render as an empty card."""
    sections = parse("## Policy: Real\nSomething a reader can act on.\n## Policy: Empty\n")
    assert [s.title for s in sections] == ["Real"]


# ---------------------------------------------------------- terms document ---


def test_terms_preserve_their_numbering(client) -> None:  # noqa: ANN001
    """A legal document is navigated by its numbers, so they must survive."""
    body = client.get(f"{API}/help/terms").json()
    articles = body["articles"]

    assert len(articles) >= 5, "terms came back nearly empty"
    # Articles are numbered 1..N in document order.
    assert [a["number"] for a in articles] == [str(i + 1) for i in range(len(articles))]

    for article in articles:
        assert article["clauses"], f"article {article['number']} has no clauses"
        for clause in article["clauses"]:
            # "3.2" must sit under article "3".
            assert clause["number"].split(".")[0] == article["number"]
            assert clause["body"], f"clause {clause['number']} is empty"


def test_terms_slugs_are_unique(client) -> None:  # noqa: ANN001
    """Slugs are public anchors; a collision sends a link to the wrong clause."""
    articles = client.get(f"{API}/help/terms").json()["articles"]
    slugs = [a["slug"] for a in articles] + [
        c["slug"] for a in articles for c in a["clauses"]
    ]
    assert len(slugs) == len(set(slugs))


def test_template_placeholders_are_filled(client) -> None:  # noqa: ANN001
    """`[Website Name]` rendered to a customer reads as a broken page.

    Address and jurisdiction placeholders are deliberately left: inventing a
    registered office would be worse than visibly not having one.
    """
    articles = client.get(f"{API}/help/terms").json()["articles"]
    text = " ".join(line for a in articles for c in a["clauses"] for line in c["body"])

    assert "[Website Name]" not in text
    assert "yourdomain.com" not in text
    assert "vijju.booking" in text


def test_privacy_policy_is_published(client) -> None:  # noqa: ANN001
    """The footer links straight to it."""
    articles = client.get(f"{API}/help/terms").json()["articles"]
    assert any("privacy" in a["title"].lower() for a in articles)


def test_the_two_sources_stay_separate() -> None:
    """Operational help and the legal document are different files.

    Collapsing them into one would force a shape that renders neither well --
    and only the help-centre corpus is shared with the assistant.
    """
    from app.modules.help.content import DEFAULT_CORPUS
    from app.modules.help.legal import DEFAULT_LEGAL

    assert DEFAULT_CORPUS != DEFAULT_LEGAL
    assert DEFAULT_LEGAL.exists(), "the terms document is not shipped with the app"
