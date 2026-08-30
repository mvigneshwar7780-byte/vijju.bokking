import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Bookings } from '@/api/endpoints'
import { ErrorNote } from '@/components/ui'
import { rupees } from '@/lib/format'
import type { Booking } from '@/api/types'

/**
 * Cancel a ticket, with the refund stated before the customer commits.
 *
 * The amount comes from the server's own quote rather than being recomputed
 * here — a client that does its own refund arithmetic will eventually disagree
 * with the ledger, and the customer will believe the client.
 */
export function CancelBooking({ booking }: { booking: Booking }) {
  const qc = useQueryClient()
  const [confirming, setConfirming] = useState(false)
  const [reason, setReason] = useState('')

  const cancel = useMutation({
    mutationFn: () => Bookings.cancel(booking.id, reason || 'Cancelled by customer'),
    onSuccess: () => {
      setConfirming(false)
      void qc.invalidateQueries({ queryKey: ['booking', booking.id] })
      void qc.invalidateQueries({ queryKey: ['my-bookings'] })
    },
  })

  // Already cancelled: show what came back instead of offering to cancel again.
  if (booking.refunds.length > 0) {
    const settled = booking.refunds.filter((r) => r.status === 'succeeded')
    const pending = booking.refunds.filter((r) => r.status === 'pending')
    return (
      <div className="card border-sky-900/50 bg-sky-950/20 p-4">
        <h3 className="text-sm font-semibold text-sky-200">Refund</h3>
        {settled.length > 0 && (
          <p className="mt-1 text-sm text-sky-100">
            {rupees(booking.refunded_minor)} refunded to your original payment
            method.
          </p>
        )}
        {pending.length > 0 && (
          <p className="mt-1 text-sm text-amber-200">
            {rupees(pending.reduce((n, r) => n + r.amount_minor, 0))} is being
            processed. Bank refunds usually take 5–7 working days.
          </p>
        )}
        <p className="mt-2 text-xs text-ink-500">
          Of {rupees(booking.total_minor)} paid,{' '}
          {rupees(booking.total_minor - booking.refunded_minor)} was retained.
        </p>
      </div>
    )
  }

  const quote = booking.cancellation
  if (booking.status !== 'confirmed' || !quote) return null

  if (!quote.refundable) {
    return (
      <div className="card p-4">
        <h3 className="text-sm font-semibold">Cancellation</h3>
        <p className="mt-1 text-sm text-ink-300">{quote.reason}</p>
      </div>
    )
  }

  return (
    <div className="card p-4">
      <h3 className="text-sm font-semibold">Cancel this booking</h3>
      <p className="mt-1 text-sm text-ink-300">{quote.reason}</p>

      <dl className="mt-3 space-y-1 text-sm">
        <div className="flex justify-between">
          <dt className="text-ink-500">You paid</dt>
          <dd>{rupees(booking.total_minor)}</dd>
        </div>
        <div className="flex justify-between text-emerald-300">
          <dt>Refund</dt>
          <dd>{rupees(quote.refund_minor)}</dd>
        </div>
        <div className="flex justify-between text-ink-500">
          <dt>Retained</dt>
          <dd>{rupees(quote.forfeited_minor)}</dd>
        </div>
      </dl>

      {!confirming ? (
        <button className="btn-ghost mt-3 w-full !text-xs" onClick={() => setConfirming(true)}>
          Cancel booking
        </button>
      ) : (
        <div className="mt-3 space-y-2">
          <input
            className="field"
            placeholder="Reason (optional)"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <div className="flex gap-2">
            <button
              className="btn-ghost flex-1 !text-xs"
              onClick={() => setConfirming(false)}
              disabled={cancel.isPending}
            >
              Keep my tickets
            </button>
            <button
              className="btn-primary flex-1 !text-xs"
              onClick={() => cancel.mutate()}
              disabled={cancel.isPending}
            >
              {cancel.isPending
                ? 'Cancelling…'
                : `Confirm · refund ${rupees(quote.refund_minor)}`}
            </button>
          </div>
        </div>
      )}
      {cancel.error && <div className="mt-2"><ErrorNote error={cancel.error} /></div>}
    </div>
  )
}
