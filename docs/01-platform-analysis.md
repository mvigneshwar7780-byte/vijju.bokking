# How BookMyShow-class platforms actually work

A teardown of the incumbents, and what each observation implies for the data
model. This is the reasoning behind the schema in
[`03-database-schema.md`](03-database-schema.md).

---

## 1. The two-sided shape of the product

Every ticketing platform is really two products sharing one inventory table.

| Side | Who | What they do | Read/write profile |
|---|---|---|---|
| Customer | Public, mostly anonymous until checkout | Browse → pick a showtime → pick seats → pay | Very read-heavy, short bursts of contended writes |
| Operator | Cinema staff, a few hundred people | Define screens and seat layouts, schedule shows, set prices, block seats, pull settlement reports | Low volume, high blast radius |

Aggregators (BookMyShow, Fandango) do **not** own the seat inventory — they
syndicate it from the chain's ticketing backend, which is why "that seat was
just taken" is a routine, expected error there. First-party systems (PVR INOX,
AMC) *are* the system of record, so the same concurrency problem moves from a
sync-lag problem to a database-locking problem.

**This project is modelled as first-party.** It owns the seats. That is the more
interesting problem and the one with a crisp correct answer.

---

## 2. The customer funnel, and what each step needs

```
city → now-showing list → movie detail → date → cinema + showtime
     → seat map → seat hold (countdown starts) → review + offers
     → payment → confirmation + QR ticket → booking history → cancel/refund
```

**City is the root navigation primitive.** BookMyShow puts it in the URL
(`/explore/home/mumbai`); every listing, price and cinema set is scoped to it.
Changing city resets the session context.

> *Schema consequence:* the hottest query in the product is
> "showtimes for movie M, in city C, on date D". A three-table join
> (`shows → screens → cinemas → cities`) cannot be served by one composite
> index, so `shows` carries a denormalised `city_id` and `cinema_id`. This is
> the one place the schema trades normalisation for a query plan, and it is
> worth it.

**Two browse pivots must both exist.** Movie-first (movie → date → cinemas) and
cinema-first (cinema → date → movies). Same table, two access paths, two
indexes.

**Showtime chips carry stacked attributes** — language, dimension (2D/3D),
premium format brand (IMAX, 4DX, ICE), subtitle flag.

> *Schema consequence:* format is a property of the **show**, not of the movie
> and not of the screen. The same film, in the same cinema, on the same evening,
> can run in three formats at three prices. `shows.format_id` + `show_prices`.

**Availability is heat-coded before you click** — green / amber / red on the
chip itself. That must be a cheap per-show aggregate, never a seat-map read.

> *Schema consequence:* `shows.available_seats`, maintained inside the same
> transaction that changes seat state.

**Quantity is often chosen before the seat map opens.** That is what lets the UI
pre-filter to contiguous blocks and drive "best available".

---

## 3. The seat map is the hard part

Observations that break naive implementations:

- **Seat classes are per-property names over a small set of tiers** — Recliner,
  Gold, Prime, Executive, Superior, Classic, Lounger. Class is an attribute of
  the *physical seat*; the *price* is per show.
- **Front-row recliners invert the price gradient.** The cheapest row by
  geometry is the most expensive by class. Never derive price from row index.
- **Aisles are gaps in the grid, not gaps in the numbering.** Seat 3 and seat 4
  can be separated by a walkway while remaining consecutive numbers.
- **Wheelchair spaces and companion seats are legally protected** (ADA in the
  US) and cannot be sold to non-qualifying parties by default.
- **The single-seat rule is enforced at selection time, not checkout.** You may
  not strand one seat between two occupied ones, or at a row end.
- **A timed cart with a visible countdown**, server-authoritative, silently
  returning inventory on expiry.

> *Schema consequence:* `seats` holds the layout template
> (`row_label`, `row_index`, `seat_number`, `column_index`, `is_aisle`,
> `is_wheelchair_accessible`) once per screen. `show_seats` holds one row per
> seat per show — the thing that gets locked.

---

## 4. Money is messier than it looks

- **Convenience fee is per-ticket, varies by theatre/format/showtime, and is
  non-refundable.** It is a rule, not a constant, and it is disclosed late in
  the funnel on purpose.
- **GST on Indian cinema admission is banded**: 12% at or below ₹100 per ticket,
  18% above. The band is per ticket, not per order — one expensive recliner in
  an otherwise cheap order is taxed at the higher rate.
- **State price caps** are a real regulatory constraint on the pricing engine in
  several Indian states.
- **Cancellation is a per-cinema capability**, surfaced as a facility badge, not
  a global policy. Typical window: 20 minutes to 4 hours before showtime, 50–75%
  of base fare, never the fee.
- **Cancellation is often disabled entirely when an offer was applied** — offer
  abuse control.
- **Subscriptions behave as constrained payment methods**, not discounts: AMC
  A-List consumes a weekly credit; PVR Passport caps you to a seat class and
  excludes premium formats.

> *Schema consequence:* every money field is snapshotted onto the booking at
> purchase time, and the invoice arithmetic is enforced by a CHECK constraint so
> a future pricing change cannot silently mis-charge anyone.

---

## 5. The edge cases that decide whether the design is any good

| Situation | Naive behaviour | What must happen |
|---|---|---|
| Two users click the same seat simultaneously | Both succeed; one shows up to an occupied seat | Exactly one wins, atomically, in the database |
| Hold expires while the user is on the payment page | Money captured, no seat | Hold is extended at payment start; if it still lapses, the payment is auto-refunded |
| Payment webhook arrives twice | Two bookings, or a double charge | Deduplicated on `(gateway, event_id)` |
| Browser says "paid" but the gateway says otherwise | Booking confirmed on a lie | Only the signed webhook moves money state |
| A show is cancelled with bookings in flight | Orphaned bookings | Bulk refund, seats released, bookings revoked |
| A cancelled seat is rebooked | Unique-constraint collision; seat permanently unsellable | Uniqueness is scoped to *live* tickets only |
| Two shows scheduled with overlapping runtimes | Double-booked auditorium | Excluded by a range constraint in the database |
| Midnight show at 00:30 | Listed under the wrong day | `show_date` stored in cinema-local time, separate from the UTC instant |
| DST shift | Every show an hour wrong twice a year | Local wall time + IANA zone → absolute instant, never the reverse |

The last five are the ones this implementation was specifically tested against.

---

## 6. What was deliberately left out

Real platforms carry a lot that adds surface without adding insight for a
learning build: waiting rooms and Smart Queue, rotating SafeTix barcodes,
subscriptions-as-tender, split tender, loyalty points, gift cards, private
hires, in-seat delivery, and multi-tenant syndication.

The parts kept are the ones that are *load-bearing*: inventory, holds, pricing,
payments, refunds, and the scheduling calendar.
