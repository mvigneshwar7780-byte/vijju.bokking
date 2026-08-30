import { useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Operator } from '@/api/endpoints'
import { ErrorNote, Spinner } from '@/components/ui'
import { rupees, showDateTime } from '@/lib/format'

type Ctx = { cinemaId: string }

function isoDate(offsetDays = 0): string {
  const d = new Date()
  d.setDate(d.getDate() + offsetDays)
  return d.toISOString().slice(0, 10)
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="card p-4">
      <p className="text-xs uppercase tracking-wide text-ink-500">{label}</p>
      <p className="mt-1 text-xl font-bold tabular-nums">{value}</p>
      {hint && <p className="text-xs text-ink-500">{hint}</p>}
    </div>
  )
}

/** Revenue and occupancy for this cinema. */
export function OperatorReports() {
  const { cinemaId } = useOutletContext<Ctx>()
  const [from, setFrom] = useState(isoDate(-30))
  const [to, setTo] = useState(isoDate(7))
  const [groupBy, setGroupBy] = useState('day')

  const revenue = useQuery({
    queryKey: ['op-revenue', cinemaId, from, to, groupBy],
    queryFn: () => Operator.revenue(cinemaId, from, to, groupBy),
  })
  const occupancy = useQuery({
    queryKey: ['op-occupancy', cinemaId, from, to],
    queryFn: () => Operator.occupancy(cinemaId, from, to),
  })

  if (revenue.isPending) return <Spinner label="Crunching numbers" />
  if (revenue.error) return <ErrorNote error={revenue.error} />

  const t = revenue.data!.totals
  const peak = revenue.data!.rows.reduce(
    (max, r) => Math.max(max, r.gross_minor), 1,
  )

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end gap-3">
        <div><label className="label">From</label>
          <input type="date" className="field w-40" value={from}
            onChange={(e) => setFrom(e.target.value)} /></div>
        <div><label className="label">To</label>
          <input type="date" className="field w-40" value={to}
            onChange={(e) => setTo(e.target.value)} /></div>
        <div><label className="label">Group by</label>
          <select className="field w-32" value={groupBy}
            onChange={(e) => setGroupBy(e.target.value)}>
            {['day', 'movie', 'screen', 'show'].map((g) => (
              <option key={g} value={g}>{g}</option>
            ))}
          </select></div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Net revenue" value={rupees(t.net_minor)}
          hint={`${rupees(t.gross_minor, { compact: true })} gross`} />
        <Stat label="Tickets" value={String(t.tickets)}
          hint={`${t.bookings} booking(s)`} />
        <Stat label="Refunded" value={rupees(t.refunded_minor)}
          hint={t.gross_minor ? `${Math.round(100 * t.refunded_minor / t.gross_minor)}% of gross` : undefined} />
        <Stat label="Occupancy"
          value={`${occupancy.data?.average_occupancy_percent ?? 0}%`}
          hint={occupancy.data
            ? `${occupancy.data.booked_seats} of ${occupancy.data.total_seats} seats`
            : undefined} />
      </div>

      <section className="card p-4">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-300">
          Revenue by {groupBy}
        </h2>
        {revenue.data!.rows.length === 0 ? (
          <p className="text-sm text-ink-500">No sales in this range.</p>
        ) : (
          <div className="space-y-2">
            {revenue.data!.rows.map((row) => (
              <div key={row.bucket} className="space-y-1">
                <div className="flex justify-between text-sm">
                  <span className="truncate pr-3 text-ink-300">{row.bucket}</span>
                  <span className="shrink-0 tabular-nums">
                    {rupees(row.net_minor)}
                    <span className="ml-2 text-xs text-ink-500">
                      {row.tickets} tkt
                    </span>
                  </span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-ink-850">
                  <div className="h-full rounded-full bg-brand-500"
                    style={{ width: `${Math.max(2, (row.gross_minor / peak) * 100)}%` }} />
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {occupancy.data && occupancy.data.rows.length > 0 && (
        <section className="card p-4">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-300">
            Occupancy by show
          </h2>
          <div className="space-y-2">
            {occupancy.data.rows.slice(0, 20).map((row) => (
              <div key={row.show_id} className="flex items-center gap-3 text-sm">
                <span className="w-40 shrink-0 truncate text-ink-300">
                  {row.movie_title}
                </span>
                <span className="w-36 shrink-0 text-xs text-ink-500">
                  {showDateTime(row.starts_at)}
                </span>
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-ink-850">
                  <div className="h-full rounded-full bg-emerald-500"
                    style={{ width: `${row.occupancy_percent}%` }} />
                </div>
                <span className="w-24 shrink-0 text-right text-xs tabular-nums">
                  {row.booked_seats}/{row.total_seats} · {row.occupancy_percent}%
                </span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
