import { useOutletContext } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { Operator } from '@/api/endpoints'
import { Empty, ErrorNote, Spinner } from '@/components/ui'
import { rupees, showDateTime } from '@/lib/format'

type Ctx = { cinemaId: string }

const TONE: Record<string, string> = {
  confirmed: 'border-emerald-800 text-emerald-300',
  payment_pending: 'border-amber-800 text-amber-300',
  payment_failed: 'border-red-900 text-red-300',
  cancelled: 'border-ink-700 text-ink-500',
  revoked: 'border-red-900 text-red-300',
  refunded: 'border-sky-900 text-sky-300',
}

/** Every booking made at this cinema. */
export function OperatorBookings() {
  const { cinemaId } = useOutletContext<Ctx>()
  const { data, isPending, error, refetch } = useQuery({
    queryKey: ['op-bookings', cinemaId],
    queryFn: () => Operator.bookings(cinemaId),
  })

  if (isPending) return <Spinner label="Loading bookings" />
  if (error) return <ErrorNote error={error} onRetry={() => void refetch()} />
  if (!data || data.items.length === 0) {
    return <Empty title="No bookings yet" hint="They appear here as customers buy." />
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-ink-500">{data.total} booking(s)</p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[42rem] text-sm">
          <thead className="text-left text-xs uppercase tracking-wide text-ink-500">
            <tr className="border-b border-ink-800">
              <th className="py-2 pr-3">Reference</th>
              <th className="py-2 pr-3">Show</th>
              <th className="py-2 pr-3">Seats</th>
              <th className="py-2 pr-3">Customer</th>
              <th className="py-2 pr-3 text-right">Total</th>
              <th className="py-2">Status</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((b) => (
              <tr key={b.id} className="border-b border-ink-850">
                <td className="py-2.5 pr-3 font-mono text-xs">{b.booking_reference}</td>
                <td className="py-2.5 pr-3">
                  <div className="font-medium">{b.movie_title}</div>
                  <div className="text-xs text-ink-500">
                    {b.screen_name} · {showDateTime(b.starts_at)}
                  </div>
                </td>
                <td className="py-2.5 pr-3 text-xs">{b.seat_labels.join(', ')}</td>
                <td className="py-2.5 pr-3 text-xs text-ink-300">{b.contact_email}</td>
                <td className="py-2.5 pr-3 text-right font-medium">
                  {rupees(b.total_minor)}
                </td>
                <td className="py-2.5">
                  <span className={clsx('chip', TONE[b.status])}>
                    {b.status.replace(/_/g, ' ')}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
