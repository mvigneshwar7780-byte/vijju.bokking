import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Bookings, Seats, Showtimes } from '@/api/endpoints'
import { ApiClientError, newIdempotencyKey } from '@/api/client'
import { useSession } from '@/store/session'
import { HoldTimer } from '@/components/HoldTimer'
import { cancelHoldRelease, scheduleHoldRelease } from '@/lib/holdRelease'
import { ErrorNote, Spinner, Stepper } from '@/components/ui'
import { rupees } from '@/lib/format'

export function Checkout() {
  const { holdId = '' } = useParams()
  const navigate = useNavigate()
  const { user } = useSession()

  const [offerCode, setOfferCode] = useState('')
  const [appliedOffer, setAppliedOffer] = useState<string | null>(null)
  // Contact details default to the signed-in user's, but are owned by the
  // field the moment the customer types.
  //
  // This has to be *derived*, not seeded with `useState(user?.email)`: the
  // session hydrates asynchronously, so `user` is still null on first render
  // and a seeded value would be captured as '' and never updated. That is what
  // left "Proceed to payment" permanently disabled behind its `!email` guard.
  // Holding the edit separately keeps it correct without an effect and without
  // a later auth refresh overwriting what was typed.
  const [emailEdit, setEmailEdit] = useState<string | null>(null)
  const [phoneEdit, setPhoneEdit] = useState<string | null>(null)
  const email = emailEdit ?? user?.email ?? ''
  const phone = phoneEdit ?? user?.phone ?? ''
  const [expired, setExpired] = useState(false)

  // One key per checkout attempt, generated once. Regenerating it on re-render
  // would defeat the point: a double-submit would create two bookings.
  const idempotencyKey = useMemo(() => newIdempotencyKey(), [])

  /**
   * Give the seats back when the customer leaves without paying.
   *
   * The release is *scheduled*, not immediate. React StrictMode mounts,
   * unmounts and remounts every component in development, so an immediate
   * release in cleanup fires on page load and hands the seats back while the
   * customer is still looking at them. Mounting cancels any release queued by
   * the previous (possibly simulated) unmount.
   *
   * `proceeded` guards the happy path, and a hold the customer explicitly kept
   * is left alone -- the server also ignores an "abandoned" release for those,
   * so this is belt and braces rather than the actual rule.
   */
  const proceeded = useRef(false)
  const keptRef = useRef(false)

  useEffect(() => {
    if (!holdId) return
    cancelHoldRelease(holdId)

    const onUnload = () => {
      if (!proceeded.current && !keptRef.current) Seats.releaseBeacon(holdId)
    }
    window.addEventListener('pagehide', onUnload)
    return () => {
      window.removeEventListener('pagehide', onUnload)
      if (!proceeded.current && !keptRef.current) scheduleHoldRelease(holdId)
    }
  }, [holdId])

  const holdQuery = useQuery({
    queryKey: ['hold', holdId],
    queryFn: () => Seats.getHold(holdId),
    retry: false,
  })

  const keep = useMutation({
    mutationFn: () => Seats.keep(holdId),
    onSuccess: () => {
      keptRef.current = true
      void holdQuery.refetch()
    },
  })

  const releaseAndGoBack = useCallback(() => {
    proceeded.current = true // stop the unmount handler double-releasing
    void Seats.release(holdId, 'explicit').finally(() => {
      navigate(`/shows/${holdQuery.data?.show_id ?? ''}/seats`)
    })
  }, [holdId, holdQuery.data?.show_id, navigate])

  const showQuery = useQuery({
    queryKey: ['show', holdQuery.data?.show_id],
    queryFn: () => Showtimes.show(holdQuery.data!.show_id),
    enabled: Boolean(holdQuery.data?.show_id),
  })

  const quoteQuery = useQuery({
    queryKey: ['quote', holdId, appliedOffer],
    queryFn: () => Bookings.quote({ hold_id: holdId, offer_code: appliedOffer }),
    enabled: Boolean(holdQuery.data),
  })

  const create = useMutation({
    mutationFn: () =>
      Bookings.create(
        {
          hold_id: holdId,
          contact_email: email,
          contact_phone: phone || null,
          offer_code: appliedOffer,
        },
        idempotencyKey,
      ),
    onSuccess: (booking) => {
      proceeded.current = true
      cancelHoldRelease(holdId)
      navigate(`/pay/${booking.id}`)
    },
  })

  if (holdQuery.isPending) return <Spinner label="Loading your selection" />
  if (holdQuery.error) {
    return (
      <div className="space-y-4">
        <ErrorNote error={holdQuery.error} />
        <button className="btn-ghost" onClick={() => navigate('/')}>Start over</button>
      </div>
    )
  }

  const hold = holdQuery.data!
  const quote = quoteQuery.data
  const show = showQuery.data

  // The countdown runs off a timestamp fetched when the page loaded. If the
  // hold dies for any other reason -- released elsewhere, swept, taken over --
  // the quote is the first thing to notice. Trust it over the clock.
  // (A failure loading the hold itself is already handled above.)
  const holdGone =
    quoteQuery.error instanceof ApiClientError &&
    ['HOLD_EXPIRED', 'NOT_FOUND', 'FORBIDDEN'].includes(quoteQuery.error.code)

  if (expired || holdGone) {
    return (
      <div className="card space-y-4 p-8 text-center">
        <h1 className="text-lg font-semibold">Your seat hold expired</h1>
        <p className="text-sm text-ink-300">
          Seats are released after a few minutes so other people can book them.
          Nothing was charged.
        </p>
        <button className="btn-primary mx-auto" onClick={() => navigate(`/shows/${hold.show_id}/seats`)}>
          Choose seats again
        </button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <Stepper step={2} />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Review your booking</h1>
          {show && (
            <p className="text-sm text-ink-500">
              {String(show.movie_title)} · {String(show.cinema_name)} · {String(show.screen_name)}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <HoldTimer expiresAt={hold.expires_at} onExpire={() => setExpired(true)} />
          {hold.is_kept ? (
            <span className="chip border-emerald-800 text-emerald-300">
              Seats held
            </span>
          ) : (
            <button
              className="btn-ghost !py-1.5 !text-xs"
              disabled={keep.isPending}
              onClick={() => keep.mutate()}
              title="Hold these seats for longer while you decide"
            >
              {keep.isPending ? 'Holding…' : 'Keep seats on hold'}
            </button>
          )}
        </div>
      </div>

      {!hold.is_kept && (
        <p className="text-xs text-ink-500">
          Your seats are reserved briefly while you check out. Leave this page and
          they go back on sale straight away — press <em>Keep seats on hold</em> if
          you need more time.
        </p>
      )}

      <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
        <div className="space-y-4">
          <section className="card p-4">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-300">
              Seats
            </h2>
            <div className="flex flex-wrap gap-2">
              {hold.seat_labels.map((label) => (
                <span key={label} className="rounded-lg border border-ink-700 bg-ink-850 px-3 py-1.5 text-sm font-medium">
                  {label}
                </span>
              ))}
            </div>
          </section>

          <section className="card p-4">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-300">
              Contact details
            </h2>
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label className="label" htmlFor="email">Email for the ticket</label>
                <input
                  id="email" type="email" className="field" value={email}
                  onChange={(e) => setEmailEdit(e.target.value)}
                  placeholder="you@example.com"
                />
              </div>
              <div>
                <label className="label" htmlFor="phone">Phone (optional)</label>
                <input
                  id="phone" className="field" value={phone}
                  onChange={(e) => setPhoneEdit(e.target.value)} placeholder="+91…"
                />
              </div>
            </div>
          </section>

          <section className="card p-4">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-300">
              Offer code
            </h2>
            <div className="flex gap-2">
              <input
                className="field" placeholder="e.g. FIRSTSHOW"
                value={offerCode}
                onChange={(e) => setOfferCode(e.target.value.toUpperCase())}
              />
              <button
                className="btn-ghost shrink-0"
                onClick={() => setAppliedOffer(offerCode.trim() || null)}
              >
                Apply
              </button>
            </div>
            {quote?.offer_error && (
              <p className="mt-2 text-xs text-amber-300">{quote.offer_error}</p>
            )}
            {quote?.offer_code && !quote.offer_error && (
              <p className="mt-2 text-xs text-emerald-300">
                {quote.offer_label} applied — you save {rupees(quote.discount_minor)}
              </p>
            )}
          </section>
        </div>

        <aside className="space-y-4">
          <section className="card p-4">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-300">
              Price breakdown
            </h2>
            {quoteQuery.isPending && <p className="text-sm text-ink-500">Calculating…</p>}
            {quoteQuery.error != null && !holdGone && (
              <ErrorNote error={quoteQuery.error} onRetry={() => void quoteQuery.refetch()} />
            )}
            {quote && (
              <>
                <dl className="space-y-2 text-sm">
                  {quote.lines.map((line) => (
                    <div key={line.label} className="flex justify-between gap-4">
                      <dt className={line.kind === 'discount' ? 'text-emerald-300' : 'text-ink-300'}>
                        {line.label}
                      </dt>
                      <dd className={line.kind === 'discount' ? 'text-emerald-300' : ''}>
                        {rupees(line.amount_minor)}
                      </dd>
                    </div>
                  ))}
                </dl>
                <div className="mt-3 flex justify-between border-t border-ink-800 pt-3 font-semibold">
                  <span>Total payable</span>
                  <span>{rupees(quote.total_minor)}</span>
                </div>
              </>
            )}
          </section>

          {create.error && <ErrorNote error={create.error} />}

          <button
            className="btn-primary w-full"
            disabled={!email || !quote || create.isPending}
            onClick={() => create.mutate()}
          >
            {create.isPending ? 'Creating booking…' : 'Proceed to payment'}
          </button>
          {!email && (
            <p className="text-center text-[11px] text-amber-300">
              Add an email address above — that is where your ticket is sent.
            </p>
          )}
          <button
            className="btn-ghost w-full !py-1.5 !text-xs"
            onClick={releaseAndGoBack}
          >
            Change seats
          </button>
          <p className="text-center text-[11px] text-ink-500">
            Payments are simulated — no real card is charged.
          </p>
        </aside>
      </div>
    </div>
  )
}
