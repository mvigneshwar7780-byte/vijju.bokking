import { Link } from 'react-router-dom'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { Bookings } from '@/api/endpoints'
import { useSession } from '@/store/session'
import { Empty, ErrorNote, Spinner } from '@/components/ui'
import { CancelBooking } from '@/components/CancelBooking'
import { rupees, showDateTime } from '@/lib/format'
import type { Booking, BookingStatus } from '@/api/types'

const STATUS_TONE: Record<BookingStatus, string> = {
  confirmed: 'border-emerald-800 text-emerald-300',
  draft: 'border-ink-700 text-ink-300',
  payment_pending: 'border-amber-800 text-amber-300',
  payment_failed: 'border-red-900 text-red-300',
  expired: 'border-ink-700 text-ink-500',
  cancelled: 'border-ink-700 text-ink-500',
  refunded: 'border-sky-900 text-sky-300',
  revoked: 'border-red-900 text-red-300',
}

function BookingRow({ booking }: { booking: Booking }) {
  const [showCancel, setShowCancel] = useState(false)

  return (
    <article className="card p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h2 className="truncate font-semibold">{booking.show.movie_title}</h2>
            <span className={clsx('chip', STATUS_TONE[booking.status])}>
              {booking.status.replace(/_/g, ' ')}
            </span>
          </div>
          <p className="mt-0.5 text-sm text-ink-300">
            {booking.show.cinema_name} · {booking.show.screen_name}
          </p>
          <p className="text-sm text-ink-500">{showDateTime(booking.show.starts_at)}</p>
          <p className="mt-1 text-xs text-ink-500">
            {booking.seats.map((s) => s.seat_label).join(', ')} ·{' '}
            <span className="font-mono">{booking.booking_reference}</span>
          </p>
        </div>

        <div className="text-right">
          <p className="font-semibold">{rupees(booking.total_minor)}</p>
          <div className="mt-2 flex flex-col items-end gap-1.5">
            {booking.status === 'confirmed' && (
              <Link to={`/tickets/${booking.id}`} className="btn-ghost !py-1.5 !text-xs">
                View ticket
              </Link>
            )}
            {booking.status === 'draft' && (
              <Link to={`/pay/${booking.id}`} className="btn-primary !py-1.5 !text-xs">
                Complete payment
              </Link>
            )}
            {booking.status === 'confirmed' && booking.cancellation?.refundable && (
              <button
                className="btn-ghost !py-1.5 !text-xs"
                onClick={() => setShowCancel((v) => !v)}
              >
                {showCancel ? 'Close' : `Cancel · refund ${rupees(booking.cancellation.refund_minor)}`}
              </button>
            )}
            {booking.refunded_minor > 0 && (
              <span className="text-[11px] text-sky-300">
                {rupees(booking.refunded_minor)} refunded
              </span>
            )}
          </div>
        </div>
      </div>
      {(showCancel || booking.refunds.length > 0) && (
        <div className="mt-3">
          <CancelBooking booking={booking} />
        </div>
      )}
    </article>
  )
}

export function MyBookings() {
  const { user } = useSession()
  const { data, isPending, error, refetch } = useQuery({
    queryKey: ['my-bookings'],
    queryFn: () => Bookings.mine(),
    enabled: Boolean(user),
  })

  if (!user) {
    return (
      <Empty title="Sign in to see your bookings" hint="Your tickets are tied to your account." />
    )
  }
  if (isPending) return <Spinner label="Loading bookings" />
  if (error) return <ErrorNote error={error} onRetry={() => void refetch()} />

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold tracking-tight">My bookings</h1>
      {data && data.items.length === 0 ? (
        <Empty title="No bookings yet" hint="Pick a film and grab some seats." />
      ) : (
        <div className="space-y-3">
          {data?.items.map((b) => <BookingRow key={b.id} booking={b} />)}
        </div>
      )}
    </div>
  )
}
