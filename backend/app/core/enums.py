"""Domain enumerations.

These are declared as *native PostgreSQL enum types*. The trade-off, stated
plainly because it bites people later:

* Native enum  -> the database itself rejects a bad status; no join needed to
  read a row; tiny storage. Adding a value is ``ALTER TYPE ... ADD VALUE``
  (cheap); removing or reordering one is painful.
* Lookup table -> values are data, editable at runtime, joinable for labels;
  but every read costs a join and nothing stops an orphan status.

Status columns here are part of the domain's *logic*, not user-editable data --
a new booking status means new code either way. So native enums win. Anything a
cinema operator should be able to edit at runtime (seat categories, screen
formats, offer types) is a table instead, not an enum.
"""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Enum as SAEnum


class UserRole(StrEnum):
    CUSTOMER = "customer"
    CINEMA_OPERATOR = "cinema_operator"
    ADMIN = "admin"


class ShowStatus(StrEnum):
    SCHEDULED = "scheduled"
    OPEN = "open"            # selling
    CLOSED = "closed"        # sales cut off, show still upcoming/running
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class ShowSeatStatus(StrEnum):
    """Lifecycle of one physical seat for one specific show."""

    AVAILABLE = "available"
    HELD = "held"            # soft-locked with a TTL while the user pays
    BOOKED = "booked"        # paid for and confirmed
    BLOCKED = "blocked"      # taken out of sale by the operator (maintenance)


class HoldStatus(StrEnum):
    ACTIVE = "active"
    CONVERTED = "converted"  # became a confirmed booking
    RELEASED = "released"    # user abandoned or explicitly released
    EXPIRED = "expired"      # TTL elapsed


class BookingStatus(StrEnum):
    DRAFT = "draft"                    # seats held, nothing paid yet
    PAYMENT_PENDING = "payment_pending"  # gateway order created, awaiting outcome
    CONFIRMED = "confirmed"
    PAYMENT_FAILED = "payment_failed"
    EXPIRED = "expired"                # hold lapsed before payment completed
    CANCELLED = "cancelled"            # cancelled by the user
    REFUNDED = "refunded"
    REVOKED = "revoked"                # show cancelled by the operator


class PaymentStatus(StrEnum):
    CREATED = "created"
    # The gateway accepted the request but the outcome is not known yet. Real
    # for UPI collect requests and netbanking, where the customer may take
    # minutes to approve and the answer arrives by webhook -- or never does, in
    # which case reconciliation asks the gateway directly.
    PROCESSING = "processing"
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    FAILED = "failed"
    # The customer walked away from the checkout page, or the gateway timed the
    # session out. Distinct from `failed`: nothing was declined, so it is not a
    # signal about the customer's payment method and should not be surfaced as
    # one.
    CANCELLED = "cancelled"
    REFUND_PENDING = "refund_pending"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"


class RefundStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class OfferType(StrEnum):
    PERCENT = "percent"
    FLAT = "flat"
    BUY_N_GET_M = "buy_n_get_m"


class NotificationChannel(StrEnum):
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"
    IN_APP = "in_app"


class NotificationStatus(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"


class EmbeddingOwnerType(StrEnum):
    MOVIE = "movie"
    REVIEW = "review"
    USER_TASTE = "user_taste"


class ChatRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM = "system"


class TicketScanResult(StrEnum):
    VALID = "valid"
    ALREADY_SCANNED = "already_scanned"
    INVALID_SIGNATURE = "invalid_signature"
    WRONG_SHOW = "wrong_show"
    NOT_CONFIRMED = "not_confirmed"


# ---------------------------------------------------------------------------
# SQLAlchemy binding
# ---------------------------------------------------------------------------
def pg_enum(enum_cls: type[StrEnum], name: str) -> SAEnum:
    """Bind a Python StrEnum to a native PostgreSQL enum type by *value*.

    SQLAlchemy's default is to persist the member **name** (``DRAFT``), not the
    value (``draft``). That default is a trap here: every CHECK constraint in
    the schema is written against lowercase literals (``status <> 'booked'``),
    and every API payload uses them too. ``values_callable`` makes the stored
    representation the value, so Python, SQL and JSON all agree on one spelling.
    """
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=True,
        validate_strings=True,
        values_callable=lambda e: [member.value for member in e],
    )
