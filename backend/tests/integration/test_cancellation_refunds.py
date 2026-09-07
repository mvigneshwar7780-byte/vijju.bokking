"""Cancellation and refunds.

The policy is tiered on time-to-showtime, which is the only variable that
matters: the further out you cancel, the more likely the seat resells. Inside
the cutoff it will not, so cancellation closes.

Also checked here: the money actually comes back and is *visible* on the
booking afterwards. A refund the customer cannot see is indistinguishable from
one that never happened.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.core.db import SessionLocal

API = "/api/v1"


@pytest.fixture
def confirmed_booking(client, pick_show, cleanup_bookings):  # noqa: ANN001
    """A paid, confirmed booking. `hours_ahead` shifts the show to test tiers."""

    def _make(hours_ahead: float | None = None) -> dict:
        email = f"cancel_{uuid.uuid4().hex[:8]}@example.com"
        reg = client.post(
            f"{API}/auth/register",
            json={"email": email, "password": "hunter2pass", "full_name": "Canceller"},
        ).json()
        auth = {"Authorization": f"Bearer {reg['tokens']['access_token']}"}
        session_key = uuid.uuid4().hex

        show = pick_show(client, cancellable=True)
        cleanup_bookings.append(show["id"])
        seatmap = client.get(f"{API}/shows/{show['id']}/seatmap").json()
        row = next(
            r for r in seatmap["rows"]
            if sum(s["status"] == "available" for s in r["seats"]) >= 4
        )
        seat_ids = [s["seat_id"] for s in row["seats"] if s["status"] == "available"][:2]

        hold = client.post(
            f"{API}/holds",
            json={"show_id": show["id"], "seat_ids": seat_ids,
                  "session_key": session_key},
            headers=auth,
        ).json()
        booking = client.post(
            f"{API}/bookings",
            json={"hold_id": hold["hold_id"], "session_key": session_key,
                  "contact_email": email},
            headers=auth,
        ).json()
        payment = client.post(
            f"{API}/bookings/{booking['id']}/pay", json={"method": "upi"}, headers=auth
        ).json()
        settled = client.post(
            f"{API}/payments/mock/{payment['gateway_order_id']}/complete",
            params={"outcome": "success"},
        ).json()
        assert settled["status"] == "confirmed", settled

        if hours_ahead is not None:
            # Move the show so a specific refund tier applies. Adjusting the
            # clock is not an option in a shared test database.
            #
            # The screen's EXCLUDE constraint refuses overlapping shows -- doing
            # its job -- so anything already sitting in the target slot is
            # cancelled first. Cancelled shows are excluded from the constraint,
            # which is exactly why it is a partial one.
            with SessionLocal() as db:
                starts = datetime.now(UTC) + timedelta(hours=hours_ahead)
                ends = starts + timedelta(hours=2)
                db.execute(
                    text(
                        """
                        UPDATE shows SET status = 'cancelled'
                         WHERE screen_id = (SELECT screen_id FROM shows
                                             WHERE id = CAST(:i AS uuid))
                           AND id <> CAST(:i AS uuid)
                           AND status <> 'cancelled'
                           AND tstzrange(starts_at, ends_at) && tstzrange(:s, :e)
                        """
                    ),
                    {"i": show["id"], "s": starts, "e": ends},
                )
                db.execute(
                    text(
                        "UPDATE shows SET starts_at = :s, ends_at = :e, "
                        "sales_close_at = :c WHERE id = CAST(:i AS uuid)"
                    ),
                    {
                        "s": starts,
                        "e": ends,
                        "c": starts - timedelta(minutes=20),
                        "i": show["id"],
                    },
                )
                db.commit()

        return {"booking": booking, "auth": auth, "show_id": show["id"]}

    return _make


def _get(client, ctx) -> dict:  # noqa: ANN001
    return client.get(
        f"{API}/bookings/{ctx['booking']['id']}", headers=ctx["auth"]
    ).json()


# ------------------------------------------------------------------- tiers ---
def test_cancelling_well_ahead_returns_the_full_ticket_value(client, confirmed_booking) -> None:  # noqa: ANN001
    ctx = confirmed_booking(hours_ahead=48)
    booking = _get(client, ctx)
    quote = booking["cancellation"]

    assert quote["refundable"] is True
    assert "100" in quote["reason"]
    # Everything except the fee and the tax on the fee.
    assert quote["refund_minor"] > booking["ticket_subtotal_minor"]
    assert quote["refund_minor"] < booking["total_minor"]
    assert quote["forfeited_minor"] >= booking["convenience_fee_minor"]


def test_cancelling_close_to_showtime_returns_less(client, confirmed_booking) -> None:  # noqa: ANN001
    """Same booking, later cancellation, smaller refund."""
    # Quote each booking *before* creating the next. `pick_show` is
    # deterministic, so both bookings can land on the same show -- and moving
    # that show to +6h for the second booking silently re-times the first.
    # Reading the quote while the show is still positioned removes the coupling.
    far = confirmed_booking(hours_ahead=48)
    far_quote = _get(client, far)["cancellation"]

    near = confirmed_booking(hours_ahead=6)
    near_quote = _get(client, near)["cancellation"]

    assert near_quote["refundable"] is True
    assert near_quote["refund_minor"] < far_quote["refund_minor"], (
        "cancelling closer to showtime should return less"
    )
    assert settings.cancellation_partial_refund_percent.split(".")[0] in near_quote["reason"]


def test_cancellation_closes_near_showtime(client, confirmed_booking) -> None:  # noqa: ANN001
    ctx = confirmed_booking(hours_ahead=1)
    quote = _get(client, ctx)["cancellation"]
    assert quote["refundable"] is False
    assert quote["refund_minor"] == 0
    assert "closes" in quote["reason"]

    refused = client.post(
        f"{API}/bookings/{ctx['booking']['id']}/cancel",
        json={"reason": "too late"},
        headers=ctx["auth"],
    )
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "CANCELLATION_NOT_ALLOWED"


# ------------------------------------------------------------------ refund ---
def test_cancelling_refunds_and_shows_the_refund(client, confirmed_booking) -> None:  # noqa: ANN001
    ctx = confirmed_booking(hours_ahead=48)
    expected = _get(client, ctx)["cancellation"]["refund_minor"]

    cancelled = client.post(
        f"{API}/bookings/{ctx['booking']['id']}/cancel",
        json={"reason": "plans changed"},
        headers=ctx["auth"],
    )
    assert cancelled.status_code == 200, cancelled.text

    after = _get(client, ctx)
    assert after["status"] == "cancelled"
    assert after["refunded_minor"] == expected
    assert len(after["refunds"]) == 1

    refund = after["refunds"][0]
    assert refund["status"] == "succeeded"
    assert refund["amount_minor"] == expected
    assert refund["reason"] == "user_cancellation"
    assert refund["completed_at"] is not None
    # Nothing left to cancel.
    assert after["cancellation"] is None


def test_cancelling_returns_the_seats_to_sale(client, confirmed_booking) -> None:  # noqa: ANN001
    ctx = confirmed_booking(hours_ahead=48)
    before = client.get(f"{API}/shows/{ctx['show_id']}/seatmap").json()["available_seats"]

    client.post(
        f"{API}/bookings/{ctx['booking']['id']}/cancel",
        json={"reason": "plans changed"},
        headers=ctx["auth"],
    )
    after = client.get(f"{API}/shows/{ctx['show_id']}/seatmap").json()["available_seats"]
    assert after == before + 2


def test_a_booking_cannot_be_cancelled_twice(client, confirmed_booking) -> None:  # noqa: ANN001
    """Otherwise a double-click refunds twice."""
    ctx = confirmed_booking(hours_ahead=48)
    first = client.post(
        f"{API}/bookings/{ctx['booking']['id']}/cancel",
        json={"reason": "once"},
        headers=ctx["auth"],
    )
    assert first.status_code == 200
    second = client.post(
        f"{API}/bookings/{ctx['booking']['id']}/cancel",
        json={"reason": "twice"},
        headers=ctx["auth"],
    )
    assert second.status_code == 409

    after = _get(client, ctx)
    assert len(after["refunds"]) == 1, "a second cancel must not create a second refund"


def test_only_the_owner_can_cancel(client, confirmed_booking) -> None:  # noqa: ANN001
    ctx = confirmed_booking(hours_ahead=48)
    intruder = client.post(
        f"{API}/auth/register",
        json={"email": f"x_{uuid.uuid4().hex[:8]}@example.com",
              "password": "hunter2pass", "full_name": "Intruder"},
    ).json()
    resp = client.post(
        f"{API}/bookings/{ctx['booking']['id']}/cancel",
        json={"reason": "not mine"},
        headers={"Authorization": f"Bearer {intruder['tokens']['access_token']}"},
    )
    assert resp.status_code == 403
