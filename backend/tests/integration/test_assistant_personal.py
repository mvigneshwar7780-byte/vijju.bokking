"""Scoping of the signed-in customer's own data.

The property under test is not "the assistant is helpful" -- it is that the set
of rows reaching the prompt is decided by the token, and that nothing a customer
types can widen it. These tests therefore assert on *which user id the query
runs for*, not on the wording of any answer.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from sqlalchemy import text

from app.modules.assistant.personal import build_personal_context

API = "/api/v1"


# ------------------------------------------------------------ guests ---------


def test_a_guest_contributes_no_personal_context() -> None:
    """Empty, not a 'no bookings' notice.

    A sentence saying "no bookings found" would invite the model to reason
    about whose account it is looking at. Silence cannot be misread.
    """
    assert build_personal_context(None) == ""
    assert build_personal_context("") == ""


def test_a_malformed_id_yields_nothing() -> None:
    """If the id is not a uuid the caller is not who the token says."""
    assert build_personal_context("not-a-uuid") == ""
    assert build_personal_context("'; DROP TABLE bookings; --") == ""


# ------------------------------------------------------------ scoping --------


def test_the_query_runs_for_the_token_user_only() -> None:
    """The decisive test: which id reaches the scoped query.

    `list_for_user` filters `Booking.user_id == user_id` in SQL. Proving the
    right id is handed to it proves the model cannot widen the row set, because
    the model is not involved in choosing it.
    """
    mine = uuid.uuid4()
    seen: dict = {}

    class FakeService:
        def __init__(self, db):  # noqa: ANN001
            pass

        def list_for_user(self, user_id, *, offset, limit):  # noqa: ANN001
            seen["user_id"] = user_id
            return [], 0

    with patch("app.modules.booking.service.BookingService", FakeService):
        build_personal_context(str(mine))

    assert seen["user_id"] == mine, "the scoped query ran for the wrong user"


def test_question_text_cannot_redirect_the_lookup() -> None:
    """A forged id inside the question must not become the identity.

    `build_personal_context` takes only the token's id as an argument -- there
    is no parameter the question could reach. This pins that shape.
    """
    import inspect

    params = list(inspect.signature(build_personal_context).parameters)
    assert params == ["user_id"], (
        f"build_personal_context grew a parameter ({params}); if any of them can "
        "carry question text, the scoping guarantee is gone"
    )


# ------------------------------------------------------ against real rows ----


def _a_user_with_bookings(db) -> uuid.UUID | None:  # noqa: ANN001
    row = db.execute(
        text(
            "SELECT user_id FROM bookings WHERE user_id IS NOT NULL "
            "GROUP BY user_id ORDER BY count(*) DESC LIMIT 1"
        )
    ).first()
    return uuid.UUID(str(row.user_id)) if row else None


@pytest.fixture
def two_customers_with_bookings(client, pick_show, cleanup_bookings):  # noqa: ANN001
    """Two real, paid bookings owned by two different accounts.

    Committed through the API rather than inserted, because
    `build_personal_context` opens its own session and would never see rows
    written inside the rolled-back `db` fixture -- a test built that way would
    pass while proving nothing.
    """

    def book() -> uuid.UUID:
        email = f"ctx_{uuid.uuid4().hex[:8]}@example.com"
        reg = client.post(
            f"{API}/auth/register",
            json={"email": email, "password": "hunter2pass", "full_name": "Ctx"},
        ).json()
        auth = {"Authorization": f"Bearer {reg['tokens']['access_token']}"}
        session_key = uuid.uuid4().hex

        show = pick_show(client, cancellable=True)
        cleanup_bookings.append(show["id"])
        seatmap = client.get(f"{API}/shows/{show['id']}/seatmap").json()
        row = next(
            r for r in seatmap["rows"]
            if sum(s["status"] == "available" for s in r["seats"]) >= 2
        )
        seat_ids = [s["seat_id"] for s in row["seats"] if s["status"] == "available"][:1]

        hold = client.post(
            f"{API}/holds",
            json={"show_id": show["id"], "seat_ids": seat_ids, "session_key": session_key},
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
        client.post(
            f"{API}/payments/mock/{payment['gateway_order_id']}/complete",
            params={"outcome": "success"},
        )
        return uuid.UUID(reg["user"]["id"])

    return book(), book()


def test_one_customer_never_sees_another(two_customers_with_bookings, db) -> None:  # noqa: ANN001
    """The security property: my context contains my rows and nobody else's."""
    mine, theirs = two_customers_with_bookings

    def references(user_id: uuid.UUID) -> set[str]:
        return {
            r.booking_reference
            for r in db.execute(
                text("SELECT booking_reference FROM bookings WHERE user_id = CAST(:u AS uuid)"),
                {"u": str(user_id)},
            )
        }

    my_refs, their_refs = references(mine), references(theirs)
    assert my_refs and their_refs, "fixture did not create bookings for both"
    assert not (my_refs & their_refs), "fixture users share a booking"

    context = build_personal_context(str(mine))

    assert my_refs & {r for r in my_refs if r in context}, "my own booking is missing"
    leaked = [ref for ref in their_refs if ref in context]
    assert not leaked, f"another customer's bookings leaked into the prompt: {leaked}"


def test_refund_figures_match_the_cancel_button(two_customers_with_bookings, db) -> None:  # noqa: ANN001
    """The assistant and the UI must not quote different money.

    Both go through `quote_cancellation`, so the amount in the prompt is the
    amount the customer sees when they actually press cancel.
    """
    mine, _ = two_customers_with_bookings

    from app.modules.booking.service import BookingService

    service = BookingService(db)
    bookings, _ = service.list_for_user(mine, offset=0, limit=5)
    refundable = [b for b in bookings if service.quote_cancellation(b)[0]]
    if not refundable:
        import pytest

        pytest.skip("no currently-refundable booking to compare")

    context = build_personal_context(str(mine))
    _, refund_minor, _ = service.quote_cancellation(refundable[0])
    assert f"{refund_minor / 100:,.2f}" in context, (
        "the refund amount in the prompt does not match quote_cancellation"
    )
