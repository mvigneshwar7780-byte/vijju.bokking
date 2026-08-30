"""Every outcome a real payment gateway can produce.

A checkout has four endings, not two, and each demands different behaviour:

* **captured** -> confirm the booking, issue the ticket.
* **failed**   -> the bank declined. Release the seats; the customer needs a
                  different method.
* **cancelled**-> the customer walked away. Nothing was declined, so keep the
                  seats held and let them retry.
* **pending**  -> accepted, answer later. Decide nothing; wait for the terminal
                  event or for reconciliation to ask.

Collapsing cancelled into failed is the common shortcut, and it costs the
customer their seats for pressing "back".
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.core.db import SessionLocal

API = "/api/v1"


@pytest.fixture
def draft_booking(client, pick_show, cleanup_bookings):  # noqa: ANN001
    """A booking with held seats, sitting at the payment step."""

    def _make(seats: int = 2) -> dict:
        email = f"pay_{uuid.uuid4().hex[:8]}@example.com"
        reg = client.post(
            f"{API}/auth/register",
            json={"email": email, "password": "hunter2pass", "full_name": "Payer"},
        )
        auth = {"Authorization": f"Bearer {reg.json()['tokens']['access_token']}"}
        session_key = uuid.uuid4().hex

        show = pick_show(client)
        cleanup_bookings.append(show["id"])
        seatmap = client.get(f"{API}/shows/{show['id']}/seatmap").json()
        row = next(
            r for r in seatmap["rows"]
            if sum(s["status"] == "available" for s in r["seats"]) >= seats + 4
        )
        seat_ids = [s["seat_id"] for s in row["seats"] if s["status"] == "available"][:seats]

        hold = client.post(
            f"{API}/holds",
            json={"show_id": show["id"], "seat_ids": seat_ids, "session_key": session_key},
            headers=auth,
        )
        assert hold.status_code == 201, hold.text
        booking = client.post(
            f"{API}/bookings",
            json={
                "hold_id": hold.json()["hold_id"],
                "session_key": session_key,
                "contact_email": email,
            },
            headers=auth,
        )
        assert booking.status_code == 201, booking.text
        return {
            "booking": booking.json(),
            "auth": auth,
            "show_id": show["id"],
            "available_before": seatmap["available_seats"],
        }

    return _make


def _start(client, ctx) -> str:  # noqa: ANN001
    resp = client.post(
        f"{API}/bookings/{ctx['booking']['id']}/pay",
        json={"method": "upi"},
        headers=ctx["auth"],
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["gateway_order_id"]


def _status(client, ctx) -> str:  # noqa: ANN001
    return client.get(
        f"{API}/bookings/{ctx['booking']['id']}", headers=ctx["auth"]
    ).json()["status"]


def _payment_status(booking_id: str) -> str:
    with SessionLocal() as db:
        return db.execute(
            text(
                "SELECT status::text FROM payments WHERE booking_id = CAST(:b AS uuid) "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"b": booking_id},
        ).scalar_one()


# ---------------------------------------------------------------- captured ---
def test_successful_payment_confirms_and_issues_a_ticket(client, draft_booking) -> None:  # noqa: ANN001
    ctx = draft_booking()
    order = _start(client, ctx)
    result = client.post(
        f"{API}/payments/mock/{order}/complete", params={"outcome": "success"}
    ).json()
    assert result["status"] == "confirmed"
    assert _status(client, ctx) == "confirmed"
    assert _payment_status(ctx["booking"]["id"]) == "captured"

    booking = client.get(
        f"{API}/bookings/{ctx['booking']['id']}", headers=ctx["auth"]
    ).json()
    assert booking["qr_payload"]


# ------------------------------------------------------------------ failed ---
def test_declined_payment_releases_the_seats(client, draft_booking) -> None:  # noqa: ANN001
    ctx = draft_booking()
    order = _start(client, ctx)
    result = client.post(
        f"{API}/payments/mock/{order}/complete", params={"outcome": "failure"}
    ).json()
    assert result["status"] == "failed"
    assert _status(client, ctx) == "payment_failed"
    assert _payment_status(ctx["booking"]["id"]) == "failed"

    seatmap = client.get(f"{API}/shows/{ctx['show_id']}/seatmap").json()
    assert seatmap["available_seats"] == ctx["available_before"], (
        "a decline must put the seats straight back on sale"
    )


# --------------------------------------------------------------- cancelled ---
def test_cancelling_at_the_gateway_keeps_the_seats_for_a_retry(client, draft_booking) -> None:  # noqa: ANN001
    """The distinction that matters: cancelled is not declined."""
    ctx = draft_booking()
    order = _start(client, ctx)
    result = client.post(
        f"{API}/payments/mock/{order}/complete", params={"outcome": "cancel"}
    ).json()

    assert result["status"] == "cancelled"
    assert result["retryable"] is True
    assert _payment_status(ctx["booking"]["id"]) == "cancelled"

    # Back to draft, seats still held -- not handed to someone else.
    assert _status(client, ctx) == "draft"
    seatmap = client.get(f"{API}/shows/{ctx['show_id']}/seatmap").json()
    assert seatmap["available_seats"] == ctx["available_before"] - 2

    # ...and the customer can pay again.
    retry_order = _start(client, ctx)
    done = client.post(
        f"{API}/payments/mock/{retry_order}/complete", params={"outcome": "success"}
    ).json()
    assert done["status"] == "confirmed"
    assert _status(client, ctx) == "confirmed"


def test_user_can_cancel_payment_from_the_app(client, draft_booking) -> None:  # noqa: ANN001
    ctx = draft_booking()
    _start(client, ctx)
    result = client.post(
        f"{API}/bookings/{ctx['booking']['id']}/payment/cancel", headers=ctx["auth"]
    )
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "cancelled"
    assert _status(client, ctx) == "draft"


# ----------------------------------------------------------------- pending ---
def test_pending_payment_decides_nothing_until_it_settles(client, draft_booking) -> None:  # noqa: ANN001
    ctx = draft_booking()
    order = _start(client, ctx)
    result = client.post(
        f"{API}/payments/mock/{order}/complete", params={"outcome": "pending"}
    ).json()

    assert result["status"] == "pending"
    assert _status(client, ctx) == "payment_pending"
    assert _payment_status(ctx["booking"]["id"]) == "processing"

    booking = client.get(
        f"{API}/bookings/{ctx['booking']['id']}", headers=ctx["auth"]
    ).json()
    assert booking["qr_payload"] is None, "a pending payment must not issue a ticket"

    # Seats stay held while we wait.
    seatmap = client.get(f"{API}/shows/{ctx['show_id']}/seatmap").json()
    assert seatmap["available_seats"] == ctx["available_before"] - 2

    # The delayed webhook arrives.
    settled = client.post(
        f"{API}/payments/mock/{order}/settle", params={"outcome": "success"}
    ).json()
    assert settled["status"] == "confirmed"
    assert _status(client, ctx) == "confirmed"


def test_pending_that_later_fails_releases_the_seats(client, draft_booking) -> None:  # noqa: ANN001
    ctx = draft_booking()
    order = _start(client, ctx)
    client.post(f"{API}/payments/mock/{order}/complete", params={"outcome": "pending"})
    settled = client.post(
        f"{API}/payments/mock/{order}/settle", params={"outcome": "failure"}
    ).json()
    assert settled["status"] == "failed"
    assert _status(client, ctx) == "payment_failed"
    seatmap = client.get(f"{API}/shows/{ctx['show_id']}/seatmap").json()
    assert seatmap["available_seats"] == ctx["available_before"]


# ---------------------------------------------------------- reconciliation ---
def test_reconciliation_resolves_a_payment_whose_webhook_never_arrived(
    client, draft_booking
) -> None:  # noqa: ANN001
    """The webhook is dropped. The customer must not be stranded."""
    from app.modules.payments.service import PaymentService, get_gateway

    ctx = draft_booking()
    order = _start(client, ctx)

    # Settle it at the gateway, but never deliver the webhook.
    get_gateway().authorize_and_capture(order, force_outcome="success")
    assert _status(client, ctx) == "payment_pending"

    with SessionLocal() as db:
        counts = PaymentService(db).reconcile_pending_payments(older_than_minutes=0)
        db.commit()

    assert counts["resolved"] >= 1, counts
    assert _status(client, ctx) == "confirmed", "reconciliation should have confirmed it"
    assert _payment_status(ctx["booking"]["id"]) == "captured"
