# Database schema

PostgreSQL 18. **32 tables**, grouped by owning module. The full DDL is in
[`backend/app/db/migrations/versions/`](../backend/app/db/migrations/versions/);
this document explains the decisions behind it.

---

## Conventions

| Decision | Choice | Why |
|---|---|---|
| Primary keys | `uuid` defaulting to `uuidv7()` | PostgreSQL 18 ships UUIDv7 natively. Time-ordered, so inserts land at the right edge of the B-tree like a sequence, but globally unique and non-guessable — safe to expose in URLs. |
| Money | `integer`, minor units (paise) | Money arithmetic that can round is money arithmetic that will eventually be wrong. Every column is `*_minor`. Rupees exist only at the formatting boundary. |
| Timestamps | `timestamptz` everywhere | Absolute instants. Local wall time is reconstructed from the cinema's IANA zone. |
| Status columns | Native PG enums | The database itself rejects a bad status, and adding a value is a cheap `ALTER TYPE`. Anything an operator edits at runtime (seat categories, formats, offers) is a **table** instead. |
| Constraint names | Explicit naming convention | Alembic autogenerate then produces stable, reversible migrations. |
| Soft delete | `is_active` flags, no global soft-delete | Only where something must survive for the record (`booking_seats`, `seats`). |

### Time, specifically

A "9:30 PM show" is stored as three facts:

```
cinemas.timezone   'Asia/Kolkata'          -- IANA name, the anchor
shows.starts_at    timestamptz             -- the absolute instant
shows.show_date    date                    -- the calendar date IN CINEMA-LOCAL TIME
```

`show_date` cannot be derived with `date(starts_at)`: a 00:30 midnight show
belongs to the *previous* evening's listing. The scheduler builds the instant as
`local wall time → attach zone → convert to UTC`. Doing it the other way round
is the bug that makes every show an hour wrong twice a year.

---

## Identity

```
users                id, email UNIQUE, phone UNIQUE, full_name, password_hash,
                     role(user_role), is_active, email_verified_at, last_login_at,
                     default_city_id → cities, preferences jsonb, timestamps

refresh_tokens       id, user_id → users CASCADE, token_hash(64) UNIQUE,
                     expires_at, revoked_at, rotated_from_id → refresh_tokens,
                     user_agent, ip_address inet, created_at
```

Passwords are Argon2id. Only the **SHA-256 hash** of a refresh token is stored,
so a database dump cannot be replayed as a login. `rotated_from_id` makes theft
detectable: a token that was already rotated being presented again revokes the
whole chain.

---

## Venues — the physical template

```
cities               id, name, slug UNIQUE, state, country_code, timezone,
                     lat, lon, is_active, display_order

cinemas              id, city_id → cities, name, slug UNIQUE, brand,
                     address_line, locality, pincode, lat, lon, timezone,
                     amenities jsonb, is_active, operator_user_id → users

seat_categories      id, cinema_id → cinemas CASCADE, code, name, description,
                     default_price_minor, display_order, color_hex
                     UNIQUE (cinema_id, code)

screens              id, cinema_id → cinemas CASCADE, name, screen_number,
                     supported_formats jsonb, sound_system, total_seats,
                     layout_meta jsonb, layout_version, is_active
                     UNIQUE (cinema_id, screen_number)

seats                id, screen_id → screens CASCADE, category_id → seat_categories,
                     row_label, row_index, seat_number, column_index,
                     is_aisle, is_wheelchair_accessible, is_companion, is_active
                     UNIQUE (screen_id, row_label, seat_number)
                     INDEX (screen_id, row_index, column_index)
```

**`column_index` is not `seat_number`.** Aisles occupy grid columns without
being seats. Keeping them distinct is what lets the UI render the gap, and what
makes "an aisle seat" a precise idea rather than a guess.

`seat_categories` is a table, not an enum: operators rename tiers and each
carries a default price. Enums cannot hold a price.

---

## Catalog

```
movies               id, title, original_title, slug UNIQUE, tagline, synopsis,
                     runtime_minutes, certification, release_date,
                     status(movie_status), original_language_id → languages,
                     poster_url, backdrop_url, trailer_url,
                     rating_average, rating_count, popularity_score,
                     ai_summary, ai_summary_generated_at, ai_attributes jsonb,
                     is_active
                     INDEX (status, release_date), (popularity_score)
                     GIN trgm INDEX (title)          -- typo-tolerant search

genres / languages / people        reference data
movie_genres / movie_languages     join tables (no payload → Core tables)
movie_credits        id, movie_id, person_id, credit_type, character_name,
                     job, billing_order
                     UNIQUE (movie_id, person_id, credit_type, job, character_name)
                            NULLS NOT DISTINCT

reviews              id, movie_id, user_id, booking_id, rating 1..10, title, body,
                     is_spoiler, helpful_count, ai_aspects jsonb, ai_sentiment
                     UNIQUE (movie_id, user_id)
```

`movie_credits` needs **`NULLS NOT DISTINCT`** (PostgreSQL 15+). `job` and
`character_name` are nullable, and under the default rule two crew rows with a
NULL job would both be permitted — the constraint would silently allow exactly
the duplicates it exists to prevent.

`rating_average` / `rating_count` are caches recomputed after each review;
`reviews` stays the source of truth. Listing pages must not `AVG()` per card.

---

## Scheduling

```
formats              id, code UNIQUE, name, surcharge_minor, display_order

shows                id, movie_id, screen_id, format_id,
                     audio_language_id, subtitle_language_id,
                     cinema_id ┐ denormalised
                     city_id   ┘
                     starts_at, ends_at, show_date,
                     status(show_status), sales_open_at, sales_close_at,
                     screen_layout_version, total_seats, available_seats,
                     cancellation_reason
                     UNIQUE (screen_id, starts_at)
                     EXCLUDE USING gist (screen_id WITH =,
                                         tstzrange(starts_at, ends_at) WITH &&)
                             WHERE (status <> 'cancelled')
                     INDEX (city_id, movie_id, show_date)      ← the hot query
                     INDEX (cinema_id, show_date, starts_at)
                     INDEX (status, starts_at)

show_prices          id, show_id → shows CASCADE, seat_category_id, price_minor
                     UNIQUE (show_id, seat_category_id)
```

**The overlap constraint is the important one.** `UNIQUE (screen_id, starts_at)`
only catches identical start times; a 168-minute film at 17:00 and another at
18:00 are two different start times and one double-booked auditorium. The
`EXCLUDE` constraint (GiST + `btree_gist`) expresses "same screen **and**
overlapping time range" as a single database-enforced rule. Ranges are
half-open, so back-to-back scheduling is allowed; cancelled shows are excluded
so a cancellation frees the slot immediately.

Prices live per **show**, not per screen — that is what makes weekend pricing,
matinee discounts and dynamic pricing possible without touching the layout.

---

## Inventory — the contended tables

```
seat_holds           id, show_id → shows CASCADE, user_id, session_key,
                     status(hold_status), seat_count, expires_at, released_at
                     INDEX (show_id, status), (status, expires_at)

show_seats           id, show_id → shows CASCADE, seat_id → seats,
                     seat_category_id, price_minor,
                     status(show_seat_status),
                     hold_id → seat_holds, hold_expires_at,
                     booking_id → bookings, blocked_reason
                     UNIQUE (show_id, seat_id)              ← anti-double-booking
                     INDEX  (show_id, status)
                     CHECK  status <> 'booked'    OR booking_id IS NOT NULL
                     CHECK  status <> 'held'      OR (hold_id IS NOT NULL
                                                      AND hold_expires_at IS NOT NULL)
                     CHECK  status <> 'available' OR (hold_id IS NULL
                                                      AND booking_id IS NULL)
```

### Why one row per (show, seat)

The alternative — deriving availability by subtracting booked seats from the
layout — looks cheaper until you need to *hold* a seat. A hold has state (who,
until when) that must live somewhere and must be lockable. A materialised row is
that somewhere.

The cost is bounded: 12 screens × 140 seats × 24 shows/day ≈ 40k rows per day of
schedule. The demo seed creates 40,320 rows in 2.4 seconds. In exchange, every
seat map is one indexed read and "is this seat taken?" becomes a property of a
single lockable row.

`hold_expires_at` is denormalised from `seat_holds` so the "is this hold still
good?" test is a single-table predicate. Without it, reclaiming an expired hold
would need a join inside the hot `UPDATE`'s `WHERE` clause — and joins inside an
UPDATE predicate are where concurrency bugs hide.

---

## Booking

```
bookings             id, booking_reference(16) UNIQUE, user_id, show_id, hold_id,
                     status(booking_status), seat_count,
                     ticket_subtotal_minor, fnb_subtotal_minor, discount_minor,
                     convenience_fee_minor, tax_minor, total_minor, currency,
                     price_breakdown jsonb, offer_id, offer_code,
                     contact_email, contact_phone,
                     payment_deadline_at, confirmed_at, cancelled_at,
                     cancellation_reason, qr_payload,
                     checked_in_at, checked_in_seats, booking_metadata jsonb
                     CHECK total_minor = ticket_subtotal + fnb_subtotal
                                       - discount + convenience_fee + tax
                     INDEX (user_id, created_at), (show_id, status),
                           (status, payment_deadline_at), (hold_id)

booking_seats        id, booking_id → bookings CASCADE, show_seat_id → show_seats,
                     seat_id, seat_label, seat_category_name, price_minor,
                     checked_in_at, is_active
                     UNIQUE INDEX (show_seat_id) WHERE is_active   ← partial!

booking_fnb_items    id, booking_id, fnb_item_id, item_name, quantity,
                     unit_price_minor, total_minor
                     CHECK total_minor = unit_price_minor * quantity

idempotency_keys     id, key, user_id, scope, request_hash,
                     response_status, response_body jsonb, booking_id,
                     created_at, completed_at
                     UNIQUE (scope, key)
```

**The partial index on `booking_seats` matters and is easy to get wrong.**
A plain `UNIQUE (show_seat_id)` looks equivalent and is not: after a
cancellation the seat returns to sale, and the next buyer's INSERT collides with
the *cancelled* booking's row. The seat becomes silently unsellable forever —
and only seats that had once been cancelled are affected, which is precisely the
class of bug that survives a happy-path test suite. `is_active` is set to false
on every terminal transition, and
[`test_rebooking_after_cancel.py`](../backend/tests/integration/test_rebooking_after_cancel.py)
locks the behaviour in.

The **`total_is_sum_of_parts` CHECK** means a future pricing change that breaks
the arithmetic fails the insert instead of quietly mis-charging a customer.

---

## Payments

```
payments             id, booking_id, gateway, gateway_order_id, gateway_payment_id,
                     amount_minor, currency, amount_refunded_minor,
                     status(payment_status), method, failure_code, failure_message,
                     authorized_at, captured_at, requires_auto_refund,
                     gateway_payload jsonb
                     UNIQUE (gateway, gateway_order_id)
                     CHECK amount_refunded_minor BETWEEN 0 AND amount_minor

payment_events       id, payment_id, gateway, event_id, event_type,
                     signature_valid, payload jsonb,
                     received_at, processed_at, processing_error
                     UNIQUE (gateway, event_id)              ← exactly-once

refunds              id, payment_id, booking_id, amount_minor,
                     status(refund_status), reason, gateway_refund_id,
                     idempotency_key UNIQUE, completed_at, failure_message
```

`UNIQUE (gateway, event_id)` is the entire idempotency story: at-least-once
delivery becomes exactly-once processing with one index. The event row is
inserted **before** any effect is applied.

`requires_auto_refund` is the flag for the one outcome that must never be
silently dropped — money captured for seats that could not be delivered.

---

## Pricing, F&B, notifications, audit

```
offers               id, code UNIQUE, name, description, offer_type,
                     percent_off, flat_off_minor, buy_quantity, get_quantity,
                     max_discount_minor, min_order_minor,
                     valid_from, valid_until,
                     usage_limit_total, usage_limit_per_user, redeemed_count,
                     conditions jsonb, is_active, is_stackable
                     CHECK the value column matches offer_type

offer_redemptions    id, offer_id, booking_id UNIQUE, user_id, discount_minor
fnb_items            id, cinema_id, name, description, category, price_minor,
                     image_url, is_vegetarian, is_available, display_order
notifications        id, user_id, booking_id, channel, template, recipient,
                     subject, body, payload jsonb, status, attempts, last_error,
                     scheduled_for, sent_at
domain_events        id, aggregate_type, aggregate_id, event_type,
                     actor_user_id, actor_type, request_id, ip_address,
                     payload jsonb, created_at
```

`UNIQUE (booking_id)` on `offer_redemptions` enforces "one offer per booking" in
the database, where a concurrent double-apply cannot slip past it.

---

## Worked pricing example

Three Prime seats at ₹260, one large popcorn at ₹320, promo `FIRSTSHOW`
(20% off tickets, capped at ₹150):

| Step | Rule | Amount |
|---|---|---|
| Ticket subtotal | 3 × ₹260 | ₹780.00 |
| F&B subtotal | 1 × ₹320 | ₹320.00 |
| Discount | 20% of ₹780 = ₹156, capped at ₹150 | −₹150.00 |
| Convenience fee | 8% of post-discount tickets (₹630), cap ₹60 | ₹50.40 |
| GST on tickets | per-ticket band: ₹260 > ₹100 → 18%, discount apportioned | ₹113.40 |
| GST on fee | 18% of ₹50.40 | ₹9.07 |
| GST on F&B | 5% of ₹320 | ₹16.00 |
| **Total** | | **₹1,138.87** |

Order of operations matters: the fee is charged on the *post-discount* ticket
amount, because charging it on the pre-discount amount would let a coupon
silently increase the fee's share — customers notice.

The calculator ([`pricing/calculator.py`](../backend/app/modules/pricing/calculator.py))
is a pure function over plain data — no session, no clock — so every rule is
unit-testable and the UI, the booking and any future caller cannot disagree.

---

## Growth notes

- **Partition `bookings` by `created_at`** (monthly) once it passes ~10M rows.
  The PK becomes `(id, created_at)`, so plan for it before the table is huge.
- **`domain_events` and `payment_events`** grow fastest and are archival by
  nature — partition or roll off to cold storage first.
- **`show_seats`** can be pruned for shows that finished more than N months ago;
  `booking_seats` already snapshots everything a ticket needs.
- **pgvector is installed but unused.** The extension is enabled in migration
  `0001` so the ground is prepared, and there is no `embeddings` table — that is
  yours to design.
