"""The end-to-end acceptance test.

Walks the exact path a customer takes, through the real HTTP API, against a real
PostgreSQL database, with the mock gateway delivering a real signed webhook:

    register -> pick city -> browse movies -> showtimes -> seat map -> hold
    -> quote with an offer -> create booking -> start payment -> settle
    -> confirmed ticket -> booking history -> cancel with refund

If this passes, the vertical slice genuinely works.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.core.db import SessionLocal

API = "/api/v1"


@pytest.fixture
def session_key() -> str:
    return uuid.uuid4().hex


def _register(client) -> tuple[dict, str]:  # noqa: ANN001
    email = f"e2e_{uuid.uuid4().hex[:10]}@example.com"
    resp = client.post(
        f"{API}/auth/register",
        json={"email": email, "password": "hunter2pass", "full_name": "E2E Tester"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body["user"], body["tokens"]["access_token"]


def test_full_booking_journey(client, session_key, cleanup_bookings, pick_show) -> None:  # noqa: ANN001
    user, token = _register(client)
    auth = {"Authorization": f"Bearer {token}"}

    # --- 1. Cities -------------------------------------------------------
    cities = client.get(f"{API}/cities").json()
    assert cities, "seed should provide cities"
    city = cities[0]

    # --- 2. Movies showing in that city ----------------------------------
    movies = client.get(
        f"{API}/movies", params={"city_id": city["id"], "status": "now_showing"}
    ).json()
    assert movies["total"] > 0, "no movies showing in the seeded city"
    movie = movies["items"][0]

    detail = client.get(f"{API}/movies/{movie['id']}").json()
    assert detail["synopsis"], "movie detail must carry the synopsis the AI layer embeds"

    # --- 3. Showtimes ----------------------------------------------------
    board = client.get(
        f"{API}/showtimes", params={"movie_id": movie["id"], "city_id": city["id"]}
    ).json()
    assert board["cinemas"], "no showtimes for that movie/city"

    # This journey ends by cancelling, so the show must sit outside the
    # configured cancellation cutoff. Without that requirement the test passes
    # in the morning and fails in the evening.
    show = pick_show(client, cancellable=True)
    show_id = show["id"]
    cleanup_bookings.append(show_id)

    # --- 4. Seat map -----------------------------------------------------
    seatmap = client.get(f"{API}/shows/{show_id}/seatmap").json()
    assert seatmap["total_seats"] > 0
    assert seatmap["available_seats"] > 0

    # Three adjacent seats in one row, avoiding the orphan-seat rule.
    row = next(r for r in seatmap["rows"] if sum(s["status"] == "available" for s in r["seats"]) >= 6)
    available = [s for s in row["seats"] if s["status"] == "available"]
    chosen = available[:3]
    seat_ids = [s["seat_id"] for s in chosen]
    expected_ticket_total = sum(s["price_minor"] for s in chosen)

    # --- 5. Hold ---------------------------------------------------------
    hold_resp = client.post(
        f"{API}/holds",
        json={"show_id": show_id, "seat_ids": seat_ids, "session_key": session_key},
        headers=auth,
    )
    assert hold_resp.status_code == 201, hold_resp.text
    hold = hold_resp.json()
    assert hold["seat_count"] == 3
    assert hold["subtotal_minor"] == expected_ticket_total
    assert hold["seconds_remaining"] > 0

    # The seat map must now show them as held to everyone else.
    after_hold = client.get(f"{API}/shows/{show_id}/seatmap").json()
    held = {s["seat_id"] for r in after_hold["rows"] for s in r["seats"] if s["status"] == "held"}
    assert set(seat_ids) <= held
    assert after_hold["available_seats"] == seatmap["available_seats"] - 3

    # --- 6. Quote, with a valid and an invalid offer ----------------------
    bad = client.post(
        f"{API}/bookings/quote",
        json={"hold_id": hold["hold_id"], "session_key": session_key, "offer_code": "NOPE"},
        headers=auth,
    ).json()
    assert bad["offer_error"], "an unknown code should report an error, not 500"
    assert bad["discount_minor"] == 0

    quote = client.post(
        f"{API}/bookings/quote",
        json={
            "hold_id": hold["hold_id"],
            "session_key": session_key,
            "offer_code": "FIRSTSHOW",
        },
        headers=auth,
    ).json()
    assert quote["discount_minor"] > 0, quote
    assert quote["total_minor"] == (
        quote["ticket_subtotal_minor"]
        + quote["fnb_subtotal_minor"]
        - quote["discount_minor"]
        + quote["convenience_fee_minor"]
        + quote["tax_minor"]
    )

    # --- 7. Create the booking (with idempotency) ------------------------
    idem = uuid.uuid4().hex
    payload = {
        "hold_id": hold["hold_id"],
        "session_key": session_key,
        "contact_email": user["email"],
        "contact_phone": "+919000000000",
        "offer_code": "FIRSTSHOW",
    }
    created = client.post(
        f"{API}/bookings", json=payload, headers={**auth, "Idempotency-Key": idem}
    )
    assert created.status_code == 201, created.text
    booking = created.json()
    assert booking["status"] == "draft"
    assert booking["total_minor"] == quote["total_minor"]
    assert len(booking["seats"]) == 3

    # A retried POST with the same key returns the same booking, not a new one.
    replay = client.post(
        f"{API}/bookings", json=payload, headers={**auth, "Idempotency-Key": idem}
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == booking["id"]

    # A different body under the same key is a client bug and is rejected.
    conflict = client.post(
        f"{API}/bookings",
        json={**payload, "contact_phone": "+919111111111"},
        headers={**auth, "Idempotency-Key": idem},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    # --- 8. Start payment ------------------------------------------------
    pay = client.post(
        f"{API}/bookings/{booking['id']}/pay", json={"method": "upi"}, headers=auth
    )
    assert pay.status_code == 200, pay.text
    payment = pay.json()
    assert payment["amount_minor"] == booking["total_minor"]

    pending = client.get(f"{API}/bookings/{booking['id']}", headers=auth).json()
    assert pending["status"] == "payment_pending"

    # --- 9. Settle: the mock PSP sends a signed webhook -------------------
    settle = client.post(
        f"{API}/payments/mock/{payment['gateway_order_id']}/complete",
        params={"outcome": "success"},
    )
    assert settle.status_code == 200, settle.text
    assert settle.json()["status"] == "confirmed", settle.json()

    confirmed = client.get(f"{API}/bookings/{booking['id']}", headers=auth).json()
    assert confirmed["status"] == "confirmed"
    assert confirmed["qr_payload"], "a confirmed booking must carry a signed ticket"
    assert confirmed["confirmed_at"]

    # Seats are now booked, not merely held.
    with SessionLocal() as db:
        statuses = db.execute(
            text(
                "SELECT DISTINCT status::text FROM show_seats "
                "WHERE booking_id = CAST(:b AS uuid)"
            ),
            {"b": booking["id"]},
        ).scalars().all()
    assert statuses == ["booked"], statuses

    # --- 10. Duplicate webhook must be a no-op ---------------------------
    replayed = client.post(
        f"{API}/payments/mock/{payment['gateway_order_id']}/complete",
        params={"outcome": "success"},
    )
    assert replayed.json()["status"] == "duplicate", replayed.json()
    with SessionLocal() as db:
        seat_count = db.execute(
            text("SELECT count(*) FROM booking_seats WHERE booking_id = CAST(:b AS uuid)"),
            {"b": booking["id"]},
        ).scalar_one()
    assert seat_count == 3, "a replayed webhook must not duplicate tickets"

    # --- 11. Booking history ---------------------------------------------
    history = client.get(f"{API}/bookings", headers=auth).json()
    assert history["total"] == 1
    assert history["items"][0]["booking_reference"] == booking["booking_reference"]

    # --- 12. Cancel with refund ------------------------------------------
    cq = client.get(f"{API}/bookings/{booking['id']}/cancellation-quote", headers=auth).json()
    assert cq["refundable"] is True
    assert 0 < cq["refund_minor"] < booking["total_minor"], "fee should be forfeited"

    cancelled = client.post(
        f"{API}/bookings/{booking['id']}/cancel",
        json={"reason": "plans changed"},
        headers=auth,
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"

    # Seats are back on sale and the counter agrees.
    final_map = client.get(f"{API}/shows/{show_id}/seatmap").json()
    assert final_map["available_seats"] == seatmap["available_seats"]

    with SessionLocal() as db:
        refund_status, refund_amount = db.execute(
            text(
                "SELECT status::text, amount_minor FROM refunds "
                "WHERE booking_id = CAST(:b AS uuid)"
            ),
            {"b": booking["id"]},
        ).one()
    assert refund_status == "succeeded"
    assert refund_amount == cq["refund_minor"]


def test_failed_payment_releases_seats(client, session_key, cleanup_bookings, pick_show) -> None:  # noqa: ANN001
    """A declined card must put the seats straight back on sale."""
    user, token = _register(client)
    auth = {"Authorization": f"Bearer {token}"}

    # No cancellation here, so any bookable show will do.
    show_id = pick_show(client)["id"]
    cleanup_bookings.append(show_id)

    seatmap = client.get(f"{API}/shows/{show_id}/seatmap").json()
    before = seatmap["available_seats"]
    row = next(r for r in seatmap["rows"] if sum(s["status"] == "available" for s in r["seats"]) >= 4)
    seat_ids = [s["seat_id"] for s in row["seats"] if s["status"] == "available"][:2]

    hold = client.post(
        f"{API}/holds",
        json={"show_id": show_id, "seat_ids": seat_ids, "session_key": session_key},
        headers=auth,
    ).json()
    booking = client.post(
        f"{API}/bookings",
        json={
            "hold_id": hold["hold_id"],
            "session_key": session_key,
            "contact_email": user["email"],
        },
        headers=auth,
    ).json()
    payment = client.post(
        f"{API}/bookings/{booking['id']}/pay", json={"method": "card"}, headers=auth
    ).json()

    result = client.post(
        f"{API}/payments/mock/{payment['gateway_order_id']}/complete",
        params={"outcome": "failure"},
    )
    assert result.json()["status"] == "failed", result.json()

    after = client.get(f"{API}/bookings/{booking['id']}", headers=auth).json()
    assert after["status"] == "payment_failed"

    final_map = client.get(f"{API}/shows/{show_id}/seatmap").json()
    assert final_map["available_seats"] == before, "seats must return to the pool immediately"


def test_forged_webhook_signature_is_rejected(client) -> None:  # noqa: ANN001
    """An unsigned/forged event must never move money state."""
    resp = client.post(
        f"{API}/payments/webhook/mock",
        content=b'{"id":"evt_forged","type":"payment.captured","data":{"order_id":"x"}}',
        headers={"X-Signature": "deadbeef", "Content-Type": "application/json"},
    )
    assert resp.status_code == 402
    assert resp.json()["error"]["code"] == "BAD_SIGNATURE"
