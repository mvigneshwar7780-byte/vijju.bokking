"""Selecting seats must not tie them up because someone wandered off.

The reported bug: pick seats, go back, and they are unbookable for eight
minutes -- including by the person who just picked them. That is what happens
when selection creates a long hold and nothing releases it.

The fix has three parts, and each is tested here:

* selection takes a **short** hold, long enough to reach payment;
* leaving checkout **releases** it;
* a customer who wants longer asks for it, and that request survives navigation.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.core.db import SessionLocal

API = "/api/v1"


@pytest.fixture
def picker(client, pick_show, cleanup_bookings):  # noqa: ANN001
    """Pick n available seats on a fresh show."""

    def _pick(n: int = 2) -> dict:
        show = pick_show(client)
        cleanup_bookings.append(show["id"])
        seatmap = client.get(f"{API}/shows/{show['id']}/seatmap").json()
        row = next(
            r for r in seatmap["rows"]
            if sum(s["status"] == "available" for s in r["seats"]) >= n + 2
        )
        seats = [s for s in row["seats"] if s["status"] == "available"][:n]
        return {
            "show_id": show["id"],
            "seat_ids": [s["seat_id"] for s in seats],
            "labels": [s["label"] for s in seats],
            "session_key": uuid.uuid4().hex,
            "available_before": seatmap["available_seats"],
        }

    return _pick


def _status_of(show_id: str, seat_id: str) -> str:
    with SessionLocal() as db:
        return db.execute(
            text(
                """
                SELECT CASE WHEN status = 'held' AND hold_expires_at <= now()
                            THEN 'available' ELSE status::text END
                  FROM show_seats
                 WHERE show_id = CAST(:s AS uuid) AND seat_id = CAST(:t AS uuid)
                """
            ),
            {"s": show_id, "t": seat_id},
        ).scalar_one()


# ------------------------------------------------------------------ selection
def test_selecting_seats_takes_only_a_short_hold(client, picker) -> None:  # noqa: ANN001
    """A selection must not tie seats up for the full window."""
    p = picker()
    hold = client.post(
        f"{API}/holds",
        json={"show_id": p["show_id"], "seat_ids": p["seat_ids"],
              "session_key": p["session_key"]},
    )
    assert hold.status_code == 201, hold.text
    body = hold.json()

    assert body["seconds_remaining"] <= settings.seat_selection_ttl_seconds
    assert body["seconds_remaining"] < settings.seat_hold_ttl_seconds, (
        "selection should be shorter than the opt-in hold"
    )
    assert body["is_kept"] is False


def test_leaving_checkout_puts_the_seats_straight_back(client, picker) -> None:  # noqa: ANN001
    """The reported bug: go back, seats stay blocked. They must not."""
    p = picker()
    hold = client.post(
        f"{API}/holds",
        json={"show_id": p["show_id"], "seat_ids": p["seat_ids"],
              "session_key": p["session_key"]},
    ).json()
    assert _status_of(p["show_id"], p["seat_ids"][0]) == "held"

    released = client.request(
        "DELETE",
        f"{API}/holds/{hold['hold_id']}",
        json={"session_key": p["session_key"], "reason": "abandoned"},
    )
    assert released.status_code == 200, released.text

    assert _status_of(p["show_id"], p["seat_ids"][0]) == "available"
    seatmap = client.get(f"{API}/shows/{p['show_id']}/seatmap").json()
    assert seatmap["available_seats"] == p["available_before"]


def test_the_same_person_can_reselect_after_going_back(client, picker) -> None:  # noqa: ANN001
    """Re-picking the seats you just abandoned must simply work."""
    p = picker()
    first = client.post(
        f"{API}/holds",
        json={"show_id": p["show_id"], "seat_ids": p["seat_ids"],
              "session_key": p["session_key"]},
    ).json()
    client.request(
        "DELETE",
        f"{API}/holds/{first['hold_id']}",
        json={"session_key": p["session_key"], "reason": "abandoned"},
    )

    again = client.post(
        f"{API}/holds",
        json={"show_id": p["show_id"], "seat_ids": p["seat_ids"],
              "session_key": p["session_key"]},
    )
    assert again.status_code == 201, again.text
    assert set(again.json()["seat_ids"]) == set(p["seat_ids"])


def test_someone_else_can_take_abandoned_seats_immediately(client, picker) -> None:  # noqa: ANN001
    p = picker()
    hold = client.post(
        f"{API}/holds",
        json={"show_id": p["show_id"], "seat_ids": p["seat_ids"],
              "session_key": p["session_key"]},
    ).json()
    client.request(
        "DELETE",
        f"{API}/holds/{hold['hold_id']}",
        json={"session_key": p["session_key"], "reason": "abandoned"},
    )

    other = client.post(
        f"{API}/holds",
        json={"show_id": p["show_id"], "seat_ids": p["seat_ids"],
              "session_key": uuid.uuid4().hex},
    )
    assert other.status_code == 201, "abandoned seats should be free at once"


# ----------------------------------------------------------------- keep on hold
def test_keeping_seats_extends_the_window(client, picker) -> None:  # noqa: ANN001
    p = picker()
    hold = client.post(
        f"{API}/holds",
        json={"show_id": p["show_id"], "seat_ids": p["seat_ids"],
              "session_key": p["session_key"]},
    ).json()
    short = hold["seconds_remaining"]

    kept = client.post(
        f"{API}/holds/{hold['hold_id']}/keep",
        json={"session_key": p["session_key"]},
    )
    assert kept.status_code == 200, kept.text
    body = kept.json()

    assert body["is_kept"] is True
    assert body["seconds_remaining"] > short
    assert body["seconds_remaining"] > settings.seat_selection_ttl_seconds
    assert set(body["seat_ids"]) == set(p["seat_ids"])


def test_a_kept_hold_survives_navigating_away(client, picker) -> None:  # noqa: ANN001
    """Having asked to keep the seats, leaving the page must not drop them."""
    p = picker()
    hold = client.post(
        f"{API}/holds",
        json={"show_id": p["show_id"], "seat_ids": p["seat_ids"],
              "session_key": p["session_key"]},
    ).json()
    client.post(
        f"{API}/holds/{hold['hold_id']}/keep", json={"session_key": p["session_key"]}
    )

    # The browser reports the customer left checkout.
    released = client.request(
        "DELETE",
        f"{API}/holds/{hold['hold_id']}",
        json={"session_key": p["session_key"], "reason": "abandoned"},
    )
    assert released.status_code == 200
    assert _status_of(p["show_id"], p["seat_ids"][0]) == "held", (
        "an explicit keep must outrank an abandon"
    )

    # But an explicit release still works.
    client.request(
        "DELETE",
        f"{API}/holds/{hold['hold_id']}",
        json={"session_key": p["session_key"], "reason": "explicit"},
    )
    assert _status_of(p["show_id"], p["seat_ids"][0]) == "available"


def test_another_session_cannot_keep_or_release_your_hold(client, picker) -> None:  # noqa: ANN001
    p = picker()
    hold = client.post(
        f"{API}/holds",
        json={"show_id": p["show_id"], "seat_ids": p["seat_ids"],
              "session_key": p["session_key"]},
    ).json()
    stranger = uuid.uuid4().hex

    assert client.post(
        f"{API}/holds/{hold['hold_id']}/keep", json={"session_key": stranger}
    ).status_code == 403
    assert client.request(
        "DELETE", f"{API}/holds/{hold['hold_id']}",
        json={"session_key": stranger, "reason": "explicit"},
    ).status_code == 403


def test_starting_payment_extends_a_short_selection_hold(client, picker) -> None:  # noqa: ANN001
    """Reaching payment must not fail because the selection window was short."""
    p = picker()
    email = f"hold_{uuid.uuid4().hex[:8]}@example.com"
    reg = client.post(
        f"{API}/auth/register",
        json={"email": email, "password": "hunter2pass", "full_name": "Holder"},
    ).json()
    auth = {"Authorization": f"Bearer {reg['tokens']['access_token']}"}

    hold = client.post(
        f"{API}/holds",
        json={"show_id": p["show_id"], "seat_ids": p["seat_ids"],
              "session_key": p["session_key"]},
        headers=auth,
    ).json()
    booking = client.post(
        f"{API}/bookings",
        json={"hold_id": hold["hold_id"], "session_key": p["session_key"],
              "contact_email": email},
        headers=auth,
    ).json()

    pay = client.post(
        f"{API}/bookings/{booking['id']}/pay", json={"method": "upi"}, headers=auth
    )
    assert pay.status_code == 200, pay.text

    refreshed = client.get(
        f"{API}/holds/{hold['hold_id']}", params={"session_key": p["session_key"]}
    ).json()
    assert refreshed["seconds_remaining"] > settings.seat_selection_ttl_seconds, (
        "the payment window should have extended the hold"
    )


# ------------------------------------------------------- no more orphan rule
def test_any_available_seat_can_be_selected(client, picker) -> None:  # noqa: ANN001
    """The single-seat-gap restriction is gone.

    Booking seats that strand a lone seat between two taken ones used to be
    refused. It is a legitimate selection and is now allowed.
    """
    p = picker(n=1)
    seatmap = client.get(f"{API}/shows/{p['show_id']}/seatmap").json()
    row = next(
        r for r in seatmap["rows"]
        if sum(s["status"] == "available" for s in r["seats"]) >= 4
    )
    seats = [s for s in row["seats"] if s["status"] == "available"]

    # Take seat 1 and seat 3, deliberately stranding seat 2.
    resp = client.post(
        f"{API}/holds",
        json={
            "show_id": p["show_id"],
            "seat_ids": [seats[0]["seat_id"], seats[2]["seat_id"]],
            "session_key": uuid.uuid4().hex,
        },
    )
    assert resp.status_code == 201, (
        f"a gap-leaving selection must be allowed now: {resp.text}"
    )
