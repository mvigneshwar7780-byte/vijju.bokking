"""Both browse directions, and the price comparison that justifies the schema.

A ticketing product has two entry points and they are not symmetric:

* **movie-first** -- "where can I watch this, and what will it cost?" That
  question only has an answer because price hangs off the show, not the film.
* **cinema-first** -- "what's on at my local hall?"

Both are served from the same `shows` table, which is what "related but not
tightly coupled" buys: no duplicated catalogue per cinema, no per-movie price to
keep in sync.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text

from app.core.db import SessionLocal

API = "/api/v1"


def _busiest_showing(cinema_min: int = 2) -> tuple[str, str, str]:
    """A (movie, city, date) combination playing at several cinemas."""
    with SessionLocal() as db:
        row = db.execute(
            text(
                """
                SELECT s.movie_id, s.city_id, s.show_date,
                       count(DISTINCT s.cinema_id) AS n
                  FROM shows s
                 WHERE s.status = 'open' AND s.sales_close_at > now()
                 GROUP BY 1, 2, 3
                HAVING count(DISTINCT s.cinema_id) >= :n
                 ORDER BY n DESC, s.show_date
                 LIMIT 1
                """
            ),
            {"n": cinema_min},
        ).first()
    assert row is not None, "seed should schedule a film at several cinemas"
    return str(row[0]), str(row[1]), str(row[2])


# ---------------------------------------------------------------- movie-first
def test_one_movie_lists_every_cinema_with_its_own_price(client) -> None:  # noqa: ANN001
    movie_id, city_id, show_date = _busiest_showing()
    resp = client.get(
        f"{API}/movies/{movie_id}/cinemas",
        params={"city_id": city_id, "date": show_date},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert len(body["cinemas"]) >= 2
    for cinema in body["cinemas"]:
        assert cinema["min_price_minor"] > 0
        assert cinema["show_count"] >= 1
        assert cinema["formats"]

    prices = [c["min_price_minor"] for c in body["cinemas"]]
    assert prices == sorted(prices), "cheapest hall should come first"
    assert len(set(prices)) > 1, (
        "the same film at different halls must be able to differ in price -- "
        "if these are all equal the pricing model is not being exercised"
    )
    assert body["cheapest_minor"] == min(prices)
    assert body["dearest_minor"] == max(c["max_price_minor"] for c in body["cinemas"])


def test_price_comparison_needs_a_city(client) -> None:  # noqa: ANN001
    """Comparing across the whole country is meaningless; city is required."""
    movie_id, _city, _date = _busiest_showing()
    assert client.get(f"{API}/movies/{movie_id}/cinemas").status_code == 422


# --------------------------------------------------------------- cinema-first
def test_a_cinema_lists_what_is_playing_with_its_own_prices(client) -> None:  # noqa: ANN001
    cinemas = client.get(f"{API}/cinemas").json()
    cinema_id = cinemas[0]["id"]

    resp = client.get(f"{API}/cinemas/{cinema_id}/movies")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["cinema_id"] == cinema_id
    assert body["movies"], "the seeded cinema should have something on"
    for movie in body["movies"]:
        assert movie["show_count"] >= 1
        assert movie["min_price_minor"] > 0
        assert movie["max_price_minor"] >= movie["min_price_minor"]
        assert movie["available_dates"]


def test_the_two_browse_directions_agree(client) -> None:  # noqa: ANN001
    """Cinema-first and movie-first must report the same price for the same show.

    They are computed by different queries; if they ever disagree, one of them
    is lying to the customer.
    """
    movie_id, city_id, show_date = _busiest_showing()
    comparison = client.get(
        f"{API}/movies/{movie_id}/cinemas",
        params={"city_id": city_id, "date": show_date},
    ).json()
    cinema = comparison["cinemas"][0]

    at_cinema = client.get(
        f"{API}/cinemas/{cinema['cinema_id']}/movies", params={"date": show_date}
    ).json()
    listed = next(
        (m for m in at_cinema["movies"] if m["movie_id"] == movie_id), None
    )
    assert listed is not None, "the film should appear in that cinema's listing"
    assert listed["min_price_minor"] == cinema["min_price_minor"]


def test_browsing_an_unknown_cinema_is_a_clean_404(client) -> None:  # noqa: ANN001
    resp = client.get(f"{API}/cinemas/{uuid.uuid4()}/movies")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_the_full_cinema_first_path_reaches_a_seat_map(client) -> None:  # noqa: ANN001
    """Cinema -> movie -> date -> showtime -> seats, as a customer walks it."""
    cinemas = client.get(f"{API}/cinemas").json()
    listing = next(
        (
            body
            for c in cinemas
            if (body := client.get(f"{API}/cinemas/{c['id']}/movies").json())["movies"]
        ),
        None,
    )
    assert listing is not None

    movie = listing["movies"][0]
    board = client.get(
        f"{API}/showtimes",
        params={
            "movie_id": movie["movie_id"],
            "city_id": client.get(f"{API}/cities").json()[0]["id"],
            "date": listing["show_date"],
        },
    ).json()
    show = next(
        s for c in board["cinemas"] for s in c["shows"] if s["is_bookable"]
    )
    seatmap = client.get(f"{API}/shows/{show['id']}/seatmap").json()
    assert seatmap["rows"]
    assert seatmap["categories"]
    # The seat price must fall inside the range the listing advertised.
    cheapest_seat = min(
        s["price_minor"] for r in seatmap["rows"] for s in r["seats"]
    )
    assert cheapest_seat >= movie["min_price_minor"], (
        "advertised 'from' price should not exceed the actual cheapest seat"
    )
