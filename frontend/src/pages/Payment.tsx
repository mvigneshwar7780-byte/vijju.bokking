import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { Bookings, PaymentActions, Payments } from '@/api/endpoints'
import { HoldTimer } from '@/components/HoldTimer'
import { ErrorNote, Spinner, Stepper } from '@/components/ui'
import { rupees } from '@/lib/format'

type Outcome = 'success' | 'failure' | 'cancel' | 'pending'

const METHODS = [
  { id: 'upi', label: 'UPI', hint: 'Pay by VPA' },
  { id: 'card', label: 'Card', hint: 'Credit or debit' },
  { id: 'netbanking', label: 'Net banking', hint: 'All major banks' },
  { id: 'wallet', label: 'Wallet', hint: 'Prepaid balance' },
]

export function Payment() {
  const { bookingId = '' } = useParams()
  const navigate = useNavigate()
  const [method, setMethod] = useState('upi')

  const bookingQuery = useQuery({
    queryKey: ['booking', bookingId],
    queryFn: () => Bookings.get(bookingId),
  })

  /**
   * The two-step simulation deliberately mirrors a real PSP:
   *   1. `start` creates a server-side order (the amount is fixed there).
   *   2. `completeMock` stands in for the hosted checkout page; the gateway
   *      then posts a *signed webhook* back to the API, and that webhook — not
   *      this browser — is what confirms the booking.
   * So the UI never reports success on its own; it re-reads the booking.
   */
  const [pendingOrder, setPendingOrder] = useState<string | null>(null)

  const pay = useMutation({
    mutationFn: async (outcome: Outcome) => {
      const order = await Payments.start(bookingId, method)
      const result = await Payments.completeMock(
        order.gateway_order_id,
        // The mock endpoint takes the outcome verbatim; 'cancel' and 'pending'
        // are as real as success and failure.
        outcome as 'success' | 'failure',
        method,
      )
      return { result, orderId: order.gateway_order_id }
    },
    onSuccess: async ({ result, orderId }) => {
      if (result.status === 'pending') setPendingOrder(orderId)
      const booking = await Bookings.get(bookingId)
      if (booking.status === 'confirmed') navigate(`/tickets/${booking.id}`)
      else void bookingQuery.refetch()
    },
  })

  /** Resolve a UPI-style collect request that was left awaiting approval. */
  const settle = useMutation({
    mutationFn: (outcome: 'success' | 'failure') =>
      PaymentActions.settleMock(pendingOrder!, outcome),
    onSuccess: async () => {
      setPendingOrder(null)
      const booking = await Bookings.get(bookingId)
      if (booking.status === 'confirmed') navigate(`/tickets/${booking.id}`)
      else void bookingQuery.refetch()
    },
  })

  /** Abandon checkout without losing the seats. */
  const abandon = useMutation({
    mutationFn: () => PaymentActions.cancel(bookingId),
    onSuccess: () => void bookingQuery.refetch(),
  })

  if (bookingQuery.isPending) return <Spinner label="Loading booking" />
  if (bookingQuery.error) return <ErrorNote error={bookingQuery.error} />
  const booking = bookingQuery.data!

  if (booking.status === 'confirmed') {
    navigate(`/tickets/${booking.id}`, { replace: true })
    return null
  }

  const failed = booking.status === 'payment_failed'
  const pending = booking.status === 'payment_pending' && Boolean(pendingOrder)
  const dead = booking.status === 'expired' || booking.status === 'cancelled'

  return (
    <div className="space-y-6">
      <Stepper step={3} />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Payment</h1>
          <p className="text-sm text-ink-500">
            {booking.show.movie_title} · {booking.seats.map((s) => s.seat_label).join(', ')}
          </p>
        </div>
        {booking.payment_deadline_at && !dead && (
          <HoldTimer expiresAt={booking.payment_deadline_at} />
        )}
      </div>

      {dead && (
        <div className="card space-y-4 p-8 text-center">
          <h2 className="font-semibold">This booking is no longer payable</h2>
          <p className="text-sm text-ink-300">
            The seat hold lapsed and the seats went back on sale. Nothing was charged.
          </p>
          <button className="btn-primary mx-auto" onClick={() => navigate('/')}>
            Start again
          </button>
        </div>
      )}

      {!dead && (
        <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
          <section className="card p-4">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-300">
              Payment method
            </h2>
            <div className="grid gap-2 sm:grid-cols-2">
              {METHODS.map((m) => (
                <button
                  key={m.id}
                  onClick={() => setMethod(m.id)}
                  className={clsx(
                    'rounded-lg border p-3 text-left transition-colors',
                    method === m.id
                      ? 'border-brand-500 bg-brand-500/10'
                      : 'border-ink-800 hover:border-ink-700',
                  )}
                >
                  <div className="text-sm font-medium">{m.label}</div>
                  <div className="text-xs text-ink-500">{m.hint}</div>
                </button>
              ))}
            </div>

            {failed && (
              <div className="mt-4 card border-red-900/60 bg-red-950/30 p-3 text-sm text-red-200">
                Your bank declined that payment and the seats were released.
                Start a new booking to try again.
              </div>
            )}

            {abandon.data?.status === 'cancelled' && (
              <div className="mt-4 card border-ink-700 p-3 text-sm text-ink-300">
                {abandon.data.retryable
                  ? 'Payment cancelled. Your seats are still held — pay again whenever you are ready.'
                  : 'Payment cancelled, and the seat hold had already expired.'}
              </div>
            )}

            {pending && pendingOrder && (
              <div className="mt-4 card border-amber-900/60 bg-amber-950/30 p-3">
                <p className="text-sm text-amber-200">
                  Waiting for you to approve the request in your UPI app. Your
                  seats stay held until it resolves.
                </p>
                <div className="mt-2 flex gap-2">
                  <button className="btn-ghost !py-1.5 !text-xs"
                    disabled={settle.isPending}
                    onClick={() => settle.mutate('success')}>
                    Simulate approval
                  </button>
                  <button className="btn-ghost !py-1.5 !text-xs"
                    disabled={settle.isPending}
                    onClick={() => settle.mutate('failure')}>
                    Simulate rejection
                  </button>
                </div>
              </div>
            )}

            <div className="mt-6 space-y-2">
              <button
                className="btn-primary w-full"
                disabled={pay.isPending || failed || pending}
                onClick={() => pay.mutate('success')}
              >
                {pay.isPending ? 'Contacting gateway…' : `Pay ${rupees(booking.total_minor)}`}
              </button>

              {/* The mock gateway can produce every outcome a real one does, so
                  each unhappy path is reachable deliberately rather than by
                  waiting for a real decline. */}
              <div className="grid grid-cols-3 gap-2">
                {([
                  ['failure', 'Decline'],
                  ['cancel', 'Cancel'],
                  ['pending', 'Pending'],
                ] as [Outcome, string][]).map(([outcome, label]) => (
                  <button
                    key={outcome}
                    className="btn-ghost !py-1.5 !text-[11px]"
                    disabled={pay.isPending || failed || pending}
                    onClick={() => pay.mutate(outcome)}
                  >
                    Simulate {label}
                  </button>
                ))}
              </div>

              <button
                className="btn-ghost w-full !text-xs"
                disabled={abandon.isPending}
                onClick={() => abandon.mutate()}
              >
                {abandon.isPending ? 'Cancelling…' : 'Cancel payment and keep my seats'}
              </button>
            </div>

            {pay.error && <div className="mt-3"><ErrorNote error={pay.error} /></div>}
          </section>

          <aside className="card h-fit p-4">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-300">
              Order summary
            </h2>
            <dl className="space-y-2 text-sm">
              <div className="flex justify-between"><dt className="text-ink-300">Tickets</dt>
                <dd>{rupees(booking.ticket_subtotal_minor)}</dd></div>
              {booking.discount_minor > 0 && (
                <div className="flex justify-between text-emerald-300">
                  <dt>Offer {booking.offer_code}</dt>
                  <dd>−{rupees(booking.discount_minor)}</dd>
                </div>
              )}
              <div className="flex justify-between"><dt className="text-ink-300">Convenience fee</dt>
                <dd>{rupees(booking.convenience_fee_minor)}</dd></div>
              <div className="flex justify-between"><dt className="text-ink-300">GST</dt>
                <dd>{rupees(booking.tax_minor)}</dd></div>
            </dl>
            <div className="mt-3 flex justify-between border-t border-ink-800 pt-3 font-semibold">
              <span>Total</span><span>{rupees(booking.total_minor)}</span>
            </div>
            <p className="mt-3 text-[11px] text-ink-500">
              Reference {booking.booking_reference}
            </p>
          </aside>
        </div>
      )}
    </div>
  )
}
