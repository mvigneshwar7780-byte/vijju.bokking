"""Single import surface for every mapped class.

Alembic's autogenerate only sees what has been imported. Rather than scatter
imports through ``env.py``, every module registers here -- and the ordering
below doubles as a dependency map of the domain.
"""

from __future__ import annotations

from app.core.db import Base  # noqa: F401  (re-exported for Alembic)

# Order matters only for readability; SQLAlchemy resolves FKs by name.
from app.modules.identity.models import RefreshToken, User  # noqa: F401
from app.modules.venues.models import (  # noqa: F401
    Cinema,
    City,
    Screen,
    Seat,
    SeatCategory,
)
from app.modules.catalog.models import (  # noqa: F401
    Genre,
    Language,
    Movie,
    MovieCredit,
    Person,
    Review,
    movie_genres,
    movie_languages,
)
from app.modules.scheduling.models import Format, Show, ShowPrice  # noqa: F401
from app.modules.inventory.models import SeatHold, ShowSeat  # noqa: F401
from app.modules.pricing.models import Offer, OfferRedemption  # noqa: F401
from app.modules.fnb.models import FnbItem  # noqa: F401
from app.modules.booking.models import (  # noqa: F401
    Booking,
    BookingFnbItem,
    BookingSeat,
    IdempotencyKey,
)
from app.modules.payments.models import Payment, PaymentEvent, Refund  # noqa: F401
from app.modules.notifications.models import Notification  # noqa: F401
from app.modules.analytics.models import DomainEvent  # noqa: F401

__all__ = ["Base"]
