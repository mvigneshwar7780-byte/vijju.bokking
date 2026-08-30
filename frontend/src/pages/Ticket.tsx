import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Bookings } from '@/api/endpoints'
import { ErrorNote, Spinner, Stepper } from '@/components/ui'
import { CancelBooking } from '@/components/CancelBooking'
import { rupees, showDateTime } from '@/lib/format'

/** A deterministic block-pattern stand-in for a scannable code.
 *  The real payload is an HMAC-signed string the API issues; rendering an
 *  actual QR is a library call away, but the signature is what matters. */
function CodeBlock({ payload }: { payload: string }) {
  const cells = Array.from({ length: 144 }, (_, i) => {
    let h = 0
    for (let j = 0; j < payload.length; j++) h = (h * 31 + payload.charCodeAt(j) + i) & 0xffff
    return h % 3 !== 0
  })
  return (
    <div className="mx-auto grid w-40 grid-cols-12 gap-px rounded-lg bg-white p-2">
      {cells.map((on, i) => (
        <span key={i} className={on ? 'aspect-square bg-black' : 'aspect-square bg-white'} />
      ))}
    </div>
  )
}

export function Ticket() {
  const { bookingId = '' } = useParams()
  const { data: booking, isPending, error } = useQuery({
    queryKey: ['booking', bookingId],
    queryFn: () => Bookings.get(bookingId),
  })

  if (isPending) return <Spinner label="Loading ticket" />
  if (error) return <ErrorNote error={error} />
  if (!booking) return null

  return (
    <div className="space-y-6">
      <Stepper step={4} />

      <div className="mx-auto max-w-md space-y-4">
        <div className="card overflow-hidden">
          <div className="border-b border-dashed border-ink-800 bg-emerald-950/20 p-5 text-center">
            <p className="text-sm font-semibold text-emerald-300">Booking confirmed</p>
            <p className="mt-1 font-mono text-2xl font-bold tracking-widest">
              {booking.booking_reference}
            </p>
          </div>

          <div className="space-y-4 p-5">
            <div>
              <h1 className="text-lg font-bold">{booking.show.movie_title}</h1>
              <p className="text-sm text-ink-300">
                {booking.show.cinema_name} · {booking.show.screen_name}
              </p>
              <p className="text-sm text-ink-300">{showDateTime(booking.show.starts_at)}</p>
              <p className="mt-1 text-xs text-ink-500">
                {booking.show.format_code} · {booking.show.language}
              </p>
            </div>

            <div>
              <p className="label">Seats</p>
              <div className="flex flex-wrap gap-1.5">
                {booking.seats.map((s) => (
                  <span key={s.seat_label} className="chip !text-sm !text-ink-100">
                    {s.seat_label}
                  </span>
                ))}
              </div>
            </div>

            {booking.qr_payload && (
              <div className="space-y-2 pt-2">
                <CodeBlock payload={booking.qr_payload} />
                <p className="text-center text-[10px] text-ink-500">
                  Signed ticket — show this at the gate
                </p>
              </div>
            )}

            <div className="flex justify-between border-t border-ink-800 pt-3 text-sm">
              <span className="text-ink-300">Paid</span>
              <span className="font-semibold">{rupees(booking.total_minor)}</span>
            </div>
          </div>
        </div>

        <CancelBooking booking={booking} />

        <div className="flex gap-2">
          <Link to="/bookings" className="btn-ghost flex-1">My bookings</Link>
          <Link to="/" className="btn-primary flex-1">Book another</Link>
        </div>
      </div>
    </div>
  )
}
