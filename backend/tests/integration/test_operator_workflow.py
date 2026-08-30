"""A cinema owner sets up a hall from nothing and sells a ticket.

This is the acceptance test for the operator role: register, define the venue,
lay out the seats, add a film, schedule a show with its own prices, watch a
customer book it, then read the money back out. It finishes by cancelling a
show and checking that everybody affected is refunded.

It also demonstrates the pricing requirement directly: two operators schedule
the *same* film and charge different amounts, because price belongs to
cinema -> screen -> show -> seat category, never to the movie.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy import text

from app.core.db import SessionLocal

API = "/api/v1"


def _register(client, role: str | None = None) -> dict:  # noqa: ANN001
    email = f"op_{uuid.uuid4().hex[:8]}@example.com"
    body = client.post(
        f"{API}/auth/register",
        json={"email": email, "password": "hunter2pass", "full_name": "Owner"},
    ).json()
    if role:
        with SessionLocal() as db:
            db.execute(
                text("UPDATE users SET role = :r WHERE id = CAST(:i AS uuid)"),
                {"r": role, "i": body["user"]["id"]},
            )
            db.commit()
    return {
        "email": email,
        "auth": {"Authorization": f"Bearer {body['tokens']['access_token']}"},
    }


def _build_cinema(client, operator, *, hall_name: str, prices: dict[str, int]) -> dict:  # noqa: ANN001
    """Venue -> tiers -> screen -> layout. Returns the ids."""
    city_id = client.get(f"{API}/cities").json()[0]["id"]

    cinema = client.post(
        f"{API}/operator/cinemas",
        json={
            "city_id": city_id,
            "name": hall_name,
            "brand": "Indie",
            "address_line": "12 Example Street",
            "locality": "Central",
            "timezone": "Asia/Kolkata",
            "amenities": ["Parking", "F&B"],
        },
        headers=operator["auth"],
    )
    assert cinema.status_code == 201, cinema.text
    cinema_id = cinema.json()["id"]

    categories = {}
    for order, (code, name, minor) in enumerate(
        [("STD", "Standard", prices["STD"]), ("PREM", "Premium", prices["PREM"])]
    ):
        resp = client.post(
            f"{API}/operator/cinemas/{cinema_id}/seat-categories",
            json={
                "code": code,
                "name": name,
                "default_price_minor": minor,
                "display_order": order,
            },
            headers=operator["auth"],
        )
        assert resp.status_code == 201, resp.text
        categories[code] = resp.json()["id"]

    screen = client.post(
        f"{API}/operator/cinemas/{cinema_id}/screens",
        json={
            "name": "Audi 1",
            "screen_number": 1,
            "supported_formats": ["2D", "IMAX"],
            "sound_system": "Dolby Atmos",
        },
        headers=operator["auth"],
    )
    assert screen.status_code == 201, screen.text
    screen_id = screen.json()["id"]

    layout = client.put(
        f"{API}/operator/screens/{screen_id}/layout",
        json={
            "rows": [
                {"row_label": "A", "seat_count": 8, "category_code": "STD",
                 "aisles_after": [4], "wheelchair_seats": [1]},
                {"row_label": "B", "seat_count": 8, "category_code": "STD",
                 "aisles_after": [4]},
                {"row_label": "C", "seat_count": 6, "category_code": "PREM"},
            ],
            "screen_label": "All eyes this way",
        },
        headers=operator["auth"],
    )
    assert layout.status_code == 200, layout.text
    assert layout.json()["total_seats"] == 22
    assert layout.json()["by_category"] == {"Standard": 16, "Premium": 6}

    return {"cinema_id": cinema_id, "screen_id": screen_id, "categories": categories}


def test_owner_sets_up_a_hall_and_sells_a_ticket(client) -> None:  # noqa: ANN001
    owner = _register(client, "cinema_operator")
    venue = _build_cinema(
        client, owner, hall_name=f"Indie Hall {uuid.uuid4().hex[:6]}",
        prices={"STD": 20000, "PREM": 35000},
    )

    # --- a film, added to the shared catalogue ---------------------------
    movie = client.post(
        f"{API}/operator/movies",
        json={
            "title": f"The Operator's Cut {uuid.uuid4().hex[:6]}",
            "synopsis": "A projectionist discovers the reels rearrange themselves.",
            "runtime_minutes": 105,
            "certification": "UA13+",
            "status": "now_showing",
            "language_codes": ["en", "hi"],
            "genre_names": ["Drama", "Mystery"],
            "cast": ["Asha Rao", "Vikram Nair"],
            "director": "Leela Menon",
            "poster_url": "https://placehold.co/400x600",
        },
        headers=owner["auth"],
    )
    assert movie.status_code == 201, movie.text
    movie_id = movie.json()["id"]
    assert {g["name"] for g in movie.json()["genres"]} == {"Drama", "Mystery"}

    # --- a showtime, priced per seat tier --------------------------------
    show_date = date.today() + timedelta(days=2)
    show = client.post(
        f"{API}/operator/cinemas/{venue['cinema_id']}/shows",
        json={
            "screen_id": venue["screen_id"],
            "movie_id": movie_id,
            "format_code": "IMAX",
            "audio_language_code": "en",
            "show_date": str(show_date),
            "start_time": "19:15:00",
            "prices": [
                {"seat_category_id": venue["categories"]["STD"], "price_minor": 24000},
                {"seat_category_id": venue["categories"]["PREM"], "price_minor": 42000},
            ],
        },
        headers=owner["auth"],
    )
    assert show.status_code == 201, show.text
    show_body = show.json()
    show_id = show_body["id"]
    assert show_body["total_seats"] == 22
    assert show_body["occupancy_percent"] == 0.0

    # --- a customer books it ---------------------------------------------
    customer_email = f"cust_{uuid.uuid4().hex[:8]}@example.com"
    cust = client.post(
        f"{API}/auth/register",
        json={"email": customer_email, "password": "hunter2pass", "full_name": "Cust"},
    ).json()
    cust_auth = {"Authorization": f"Bearer {cust['tokens']['access_token']}"}
    session_key = uuid.uuid4().hex

    seatmap = client.get(f"{API}/shows/{show_id}/seatmap").json()
    # The IMAX surcharge is added on top of the operator's tier price.
    premium = next(
        s for r in seatmap["rows"] for s in r["seats"] if s["category_code"] == "PREM"
    )
    assert premium["price_minor"] == 42000 + 15000, "format surcharge should apply"

    seat_ids = [
        s["seat_id"]
        for r in seatmap["rows"]
        for s in r["seats"]
        if s["category_code"] == "STD" and s["status"] == "available"
    ][:2]
    hold = client.post(
        f"{API}/holds",
        json={"show_id": show_id, "seat_ids": seat_ids, "session_key": session_key},
        headers=cust_auth,
    )
    assert hold.status_code == 201, hold.text
    booking = client.post(
        f"{API}/bookings",
        json={
            "hold_id": hold.json()["hold_id"],
            "session_key": session_key,
            "contact_email": customer_email,
        },
        headers=cust_auth,
    ).json()
    payment = client.post(
        f"{API}/bookings/{booking['id']}/pay", json={"method": "upi"}, headers=cust_auth
    ).json()
    settled = client.post(
        f"{API}/payments/mock/{payment['gateway_order_id']}/complete",
        params={"outcome": "success"},
    ).json()
    assert settled["status"] == "confirmed"

    # --- the owner sees it -----------------------------------------------
    bookings = client.get(
        f"{API}/operator/cinemas/{venue['cinema_id']}/bookings", headers=owner["auth"]
    ).json()
    assert bookings["total"] == 1
    row = bookings["items"][0]
    assert row["booking_reference"] == booking["booking_reference"]
    assert row["seat_count"] == 2
    assert len(row["seat_labels"]) == 2

    shows = client.get(
        f"{API}/operator/cinemas/{venue['cinema_id']}/shows",
        params={"date_from": str(show_date), "date_to": str(show_date)},
        headers=owner["auth"],
    ).json()
    assert shows[0]["booked_seats"] == 2
    assert shows[0]["occupancy_percent"] == round(100 * 2 / 22, 1)

    occupancy = client.get(
        f"{API}/operator/cinemas/{venue['cinema_id']}/reports/occupancy",
        params={"date_from": str(show_date), "date_to": str(show_date)},
        headers=owner["auth"],
    ).json()
    assert occupancy["booked_seats"] == 2
    assert occupancy["total_seats"] == 22

    revenue = client.get(
        f"{API}/operator/cinemas/{venue['cinema_id']}/reports/revenue",
        params={"date_from": str(show_date), "date_to": str(show_date)},
        headers=owner["auth"],
    ).json()
    assert revenue["totals"]["bookings"] == 1
    assert revenue["totals"]["tickets"] == 2
    assert revenue["totals"]["gross_minor"] == booking["total_minor"]
    assert revenue["totals"]["refunded_minor"] == 0

    # --- cancelling the show refunds everyone ----------------------------
    cancelled = client.post(
        f"{API}/operator/shows/{show_id}/cancel",
        json={"reason": "Projector failure"},
        headers=owner["auth"],
    )
    assert cancelled.status_code == 200, cancelled.text
    result = cancelled.json()
    assert result["bookings_revoked"] == 1
    assert result["refunds_created"] == 1
    # A cancellation is the operator's fault, so the fee comes back too.
    assert result["refund_total_minor"] == booking["total_minor"]

    after = client.get(f"{API}/bookings/{booking['id']}", headers=cust_auth).json()
    assert after["status"] == "revoked"


def test_the_same_film_costs_different_amounts_at_different_halls(client) -> None:  # noqa: ANN001
    """The architecture requirement, demonstrated end to end.

    Price is a property of cinema -> screen -> show -> seat category. Two
    independent operators schedule one shared catalogue entry and charge what
    they like, with no coordination and no per-movie price anywhere.
    """
    cheap_owner = _register(client, "cinema_operator")
    plush_owner = _register(client, "cinema_operator")

    cheap = _build_cinema(
        client, cheap_owner, hall_name=f"Budget Screens {uuid.uuid4().hex[:6]}",
        prices={"STD": 12000, "PREM": 18000},
    )
    plush = _build_cinema(
        client, plush_owner, hall_name=f"Luxe Cinema {uuid.uuid4().hex[:6]}",
        prices={"STD": 30000, "PREM": 55000},
    )

    # One shared title.
    movie_id = client.post(
        f"{API}/operator/movies",
        json={"title": f"Shared Title {uuid.uuid4().hex[:6]}", "runtime_minutes": 120,
              "status": "now_showing"},
        headers=cheap_owner["auth"],
    ).json()["id"]

    show_date = date.today() + timedelta(days=3)
    prices_seen = {}
    for label, venue, owner, std_price in (
        ("cheap", cheap, cheap_owner, 15000),
        ("plush", plush, plush_owner, 38000),
    ):
        resp = client.post(
            f"{API}/operator/cinemas/{venue['cinema_id']}/shows",
            json={
                "screen_id": venue["screen_id"],
                "movie_id": movie_id,
                "format_code": "2D",
                "show_date": str(show_date),
                "start_time": "17:00:00",
                "prices": [
                    {"seat_category_id": venue["categories"]["STD"],
                     "price_minor": std_price},
                    {"seat_category_id": venue["categories"]["PREM"],
                     "price_minor": std_price * 2},
                ],
            },
            headers=owner["auth"],
        )
        assert resp.status_code == 201, resp.text
        seatmap = client.get(f"{API}/shows/{resp.json()['id']}/seatmap").json()
        std = next(
            s for r in seatmap["rows"] for s in r["seats"] if s["category_code"] == "STD"
        )
        prices_seen[label] = std["price_minor"]

    assert prices_seen["cheap"] == 15000
    assert prices_seen["plush"] == 38000
    assert prices_seen["cheap"] != prices_seen["plush"], (
        "the same film must be priceable differently per hall"
    )


def test_an_overlapping_show_is_a_clear_conflict_not_a_500(client) -> None:  # noqa: ANN001
    """The auditorium is already busy — say so, do not crash.

    The EXCLUDE constraint catches the overlap in the database, but the message
    naming the screen is built from an ORM instance that the failed flush has
    expired. Reading it afterwards reloads on a poisoned session and raises
    PendingRollbackError, which surfaced as a 500 and buried the real reason.
    """
    owner = _register(client, "cinema_operator")
    venue = _build_cinema(
        client, owner, hall_name=f"Overlap Hall {uuid.uuid4().hex[:6]}",
        prices={"STD": 20000, "PREM": 30000},
    )
    movie = client.post(
        f"{API}/operator/movies",
        json={"title": f"Long Film {uuid.uuid4().hex[:6]}", "runtime_minutes": 150,
              "status": "now_showing"},
        headers=owner["auth"],
    ).json()

    show_date = date.today() + timedelta(days=4)
    prices = [
        {"seat_category_id": venue["categories"]["STD"], "price_minor": 20000},
        {"seat_category_id": venue["categories"]["PREM"], "price_minor": 30000},
    ]
    body = {
        "screen_id": venue["screen_id"],
        "movie_id": movie["id"],
        "show_date": str(show_date),
        "start_time": "18:00:00",
        "prices": prices,
    }
    first = client.post(
        f"{API}/operator/cinemas/{venue['cinema_id']}/shows",
        json=body, headers=owner["auth"],
    )
    assert first.status_code == 201, first.text

    # 150 minutes plus turnaround runs past 20:30, so this clashes.
    clash = client.post(
        f"{API}/operator/cinemas/{venue['cinema_id']}/shows",
        json={**body, "start_time": "20:00:00"}, headers=owner["auth"],
    )
    assert clash.status_code == 409, f"expected a conflict, got {clash.status_code}: {clash.text}"
    error = clash.json()["error"]
    assert error["code"] == "SHOW_OVERLAP"
    assert "Audi 1" in error["message"], error["message"]

    # The session must still be usable -- a later, non-clashing show works.
    later = client.post(
        f"{API}/operator/cinemas/{venue['cinema_id']}/shows",
        json={**body, "start_time": "23:30:00"}, headers=owner["auth"],
    )
    assert later.status_code == 201, later.text


def test_scheduling_a_title_from_the_shared_catalogue(client) -> None:  # noqa: ANN001
    """An operator must be able to show a film someone else added.

    The show form used to list only titles that operator had personally
    created, so a new operator saw an empty control with nothing to pick and no
    way to add anything -- while the catalogue already held films they could
    have scheduled immediately.
    """
    owner = _register(client, "cinema_operator")
    venue = _build_cinema(
        client, owner, hall_name=f"Catalogue Hall {uuid.uuid4().hex[:6]}",
        prices={"STD": 15000, "PREM": 25000},
    )

    # This operator has contributed nothing...
    own = client.get(f"{API}/operator/movies", headers=owner["auth"]).json()
    assert own["total"] == 0

    # ...but the shared catalogue is not empty, and is searchable.
    catalogue = client.get(f"{API}/movies", params={"status": "now_showing"}).json()
    assert catalogue["total"] > 0, "the seeded catalogue should have films"
    existing = catalogue["items"][0]

    scheduled = client.post(
        f"{API}/operator/cinemas/{venue['cinema_id']}/shows",
        json={
            "screen_id": venue["screen_id"],
            "movie_id": existing["id"],
            "show_date": str(date.today() + timedelta(days=5)),
            "start_time": "14:00:00",
            "prices": [
                {"seat_category_id": venue["categories"]["STD"], "price_minor": 16000},
                {"seat_category_id": venue["categories"]["PREM"], "price_minor": 26000},
            ],
        },
        headers=owner["auth"],
    )
    assert scheduled.status_code == 201, scheduled.text
    assert scheduled.json()["movie_title"] == existing["title"]
