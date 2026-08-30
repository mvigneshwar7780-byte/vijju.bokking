import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { Browse } from '@/api/endpoints'
import { Empty, Spinner } from '@/components/ui'
import { dayLabel, rupees, showTime } from '@/lib/format'

/**
 * "Where can I watch this, and what will it cost?"
 *
 * This view only exists because a movie has no price of its own — the amount
 * comes from cinema → screen → show → seat category, so three halls can charge
 * three different amounts for the same film on the same evening. The bar makes
 * that spread visible rather than making the reader compare numbers.
 */
export function PriceComparison({ movieId, cityId }: { movieId: string; cityId: string }) {
  const [date, setDate] = useState<string | undefined>()

  const { data, isPending } = useQuery({
    queryKey: ['price-comparison', movieId, cityId, date],
    queryFn: () => Browse.cinemasForMovie(movieId, cityId, date),
  })

  if (isPending) return <Spinner label="Comparing cinemas" />
  if (!data) return null
  if (data.cinemas.length === 0) {
    return <Empty title="Not playing here right now" hint="Try another date or city." />
  }

  const cheapest = data.cheapest_minor ?? 0
  const dearest = data.dearest_minor ?? cheapest
  const span = Math.max(dearest - cheapest, 1)

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold">Where to watch</h2>
          <p className="text-sm text-ink-500">
            {data.cinemas.length} cinema{data.cinemas.length > 1 ? 's' : ''} in{' '}
            {data.city_name} · cheapest first
          </p>
        </div>
        {data.cheapest_minor != null && (
          <p className="text-sm text-ink-300">
            From <span className="font-semibold">{rupees(data.cheapest_minor, { compact: true })}</span>
            {data.dearest_minor !== data.cheapest_minor && (
              <> to {rupees(data.dearest_minor!, { compact: true })}</>
            )}
          </p>
        )}
      </div>

      {data.available_dates.length > 1 && (
        <div className="flex gap-2 overflow-x-auto pb-1">
          {data.available_dates.map((d) => {
            const { weekday, day, month } = dayLabel(d)
            const active = d === data.show_date
            return (
              <button
                key={d}
                onClick={() => setDate(d)}
                className={clsx(
                  'flex w-14 shrink-0 flex-col items-center rounded-lg border py-1.5 transition-colors',
                  active
                    ? 'border-brand-500 bg-brand-500 text-white'
                    : 'border-ink-800 text-ink-300 hover:border-ink-700',
                )}
              >
                <span className="text-[10px]">{weekday}</span>
                <span className="text-base font-bold leading-none">{day}</span>
                <span className="text-[9px]">{month}</span>
              </button>
            )
          })}
        </div>
      )}

      <ol className="space-y-2">
        {data.cinemas.map((cinema, index) => {
          const share = (cinema.min_price_minor - cheapest) / span
          return (
            <li key={cinema.cinema_id} className="card p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <Link
                      to={`/cinemas/${cinema.cinema_id}`}
                      className="truncate font-semibold hover:text-brand-400"
                    >
                      {cinema.cinema_name}
                    </Link>
                    {index === 0 && data.cinemas.length > 1 && (
                      <span className="chip border-emerald-800 text-emerald-300">
                        Cheapest
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-ink-500">
                    {cinema.locality} · {cinema.show_count} show
                    {cinema.show_count > 1 ? 's' : ''} from{' '}
                    {showTime(cinema.earliest_show_at)} ·{' '}
                    {cinema.total_available_seats} seats free
                  </p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {cinema.formats.map((f) => <span key={f} className="chip">{f}</span>)}
                    {cinema.languages.slice(0, 2).map((l) => (
                      <span key={l} className="chip">{l}</span>
                    ))}
                  </div>
                </div>

                <div className="text-right">
                  <p className="text-lg font-bold">
                    {rupees(cinema.min_price_minor, { compact: true })}
                  </p>
                  <p className="text-[11px] text-ink-500">
                    up to {rupees(cinema.max_price_minor, { compact: true })}
                  </p>
                </div>
              </div>

              {/* Relative position between the cheapest and dearest hall. */}
              <div className="mt-3 h-1 overflow-hidden rounded-full bg-ink-850">
                <div
                  className={clsx(
                    'h-full rounded-full',
                    index === 0 ? 'bg-emerald-500' : 'bg-brand-500',
                  )}
                  style={{ width: `${Math.max(8, 8 + share * 92)}%` }}
                />
              </div>

              <Link
                to={`/movies/${movieId}/showtimes`}
                className="btn-ghost mt-3 !py-1.5 !text-xs"
              >
                Pick a showtime
              </Link>
            </li>
          )
        })}
      </ol>
    </section>
  )
}
